# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- `get_devices` (`status=`) returned nothing for every status: it filtered on `hostStatus:0`
  to `hostStatus:4`, which match nothing on a live portal. It now sends the quoted word
  (`hostStatus:"dead"`); an unquoted word is rejected by the API. This also fixes
  `portal_overview`, whose dead-device list was always empty.
- The diagnostic and remediation execution guard checked `hostStatus == 1`, but the API
  returns `"dead"`, so a dead device was never refused up front. It now accepts either form.
- The filter, enum, schema and guide resources and the remediation prompt taught numeric
  `hostStatus` filters. On a live portal `hostStatus:0` matches nothing and `hostStatus!:0`
  matches every device. They now teach the quoted words, and a test fails if a numeric
  `hostStatus` filter comes back.

### Added

- `LM_HTTP_AUTH_TOKEN`: opt-in inbound bearer authentication for the HTTP
  transport. When set, `/mcp` and `/api/v1/*` require
  `Authorization: Bearer <token>` (constant-time comparison) and return 401
  with `WWW-Authenticate: Bearer` otherwise; `/`, `/health`, `/healthz`, and
  `/readyz` stay open for container healthchecks and orchestrator probes.
  Unset preserves previous behavior and logs a startup warning. Minimum token
  length 16; a blank value means unset, and surrounding whitespace is stripped
  so a token read from a secret file still matches. The scheme is matched
  case-insensitively per RFC 7235, and probe paths match with or without a
  trailing slash. Stdio is unaffected.
- `CONTRIBUTING.md`: fork-and-pull-request workflow, development setup, PR
  expectations, and the tool-surface regeneration commands.
- `deploy/k8s/deployment.yaml`: vendor-neutral Kubernetes Deployment and
  Service for the published container image, with credentials read from a
  user-created secret and probes wired to the health endpoints.
- `.pre-commit-config.yaml`: local hooks mirroring the blocking CI gates (ruff
  check and format on `src/` and `tests/`, file hygiene, private-key guard).
  Install with `uv run pre-commit install`; `pre-commit` is now a dev dependency.
- `.github/pull_request_template.md`: prompts contributors for a summary,
  changes, test plan, and rollback note.
- CI step that regenerates the tool contract fixture and `documentation/tools.md`
  and fails with the exact regeneration commands when either is stale.

### Changed

- `deploy/docker-compose.yml` now publishes the plaintext port on loopback
  (`127.0.0.1`) instead of every interface. That port is published whether or
  not the `tls` profile is active, so a TLS deployment was still exposing an
  unencrypted listener that would carry `LM_HTTP_AUTH_TOKEN` in cleartext.
  Caddy is unaffected, since it reaches the service over the compose network.
  Set `LM_HTTP_BIND=0.0.0.0` to serve plaintext to other hosts deliberately.
- `deploy/docker-compose.yml` no longer defaults `LM_CORS_ORIGINS` to `*`.
  Deployments that relied on the implicit wildcard should set an explicit
  origin list rather than restoring `*`: CORS runs with
  `allow_credentials=true`, so a wildcard lets any site a browser visits call
  `/mcp` with the visitor's credentials.

### Fixed

- Configuration validation errors no longer echo the rejected value, which
  previously put a too-short `LM_HTTP_AUTH_TOKEN` or `LM_BEARER_TOKEN` into the
  startup traceback, container logs, and the health endpoint's response body.
- `lm_mcp.__version__` synced to the release version (the published 4.2.0 wheel
  self-reports "4.1.0" at the HTTP root endpoint); the foundation test now
  asserts `__version__` against the installed package metadata so a bump that
  misses `__init__.py` fails the suite instead of shipping.
- HTTP transport `tools/list` now includes the Terraform tools when a Terraform
  runner is configured. They were dispatchable over HTTP but invisible to HTTP
  clients, unlike stdio which listed them correctly.
- Documentation: removed the `LM_ANALYSIS_TTL_MINUTES` row from the README
  (not a config field), corrected the `LM_CORS_ORIGINS` default, and dropped a
  `.gitignore` negation for a file that does not exist.

## [4.2.0] - 2026-08-11

Optional **multi-portal mode**: a single server can serve many customer portals,
selecting the active one at runtime, instead of running one server (and pasting one
token) per portal. With `LM_MULTI_PORTAL=true` the server no longer binds to a fixed
portal + token at startup — it loads a credential vault and switches portals on
demand, so the full tool set is registered once rather than per portal. Core LM tools
273 -> 277 (full surface 306). Single-portal behavior is unchanged.

### Added

- `list_portals` -- list the portals in the vault (name, host, auth type, writable).
  Returns metadata only; never a token.
- `use_portal` -- make a portal active for subsequent tool calls (builds and caches a
  LogicMonitor client per portal on demand).
- `current_portal` -- show the active portal.
- `reload_portals` -- re-read the vault so portals added/removed since startup take
  effect without a client restart (keeps the active portal if it still exists).
- New `portals` grouping in search_tools and the tool-categories resource (not an
  `LM_MCP_CATEGORIES` token; portal tools are exempt from category filtering in
  multi-portal mode).

### Behavior and safety

- Credentials load from an age-encrypted vault (`LM_VAULT_FILE` + `LM_AGE_KEY`) or a
  plaintext JSON file (`LM_PORTALS_FILE`, testing only) instead of the environment.
- Read-only by default per portal: a write requires both `LM_ENABLE_WRITE_OPERATIONS=true`
  and `"writable": true` on that portal's vault record (error code `PORTAL_READ_ONLY`).
- Data tools return a clear "No portal selected" message until `use_portal` is called.
- Single-portal mode is preserved: without `LM_MULTI_PORTAL`, a fixed `LM_PORTAL` is
  still required (fail-fast retained), and behavior matches previous releases.

### Config

- `portal` is now optional (multi-portal selects at runtime); added `multi_portal`,
  `vault_file`, `age_key`, and `portals_file`. Authentication validation is skipped in
  multi-portal mode; `base_url` guards a missing portal.

### Fixed (multi-portal hardening)

- Multi-portal mode is stdio-only: config construction rejects it with the HTTP
  transport, whose process-global client would leak the active portal across
  concurrent callers (this also removes the unreachable-healthy `healthz` state).
- Portal tools are hidden and rejected outside multi-portal mode; a vault in the
  environment can no longer repoint a single-portal server or bypass the per-portal
  write gate.
- Multi-portal config fails fast at startup when no vault source is configured;
  vault paths expand `~`; the encrypted vault takes precedence over
  `LM_PORTALS_FILE` with a warning when both are set.
- age failures surface stderr, a missing age binary gets a clear error, and
  decryption has a 30s timeout.
- Vault record hostnames are normalized like `LM_PORTAL` (scheme stripped,
  validated); one invalid record warns instead of breaking the vault.
- `reload_portals` is atomic (a failed reload leaves the old registry, active
  portal, and client intact) and closes replaced clients instead of leaking
  connection pools; shutdown clears the global client reference.
- `LM_MCP_CATEGORIES` no longer filters out the portal tools in multi-portal mode
  (the documented Cursor recipe previously made the mode unusable).
- `search_tools`, `get_reference`, and `get_workflow` work before a portal is
  selected.
- Terraform tools return a clear unsupported error in multi-portal mode instead of
  running with no credentials.
- `portal_url` deep links use the active portal instead of emitting
  `https://None/...`; `ingest_url` guards a missing portal.
- The write gate reports "No portal selected" before claiming a portal is
  read-only; portal switches are recorded in session history and the write audit
  log, and audit lines carry the active portal name.
- Deploy scripts and MULTIPORTAL.md: `lm-mcp-add.sh` creates the age identity on
  first run (the referenced vault setup now exists), the launcher honors
  `LM_PORTALS_FILE` and falls back to the published package when no clone is
  present, hardcoded personal paths are gone, and the manual re-encrypt snippet
  can no longer truncate the vault via an unset variable.

## [4.1.0] - 2026-06-11

Native OTLP metrics query surface. LogicMonitor's new OTLP Metrics feature
(feature-flag gated, AMP/Prometheus-backed; its only UI surface in this first
phase is the dashboard Advanced Metrics Widget, with Metrics Explorer arriving
later) gets its first programmatic client: four read tools wrapping the v3
`/metrics` query APIs, live-validated against a flag-enabled portal fed by a
real OTel collector. Core LM tools 269 -> 273 (full surface 302).

### Added

- `get_otlp_metric_names` -- list/autocomplete metric names (`contains` substring
  filter; wildcards are not supported by the backend).
- `get_otlp_metric_labels` -- label names across all metrics or narrowed to one
  metric (`label_name` substring filter).
- `get_otlp_label_values` -- values observed for one label key, optionally narrowed
  to a metric.
- `query_otlp_metrics` -- PromQL range queries via `POST /metrics/query-range`,
  returning normalized time-series matrices (`[timestamp, value]` point pairs,
  `__name__` lifted out of labels). Output is capped at 20 series and 500 points
  per series via even-stride downsampling, flagged with `truncated` plus guidance.
- New `otlp_metrics` tool category (search_tools and the tool-categories resource).

### Behavior notes (live-verified against the real backend)

- Under `X-Version: 3` these endpoints return bare bodies (no standard envelope),
  and omit the `data` key entirely when nothing matches; tools normalize both.
- Feature-unavailable portals are handled gracefully: flag-disabled portals return
  404 (routes absent) and flag-deployed-but-off portals return an explicit 400;
  both become a clear "OTLP Metrics is not available on this portal" notice.
- Backend failures reported as HTTP 200 with an `errors` array are detected and
  surfaced as proper error envelopes.
- Query windows wider than ~30 days are rejected by the metrics backend; the
  tool descriptions steer toward narrower windows and larger steps.

### Validation

- The v4.0.0 deferred live write validation was completed against a live portal
  in this release cycle: diagnosticsource and remediationsource CRUD lifecycles
  (create/get/update-with-confirm/delete), report execution polling
  (`run_report` -> `get_report_execution`), and the full Tier 3 path -- manual
  `execute_diagnostic` (plain `hostId`+`diagnosticId` body confirmed; the
  response carries `hostDiagnosticSourceId`), assignment materialization via
  `get_diagnostic_remediation_assignments`, and end-to-end execution-results
  retrieval with captured script output via
  `get_diagnostic_remediation_results`.
- The action chain / action rule write lifecycle remains validated by mocked
  tests only: the validation portal's API token lacked the action-chain write
  permission (the API returns Permission denied). Read paths were live-validated
  in v4.0.0.

## [4.0.0] - 2026-06-11

Correctness major. A full bidirectional diff of the tool surface against the master v3
swagger, backed by live-portal probes, found shipped tools calling endpoints that do not
exist and a new Automated Diagnostics & Remediation (ADR) API surface we lacked. Every
change in this release was validated against a live portal or carries an explicit
deferred-validation note. Core LM tools 251 -> 269 (full surface 298).

### Removed (BREAKING)

Six tools wrapped endpoints that have never existed on any portal (all 404/415 live):

| Removed tool | Replacement |
|---|---|
| `get_cloud_cost_accounts` | none (the `/cost/*` namespace never existed) |
| `get_cost_summary` | none |
| `get_resource_cost` | none |
| `get_remediation_status` | `get_diagnostic_remediation_results` |
| `get_remediation_history` | `get_diagnostic_remediation_results` |
| `get_batchjob_history` | `get_device_data` on the BatchJob instance |

### Changed (BREAKING)

- **`get_cost_recommendations`** remapped onto `GET /cost-optimization/recommendations`
  (the old `/cost/recommendations` 404s everywhere). Params change from
  `cloud_account_id`/`recommendation_type` to `category` (a category DESCRIPTION string,
  e.g. "Idle AWS EC2 instances" -- the API matches descriptions, not enum names, and
  silently ignores unknown values), `status`, and `offset`. Projects the live item shape
  (annualSavings, cloudProvider, criteria, providerConsoleUrl, recommendationStatus).
- **`get_idle_resources`** rebuilt on the same API: idle-type categories are resolved
  dynamically from the categories endpoint (enum names containing `_IDLE`,
  `_UNDERUTILIZED`, `_UNATTACHED`, `_STOPPED`), OR-joined into a description filter, and
  re-filtered defensively client-side. Gains `provider` (aws/azure/gcp, client-side).
- **`get_services`/`get_service`/`get_service_groups`** rewired onto Service Insight.
  The old `/service/services` path is the legacy v1 websites API: it 415s under
  `X-Version: 3`, and under v1 it returns website objects (verified: same object ids as
  `/website/websites`), so these tools have never returned a service. They now query
  `GET /device/devices?filter=deviceType:6` and
  `GET /device/groups?filter=groupType:"BizService"`, expose `name_filter`, and project
  alert/SDT/host status. `get_service` flags non-service devices instead of mislabeling.
- **`get_device_batchjobs`** rewired onto
  `GET /device/devices/{id}/devicedatasources?filter=dataSourceType:"BJ"` (the old
  device batchjobs path does not exist); gains `limit`.

### Added

Automated Diagnostics & Remediation, complete (21 tools):

- `get_diagnostic_remediation_assignments` -- ADR sources assigned to a resource/alert
  (`GET /setting/diagnosticRemediation/list`).
- `get_diagnostic_remediation_results` -- structured execution records: status, trigger
  type, executor, script output, timing (`GET /setting/diagnosticRemediation/
  executionResults`). Replaces audit-log scraping. Window params are epoch milliseconds;
  result timestamps are epoch seconds; cursors rejected when `module_type="both"`;
  per-execution output capped at 10k chars with an `output_truncated` marker.
- `execute_diagnostic` -- manual DiagnosticSource execution with the shared
  pre-execution checklist (device reachable, collector >= 39.200, script review with
  state-mutation warning), now extracted to one implementation shared with
  `execute_remediation`.
- `create_/update_/delete_diagnosticsource` and `create_/update_/delete_
  remediationsource` -- full source CRUD with field normalization and full-replace
  confirm guards. `import_diagnosticsource` (LM Exchange multipart) and
  `export_diagnosticsource`/`export_remediationsource`. `import_remediationsource` is
  deliberately absent: the API has no importjson endpoint for remediationsources.
- Action chains and rules (`/setting/action/*`, 11 tools): `get_/create_/update_/
  delete_action_chain`, `get_/create_/update_/delete_action_rule`, plus
  `set_action_rule_status` for enable/disable without touching matchers. Chain stages
  are client-validated ({id, type: diagnosticSource|remediationSource}).
- `get_report_execution` -- polls `GET /report/reports/{id}/tasks/{taskId}`, closing the
  loop `run_report` documented but never implemented.
- `get_alert_details` gains `include_message` (`needMessage=true`, full alert message
  body); `get_reports`/`get_scheduled_reports` gain `include_nextgen`
  (`showNextGenReports=true`; NextGen reports were previously invisible).
- `update_logicmodule` supports the two new source types (`diagnosticsource`,
  `remediationsource`).

### Fixed

- **`update_logicmodule(mode="apply")` could never apply.** Every `update_<type>` tool
  requires `confirm=true`; the apply path never passed it, so the sub-tool returned
  CONFIRMATION_REQUIRED and `call_sub_tool` raised. The existing apply tests mocked the
  update handler and could not see it. Apply now forwards `confirm=true` (regression
  test asserts the forwarded kwargs).
- `set_action_rule_status` is write-classified via a precise `"set_action_rule"` prefix
  in `WRITE_TOOL_PREFIXES` (a bare `set_` would have reclassified the read-only session
  tools).

## [3.9.0] - 2026-06-05

Correctness and reliability sweep. Started from dashboard/report bugs hit against a
live portal (root causes confirmed against the LM v3 API shapes -- widget placement
lives on the dashboard's `widgetsConfig` keyed by widget id; the report schedule is a
flat cron string, not a nested object) and extended to silent failures that corrupt
health verdicts.

### Added

- **Server instructions** that steer the model to call `search_tools` first and point at
  the composite workflow tools, so the large tool surface is navigated by search rather
  than enumeration (the established pattern for large MCP servers).
- **A tool-contract snapshot test** (`tests/test_tool_contract.py` against
  `tests/fixtures/tool_list.json`) that fails on any accidental change to a tool name,
  parameter, type, required field, description, or schema across all 280 tools.
  Intentional changes regenerate the fixture with
  `uv run python tests/test_tool_contract.py`.
- A `WORKFLOW_TOOLS` membership guard (every tool implemented in `tools/workflows.py`
  must be in the curated set), a `search_tools` coverage test (configured AWX/Terraform
  tools are searchable), and a duplicate-tool-name guard.

### Fixed

- **`create_dashboard(template=...)` silently dropped every widget.** The handler
  copied the exported definition into the create body and POSTed it once; the dashboard
  create endpoint does not accept embedded widgets, so cloning an exported dashboard
  produced an empty one (HTTP 200, `success: true`, zero widgets) while only
  `widgetTokens` survived. `create_dashboard` now creates the shell, recreates each
  widget from the template's `widgets_full` on the new dashboard (old id stripped, new
  `dashboardId` set), and re-applies the exported `widgetsConfig` placement remapped to
  the new widget ids. A single failed widget is logged with stack trace and surfaced as
  a `widget_warnings` entry rather than aborting the clone or vanishing. This makes
  `export_dashboard` -> `create_dashboard` round-trip widgets, not just the shell.
- **`add_widget` silently discarded widget placement.** `columnIdx`/`rowSpan`/`colSpan`
  were sent on the `/dashboard/widgets` body, which the API accepts and discards, so
  every widget landed at the default cell and the position parameters were dead.
  Placement lives on the parent dashboard's `widgetsConfig` (keyed by widget id);
  `add_widget` now writes it there via a PATCH that preserves sibling positions, and
  only when a position is requested (otherwise the portal auto-places). Added a `row`
  parameter for explicit vertical placement.
- **`get_dashboard_widgets` returned null `column`/`row_span`/`col_span` for every
  widget.** It read those off the widget objects, which never carry them; it now sources
  `column`/`row`/`col_span`/`row_span` from the parent dashboard's `widgetsConfig`.
- **`get_dashboards` reported `widget_count: 0` for widget-bearing dashboards.**
  `_count_widgets` only counted `widgetsConfig` as a list or a literal `count` key;
  real portals return a dict keyed by widget id. It now counts the keyed dict, and the
  same helper backs `delete_dashboard`'s count (previously `len(..., [])` on the wrong
  default type).
- **`update_widget` could 400 on echoed read-only fields and could not move a widget.**
  Content updates now strip server-managed read-only fields (`lastUpdatedOn`,
  `lastUpdatedBy`, `userPermission`) before the PUT; placement updates route to the
  dashboard `widgetsConfig` PATCH. `update_dashboard` likewise strips dashboard
  read-only fields (`fullName`, `userPermission`, `groupName`, `groupFullPath`,
  `owner`) before its PUT.
- **`run_report` posted to a nonexistent `/functions` endpoint** and 404'd on every v3
  portal. It now triggers generation via `POST /report/reports/{id}/executions` and
  returns the execution `taskId` and `resulturl` for polling.
- **The report `schedule` was modeled as a nested dict, but the LM v3 field is a flat
  string** (a cron expression; empty means unscheduled) with a separate
  `scheduleTimezone` string. The dict model broke every path: `update_report_schedule`
  raised `TypeError` (`'str' object does not support item assignment`) on a real
  scheduled report, `get_scheduled_reports` raised `AttributeError` calling `.get()` on
  a string, and `create_report` sent a wrong-typed body. `create_report`,
  `update_report_schedule`, `get_scheduled_reports`, and `get_report` now use the flat
  `schedule`/`scheduleTimezone` strings, and `update_report_schedule` strips report
  read-only fields before its PUT.
- **Three health-verdict signals were silently zeroed on API failure**, none logged:
  - `get_collector_health` returned `active_collector_down_alerts: 0` (and
    `is_down: false`) whenever the CollectorDown alert query failed, so a real outage
    could read `collectors_down: 0`. The probe now returns "unknown" instead of 0 on
    failure, sets a per-collector `down_signal_unavailable` flag plus a top-level
    `collectors_down_signal_unavailable` count and warning, and logs the exception.
  - `analyze_blast_radius` treated a failed neighbor lookup as "no neighbors" and a
    failed per-device alert lookup as `has_critical: false`, understating the blast
    radius and reporting alerting devices as healthy. Failures are now logged, the
    device is marked `alert_status_unavailable` with `has_critical: null`, and the
    response carries a `degraded` flag.
  - `get_remediation_history` turned a failed audit-log read (commonly a 403) into the
    benign "no remediation execution records found" note, conflating "could not read"
    with "nothing ran." It now logs the failure and returns a distinct
    `audit_read_failed` note stating history is unavailable, not confirmed empty.
- Added module loggers to `collectors`, `topology_analysis`, and `remediationsources`
  so these degrade-on-failure paths log a stack trace before falling back (per the
  no-silent-except rule).
- **MED/LOW silent-failure hardening** across degrade-on-failure paths, each now logged
  before the fallback:
  - `ingest_post` returned blanket success on an HTTP 202 even when the body reported
    per-record rejections (silent ingestion data loss). It now inspects the 202 body
    and raises on an error envelope or `success: false`.
  - `correlate_changes` turned a failed audit/change-log read into "0 changes"; it now
    sets `audit_read_failed` + a warning so "no changes" is not confused with "could
    not read."
  - the watsonx TTM forecast silently fell back to linear regression; it now logs the
    failure and tags the result with `ttm_fallback_reason` (`watsonx_not_configured`
    vs `watsonx_error: ...`).
  - the `terraform` env-var build and the `get_collector_health` advisory fallbacks
    (downstream device count, collector-down history) now log before degrading.
- Added module loggers to `event_correlation`, `forecasting`, and `terraform`.
- **Composite workflows no longer swallow sub-step failures silently.** In `triage`,
  `health_check`/`diagnose`, and `capacity_plan`, eight bare
  `except Exception: pass / continue / = None` blocks now log via the audit logger and
  surface the failure: the higher-signal ones (blast radius, health score, datasource
  and instance fetches) append to the response `warnings`, and the per-metric
  `capacity_plan` analyses (forecast, trend, seasonality, change points) attach a
  `<field>_error` alongside the `None` so a failure is distinguishable from "no data."
- **The empty/null-id import silent-failure guard now covers all eight `import_*`
  tools.** Previously only `import_datasource` detected a 200 response with no id and no
  error (the wrong-definition-format case); the other seven reported `imported_id: null`
  as a success. All eight now route through a shared `_import_result_response` helper
  that returns `IMPORT_SILENT_FAILURE` for that shape.
- **Registration / discoverability drift.**
  - `LM_MCP_CATEGORIES=workflow` (the documented Cursor 40-tool-cap workaround) silently
    dropped `detect_site_outage` and `audit_network_monitoring_coverage`: the curated
    `WORKFLOW_TOOLS` set was never updated when those v3.8.0 composites landed. Both are
    now included.
  - `search_tools` searched only the core `TOOLS` list, so the 29 AWX/watsonx/Terraform
    tools were unsearchable even when configured (and `search_tools(category="ansible"
    |"terraform"|"watsonx")` always returned empty). It now builds its corpus the same
    way the server advertises tools.
  - `recover_device` and `collect_device_config` mutate the portal but lacked a write
    prefix, so they executed with no audit-log entry; `recover_`/`collect_` were added to
    `WRITE_TOOL_PREFIXES`.
  - Removed the dead, unreachable `ops.get_audit_logs` duplicate (the registry routes
    `get_audit_logs` to the more specific `audit.get_audit_logs`).
  - Corrected stale tool counts in the README (272/225/220 -> 280/240/280).
- **`import_*` LogicModule tools now redirect REST/exported definitions to `create_*`.**
  Feeding a REST API definition (from `export_<type>` or the API) to an `import_*` tool
  made the importjson endpoint reject it with a generic "does not match the expected
  module type" 400, and you had to already know to pivot to `create_*`. The `import_*`
  tools now detect that rejection and return an actionable `IMPORT_FORMAT_MISMATCH` error
  naming the matching `create_*` tool. (`import_*` accepts only LM Exchange JSON;
  `export_*` yields REST format that `create_*` consumes -- the names mislead, so the
  error now says so.)

### Changed

- `add_widget` and `update_widget` expose a `row` parameter and treat `column_index`,
  `row_span`, and `col_span` as 1-indexed grid coordinates clamped to the 12-column
  grid. Omitting all placement on `add_widget` lets the portal auto-place the widget
  below existing ones.
- `create_report` and `update_report_schedule` take a cron schedule string plus
  `schedule_timezone` (replacing the prior nested-dict / `schedule_type` /
  `schedule_enabled` parameters); `get_scheduled_reports` returns the `schedule` string
  and `schedule_timezone`.
- `create_dashboard` accepts a `template_path` to load the dashboard definition (or an
  `export_dashboard` envelope) from a local file by reference, keeping a large export out
  of the model context. There is intentionally no `import_dashboard` tool: dashboards
  have no LM Exchange format, so recreating an export is a create, not an import.

### Documentation

- Slimmed the README from roughly 1380 to roughly 640 lines: the full tool catalog moved
  to `documentation/tools.md`, the per-client configuration matrix to
  `documentation/client-setup.md`, and the example-prompt list and What's New section were
  trimmed. Full version history remains in this changelog.
- `documentation/tools.md` is now generated from the tool registry and the
  `lm://guide/tool-categories` index by `tests/test_tools_doc.py`. Drift guards fail the
  suite when a tool is added without a category or when the committed doc is stale, so the
  tool reference can no longer fall out of sync with the code.

### Verified

- Live-portal read validation of the `widgetsConfig` shape (dict keyed by widget id ->
  {col, row, sizex, sizey}) on dashboards 3 and 15, and of the report
  `schedule`/`scheduleTimezone` flat-string shape on reports 1, 2, and 6.
- Live-portal write validation: a widget placed via `add_widget` persisted its position
  and an `export_dashboard` -> `create_dashboard` clone round-tripped its widget;
  `run_report` reached the executions endpoint and a cron written via
  `update_report_schedule` stored `schedule="0 8 * * 1"` + `scheduleTimezone` (report 6,
  restored afterward).
- New regression tests assert the degraded/unavailable surfacing for the three
  silent-failure fixes (collector down-signal, blast-radius alert lookup, remediation
  audit read).
- Full test suite green; ruff check and format clean. Dashboard and report mock fixtures
  corrected from the prior list / `{"count": N}` / nested-dict-schedule shapes to the
  real API shapes.

## [3.8.3] - 2026-05-18

### Fixed

- **DiagnosticSource and RemediationSource read tools return HTTP 415.** `get_diagnosticsources`, `get_diagnosticsource`, `get_remediationsources`, and `get_remediationsource` were calling the Santaba UI's internal Exchange Toolbox endpoint (`POST /exchange/toolbox/exchange{Diagnostic,Remediation}Sources` with body `{}`). Per LM's internal Action Source API spec, that path with POST is the CREATE verb -- not LIST or GET -- so the API rejected the malformed CREATE payload with 415. Repointed all four tools to the public REST surface `GET /setting/{diagnostic,remediation}sources` and `GET /setting/{diagnostic,remediation}sources/{id}`. This is the same path family every other source tool uses (`get_datasources`, `get_configsources`, etc.) and that LogicMonitor's official PowerShell module canonicalizes for these resources. Filtering is now pushed server-side via the standard LM `filter=name~"x"` query parameter and pagination via `size`/`offset`. `[PREVIEW]` markers removed from the four tools -- they are first-class public reads.
- **LMv1 HMAC signature drift on empty-body requests.** The body-signing path in `client/api.py` checked `if json_body` (truthiness), so an empty dict `{}` was treated as missing and signed against `""` while httpx put `"{}"` on the wire. The mismatch produced 401 on LMv1 portals every empty-body POST/PATCH (`recover_device`, the broken Exchange Toolbox readers above, and anything future that passes `json_body={}`). Bearer-auth portals ignore body in the signature so the bug remained dormant. Fix uses `if json_body is not None`, applied to both `request()` (line 299) and `ingest_post()` (line 520).
- **`calculate_error_budget` JSON-decode crash on inner errors.** When the inner `calculate_availability` call returned a human-readable `"Error: ...\nSuggestion: ..."` envelope (now reachable through the device-lookup fix below), `calculate_error_budget` did a raw `json.loads(avail_result[0].text)` and raised `JSONDecodeError`, which propagated as `"Expecting value: line 1 column 1 (char 0)"`. Routed through `call_sub_tool` so the inner failure surfaces cleanly. Same hardening v3.8.2 applied to workflow composites; `calculate_error_budget` was missed in that sweep.
- **`calculate_availability` device-lookup silent failure.** A 404 or 403 on the device lookup proceeded silently with unfiltered alerts, producing availability numbers for a different device set (or every device in the portal). Replaced the bare `except Exception: pass` with an `LMError`-only catch that returns a structured `DEVICE_LOOKUP_FAILED` envelope.
- **`ingest_logs` and `push_metrics` missing `@require_write_permission`.** Both tools push data into the portal but the decorator was absent, so `LM_ENABLE_WRITE_OPERATIONS=false` did not gate them. Added the decorator and converted the bare `[TextContent(text="Error: ...")]` validation returns to the new `validation_error()` helper for canonical envelope shape.
- **`baselines.save_baseline` and `compare_to_baseline` bare error returns.** Both functions returned `[TextContent(text=f"Error: {e}")]` from their outer except blocks, bypassing `handle_error()`. No structured envelope, no logged stack trace, no `error: true`/`code` fields. Replaced with `return handle_error(e)`.

### Added

- **`lm_mcp.tools.call_sub_tool`** (moved and renamed from `_call_sub_tool` in `workflows.py`). Public helper that calls a sub-handler, parses the JSON response, and raises a clean `RuntimeError` on error envelopes or non-JSON bodies. Now usable from non-workflow composites without copy-paste or circular imports.
- **`lm_mcp.tools.validation_error(code, message, suggestion?)`** helper for canonical input-validation responses. Used by `ingest_logs` and `push_metrics`; available to every tool.
- New regression tests for each of the six fix sites (~15 tests total).

### Tracked Follow-ups

The pre-release audit surfaced additional consistency and silent-failure gaps that are not bundled in v3.8.3 to keep the diff focused. Each will get a dedicated PR:

- Pagination compliance for ~17 list endpoints missing `offset`/`has_more` (sdts, netscans, oids, services, alert_rules, escalations, integrations, device_groups, website_groups, dashboard_groups, collector_groups, roles, batchjobs, api_tokens, device_eventsources, device_logsources, dashboard_widgets).
- Filter-convention rollout: add raw `filter` escape hatch to list tools that currently accept only typed filters.
- Naming: `list_sdts` -> `get_sdts`, `list_session_history` -> `get_session_history` (one release with alias).
- List/singular field parity expansion (`get_devices`, `get_alerts`, `get_collectors`, `logsources` `display_name`).
- Session singleton thread-safety for HTTP transport.
- Method-gated retry on POST 5xx in the client.
- `_LM_ERROR_PATTERNS` coverage: add 415, malformed-enum, and empty-body 400 patterns.
- Workflows.py silent-failure cleanup (~20 bare `except Exception: pass` sites in `triage`, `diagnose`, `audit_network_monitoring_coverage`, `capacity_plan`).
- Expand `IMPORT_SILENT_FAILURE` guard to the 7 sibling `import_*` tools.
- `export_topologysource` missing despite create/import/update/delete being present.

### Verified

- Full test suite passing (1810+ tests).
- Ruff check + format clean.
- LM PowerShell module (`logicmonitor/lm-powershell-module`) cross-referenced as the canonical public-API path source for diagnosticsources and remediationsources.

## [3.8.2] - 2026-04-23

### Fixed

- `_call_sub_tool` (composite dispatch helper) no longer leaks a cryptic `JSONDecodeError: Expecting value: line 1 column 1 (char 0)` when a sub-tool returns an error response. `format_response` renders error dicts as human-readable `"Error: <message>\nSuggestion: <suggestion>"` text, which is not JSON. `_call_sub_tool` now detects that shape and raises a clean `RuntimeError` carrying the underlying message. Benefits every composite (`triage`, `diagnose`, `health_check`, `capacity_plan`, `portal_overview`, `update_logicmodule`, `detect_site_outage`, `audit_network_monitoring_coverage`), not just the one that surfaced the bug. Also handles truly unexpected non-JSON bodies by surfacing a 200-char snippet for debugging.
- `detect_site_outage` no longer aborts the entire CollectorDown signal when a single collector-health probe fails. Each `collector_id` is now probed under its own try/except; failures accumulate into a single aggregate warning (`"N/M collector health probes failed: collector_id=X: <error>; ..."`) while the remaining collectors continue to be inspected. Surfaced during the v3.8.1 portal smoke test on Ryan's portal: 2 of 4 collectors returned errors (likely orphaned references to deleted collectors) and truncated `collectors_inspected` to 2 entries.

### Added

- Four direct unit tests for `_call_sub_tool` covering happy-path JSON, `"Error:"`-formatted text, non-JSON non-error body, and `{"error": True}` dict shape.
- `test_partial_collector_failures_do_not_abort_loop` covers the multi-collector partial-failure path end-to-end.

### Verified

- Full 1784-test suite passing (4 new `_call_sub_tool` + 1 new partial-failure test + 1 updated assertion).
- Ruff check + format clean.

## [3.8.1] - 2026-04-23

### Fixed

- `detect_site_outage` now correctly enumerates the collectors serving a device group. Previously, `_collector_ids_from_devices` looked for `currentCollectorId` / `preferredCollectorId` on device records, but the formatted `get_devices` sub-tool response renames that field to `collector_id`. The mismatch meant the CollectorDown signal was always zero for the composite when called through the normal dispatch path. Surfaced during the v3.8.0 smoke test on Ryan's portal (500 devices in group 1 reported `collectors_serving_group: 0`). The helper now checks `collector_id` first, with fallback to the raw API field names so raw-data callers still work.
- `_count_dead_devices` now counts LM `hostStatus=2` (dead-collector) in addition to `hostStatus=1` (dead). Both indicate devices not reporting metrics; counting only one under-reported device silence. Also reads the formatted-response `status` field before falling back to the raw `hostStatus`, matching the shape that arrives from the composite's sub-tool dispatch.

### Added

- Six direct unit tests for the `_collector_ids_from_devices` and `_count_dead_devices` helpers covering formatted shape, raw API shape, absent fields, and alertStatus-only fallback.

### Verified

- Full 1779-test suite passing (6 new helper tests).
- Ruff check + format clean.

## [3.8.0] - 2026-04-23

### Added

Networking intelligence release. Eight new tools for interface metrics, NetFlow intelligence, alert burst detection, link flap identification, UPS/PDU event filtering, enriched collector health, site-outage composition, and coverage audit. Answers the class of networking questions operators ask every day and, crucially, detects site-outage signatures (collector down + mass interface-down + UPS on-battery + downstream device silence) that generic AIOps correlation misses.

**Network primitives (5):**

- `get_interface_metrics(device_id, interface, metrics, hours_back)` -- pulls per-interface time-series metrics (default datapoints: RxRate, TxRate, ErrorsIn, ErrorsOut, DiscardsIn, DiscardsOut, InterfaceStatus). Resolves the Interface-family DataSource and instance from an interface name substring, then fetches datapoints via the existing metrics endpoint. Returns structured errors (`INTERFACE_DATASOURCE_NOT_FOUND`, `INTERFACE_NOT_FOUND`) with available-instance suggestions to aid discovery.
- `get_top_talkers(exporter_device_id, hours_back, n, group_by, min_bytes)` -- ranks NetFlow flows for an exporter. Group by `src_ip`, `dst_ip`, `application`, `protocol`, or `src_dst_pair`. Client-side aggregation with percentage-of-total reporting. Graceful "no flows in window" path when the exporter is not configured or the window is empty.
- `detect_alert_burst(group_id, device, datasource_pattern, window_seconds, min_alerts, min_devices, hours_back, severity)` -- sliding-window mass-event detector. Buckets alerts by DataSource, identifies windows where alert count and distinct device count exceed thresholds. Hard-capped at 5000 alerts per window with truncation warning. Used by the site-outage composite but also answers general "did a bunch of things break at once?" queries (DDoS, switch cascade, firmware push failures).
- `get_link_flaps(group_id, device, hours_back, min_transitions, interface_pattern)` -- identifies interfaces with repeated up/down transitions. Regex-matches interface-family DataSources against alert stream, groups by (device, instance), counts transitions, returns top-50 flappers.
- `get_power_events(group_id, device, hours_back, severity, patterns)` -- UPS/PDU alert filter. Default patterns cover APC, Liebert, Eaton, UPS, PDU, Battery, PowerSupply, Power_. Client-side substring match on `dataSourceName` and `alertName`. Returns per-pattern match counts for quick attribution.

**Enriched collector status (1):**

- `get_collector_health(collector_id, collector_group_id, include_history, history_days)` -- augments the thin `get_collectors` with time-since-last-contact, downstream device count (via `/device/devices?filter=currentCollectorId:{id}`), active CollectorDown alert detection, and optional CollectorDown history over a lookback window. Now the preferred query when investigating potential outages.

**Composite workflows (2):**

- `detect_site_outage(group_id, window_seconds, hours_back, detail_level)` -- the headline tool. Chains four signals into a single verdict with confidence score (0-100): CollectorDown on any collector serving the group (+40), mass-interface-down burst (+25), UPS/PDU power events (+25), elevated dead-device count (+10). Verdict thresholds: `>= 70` site_outage_detected, `>= 40` possible_site_outage, `< 40` no_outage_signature. Returns affected scope, triggered signals, actionable recommendations, and per-signal detail available in `full` mode.
- `audit_network_monitoring_coverage(group_id)` -- portal coverage audit. Inventories devices and collectors, counts SNMP-credentialed devices, NetFlow exporters, power-monitored devices, and collector health. Produces prioritized gap list with specific onboarding recommendations (e.g., "0 UPS devices onboarded -- add APC_UPS_Battery or equivalent to enable power-event detection"). Turns prerequisite gaps into actionable consulting output.

### Rationale

The Edwin AI product recently failed to correlate a customer power outage as a single incident. The MCP had a parallel gap: no primitives for interface-level metric queries, NetFlow aggregation beyond a raw flow list, alert burst detection, link flap counting, UPS event filtering, or collector-health enrichment, and no composite that combined these into an outage verdict. This release closes the gap with eight read-only tools that run alongside existing correlation tools and composites. The site-outage composite specifically encodes the signal pattern that generic temporal correlation misses: a collector losing power at the same moment 40 interfaces on 8 switches drop and 3 UPS units switch to battery is one incident, not 51.

### Changed

- Tool count: 243 -> 251 LM tools. Overall surface (LM + AAP + Terraform + watsonx): 272 -> 280.
- `collectors` and `workflows` tool-categories indexes updated with the new entries. Added a `networking` category listing the five primitives.
- Composite dispatch remains unchanged -- all new tools live in the LM dispatch path.

### Verified

- 1773 unit tests passing (80 new).
- Ruff lint and format clean across `src` and `tests`.
- No `hostGroupIds~` regressions in new code (all group-scoped queries use `resolve_group_filter` per `docs/lessons.md`).

## [3.7.3] - 2026-04-20

### Fixed

- `create_http_integration` now copies the active-lifecycle `url`, `method`, `payload`, `payloadFormat`, and `headers` into each enabled lifecycle that does not already override them. LM rejects a create with `ackUrl is null or empty, ackMethod is null or empty, ...` when an enabled lifecycle lacks these fields; the LM web UI silently defaults them to the active values, but the v3.7.1 MCP tool did not. The live smoke test (`scripts/smoke_http_integration.py`) against a real portal was failing as a result. Explicit per-lifecycle overrides (`ack_url`, `clear_method`, etc.) still take precedence. Lifecycles not listed in `enabled_lifecycles` are left untouched.
- `scripts/smoke_http_integration.py` now posts to `https://example.com/lm-mcp-smoke` instead of `https://example.invalid/smoke`. LM does a DNS check on create; the IANA-reserved `.invalid` TLD fails resolution and surfaces as "Unknown Host" even though the webhook is never actually invoked during create. `example.com` resolves (owned by IANA for docs/examples) and accepts POSTs harmlessly.
- Smoke script now prints the raw tool response on failure instead of crashing with `JSONDecodeError` when the tool returned an error string.

### Verified

- End-to-end live smoke test (create, get, patch, delete) now passes against Ryan's portal.

## [3.7.2] - 2026-04-20

### Added

- **Jackson-aware 4xx error translation**. `_raise_for_status` in the HTTP client now matches LogicMonitor's raw Jackson deserialization errors (`Cannot construct instance of ...$Period`, `Cannot deserialize value of type ...ArrayList<...Recipient...> from Object`, `invalid recipient for stage N`, `admin<N> is not found`, `invalid method <...> for type ARBITRARY`) against a small translation table and rewrites them into actionable `LMError.message` + `LMError.suggestion` values. The raw server text is preserved on `LMError.details` so debugging context is not lost. Five starter patterns; the table is designed to grow as new shapes are seen in the wild.
- **`LMError.details`** -- new optional field on the base exception. Surfaced by `to_dict()` when set. Carries the raw untranslated server message for callers that want to inspect it (logs, debuggers, follow-up tooling).
- **Integration-shorthand recipient** in `create_escalation_chain` and `update_escalation_chain` destinations. Recipients of the form `{type: "integration", integration_name: "<display name>", admin: "<username>"}` are rewritten to the canonical `{type: "admin", addr: "<username>", method: "<display name>"}` form before the request is sent. `method`/`addr` aliases are also accepted. `integration_id` alone is explicitly rejected with an actionable error -- the display name and owning admin must be passed (use `get_integration` to look them up).

### Rationale

Wiring LogicMonitor escalation chains used to fail with multi-line Java stack traces like "Cannot construct instance of com.santaba.server.servlet.rest.v3.pojos.setting.alert.RestEscalatingChainV3$Period" because the LM v3 API forwards Jackson's raw deserialization errors to API clients. That wording names internal POJOs and teaches callers nothing about the fix. After v3.7.2, the same 400 response comes back as "destinations[].period must be null or a Period object" plus a concrete example, and the integration-shorthand rewrite means callers never have to discover the non-obvious `admin+method` form in the first place.

## [3.7.1] - 2026-04-20

### Added

- Custom HTTP Delivery integration CRUD on `/setting/integrations`:
  - `get_integrations(name_filter, type_filter, limit)` -- list integrations with optional `type:"http"` exact-match and `name~` substring filters (LM v3 requires exact quoting on type, wildcards are not supported there).
  - `get_integration(integration_id)` -- full passthrough of the LM definition (field set varies by integration type; `password` and `oAuthClientSecret` are server-masked).
  - `create_http_integration(name, url, ...)` -- creates a `type="http"` integration. Exposes `description`, `http_method`, `headers`, `alert_body`, `alert_body_format`, `alert_data_type`, `username`, `password`, `enabled_lifecycles` (subset of active/ack/clear/update/actionNotes/updateData), per-lifecycle overrides for ack/clear/update, and `extra_fields` for OAuth credentials, `actionNotes*`, `updateData*`, and the `extra` UI metadata blob.
  - `update_http_integration(integration_id, ...)` -- PATCH partial update; only fields explicitly provided are sent.
  - `delete_integration(integration_id)` -- works for any integration type.
  - `headers` accepts a plain `{name: value}` dict (converted to LM's native `list[{HeaderName: value}]` form) or a friendly `[{name, value}, ...]` list.
- `scripts/smoke_http_integration.py` -- one-shot live smoke test that creates a throwaway integration pointing at `https://example.invalid/smoke`, reads it back, patches it, then deletes it. Run post-merge with `LM_ENABLE_WRITE_OPERATIONS=true uv run python scripts/smoke_http_integration.py`.

### Rationale

Before v3.7.1, wiring LogicMonitor to any webhook-style destination (Azure Sentinel, PagerDuty, ServiceNow, Splunk, custom pipelines) required manual UI steps at Settings -> Integrations because the MCP server had no tool for the integration resource. Only `create_alert_rule` and (post-v3.7.0) `create_escalation_chain` worked via MCP. This release closes the gap so a single MCP session can wire the full alert-delivery path end-to-end.

## [3.7.0] - 2026-04-20

### Fixed

- `get_recipient_groups` and `get_recipient_group` now read the LM v3 API's `groupName` field (falling back to `name` for legacy portal responses). Previously these tools read `item.get("name")`, which LM leaves unset on recipient-group reads, so the MCP response surfaced `name: null` for groups that do exist in the portal. The obsolete `group_type` field is no longer surfaced -- it is not part of the v3 `RecipientGroup` model.
- `create_recipient_group` and `update_recipient_group` now post `groupName` to match the LM v3 model. The previous payload used `name`, which the API silently ignored.

### Added

- `create_recipient_group(..., recipients=[...])` accepts a list of Recipient objects at creation time, eliminating the prior two-step create-then-populate workflow. Each recipient is `{type, method, addr, contact}` with `type` and `method` required.
- `update_recipient_group(..., recipients=[...])` accepts a replacement recipient list.
- `get_recipient_groups(..., detail=True)` issues one follow-up GET per group to attach the full recipient list. Off by default to avoid N+1 API calls.

### Changed

- `create_escalation_chain` and `update_escalation_chain` input schemas now describe the Chain object shape (`{type, period, stages}`) and document that `stages` is a list of stage arrays where each stage is a list of Recipient objects. A concrete example covers routing alerts to a Custom HTTP Delivery integration via `{type: "admin", addr: "<username>", method: "<integration display name>"}` -- the reverse-engineered working form. The same guidance is mirrored into the tool docstrings for clients that don't render schema examples.

## [3.6.1] - 2026-04-18

### Added

- `get_reference(category, name, list)`: universal read-only tool that mirrors MCP Resource content (schemas, enums, filters, syntax, guides) over the Tool primitive. Targets clients without full Resource support -- GitHub Copilot cloud agent, OpenAI Codex CLI, Cline. Pass `list=true` (or call with no args) to discover the available (category, name) pairs.
- `get_workflow(name, list, arguments)`: universal read-only tool that mirrors MCP Prompt content for clients without Prompt support. Returns the rendered workflow guidance text. Prefer the composite workflow tools (`triage`, `diagnose`, `health_check`, `capacity_plan`, `portal_overview`) when they exist -- those execute the procedure rather than returning guidance.
- `universal_reference` entry in the tool-categories guide for `search_tools` discovery.
- Seven single-word aliases in `_WORKFLOW_ALIASES` (`schema`, `filter`, `syntax`, `reference`, `guide`, `workflow`, `prompt`) route `search_tools` queries to the two new tools.

### Changed

- `prompts/registry.py`: hoisted the `templates` dict from inside `get_prompt_messages` to a module-level `_TEMPLATES` constant so `tools/reference.py` can import it without duplication. `get_prompt_messages` behavior is unchanged (same signature, same `ValueError` on unknown prompt).
- Tool count: 236 -> 238 (LM), 265 -> 267 (overall: 238 LM + 18 AAP + 10 Terraform + 1 watsonx).
- README release notes consolidated into this CHANGELOG; README now shows only the current version with a link here for full history.

## [3.6.0] - 2026-04-17

### Added

- `LM_MCP_CATEGORIES` env var: filter the visible tool surface by logical category. Categories: `read`, `write`, `delete`, `export`, `import`, `session`, `workflow`. Composes by intersection with `LM_ENABLED_TOOLS`/`LM_DISABLED_TOOLS` -- only narrows, never expands. Useful for clients with tool-count limits (e.g., Cursor's 40-tool cap) and for restricting agent surface to read-only or workflow operations. Default behavior unchanged when env var is unset.
- `update_logicmodule(type, id, changes, mode='preview')` workflow tool: safe partial update for LogicMonitor source types (configsource, datasource, eventsource, logsource, propertysource, topologysource). Exports the current full definition, deep-merges your `changes` onto it, validates required fields, and returns a dry-run diff (`mode='preview'`, default) or applies the merged definition (`mode='apply'`). Prevents the full-replace blanking footgun that has caused two prior production incidents.

### Changed

- The 6 raw `update_<source>` tools (`update_configsource`, `update_datasource`, `update_eventsource`, `update_logsource`, `update_propertysource`, `update_topologysource`) now require `confirm=true` to proceed. Without confirmation they return `CONFIRMATION_REQUIRED` with a pointer to `update_logicmodule` for safe partial updates. This is a soft-breaking change for direct API users who relied on the old default; the rationale is that two prior incidents wiped Groovy scripts via these tools, and LLM-driven callers cannot be relied upon to read docstrings about full-replace semantics.
- `handle_error` now logs unexpected exceptions via `logger.exception()` before returning the sanitized response. Previously, JSONDecodeError / KeyError / ValueError and other non-`LMError` exceptions were silently swallowed without leaving a stack trace, making debugging impossible. LMError instances continue to propagate without logging (they're expected).

### Internal

- New module `src/lm_mcp/categories.py` with annotation-driven categorization plus a curated `WORKFLOW_TOOLS` frozenset.
- `_filter_tools` (server.py), `execute_tool` rejection (server.py), and `check_required_tools` (workflows.py) all honor the new categories filter.
- Tool count: 235 -> 236 (added `update_logicmodule`).

## [3.5.0] - 2026-04-08

### Added

- `delete_configsource`, `delete_eventsource`, `delete_logsource`, `delete_propertysource`, `delete_topologysource` -- delete operations for all LogicModule source types.
- `handle_conflict` and `fields_to_preserve` parameters on all `import_*` tools for safer imports into existing resources.

### Fixed

- `create_*` and `update_*` tools now auto-normalize field names from LM Exchange format and `snake_case` to the REST API's `camelCase`.
- Import tools auto-inject the LM Exchange `type` envelope field when missing.

## [3.4.0] - 2026-04-01

### Added

- REST API `create_*` and `update_*` tools for all LogicModule source types -- ConfigSource, EventSource, LogSource, TopologySource, PropertySource. Enables export -> modify -> update workflows without delete/recreate.

### Fixed

- `update_datasource` description now correctly documents full-replace semantics (name and displayName required).
- All `import_*` tool descriptions clarify LM Exchange format requirement and direct users to `create_*` for REST API format.
- All `export_*` tool descriptions reference both `create_*` and `update_*` for round-tripping.
- Version synced across all locations (was drifted since v3.2.0).

## [3.1.0] - [3.3.0] - 2026-03-25 - 2026-03-30

### Added

- Terraform IaC integration -- 10 tools (later 11 in v3.4.x) for plan/apply/state/import/HCL generation.
- HuggingFace local Granite fallback for TTM forecasting and NL summaries via local models.
- `[huggingface]` optional dependency group (`torch`, `transformers`, `granite-tsfm`, `accelerate`).
- Device config retrieval and audit tools (`get_device_config`, `get_device_config_version`, `collect_device_config`).
- `create_propertysource` REST API tool.
- 5-way dispatch (Session, AWX, WatsonX, Terraform, LM) with graceful degradation when optional integrations are not configured.
- AI inference priority chain: watsonx.ai API > HuggingFace local > statistical/linear fallback.

## [3.0.0] - 2026-03-25

### Added

- IBM watsonx.ai integration (optional, requires `WATSONX_API_KEY`).
- Granite TTM time-series forecasting via `method="ttm"` on `forecast_metric`.
- Granite NL summaries via `summarize=true` on composite workflow tools.
- `watsonx_summarize` standalone tool for ad-hoc data summarization.
- `[ibm]` optional dependency group (`ibm-watsonx-ai`, `pandas`).
- 4-way dispatch (Session, AWX, WatsonX, LM).

## [2.5.0] - 2026-03-24

### Added

- `create_user`, `update_user`, `delete_user` -- full CRUD for user accounts via `/setting/admins` API. Delete fetches username before removal for audit-friendly responses.
- `create_collector_group`, `update_collector_group`, `delete_collector_group` -- collector group management. Delete blocks if collectors are still assigned. Update merges custom properties with existing values.
- `update_ops_note`, `delete_ops_note` -- ops note write operations. Update supports note text, tags, and device/group scopes.
- `update_dashboard_group` -- update dashboard group name, description, or parent ID via PATCH.
- `update_sdt` -- modify scheduled downtimes using fetch-modify-PUT pattern to preserve unmodified fields.
- Tool categories index updated to include all new tools.

## [2.4.0] - 2026-03-24

### Added

- Portal URL links in single-resource detail responses (`get_device`, `get_device_group`, `get_alert_details`, `get_dashboard`, `get_website`). Each response now includes a `portal_url` field linking directly to the resource in the LM portal UI.
- HTTPS transport support via `LM_HTTP_SSL_CERTFILE`, `LM_HTTP_SSL_KEYFILE`, and `LM_HTTP_SSL_KEYFILE_PASSWORD` environment variables. When configured, the HTTP transport starts with TLS via Uvicorn.
- `portal_url()` shared helper in tools init for constructing LM portal UI links.

## [2.3.2] - 2026-03-23

### Added

- `get_alerts` now supports `group_id` parameter to filter alerts by device group. Resolves the group ID to its `fullPath` and uses the `monitorObjectGroups~` filter, which works reliably for Kubernetes clusters and all other device groups.
- `get_alerts` now supports `device_id` parameter to filter alerts by device/resource ID using `monitorObjectId:` filter.
- `resolve_group_filter()` shared helper resolves a group ID to a `monitorObjectGroups~` filter clause via a single API call.
- Alert filter documentation (`filters.py`) now includes `hostGroupIds`, `monitorObjectId`, and `monitorObjectGroups` fields with examples.

### Fixed

- `correlate_alerts`, `get_alert_statistics`, and `score_alert_noise` now use `monitorObjectGroups~` instead of `hostGroupIds~` for group filtering. The `hostGroupIds~` filter does not reliably restrict results to the target group in the LM API.
- `correlate_alerts` and `score_alert_noise` now sanitize the `device` parameter through `sanitize_filter_value()`, matching `get_alerts` behavior.

## [2.3.0] - 2026-03-22

### Added

- `get_device_group` — Fetch full device group detail including `appliesTo` expression and `parentId`
- `get_device_eventsources` — List EventSources applied to a device with alerting status
- `update_device_eventsource` — Enable/disable alerting for an EventSource on a device (write-protected)
- `bulk_delete_devices` — Batch delete up to 100 devices with K8S warnings, soft or hard delete (write-protected)
- `update_collector` — Update collector group, description, failback, and escalation chain (write-protected)
- `delete_collector` — Delete a collector with guardrail blocking deletion if devices are still assigned (write-protected)
- `recover_device` — Restore soft-deleted devices via PATCH with `recover=true` parameter (write-protected)
- `safe_total()` helper for handling LM API negative total sentinel values in paginated responses

### Fixed

- `get_devices` status filter restored to numeric codes (`hostStatus:1` for dead) — the v3 API rejects string values like `hostStatus:dead` with "invalid filter"
- `get_devices` and `get_alerts` no longer return negative totals when the API response is truncated — `safe_total()` applies `abs()` to sentinel values
- `score_alert_noise` weight formula corrected from `repeat_ratio * 3000` / `flap_ratio * 3000` to `* 30` — scores were pegged at 100 for any normal alert volume

### Changed

- `calculate_availability` now post-filters results to the target device, preventing unrelated devices from polluting calculations; added optional `device_name` parameter and safe uptime floor (`max(0.0, ...)`)
- `delete_device` warns when deleting K8S-managed devices (deviceType=8) since Argus may recreate them; includes deleted device audit context
- `update_device` warns when `host_group_ids` changes may not persist on K8S-managed devices
- `get_device_groups` now includes `parentId` and `appliesTo` in list results
- Tool count: 216 -> 223 (205 LM + 18 AAP)

## [2.2.0] - 2026-03-20

### Changed

- CORS default changed from `*` (allow all) to empty string (no CORS by default). HTTP transport users must now explicitly set `LM_CORS_ORIGINS` to enable cross-origin requests.
- `AWX_VERIFY_SSL` default changed from `false` to `true` in setup script
- Expanded ruff lint rules to full recommended set (E/F/I/N/W/UP/B/SIM/RUF)
- Added mypy type checking to CI (non-blocking)
- Pinned uv to 0.9.27 in Dockerfile and CI workflows
- Added Docker layer caching to release workflow

### Fixed

- Setup script (`scripts/add-mcp-to-project.sh`) no longer uses hardcoded path; auto-detects project root

## [2.1.1] - 2026-03-17

### Fixed

- `create_sdt` and `bulk_create_device_sdt` map Device* SDT type names to Resource* before POST, fixing 400 "Invalid type" errors on the v3 API which renamed Device* to Resource* for SDT create endpoints

## [2.1.0] - 2026-03-12

### Added

- `create_sdt` expanded from 2 types (DeviceSDT, DeviceGroupSDT) to all 13 LM API SDT types
- `datasource_id` parameter on `create_sdt` for DeviceDataSourceSDT type
- Generalized Device-prefixed type handling so `deviceId` is sent for all Device* types
- Improved error messages with cloud resource workaround guidance

## [2.0.1] - 2026-03-12

### Added

- `update_device_group` tool for modifying group name, description, AppliesTo, properties, and alerting state with property merging

### Removed

- 10 action chain/rule tools removed (not present on v3 API swagger)
- Action sources guide category renamed to remediation (7 tools retained)

### Changed

- Tool count: 225 -> 216 (198 LM + 18 AAP)

## [2.0.0] - 2026-03-12

### Added

- 5 composite workflow tools (`triage`, `health_check`, `capacity_plan`, `portal_overview`, `diagnose`) combining multiple sub-tools into single calls with summary/full detail levels and partial failure handling
- `search_tools` for keyword-based progressive discovery across all 225 tools
- `calculate_error_budget` for SLO error budget tracking
- `execute_remediation`, `get_remediation_status`, `get_remediation_history` for RemediationSource execution with 8-point pre-execution safety checklist
- Holt-Winters forecasting with auto-selection between linear and exponential smoothing
- IQR and MAD anomaly detection methods alongside existing z-score
- Prediction intervals on forecast results
- Metric presets auto-configure analysis parameters by datapoint name
- 15 enriched prompts with composite shortcuts and argument parsing
- 2 new resources (best-practices, example-responses)
- Common mistake notes on 6 frequently misused tool descriptions

### Changed

- Scoring tools return structured best-practice recommendations and anti-patterns when thresholds are breached
- Tool count: 215 -> 225 (207 LM + 18 AAP), prompt count: 14 -> 15, resource count: 24 -> 26

## [1.9.6] - 2026-03-11

### Fixed

- `get_widget`, `update_widget`, `delete_widget` use flat `/dashboard/widgets/{id}` endpoint instead of nested path that returned 404
- `add_widget` applies deviceSLA default fields (daysInWeek, periodInOneDay, displayType, calculationMethod, unmonitoredTimeAlertStatus) that the portal UI sets automatically
- `add_widget` remaps common field name aliases (`deviceGroupFullPath` -> `groupName`, `html` -> `content`) to prevent silent data loss from LM API discarding unknown fields
- `get_dashboards` prefers `numOfWidgets` over unreliable `widgetsConfig` for widget count

### Changed

- `add_widget` description documents text widget `content` key and deviceSLA required fields

## [1.9.5] - 2026-02-27

### Added

- Action Sources integration: 14 tools for diagnostic and remediation workflows
  - Action chains: get, create, update, delete
  - Action rules: get, create, update, delete
  - Diagnostic sources: list, get details
  - Remediation sources: list, get details
- All Action Sources tools marked `[PREVIEW]` — API endpoints are not yet GA in LM portals

### Removed

- Event-Driven Ansible (EDA) tools removed from deployed package (20 tools)
  - EDA required standalone infrastructure not available through LM Portal
  - Source code preserved in `contrib/eda/` for future reference
  - `/lm-eda` skill removed

### Changed

- Tool count: 221 -> 215 (197 LM + 18 AAP)
- Skill count: 7 -> 6
- Dispatch simplified from 4-way (session -> EDA -> AWX -> LM) to 3-way (session -> AWX -> LM)

## [1.9.2] - 2026-02-25

### Fixed

- EDA create tools now include required `organization_id` parameter (default 1 = "Default" org)
- `create_eda_event_stream` now requires `eda_credential_id` parameter (EDA API requirement)
- `create_eda_project` sends `organization_id` in request body
- `create_eda_activation` sends `organization_id` in request body

## [1.9.0] - 2026-02-25

### Added

- Event-Driven Ansible integration (20 tools) for automated event response
- EdaClient HTTP client with Bearer token auth, retry logic, and error mapping
- Activation management: list, get, create, enable, disable, restart, delete
- Activation instance monitoring with log retrieval
- EDA project management: list, get, create, sync from Git
- Rulebook queries: list, get (populated via project sync)
- Event stream management: list, get, create, delete
- Write-protected tools: create/enable/disable/restart/delete activations, create/sync projects, create/delete event streams
- `test_eda_connection` tool for verifying EDA Controller connectivity
- EDA_URL, EDA_TOKEN env vars (optional — EDA tools excluded if not set)
- `/lm-eda` Claude Code skill: event-driven alert automation workflow
- 4-way dispatch in server: session -> EDA -> AWX -> LM
- `add_device_instance` — Create datasource instances on a device (for datasources without Active Discovery)
- `update_device_instance` — Update instance properties (display name, description, monitoring, alerting)
- `delete_device_instance` — Delete a datasource instance from a device

### Fixed

- AAP check_mode (dry run) now sends `job_type: "check"` to the controller, preventing accidental execution during dry runs

### Changed

- Tool count: 198 -> 221 (183 LM + 18 AAP + 20 EDA)
- Skill count: 6 -> 7
- Tool categories guide updated with "eda" domain
- Write audit logging expanded with enable/disable/restart/sync prefixes

## [1.8.0] - 2026-02-19

### Added

- Ansible Automation Platform integration (18 tools) for observability-driven remediation
- Tool categories: job templates, job execution, inventories, workflows, projects, credentials, organizations, hosts
- Write-protected tools: launch_job, launch_workflow, cancel_job, relaunch_job (require LM_ENABLE_WRITE_OPERATIONS=true)
- Jinja2 injection protection on all extra_vars inputs
- `/lm-remediate` Claude Code skill: 10-step diagnosis-to-remediation workflow
- `remediate_workflow` MCP prompt for non-Claude-Code MCP clients
- Job template naming convention: `lm-remediate-<category>-<action>` for automatic discovery
- Example playbooks: disk-cleanup, service-restart, log-rotate, memory-cache-clear
- Skill structure tests validating all 6 skills against the tool registry
- `test_awx_connection` tool for verifying AAP connectivity
- AWX_URL, AWX_TOKEN env vars (optional — AAP tools excluded if not set)

### Changed

- Tool count: 180 -> 198 (180 LM + 18 AAP)
- Prompt count: 13 -> 14
- Skill count: 5 -> 6
- Tool categories guide updated with "ansible" domain

## [1.7.2] - 2026-02-18

### Fixed

- **`update_device` custom_properties merge** — Custom properties are now merged with existing properties instead of replacing them. Prevents silent data loss when updating a subset of custom properties on a device.
- **`update_device_property` create-on-404** — Falls back to POST (create) when PUT returns 404 for a property that doesn't exist yet. Matches the tool description "Update or create a device property".
- **`get_devices` filter validation for dot-notation fields** — Custom property filter queries like `customProperties.name:"env"` no longer fail schema validation. Dot-notation fields are now skipped during field validation since the LM API handles them natively.
- **Import tools string definition handling** — All import tools (`import_datasource`, `import_configsource`, etc.) and `post_multipart()` now handle definitions that arrive as JSON strings instead of dicts, preventing double-serialization of complex embedded content (e.g., Groovy scripts with escape characters).

### Added

- **`update_datasource`** — Update an existing DataSource definition via PUT.
- **`delete_datasource`** — Delete a DataSource definition by ID with confirmation.
- **`hostname_filter` on `get_devices`** — Filter devices by hostname or IP address (the `name` field). The existing `name_filter` parameter searches `displayName`; the new parameter searches the actual hostname/IP.
- **`overwrite` on `create_datasource`** — When `true`, deletes any existing DataSource with the same name before creating. Provides explicit upsert semantics without hidden behavior.

### Changed

- **`update_device` description** — Now documents merge behavior for custom properties.
- **`get_devices` filter description** — Documents custom property query syntax with proper quoting examples.
- **`get_devices` `name_filter` description** — Clarified as "display name" filter to distinguish from the new `hostname_filter`.

Tool count: 178 -> 180.

## [1.7.1] - 2026-02-17

### Fixed

- **HTTP 200 error body detection** — API client now checks for `errorMessage` + `errorCode` inside HTTP 200 response bodies and raises `LMError` with code `API_ERROR_{errorCode}`. Some LM API endpoints return HTTP 200 with error details in the body instead of using HTTP status codes; these previously passed through silently as success.
- **`add_widget` endpoint URL** — Changed from `/dashboard/dashboards/{id}/widgets` (returns 405) to `/dashboard/widgets`. The `dashboardId` field in the request body specifies which dashboard the widget belongs to.
- **`import_datasource` silent failure detection** — Now detects empty `{}` responses (no `id` or `errorMessage`) and returns an error noting the import may have silently failed, with guidance to use `create_datasource` for REST API format definitions.

### Added

- **`create_datasource`** — Create a DataSource via REST API from a full definition dict. Accepts the same format as `export_datasource` output, enabling round-tripping of exported definitions. Strips `id` from the definition before POST.

### Changed

- **Export/import format documentation** — Updated descriptions for `export_datasource`, `import_datasource`, and `create_datasource` to clarify the difference between REST API format (used by export/create) and LM Exchange format (used by import).
- **`add_widget` description** — Added format guidance for common widget types (bigNumber, cgraph) including GlobMatchToggle objects and aggregateFunction casing.

Tool count: 177 -> 178.

## [1.7.0] - 2026-02-17

### Added

5 Claude Code skills providing guided multi-step workflows for common LogicMonitor admin operations. Skills ship in the repo so anyone cloning it gets them automatically via `.claude/skills/`.

- **`/lm-triage`** — Alert triage workflow: gathers active alerts and statistics, scores noise level, clusters correlated alerts, performs deep dive with blast radius analysis, checks change correlation, and presents numbered action options (acknowledge, add note, bulk acknowledge). Write actions require explicit confirmation.
- **`/lm-health`** — Device health check: resolves device by ID or name, inventories datasources by category (CPU/Memory/Disk/Network), pulls core metrics, computes health score with decision tree, runs anomaly detection on degraded datasources, checks alert status, device properties, 30-day availability, and topology neighbors. Produces a compiled health report.
- **`/lm-portal`** — Portal-wide health snapshot for shift handoff: alert severity breakdown with trends, collector status (flags any down collectors), active SDT windows, top 5 alert clusters, noise scoring, down device count with collector correlation heuristic. Outputs a GREEN/YELLOW/RED portal status.
- **`/lm-capacity`** — Capacity planning and forecasting: current utilization across CPU/Memory/Disk, trend classification (stable/increasing/decreasing/volatile), seasonality detection, change point detection, breach forecasting with urgency tiers, and baseline comparison. Offers to save baselines with confirmation.
- **`/lm-apm`** — APM trace investigation: service discovery, service profile with properties, service-level RED metrics, operation breakdown sorted by volume, per-operation deep dive, datasource coverage check, and alert correlation. Supports both targeted service investigation and discovery mode.

### Changed

- `.gitignore` updated to track `.claude/skills/` while keeping other `.claude/` contents ignored.

## [1.6.1] - 2026-02-17

### Fixed

- **Import tools send wrong Content-Type** — All 8 `import_*` tools now use `multipart/form-data` file upload via `post_multipart()` instead of `application/json` POST. The LM import endpoints require multipart upload; the previous JSON body approach silently failed.
- **Unhandled 4xx status codes returned as success** — `_raise_for_status()` now has a catch-all for 400-499 status codes (400, 405, 409, 415, etc.) that raises `LMError` with code `HTTP_{status}`. Previously these fell through and returned error response bodies as if they were successful results.
- **Export/import format mismatch documented** — Updated docstrings on all export and import functions to clarify that REST API export format differs from LM Exchange format required by import endpoints.

### Added

- **`create_dashboard` template and widget token support** — `create_dashboard` now accepts `widget_tokens` (list of token overrides) and `template` (full dashboard definition from `export_dashboard` to clone from). When using a template, the exported definition is used as the base payload with name overridden and id stripped.
- **`create_dashboard_group`** — Create dashboard groups with optional parent_id and description. Follows the same pattern as `create_website_group`.
- **`delete_dashboard_group`** — Delete dashboard groups by ID. Follows the same pattern as `delete_website_group`.
- **`post_multipart()` client method** — Handles multipart/form-data file uploads for LM import endpoints with proper auth headers and retry logic.

Tool count: 175 -> 177.

## [1.6.0] - 2026-02-16

### Added

8 APM trace tools for service discovery and RED metrics via the v3 API. APM services are stored as `deviceType:6` devices with `LogicMonitor_APM_Services` and `LogicMonitor_APM_Operations` datasources.

- **`get_trace_services`** — Lists all APM trace services by filtering for deviceType:6. Entry point for discovering which services are instrumented. Supports namespace filtering for substring matching on service names.
- **`get_trace_service`** — Gets full device detail for a specific APM service, including status, groups, and configuration.
- **`get_trace_service_alerts`** — Gets active alerts for an APM service with optional severity filtering (critical, error, warning, info). Bridges traces and alerting.
- **`get_trace_service_datasources`** — Lists datasources applied to an APM service (LogicMonitor_APM_Services, LogicMonitor_APM_Operations, etc.). Required step before querying instances or metric data.
- **`get_trace_operations`** — Lists operation instances (endpoints/routes) for an APM service datasource. Each operation has its own RED metrics.
- **`get_trace_service_metrics`** — Gets service-level time-series data for Duration, ErrorOperationCount, OperationCount, and UniqueOperationCount. Supports time range and datapoint filtering.
- **`get_trace_operation_metrics`** — Gets per-operation RED metrics for a specific endpoint/route. Same API shape as service metrics but scoped to an individual operation instance.
- **`get_trace_service_properties`** — Gets device properties for an APM service including OTel attributes, namespace info, and auto-discovered metadata. Supports name filtering.

Tool count: 167 -> 175. Added "traces" category to tool-categories guide resource.

## [1.5.1] - 2026-02-14

### Added
- ML tool usage guide with detailed examples for capacity forecasting, metric correlation, change point detection, noise scoring, health scoring, and availability calculation
- ML Analysis & Forecasting example prompts section (10 natural language examples)
- Updated project structure with new tool files

## [1.5.0] - 2026-02-14

### Added

10 ML/statistical analysis tools using pure-Python implementations (no numpy/scipy dependencies).

- **`forecast_metric`** — Predicts when a metric will breach a threshold. Uses linear regression on historical data to calculate trend direction, slope, and estimated days until breach. Useful for capacity planning — point it at CPU, memory, or disk and set a threshold to get an early warning.
- **`correlate_metrics`** — Computes a Pearson correlation matrix across up to 10 metric series. Helps answer "are these metrics related?" — for example, does CPU spike when memory does? Highlights strong correlations (|r| > 0.7) automatically. Each source can be from a different device.
- **`detect_change_points`** — Finds moments where metric behavior shifted using the CUSUM algorithm. Instead of just looking at whether a value is high or low, it detects when the pattern changed — a sudden jump, a drop to a new baseline, or a regime shift. Sensitivity is configurable.
- **`score_alert_noise`** — Scores how noisy your alert environment is on a 0-100 scale. Combines Shannon entropy (how spread out alerts are across sources), flap detection (alerts that clear and re-fire within 30 minutes), and repeat ratio. Returns the top noisy devices and datasources with tuning recommendations.
- **`detect_seasonality`** — Checks whether a metric has a repeating pattern using autocorrelation. Tests standard intervals (1h, 4h, 6h, 8h, 12h, 24h, 7d) and reports which periods show strong periodicity. Useful for distinguishing "this spikes every day at 2pm" from "this is random."
- **`calculate_availability`** — Computes SLA-style uptime percentage from alert history. Merges overlapping alert windows and returns availability %, MTTR, incident count, longest incident duration, and a per-device breakdown. Filterable by severity threshold and time range.
- **`analyze_blast_radius`** — Scores the downstream impact if a device goes down. Walks the topology map to find dependent devices and produces an impact score. Useful for change management — check the blast radius before taking a device offline for maintenance.
- **`correlate_changes`** — Cross-references alert activity with audit/change logs to find correlations. Identifies config changes, device updates, or user actions that occurred within a configurable window before alert spikes. Each correlation gets a confidence score based on time proximity.
- **`classify_trend`** — Categorizes a metric's recent behavior into one of five patterns: stable, increasing, decreasing, cyclic, or volatile. A quick way to triage a metric without staring at a graph — run it across multiple datapoints to see what's moving.
- **`score_device_health`** — Produces a composite health score from 0-100 by computing z-scores for each datapoint's latest value against its historical window. Weights are configurable. Returns an overall status (healthy/degraded/critical) and identifies the top contributing factors dragging the score down.

2 analysis workflows:
- `capacity_forecast` — runs forecast_metric + classify_trend
- `device_health_assessment` — runs score_device_health + analyze_blast_radius + get_metric_anomalies

Shared statistical helpers module (`stats_helpers.py`) for reusable math utilities.

## [1.4.1] - 2026-02-14

### Fixed
- Metric data API returns values as list-of-lists, not dict

## [1.4.0] - 2026-02-14

### Added

5 AI analysis tools for server-side intelligence on monitoring data.

- **`correlate_alerts`** — Groups related alerts together by device, datasource, and time proximity. Instead of looking at alerts one by one, it clusters them to show which alerts are part of the same incident. Helps cut through a noisy alert storm to see "these 15 alerts are actually 3 distinct issues."
- **`get_alert_statistics`** — Aggregates alert counts across severity, device, datasource, and time buckets. Returns a statistical summary over a configurable time window — think of it as a quick dashboard view of alert volume and distribution without needing to open the portal.
- **`get_metric_anomalies`** — Detects datapoints that are deviating significantly from their historical mean using z-score analysis. Point it at a device and it flags which metrics are behaving abnormally right now. Useful for triage — instead of checking every graph, let it tell you what looks off.
- **`save_baseline`** — Snapshots a metric's historical behavior — mean, min, max, and standard deviation per datapoint — and stores it in the session. Use this to capture what "normal" looks like before a maintenance window, deployment, or any planned change.
- **`compare_to_baseline`** — Compares current metric values against a previously saved baseline. Reports deviation percentage and status (normal, elevated, critical) for each datapoint. The companion to `save_baseline` — run it after a change to see if anything drifted from where it was.

3 workflow prompts:
- `top_talkers` — Identify the noisiest devices and datasources generating the most alerts
- `rca_workflow` — Guided root cause analysis combining alert correlation, topology, and change history
- `capacity_forecast` — Forecast capacity trends and predict days-until-threshold-breach

Enhanced `alert_correlation` prompt with `device_id`/`group_id` scoping and correlation tool integration.

MCP orchestration guide resource (`lm://guide/mcp-orchestration`) documenting multi-MCP-server patterns.

Session persistence via `LM_SESSION_PERSIST_PATH` — session variables survive restarts.

HTTP analysis API: `POST /api/v1/analyze`, `GET /api/v1/analysis/{id}`, `POST /api/v1/webhooks/alert` for scheduled and webhook-triggered analysis workflows.

## [1.3.3] - 2026-02-13

### Fixed
- HTTP transport now applies the full middleware chain (tool filtering, field validation, write audit logging, session recording) — previously bypassed entirely
- HTTP `tools/list` now respects `LM_ENABLED_TOOLS` and `LM_DISABLED_TOOLS` filtering

### Changed
- Extracted shared `execute_tool()` middleware from `call_tool()` for transport-agnostic tool execution
- LMConfig cached as singleton to avoid redundant environment parsing on every tool call
- Removed dead logging infrastructure (LogLevel enum, LogEvent dataclass, 7 unused event factory functions)

## [1.3.2] - 2025-02-13

### Fixed
- Fixed 20 MCP tool schemas where parameter names did not match handler function signatures, causing "unexpected keyword argument" errors at runtime

### Added
- Registry test that validates all schema property names match handler function parameter names, preventing future mismatches

## [1.3.1] - 2025-02-12

### Fixed
- `get_change_audit` no longer crashes when the API returns `happenedOn` as an epoch integer

## [1.3.0] - 2025-02-10

### Added
- 5 MCP prompts: `cost_optimization`, `audit_review`, `alert_correlation`, `collector_health`, `troubleshoot_device`
- 6 resource schemas: escalations, reports, websites, datasources, users, audit
- 2 guide resources: tool categories index (all 152 tools) and common query examples
- `LM_LOG_LEVEL` configuration for controlling debug output (debug, info, warning, error)
- Write operation audit trail (INFO-level logging for create/update/delete actions)

### Fixed
- Wildcard sanitization applied to all 11 remaining string filter parameters across audit, cost, batchjobs, SDTs, and topology tools

## [1.2.1] - 2025-02-05

### Fixed
- Patch release with minor fixes

## [1.2.0] - 2025-02-01

### Added
- Tool filtering with `LM_ENABLED_TOOLS` and `LM_DISABLED_TOOLS` glob patterns
- Export/import support for all LogicModule types
- Cost optimization recommendation categories and detail endpoints

## [1.1.0] - 2025-01-20

### Added
- HTTP transport for remote deployments via Starlette/Uvicorn
- Session context tracking for conversational workflows
- 6 session management tools
- Health endpoints (`/health`, `/healthz`, `/readyz`) for Kubernetes
- Docker deployment with multi-stage build and Caddy reverse proxy
- CORS middleware configuration via `LM_CORS_ORIGINS`

## [1.0.1] - 2025-01-15

### Changed
- Comprehensive README update with all 146 tools documented
- Fixed installation command: `uvx --from lm-mcp lm-mcp-server`
- Added MCP Resources and Prompts documentation
- Added LMv1 authentication configuration instructions

## [1.0.0] - 2025-01-15

### Added
- **MCP Resources**: 15 schema/enum/filter resources for API reference
  - Schema resources: alerts, devices, sdts, dashboards, collectors
  - Enum resources: severity, device-status, sdt-type, alert-cleared, alert-acked, collector-build
  - Filter resources: alerts, devices, sdts, operators
- **MCP Prompts**: 5 workflow templates
  - incident_triage, capacity_review, health_check, alert_summary, sdt_planning
- **MCP Completions**: Auto-complete for tool arguments (severity, status, sdt_type, etc.)
- **LMv1 HMAC Authentication**: Support for Access ID/Key authentication
- **Ingestion APIs**: ingest_logs and push_metrics tools (requires LMv1 auth)
- **Cost Optimization Tools**: 7 tools for LM Envision cost analysis
  - get_cost_summary, get_resource_cost, get_cost_recommendations
  - get_cost_recommendation_categories, get_cost_recommendation
  - get_idle_resources, get_cloud_cost_accounts
- **LogicModule Import Tools**: 8 import tools for JSON definitions
  - import_datasource, import_configsource, import_eventsource
  - import_propertysource, import_logsource, import_topologysource
  - import_jobmonitor, import_appliesto_function
- **Website CRUD**: create_website, update_website, delete_website, create_website_group, delete_website_group
- **Alert Rule CRUD**: create_alert_rule, update_alert_rule, delete_alert_rule
- **Escalation CRUD**: create_escalation_chain, update_escalation_chain, delete_escalation_chain
- **Recipient Group CRUD**: create_recipient_group, update_recipient_group, delete_recipient_group
- **Structured Logging**: Event-based logging for API operations

### Changed
- Total tool count increased from ~120 to 146
- Development status changed to Production/Stable
- Improved metrics ingestion endpoint (changed to /rest/metric/ingest with create=true)

### Fixed
- MCP resource reading: Convert AnyUrl to string in read handler

## [0.5.1] - 2024-12-14

### Added
- MCP Registry server name in README for registry ownership validation

## [0.5.0] - 2024-12-14

### Added
- Comprehensive API filter support for all list tools
- Raw `filter` parameter for power users (LogicMonitor filter syntax)
- Named filter parameters for convenience (e.g., `name_filter`, `severity`)
- `offset` parameter for pagination on all list endpoints
- `has_more` indicator in responses for easier pagination
- Expanded README with Quick Start section and 50+ example prompts

### Changed
- All list tools now support both named parameters and raw filter expressions
- Improved pagination support across all endpoints

## [0.4.0] - 2024-12-13

### Added
- MCP tool registration with 120 tools
- Bulk operations: bulk_acknowledge_alerts, bulk_create_device_sdt, bulk_delete_sdt
- Export tools for datasources, dashboards, alert rules, escalation chains
- Active and upcoming SDT queries
- Network topology and flow tools
- Batch job management tools
- Cloud cost analysis tools
- Comprehensive LogicModule support (ConfigSources, EventSources, PropertySources, TopologySources, LogSources)

### Changed
- Improved tool descriptions for better AI understanding
- Enhanced error messages with actionable guidance

## [0.3.0] - 2024-12-13

### Added
- Dashboard management (create, update, delete dashboards and widgets)
- Report management (list, view, run, schedule reports)
- User and role management
- Access group tools
- API token tools
- Service and service group tools
- OID management tools
- Netscan execution

### Changed
- Reorganized tool modules for better maintainability
- Improved response formatting consistency

## [0.2.0] - 2024-12-12

### Added
- Alert rules tools
- Escalation chain and recipient group tools
- Ops notes and audit log tools
- Website/synthetic monitoring tools
- Collector group tools
- Device property management

### Changed
- Enhanced alert filtering options
- Improved error handling with retry logic

## [0.1.0] - 2024-12-12

### Added
- Initial release
- Bearer token authentication
- Core device management (list, create, update, delete)
- Alert management (list, view, acknowledge, add notes)
- SDT management (list, create, delete)
- Collector listing
- Basic metrics and datasource queries
- Rate limit handling with exponential backoff
- Write operation protection (disabled by default)

[2.3.0]: https://github.com/ryanmat/mcp-server-logicmonitor/compare/v2.2.0...v2.3.0
[2.2.0]: https://github.com/ryanmat/mcp-server-logicmonitor/compare/v2.1.1...v2.2.0
[2.1.1]: https://github.com/ryanmat/mcp-server-logicmonitor/compare/v2.1.0...v2.1.1
[2.1.0]: https://github.com/ryanmat/mcp-server-logicmonitor/compare/v2.0.1...v2.1.0
[2.0.1]: https://github.com/ryanmat/mcp-server-logicmonitor/compare/v2.0.0...v2.0.1
[2.0.0]: https://github.com/ryanmat/mcp-server-logicmonitor/compare/v1.9.6...v2.0.0
[1.9.6]: https://github.com/ryanmat/mcp-server-logicmonitor/compare/v1.9.5...v1.9.6
[1.9.5]: https://github.com/ryanmat/mcp-server-logicmonitor/compare/v1.9.2...v1.9.5
[1.9.2]: https://github.com/ryanmat/mcp-server-logicmonitor/compare/v1.9.0...v1.9.2
[1.9.0]: https://github.com/ryanmat/mcp-server-logicmonitor/compare/v1.8.0...v1.9.0
[1.8.0]: https://github.com/ryanmat/mcp-server-logicmonitor/compare/v1.7.2...v1.8.0
[1.7.2]: https://github.com/ryanmat/mcp-server-logicmonitor/compare/v1.7.1...v1.7.2
[1.7.1]: https://github.com/ryanmat/mcp-server-logicmonitor/compare/v1.7.0...v1.7.1
[1.7.0]: https://github.com/ryanmat/mcp-server-logicmonitor/compare/v1.6.1...v1.7.0
[1.6.1]: https://github.com/ryanmat/mcp-server-logicmonitor/compare/v1.6.0...v1.6.1
[1.6.0]: https://github.com/ryanmat/mcp-server-logicmonitor/compare/v1.5.1...v1.6.0
[1.5.1]: https://github.com/ryanmat/mcp-server-logicmonitor/compare/v1.5.0...v1.5.1
[1.5.0]: https://github.com/ryanmat/mcp-server-logicmonitor/compare/v1.4.1...v1.5.0
[1.4.1]: https://github.com/ryanmat/mcp-server-logicmonitor/compare/v1.4.0...v1.4.1
[1.4.0]: https://github.com/ryanmat/mcp-server-logicmonitor/compare/v1.3.3...v1.4.0
[1.3.3]: https://github.com/ryanmat/mcp-server-logicmonitor/compare/v1.3.2...v1.3.3
[1.3.2]: https://github.com/ryanmat/mcp-server-logicmonitor/compare/v1.3.1...v1.3.2
[1.3.1]: https://github.com/ryanmat/mcp-server-logicmonitor/compare/v1.3.0...v1.3.1
[1.3.0]: https://github.com/ryanmat/mcp-server-logicmonitor/compare/v1.2.1...v1.3.0
[1.2.1]: https://github.com/ryanmat/mcp-server-logicmonitor/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/ryanmat/mcp-server-logicmonitor/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/ryanmat/mcp-server-logicmonitor/compare/v1.0.1...v1.1.0
[1.0.1]: https://github.com/ryanmat/mcp-server-logicmonitor/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/ryanmat/mcp-server-logicmonitor/compare/v0.5.1...v1.0.0
[0.5.1]: https://github.com/ryanmat/mcp-server-logicmonitor/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/ryanmat/mcp-server-logicmonitor/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/ryanmat/mcp-server-logicmonitor/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/ryanmat/mcp-server-logicmonitor/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/ryanmat/mcp-server-logicmonitor/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/ryanmat/mcp-server-logicmonitor/releases/tag/v0.1.0
