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
"""Service desk tickets: list, read, create, add notes."""

from datetime import UTC, datetime
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..api_client import BmsClient
from ..config import MAX_PAGE_SIZE
from ._common import READ_ONLY, WRITES, ClientFactory, Skip, by_name, compact, page, paging, result, run_tool

TicketId = Annotated[str, Field(description="BMS ticket id (numeric Id, not the ticket number).", min_length=1)]
OptionalId = Annotated[int | None, Field(description="Override; omitted = the usual value (see the tool).", ge=1)]


def _number(value: Any, name: str) -> int:
    text = str(value).strip()
    if not text.isdigit():
        raise ValueError(f"{name} must be a number, got {value!r}.")
    return int(text)


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _rows(payload: Any) -> list[dict]:
    rows = result(payload)
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


async def _priority_id(client: BmsClient, name: str | None) -> int:
    rows = _rows(await client.get("v2/system/priorities/lookup"))
    if name:
        return by_name(rows, name, "priority")
    default = next((r for r in rows if r.get("IsDefault")), rows[0] if rows else None)
    if not default:
        raise ValueError("Kaseya BMS returned no priorities; pass a priority.")
    return int(default["Id"])


async def _status_id(client: BmsClient, name: str | None) -> int:
    rows = [r for r in _rows(await client.get("v2/system/statuses/lookup")) if r.get("IsActive", True)]
    if name:
        return by_name(rows, name, "status")
    rows.sort(key=lambda r: (str(r.get("Name") or "").lower() != "new", r.get("StatusOrder") or 0))
    if not rows:
        raise ValueError("Kaseya BMS returned no statuses; pass a status.")
    return int(rows[0]["Id"])


async def _location_id(client: BmsClient, account_id: int) -> int:
    rows = _rows(await client.get(f"v2/crm/accounts/{account_id}/locations/lookup"))
    main = next((r for r in rows if r.get("IsMain")), rows[0] if rows else None)
    if not main:
        raise ValueError(f"Account {account_id} has no locations; pass locationId.")
    return int(main["Id"])


async def _usual_type_and_source(client: BmsClient, account_id: int) -> tuple[int | None, int | None]:
    """Ticket type and source of a recent ticket (of this account if it has any); BMS has no lookup for them."""
    for params in ({"Filter.AccountIds": str(account_id)}, {}):
        rows = _rows(await client.get("v2/servicedesk/tickets", params | {"PageSize": 1, "PageNumber": 1}))
        if rows:
            return rows[0].get("TypeId"), rows[0].get("SourceId")
    return None, None


async def _note_type_id(client: BmsClient, ticket_id: int) -> int | None:
    notes = _rows(await client.get(f"v2/servicedesk/tickets/{ticket_id}/notes", {"PageSize": 1, "PageNumber": 1}))
    if notes and notes[0].get("TypeId"):
        return int(notes[0]["TypeId"])
    templates = _rows(await client.get("v2/servicedesk/templates/notes/lookup"))
    return next((int(t["TypeId"]) for t in templates if t.get("TypeId")), None)


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def kaseya_bms_list_tickets(
        filter: Annotated[str | None, Field(description="Text to search for in tickets (number, title, details ...).")] = None,
        top: Annotated[int, Field(description=f"Page size (default 50, max {MAX_PAGE_SIZE}).", ge=1, le=MAX_PAGE_SIZE)] = 50,
        skip: Skip = None,
        status_names: Annotated[str | None, Field(description="Comma-separated status names, e.g. New,In Progress.")] = None,
        priority_names: Annotated[str | None, Field(description="Comma-separated priority names.")] = None,
        queue_names: Annotated[str | None, Field(description="Comma-separated queue names.")] = None,
        account: Annotated[str | None, Field(description="Account name.")] = None,
        assignee: Annotated[str | None, Field(description="Assignee name.")] = None,
        open_date_from: Annotated[str | None, Field(description="ISO date: opened on or after.")] = None,
        open_date_to: Annotated[str | None, Field(description="ISO date: opened on or before.")] = None,
        exclude_completed: Annotated[bool | None, Field(description="true = only tickets not completed.")] = None,
    ) -> str:
        """List service desk tickets: number, title, account, contact, status, priority, queue, assignee, SLA."""

        async def action(client: BmsClient) -> dict:
            params = paging(top, skip)
            query = compact(
                {
                    "Filter.Value": filter,
                    "Filter.StatusNames": status_names,
                    "Filter.PriorityNames": priority_names,
                    "Filter.QueueNames": queue_names,
                    "Filter.Account": account,
                    "Filter.AssigneeName": assignee,
                    "Filter.OpenDateFrom": open_date_from,
                    "Filter.OpenDateTo": open_date_to,
                    "Filter.ExcludeCompleted": 1 if exclude_completed else None,
                }
            )
            return page(await client.get("v2/servicedesk/tickets", query | params), "tickets", params)

        return await run_tool("kaseya_bms_list_tickets", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def kaseya_bms_get_ticket(ticketId: TicketId) -> str:
        """Get one ticket with its details, account, contact, status, priority, SLA and dates."""

        async def action(client: BmsClient) -> Any:
            return result(await client.get(f"v2/servicedesk/tickets/{_number(ticketId, 'ticketId')}"))

        return await run_tool("kaseya_bms_get_ticket", client_factory, action)

    @mcp.tool(annotations=WRITES)
    async def kaseya_bms_create_ticket(
        subject: Annotated[str, Field(description="Ticket title.", min_length=1)],
        description: Annotated[str, Field(description="Ticket details.", min_length=1)],
        accountId: Annotated[str | None, Field(description="Account (client) id; required by Kaseya BMS.")] = None,
        contactId: Annotated[str | None, Field(description="Contact id at that account.")] = None,
        priority: Annotated[str | None, Field(description="Priority name; default = the default priority.")] = None,
        status: Annotated[str | None, Field(description="Status name; default = New (or the first status).")] = None,
        queueId: OptionalId = None,
        issueTypeId: OptionalId = None,
        typeId: Annotated[int | None, Field(description="Ticket type id; default = that of a recent ticket.", ge=1)] = None,
        sourceId: Annotated[int | None, Field(description="Source id; default = that of a recent ticket.", ge=1)] = None,
        locationId: Annotated[int | None, Field(description="Account location id; default = its main location.", ge=1)] = None,
    ) -> str:
        """Create a service desk ticket for an account. Only when the user explicitly asks."""

        async def action(client: BmsClient) -> Any:
            if not accountId:
                raise ValueError("Pass accountId: Kaseya BMS requires every ticket to belong to an account (see kaseya_bms_list_accounts).")
            account = _number(accountId, "accountId")
            usual_type, usual_source = (typeId, sourceId) if typeId and sourceId else await _usual_type_and_source(client, account)
            type_id, source_id = typeId or usual_type, sourceId or usual_source
            if not type_id or not source_id:
                raise ValueError("No earlier ticket to copy the ticket type and source from; pass typeId and sourceId.")
            body = compact(
                {
                    "Title": subject,
                    "Details": description,
                    "AccountId": account,
                    "LocationId": locationId or await _location_id(client, account),
                    "ContactId": _number(contactId, "contactId") if contactId else None,
                    "PriorityId": await _priority_id(client, priority),
                    "StatusId": await _status_id(client, status),
                    "TypeId": int(type_id),
                    "SourceId": int(source_id),
                    "QueueId": queueId,
                    "IssueTypeId": issueTypeId,
                    "OpenDate": _now(),
                    "UseDefaultContract": True,
                }
            )
            return result(await client.post("v2/servicedesk/tickets", body))

        return await run_tool("kaseya_bms_create_ticket", client_factory, action)

    @mcp.tool(annotations=WRITES)
    async def kaseya_bms_add_ticket_note(
        ticketId: TicketId,
        body: Annotated[str, Field(description="Note text.", min_length=1)],
        isInternal: Annotated[bool, Field(description="true = internal note, hidden from the client.")] = False,
        noteTypeId: Annotated[int | None, Field(description="Note type id; default = that of the ticket's notes.", ge=1)] = None,
    ) -> str:
        """Add a note to a ticket (internal or visible to the client). Only when the user explicitly asks."""

        async def action(client: BmsClient) -> Any:
            ticket = _number(ticketId, "ticketId")
            type_id = noteTypeId or await _note_type_id(client, ticket)
            if not type_id:
                raise ValueError("Could not work out the note type; pass noteTypeId.")
            note = {"Details": body, "IsInternal": isInternal, "TypeId": type_id, "NoteDate": _now()}
            return result(await client.post(f"v2/servicedesk/tickets/{ticket}/notes", note))

        return await run_tool("kaseya_bms_add_ticket_note", client_factory, action)
