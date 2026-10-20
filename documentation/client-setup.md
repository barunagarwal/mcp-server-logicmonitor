# LogicMonitor MCP Server: Client Setup

Per-client configuration for connecting the LogicMonitor MCP server. Every client runs the
same server (`uvx --from lm-mcp lm-mcp-server`); only the config format and file location
differ. For the fastest path (Claude Code) see the [README Quick Start](../README.md#quick-start).

Back to the [README](../README.md).

### Claude Code

```bash
claude mcp add logicmonitor \
  -e LM_PORTAL=yourcompany.logicmonitor.com \
  -e LM_BEARER_TOKEN=<your-bearer-token> \
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

**Cursor's 40-tool cap (recommended for v3.6.0+):** Cursor only loads the first 40 MCP tools — the remaining ~240 are invisible to the agent. Use `LM_MCP_CATEGORIES` to fit a curated subset under the cap. The `workflow` category alone (`triage`, `diagnose`, `health_check`, `portal_overview`, `capacity_plan`, scoring/correlation tools, plus `update_logicmodule`) is roughly 23 tools and covers the 80% case:

```json
{
  "mcpServers": {
    "logicmonitor": {
      "command": "uvx",
      "args": ["--from", "lm-mcp", "lm-mcp-server"],
      "env": {
        "LM_PORTAL": "yourcompany.logicmonitor.com",
        "LM_BEARER_TOKEN": "your-bearer-token",
        "LM_MCP_CATEGORIES": "workflow"
      }
    }
  }
}
```

For surgical control, combine with `LM_ENABLED_TOOLS`:

```json
"env": {
  "LM_PORTAL": "yourcompany.logicmonitor.com",
  "LM_BEARER_TOKEN": "your-bearer-token",
  "LM_ENABLED_TOOLS": "triage,diagnose,health_check,portal_overview,get_alerts,get_devices,get_alert_details,acknowledge_alert,search_tools",
  "LM_MCP_CATEGORIES": "read,workflow"
}
```

The two filters compose by intersection: `LM_MCP_CATEGORIES` only narrows further, never expands. Default behavior (env var unset) returns all 280 tools — backwards compatible.

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
  --env LM_BEARER_TOKEN=<your-bearer-token> \
  -- uvx --from lm-mcp lm-mcp-server
```

Or add directly to `~/.codex/config.toml`:

```toml
[mcp_servers.logicmonitor]
command = "uvx"
args = ["--from", "lm-mcp", "lm-mcp-server"]

[mcp_servers.logicmonitor.env]
LM_PORTAL = "yourcompany.logicmonitor.com"
LM_BEARER_TOKEN = "<your-bearer-token>"
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
