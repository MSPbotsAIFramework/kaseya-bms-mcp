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
"""tools/list snapshot, annotations and error-envelope mapping. No network access."""

import asyncio
import json

import pytest

from kaseya_bms_mcp.api_client import BmsError
from kaseya_bms_mcp.server import INSTRUCTIONS, create_mcp_server

# Tool names are a public contract: existing agents and tenant connections
# depend on them. Changing this snapshot is a breaking change.
EXPECTED_TOOLS: dict[str, set[str]] = {
    "kaseya_bms_list_tickets": set(),
    "kaseya_bms_get_ticket": {"ticketId"},
    "kaseya_bms_create_ticket": {"subject", "description"},
    "kaseya_bms_add_ticket_note": {"ticketId", "body"},
    "kaseya_bms_list_time_entries": set(),
    "kaseya_bms_list_accounts": set(),
    "kaseya_bms_list_contacts": set(),
    "kaseya_bms_list_contracts": set(),
    "kaseya_bms_list_service_catalog": set(),
    "kaseya_bms_search_knowledge_base": set(),
}
# Every parameter the earlier version declared is still accepted.
UPSTREAM_PARAMS: dict[str, set[str]] = {
    "kaseya_bms_list_tickets": {"filter", "top", "skip"},
    "kaseya_bms_create_ticket": {"subject", "description", "accountId", "contactId", "priority", "status"},
    "kaseya_bms_add_ticket_note": {"ticketId", "body", "isInternal"},
    "kaseya_bms_list_time_entries": {"startDate", "endDate", "top"},
    "kaseya_bms_list_accounts": {"filter", "top"},
    "kaseya_bms_list_contacts": {"filter", "top"},
    "kaseya_bms_list_contracts": {"filter", "top"},
    "kaseya_bms_list_service_catalog": {"top"},
    "kaseya_bms_search_knowledge_base": {"query", "top"},
}
WRITE_TOOLS = {"kaseya_bms_create_ticket", "kaseya_bms_add_ticket_note"}
LOCAL_TOOLS = {"kaseya_bms_search_knowledge_base"}


@pytest.fixture(scope="module")
def tools():
    return {t.name: t for t in asyncio.run(create_mcp_server().list_tools())}


def test_tool_names_are_stable(tools):
    assert set(tools) == set(EXPECTED_TOOLS)


@pytest.mark.parametrize("name", sorted(EXPECTED_TOOLS))
def test_required_params(tools, name):
    assert set(tools[name].inputSchema.get("required", [])) == EXPECTED_TOOLS[name]


@pytest.mark.parametrize("name", sorted(UPSTREAM_PARAMS))
def test_earlier_params_still_accepted(tools, name):
    assert UPSTREAM_PARAMS[name] <= set(tools[name].inputSchema["properties"])


@pytest.mark.parametrize("name", sorted(EXPECTED_TOOLS))
def test_description_budget(tools, name):
    description = (tools[name].description or "").strip()
    assert description, f"{name} has no description"
    assert len(description) <= 500
    assert len(description.splitlines()[0]) <= 100


@pytest.mark.parametrize("name", sorted(EXPECTED_TOOLS))
def test_annotations_match_side_effects(tools, name):
    annotations = tools[name].annotations
    assert annotations is not None
    assert annotations.readOnlyHint is (name not in WRITE_TOOLS)
    assert not annotations.destructiveHint
    assert (annotations.openWorldHint is False) is (name in LOCAL_TOOLS)


@pytest.mark.parametrize("name", sorted(WRITE_TOOLS))
def test_write_tools_say_when_to_use_them(tools, name):
    assert "explicitly ask" in tools[name].description


@pytest.mark.parametrize("name", sorted(set(UPSTREAM_PARAMS) - LOCAL_TOOLS - WRITE_TOOLS))
def test_paged_lists_cap_top_at_200(tools, name):
    top = tools[name].inputSchema["properties"]["top"]
    assert top["maximum"] == 200
    assert top["default"] == 50


def test_instructions_budget():
    assert len(INSTRUCTIONS) <= 1500
    assert "\n" in INSTRUCTIONS


def test_knowledge_base_is_reported_unsupported():
    content, _ = asyncio.run(create_mcp_server().call_tool("kaseya_bms_search_knowledge_base", {"query": "vpn"}))
    error = json.loads(content[0].text)["error"]
    assert error["code"] == "invalid_argument" and "kaseya_bms_list_tickets" in error["message"]


@pytest.mark.parametrize(
    "status,code,retryable",
    [
        (401, "unauthorized", False),
        (403, "unauthorized", False),
        (404, "not_found", False),
        (400, "invalid_argument", False),
        (429, "rate_limited", True),
        (500, "upstream_error", True),
        (0, "upstream_error", True),
    ],
)
def test_error_envelope(status, code, retryable):
    envelope = json.loads(BmsError(status, "boom").to_envelope())
    assert envelope == {"error": {"code": code, "message": "boom", "retryable": retryable}}


def test_tool_without_credentials_returns_not_configured():
    content, _ = asyncio.run(create_mcp_server().call_tool("kaseya_bms_list_tickets", {}))
    assert json.loads(content[0].text)["error"]["code"] == "not_configured"
