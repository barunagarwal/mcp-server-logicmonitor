# LogicMonitor MCP Server

[![PyPI version](https://img.shields.io/pypi/v/lm-mcp.svg)](https://pypi.org/project/lm-mcp/)
[![Python versions](https://img.shields.io/pypi/pyversions/lm-mcp.svg)](https://pypi.org/project/lm-mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

<!-- mcp-name: io.github.ryanmat/logicmonitor -->

Model Context Protocol (MCP) server for LogicMonitor REST API v3 integration. Enables AI assistants to interact with LogicMonitor monitoring data through 258+ structured tools, 15 workflow prompts, and 26 resources. Optional integrations: IBM watsonx.ai for Granite TTM forecasting and NL summaries, Terraform IaC for any provider, and HuggingFace local Granite model fallback.

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
  -e LM_BEARER_TOKEN=your-bearer-token \
  -- uvx --from lm-mcp lm-mcp-server
```

With **IBM watsonx.ai integration** (optional -- adds Granite TTM forecasting and NL summaries):
```bash
claude mcp add logicmonitor \
  -e LM_PORTAL=yourcompany.logicmonitor.com \
  -e LM_BEARER_TOKEN=your-bearer-token \
  -e WATSONX_API_KEY=your-ibm-cloud-api-key \
  -e WATSONX_URL=https://us-south.ml.cloud.ibm.com \
  -e WATSONX_PROJECT_ID=your-watsonx-project-id \
  -- uvx --from "lm-mcp[ibm]" lm-mcp-server
```

With **Terraform IaC** (optional -- adds terraform plan/apply/generate tools):
```bash
claude mcp add logicmonitor \
  -e LM_PORTAL=yourcompany.logicmonitor.com \
  -e LM_BEARER_TOKEN=your-bearer-token \
  -e TF_WORKSPACE_DIR=/path/to/terraform/workspaces \
  -- uvx --from lm-mcp lm-mcp-server
```

With **HuggingFace local models** (optional -- local Granite TTM + NL summaries, no cloud API needed):
```bash
claude mcp add logicmonitor \
  -e LM_PORTAL=yourcompany.logicmonitor.com \
  -e LM_BEARER_TOKEN=your-bearer-token \
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

## Release Notes

### v3.4.0 (Current)
- **New**: REST API create/update tools for all LogicModule source types -- ConfigSource, EventSource, LogSource, TopologySource, PropertySource. Enables export -> modify -> update workflows without delete/recreate.
- **Fix**: `update_datasource` description now correctly documents full-replace semantics (name and displayName required).
- **Fix**: All `import_*` tool descriptions clarify LM Exchange format requirement and direct users to `create_*` for REST API format.
- **Fix**: All `export_*` tool descriptions reference both `create_*` and `update_*` for round-tripping.
- **Fix**: Version synced across all locations (was drifted since v3.2.0).

### Changelog

<details>
<summary>v3.1.0-v3.3.0 — Terraform, HuggingFace, config tools, PropertySource create</summary>

- Terraform IaC integration -- 11 tools for plan, apply, state, import, and HCL generation
- HuggingFace local Granite fallback -- TTM forecasting and NL summaries via local models
- `[huggingface]` optional dependency group (torch, transformers, granite-tsfm, accelerate)
- Device config data retrieval and audit tools (get_device_config, get_device_config_version, collect_device_config)
- create_propertysource REST API tool
- 5-way dispatch (Session, AWX, WatsonX, Terraform, LM) with graceful degradation
- AI inference priority chain: watsonx.ai API > HuggingFace local > statistical/linear
</details>

### Changelog

<details>
<summary>v3.0.0 — IBM watsonx.ai integration</summary>

- IBM watsonx.ai integration (optional, requires `WATSONX_API_KEY`)
- Granite TTM time series forecasting via `method="ttm"` on `forecast_metric`
- Granite NL summaries via `summarize=true` on composite workflow tools
- `watsonx_summarize` standalone tool for ad-hoc data summarization
- `[ibm]` optional dependency group (`ibm-watsonx-ai`, `pandas`)
- 4-way dispatch (Session, AWX, WatsonX, LM)
</details>

<details>
<summary>v2.0.0–v2.6.0 — Composite workflows, ML analysis, AAP integration</summary>

- Progressive discovery via `search_tools`
- Holt-Winters, IQR/MAD anomaly detection, prediction intervals
- `calculate_error_budget` SLO tracking
- RemediationSource execution with 8-point safety checklist
- 18 Ansible Automation Platform tools
- User/role CRUD, collector group management, ops notes
- Portal URL links, HTTPS transport
</details>

## Features

**258+ Tools** across comprehensive LogicMonitor API coverage (230 LM + 18 AAP + 10 Terraform + 1 watsonx):

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
- **Search Tools**: Keyword search across all 230 tools by name and description with category filtering

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

AAP tools are optional — they only appear when `AWX_URL` and `AWX_TOKEN` are configured. See [Example Playbooks](examples/playbooks/) for remediation templates.

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

- **terraform_init**: Initialize workspace and download providers
- **terraform_validate**: Syntax-check HCL configuration
- **terraform_plan**: Preview changes with structured JSON output
- **terraform_apply**: Apply changes (triple-gated: write perms + config flag + confirm param)
- **terraform_destroy**: Destroy infrastructure (same triple gate)
- **terraform_import**: Import existing resources into Terraform state
- **terraform_state_list / terraform_state_show**: Inspect current state
- **terraform_output**: View Terraform outputs
- **terraform_write_config**: Write HCL files to workspace directories
- **terraform_generate**: Export existing LM portal resources as HCL using the `logicmonitor/logicmonitor` provider

Terraform tools are optional -- they only appear when `TF_WORKSPACE_DIR` is configured. Requires the `terraform` CLI installed separately.

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
- **Cost Optimization**: Cloud cost analysis, recommendations, idle resources (LM Envision)
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
- **Server Error Recovery**: Automatic retry on 5xx server errors
- **Pagination Support**: Handle large result sets with offset-based pagination
- **Session Persistence**: Optional file-backed session variables that survive restarts

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
# Edit .env with your credentials

# Run with docker-compose
docker compose up -d

# With TLS via Caddy
docker compose --profile tls up -d
```

The server exposes health endpoints for container orchestration:
- `GET /health` - Detailed health check with all component statuses
- `GET /healthz` - Liveness probe (200 OK or 503)
- `GET /readyz` - Readiness probe (includes connectivity check if enabled)

### Multi-Cloud Image Publishing

This repo includes a Travis build path for publishing the container image to the same GCP/AWS registries used by Edwin-style deployments:

- `eu.gcr.io/dexda-non-production/mcp-server-logicmonitor`
- `eu.gcr.io/dexda-production/mcp-server-logicmonitor`
- `560269851512.dkr.ecr.us-west-2.amazonaws.com/mcp-server-logicmonitor`

Builds are gated by `AUTOBUILD` for non-tag branches. Configure Travis repository secrets for the registries you want to target:

- `GCLOUD_SA_NON_PROD_JSON` - base64-encoded GCP service account JSON for `dexda-non-production`
- `GCLOUD_SA_PROD_JSON` - base64-encoded GCP service account JSON for `dexda-production` (tag builds only)
- `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` - AWS credentials for ECR
- `AWS_REGION` - defaults to `us-west-2`

### Kubernetes Deployment (Feature Test)

A feature-test manifest is included at `deploy/k8s/feature-test/mcp-server-logicmonitor.yaml`.
It points to `eu.gcr.io/dexda-non-production/mcp-server-logicmonitor:main` and expects the
existing `feature-test` secret `topology-feature-lmv1-token` with key `test-feature`.

Apply it with:

```bash
kubectl apply -f deploy/k8s/feature-test/mcp-server-logicmonitor.yaml
```

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LM_PORTAL` | Yes | - | LogicMonitor portal hostname (e.g., `company.logicmonitor.com`) |
| `LM_BEARER_TOKEN` | Yes* | - | API Bearer token (min 10 characters) |
| `LM_ACCESS_ID` | No | - | LMv1 API access ID (for ingestion APIs) |
| `LM_ACCESS_KEY` | No | - | LMv1 API access key (for ingestion APIs) |
| `LM_CREDENTIALS_JSON` | No | - | JSON credential payload containing `access_id`/`access_key` or `bearer_token`, and optionally `portal` or `portal_id` |
| `LM_ENABLE_WRITE_OPERATIONS` | No | `false` | Enable write operations (create, update, delete) |
| `LM_API_VERSION` | No | `3` | API version |
| `LM_TIMEOUT` | No | `30` | Request timeout in seconds (range: 5-300) |
| `LM_MAX_RETRIES` | No | `3` | Max retries for rate-limited/server error requests (range: 0-10) |
| `LM_TRANSPORT` | No | `stdio` | Transport mode: `stdio` (local) or `http` (remote) |
| `LM_HTTP_HOST` | No | `0.0.0.0` | HTTP server bind address |
| `LM_HTTP_PORT` | No | `8080` | HTTP server port |
| `LM_CORS_ORIGINS` | No | `*` | Comma-separated CORS origins |
| `LM_SESSION_ENABLED` | No | `true` | Enable session context tracking |
| `LM_SESSION_HISTORY_SIZE` | No | `50` | Number of tool calls to keep in history |
| `LM_LOG_LEVEL` | No | `warning` | Logging level: `debug`, `info`, `warning`, or `error` |
| `LM_FIELD_VALIDATION` | No | `warn` | Field validation: `off`, `warn`, or `error` |
| `LM_HEALTH_CHECK_CONNECTIVITY` | No | `false` | Include LM API ping in health checks |
| `LM_SESSION_PERSIST_PATH` | No | - | File path for persistent session variables (survives restarts) |
| `LM_ANALYSIS_TTL_MINUTES` | No | `60` | TTL for scheduled analysis results (1-1440 minutes) |
| `AWX_URL` | No | - | Ansible Automation Platform controller URL (e.g., `https://aap.example.com`) |
| `AWX_TOKEN` | No | - | AAP personal access token |
| `AWX_VERIFY_SSL` | No | `true` | Verify SSL certificates for AAP connections |
| `AWX_TIMEOUT` | No | `30` | Request timeout in seconds for AAP API calls |
| `AWX_MAX_RETRIES` | No | `3` | Max retries for failed AAP API requests |
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

`LM_CREDENTIALS_JSON` is an alternative way to provide those credentials, which is useful
when injecting a single Kubernetes secret value that already contains a JSON payload.

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

### Claude Code

```bash
claude mcp add logicmonitor \
  -e LM_PORTAL=yourcompany.logicmonitor.com \
  -e LM_BEARER_TOKEN=your-bearer-token \
  -e LM_ENABLE_WRITE_OPERATIONS=true \
  -- uvx --from lm-mcp lm-mcp-server
```

> **Note:** Remove `-e LM_ENABLE_WRITE_OPERATIONS=true` if you want read-only access.
>
> **IBM watsonx.ai:** To enable Granite TTM forecasting and NL summaries, add `-e WATSONX_API_KEY=... -e WATSONX_URL=... -e WATSONX_PROJECT_ID=...` and change `--from lm-mcp` to `--from "lm-mcp[ibm]"`.

Verify the connection:
```bash
claude mcp list
```

To update an existing configuration, remove and re-add:
```bash
claude mcp remove logicmonitor
claude mcp add logicmonitor -e LM_PORTAL=... -e LM_BEARER_TOKEN=... -- uvx --from lm-mcp lm-mcp-server
```

### Cursor

Add to `~/.cursor/mcp.json` (global) or `.cursor/mcp.json` (project):

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

To enable write operations and ingestion APIs:

```json
{
  "mcpServers": {
    "logicmonitor": {
      "command": "uvx",
      "args": ["--from", "lm-mcp", "lm-mcp-server"],
      "env": {
        "LM_PORTAL": "yourcompany.logicmonitor.com",
        "LM_BEARER_TOKEN": "your-bearer-token",
        "LM_ACCESS_ID": "your-access-id",
        "LM_ACCESS_KEY": "your-access-key",
        "LM_ENABLE_WRITE_OPERATIONS": "true"
      }
    }
  }
}
```

Then restart Cursor or enable the server in **Cursor Settings** → **MCP**.

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

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

To enable write operations and ingestion APIs:

```json
{
  "mcpServers": {
    "logicmonitor": {
      "command": "uvx",
      "args": ["--from", "lm-mcp", "lm-mcp-server"],
      "env": {
        "LM_PORTAL": "yourcompany.logicmonitor.com",
        "LM_BEARER_TOKEN": "your-bearer-token",
        "LM_ACCESS_ID": "your-access-id",
        "LM_ACCESS_KEY": "your-access-key",
        "LM_ENABLE_WRITE_OPERATIONS": "true"
      }
    }
  }
}
```

### OpenAI Codex CLI

```bash
codex mcp add logicmonitor \
  --env LM_PORTAL=yourcompany.logicmonitor.com \
  --env LM_BEARER_TOKEN=your-bearer-token \
  -- uvx --from lm-mcp lm-mcp-server
```

Or add directly to `~/.codex/config.toml`:

```toml
[mcp_servers.logicmonitor]
command = "uvx"
args = ["--from", "lm-mcp", "lm-mcp-server"]

[mcp_servers.logicmonitor.env]
LM_PORTAL = "yourcompany.logicmonitor.com"
LM_BEARER_TOKEN = "your-bearer-token"
```

### Cline (VS Code Extension)

Add to Cline's MCP settings file:

**macOS**: `~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json`

**Windows**: `%APPDATA%\Code\User\globalStorage\saoudrizwan.claude-dev\settings\cline_mcp_settings.json`

**Linux**: `~/.config/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json`

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

### GitHub Copilot (VS Code 1.99+)

Add to your VS Code settings (`settings.json`) or project-level `.vscode/mcp.json`:

```json
{
  "mcp": {
    "servers": {
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
}
```

Enable MCP in VS Code settings: `"chat.mcp.enabled": true`

### Gemini CLI

Gemini CLI supports MCP servers. Configure in `~/.gemini/settings.json`:

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

### Other Clients

**Aider**: Does not currently have native MCP support. Track progress at [aider issue #3314](https://github.com/Aider-AI/aider/issues/3314).

**Continue**: Uses similar JSON configuration. See [Continue MCP docs](https://docs.continue.dev/customize/model-providers/mcp).

### Enabling Write Operations

For any JSON-based configuration, add `LM_ENABLE_WRITE_OPERATIONS` to the `env` section:

```json
"env": {
  "LM_PORTAL": "yourcompany.logicmonitor.com",
  "LM_BEARER_TOKEN": "your-bearer-token",
  "LM_ENABLE_WRITE_OPERATIONS": "true"
}
```

This enables tools like `acknowledge_alert`, `create_sdt`, `create_device`, etc.

## Available Tools

### Alert Tools

| Tool | Description | Write |
|------|-------------|-------|
| `get_alerts` | List alerts with optional severity/status/group/device filters | No |
| `get_alert_details` | Get detailed information about a specific alert | No |
| `acknowledge_alert` | Acknowledge an alert with optional note | Yes |
| `add_alert_note` | Add a note to an alert | Yes |
| `bulk_acknowledge_alerts` | Acknowledge multiple alerts at once (max 100) | Yes |

### Alert Rule Tools

| Tool | Description | Write |
|------|-------------|-------|
| `get_alert_rules` | List alert rules | No |
| `get_alert_rule` | Get detailed alert rule information | No |
| `create_alert_rule` | Create a new alert rule | Yes |
| `update_alert_rule` | Update an existing alert rule | Yes |
| `delete_alert_rule` | Delete an alert rule | Yes |
| `export_alert_rule` | Export alert rule as JSON | No |

### Device Tools

| Tool | Description | Write |
|------|-------------|-------|
| `get_devices` | List devices with optional group/name filters | No |
| `get_device` | Get detailed information about a specific device | No |
| `get_device_groups` | List device groups | No |
| `create_device` | Create a new device | Yes |
| `update_device` | Update an existing device | Yes |
| `delete_device` | Delete a device | Yes |
| `create_device_group` | Create a new device group | Yes |
| `update_device_group` | Update a device group (name, properties, AppliesTo, alerting) | Yes |
| `delete_device_group` | Delete a device group | Yes |

### Metrics Tools

| Tool | Description | Write |
|------|-------------|-------|
| `get_device_datasources` | List DataSources applied to a device | No |
| `get_device_instances` | List instances for a DataSource on a device | No |
| `get_device_data` | Get metric data for a specific instance | No |
| `get_graph_data` | Get graph data for visualization | No |

### APM Trace Tools

| Tool | Description | Write |
|------|-------------|-------|
| `get_trace_services` | List APM trace services (deviceType:6) | No |
| `get_trace_service` | Get detailed APM service information | No |
| `get_trace_service_alerts` | Get alerts for an APM service | No |
| `get_trace_service_datasources` | List datasources applied to an APM service | No |
| `get_trace_operations` | List operations (endpoints/routes) for an APM service | No |
| `get_trace_service_metrics` | Get service-level RED metrics (Duration, ErrorOperationCount, OperationCount) | No |
| `get_trace_operation_metrics` | Get per-operation RED metrics | No |
| `get_trace_service_properties` | Get APM service properties (OTel attributes, metadata) | No |

### Dashboard Tools

| Tool | Description | Write |
|------|-------------|-------|
| `get_dashboards` | List dashboards with optional filters | No |
| `get_dashboard` | Get detailed dashboard information | No |
| `get_dashboard_widgets` | Get widgets for a specific dashboard | No |
| `get_widget` | Get detailed widget information | No |
| `get_dashboard_groups` | List dashboard groups | No |
| `get_dashboard_group` | Get dashboard group details | No |
| `create_dashboard` | Create a new dashboard | Yes |
| `update_dashboard` | Update an existing dashboard | Yes |
| `delete_dashboard` | Delete a dashboard | Yes |
| `add_widget` | Add a widget to a dashboard | Yes |
| `update_widget` | Update a widget | Yes |
| `delete_widget` | Delete a widget from a dashboard | Yes |
| `export_dashboard` | Export dashboard as JSON | No |
| `create_dashboard_group` | Create a dashboard group | Yes |
| `update_dashboard_group` | Update a dashboard group | Yes |
| `delete_dashboard_group` | Delete a dashboard group | Yes |

### SDT Tools

| Tool | Description | Write |
|------|-------------|-------|
| `list_sdts` | List Scheduled Downtime entries | No |
| `get_active_sdts` | Get currently active SDTs | No |
| `get_upcoming_sdts` | Get SDTs scheduled within a time window | No |
| `create_sdt` | Create a new SDT for a device or group | Yes |
| `update_sdt` | Update an existing SDT (fetch-modify-PUT) | Yes |
| `delete_sdt` | Delete an existing SDT | Yes |
| `bulk_create_device_sdt` | Create SDT for multiple devices (max 100) | Yes |
| `bulk_delete_sdt` | Delete multiple SDTs at once (max 100) | Yes |

### Collector Tools

| Tool | Description | Write |
|------|-------------|-------|
| `get_collectors` | List all collectors | No |
| `get_collector` | Get detailed information about a specific collector | No |
| `get_collector_groups` | List collector groups | No |
| `get_collector_group` | Get detailed collector group info | No |
| `create_collector_group` | Create a collector group | Yes |
| `update_collector_group` | Update a collector group | Yes |
| `delete_collector_group` | Delete a collector group (blocks if collectors assigned) | Yes |

### Website Tools

| Tool | Description | Write |
|------|-------------|-------|
| `get_websites` | List websites/synthetic checks | No |
| `get_website` | Get detailed website information | No |
| `get_website_groups` | List website groups | No |
| `get_website_data` | Get monitoring data for a website | No |
| `create_website` | Create a new website check | Yes |
| `update_website` | Update a website check | Yes |
| `delete_website` | Delete a website check | Yes |
| `create_website_group` | Create a website group | Yes |
| `delete_website_group` | Delete a website group | Yes |

### Escalation Tools

| Tool | Description | Write |
|------|-------------|-------|
| `get_escalation_chains` | List escalation chains | No |
| `get_escalation_chain` | Get detailed escalation chain info | No |
| `create_escalation_chain` | Create a new escalation chain | Yes |
| `update_escalation_chain` | Update an escalation chain | Yes |
| `delete_escalation_chain` | Delete an escalation chain | Yes |
| `export_escalation_chain` | Export escalation chain as JSON | No |
| `get_recipient_groups` | List recipient groups | No |
| `get_recipient_group` | Get detailed recipient group info | No |
| `create_recipient_group` | Create a new recipient group | Yes |
| `update_recipient_group` | Update a recipient group | Yes |
| `delete_recipient_group` | Delete a recipient group | Yes |

### Resource Tools

| Tool | Description | Write |
|------|-------------|-------|
| `get_device_properties` | List all properties for a device | No |
| `get_device_property` | Get a specific device property | No |
| `update_device_property` | Update or create a custom device property | Yes |

### Report Tools

| Tool | Description | Write |
|------|-------------|-------|
| `get_reports` | List reports with optional filters | No |
| `get_report` | Get detailed report information | No |
| `get_report_groups` | List report groups | No |
| `get_scheduled_reports` | Get reports with schedules configured | No |
| `run_report` | Execute/run a report | Yes |
| `create_report` | Create a new report | Yes |
| `update_report_schedule` | Update a report's schedule | Yes |
| `delete_report` | Delete a report | Yes |

### DataSource Tools

| Tool | Description | Write |
|------|-------------|-------|
| `get_datasources` | List all DataSources | No |
| `get_datasource` | Get DataSource details | No |
| `export_datasource` | Export DataSource as JSON | No |
| `import_datasource` | Import DataSource from JSON | Yes |
| `create_datasource` | Create DataSource via REST API format (supports overwrite) | Yes |
| `update_datasource` | Update existing DataSource definition | Yes |
| `delete_datasource` | Delete a DataSource definition | Yes |

### LogicModule Tools

| Tool | Description | Write |
|------|-------------|-------|
| `get_configsources` | List ConfigSources | No |
| `get_configsource` | Get ConfigSource details | No |
| `get_configsource_update_reasons` | Get ConfigSource change audit trail | No |
| `get_device_config` | List config versions for a device instance | No |
| `get_device_config_version` | Get config content with diffs and alerts | No |
| `collect_device_config` | Trigger on-demand config collection | Yes |
| `export_configsource` | Export ConfigSource as JSON | No |
| `import_configsource` | Import ConfigSource from JSON | Yes |
| `get_eventsources` | List EventSources | No |
| `get_eventsource` | Get EventSource details | No |
| `export_eventsource` | Export EventSource as JSON | No |
| `import_eventsource` | Import EventSource from JSON | Yes |
| `get_propertysources` | List PropertySources | No |
| `get_propertysource` | Get PropertySource details | No |
| `create_propertysource` | Create PropertySource via REST API | Yes |
| `export_propertysource` | Export PropertySource as JSON | No |
| `import_propertysource` | Import PropertySource from JSON | Yes |
| `get_topologysources` | List TopologySources | No |
| `get_topologysource` | Get TopologySource details | No |
| `import_topologysource` | Import TopologySource from JSON | Yes |
| `get_logsources` | List LogSources | No |
| `get_logsource` | Get LogSource details | No |
| `get_device_logsources` | Get LogSources applied to a device | No |
| `export_logsource` | Export LogSource as JSON | No |
| `import_logsource` | Import LogSource from JSON | Yes |
| `import_jobmonitor` | Import JobMonitor from JSON | Yes |
| `import_appliesto_function` | Import AppliesTo function from JSON | Yes |

### Cost Optimization Tools (LM Envision)

| Tool | Description | Write |
|------|-------------|-------|
| `get_cost_summary` | Get cloud cost summary | No |
| `get_resource_cost` | Get cost data for a specific resource | No |
| `get_cost_recommendations` | Get cost optimization recommendations | No |
| `get_cost_recommendation_categories` | Get recommendation categories with counts | No |
| `get_cost_recommendation` | Get specific recommendation by ID | No |
| `get_idle_resources` | Get idle/underutilized resources | No |
| `get_cloud_cost_accounts` | Get cloud accounts with cost data | No |

### Ingestion Tools (Requires LMv1 Auth)

| Tool | Description | Write |
|------|-------------|-------|
| `ingest_logs` | Push log entries to LogicMonitor | Yes |
| `push_metrics` | Push custom metrics to LogicMonitor | Yes |

### Network & Topology Tools

| Tool | Description | Write |
|------|-------------|-------|
| `get_topology_map` | Get network topology map data | No |
| `get_device_neighbors` | Get neighboring devices based on topology | No |
| `get_device_interfaces` | Get network interfaces for a device | No |
| `get_network_flows` | Get network flow data (NetFlow/sFlow) | No |
| `get_device_connections` | Get device relationships/connections | No |

### Batch Job Tools

| Tool | Description | Write |
|------|-------------|-------|
| `get_batchjobs` | List batch jobs | No |
| `get_batchjob` | Get batch job details | No |
| `get_batchjob_history` | Get execution history for a batch job | No |
| `get_device_batchjobs` | Get batch jobs for a specific device | No |
| `get_scheduled_downtime_jobs` | Get batch jobs related to SDT automation | No |

### Ops & Audit Tools

| Tool | Description | Write |
|------|-------------|-------|
| `get_audit_logs` | Get audit log entries | No |
| `get_api_token_audit` | Get API token usage audit logs | No |
| `get_login_audit` | Get login/authentication audit logs | No |
| `get_change_audit` | Get configuration change audit logs | No |
| `get_ops_notes` | List ops notes | No |
| `get_ops_note` | Get detailed ops note information | No |
| `add_ops_note` | Add a new ops note | Yes |
| `update_ops_note` | Update an existing ops note | Yes |
| `delete_ops_note` | Delete an ops note | Yes |

### User & Access Tools

| Tool | Description | Write |
|------|-------------|-------|
| `get_users` | List users | No |
| `get_user` | Get detailed user information | No |
| `create_user` | Create a new user | Yes |
| `update_user` | Update an existing user | Yes |
| `delete_user` | Delete a user | Yes |
| `get_roles` | List roles | No |
| `get_role` | Get detailed role information | No |
| `get_access_groups` | List access groups (RBAC) | No |
| `get_access_group` | Get access group details | No |
| `get_api_tokens` | List API tokens | No |
| `get_api_token` | Get API token details | No |

### Service Tools

| Tool | Description | Write |
|------|-------------|-------|
| `get_services` | List services (LM Service Insight) | No |
| `get_service` | Get detailed service information | No |
| `get_service_groups` | List service groups | No |

### Netscan Tools

| Tool | Description | Write |
|------|-------------|-------|
| `get_netscans` | List network discovery scans | No |
| `get_netscan` | Get detailed netscan information | No |
| `run_netscan` | Execute a netscan immediately | Yes |

### OID Tools

| Tool | Description | Write |
|------|-------------|-------|
| `get_oids` | List SNMP OIDs | No |
| `get_oid` | Get detailed OID information | No |

### Session Tools

| Tool | Description | Write |
|------|-------------|-------|
| `get_session_context` | Get current session state (last results, variables, history) | No |
| `set_session_variable` | Store a named variable in the session | No |
| `get_session_variable` | Retrieve a session variable | No |
| `delete_session_variable` | Delete a session variable | No |
| `clear_session_context` | Reset all session state | No |
| `list_session_history` | List recent tool call history | No |

### Correlation & Analysis Tools

| Tool | Description | Write |
|------|-------------|-------|
| `correlate_alerts` | Cluster related alerts by device, datasource, and temporal proximity | No |
| `get_alert_statistics` | Aggregated alert counts by severity, top devices/datasources, time buckets | No |
| `get_metric_anomalies` | Multi-method anomaly detection (z-score/IQR/MAD/auto) on metric datapoints | No |

### Baseline Tools

| Tool | Description | Write |
|------|-------------|-------|
| `save_baseline` | Save a metric baseline snapshot to session for later comparison | No |
| `compare_to_baseline` | Compare current metrics against a saved baseline | No |

### ML/Statistical Analysis Tools

| Tool | Description | Write |
|------|-------------|-------|
| `forecast_metric` | Multi-method forecasting (linear/Holt-Winters/auto) with confidence intervals | No |
| `correlate_metrics` | Pearson correlation matrix across multiple metric series (max 10) | No |
| `detect_change_points` | CUSUM-based regime shift detection with configurable sensitivity | No |
| `score_alert_noise` | Shannon entropy + flap detection to score alert noise (0-100) | No |
| `detect_seasonality` | Autocorrelation-based periodicity detection at standard intervals | No |
| `calculate_availability` | SLA-style uptime % from alert history with MTTR and incident counts | No |
| `analyze_blast_radius` | Topology-based downstream impact scoring for device failures | No |
| `correlate_changes` | Cross-reference alert spikes with audit/change logs | No |
| `classify_trend` | Categorize metric behavior: stable, increasing, decreasing, cyclic, volatile | No |
| `score_device_health` | Composite health score (0-100) from multi-metric z-score analysis | No |

### Ansible Automation Platform Tools

These tools are only available when `AWX_URL` and `AWX_TOKEN` are configured.

| Tool | Description | Write |
|------|-------------|-------|
| `test_awx_connection` | Test connectivity to Ansible Automation Platform controller | No |
| `get_job_templates` | List job templates with optional name/project filters | No |
| `get_job_template` | Get details of a specific job template | No |
| `launch_job` | Launch a job template with extra variables, host limits, and check mode | Yes |
| `get_job_status` | Get the status of a running or completed job | No |
| `get_job_output` | Get the stdout output of a job | No |
| `cancel_job` | Cancel a running job | Yes |
| `relaunch_job` | Relaunch a previously run job with optional variable overrides | Yes |
| `get_inventories` | List inventories with optional name filter | No |
| `get_inventory_hosts` | List hosts in a specific inventory | No |
| `launch_workflow` | Launch a workflow job template | Yes |
| `get_workflow_status` | Get the status of a workflow job | No |
| `get_workflow_templates` | List workflow job templates | No |
| `get_projects` | List projects from Ansible Automation Platform | No |
| `get_credentials` | List credentials (secrets not exposed) | No |
| `get_organizations` | List organizations from Ansible Automation Platform | No |
| `get_job_events` | Get events from a specific job run | No |
| `get_hosts` | List hosts with optional name/inventory filters | No |

### Remediation Tools

| Tool | Description | Write |
|------|-------------|-------|
| `get_diagnosticsources` | List diagnostic sources from Exchange Toolbox | No |
| `get_diagnosticsource` | Get diagnostic source details | No |
| `get_remediationsources` | List remediation sources from Exchange Toolbox | No |
| `get_remediationsource` | Get remediation source details | No |
| `execute_remediation` | Execute a remediation source on a device with safety checks | Yes |
| `get_remediation_status` | Get current status of a remediation source on a device | No |
| `get_remediation_history` | Get past remediation executions from audit logs | No |

### Composite Workflow Tools

| Tool | Description | Write |
|------|-------------|-------|
| `triage` | Multi-step alert triage: correlation, noise scoring, blast radius, change correlation | No |
| `health_check` | Device health: score, anomalies, alerts, availability, monitoring coverage | No |
| `capacity_plan` | Capacity planning: forecasting, trends, seasonality per datasource | No |
| `portal_overview` | Portal snapshot: alert stats, collectors, SDTs, clusters, down devices | No |
| `diagnose` | Alert diagnosis: details, device context, correlation, blast radius, root cause | No |
| `search_tools` | Keyword search across all tools by name and description | No |

### Error Budget Tool

| Tool | Description | Write |
|------|-------------|-------|
| `calculate_error_budget` | SLO error budget tracking with burn rate and projected exhaustion | No |

#### ML Tool Usage Guide

These tools use pure-Python statistical methods (no external ML libraries). They all operate on data fetched from the LM API at query time. Most metric-based tools share the same core parameters: `device_id`, `device_datasource_id`, `instance_id` (find these using `get_device_datasources` and `get_device_instances`).

**Capacity forecasting** — predict when a metric will breach a threshold:
```
"Forecast when memory usage on device 150098 will exceed 90%"
```
Uses `forecast_metric` with `threshold=90`. Supports `method` parameter: `"auto"` (default, selects based on data), `"linear"` (regression), or `"holt_winters"` (seasonal). Returns days until breach, trend direction, confidence interval, and method used. Use `hours_back=168` (1 week) for meaningful regression, or `hours_back=24` if the device has limited history.

**Metric correlation** — find relationships between metrics across devices:
```
"Correlate CPU usage on server A with memory usage on server B over the last 24 hours"
```
Uses `correlate_metrics` with a `sources` array. Each source requires `device_id`, `device_datasource_id`, `instance_id`, and `datapoint` name. Returns an NxN Pearson correlation matrix and highlights strong correlations (|r| > 0.7). Maximum 10 sources per call.

**Change point detection** — find when metric behavior shifted:
```
"Detect any regime shifts in CPU metrics on device 150098 in the last 24 hours"
```
Uses `detect_change_points` with CUSUM algorithm. The `sensitivity` parameter (default 1.0) controls detection threshold — lower values detect smaller shifts. Returns timestamps and direction of each detected change.

**Alert noise scoring** — identify tuning opportunities:
```
"Score the alert noise across all devices over the last 24 hours"
```
Uses `score_alert_noise`. Returns a 0-100 noise score combining Shannon entropy, flap detection (alerts that clear and re-fire within 30 minutes), and repeat ratio. Includes top noisy devices/datasources and tuning recommendations.

**Device health scoring** — aggregate health into a single number:
```
"Give me a health score for the stress-demo pod"
```
Uses `score_device_health`. Computes z-scores for each datapoint's latest value against its historical window, then produces a weighted composite score (0-100). Status: healthy (80+), degraded (50-79), critical (<50). Use the `weights` parameter to emphasize specific datapoints.

**Availability calculation** — SLA reporting from alert data:
```
"Calculate 30-day availability across all devices at error severity or above"
```
Uses `calculate_availability` with `hours_back=720` and `severity_threshold="error"`. Merges overlapping alert windows and returns availability %, MTTR, incident count, longest incident, and per-device breakdown.

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
| `lm://guide/tool-categories` | All 220 tools organized by domain category |
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

Once configured, you can ask your AI assistant natural language questions. Here are prompts to test different capabilities:

### Quick Verification Prompts
Start with these to verify the connection is working:
- "List the first 5 devices in LogicMonitor"
- "How many collectors do I have?"
- "Show me active alerts"

### Alert Management
- "Show me all critical alerts"
- "What alerts fired in the last hour?"
- "Get details on alert LMA12345"
- "Acknowledge alert LMA12345 with note 'Investigating disk issue'"
- "Bulk acknowledge all warning alerts from the last hour"
- "Add a note to alert LMA67890: 'Escalated to storage team'"
- "What alert rules route to the Primary On-Call escalation chain?"

### Device Operations
- "What devices are in the Production group?"
- "Find all devices with 'web' in the name"
- "Show me details for device ID 123"
- "Add device 10.0.0.1 called 'web-server-03' to group ID 5 using collector 2"
- "Create a device group called 'Staging' under the Production group"
- "Update the description on device 456 to 'Primary web server'"

### Monitoring & Metrics
- "What datasources are applied to device 123?"
- "Show me the instances for datasource 456 on device 123"
- "Get CPU metrics for the last hour on device 123"
- "List all collectors and their status"

### Dashboards & Visualization
- "List all dashboards"
- "Show me dashboards with 'NOC' in the name"
- "What widgets are on dashboard 123?"
- "Create a new dashboard called 'API Health'"
- "Add a graph widget to dashboard 123"

### Scheduled Downtime (SDT)
- "List all active SDTs"
- "What SDTs are coming up in the next 24 hours?"
- "Create a 2-hour maintenance window for device 123"
- "Schedule downtime for devices 1, 2, and 3 for 1 hour"
- "Delete SDT abc123"

### Website Monitoring
- "List all website checks"
- "Create a ping check for example.com"
- "Show me details for website 123"
- "Update the polling interval on website 456 to 10 minutes"

### Cost Optimization (LM Envision)
- "Show me a cloud cost summary"
- "What are the cost optimization recommendations?"
- "List idle resources under 10% utilization"
- "What are the cost recommendation categories?"

### LogicModule Management
- "Export datasource ID 123 as JSON"
- "List all ConfigSources"
- "Show me EventSources that apply to Windows"
- "Import this datasource JSON definition"
- "Show me the running config for device 42"
- "What changed in the last config collection for this switch?"
- "Trigger a config collection on device 100"

### Log & Metric Ingestion
- "Push this log entry to LogicMonitor: 'Application started successfully'"
- "Send these metrics to device server1"

### Escalations & Notifications
- "Show me all escalation chains"
- "Create an escalation chain called 'Critical Alerts'"
- "List recipient groups"
- "Who is in the 'DevOps On-Call' recipient group?"

### Operations & Audit
- "Show me recent audit log entries"
- "What configuration changes were made in the last 24 hours?"
- "Show me failed login attempts"
- "List ops notes tagged 'maintenance'"
- "Add an ops note: 'Starting v2.5 deployment' with tag 'deployment'"

### Composite Workflows
- "Triage all critical alerts from the last 4 hours"
- "Run a health check on device 123"
- "Do a capacity plan for the database server over the last week"
- "Give me a portal overview for shift handoff"
- "Diagnose alert LMA12345"
- "Search for tools related to dashboards"

### ML Analysis & Forecasting
- "Forecast when memory on device 123 will hit 90%"
- "Score the alert noise level across all devices"
- "Classify the trend for CPU metrics on device 456"
- "Detect any change points in network throughput over the last 24 hours"
- "Check if there's a seasonal pattern in CPU usage over the past week"
- "Calculate 30-day availability for the Production group"
- "What's the blast radius if device 789 goes down?"
- "Correlate recent config changes with alert spikes"
- "Give me a health score for device 123"
- "Are CPU and memory correlated on my web servers?"
- "Calculate error budget for the Production group with a 99.9% SLO"

### Advanced Filtering
The server supports LogicMonitor's filter syntax for power users:
- "Get devices where filter is 'displayName~prod,hostStatus:alive'"
- "List alerts with filter 'severity>2,cleared:false'"
- "Find datasources matching 'appliesTo~isWindows()'"

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
  -e LM_BEARER_TOKEN=your-bearer-token \
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

## Changelog

### v3.2.0
- **New**: `get_device_config` -- list config versions collected for a device instance from the Config Archive
- **New**: `get_device_config_version` -- retrieve full config text, line-by-line diffs, and triggered alerts
- **New**: `collect_device_config` -- trigger on-demand config collection (write operation)
- **New**: `get_configsource_update_reasons` -- audit trail of ConfigSource definition changes
- **Counts**: 249 tools (220 LM + 18 AAP + 10 Terraform + 1 watsonx), 15 prompts, 26 resources

### v2.5.0
- **New**: `create_user`, `update_user`, `delete_user` -- full user account CRUD
- **New**: `create_collector_group`, `update_collector_group`, `delete_collector_group` -- collector group management with safety guards
- **New**: `update_ops_note`, `delete_ops_note` -- ops note write operations
- **New**: `update_dashboard_group` -- dashboard group updates
- **New**: `update_sdt` -- modify scheduled downtimes (fetch-modify-PUT)

### v2.4.0
- **New**: Portal URL links in detail tool responses (`get_device`, `get_alert_details`, `get_dashboard`, `get_device_group`, `get_website`)
- **New**: HTTPS transport support via `LM_HTTP_SSL_CERTFILE`/`LM_HTTP_SSL_KEYFILE` env vars

### v2.3.2
- **New**: `get_alerts` now supports `group_id` and `device_id` parameters for reliable Kubernetes cluster alert filtering
- **Fix**: Group filtering uses `monitorObjectGroups~` (resolves group path) instead of broken `hostGroupIds~`
- **Fix**: `correlate_alerts` and `score_alert_noise` now sanitize device filter wildcards consistently
- **Docs**: Alert filter documentation expanded with `monitorObjectId`, `monitorObjectGroups` fields

### v2.3.0
- **New**: `update_collector`, `delete_collector` — collector write operations with device-count guardrails
- **New**: `bulk_delete_devices` — batch delete up to 100 devices with K8S warnings
- **New**: `get_device_group` — single group detail with appliesTo and parentId
- **New**: `recover_device` — restore soft-deleted devices
- **New**: `get_device_eventsources`, `update_device_eventsource` — EventSource visibility and alerting control
- **Fix**: `get_devices` status filter now uses string values (was numeric, returned 0 results)
- **Fix**: Negative API total sentinel values handled with `safe_total()` helper
- **Fix**: `score_alert_noise` weights rebalanced (was pegging at 100 with normal alert volume)
- **Fix**: `calculate_availability` now filters to target device only
- **Guardrail**: `delete_device` warns on K8S-managed devices, includes audit trail
- **Guardrail**: `update_device` warns when group changes fail on Argus-managed devices
- **Counts**: 223 tools (205 LM + 18 AAP), 15 prompts, 26 resources, 6 skills

### v2.2.0
- **Breaking**: CORS default changed from `*` to empty. HTTP transport users must now set `LM_CORS_ORIGINS` explicitly.
- **Fix**: Setup script auto-detects project root instead of hardcoded path
- **Infra**: uv pinned to 0.9.27, Docker layer caching, expanded lint rules, mypy added to CI
- **Counts**: 216 tools (198 LM + 18 AAP), 15 prompts, 26 resources, 6 skills

### v2.1.1
- **Fix**: `create_sdt` and `bulk_create_device_sdt` now map `Device*` SDT types to `Resource*` for LM API v3 POST endpoints (fixes `400 "Invalid type"` errors)
- **Counts**: 216 tools (198 LM + 18 AAP), 15 prompts, 26 resources, 6 skills

### v2.1.0
- **Improved**: `create_sdt` — expanded from 2 to all 13 SDT types (DeviceDataSourceSDT, CollectorSDT, WebsiteSDT, etc.)
- **New parameter**: `datasource_id` on `create_sdt` for DeviceDataSourceSDT scheduling
- **Fix**: `create_sdt` now maps `deviceId` for all Device-prefixed SDT types, not just DeviceSDT
- **Improved**: SDT error messages include sent type and cloud resource workaround guidance
- **Counts**: 216 tools (198 LM + 18 AAP), 15 prompts, 26 resources, 6 skills

### v2.0.1
- **New**: `update_device_group` — update device group name, description, AppliesTo, properties, alerting
- **Removed**: 10 Action Sources preview tools (action chains, action rules) — not on v3 API swagger
- **Renamed**: Action Sources category to Remediation (7 tools retained)
- **Counts**: 216 tools (198 LM + 18 AAP), 15 prompts, 26 resources, 6 skills

### v2.0.0
- **New**: 5 composite workflow tools (`triage`, `health_check`, `capacity_plan`, `portal_overview`, `diagnose`) for multi-step analysis in a single call
- **New**: `search_tools` for keyword-based tool discovery across all 216 tools
- **New**: `calculate_error_budget` — SLO error budget tracking with burn rate and projected exhaustion
- **New**: 3 remediation execution tools (`execute_remediation`, `get_remediation_status`, `get_remediation_history`) with 8-point safety checklist
- **New**: Holt-Winters triple exponential smoothing in `forecast_metric` with auto-selection and confidence intervals
- **New**: IQR and MAD anomaly detection methods in `get_metric_anomalies` with auto-selection based on data skewness
- **New**: Best practices resource (`lm://guide/best-practices`) with scenario-based recommendations and anti-patterns
- **New**: Example responses resource (`lm://guide/example-responses`) for understanding tool output formats
- **New**: Metric-type presets — auto-configuration of analysis parameters based on datapoint name detection
- **New**: `remediation` MCP prompt for execution workflows with safety guidance
- **Improved**: Scoring tools (`score_alert_noise`, `score_device_health`, `calculate_availability`) return structured remediation recommendations when thresholds are breached
- **Improved**: All 15 prompts enriched with composite tool shortcuts, argument parsing guidance, and expected output format
- **Improved**: Common mistake notes added to 6 frequently misused tool descriptions
- **Fix**: `get_datasource` datapoints now include `post_processor_method` and `post_processor_param` fields
- **Counts**: 216 tools (198 LM + 18 AAP), 15 prompts, 26 resources, 6 skills

### v1.9.0
- **New**: Event-Driven Ansible integration (removed in v1.9.5 — see `contrib/eda/`)
- **New**: Device instance CRUD: add_device_instance, update_device_instance, delete_device_instance

### v1.8.0
- **New**: Ansible Automation Platform integration — 18 tools for observability-driven remediation
- **New**: `/lm-remediate` Claude Code skill — 10-step diagnosis-to-remediation workflow
- **New**: `remediate_workflow` MCP prompt for non-Claude-Code MCP clients
- **New**: Example playbooks for disk cleanup, service restart, log rotation, memory cache clearing
- **New**: Jinja2 injection protection on all AAP extra_vars inputs
- **New**: `test_awx_connection` tool for verifying AAP connectivity
- **Counts**: 201 tools (183 LM + 18 AAP), 14 prompts, 7 skills
- **Release**: [v1.8.0 on GitHub](https://github.com/ryanmat/mcp-server-logicmonitor/releases/tag/v1.8.0) | [PyPI](https://pypi.org/project/lm-mcp/1.8.0/)

### v1.7.2
- **Fix**: `update_device` custom_properties merge — prevents silent data loss when updating a subset of properties
- **Fix**: `update_device_property` create-on-404 — falls back to POST when property doesn't exist yet
- **Fix**: `get_devices` filter validation for dot-notation fields (`customProperties.name`)
- **Fix**: Import tools string definition handling — prevents double-serialization of complex embedded content
- **New**: `update_datasource`, `delete_datasource`, `hostname_filter` on `get_devices`, `overwrite` on `create_datasource`
- **Counts**: 178 -> 180 tools

### v1.7.1
- **Fix**: API client detects errors returned inside HTTP 200 response bodies (`errorMessage` + `errorCode`)
- **Fix**: `add_widget` endpoint corrected from `/dashboard/dashboards/{id}/widgets` to `/dashboard/widgets`
- **Fix**: `import_datasource` detects silent failures (empty `{}` responses)
- **New**: `create_datasource` tool for creating DataSources via REST API format (round-trip with `export_datasource`)
- **Docs**: Clarified export/import format differences (REST API vs LM Exchange)

### v1.7.0
- **New**: 5 Claude Code skills for guided multi-step workflows: `/lm-triage` (alert triage), `/lm-health` (device health), `/lm-portal` (portal overview), `/lm-capacity` (capacity planning), `/lm-apm` (APM investigation)
- **New**: Skills ship in the repo via `.claude/skills/` — available to anyone cloning the project

### v1.6.1
- **Fix**: Import tools now use `multipart/form-data` uploads (LM API requirement)
- **Fix**: Unhandled 4xx status codes no longer returned as success
- **New**: `create_dashboard` template/widget token support, `create_dashboard_group`, `delete_dashboard_group`

### v1.6.0
- **New**: 8 APM trace tools for service discovery and RED metrics via v3 API

### v1.5.1
- **Docs**: Add ML tool usage guide with examples for capacity forecasting, metric correlation, change point detection, noise scoring, health scoring, and availability calculation
- **Docs**: Add ML Analysis & Forecasting example prompts section
- **Docs**: Update project structure with new tool files

### v1.5.0
- **New**: 10 ML/statistical analysis tools using pure-Python implementations (no numpy/scipy dependencies)
- **New**: `forecast_metric` — linear regression-based threshold breach prediction
- **New**: `correlate_metrics` — Pearson correlation matrix across multiple metric series
- **New**: `detect_change_points` — CUSUM algorithm for regime shift detection
- **New**: `score_alert_noise` — Shannon entropy + flap detection for alert noise scoring
- **New**: `detect_seasonality` — autocorrelation-based periodicity detection
- **New**: `calculate_availability` — SLA-style uptime calculation from alert history
- **New**: `analyze_blast_radius` — topology-based downstream impact assessment
- **New**: `correlate_changes` — cross-references alert spikes with audit/change logs
- **New**: `classify_trend` — categorizes metrics as stable/increasing/decreasing/cyclic/volatile
- **New**: `score_device_health` — multi-metric composite health score (0-100)
- **New**: 2 analysis workflows: `capacity_forecast`, `device_health_assessment`
- **New**: Shared statistical helpers module (`stats_helpers.py`) for reusable math utilities

### v1.4.0
- **New**: 3 correlation and analysis tools: `correlate_alerts`, `get_alert_statistics`, `get_metric_anomalies` — server-side alert clustering, aggregated statistics, and Z-score anomaly detection
- **New**: 2 baseline tools: `save_baseline`, `compare_to_baseline` — snapshot metric behavior and detect drift over time
- **New**: 3 workflow prompts: `top_talkers` (noisiest devices/datasources), `rca_workflow` (guided root cause analysis), `capacity_forecast` (capacity trend prediction)
- **New**: Enhanced `alert_correlation` prompt with `device_id`/`group_id` scoping and correlation tool integration
- **New**: MCP orchestration guide resource (`lm://guide/mcp-orchestration`) documenting multi-MCP-server patterns
- **New**: Session persistence via `LM_SESSION_PERSIST_PATH` — session variables survive restarts
- **New**: HTTP analysis API: `POST /api/v1/analyze`, `GET /api/v1/analysis/{id}`, `POST /api/v1/webhooks/alert` for scheduled and webhook-triggered analysis workflows
- **New**: `LM_ANALYSIS_TTL_MINUTES` config for analysis result retention (default 60 minutes)

### v1.3.3
- **Fix**: HTTP transport now applies the full middleware chain (tool filtering, field validation, write audit logging, session recording) instead of bypassing it
- **Fix**: HTTP `tools/list` now respects `LM_ENABLED_TOOLS` and `LM_DISABLED_TOOLS` filtering
- **Change**: LMConfig cached as singleton for better performance on repeated tool calls
- **Change**: Removed unused logging infrastructure (LogLevel enum, LogEvent dataclass, event factory functions)

### v1.3.2
- **Fix**: 20 MCP tools had schema parameter names that did not match their handler function signatures, causing every call via the MCP protocol to fail with "unexpected keyword argument". Affected tools: `get_device_instances`, `get_device_data`, `get_graph_data`, `get_website_data`, `get_device_properties`, `get_dashboard_groups`, `get_oids`, `add_ops_note`, `get_audit_logs`, `get_api_token_audit`, `get_login_audit`, `get_change_audit`, `get_topology_map`, `get_network_flows`, `get_batchjob`, `get_batchjob_history`, `get_cost_summary`, `get_resource_cost`, `get_cost_recommendations`, `get_idle_resources`, `export_alert_rule`, `export_escalation_chain`
- **New**: Registry test that validates all schema property names match handler function parameter names, preventing future mismatches

### v1.3.1
- **Fix**: `get_change_audit` no longer crashes when the API returns `happenedOn` as an epoch integer

### v1.3.0
- **New**: 5 MCP prompts: `cost_optimization`, `audit_review`, `alert_correlation`, `collector_health`, `troubleshoot_device`
- **New**: 6 resource schemas: escalations, reports, websites, datasources, users, audit
- **New**: 2 guide resources: tool categories index (all 152 tools) and common query examples
- **New**: `LM_LOG_LEVEL` config for API request/response debug logging
- **New**: Write operation audit trail (INFO-level logging for create/update/delete actions)
- **Fix**: Wildcard sanitization applied to all 11 remaining string filter parameters across audit, cost, batchjobs, SDTs, and topology tools

### v1.2.1
- Patch release with minor fixes

### v1.2.0
- Tool filtering with `LM_ENABLED_TOOLS` and `LM_DISABLED_TOOLS` glob patterns
- Export/import support for all LogicModule types
- Cost optimization recommendation categories and detail endpoints

### v1.1.0
- HTTP transport for remote deployments via Starlette/Uvicorn
- Session context tracking for conversational workflows
- 6 session management tools
- Health check endpoints for container orchestration
- Field validation with typo suggestions
- Docker support with optional TLS via Caddy

### v1.0.0
- Initial release with 152 tools across 22 domains
- Bearer token and LMv1 HMAC authentication
- Read-only by default with opt-in write operations
- Rate limit handling with exponential backoff
- 15 MCP resources for API reference
- 5 MCP prompts for common workflows

## License

MIT License - see LICENSE file.
