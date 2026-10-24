# Description: MCP server entry point for LogicMonitor platform.
# Description: Provides shared tool execution middleware and stdio transport.

import asyncio
import json
import logging
from fnmatch import fnmatch

from mcp.server import Server
from mcp.types import CallToolResult, CompleteResult, GetPromptResult, TextContent, Tool

from lm_mcp.client import LogicMonitorClient
from lm_mcp.completions import get_completions
from lm_mcp.config import get_config
from lm_mcp.logging import configure_logging, is_write_tool, log_write_operation
from lm_mcp.prompts import PROMPTS, get_prompt_messages
from lm_mcp.registry import AWX_TOOLS, TF_TOOLS, TOOLS, WATSONX_TOOLS, get_tool_handler
from lm_mcp.resources import RESOURCES, get_resource_content
from lm_mcp.session import get_session
from lm_mcp.tools import ErrorContent, is_error_result
from lm_mcp.validation import infer_resource_type, validate_fields, validate_filter_fields

logger = logging.getLogger(__name__)

# Create server instance
SERVER_INSTRUCTIONS = (
    "This server exposes 306 LogicMonitor tools, more than most clients load at once. "
    "To find the right tool for a task, call `search_tools` with relevant keywords (or a "
    "`category`) first instead of enumerating the full list. Composite workflow tools -- "
    "`triage`, `diagnose`, `health_check`, `portal_overview`, `capacity_plan`, "
    "`detect_site_outage` -- answer common multi-step investigations in a single call. "
    "Write operations (create/update/delete/run) are gated behind "
    "`LM_ENABLE_WRITE_OPERATIONS` and are absent unless the operator enabled them."
)
server = Server("logicmonitor-platform", instructions=SERVER_INSTRUCTIONS)

# Global client (initialized on startup)
_client: LogicMonitorClient | None = None


def get_client() -> LogicMonitorClient:
    """Get the initialized LogicMonitor client.

    Returns:
        The LogicMonitor API client instance.

    Raises:
        RuntimeError: If called before server initialization.
    """
    if _client is None:
        # Only surface the multi-portal hint when we can confirm multi-portal mode.
        # If the config can't be built yet (e.g. no env in a unit test), fall back to
        # the plain "not initialized" message rather than leaking a config error.
        multi = False
        try:
            from lm_mcp.config import get_config

            multi = get_config().multi_portal
        except Exception:
            multi = False
        if multi:
            raise RuntimeError(
                "No portal selected. Call use_portal(<customer>) first (see list_portals)."
            )
        raise RuntimeError("Client not initialized")
    return _client


def _set_client(client: LogicMonitorClient) -> None:
    """Set the global LogicMonitor client.

    Called by transport runners during initialization.

    Args:
        client: The LogicMonitor API client instance.
    """
    global _client
    _client = client


# Global AWX client (initialized when AWX_URL and AWX_TOKEN are set)
_awx_client = None

# Set of AWX tool names for dispatch routing
AWX_TOOL_NAMES = {t.name for t in AWX_TOOLS}


def get_awx_client():
    """Get the initialized AWX client.

    Returns:
        The AWX client instance, or None if not configured.
    """
    return _awx_client


def _set_awx_client(client) -> None:
    """Set the global AWX client.

    Called by transport runners during initialization when AWX
    credentials are available.

    Args:
        client: The AwxClient instance, or None to clear.
    """
    global _awx_client
    _awx_client = client


# Global watsonx client (initialized when WATSONX_API_KEY is set)
_watsonx_client = None

# Set of watsonx tool names for dispatch routing
WATSONX_TOOL_NAMES = {t.name for t in WATSONX_TOOLS}


def get_watsonx_client():
    """Get the initialized watsonx client.

    Returns:
        The WatsonxClient instance, or None if not configured.
    """
    return _watsonx_client


def _set_watsonx_client(client) -> None:
    """Set the global watsonx client.

    Called by transport runners during initialization when watsonx
    credentials are available.

    Args:
        client: The WatsonxClient instance, or None to clear.
    """
    global _watsonx_client
    _watsonx_client = client


# Global Terraform runner (initialized when TF_WORKSPACE_DIR is set)
_tf_runner = None

# Set of Terraform tool names for dispatch routing
TF_TOOL_NAMES = {t.name for t in TF_TOOLS}


def get_tf_runner():
    """Get the initialized Terraform runner.

    Returns:
        The TerraformRunner instance, or None if not configured.
    """
    return _tf_runner


def _set_tf_runner(runner) -> None:
    """Set the global Terraform runner.

    Called by transport runners during initialization when Terraform
    workspace directory is configured.

    Args:
        runner: The TerraformRunner instance, or None to clear.
    """
    global _tf_runner
    _tf_runner = runner


def _filter_tools(tools: list, config) -> list:
    """Filter tools based on LM_ENABLED_TOOLS, LM_DISABLED_TOOLS, and LM_MCP_CATEGORIES.

    Supports comma-separated tool names and glob patterns (e.g., "get_*", "delete_*").
    LM_MCP_CATEGORIES composes by intersection — it narrows the result of the
    enabled/disabled pass but never expands it.

    Args:
        tools: Full list of Tool objects.
        config: LMConfig instance with enabled_tools/disabled_tools/mcp_categories.

    Returns:
        Filtered list of Tool objects.
    """
    if not config.multi_portal:
        tools = [t for t in tools if t.name not in PORTAL_TOOLS]

    if config.enabled_tools:
        patterns = [p.strip() for p in config.enabled_tools.split(",") if p.strip()]
        tools = [t for t in tools if any(fnmatch(t.name, pat) for pat in patterns)]
    elif config.disabled_tools:
        patterns = [p.strip() for p in config.disabled_tools.split(",") if p.strip()]
        tools = [t for t in tools if not any(fnmatch(t.name, pat) for pat in patterns)]

    if config.mcp_categories:
        from lm_mcp.categories import filter_by_categories

        # In multi-portal mode the portal tools are the control plane: filtering
        # them out would leave every data tool stuck at "No portal selected".
        exempt = [t for t in tools if config.multi_portal and t.name in PORTAL_TOOLS]
        candidates = [t for t in tools if t not in exempt]
        tools, unknown = filter_by_categories(candidates, config.mcp_categories)
        tools.extend(exempt)
        if unknown:
            logger.warning(
                "LM_MCP_CATEGORIES contains unknown tokens %s — ignored. "
                "Known categories: read, write, delete, export, import, session, workflow",
                unknown,
            )

    return tools


@server.list_tools()
async def list_tools():
    """Return available tools, filtered by config.

    Includes AWX tools only when the AWX client is configured.
    """
    return _filter_tools(collect_tools(), get_config())


def collect_tools() -> list[Tool]:
    """The tools this server can dispatch with its configured backends, before operator filters.

    The AWX, watsonx and Terraform tools are included only when their backend is set.
    Both transports build their tool lists from this.
    """
    tools = list(TOOLS)
    if _awx_client is not None:
        tools.extend(AWX_TOOLS)
    if _watsonx_client is not None:
        tools.extend(WATSONX_TOOLS)
    if _tf_runner is not None:
        tools.extend(TF_TOOLS)
    return tools


# Session tools that don't require the LM client
SESSION_TOOLS = {
    "get_session_context",
    "set_session_variable",
    "get_session_variable",
    "delete_session_variable",
    "clear_session_context",
    "list_session_history",
}

PORTAL_TOOLS = {
    "list_portals",
    "use_portal",
    "current_portal",
    "reload_portals",
}

# Discovery tools that take the client argument by convention but never use it,
# so they must work before a portal is selected in multi-portal mode.
CLIENT_OPTIONAL_TOOLS = {
    "search_tools",
    "get_reference",
    "get_workflow",
}


async def execute_tool(name: str, arguments: dict) -> list[TextContent]:
    """Execute a LogicMonitor tool with full middleware chain.

    Applies tool filtering, field validation, write audit logging, and
    session recording. Used by both the MCP stdio handler and the HTTP
    transport endpoint to ensure consistent behavior across transports.

    Args:
        name: Tool name to execute.
        arguments: Tool arguments.

    Returns:
        List of TextContent with the tool result.
    """
    config = get_config()

    try:
        handler = get_tool_handler(name)

        # Portal tools exist only in multi-portal mode
        if name in PORTAL_TOOLS and not config.multi_portal:
            return [
                ErrorContent(
                    type="text",
                    text=f"Error: Tool '{name}' is only available in multi-portal mode "
                    "(set LM_MULTI_PORTAL=true).",
                )
            ]

        # Reject calls to filtered-out tools
        if config.enabled_tools:
            patterns = [p.strip() for p in config.enabled_tools.split(",") if p.strip()]
            if not any(fnmatch(name, pat) for pat in patterns):
                return [
                    ErrorContent(
                        type="text",
                        text=f"Error: Tool '{name}' is not enabled. "
                        f"Enabled tools: {config.enabled_tools}",
                    )
                ]
        elif config.disabled_tools:
            patterns = [p.strip() for p in config.disabled_tools.split(",") if p.strip()]
            if any(fnmatch(name, pat) for pat in patterns):
                return [
                    ErrorContent(
                        type="text",
                        text=f"Error: Tool '{name}' is disabled. "
                        f"Disabled tools: {config.disabled_tools}",
                    )
                ]

        if config.mcp_categories and not (name in PORTAL_TOOLS and config.multi_portal):
            from lm_mcp.categories import tool_in_categories

            tools_index = {t.name: t for t in TOOLS}
            tools_index.update({t.name: t for t in AWX_TOOLS})
            tools_index.update({t.name: t for t in WATSONX_TOOLS})
            tools_index.update({t.name: t for t in TF_TOOLS})
            if not tool_in_categories(name, tools_index, config.mcp_categories):
                return [
                    ErrorContent(
                        type="text",
                        text=f"Error: Tool '{name}' is excluded by LM_MCP_CATEGORIES "
                        f"(active categories: {config.mcp_categories}).",
                    )
                ]

        # Field validation (if enabled and not a session tool)
        if (
            config.field_validation != "off"
            and name not in SESSION_TOOLS
            and name not in PORTAL_TOOLS
        ):
            resource_type = infer_resource_type(name)
            if resource_type:
                # Validate 'fields' argument if present
                if arguments.get("fields"):
                    validation = validate_fields(resource_type, arguments["fields"])
                    if not validation.valid:
                        msg = f"Invalid fields: {validation.invalid_fields}"
                        if validation.suggestions:
                            suggestions = ", ".join(
                                f"{k} -> {v}" for k, v in validation.suggestions.items()
                            )
                            msg += f". Did you mean: {suggestions}?"

                        if config.field_validation == "error":
                            return [
                                ErrorContent(
                                    type="text",
                                    text=json.dumps(
                                        {
                                            "error": True,
                                            "code": "INVALID_FIELDS",
                                            "message": msg,
                                            "invalid_fields": validation.invalid_fields,
                                            "suggestions": validation.suggestions,
                                            "valid_fields": validation.valid_field_names[:20],
                                        },
                                        indent=2,
                                    ),
                                )
                            ]
                        else:
                            logger.warning(f"Field validation warning for {name}: {msg}")

                # Validate 'filter' argument if present
                if arguments.get("filter"):
                    validation = validate_filter_fields(resource_type, arguments["filter"])
                    if not validation.valid:
                        msg = f"Invalid filter fields: {validation.invalid_fields}"
                        if validation.suggestions:
                            suggestions = ", ".join(
                                f"{k} -> {v}" for k, v in validation.suggestions.items()
                            )
                            msg += f". Did you mean: {suggestions}?"

                        if config.field_validation == "error":
                            return [
                                ErrorContent(
                                    type="text",
                                    text=json.dumps(
                                        {
                                            "error": True,
                                            "code": "INVALID_FILTER_FIELDS",
                                            "message": msg,
                                            "invalid_fields": validation.invalid_fields,
                                            "suggestions": validation.suggestions,
                                        },
                                        indent=2,
                                    ),
                                )
                            ]
                        else:
                            logger.warning(f"Filter validation warning for {name}: {msg}")

        # Session and portal tools don't need an LM client
        if name in SESSION_TOOLS or name in PORTAL_TOOLS:
            result = await handler(**arguments)
        elif name in AWX_TOOL_NAMES:
            # AWX tools use the AWX client
            if _awx_client is None:
                return [
                    ErrorContent(
                        type="text",
                        text="Error: Ansible Automation Platform not configured. "
                        "Set AWX_URL and AWX_TOKEN environment variables.",
                    )
                ]
            result = await handler(_awx_client, **arguments)
        elif name in WATSONX_TOOL_NAMES:
            # WatsonX tools use the watsonx client
            if _watsonx_client is None:
                return [
                    ErrorContent(
                        type="text",
                        text="Error: IBM watsonx not configured. "
                        "Set WATSONX_API_KEY, WATSONX_URL, and "
                        "WATSONX_PROJECT_ID environment variables.",
                    )
                ]
            result = await handler(_watsonx_client, **arguments)
        elif name in TF_TOOL_NAMES:
            # The LM Terraform provider needs fixed LM_* credentials; multi-portal
            # credentials are selected at runtime and never reach the subprocess.
            if config.multi_portal:
                return [
                    ErrorContent(
                        type="text",
                        text="Error: Terraform tools are not supported in multi-portal mode "
                        "(the Terraform provider needs fixed LM_* credentials). "
                        "Run a single-portal server for Terraform.",
                    )
                ]
            # Terraform tools use the Terraform runner
            if _tf_runner is None:
                return [
                    ErrorContent(
                        type="text",
                        text="Error: Terraform not configured. "
                        "Set TF_WORKSPACE_DIR environment variable.",
                    )
                ]
            result = await handler(_tf_runner, **arguments)
        elif name in CLIENT_OPTIONAL_TOOLS:
            # These handlers ignore the client; pass the global as-is (possibly
            # None before use_portal) so discovery works portal-free.
            result = await handler(_client, **arguments)
        else:
            client = get_client()
            result = await handler(client, **arguments)

        # Handlers return errors rather than raise, so the outcome comes from the result
        failed = is_error_result(result)

        # Audit trail for write operations
        if is_write_tool(name):
            log_write_operation(name, arguments, success=not failed)

        # Record result in session if enabled. Portal tools are recorded too:
        # a portal switch is the marker that scopes every entry around it.
        if config.session_enabled and name not in SESSION_TOOLS:
            session = get_session()
            # Try to parse the result for session storage
            if result and len(result) > 0:
                try:
                    text = result[0].text
                    data = json.loads(text)
                    session.record_result(name, arguments, data, success=not failed)
                except (json.JSONDecodeError, AttributeError):
                    # Non-JSON result, just record with minimal info
                    session.record_result(name, arguments, {}, success=not failed)

        return result
    except ValueError as e:
        logger.exception("Tool %s rejected its arguments", name)
        if is_write_tool(name):
            log_write_operation(name, arguments, success=False)
        return [ErrorContent(type="text", text=f"Error: {e}")]
    except Exception as e:
        logger.exception("Tool %s raised", name)
        if is_write_tool(name):
            log_write_operation(name, arguments, success=False)
        return [ErrorContent(type="text", text=f"Error executing {name}: {e}")]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent] | CallToolResult:
    """MCP call_tool handler that delegates to execute_tool.

    Args:
        name: Tool name to execute.
        arguments: Tool arguments.

    Returns:
        List of TextContent with the tool result, or a CallToolResult with
        isError=True when the result is an error, which the SDK passes through.
    """
    result = await execute_tool(name, arguments)
    if is_error_result(result):
        return CallToolResult(content=list(result), isError=True)
    return result


@server.list_resources()
async def list_resources():
    """Return all available LogicMonitor schema resources.

    Resources expose API field definitions, valid enum values, and filter
    syntax to help AI agents construct valid API queries.
    """
    return RESOURCES


@server.read_resource()
async def read_resource(uri) -> str:
    """Read the content of a LogicMonitor schema resource.

    Args:
        uri: Resource URI (e.g., 'lm://schema/alerts'). May be AnyUrl or str.

    Returns:
        JSON string containing the resource content.
    """
    try:
        # Convert AnyUrl to string if needed
        uri_str = str(uri)
        content = get_resource_content(uri_str)
        return content
    except ValueError as e:
        raise ValueError(f"Resource not found: {uri}") from e


@server.completion()
async def complete(ref, argument) -> CompleteResult:
    """Provide auto-complete suggestions for argument values.

    Supports completions for common LogicMonitor argument names like
    severity, status, and sdt_type.

    Args:
        ref: Reference to the prompt or resource template.
        argument: The argument being completed (name and partial value).

    Returns:
        CompleteResult with matching completion values.
    """
    completion = get_completions(argument.name, argument.value)
    return CompleteResult(completion=completion)


@server.list_prompts()
async def list_prompts():
    """Return all available LogicMonitor workflow prompts.

    Prompts provide pre-built templates for common monitoring operations
    like incident triage, capacity review, and health checks.
    """
    return PROMPTS


@server.get_prompt()
async def get_prompt(name: str, arguments: dict | None = None) -> GetPromptResult:
    """Get the messages for a LogicMonitor workflow prompt.

    Args:
        name: Prompt name (e.g., 'incident_triage', 'health_check').
        arguments: Optional prompt arguments.

    Returns:
        GetPromptResult with workflow messages.
    """
    return get_prompt_messages(name, arguments or {})


async def run_server() -> None:
    """Run the MCP server with configured transport.

    The transport is selected based on the LM_TRANSPORT environment variable:
    - "stdio" (default): Standard input/output for local AI assistants
    - "http": HTTP transport for remote/shared deployments
    """
    from lm_mcp.transport import get_transport_runner

    config = get_config()
    configure_logging(config)
    runner = get_transport_runner(config)
    await runner()


def main() -> None:
    """Entry point for the MCP server."""
    asyncio.run(run_server())


if __name__ == "__main__":
    main()
