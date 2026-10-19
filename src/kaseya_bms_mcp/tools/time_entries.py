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
"""Time entries (time logs) against tickets and projects."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..api_client import BmsClient
from ..config import MAX_PAGE_SIZE
from ._common import READ_ONLY, ClientFactory, Skip, compact, page, paging, run_tool

_DEFAULT_DAYS = 7


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def kaseya_bms_list_time_entries(
        startDate: Annotated[str | None, Field(description="ISO date: entries starting on or after (default 7 days ago).")] = None,
        endDate: Annotated[str | None, Field(description="ISO date: entries starting on or before (default today).")] = None,
        top: Annotated[int, Field(description=f"Page size (default 50, max {MAX_PAGE_SIZE}).", ge=1, le=MAX_PAGE_SIZE)] = 50,
        skip: Skip = None,
        ticket_id: Annotated[int | None, Field(description="Only this ticket's entries.", ge=1)] = None,
        user_id: Annotated[int | None, Field(description="Only this user's entries.", ge=1)] = None,
        account_id: Annotated[int | None, Field(description="Only this account's entries.", ge=1)] = None,
        billable: Annotated[bool | None, Field(description="Only billable (true) or non-billable (false).")] = None,
    ) -> str:
        """List time entries: who, ticket / project, account, work type, hours, billable / approved / billed."""

        async def action(client: BmsClient) -> dict:
            today = datetime.now(UTC).date()
            start = startDate or (today - timedelta(days=_DEFAULT_DAYS)).isoformat()
            end = endDate or today.isoformat()
            params = paging(top, skip)
            query = compact(
                {
                    "Filter.StartDateFrom": start,
                    "Filter.StartDateTo": end,
                    "Filter.TicketId": ticket_id,
                    "Filter.UserId": user_id,
                    "Filter.AccountId": account_id,
                    "Filter.IsBillable": billable,
                }
            )
            return {"window": {"from": start, "to": end}} | page(await client.get("v2/timelogs", query | params), "time_entries", params)

        return await run_tool("kaseya_bms_list_time_entries", client_factory, action)
