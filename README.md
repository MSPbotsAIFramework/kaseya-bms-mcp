# Kaseya BMS MCP Server

An [MCP](https://modelcontextprotocol.io) server for the [Kaseya BMS](https://www.kaseya.com/products/bms/)
REST API (v2), the PSA where MSPs run their service desk. It lets an AI agent read service desk
tickets, time entries, client accounts, contacts, contracts and the service catalog and, on
explicit request, create tickets and add ticket notes.

- Transport: MCP Streamable HTTP at `POST /mcp`, health probe at `GET /health`
- Stateless and multi-tenant: credentials arrive on every request as HTTP headers and are
  never stored; every tool is listed from the first `tools/list`
- Python 3.12, [uv](https://docs.astral.sh/uv/), FastMCP, httpx
- License: Apache-2.0, Copyright 2026 MSPbots.ai

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

All tools return a JSON string. Lists take `top` (page size, max 500) and `skip` (rounded down
to a whole page) and return `{count, total, page, has_more, next_skip}`. **write** marks tools
that change data.

| Area | Tools |
|---|---|
| Tickets | `kaseya_bms_list_tickets` (filter, status_names, priority_names, queue_names, account, assignee, open_date_from, open_date_to, exclude_completed), `kaseya_bms_get_ticket` (**ticketId**); **write**: `kaseya_bms_create_ticket` (**subject**, **description**, accountId, contactId, priority, status, queueId, issueTypeId, typeId, sourceId, locationId), `kaseya_bms_add_ticket_note` (**ticketId**, **body**, isInternal, noteTypeId) |
| Time | `kaseya_bms_list_time_entries` (startDate, endDate, ticket_id, user_id, account_id, billable) |
| CRM | `kaseya_bms_list_accounts` (filter = account name, account_code, account_type, is_active), `kaseya_bms_list_contacts` (filter = email or account name, account_id, first_name, last_name, is_active) |
| Finance | `kaseya_bms_list_contracts` (filter = contract name, account_name, status, contract_type) |
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

- **Tool count (10).** Kept as is because the tool names are an existing contract; every earlier
  parameter is still accepted.
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
