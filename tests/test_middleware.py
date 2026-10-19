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
"""Credential middleware: 401 on missing headers, token precedence, region, isolation."""

import asyncio

import pytest
from starlette.testclient import TestClient

from kaseya_bms_mcp.__main__ import build_http_app
from kaseya_bms_mcp.server import GatewayCredentialsMiddleware, _credentials_var, create_mcp_server, get_client_from_context, region_for

MCP_HEADERS = {"Accept": "application/json, text/event-stream"}
LIST_TOOLS = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
CREDS = {"X-Kaseya-BMS-Tenant-Subdomain": "examplemsp", "X-Kaseya-BMS-API-Token": "token"}


def _client() -> TestClient:
    return TestClient(build_http_app(create_mcp_server()))


def test_health_is_local():
    with _client() as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-Kaseya-BMS-Tenant-Subdomain": "examplemsp"},
        {"X-Kaseya-BMS-API-Token": "token"},
        {"X-Kaseya-BMS-Tenant-Subdomain": "examplemsp", "X-Kaseya-BMS-API-Token": "${TOKEN}", "X-Kaseya-BMS-K1-Token": "${K1}"},
    ],
)
def test_missing_headers_return_401(headers):
    with _client() as client:
        resp = client.post("/mcp", json=LIST_TOOLS, headers=MCP_HEADERS | headers)
    assert resp.status_code == 401


@pytest.mark.parametrize(
    "value,expected",
    [
        ("examplemsp", "us"),
        ("emea", "emea"),
        ("EU", "emea"),
        ("https://api.bmsemea.kaseya.com/", "emea"),
        ("bmsapac.kaseya.com", "apac"),
        ("apac", "apac"),
        ("api.bms.kaseya.com", "us"),
    ],
)
def test_region_for(value, expected):
    assert region_for(value) == expected


def test_tools_list_over_http():
    with _client() as client:
        resp = client.post("/mcp", json=LIST_TOOLS, headers=MCP_HEADERS | CREDS)
    assert resp.status_code == 200
    for name in ("kaseya_bms_list_tickets", "kaseya_bms_create_ticket", "kaseya_bms_search_knowledge_base"):
        assert name in resp.text


async def _receive():
    return {"type": "http.request", "body": b"", "more_body": False}


async def _send(_message):
    return None


def _run_middleware(headers: list[tuple[bytes, bytes]]) -> dict:
    seen: dict = {}

    async def app(scope, receive, send):
        seen["credentials"] = _credentials_var.get()
        seen["client"] = get_client_from_context()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    asyncio.run(GatewayCredentialsMiddleware(app)({"type": "http", "path": "/mcp", "headers": headers}, _receive, _send))
    return seen


def test_k1_token_takes_precedence_and_context_is_reset():
    seen = _run_middleware(
        [(b"x-kaseya-bms-tenant-subdomain", b"emea"), (b"x-kaseya-bms-api-token", b"api-tok"), (b"x-kaseya-bms-k1-token", b" k1-tok ")]
    )
    assert seen["credentials"].token == "k1-tok" and seen["credentials"].token_kind == "k1"
    assert seen["client"].base_url == "https://api.bmsemea.kaseya.com"
    assert seen["client"]._headers()["Authorization"] == "Bearer k1-tok"
    assert _credentials_var.get() is None


def test_placeholder_k1_does_not_hide_the_api_token():
    seen = _run_middleware(
        [(b"x-kaseya-bms-tenant-subdomain", b"examplemsp"), (b"x-kaseya-bms-api-token", b"api-tok"), (b"x-kaseya-bms-k1-token", b"${K1}")]
    )
    assert seen["credentials"].token == "api-tok" and seen["credentials"].token_kind == "api"


def test_concurrent_requests_do_not_share_credentials():
    observed: list[tuple[str, str]] = []

    async def app(scope, receive, send):
        before = _credentials_var.get().token
        await asyncio.sleep(0.01)
        observed.append((before, _credentials_var.get().token))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = GatewayCredentialsMiddleware(app)

    def scope(token: bytes) -> dict:
        return {"type": "http", "path": "/mcp", "headers": [(b"x-kaseya-bms-tenant-subdomain", b"t"), (b"x-kaseya-bms-api-token", token)]}

    async def both():
        await asyncio.gather(middleware(scope(b"tenant-a"), _receive, _send), middleware(scope(b"tenant-b"), _receive, _send))

    asyncio.run(both())
    assert sorted(observed) == [("tenant-a", "tenant-a"), ("tenant-b", "tenant-b")]


def test_credentials_repr_hides_token():
    seen = _run_middleware([(b"x-kaseya-bms-tenant-subdomain", b"t"), (b"x-kaseya-bms-api-token", b"very-secret-token")])
    assert "very-secret-token" not in repr(seen["credentials"])
