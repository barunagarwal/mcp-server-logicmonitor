# LogicMonitor MCP Server

[![PyPI version](https://img.shields.io/pypi/v/lm-mcp.svg)](https://pypi.org/project/lm-mcp/)
[![Python versions](https://img.shields.io/pypi/pyversions/lm-mcp.svg)](https://pypi.org/project/lm-mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

<!-- mcp-name: io.github.ryanmat/logicmonitor -->

Model Context Protocol (MCP) server for LogicMonitor REST API v3 integration. Enables AI assistants to interact with LogicMonitor monitoring data through 306 structured tools, 15 workflow prompts, and 26 resources. Optional integrations: IBM watsonx.ai for Granite TTM forecasting and NL summaries, Terraform IaC for any provider, and HuggingFace local Granite model fallback.

Works with any MCP-compatible client: Claude Desktop, Claude Code, Cursor, Continue, Cline, and more.

## Quick Start

**1. Get your LogicMonitor Bearer Token:**
- Log into your LogicMonitor portal
- Go to **Settings** → **Users and Roles** → **API Tokens**
- Create a new API-only user or add a token to an existing user
- Copy the Bearer token

**2. Configure your MCP client:**

For **Claude Code** (CLI):
```bash
claude mcp add logicmonitor \
  -e LM_PORTAL=yourcompany.logicmonitor.com \
  -e LM_BEARER_TOKEN=<your-bearer-token> \
  -- uvx --from lm-mcp lm-mcp-server
```

With **IBM watsonx.ai integration** (optional -- adds Granite TTM forecasting and NL summaries):
```bash
claude mcp add logicmonitor \
  -e LM_PORTAL=yourcompany.logicmonitor.com \
  -e LM_BEARER_TOKEN=<your-bearer-token> \
  -e WATSONX_API_KEY=<your-ibm-cloud-api-key> \
  -e WATSONX_URL=https://us-south.ml.cloud.ibm.com \
  -e WATSONX_PROJECT_ID=your-watsonx-project-id \
  -- uvx --from "lm-mcp[ibm]" lm-mcp-server
```

With **Terraform IaC** (optional -- adds terraform plan/apply/generate tools):
```bash
claude mcp add logicmonitor \
  -e LM_PORTAL=yourcompany.logicmonitor.com \
  -e LM_BEARER_TOKEN=<your-bearer-token> \
  -e TF_WORKSPACE_DIR=/path/to/terraform/workspaces \
  -- uvx --from lm-mcp lm-mcp-server
```

With **HuggingFace local models** (optional -- local Granite TTM + NL summaries, no cloud API needed):
```bash
claude mcp add logicmonitor \
  -e LM_PORTAL=yourcompany.logicmonitor.com \
  -e LM_BEARER_TOKEN=<your-bearer-token> \
  -- uvx --from "lm-mcp[huggingface]" lm-mcp-server
```

For **Claude Desktop**, add to your config file (see [MCP Client Configuration](#mcp-client-configuration) below).

**3. Verify it's working:**
```
claude mcp list
```

You should see: `logicmonitor: uvx --from lm-mcp lm-mcp-server - ✓ Connected`

**4. Test with a prompt:**
```
"Show me all critical alerts in LogicMonitor"
```

## What's New in v4.2.1

A fix release. LMv1 portals authenticate again, writes included: the signature
follows LogicMonitor's documented recipe and covers the exact bytes sent. Tool
errors reach the client with `isError: true` and are audited as failures, every
tool is callable per its own schema, stdio starts in every configuration, and
`/readyz` no longer calls the portal. Releases are now gated on the suite across
Python 3.11 to 3.13, and the container installs from `uv.lock` with hash
checking, digest-pinned base images, and a fixed non-root UID.

<details>
<summary>v4.2.0</summary>

### What's New in v4.2.0

Multi-portal mode arrives, hardened. A single server can now serve many customer
portals, selecting the active one at runtime with `list_portals`, `use_portal`,
`current_portal`, and `reload_portals` — one entry in your MCP client instead of
one server (and one pasted token) per portal. Credentials live in an
age-encrypted vault, every portal is read-only unless its vault record says
otherwise, and the mode is deliberately stdio-only: the server refuses to start
it on the shared HTTP transport. The release also carries a full dependency
refresh clearing 53 dependabot alerts across the lockfile.

</details>

<details>
<summary>v4.1.0</summary>

### What's New in v4.1.0

Native OTLP metrics arrive. LogicMonitor's new OTLP Metrics feature (feature-flag
gated, Prometheus-backed) ships in its first phase with a single UI surface (the
dashboard Advanced Metrics Widget) and no Metrics Explorer yet; these four tools
are the first programmatic window into that data: `get_otlp_metric_names`,
`get_otlp_metric_labels`, and `get_otlp_label_values` for discovery, and
`query_otlp_metrics` for full PromQL range queries returning time-series matrices.
All four were validated live against a flag-enabled portal fed by a real OTel
collector (Kubernetes cAdvisor and application metrics), translate the
feature-disabled portal responses into a clear availability notice, and cap large
matrix responses with even-stride downsampling so they stay LLM-friendly.

</details>

## What's New in v4.0.0

**Major.** Every tool now wraps an endpoint proven to exist, validated against a live
portal. Six tools that called nonexistent API paths since introduction are removed
(`get_cloud_cost_accounts`, `get_cost_summary`, `get_resource_cost`,
`get_remediation_status`, `get_remediation_history`, `get_batchjob_history`); the cost
recommendation tools move onto the working `/cost-optimization` API; the Service Insight
tools query real Service Insight objects (deviceType 6 devices and BizService groups)
instead of the legacy v1 websites API. The Automated Diagnostics & Remediation surface
arrives in full: `get_diagnostic_remediation_assignments` and
`get_diagnostic_remediation_results` (structured execution records with script output,
replacing audit-log scraping), `execute_diagnostic`, full CRUD plus import/export for
diagnostic and remediation sources, and the new action chain / action rule namespace
(11 tools including the `set_action_rule_status` toggle). `update_logicmodule` gains the
two new source types and its apply mode actually applies now (it previously tripped its
own sub-tools' confirm guards). `run_report` executions are pollable via
`get_report_execution`, `get_alert_details` can fetch the full message body, and NextGen
reports are visible to the report list tools.

Full release history, including v3.9.x and earlier, is in [CHANGELOG.md](https://github.com/ryanmat/mcp-server-logicmonitor/blob/main/CHANGELOG.md). The v3.8.0 networking intelligence tools have a dedicated reference: [documentation/networking-intelligence.md](https://github.com/ryanmat/mcp-server-logicmonitor/blob/main/documentation/networking-intelligence.md).

## Features

**306 Tools** across comprehensive LogicMonitor API coverage (277 LM + 18 AAP + 10 Terraform + 1 watsonx):

### Core Monitoring
- **Alert Management**: Query, acknowledge, bulk acknowledge, add notes, view rules
- **Device Management**: Full CRUD - list, create, update, delete devices and groups
- **Metrics & Data**: Query datasources, instances, metric data, and graphs. Instance CRUD for manual datasource instances.
- **Dashboard Management**: Full CRUD for dashboards, widgets, and groups
- **SDT Management**: Create, list, bulk create/delete Scheduled Downtime
- **Collector Management**: List collectors and collector groups

### Extended Features
- **Website Monitoring**: Full CRUD for synthetic checks and website groups
- **Report Management**: List, view, run reports, manage schedules
- **Escalation Management**: Full CRUD for escalation chains and recipient groups
- **Alert Rules**: Full CRUD for alert routing rules
- **User & Role Management**: View users, roles, access groups, API tokens
- **Ops Management**: Audit logs, ops notes, login/change audits
- **Automated Diagnostics & Remediation**: Assigned-source resolution, structured execution results with script output, diagnostic/remediation source CRUD, manual execution, action chains and rules
- **Native OTLP Metrics (preview)**: Metric and label discovery plus PromQL range queries against the feature-flag-gated OTLP metrics store

### AI Analysis Tools

Server-side intelligence that transforms raw monitoring data into actionable insights:

- **Alert Correlation**: Automatically clusters related alerts by device, datasource, and temporal proximity — replaces dozens of manual API calls with a single aggregated view
- **Alert Statistics**: Aggregated alert counts by severity, top-10 devices and datasources, time-bucketed distributions for trend analysis
- **Metric Anomaly Detection**: Multi-method anomaly detection (z-score, IQR, MAD) with auto-selection based on data distribution
- **Metric Baselines**: Save baseline snapshots of metric behavior, then compare current performance against the baseline to detect drift
- **Scheduled Analysis**: HTTP API endpoints for triggering analysis workflows (alert correlation, RCA, top talkers, health checks) from external schedulers and webhooks

### ML/Statistical Analysis Tools

Pure-Python statistical methods for capacity planning, trend analysis, and operational scoring:

- **Metric Forecasting**: Linear regression, Holt-Winters triple exponential smoothing, and IBM Granite TTM (via watsonx.ai, optional) with auto-selection, confidence intervals, and threshold breach prediction
- **Metric Correlation**: Pearson correlation matrix across multiple metric series with strong-correlation highlighting
- **Error Budget Tracking**: SLO-based error budget calculation with burn rate, projected exhaustion, and status classification
- **Change Point Detection**: CUSUM algorithm for identifying regime shifts and mean-level changes
- **Alert Noise Scoring**: Shannon entropy and flap detection to quantify alert noise (0-100) with tuning recommendations
- **Seasonality Detection**: Autocorrelation-based periodicity detection at standard intervals with peak-hour identification
- **Availability Calculation**: SLA-style uptime percentage from alert history with MTTR, incident counts, and per-device breakdown
- **Blast Radius Analysis**: Topology-based downstream impact scoring for device failure scenarios
- **Change Correlation**: Cross-references alert spikes with audit/change logs to identify change-induced incidents
- **Trend Classification**: Categorizes metrics as stable, increasing, decreasing, cyclic, or volatile
- **Device Health Scoring**: Multi-metric composite health score (0-100) using z-score analysis with configurable weights

### Composite Workflow Tools

Multi-step analysis tools that combine several sub-tools into a single call. Each supports `detail_level` ("summary" or "full"), optional `summarize=true` for plain-English NL summaries via IBM Granite (requires watsonx.ai), and handles sub-tool failures gracefully with partial results.

- **Triage**: Correlates active alerts, scores noise, analyzes blast radius, and cross-references recent changes
- **Health Check**: Device health score, monitoring coverage, anomaly detection, active alerts, and 30-day availability
- **Capacity Plan**: Per-datasource forecasting, trend classification, seasonality detection, and change point analysis
- **Portal Overview**: Alert statistics, collector health, active SDTs, alert clusters, noise assessment, and down devices
- **Diagnose**: Alert details, device context, correlation, blast radius, health scoring, and root cause analysis
- **Update LogicModule (Safe Partial Updates)**: `update_logicmodule(type, id, changes, mode)` exports the current full definition, deep-merges your `changes`, validates required fields, and returns a dry-run diff (default) or applies the merge. Prevents the full-replace blanking that wiped production Groovy scripts in two prior incidents. Supports configsource, datasource, eventsource, logsource, propertysource, topologysource.
- **Search Tools**: Keyword search across all tools by name and description with category filtering

### APM Trace Tools

Service discovery and RED metrics for LogicMonitor APM (Application Performance Monitoring):

- **Service Discovery**: List all traced services, inspect individual service details and properties
- **Operation Listing**: Discover endpoints/routes monitored within each service
- **RED Metrics**: Duration, error count, and operation count at both service and per-operation level
- **Alert Integration**: View active alerts for any traced service
- **Property Inspection**: OTel attributes, namespace info, and auto-discovered metadata

### Ansible Automation Platform Integration

18 tools for observability-driven remediation via Ansible Automation Platform (AAP). Connects LogicMonitor alerts to automated remediation playbooks.

- **Job Templates**: List, inspect, and launch job templates with extra variables and host limits
- **Job Execution**: Launch jobs, check status, view output, cancel or relaunch runs
- **Workflows**: Launch workflow templates, monitor multi-step automation sequences
- **Inventories & Hosts**: List inventories, inspect hosts for targeted remediation
- **Projects & Credentials**: Browse available projects and credentials (secrets never exposed)
- **Write Protection**: launch_job, launch_workflow, cancel_job, relaunch_job require `LM_ENABLE_WRITE_OPERATIONS=true`
- **Jinja2 Safety**: All extra_vars inputs are validated to prevent template injection

AAP tools are optional — they only appear when `AWX_URL` and `AWX_TOKEN` are configured. See [Example Playbooks](https://github.com/ryanmat/mcp-server-logicmonitor/tree/main/examples/playbooks) for remediation templates.

### IBM watsonx.ai Integration

Optional AI-powered enhancements using IBM Granite foundation models via watsonx.ai. Requires an IBM Cloud account with a watsonx.ai project (Lite/free tier supported).

- **Granite TTM Forecasting**: ML-powered time series forecasting using IBM Granite Tiny Time Mixer (TTM). Use `method="ttm"` on `forecast_metric` for 96-step predictions that detect seasonality and non-linear patterns. Requires 512+ data points. Gracefully falls back to statistical methods when data is insufficient.
- **Granite NL Summaries**: Plain-English shift-handoff summaries on composite workflow tools (`triage`, `diagnose`, `health_check`, `capacity_plan`, `portal_overview`). Pass `summarize=true` to append an IBM Granite-generated analysis summary to the structured output.
- **watsonx_summarize**: Standalone tool that takes any JSON data and generates a concise NL summary via Granite 4.0. Useful for summarizing output from any MCP tool.

watsonx tools are optional — they only appear when `WATSONX_API_KEY` and `WATSONX_PROJECT_ID` are configured. Install with `lm-mcp[ibm]` to include the IBM SDK dependencies.

**Setup:**
1. Create a free IBM Cloud account at [cloud.ibm.com](https://cloud.ibm.com)
2. Provision **watsonx.ai Runtime** (Lite plan, free) from the IBM Cloud catalog
3. Create a watsonx.ai project and associate the Runtime instance
4. Generate an IBM Cloud API key at [cloud.ibm.com/iam/apikeys](https://cloud.ibm.com/iam/apikeys)
5. Configure the MCP server with `WATSONX_API_KEY`, `WATSONX_URL`, and `WATSONX_PROJECT_ID`

### Terraform Integration

11 tools for Infrastructure as Code workflows with any Terraform provider. AI agents can author HCL, use pre-made scripts, or reverse-engineer existing LM resources.

- **terraform_init**: Initialize workspace and download providers (write perms required)
- **terraform_validate**: Syntax-check HCL configuration
- **terraform_plan**: Preview changes with structured JSON output (write perms required: providers and data sources call live APIs)
- **terraform_apply**: Apply changes (triple-gated: write perms + config flag + confirm param)
- **terraform_destroy**: Destroy infrastructure (same triple gate)
- **terraform_import**: Import existing resources into Terraform state
- **terraform_state_list / terraform_state_show**: Inspect current state
- **terraform_output**: View Terraform outputs
- **terraform_write_config**: Write HCL files to workspace directories
- **terraform_generate**: Export existing LM portal resources as HCL using the `logicmonitor/logicmonitor` provider

Terraform tools are optional -- they only appear when `TF_WORKSPACE_DIR` is configured. Requires the `terraform` CLI installed separately.

The `terraform` subprocess inherits only `PATH`, `HOME`, `TMPDIR`, `TF_*`, the proxy settings (`HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY` and their lowercase forms) and the CA settings (`SSL_CERT_FILE`, `SSL_CERT_DIR`) from the server's environment, so server and cloud credentials such as `LM_BEARER_TOKEN` or `AWS_SECRET_ACCESS_KEY` never reach provider or data-source code. The `logicmonitor` provider gets `LM_API_ID`, `LM_API_KEY` and `LM_COMPANY` (and their `TF_VAR_lm_*` forms) from the server's LMv1 configuration. Other providers take credentials as `TF_VAR_*` variables that the HCL passes to them, or from files under `HOME` such as `~/.aws/credentials`. A backend block cannot read variables, so backend credentials come from files under `HOME` or from `terraform_init`'s `backend_config` keys (`profile`, `access_key`, `sas_token` and the like).

`var_file` and a local backend `path` must resolve inside the workspace, symlinks included. `terraform_init`'s `backend_config` takes an object of local, s3 or azurerm backend keys and refuses endpoint and proxy overrides by name. A command that exceeds `TF_TIMEOUT` gets SIGINT and 30 seconds to persist state and release its lock before it is killed; a timed-out `apply` or `destroy` reports that the lock may still be held and state may be incomplete.

**Three entry points:**
1. **Agent-authored**: AI generates HCL from natural language, writes to workspace, plans, applies
2. **Pre-made scripts**: Point `TF_WORKSPACE_DIR` at existing `.tf` files, agent operates on them
3. **Reverse-engineer**: `terraform_generate` exports LM resources as HCL, then import into state

### HuggingFace Local Fallback

When watsonx.ai API credentials are not configured, TTM forecasting and NL summaries automatically fall back to local Granite models via HuggingFace transformers. Install with `lm-mcp[huggingface]`.

**Priority chain:** watsonx.ai API (remote) > HuggingFace local > statistical/linear

- **TTM Model**: `ibm-granite/granite-timeseries-ttm-r2` (512 context, 96 forecast)
- **LLM Model**: `ibm-granite/granite-3.3-2b-instruct` (2B params, runs on CPU)
- Models lazy-load on first inference call (initial download: ~500MB TTM, ~4GB LLM)
- Same interface as WatsonxClient -- all existing watsonx tools work with either backend

### LogicModules
- **DataSources**: Query and export datasource definitions
- **ConfigSources**: Query definitions, retrieve device config data from the Config Archive, view diffs, trigger on-demand collection, and audit change history
- **EventSources**: Query and export event detection modules
- **PropertySources**: Query, create, and export property collection modules
- **TopologySources**: Query and export topology mapping modules
- **LogSources**: Query and export log collection modules
- **Import Support**: Import LogicModules from JSON definitions

### Advanced Capabilities
- **Cost Optimization**: Cost recommendations, recommendation categories, idle resources (LM Envision)
- **Network Topology**: Device neighbors, interfaces, flows, connections
- **Batch Jobs**: View and manage batch job execution history
- **Log/Metric Ingestion**: Push logs and metrics via LMv1 authentication

### MCP Protocol Features
- **Resources**: 26 schema/enum/filter/guide resources for API reference
- **Prompts**: 15 workflow templates (incident triage, RCA, capacity forecasting, remediation execution, etc.)
- **Completions**: Auto-complete for tool arguments

### Claude Code Skills

Pre-built slash-command workflows for Claude Code that orchestrate multiple tools into guided operational runbooks:

| Skill | Command | Description |
|-------|---------|-------------|
| Alert Triage | `/lm-triage` | Investigate active alerts, score noise, correlate clusters, assess blast radius, take action |
| Device Health | `/lm-health <device>` | Comprehensive health check — metrics, anomalies, health score, availability, topology |
| Portal Overview | `/lm-portal` | Portal-wide snapshot for shift handoff — alerts, collectors, SDTs, down devices |
| Capacity Planning | `/lm-capacity <device>` | Trend analysis, seasonality detection, breach forecasting, right-sizing |
| APM Investigation | `/lm-apm [service]` | Service discovery, operation-level RED metrics, alert correlation |
| Remediation | `/lm-remediate` | Diagnose alert, find/generate playbook, launch AAP job, verify fix |

Skills ship with the repo — clone it and invoke `/lm-triage` in Claude Code to get started.

### Operational Features
- **Security-First**: Read-only by default, write operations require explicit opt-in
- **Rate Limit Handling**: Automatic retry with exponential backoff and jitter
- **Server Error Recovery**: Automatic retry on 5xx server errors for idempotent requests (GET, PUT, DELETE); a POST or PATCH that gets a 5xx is not resent, since the server may already have applied it. Timeouts and dropped connections are reported, not resent
- **Pagination Support**: Handle large result sets with offset-based pagination
- **Session Persistence**: Optional file-backed session variables that survive restarts

### Multi-Portal Mode (optional)
Work across many customer portals from a **single** server entry instead of one server (and one token) per portal. Set `LM_MULTI_PORTAL=true` and point the server at a credential vault; the full tool set loads once, and you switch the active portal at runtime. Four tools manage it: `list_portals`, `use_portal`, `current_portal`, and `reload_portals`. Credentials come from an age-encrypted vault (or a plaintext JSON file for testing) rather than the environment, and each portal is **read-only unless explicitly marked writable** — so an assistant can browse any portal but cannot change one by accident. Multi-portal mode is **stdio-only** (the server refuses to start it on the HTTP transport) and Terraform tools are unavailable in it. Unmodified single-portal behavior is unchanged (no `LM_MULTI_PORTAL`, fixed `LM_PORTAL` + token). See **[MULTIPORTAL.md](https://github.com/ryanmat/mcp-server-logicmonitor/blob/main/MULTIPORTAL.md)**.

## Installation

### Via PyPI (Recommended)

```bash
# Using uvx (no install needed)
uvx --from lm-mcp lm-mcp-server

# Using pip
pip install lm-mcp
```

### From Source

```bash
git clone https://github.com/ryanmat/mcp-server-logicmonitor.git
cd mcp-server-logicmonitor
uv sync
```

### Docker Deployment

For remote/shared deployments using HTTP transport:

```bash
cd deploy
cp .env.example .env
# Edit .env with your credentials, including LM_HTTP_AUTH_TOKEN (required)

# Run with docker-compose
docker compose up -d

# With TLS via Caddy
docker compose --profile tls up -d
```

The server exposes health endpoints for container orchestration:
- `GET /health` - Detailed health check with all component statuses (adds the LM API connectivity check when enabled, for callers presenting `LM_HTTP_AUTH_TOKEN` or when no token is set)
- `GET /healthz` - Liveness probe (200 OK or 503)
- `GET /readyz` - Readiness probe (local checks only; never calls the LM API)

POST requests to `/mcp` and `/api/v1/*` must send `Content-Type: application/json`; any other body type gets `415`. Every route except `/healthz` and `/readyz`, `/health` included, answers only the `Host` names the server expects (the loopback names, a non-wildcard `LM_HTTP_HOST`, and `LM_HTTP_ALLOWED_HOSTS`) and refuses others with `400`; those two probes accept any `Host` so probes by pod IP keep working. The compose file requires `LM_HTTP_AUTH_TOKEN` for every profile and passes `DOMAIN` through as an allowed host for the Caddy `tls` profile.

### Kubernetes

`deploy/k8s/deployment.yaml` is a vendor-neutral Deployment and Service running
the published `ghcr.io` image. It works on AKS, EKS, GKE, OpenShift, or vanilla
Kubernetes, reads credentials from a Kubernetes secret you create, and wires the
liveness and readiness probes to the endpoints above. Apply it with
`kubectl apply -f deploy/k8s/deployment.yaml` after creating the secret
documented at the top of the file.

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LM_PORTAL` | Yes | - | LogicMonitor portal hostname (e.g., `company.logicmonitor.com`) |
| `LM_BEARER_TOKEN` | Yes* | - | API Bearer token (min 10 characters) |
| `LM_ACCESS_ID` | No | - | LMv1 API access ID (for ingestion APIs) |
| `LM_ACCESS_KEY` | No | - | LMv1 API access key (for ingestion APIs) |
| `LM_ENABLE_WRITE_OPERATIONS` | No | `false` | Enable write operations (create, update, delete) |
| `LM_API_VERSION` | No | `3` | API version |
| `LM_TIMEOUT` | No | `30` | Request timeout in seconds (range: 5-300) |
| `LM_MAX_RETRIES` | No | `3` | Max retries for rate-limited requests, and for server errors on idempotent requests (GET, PUT, DELETE); a POST or PATCH that gets a 5xx is not resent (range: 0-10) |
| `LM_RETRY_AFTER_CAP_SECONDS` | No | `120` | Longest wait between retries. A server's `Retry-After` can lengthen the backoff up to this cap, never shorten it |
| `LM_TRANSPORT` | No | `stdio` | Transport mode: `stdio` (local) or `http` (remote) |
| `LM_MULTI_PORTAL` | No | `false` | Serve many customer portals from one server, selected at runtime via `use_portal`. Stdio-only. |
| `LM_VAULT_FILE` | No | - | Path to the age-encrypted portal vault (multi-portal) |
| `LM_AGE_KEY` | No | - | Path to the age identity that decrypts the vault (multi-portal) |
| `LM_PORTALS_FILE` | No | - | Plaintext JSON portal map (multi-portal, testing only; the encrypted vault wins when both are set) |
| `LM_HTTP_HOST` | No | `0.0.0.0` | HTTP server bind address. With `LM_TRANSPORT=http`, an address other than `127.0.0.1`, `::1` or `localhost` needs `LM_HTTP_AUTH_TOKEN` or `LM_HTTP_ALLOW_UNAUTHENTICATED=true`, or the server refuses to start. |
| `LM_HTTP_PORT` | No | `8080` | HTTP server port |
| `LM_CORS_ORIGINS` | No | - | Comma-separated CORS origins (default: none) |
| `LM_HTTP_AUTH_TOKEN` | No | - | Require this bearer token on `/mcp` and `/api/v1/*` (min 16 chars). Needed to start on a non-loopback `LM_HTTP_HOST`, the default `0.0.0.0` included, unless `LM_HTTP_ALLOW_UNAUTHENTICATED=true`. Health endpoints and `/` stay open for probes. HTTP transport only. |
| `LM_HTTP_ALLOWED_HOSTS` | No | - | Comma-separated `Host` names the server accepts on every route except `/healthz` and `/readyz`, besides `127.0.0.1`, `::1`, `localhost` and a non-wildcard `LM_HTTP_HOST` (for example the public name a reverse proxy forwards). HTTP transport only. |
| `LM_HTTP_ALLOW_UNAUTHENTICATED` | No | `false` | Start on a non-loopback `LM_HTTP_HOST` with no `LM_HTTP_AUTH_TOKEN`, for a listener protected another way (an authenticating proxy, a private network). HTTP transport only. |
| `LM_SESSION_ENABLED` | No | `true` | Enable session context tracking |
| `LM_SESSION_HISTORY_SIZE` | No | `50` | Number of tool calls to keep in history |
| `LM_LOG_LEVEL` | No | `warning` | Logging level: `debug`, `info`, `warning`, or `error`. Records go to stderr; write audit lines (`info` for a success, `warning` for a failure) redact argument values under credential-shaped keys such as `password`, `token`, `api_key` and `extra_vars`, LogicMonitor credential properties such as `ssh.pass` and `snmp.community`, and a `property_value` whose `property_name` is one |
| `LM_FIELD_VALIDATION` | No | `warn` | Field validation: `off`, `warn`, or `error` |
| `LM_ENABLED_TOOLS` | No | - | Comma-separated tool names or glob patterns to enable (e.g., `get_*,triage`). Mutually exclusive with `LM_DISABLED_TOOLS`. |
| `LM_DISABLED_TOOLS` | No | - | Comma-separated tool names or glob patterns to disable (e.g., `delete_*`). Mutually exclusive with `LM_ENABLED_TOOLS`. |
| `LM_MCP_CATEGORIES` | No | - | Comma-separated category names to include: `read`, `write`, `delete`, `export`, `import`, `session`, `workflow`. Composes by intersection with `LM_ENABLED_TOOLS`/`LM_DISABLED_TOOLS` -- only narrows, never expands. Useful for clients with tool-count limits (e.g., Cursor's 40-tool cap). |
| `LM_HEALTH_CHECK_CONNECTIVITY` | No | `false` | Include an LM API ping in `/health` for authenticated callers (never in `/readyz`) |
| `LM_SESSION_PERSIST_PATH` | No | - | File path for persistent session variables (survives restarts) |
| `LM_ANALYSIS_MAX_CONCURRENCY` | No | `4` | Analysis workflows (`/api/v1/analyze` and the alert webhook) that run at once; later submissions are accepted and wait as `pending`. At least 1. HTTP transport only. |
| `AWX_URL` | No | - | Ansible Automation Platform controller URL (e.g., `https://aap.example.com`) |
| `AWX_TOKEN` | No | - | AAP personal access token |
| `AWX_VERIFY_SSL` | No | `true` | Verify SSL certificates for AAP connections |
| `AWX_TIMEOUT` | No | `30` | Request timeout in seconds for AAP API calls |
| `AWX_MAX_RETRIES` | No | `3` | Max retries for rate-limited AAP requests, and for server errors on idempotent ones; a job launch that gets a 5xx is not resent. A `Retry-After` lengthens the backoff up to 120 seconds |
| `WATSONX_API_KEY` | No | - | IBM Cloud API key for watsonx.ai (enables Granite TTM + NL summaries) |
| `WATSONX_URL` | No | `https://us-south.ml.cloud.ibm.com` | IBM watsonx.ai endpoint URL |
| `WATSONX_PROJECT_ID` | No | - | IBM watsonx.ai project ID |
| `WATSONX_TIMEOUT` | No | `60` | Request timeout in seconds for watsonx.ai API calls |
| `TF_WORKSPACE_DIR` | No | - | Root directory for Terraform workspaces (enables Terraform tools) |
| `TF_TERRAFORM_BINARY` | No | `terraform` | Path to the terraform binary |
| `TF_TIMEOUT` | No | `300` | Terraform command timeout in seconds |
| `TF_AUTO_APPROVE_ENABLED` | No | `false` | Enable terraform apply/destroy operations |
| `HF_TTM_MODEL` | No | `ibm-granite/granite-timeseries-ttm-r2` | HuggingFace TTM model name or path |
| `HF_LLM_MODEL` | No | `ibm-granite/granite-3.3-2b-instruct` | HuggingFace LLM model name or path |
| `HF_DEVICE` | No | `auto` | Torch device for inference (cpu, cuda, mps, auto) |
| `HF_CACHE_DIR` | No | - | HuggingFace model cache directory |

*Either `LM_BEARER_TOKEN` or both `LM_ACCESS_ID` and `LM_ACCESS_KEY` are required.

### Authentication Methods

**Bearer Token (Recommended):**
- Simpler setup, works for most operations
- Set `LM_BEARER_TOKEN`

**LMv1 HMAC (Required for Ingestion):**
- Required for `ingest_logs` and `push_metrics` tools
- Set both `LM_ACCESS_ID` and `LM_ACCESS_KEY`
- Can be used alongside Bearer token

### Getting API Credentials

**Bearer Token:**
1. Log into your LogicMonitor portal
2. Go to **Settings** → **Users and Roles** → **API Tokens**
3. Create a new API-only user or add a token to an existing user
4. Copy the Bearer token

**LMv1 Credentials:**
1. Go to **Settings** → **Users and Roles** → **Users**
2. Select a user → **API Tokens** tab
3. Create or view the Access ID and Access Key

## MCP Client Configuration

The [Quick Start](#quick-start) covers Claude Code. Every JSON-based client (Cursor, Claude Desktop, Cline, GitHub Copilot, Gemini CLI, OpenAI Codex) runs the same server with the same block:

```json
{
  "mcpServers": {
    "logicmonitor": {
      "command": "uvx",
      "args": ["--from", "lm-mcp", "lm-mcp-server"],
      "env": {
        "LM_PORTAL": "yourcompany.logicmonitor.com",
        "LM_BEARER_TOKEN": "your-bearer-token"
      }
    }
  }
}
```

Add `LM_ENABLE_WRITE_OPERATIONS`, `LM_ACCESS_ID`/`LM_ACCESS_KEY` (ingestion), or the watsonx/Terraform variables to `env` as needed. Per-client config file locations and exact steps (Claude Code, Cursor, Claude Desktop, OpenAI Codex, Cline, GitHub Copilot, Gemini CLI) are in **[documentation/client-setup.md](https://github.com/ryanmat/mcp-server-logicmonitor/blob/main/documentation/client-setup.md)**.

### Cursor's 40-tool cap

Cursor only loads the first 40 MCP tools, so the remaining ~240 are invisible to the agent. Use `LM_MCP_CATEGORIES` to fit a curated subset under the cap. The `workflow` category alone (`triage`, `diagnose`, `health_check`, `portal_overview`, `capacity_plan`, plus the scoring/correlation tools and `update_logicmodule`) is roughly 23 tools and covers the 80% case:

```json
"env": {
  "LM_PORTAL": "yourcompany.logicmonitor.com",
  "LM_BEARER_TOKEN": "your-bearer-token",
  "LM_MCP_CATEGORIES": "workflow"
}
```

`LM_MCP_CATEGORIES` composes with `LM_ENABLED_TOOLS` by intersection (it only narrows, never expands); unset, the server returns all 306 tools. In multi-portal mode the four portal tools are exempt from category filtering (they are the mode's control plane) and do not count toward your curated set. See [documentation/client-setup.md](https://github.com/ryanmat/mcp-server-logicmonitor/blob/main/documentation/client-setup.md) for a surgical `LM_ENABLED_TOOLS` example.

## Available Tools

306 tools cover the full LogicMonitor surface plus the optional Ansible Automation Platform, Terraform, and IBM watsonx.ai integrations. The complete per-tool reference (every tool, its parameters, and its read/write classification) is in **[documentation/tools.md](https://github.com/ryanmat/mcp-server-logicmonitor/blob/main/documentation/tools.md)**, generated from the tool registry so it never drifts.

Discover tools at runtime without leaving your client:

- `search_tools`: keyword search across every tool by name and description
- the `lm://guide/tool-categories` resource: all 306 tools grouped by domain

Tools are organized into these categories: Alerts, Alert Rules, Devices, Metrics, APM Traces, Dashboards, SDT, Collectors, Websites, Escalations, Device Properties, Reports, DataSources, LogicModules (Config/Event/Property/Topology/Log), Cost Optimization, Actions (Chains & Rules), Ingestion, Network & Topology, Batch Jobs, Ops & Audit, Users & Access, Services, Netscans, OIDs, Session, Correlation & Analysis, Baselines, ML/Statistical Analysis, Ansible Automation Platform, Remediation, Composite Workflows, and Error Budget.

## MCP Resources

The server exposes 26 resources for API reference:

### Schema Resources
| URI | Description |
|-----|-------------|
| `lm://schema/alerts` | Alert object fields, types, and descriptions |
| `lm://schema/devices` | Device object fields and types |
| `lm://schema/sdts` | SDT (Scheduled Downtime) object fields |
| `lm://schema/dashboards` | Dashboard object fields |
| `lm://schema/collectors` | Collector object fields |
| `lm://schema/escalations` | Escalation chain object fields |
| `lm://schema/reports` | Report object fields |
| `lm://schema/websites` | Website check object fields |
| `lm://schema/datasources` | DataSource definition fields |
| `lm://schema/users` | User object fields |
| `lm://schema/audit` | Audit log entry fields |

### Enum Resources
| URI | Description |
|-----|-------------|
| `lm://enums/severity` | Alert severity levels: critical(4), error(3), warning(2), info(1) |
| `lm://enums/device-status` | Device status values: normal(0), dead(1), etc. |
| `lm://enums/sdt-type` | SDT types: DeviceSDT, DeviceGroupSDT, etc. |
| `lm://enums/alert-cleared` | Alert cleared status: true, false |
| `lm://enums/alert-acked` | Alert acknowledgment status: true, false |
| `lm://enums/collector-build` | Collector build types: EA, GD, MGD |

### Filter Resources
| URI | Description |
|-----|-------------|
| `lm://filters/alerts` | Filter fields and operators for alert queries |
| `lm://filters/devices` | Filter fields and operators for device queries |
| `lm://filters/sdts` | Filter fields and operators for SDT queries |
| `lm://syntax/operators` | Filter operators: `:`, `~`, `>`, `<`, `!:`, `!~`, `>:`, `<:` |

### Guide Resources
| URI | Description |
|-----|-------------|
| `lm://guide/tool-categories` | All 306 tools organized by domain category |
| `lm://guide/examples` | Common filter patterns and query examples |
| `lm://guide/mcp-orchestration` | Patterns for combining LogicMonitor with other MCP servers |
| `lm://guide/best-practices` | Scenario-based best practices with recommendations and anti-patterns |
| `lm://guide/example-responses` | Example output for key tools to help understand response formats |

## MCP Prompts

Pre-built workflow templates for common tasks:

| Prompt | Description | Arguments |
|--------|-------------|-----------|
| `incident_triage` | Analyze active alerts, identify patterns, suggest root cause | `severity`, `time_window_hours` |
| `capacity_review` | Review resource utilization and identify capacity concerns | `group_id`, `threshold_percent` |
| `health_check` | Generate environment health summary with key metrics | `include_collectors` |
| `alert_summary` | Generate alert digest grouped by severity or resource | `group_by`, `hours_back` |
| `sdt_planning` | Plan scheduled downtime for maintenance windows | `device_ids`, `group_id` |
| `cost_optimization` | Analyze cloud costs, find savings opportunities | `provider`, `threshold_percent` |
| `audit_review` | Review recent changes, logins, and security events | `hours_back`, `username` |
| `alert_correlation` | Correlate alerts across devices to find common root causes | `severity`, `hours_back`, `device_id`, `group_id` |
| `collector_health` | Assess collector load balancing, versions, and failover readiness | `group_id` |
| `troubleshoot_device` | Guided troubleshooting for a specific device | `device_id` |
| `top_talkers` | Identify noisiest devices and datasources generating the most alerts | `hours_back`, `limit`, `group_by` |
| `rca_workflow` | Guided root cause analysis combining alerts, topology, and change history | `device_id`, `alert_id`, `hours_back` |
| `capacity_forecast` | Forecast capacity trends and predict threshold breaches | `device_id`, `group_id`, `datasource`, `hours_back`, `threshold` |
| `remediate_workflow` | Diagnose a LogicMonitor alert and remediate via Ansible Automation Platform | `alert_id`, `device_id` |
| `remediation` | Execute a LogicMonitor remediation source with pre-execution safety checks | `host_id`, `remediation_source_id` |

## Example Usage

Once configured, ask your assistant in natural language. A representative sample (the server understands far more across all 306 tools):

- "List the first 5 devices in LogicMonitor" (quick connectivity check)
- "Show me all critical alerts from the last hour"
- "Acknowledge alert LMA12345 with note 'Investigating disk issue'"
- "What datasources are applied to device 123, and get CPU metrics for the last hour"
- "Create a dashboard called 'API Health' and add a graph widget"
- "Create a 2-hour maintenance window (SDT) for device 123"
- "Triage all critical alerts from the last 4 hours"
- "Run a health check on device 123, then give me a portal overview for shift handoff"
- "Forecast when memory on device 123 will hit 90%"
- "What's the blast radius if device 789 goes down?"
- "What diagnostics ran on device 123 today, and what did the scripts output?"

For power users, the server accepts LogicMonitor filter syntax directly, for example "Get devices where filter is 'displayName~"prod",hostStatus:"normal"'". String values, `hostStatus` words included, are quoted.

## Development

### Running Tests

```bash
uv run pytest -v
```

### Linting

```bash
uv run ruff check src tests
uv run ruff format src tests
```

### Project Structure

```
src/lm_mcp/
├── __init__.py           # Package exports
├── analysis.py           # Scheduled analysis workflows and store
├── awx_config.py         # AAP connection configuration
├── config.py             # Environment-based configuration
├── exceptions.py         # Exception hierarchy
├── health.py             # Health check endpoints
├── logging.py            # Structured logging
├── server.py             # MCP server entry point
├── session.py            # Session context with optional persistence
├── registry.py           # Tool definitions and handlers (TOOLS + AWX_TOOLS)
├── validation.py         # Field validation with suggestions
├── auth/
│   ├── __init__.py       # Auth provider factory
│   ├── bearer.py         # Bearer token auth
│   └── lmv1.py           # LMv1 HMAC auth
├── client/
│   ├── __init__.py       # Client exports
│   ├── api.py            # Async HTTP client for LogicMonitor API
│   └── awx.py            # Async HTTP client for AAP controller API
├── completions/
│   └── registry.py       # Auto-complete definitions
├── prompts/
│   ├── registry.py       # Prompt definitions
│   └── templates.py      # Workflow template content
├── resources/
│   ├── registry.py       # Resource definitions
│   ├── schemas.py        # Schema content
│   ├── enums.py          # Enum content
│   ├── filters.py        # Filter content
│   ├── guides.py         # Tool categories, query examples, orchestration guide
│   ├── best_practices.py # Scenario-based best practices and anti-patterns
│   └── examples.py       # Example responses for key tools
├── transport/
│   ├── __init__.py       # Transport abstraction
│   └── http.py           # HTTP/SSE transport with analysis endpoints
└── tools/
    ├── __init__.py       # Tool utilities
    ├── alerts.py         # Alert management
    ├── alert_rules.py    # Alert rule CRUD
    ├── ansible.py        # Ansible Automation Platform tool handlers
    ├── baselines.py      # Metric baseline save/compare
    ├── collectors.py     # Collector tools
    ├── correlation.py    # Alert correlation, anomaly detection, metric correlation
    ├── cost.py           # Cost optimization
    ├── dashboards.py     # Dashboard CRUD
    ├── devices.py        # Device CRUD
    ├── escalations.py    # Escalation/recipient CRUD
    ├── event_correlation.py  # Change-alert correlation
    ├── forecasting.py    # Forecast, trend, seasonality, change points
    ├── imports.py        # LogicModule import
    ├── ingestion.py      # Log/metric ingestion
    ├── metrics.py        # Metrics and data
    ├── scoring.py        # Alert noise, availability, device health
    ├── sdts.py           # SDT management
    ├── session.py        # Session management tools
    ├── stats_helpers.py  # Shared statistical math utilities (incl. Holt-Winters, IQR, MAD)
    ├── topology_analysis.py  # Blast radius analysis
    ├── websites.py       # Website CRUD
    ├── workflows.py      # Composite workflow tools (triage, health_check, etc.)
    ├── metric_presets.py # Metric-type presets for auto-configuration
    └── ...               # Additional tool modules

examples/playbooks/
├── lm-remediate-disk-cleanup.yml
├── lm-remediate-service-restart.yml
├── lm-remediate-log-rotate.yml
└── lm-remediate-memory-cache-clear.yml

deploy/
├── Dockerfile            # Production Docker image
├── docker-compose.yml    # Full stack deployment
├── Caddyfile             # TLS proxy configuration
└── .env.example          # Environment template
```

## Troubleshooting

### "Failed to connect" in Claude Code

If `claude mcp list` shows `✗ Failed to connect`, the server is missing environment variables. The `-e` flags must be included when adding the server:

```bash
# Remove the broken config
claude mcp remove logicmonitor

# Re-add with environment variables
claude mcp add logicmonitor \
  -e LM_PORTAL=yourcompany.logicmonitor.com \
  -e LM_BEARER_TOKEN=<your-bearer-token> \
  -- uvx --from lm-mcp lm-mcp-server
```

> **Note:** Setting environment variables in your shell or `.env` file won't work—Claude Code spawns the MCP server as a subprocess with its own environment.

### "Write operations are disabled"

Write operations (acknowledge, create SDT, etc.) are disabled by default. Set `LM_ENABLE_WRITE_OPERATIONS=true` in your environment.

### "spawn uvx ENOENT" in Claude Desktop

Claude Desktop can't find `uvx`. Use the full path:

```json
{
  "command": "/Users/yourname/.local/bin/uvx",
  "args": ["--from", "lm-mcp", "lm-mcp-server"]
}
```

Find your uvx path with: `which uvx`

### Ingestion API Errors

The `ingest_logs` and `push_metrics` tools require LMv1 authentication. Bearer tokens don't work with ingestion APIs. Add `LM_ACCESS_ID` and `LM_ACCESS_KEY` to your configuration.

### Rate Limit Errors

The server automatically retries rate-limited requests with exponential backoff. If you're consistently hitting limits, reduce request frequency or contact LogicMonitor support.

### Authentication Errors

Verify your bearer token is correct and has appropriate permissions. API tokens can be managed in LogicMonitor under **Settings** → **Users and Roles** → **API Tokens**.

## License

MIT License - see LICENSE file.
