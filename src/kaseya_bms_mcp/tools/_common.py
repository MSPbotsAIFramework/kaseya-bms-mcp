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
"""Shared types, paging / envelope helpers and the error-handling wrapper."""

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from .._json import dump_json_capped, error_envelope
from ..api_client import BmsClient, BmsError
from ..config import MAX_PAGE_SIZE

logger = logging.getLogger("kaseya_bms_mcp.tools")

ClientFactory = Callable[[], BmsClient | None]

READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True)
LOCAL = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)
WRITES = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)

NOT_CONFIGURED = error_envelope(
    "not_configured",
    "Kaseya BMS credentials are missing for this request (X-Kaseya-BMS-Tenant-Subdomain plus "
    "X-Kaseya-BMS-API-Token or X-Kaseya-BMS-K1-Token).",
    False,
)

Skip = Annotated[int | None, Field(description="Records to skip; rounded down to a whole page.", ge=0)]


def compact(values: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in values.items() if v is not None and v != ""}


def paging(top: int, skip: int | None) -> dict[str, int]:
    size = min(max(top, 1), MAX_PAGE_SIZE)
    return {"PageSize": size, "PageNumber": (skip or 0) // size + 1}


def result(payload: Any) -> Any:
    """The `Result` member of BMS's {Success, Error, Result} envelope."""
    if isinstance(payload, dict) and "Result" in payload:
        return payload["Result"]
    return payload


def by_name(rows: list[dict], name: str, what: str) -> int:
    """Match ``name`` against a `.../lookup` list's `Name` field (case-insensitive).

    Raises ``ValueError`` naming the known values on a miss, so a tool that calls this
    turns an unmatched name into the standard `invalid_argument` envelope via `run_tool`.
    """
    for row in rows:
        if str(row.get("Name") or "").strip().lower() == name.strip().lower():
            return int(row["Id"])
    options = ", ".join(str(r.get("Name")) for r in rows[:30])
    raise ValueError(f"Unknown {what} {name!r}. Known values: {options}.")


def page(payload: Any, key: str, params: dict[str, int]) -> dict:
    rows = result(payload)
    rows = rows if isinstance(rows, list) else ([] if rows is None else [rows])
    total = payload.get("TotalRecords") if isinstance(payload, dict) else None
    number, size = params["PageNumber"], params["PageSize"]
    more = total is not None and number * size < total
    return compact(
        {key: rows, "count": len(rows), "total": total, "page": number, "has_more": more, "next_skip": number * size if more else None}
    )


async def run_tool(
    name: str,
    client_factory: ClientFactory,
    action: Callable[[BmsClient], Awaitable[Any]],
) -> str:
    """Resolve the caller's client, run ``action``, and always return a string.

    Errors never escape as exceptions: they become the standard error envelope.
    """
    client = client_factory()
    if client is None:
        return NOT_CONFIGURED
    started = time.monotonic()
    try:
        value = await action(client)
    except BmsError as e:
        logger.info("tool=%s outcome=error status=%s ms=%d", name, e.status_code, _ms(started))
        return e.to_envelope()
    except ValueError as e:
        logger.info("tool=%s outcome=invalid_argument ms=%d", name, _ms(started))
        return error_envelope("invalid_argument", str(e), False)
    except Exception as e:  # noqa: BLE001 - tools must never raise
        logger.warning("tool=%s outcome=unexpected error=%s ms=%d", name, type(e).__name__, _ms(started))
        return error_envelope("upstream_error", f"Unexpected error: {type(e).__name__}", True)
    logger.info("tool=%s outcome=ok ms=%d", name, _ms(started))
    if value is None:
        value = {"done": True}
    return value if isinstance(value, str) else dump_json_capped(value)


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
