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
"""Projects: project records, their tasks, and a task's dependencies / related tickets.

Read-only: the BMS v2 API has no endpoint to create or update a project or a project
task (only the `statuses` admin-config paths are writable), so there is no write tool
here to add later without a new vendor API version.
"""

from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..api_client import BmsClient
from ..config import MAX_PAGE_SIZE
from ._common import READ_ONLY, ClientFactory, Skip, by_name, compact, page, paging, result, run_tool
from .tickets import _number

ProjectId = Annotated[str, Field(description="BMS project id (numeric Id, not the project number).", min_length=1)]
TaskId = Annotated[str, Field(description="BMS project task id (numeric Id).", min_length=1)]
Top = Annotated[int, Field(description=f"Page size (default 50, max {MAX_PAGE_SIZE}).", ge=1, le=MAX_PAGE_SIZE)]


def _rows(payload: Any) -> list[dict]:
    rows = result(payload)
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


async def _status_ids(client: BmsClient, status_names: str) -> str:
    """Comma-separated BMS project status ids for a comma-separated list of status names."""
    rows = _rows(await client.get("v2/project/statuses/lookup"))
    ids = [by_name(rows, name.strip(), "project status") for name in status_names.split(",") if name.strip()]
    return ",".join(str(i) for i in ids)


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def kaseya_bms_list_projects(
        top: Top = 50,
        skip: Skip = None,
        account_id: Annotated[int | None, Field(description="Only this account's projects.", ge=1)] = None,
        status_names: Annotated[str | None, Field(description="Comma-separated project status names, e.g. Active,On Hold.")] = None,
        start_date_from: Annotated[str | None, Field(description="ISO date: project starts on or after.")] = None,
        start_date_to: Annotated[str | None, Field(description="ISO date: project starts on or before.")] = None,
    ) -> str:
        """List projects: id, name, project number, status, priority, start/due date, created date."""

        async def action(client: BmsClient) -> dict:
            params = paging(top, skip)
            query = compact(
                {
                    "Filter.AccountId": account_id,
                    "Filter.StatusIds": await _status_ids(client, status_names) if status_names else None,
                    "Filter.StartDateFrom": start_date_from,
                    "Filter.StartDateTo": start_date_to,
                }
            )
            return page(await client.get("v2/project/projects/summary", query | params), "projects", params)

        return await run_tool("kaseya_bms_list_projects", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def kaseya_bms_get_project(projectId: ProjectId) -> str:
        """Get one project: description, contract, manager, status, priority, dates, hours, budget."""

        async def action(client: BmsClient) -> Any:
            return result(await client.get(f"v2/project/projects/{_number(projectId, 'projectId')}"))

        return await run_tool("kaseya_bms_get_project", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def kaseya_bms_list_project_tasks(
        top: Top = 50,
        skip: Skip = None,
        project_id: Annotated[int | None, Field(description="Only this project's tasks.", ge=1)] = None,
        account_id: Annotated[int | None, Field(description="Only tasks of this account's projects.", ge=1)] = None,
        task_name: Annotated[str | None, Field(description="Task name contains this text.")] = None,
        unassigned: Annotated[bool | None, Field(description="true = only tasks with no assignee.")] = None,
        my_projects: Annotated[bool | None, Field(description="true = only tasks on the caller's own projects.")] = None,
    ) -> str:
        """List project tasks: name, project name/color, planned hours, start/end date, account id.

        Kaseya BMS's task list has no total record count, unlike the other list tools here:
        `has_more` always reads false even when more rows exist, so a caller must keep asking
        for the next `skip` until an empty page comes back rather than stopping on `has_more`.
        """

        async def action(client: BmsClient) -> dict:
            params = paging(top, skip)
            body = {
                "PageSize": params["PageSize"],
                "PageNumber": params["PageNumber"],
                "Filter": compact(
                    {
                        "ProjectIds": [project_id] if project_id else None,
                        "AccountIds": [account_id] if account_id else None,
                        "TaskName": task_name,
                        # BMS types these int32 in TasksListFilterDto, not boolean.
                        "Unassigned": 1 if unassigned else (0 if unassigned is not None else None),
                        "MyProjects": 1 if my_projects else (0 if my_projects is not None else None),
                    }
                ),
            }
            return page(await client.post("v2/project/tasks", body), "tasks", params)

        return await run_tool("kaseya_bms_list_project_tasks", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def kaseya_bms_get_task_related_items(taskId: TaskId) -> str:
        """Get a project task's title, description, dependencies, and related service-desk tickets."""

        async def action(client: BmsClient) -> Any:
            return result(await client.get(f"v2/project/tasks/{_number(taskId, 'taskId')}/relateditems"))

        return await run_tool("kaseya_bms_get_task_related_items", client_factory, action)
