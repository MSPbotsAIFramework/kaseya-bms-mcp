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
"""Projects: list/get project, list project tasks, a task's related items (PRD-21214)."""

import json

from kaseya_bms_mcp.server import INSTRUCTIONS, create_mcp_server
from test_api_client import Recorder, _call, body, ok  # reuse the shared mock-transport helpers


async def test_list_projects_returns_expected_fields_and_paging(monkeypatch):
    project = {
        "Id": 1, "Name": "Office Move", "ProjectNumber": "PRJ-1", "StatusId": 2, "StatusName": "Active",
        "PriorityId": 3, "PriorityName": "High", "StartDate": "2026-01-01", "DueDate": "2026-03-01", "CreatedOn": "2025-12-01",
    }
    rec = Recorder({"v2/project/projects/summary": ok([project], TotalRecords=1)})
    result = await _call(monkeypatch, rec, "kaseya_bms_list_projects", {})
    assert result == {"projects": [project], "count": 1, "total": 1, "page": 1, "has_more": False}
    params = rec.requests[0].url.params
    assert (params["PageSize"], params["PageNumber"]) == ("50", "1")


async def test_list_projects_resolves_account_and_status_filters(monkeypatch):
    rec = Recorder(
        {
            "v2/project/statuses/lookup": ok([{"Id": 2, "Name": "Active", "IsActive": True}, {"Id": 9, "Name": "On Hold", "IsActive": True}]),
            "v2/project/projects/summary": ok([], TotalRecords=0),
        }
    )
    await _call(monkeypatch, rec, "kaseya_bms_list_projects", {"account_id": 77, "status_names": "Active,On Hold"})
    params = rec.calls("v2/project/projects/summary")[0].url.params
    assert params["Filter.AccountId"] == "77"
    assert params["Filter.StatusIds"] == "2,9"


async def test_list_projects_unknown_status_name_is_invalid_argument(monkeypatch):
    rec = Recorder({"v2/project/statuses/lookup": ok([{"Id": 2, "Name": "Active", "IsActive": True}])})
    result = await _call(monkeypatch, rec, "kaseya_bms_list_projects", {"status_names": "NoSuchStatus"})
    assert result["error"]["code"] == "invalid_argument"
    assert "Known values: Active" in result["error"]["message"]
    assert not rec.calls("v2/project/projects/summary")


async def test_get_project_returns_full_record(monkeypatch):
    record = {
        "Id": 123, "ProjectNumber": "PRJ-123", "Name": "Office Move", "Description": "Relocate HQ",
        "ContractId": 5, "ContractName": "Gold Support", "ManagerId": 9, "ManagerName": "Pat Lee",
        "StatusId": 2, "StatusName": "Active", "PriorityId": 3, "PriorityName": "High",
        "StartDate": "2026-01-01", "DueDate": "2026-03-01", "CompletionDate": None,
        "PlannedHours": 120, "UsedHours": 40, "PlannedBudget": 50000, "ActualBudget": 18000,
    }
    rec = Recorder({"v2/project/projects/123": ok(record)})
    result = await _call(monkeypatch, rec, "kaseya_bms_get_project", {"projectId": "123"})
    assert result == record


async def test_get_project_unknown_id_is_not_found(monkeypatch):
    import httpx

    rec = Recorder({"v2/project/projects/999999": lambda r: httpx.Response(404, json={"Success": False, "Error": {"Message": "Not found"}})})
    result = await _call(monkeypatch, rec, "kaseya_bms_get_project", {"projectId": "999999"})
    assert result["error"]["code"] == "not_found"


async def test_get_project_id_must_be_numeric(monkeypatch):
    result = await _call(monkeypatch, Recorder(), "kaseya_bms_get_project", {"projectId": "P-1"})
    assert result["error"]["code"] == "invalid_argument"


async def test_list_project_tasks_returns_matching_tasks(monkeypatch):
    task = {
        "TaskId": 456, "TaskName": "Pack desks", "TaskDescription": "Pack all desks", "ProjectName": "Office Move",
        "ProjectColor": "#00ff00", "PlannedHours": 8, "StartDate": "2026-01-05", "EndDate": "2026-01-06", "AccountId": 77,
    }
    rec = Recorder({"v2/project/tasks": ok([task])})
    result = await _call(monkeypatch, rec, "kaseya_bms_list_project_tasks", {"project_id": 1, "task_name": "Pack"})
    sent = body(rec.calls("v2/project/tasks", "POST")[0])
    assert sent["Filter"] == {"ProjectIds": [1], "TaskName": "Pack"}
    # BMS's task-list response has no TotalRecords, so "total" is absent (not null) and has_more stays False.
    assert result == {"tasks": [task], "count": 1, "page": 1, "has_more": False}


async def test_list_project_tasks_unassigned_and_my_projects_are_int_not_bool(monkeypatch):
    rec = Recorder({"v2/project/tasks": ok([])})
    await _call(monkeypatch, rec, "kaseya_bms_list_project_tasks", {"unassigned": True, "my_projects": False})
    sent = body(rec.calls("v2/project/tasks", "POST")[0])
    assert sent["Filter"] == {"Unassigned": 1, "MyProjects": 0}


async def test_list_project_tasks_has_no_total_records_and_never_signals_has_more(monkeypatch):
    rec = Recorder({"v2/project/tasks": ok([{"TaskId": 1}] * 50)})
    result = await _call(monkeypatch, rec, "kaseya_bms_list_project_tasks", {"top": 50})
    assert "total" not in result and result["has_more"] is False and "next_skip" not in result


async def test_get_task_related_items_returns_details(monkeypatch):
    record = {
        "Title": "Pack desks", "Description": "Pack all desks before the move",
        "Dependencies": [{"TaskId": 455, "TaskName": "Order boxes"}],
        "RelatedTickets": [{"TicketId": 42, "TicketNumber": "T42"}],
    }
    rec = Recorder({"v2/project/tasks/456/relateditems": ok(record)})
    result = await _call(monkeypatch, rec, "kaseya_bms_get_task_related_items", {"taskId": "456"})
    assert result == record


async def test_get_task_related_items_unknown_id_is_not_found(monkeypatch):
    import httpx

    rec = Recorder({"v2/project/tasks/999999/relateditems": lambda r: httpx.Response(404, json={"Success": False, "Error": {"Message": "Not found"}})})
    result = await _call(monkeypatch, rec, "kaseya_bms_get_task_related_items", {"taskId": "999999"})
    assert result["error"]["code"] == "not_found"


async def test_new_tools_return_not_configured_without_credentials():
    mcp = create_mcp_server()
    for name, args in (
        ("kaseya_bms_list_projects", {}),
        ("kaseya_bms_get_project", {"projectId": "1"}),
        ("kaseya_bms_list_project_tasks", {}),
        ("kaseya_bms_get_task_related_items", {"taskId": "1"}),
    ):
        content, _ = await mcp.call_tool(name, args)
        assert json.loads(content[0].text)["error"]["code"] == "not_configured"


def test_instructions_mention_projects():
    assert "project" in INSTRUCTIONS.lower() and "kaseya_bms_list_projects" in INSTRUCTIONS
