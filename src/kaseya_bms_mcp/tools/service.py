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
"""Service catalog, and the knowledge-base tool kept for compatibility."""

from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from .._json import error_envelope
from ..api_client import BmsClient
from ..config import MAX_PAGE_SIZE
from ._common import LOCAL, READ_ONLY, ClientFactory, Skip, compact, page, paging, run_tool


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def kaseya_bms_list_service_catalog(
        top: Annotated[int, Field(description=f"Page size (default 250, max {MAX_PAGE_SIZE}).", ge=1, le=MAX_PAGE_SIZE)] = 250,
        skip: Skip = None,
        name: Annotated[str | None, Field(description="Service name contains this text.")] = None,
    ) -> str:
        """List the services offered (the service catalog used on contracts): id, name, description."""

        async def action(client: BmsClient) -> dict:
            params = paging(top, skip)
            return page(await client.get("v2/admin/finance/services/lookup", compact({"Filter.Name": name}) | params), "services", params)

        return await run_tool("kaseya_bms_list_service_catalog", client_factory, action)

    @mcp.tool(annotations=LOCAL)
    async def kaseya_bms_search_knowledge_base(
        query: Annotated[str | None, Field(description="Not used: see the tool description.")] = None,
        top: Annotated[int, Field(description="Not used.")] = 50,
    ) -> str:
        """Not available: the Kaseya BMS API has no knowledge-base endpoint; search tickets instead."""
        return error_envelope(
            "invalid_argument",
            "The Kaseya BMS API has no knowledge-base endpoint, so this tool cannot run. "
            "Use kaseya_bms_list_tickets(filter=...) to find similar resolved tickets.",
            False,
        )
