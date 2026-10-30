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
"""FastMCP factory and the per-request credential middleware."""

import contextvars
import re
import uuid
from collections.abc import Callable

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from ._arguments import EnvelopeFastMCP
from .api_client import BmsClient, BmsCredentials
from .config import DEFAULT_REGION, Settings

HEADER_TENANT = "X-Kaseya-BMS-Tenant-Subdomain"
HEADER_API_TOKEN = "X-Kaseya-BMS-API-Token"
HEADER_K1_TOKEN = "X-Kaseya-BMS-K1-Token"
REQUIRED_HEADERS = [HEADER_TENANT, f"{HEADER_API_TOKEN} or {HEADER_K1_TOKEN}"]

_PLACEHOLDER = re.compile(r"^\$\{.*\}$")
# Region words and hosts accepted in the tenant header; any other value (a tenant
# name) means the default region, because the API host does not depend on the tenant.
_REGION_ALIASES = {
    "us": "us", "na": "us", "bms": "us", "api.bms.kaseya.com": "us", "bms.kaseya.com": "us",
    "emea": "emea", "eu": "emea", "uk": "emea", "bmsemea": "emea", "api.bmsemea.kaseya.com": "emea", "bmsemea.kaseya.com": "emea",
    "apac": "apac", "au": "apac", "anz": "apac", "bmsapac": "apac", "api.bmsapac.kaseya.com": "apac", "bmsapac.kaseya.com": "apac",
}

# Per-request isolation: the middleware sets these for the duration of one
# HTTP request and resets them in `finally`. Nothing credential-related is
# ever stored at module level.
_credentials_var: contextvars.ContextVar[BmsCredentials | None] = contextvars.ContextVar("bms_credentials", default=None)
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("bms_request_id", default="-")

INSTRUCTIONS = (
    "Kaseya BMS is a PSA: service desk tickets for the MSP's client accounts, "
    "with notes, time logs, contacts, contracts and projects.\n"
    "Usage:\n"
    "- Find tickets: kaseya_bms_list_tickets (filter text, status / priority "
    "names, account, open-date range) -> kaseya_bms_get_ticket.\n"
    "- Who and what: kaseya_bms_list_accounts / _list_contacts / _list_contracts "
    "give the AccountId and ContactId other tools take.\n"
    "- Time: kaseya_bms_list_time_entries(startDate, endDate).\n"
    "- Projects: kaseya_bms_list_projects (account, status names) -> "
    "kaseya_bms_get_project; kaseya_bms_list_project_tasks (project, account, "
    "name, unassigned, my_projects) -> kaseya_bms_get_task_related_items. "
    "Read-only: BMS has no API to create or edit a project or task.\n"
    "- Lists page with top (page size) and skip (rounded to whole pages).\n"
    "Creating tickets and adding notes write to the live PSA: only when the "
    "user explicitly asks. A ticket needs an AccountId; status, priority, type, "
    "source and location default to the account's usual values when omitted.\n"
    "The knowledge base has no API; kaseya_bms_search_knowledge_base says so."
)


def get_client_from_context() -> BmsClient | None:
    """The client for the current request, or None outside a request."""
    credentials = _credentials_var.get()
    if credentials is None:
        return None
    return BmsClient(credentials)


def _clean(value: str | None) -> str | None:
    text = (value or "").strip()
    if not text or _PLACEHOLDER.match(text):
        return None
    return text


def region_for(value: str) -> str:
    """Region of a tenant header value: a region word or BMS host, else the default region."""
    text = re.sub(r"^https?://", "", value.strip().lower()).split("/", 1)[0]
    return _REGION_ALIASES.get(text, DEFAULT_REGION)


class GatewayCredentialsMiddleware:
    """Reads the BMS tenant and bearer token on /mcp requests into the request context."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith("/mcp"):
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        tenant = _clean(request.headers.get(HEADER_TENANT))
        api_token = _clean(request.headers.get(HEADER_API_TOKEN))
        k1_token = _clean(request.headers.get(HEADER_K1_TOKEN))
        if not tenant or not (api_token or k1_token):
            missing = ([HEADER_TENANT] if not tenant else []) + ([f"{HEADER_API_TOKEN} or {HEADER_K1_TOKEN}"] if not (api_token or k1_token) else [])
            await JSONResponse(
                {"error": "Missing credentials", "message": f"Missing header(s): {', '.join(missing)}", "required_headers": REQUIRED_HEADERS},
                status_code=401,
            )(scope, receive, send)
            return

        # The Kaseya One token takes precedence when both are set.
        token, kind = (k1_token, "k1") if k1_token else (api_token, "api")
        request_id = (request.headers.get("x-request-id") or "").strip()[:64] or uuid.uuid4().hex[:12]
        creds_token = _credentials_var.set(BmsCredentials(region_for(tenant), token, kind))
        rid_token = request_id_var.set(request_id)
        try:
            await self.app(scope, receive, send)
        finally:
            _credentials_var.reset(creds_token)
            request_id_var.reset(rid_token)


def create_mcp_server(settings: Settings | None = None) -> FastMCP:
    """Build the FastMCP server and register every tool."""
    mcp = EnvelopeFastMCP(
        name="kaseya-bms-mcp",
        instructions=INSTRUCTIONS,
        # The service sits behind the gateway, so Host is never localhost;
        # DNS-rebinding protection would reject those requests with 421.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        stateless_http=True,
    )

    client_factory: Callable[[], BmsClient | None] = get_client_from_context

    from .tools import crm, finance, projects, service, tickets, time_entries

    for module in (tickets, time_entries, crm, finance, service, projects):
        module.register(mcp, client_factory)

    return mcp
