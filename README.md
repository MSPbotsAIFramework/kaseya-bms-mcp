# Kaseya BMS MCP Server

An [MCP](https://modelcontextprotocol.io) server for the [Kaseya BMS](https://www.kaseya.com/products/bms/)
REST API (v2), the PSA where MSPs run their service desk. It lets an AI agent read service desk
tickets, time entries, client accounts, contacts, contracts, projects/project tasks and the
service catalog and, on explicit request, create tickets and add ticket notes.

- Transport: MCP Streamable HTTP at `POST /mcp`, health probe at `GET /health`
- Stateless and multi-tenant: credentials arrive on every request as HTTP headers and are
  never stored; every tool is listed from the first `tools/list`
- Python 3.12, [uv](https://docs.astral.sh/uv/), FastMCP, httpx
- License: Apache-2.0, Copyright 2026 MSPbots.ai

<div align="center">

## MSPbots Connector

**The MCP Gateway built for MSPs: visible, controlled, and your data stays where it belongs.**

[**Get started at connect.mspbots.ai →**](https://connect.mspbots.ai)

</div>

---

MSPbots Connector gives your AI clients one MCP URL to reach your entire MSP stack (RMM, PSA, documentation, security, finance), and gives you control over who can call which tool and a record of everything that was called.

**Hosted service: [connect.mspbots.ai](https://connect.mspbots.ai)** · Free to use.

### Why Connector

![MSPbots Connector](https://stgoss.mspbots.ai/files/mcp/mspbots-mcp.png)

| | |
|---|---|
| **Visible** | Every tool call is logged: who, which vendor, when. Usage dashboard, CSV export, SIEM streaming. |
| **Controlled** | Role-based, per-tool allowlist. Deny by default. |
| **Protected** | Credentials encrypted per record. AI clients never see your vendor passwords or tokens. |
| **MSP-native** | Built for the MSP stack only: RMM, PSA, documentation, security, finance. |

### Quick start

1. **Sign up** at [connect.mspbots.ai](https://connect.mspbots.ai).
2. **Connect your vendors.** Pick from 150+ connectors and authorize each one on the vendor's own page, or bring your own API keys. No extra vendor accounts needed.
3. **Set access.** Create roles and decide which tools each role may call. Nothing is allowed until you allow it.
4. **Add your MCP URL to your AI client.** Copy the URL from your Connector dashboard into Claude, ChatGPT, Cursor, VS Code, Gemini, Codex, or any MCP-capable client.
5. **Ask your AI to do real work**, and watch every call appear in the audit log.

### Features

**Unified gateway**
- One MCP URL for all your AI clients
- 150+ connectors across the MSP stack
- Custom MCP servers supported, free
- Authorization happens on each vendor's own page; the AI never sees passwords or tokens
- Bring your own credentials: use the vendor API keys you already have
- Multiple accounts per app; connect once, reuse across AI clients
- Tool search: finds the right action for the task
- One sign-in; vendor credentials are injected behind the scenes and OAuth tokens refresh automatically

**Visibility**
- Audit log for every tool call (who, which vendor, when)
- Usage dashboard: call volume, top vendors, error rate, per-user activity
- Export audit logs to CSV, or stream to Loki, Graylog, or LogScale (SIEM)
- Optional recording of tool arguments and result summaries (off by default, enabled per organization)

**Control**
- Per-role, per-tool allowlist, deny by default
- owner / admin / member roles
- SCIM provisioning with Entra ID, Okta, JumpCloud, and Google Workspace

**Security**
- Credentials encrypted one record at a time (AES-256-GCM, per-record key)
- AI clients authenticate with OAuth 2.1 + PKCE
- Vendor responses are scanned for prompt-injection patterns and returned as structured data. This is one layer of defense, not a guarantee against every attack.
- Static egress IP for customer firewall and API allowlisting

### Pricing

**Free.**

Links: [connect.mspbots.ai](https://connect.mspbots.ai) · [mspbots.ai](https://mspbots.ai)

---

## Authentication headers

| Header | Required | Type | Default | Allowed values | Description | Example |
|---|---|---|---|---|---|---|
| `X-Kaseya-BMS-Tenant-Subdomain` | Yes | string | none | tenant name, or a region: `us`, `emea`, `apac` (or the region's API host) | Selects the regional API host; a tenant name means the US host | `emea` |
| `X-Kaseya-BMS-API-Token` | One of the two | string | none | - | A BMS access token (JWT), sent as `Authorization: Bearer` | `your-api-token` |
| `X-Kaseya-BMS-K1-Token` | One of the two | string | none | - | A Kaseya One token; takes precedence when both are set | `your-k1-token` |

How they are used: every call goes to `{region host}/v2/...` with `Authorization: Bearer <token>`.
Region hosts: `https://api.bms.kaseya.com` (US, default), `https://api.bmsemea.kaseya.com` and
`https://api.bmsapac.kaseya.com`. The token is passed through as given: the server does not sign
in or refresh it, so it must be a valid, unexpired token for that BMS instance. (BMS issues
access tokens from `POST /v2/security/authenticate`, which takes a user name, password and
company name.)

A request to `/mcp` without the tenant header, or without either token, gets HTTP 401 naming what
is missing. Unresolved `${...}` placeholders count as missing.

## Tools

All tools return a JSON string. Lists take `top` (page size, default 50, max 200) and `skip` (rounded down
to a whole page) and return `{count, total, page, has_more, next_skip}`. **write** marks tools
that change data.

| Area | Tools |
|---|---|
| Tickets | `kaseya_bms_list_tickets` (filter, status_names, priority_names, queue_names, account, assignee, open_date_from, open_date_to, exclude_completed), `kaseya_bms_get_ticket` (**ticketId**); **write**: `kaseya_bms_create_ticket` (**subject**, **description**, accountId, contactId, priority, status, queueId, issueTypeId, typeId, sourceId, locationId), `kaseya_bms_add_ticket_note` (**ticketId**, **body**, isInternal, noteTypeId) |
| Time | `kaseya_bms_list_time_entries` (startDate, endDate, ticket_id, user_id, account_id, billable) |
| CRM | `kaseya_bms_list_accounts` (filter = account name, account_code, account_type, is_active), `kaseya_bms_list_contacts` (filter = email or account name, account_id, first_name, last_name, is_active) |
| Finance | `kaseya_bms_list_contracts` (filter = contract name, account_name, status, contract_type) |
| Projects | `kaseya_bms_list_projects` (account_id, status_names, start_date_from, start_date_to), `kaseya_bms_get_project` (**projectId**), `kaseya_bms_list_project_tasks` (project_id, account_id, task_name, unassigned, my_projects), `kaseya_bms_get_task_related_items` (**taskId**) — read-only: BMS has no API to create or edit a project or task |
| Service | `kaseya_bms_list_service_catalog` (name), `kaseya_bms_search_knowledge_base` (no API; see below) |

Errors come back as a JSON envelope instead of an exception:

```json
{"error": {"code": "unauthorized", "message": "Kaseya BMS returned HTTP 401 for v2/servicedesk/tickets: Security Error - 978001 : An error occured while trying to process your authentication request.", "retryable": false}}
```

`code` is one of `not_configured`, `unauthorized`, `not_found`, `invalid_argument`,
`rate_limited`, `upstream_error`. BMS can also answer HTTP 200 with `Success: false`; that is
reported as an error too. Reads are retried with backoff on 429, 5xx and network errors; writes
only on 429.

## Run locally

```bash
uv sync
uv run python -m kaseya_bms_mcp          # listens on 0.0.0.0:8080
```

or with Docker:

```bash
docker build --platform linux/amd64 -t kaseya-bms-mcp:dev .
docker run --rm -p 8080:8080 kaseya-bms-mcp:dev
```

Configuration (environment variables, all optional): `MCP_HTTP_HOST` (default `0.0.0.0`),
`MCP_HTTP_PORT` (default `8080`), `LOG_LEVEL` (default `INFO`). Credentials are never read
from the environment.

## Testing example

```bash
# list tools
curl -s http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "X-Kaseya-BMS-Tenant-Subdomain: us" \
  -H "X-Kaseya-BMS-API-Token: your-api-token" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'

# open tickets of one account
curl -s http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "X-Kaseya-BMS-Tenant-Subdomain: us" \
  -H "X-Kaseya-BMS-API-Token: your-api-token" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"kaseya_bms_list_tickets","arguments":{"account":"Example Co","exclude_completed":true,"top":20}}}'
```

Unit tests (no network access needed):

```bash
uv run pytest
```

## Delivery notes

- **Tool count (14, PRD-21214).** The original 10 tool names are kept as an existing contract;
  every earlier parameter is still accepted. 4 read-only tools were added for BMS Projects
  (`/v2/project/...`): the BMS v2 API has no endpoint to create or edit a project or task — only
  the `statuses` admin-config paths are writable — so there is no corresponding write tool.
  `kaseya_bms_list_project_tasks` calls `POST /v2/project/tasks`; despite the verb it is a paged
  list (the body is a filter object), and that response has no `TotalRecords`, so its `has_more`
  always reads `false` even when more rows exist — keep paging on `skip` until an empty page comes
  back.
- **Rebuilt on the documented API.** The official specification is published at
  `https://api.bms.kaseya.com/swagger/v2/swagger.json` (BMS API 2.0). Older versions built the
  host as `https://{tenant}.bms.kaseya.com/api`, which does not exist in DNS, and called routes
  such as `/v2/service/tickets` and `/v2/finance/accounts` that answer 404. Tickets are now
  `/v2/servicedesk/tickets`, accounts `/v2/crm/accounts/summary`, contacts
  `/v2/crm/contacts/summary`, contracts `/v2/finance/contracts/summary`, time entries
  `/v2/timelogs` and the service catalog `/v2/admin/finance/services/lookup`.
- **Credentials unchanged.** The header contract is kept: the token is used as the bearer token
  and the tenant header now only selects the region.
- **Creating tickets.** BMS requires an account, location, priority, status, ticket type, source
  and open date. The tool takes the account's main location, the named (or default) priority, the
  named status (default New), and the ticket type and source of a recent ticket of that account,
  because BMS has no lookup for those two; each can be passed explicitly instead. A missing
  `accountId` is reported instead of guessed.
- **Ticket notes** need a note type: the tool reuses the type of the ticket's existing notes or of
  a note template, or takes `noteTypeId`.
- **Knowledge base.** The BMS API has no knowledge-base endpoint, so
  `kaseya_bms_search_knowledge_base` returns an `invalid_argument` error that points to
  `kaseya_bms_list_tickets`.
- **Not included**: the ticket "card" UI resource of older versions (an MCP Apps HTML view); the
  tools return the same data as JSON.

## License

Apache License 2.0 - see [LICENSE](LICENSE) and [NOTICE](NOTICE).
