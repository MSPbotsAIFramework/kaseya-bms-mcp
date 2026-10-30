# PRD-21214 · Code review

## Round 1 · 2026-10-30 · reviewed 82a8b06 (base 4ca11bf)

Verdict: approved

### Scope

Diff `4ca11bf...3e05dfa` (implementation commit) on `dev/PRD-21214`: new `src/kaseya_bms_mcp/tools/projects.py`
(4 read-only tools), `_by_name` moved from `tools/tickets.py` to `tools/_common.py` as `by_name`,
`server.py` registration + `INSTRUCTIONS` update, `tests/test_tools.py` snapshot update,
new `tests/test_projects.py`, `README.md` tools table / delivery notes. Commit `82a8b06` on top
adds only the Self-test/Handoff sections to `docs/tickets/PRD-21214.md`, no code.

### Verification performed

- `uv sync` (clean, no lockfile change — matches Self-test's "no new dependency" claim; confirmed
  `git diff 4ca11bf...3e05dfa -- pyproject.toml uv.lock` is empty).
- `uv run pytest -q` on `82a8b06` (worktree synced with `main @ 4ca11bf`, matching the sha the design
  and Self-test section were written against): `156 passed, 1 warning in 3.27s`. Same pre-existing
  `StarletteDeprecationWarning` in `tests/test_middleware.py` the Self-test section names; matches
  the claimed count exactly.
- `grep -rnP '[\x{4e00}-\x{9fff}]' --exclude-dir=.git --exclude-dir=.venv .`: one hit, in
  `docs/tickets/PRD-21214.md` (a verbatim Chinese quote from `legs/design.md` S5, explaining why
  Option C was rejected). Not in `src/`, `tests/`, or `README.md`. Matches the Self-test claim.
- Read `src/kaseya_bms_mcp/tools/_common.py`, `tools/tickets.py`, `tools/projects.py`, `server.py`
  in full against the tech design's Data & API contract and Change list — every field name,
  parameter mapping, and error path matches what was designed.
- Confirmed no circular import: `projects.py` imports `_number` from `tickets.py`; `tickets.py`
  does not import from `projects.py`.
- Confirmed the README "MSPbots Connector" section (lines before the Tools table) is untouched by
  the diff, matching the Self-test's "byte-for-byte match" claim.

### Findings

No must-fix findings.

1. [suggestion] `src/kaseya_bms_mcp/tools/projects.py:134` — imports `_number` (underscore-prefixed,
   module-private by convention) from `tools/tickets.py` rather than promoting it to `_common.py`
   alongside `by_name`. Flagged, not blocking: the Self-test section already calls this out as a
   deliberate, narrower choice (2 modules sharing a private helper doesn't yet meet the "second
   consumer" DRY bar the design applied to `by_name`), and it costs nothing functionally. If a
   third module ever needs `_number`, that is the natural point to move it to `_common.py`.
2. [suggestion] `src/kaseya_bms_mcp/tools/projects.py:149` — `status_names` resolution against
   `/v2/project/statuses/lookup` does not filter out inactive statuses the way `tickets.py`'s
   `_status_id` does for ticket-creation defaults. Documented and reasoned in the Self-test section
   (a caller naming a specific, possibly-deactivated status to filter by is a different case than
   picking a default), and no AC requires the opposite behavior. Worth a one-line note in
   `kaseya_bms_list_projects`'s own docstring in a follow-up, since the asymmetry with
   `tickets.py`'s pattern (both now sharing `by_name`) isn't obvious from the code alone.

### Design/AC coverage check

AC1–AC9 each map to an implemented tool/behavior and a passing test in `tests/test_projects.py`
or `tests/test_tools.py`; TC-KBMS-001 through 011 all have command + result evidence in
`docs/tickets/PRD-21214.ac.json`, TC-KBMS-012 is correctly left `blocked` (needs a real BMS
tenant, not available, not a blocker per `mcp-track.md` §2.5/§3). No existing test was weakened or
removed; `tests/test_contract_types.py` (pins the original 10 tools' parameter types) is untouched
and still passes, confirming AC9 (no regression on the pre-existing tool surface).

### Non-functional / cross-cutting

- Multi-tenant isolation: no new module-level or shared state; new tools go through the same
  `get_client_from_context()` contextvar path as the existing ten. No new header introduced.
- No schema/migration (service is stateless) — not applicable here.
- No new third-party dependency.
- Purely additive, backward-compatible change (`SKILL.md` "主线 B" §B3): no renamed/removed tool,
  no removed/tightened required parameter, no changed error code — does not require pre-notifying
  the platform side.

Status: frozen @ 82a8b06
