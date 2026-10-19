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
"""Finance: client contracts."""

from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..api_client import BmsClient
from ..config import MAX_PAGE_SIZE
from ._common import READ_ONLY, ClientFactory, Skip, compact, page, paging, run_tool


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def kaseya_bms_list_contracts(
        filter: Annotated[str | None, Field(description="Contract name contains this text.")] = None,
        top: Annotated[int, Field(description=f"Page size (default 50, max {MAX_PAGE_SIZE}).", ge=1, le=MAX_PAGE_SIZE)] = 50,
        skip: Skip = None,
        account_name: Annotated[str | None, Field(description="Account name.")] = None,
        status: Annotated[str | None, Field(description="Contract status, e.g. Active.")] = None,
        contract_type: Annotated[str | None, Field(description="Contract type.")] = None,
    ) -> str:
        """List client contracts: number, name, account, type, billing cycle and price, status, dates."""

        async def action(client: BmsClient) -> dict:
            params = paging(top, skip)
            query = compact(
                {"Filter.ContractName": filter, "Filter.AccountName": account_name, "Filter.Status": status, "Filter.ContractType": contract_type}
            )
            return page(await client.get("v2/finance/contracts/summary", query | params), "contracts", params)

        return await run_tool("kaseya_bms_list_contracts", client_factory, action)
