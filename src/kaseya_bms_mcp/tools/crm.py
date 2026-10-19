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
"""CRM: client accounts and their contacts."""

from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..api_client import BmsClient
from ..config import MAX_PAGE_SIZE
from ._common import READ_ONLY, ClientFactory, Skip, compact, page, paging, run_tool

Top = Annotated[int, Field(description=f"Page size (default 50, max {MAX_PAGE_SIZE}).", ge=1, le=MAX_PAGE_SIZE)]
Active = Annotated[bool | None, Field(description="Only active (true) or inactive (false).")]


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def kaseya_bms_list_accounts(
        filter: Annotated[str | None, Field(description="Account name contains this text.")] = None,
        top: Top = 50,
        skip: Skip = None,
        account_code: Annotated[str | None, Field(description="Account code.")] = None,
        account_type: Annotated[str | None, Field(description="Account type name, e.g. Customer.")] = None,
        is_active: Active = None,
    ) -> str:
        """List client accounts: id, name, code, type, account manager, website, active flag, locations."""

        async def action(client: BmsClient) -> dict:
            params = paging(top, skip)
            query = compact(
                {"Filter.AccountName": filter, "Filter.AccountCode": account_code, "Filter.AccountTypeName": account_type, "Filter.IsActive": is_active}
            )
            return page(await client.get("v2/crm/accounts/summary", query | params), "accounts", params)

        return await run_tool("kaseya_bms_list_accounts", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def kaseya_bms_list_contacts(
        filter: Annotated[str | None, Field(description="An email address, or text the account name contains.")] = None,
        top: Top = 50,
        skip: Skip = None,
        account_id: Annotated[int | None, Field(description="Only contacts of this account.", ge=1)] = None,
        first_name: Annotated[str | None, Field(description="First name.")] = None,
        last_name: Annotated[str | None, Field(description="Last name.")] = None,
        is_active: Active = None,
    ) -> str:
        """List contacts: id, name, account, email, phone, active flag."""

        async def action(client: BmsClient) -> dict:
            params = paging(top, skip)
            email = filter if filter and "@" in filter else None
            account_name = filter if filter and not email else None
            query = compact(
                {
                    "Filter.Email": email,
                    "Filter.AccountName": account_name,
                    "Filter.AccountId": account_id,
                    "Filter.FirstName": first_name,
                    "Filter.LastName": last_name,
                    "Filter.IsActive": is_active,
                }
            )
            return page(await client.get("v2/crm/contacts/summary", query | params), "contacts", params)

        return await run_tool("kaseya_bms_list_contacts", client_factory, action)
