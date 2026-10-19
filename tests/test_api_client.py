# Copyright 2026 MSPbots.ai
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Request shapes, envelopes and tool behaviour against a mocked Kaseya BMS API."""

import json

import httpx
import pytest

from kaseya_bms_mcp import api_client
from kaseya_bms_mcp.api_client import BmsClient, BmsCredentials, BmsError
from kaseya_bms_mcp.server import _credentials_var, create_mcp_server

CREDS = BmsCredentials("us", "tok-123", "api")


def ok(value, **extra):
    return {"Success": True, "Error": None, "Result": value} | extra


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def instant(_seconds):
        return None

    monkeypatch.setattr(api_client.asyncio, "sleep", instant)


class Recorder:
    """Mock transport: replies by method + path (without the leading slash)."""

    def __init__(self, routes=None, default=None):
        self.requests: list[httpx.Request] = []
        self.routes = routes or {}
        self.default = default if default is not None else ok([])

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path.lstrip("/")
        reply = self.routes.get(f"{request.method} {path}", self.routes.get(path, self.default))
        if callable(reply):
            return reply(request)
        return httpx.Response(200, json=reply)

    def calls(self, path: str, method: str | None = None) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path == f"/{path}" and (method is None or r.method == method)]


def body(request: httpx.Request):
    return json.loads(request.content) if request.content else None


async def _call(monkeypatch, recorder: Recorder, tool: str, args: dict):
    http = httpx.AsyncClient(transport=httpx.MockTransport(recorder))
    monkeypatch.setattr(api_client, "_get_shared_http_client", lambda: http)
    ctx = _credentials_var.set(CREDS)
    try:
        content, _ = await create_mcp_server().call_tool(tool, args)
    finally:
        _credentials_var.reset(ctx)
    return json.loads(content[0].text)


def _client(recorder: Recorder) -> BmsClient:
    return BmsClient(CREDS, httpx.AsyncClient(transport=httpx.MockTransport(recorder)))


# ---- client ----------------------------------------------------------------


async def test_bearer_token_and_region_host():
    rec = Recorder()
    await _client(rec).get("v2/servicedesk/tickets", {"PageSize": 1})
    request = rec.requests[0]
    assert request.headers["authorization"] == "Bearer tok-123"
    assert str(request.url) == "https://api.bms.kaseya.com/v2/servicedesk/tickets?PageSize=1"


async def test_security_error_is_unauthorized(monkeypatch):
    error = {"success": False, "error": {"code": 978001, "message": "Security Error", "details": " 978001 : An error occured."}}
    rec = Recorder({"v2/servicedesk/tickets": lambda r: httpx.Response(401, json=error)})
    result = await _call(monkeypatch, rec, "kaseya_bms_list_tickets", {})
    assert result["error"]["code"] == "unauthorized"
    assert "Security Error - 978001" in result["error"]["message"]


async def test_success_false_on_200_is_an_error(monkeypatch):
    rec = Recorder({"v2/servicedesk/tickets/5": {"Success": False, "Error": {"Message": "Ticket not found", "SubErrors": [{"Message": "Id 5"}]}}})
    result = await _call(monkeypatch, rec, "kaseya_bms_get_ticket", {"ticketId": "5"})
    assert result["error"]["code"] == "invalid_argument" and "Ticket not found" in result["error"]["message"] and "Id 5" in result["error"]["message"]


async def test_get_retries_5xx_but_posts_do_not():
    replies = iter([httpx.Response(502), httpx.Response(200, json=ok([]))])
    rec = Recorder({"GET v2/servicedesk/tickets": lambda r: next(replies), "POST v2/servicedesk/tickets": lambda r: httpx.Response(500)})
    client = _client(rec)
    await client.get("v2/servicedesk/tickets")
    with pytest.raises(BmsError):
        await client.post("v2/servicedesk/tickets", {})
    assert len(rec.calls("v2/servicedesk/tickets", "GET")) == 2 and len(rec.calls("v2/servicedesk/tickets", "POST")) == 1


# ---- tickets ---------------------------------------------------------------


async def test_list_tickets_filters_and_paging(monkeypatch):
    rec = Recorder({"v2/servicedesk/tickets": ok([{"Id": 1, "TicketNumber": "T1"}], TotalRecords=250)})
    args = {"filter": "printer", "top": 50, "skip": 100, "status_names": "New,In Progress", "account": "Example Co", "exclude_completed": True}
    result = await _call(monkeypatch, rec, "kaseya_bms_list_tickets", args)
    params = rec.requests[0].url.params
    assert (params["Filter.Value"], params["PageSize"], params["PageNumber"]) == ("printer", "50", "3")
    assert (params["Filter.StatusNames"], params["Filter.Account"], params["Filter.ExcludeCompleted"]) == ("New,In Progress", "Example Co", "1")
    assert result == {"tickets": [{"Id": 1, "TicketNumber": "T1"}], "count": 1, "total": 250, "page": 3, "has_more": True, "next_skip": 150}


async def test_get_ticket_unwraps_result(monkeypatch):
    rec = Recorder({"v2/servicedesk/tickets/42": ok({"Id": 42, "Title": "VPN down"})})
    assert await _call(monkeypatch, rec, "kaseya_bms_get_ticket", {"ticketId": "42"}) == {"Id": 42, "Title": "VPN down"}


async def test_ticket_id_must_be_numeric(monkeypatch):
    result = await _call(monkeypatch, Recorder(), "kaseya_bms_get_ticket", {"ticketId": "T-42"})
    assert result["error"]["code"] == "invalid_argument"


def _create_routes(recent=None):
    return {
        "v2/system/priorities/lookup": ok([{"Id": 1, "Name": "Low"}, {"Id": 2, "Name": "Medium", "IsDefault": True}, {"Id": 3, "Name": "High"}]),
        "v2/system/statuses/lookup": ok([{"Id": 10, "Name": "In Progress", "StatusOrder": 2}, {"Id": 11, "Name": "New", "StatusOrder": 1}]),
        "v2/crm/accounts/77/locations/lookup": ok([{"Id": 5, "Name": "Branch"}, {"Id": 6, "Name": "HQ", "IsMain": True}]),
        "GET v2/servicedesk/tickets": ok(recent if recent is not None else [{"Id": 9, "TypeId": 4, "SourceId": 8}]),
        "POST v2/servicedesk/tickets": ok({"Id": 100, "TicketNumber": "T100"}),
    }


async def test_create_ticket_fills_required_ids(monkeypatch):
    rec = Recorder(_create_routes())
    args = {"subject": "Printer jam", "description": "Floor 2", "accountId": "77", "contactId": "12", "priority": "high"}
    result = await _call(monkeypatch, rec, "kaseya_bms_create_ticket", args)
    sent = body(rec.calls("v2/servicedesk/tickets", "POST")[0])
    assert {k: sent[k] for k in ("Title", "Details", "AccountId", "LocationId", "ContactId", "PriorityId", "StatusId", "TypeId", "SourceId")} == {
        "Title": "Printer jam", "Details": "Floor 2", "AccountId": 77, "LocationId": 6, "ContactId": 12,
        "PriorityId": 3, "StatusId": 11, "TypeId": 4, "SourceId": 8,
    }
    assert sent["OpenDate"].endswith("Z") and sent["UseDefaultContract"] is True
    assert rec.calls("v2/servicedesk/tickets", "GET")[0].url.params["Filter.AccountIds"] == "77"
    assert result == {"Id": 100, "TicketNumber": "T100"}


async def test_create_ticket_defaults_priority_and_status(monkeypatch):
    rec = Recorder(_create_routes())
    await _call(monkeypatch, rec, "kaseya_bms_create_ticket", {"subject": "s", "description": "d", "accountId": "77"})
    sent = body(rec.calls("v2/servicedesk/tickets", "POST")[0])
    assert (sent["PriorityId"], sent["StatusId"]) == (2, 11) and "ContactId" not in sent


async def test_create_ticket_errors(monkeypatch):
    no_account = await _call(monkeypatch, Recorder(_create_routes()), "kaseya_bms_create_ticket", {"subject": "s", "description": "d"})
    assert no_account["error"]["code"] == "invalid_argument" and "accountId" in no_account["error"]["message"]
    unknown = await _call(monkeypatch, Recorder(_create_routes()), "kaseya_bms_create_ticket", {"subject": "s", "description": "d", "accountId": "77", "priority": "Urgent"})
    assert "Known values: Low, Medium, High" in unknown["error"]["message"]
    rec = Recorder(_create_routes(recent=[]))
    no_template = await _call(monkeypatch, rec, "kaseya_bms_create_ticket", {"subject": "s", "description": "d", "accountId": "77"})
    assert "typeId and sourceId" in no_template["error"]["message"] and not rec.calls("v2/servicedesk/tickets", "POST")


async def test_create_ticket_with_explicit_ids_skips_template(monkeypatch):
    rec = Recorder(_create_routes())
    args = {"subject": "s", "description": "d", "accountId": "77", "typeId": 2, "sourceId": 3, "locationId": 5}
    await _call(monkeypatch, rec, "kaseya_bms_create_ticket", args)
    sent = body(rec.calls("v2/servicedesk/tickets", "POST")[0])
    assert (sent["TypeId"], sent["SourceId"], sent["LocationId"]) == (2, 3, 5)
    assert not rec.calls("v2/servicedesk/tickets", "GET") and not rec.calls("v2/crm/accounts/77/locations/lookup")


async def test_add_note_uses_existing_note_type(monkeypatch):
    rec = Recorder({"GET v2/servicedesk/tickets/42/notes": ok([{"Id": 1, "TypeId": 3}]), "POST v2/servicedesk/tickets/42/notes": ok({"Id": 2})})
    result = await _call(monkeypatch, rec, "kaseya_bms_add_ticket_note", {"ticketId": "42", "body": "Rebooted", "isInternal": True})
    sent = body(rec.calls("v2/servicedesk/tickets/42/notes", "POST")[0])
    assert {k: sent[k] for k in ("Details", "IsInternal", "TypeId")} == {"Details": "Rebooted", "IsInternal": True, "TypeId": 3}
    assert result == {"Id": 2}


async def test_add_note_falls_back_to_templates(monkeypatch):
    rec = Recorder(
        {
            "GET v2/servicedesk/tickets/42/notes": ok([]),
            "v2/servicedesk/templates/notes/lookup": ok([{"Id": 7, "TypeId": 5}]),
            "POST v2/servicedesk/tickets/42/notes": ok({"Id": 2}),
        }
    )
    await _call(monkeypatch, rec, "kaseya_bms_add_ticket_note", {"ticketId": "42", "body": "x"})
    assert body(rec.calls("v2/servicedesk/tickets/42/notes", "POST")[0])["TypeId"] == 5


async def test_add_note_without_any_type(monkeypatch):
    rec = Recorder({"GET v2/servicedesk/tickets/42/notes": ok([]), "v2/servicedesk/templates/notes/lookup": ok([])})
    result = await _call(monkeypatch, rec, "kaseya_bms_add_ticket_note", {"ticketId": "42", "body": "x"})
    assert "noteTypeId" in result["error"]["message"] and not rec.calls("v2/servicedesk/tickets/42/notes", "POST")


# ---- time / crm / finance / service ------------------------------------------


async def test_time_entries_default_window(monkeypatch):
    rec = Recorder({"v2/timelogs": ok([{"Id": 1}], TotalRecords=1)})
    result = await _call(monkeypatch, rec, "kaseya_bms_list_time_entries", {"ticket_id": 42, "billable": True})
    params = rec.requests[0].url.params
    assert "Filter.StartDateFrom" in params and params["Filter.TicketId"] == "42" and params["Filter.IsBillable"] == "true"
    assert result["window"]["from"] == params["Filter.StartDateFrom"] and result["count"] == 1


async def test_accounts_and_contacts(monkeypatch):
    rec = Recorder({"v2/crm/accounts/summary": ok([{"Id": 77}], TotalRecords=1), "v2/crm/contacts/summary": ok([{"Id": 12}], TotalRecords=1)})
    accounts = await _call(monkeypatch, rec, "kaseya_bms_list_accounts", {"filter": "Example", "is_active": True})
    assert rec.calls("v2/crm/accounts/summary")[0].url.params["Filter.AccountName"] == "Example"
    assert accounts["accounts"] == [{"Id": 77}] and accounts["has_more"] is False
    await _call(monkeypatch, rec, "kaseya_bms_list_contacts", {"filter": "ann@example.com"})
    await _call(monkeypatch, rec, "kaseya_bms_list_contacts", {"filter": "Example", "account_id": 77})
    first, second = (r.url.params for r in rec.calls("v2/crm/contacts/summary"))
    assert first["Filter.Email"] == "ann@example.com" and "Filter.AccountName" not in first
    assert second["Filter.AccountName"] == "Example" and second["Filter.AccountId"] == "77"


async def test_contracts_and_service_catalog(monkeypatch):
    rec = Recorder({"v2/finance/contracts/summary": ok([{"Id": 1}]), "v2/admin/finance/services/lookup": ok([{"Id": 2, "Name": "Managed"}])})
    contracts = await _call(monkeypatch, rec, "kaseya_bms_list_contracts", {"filter": "Gold", "status": "Active", "top": 10})
    params = rec.calls("v2/finance/contracts/summary")[0].url.params
    assert (params["Filter.ContractName"], params["Filter.Status"], params["PageSize"]) == ("Gold", "Active", "10")
    assert contracts["contracts"] == [{"Id": 1}]
    services = await _call(monkeypatch, rec, "kaseya_bms_list_service_catalog", {"name": "Man"})
    assert services["services"] == [{"Id": 2, "Name": "Managed"}]
