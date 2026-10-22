# Description: MCP tool utilities for LogicMonitor server.
# Description: Provides response formatting and error handling helpers.

from __future__ import annotations

import functools
import json
import logging
from collections.abc import Callable
from typing import Any, ClassVar, TypeVar, overload

from mcp.types import TextContent

from lm_mcp.exceptions import LMError

logger = logging.getLogger(__name__)

__all__ = [
    "SEVERITY_MAP",
    "SEVERITY_NAMES",
    "ErrorContent",
    "call_sub_tool",
    "format_response",
    "handle_error",
    "is_error_result",
    "normalize_definition_fields",
    "portal_url",
    "quote_filter_value",
    "require_write_permission",
    "resolve_group_filter",
    "safe_total",
    "sanitize_filter_value",
    "validation_error",
]

# Severity name-to-integer mapping used by alert, trace, and scoring tools
SEVERITY_MAP: dict[str, int] = {
    "critical": 4,
    "error": 3,
    "warning": 2,
    "info": 1,
}

# Severity integer-to-name mapping (reverse of SEVERITY_MAP)
SEVERITY_NAMES: dict[int, str] = {v: k for k, v in SEVERITY_MAP.items()}

F = TypeVar("F", bound=Callable[..., Any])

# Mapping of common alternate field names to REST API camelCase equivalents.
# Covers LM Exchange format names, snake_case variants from get_* output,
# and common typos. Keys already in correct camelCase pass through unchanged.
_FIELD_ALIASES: dict[str, str] = {
    # LM Exchange format -> REST API
    "displayedAs": "displayName",
    "collectionMethod": "collectMethod",
    "collectionAttrs": "collectorAttribute",
    "datapoints": "dataPoints",
    # snake_case -> REST API camelCase
    "display_name": "displayName",
    "collect_method": "collectMethod",
    "collector_attribute": "collectorAttribute",
    "data_points": "dataPoints",
    "applies_to": "appliesTo",
    "collect_interval": "collectInterval",
    "has_multi_instances": "hasMultiInstances",
    "alert_expr": "alertExpr",
    "post_processor_method": "postProcessorMethod",
    "post_processor_param": "postProcessorParam",
    "auto_discovery_config": "autoDiscoveryConfig",
    "enable_auto_discovery": "enableAutoDiscovery",
}


def normalize_definition_fields(definition: dict) -> dict:
    """Normalize field names in a LogicModule definition to REST API camelCase.

    Recursively walks the definition dict, renaming keys that appear in
    _FIELD_ALIASES to their REST API equivalents. Keys already in the correct
    camelCase form pass through unchanged for backwards compatibility.

    When both an alias and its canonical key exist in the same dict, the
    canonical key value wins to prevent silent data loss.

    Args:
        definition: LogicModule definition dict (may use LM Exchange,
            snake_case, or REST API field names).

    Returns:
        New dict with all recognized keys mapped to REST API camelCase names.
    """
    result: dict = {}
    for key, value in definition.items():
        canonical = _FIELD_ALIASES.get(key, key)
        # If this key is an alias but the canonical key already exists
        # in the original dict, skip the alias (canonical wins).
        if canonical != key and canonical in definition:
            continue
        normalized = _normalize_value(value)
        result[canonical] = normalized
    return result


def _normalize_value(value: Any) -> Any:
    """Recursively normalize values within a definition structure."""
    if isinstance(value, dict):
        return normalize_definition_fields(value)
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    return value


# Wildcard note appended to response when filter values are sanitized
WILDCARD_STRIP_NOTE = (
    "Wildcard characters were removed from filter value. "
    "The ~ operator performs substring matching automatically — no wildcards needed."
)


def safe_total(result: dict) -> int:
    """Extract the total count from an LM API response, handling negative sentinels.

    The LogicMonitor API returns negative total values (e.g., -501 for limit=500)
    as a sentinel when the result set is truncated beyond the requested limit.

    Args:
        result: The raw API response dict.

    Returns:
        The absolute value of the total field, defaulting to 0.
    """
    return abs(result.get("total", 0))


# Note added to a list response when the API total is a negative lower bound
INEXACT_TOTAL_NOTE = (
    "The API did not report an exact count; total is a lower bound and more "
    "results exist past this page."
)


def paginated_response(items: list[Any], result: dict, offset: int) -> dict[str, Any]:
    """Build the pagination fields of a list tool response.

    The API reports a negative total, -(offset + size + 1), when more results
    exist than it counted. That reads as has_more with total as the lower
    bound and a total_note, never as the end of the list.

    Args:
        items: The items returned on this page.
        result: The raw API response dict.
        offset: The offset the page was requested at.

    Returns:
        Dict with total, count, offset and has_more, plus total_note when
        the API total was negative.
    """
    total = safe_total(result)
    inexact = result.get("total", 0) < 0
    response: dict[str, Any] = {
        "total": total,
        "count": len(items),
        "offset": offset,
        "has_more": inexact or offset + len(items) < total,
    }
    if inexact:
        response["total_note"] = INEXACT_TOTAL_NOTE
    return response


def quote_filter_value(value: str) -> str:
    """Wrap a string value in double quotes for LM API v3 filter compatibility.

    The LogicMonitor REST API v3 requires string filter values to be enclosed
    in double quotes. Numeric and boolean values work without quotes, but
    string values silently return zero results when unquoted.

    Backslashes and double quotes inside the value are escaped, backslash
    first, so the value cannot close its quotes and append filter clauses
    (an unescaped ``a"|"b`` would send two clauses joined by OR).

    Args:
        value: The string value to quote.

    Returns:
        The escaped value wrapped in double quotes.
    """
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


@overload
def sanitize_filter_value(value: str) -> tuple[str, bool]: ...


@overload
def sanitize_filter_value(value: None) -> tuple[None, bool]: ...


@overload
def sanitize_filter_value(value: str | None) -> tuple[str | None, bool]: ...


def sanitize_filter_value(value: str | None) -> tuple[str | None, bool]:
    """Strip wildcard characters (* and ?) from a filter value.

    The LogicMonitor ~ operator already performs substring matching,
    so wildcards are unnecessary and cause issues when URL-encoded.

    The overloads keep a str input typed as a str output, so a call site that
    has already narrowed its argument can pass the cleaned value straight to
    quote_filter_value.

    Args:
        value: The filter value to sanitize. May be None.

    Returns:
        Tuple of (cleaned_value, was_modified). was_modified is True
        if any wildcard characters were removed.
    """
    if value is None:
        return None, False

    cleaned = value.replace("*", "").replace("?", "")
    was_modified = cleaned != value
    return cleaned, was_modified


def portal_url(resource_type: str, resource_id: int | str) -> str:
    """Build a clickable LM portal URL for a single resource.

    Args:
        resource_type: Resource type key (device, alert, dashboard,
            alert_rule, device_group, website).
        resource_id: Numeric resource ID.

    Returns:
        Full HTTPS URL to the resource in the LM portal UI,
        or empty string if the resource type is unknown or config
        is unavailable.
    """
    try:
        from lm_mcp.config import get_config

        config = get_config()
    except Exception:
        return ""

    path_map: dict[str, str] = {
        "device": f"devices/{resource_id}",
        "alert": f"alerts/{resource_id}",
        "dashboard": f"dashboard/{resource_id}",
        "alert_rule": f"setting/alert/rules/{resource_id}",
        "device_group": f"device/groups/{resource_id}",
        "website": f"setting/websites/{resource_id}",
    }

    path = path_map.get(resource_type)
    if path is None:
        return ""

    if config.multi_portal:
        from lm_mcp import portals

        host = portals.active().get("portal")
    else:
        host = config.portal
    if not host:
        return ""

    return f"https://{host}/santaba/uiv4/{path}"


async def resolve_group_filter(client: Any, group_id: int) -> str:
    """Resolve a device group ID to a monitorObjectGroups filter clause.

    The LM API hostGroupIds~ filter does not reliably restrict alerts to a
    specific group. The monitorObjectGroups~ filter (which uses the group
    fullPath) works correctly.  This helper fetches the group fullPath from
    the API and returns the ready-to-use filter clause.

    Args:
        client: LogicMonitor API client.
        group_id: Device group ID to resolve.

    Returns:
        Filter clause string, e.g. monitorObjectGroups~"My Group/Sub".

    Raises:
        LMError: If the group cannot be found.
    """
    result = await client.get(f"/device/groups/{group_id}")
    full_path = result.get("fullPath", "")
    return f"monitorObjectGroups~{quote_filter_value(full_path)}"


class ErrorContent(TextContent):
    """TextContent that carries a tool error.

    The text keeps the ``Error: ...`` form callers read; the type is what lets the
    dispatcher recognize a failure without parsing the text.
    """

    is_error: ClassVar[bool] = True


def is_error_result(result: list) -> bool:
    """Return True when a tool result carries an ErrorContent item.

    Args:
        result: The content list a tool handler or execute_tool returned.

    Returns:
        True if any item is an ErrorContent, False otherwise (including empty).
    """
    return any(isinstance(item, ErrorContent) for item in result)


def format_response(data: Any) -> list[TextContent]:
    """Format data as MCP TextContent response.

    Args:
        data: The data to format. Can be dict, list, string, or other types.

    Returns:
        List containing a single TextContent with the formatted data; an
        ErrorContent when the data is an error dict.
    """
    if isinstance(data, dict) and data.get("error"):
        # Error response - format for readability
        text = f"Error: {data['message']}"
        if data.get("suggestion"):
            text += f"\nSuggestion: {data['suggestion']}"
        return [ErrorContent(type="text", text=text)]

    # Success response
    text = json.dumps(data, indent=2, default=str) if isinstance(data, (dict, list)) else str(data)

    return [TextContent(type="text", text=text)]


def handle_error(error: Exception) -> list[TextContent]:
    """Convert exception to MCP response.

    Args:
        error: The exception to handle.

    Returns:
        List containing a single ErrorContent with the error details.
    """
    if isinstance(error, LMError):
        # An API refusal is a WARNING with the server's own words attached, so a
        # 4xx or 5xx leaves a trace on stderr and not only in the tool result.
        logger.warning(
            "%s: %s%s",
            error.code,
            error.message,
            f" (details: {error.details})" if error.details else "",
        )
        return format_response(error.to_dict())

    # Log unexpected exceptions with stack trace before returning sanitized response.
    # Without this, JSONDecodeError, KeyError, ValueError, etc. are silently swallowed.
    logger.exception("unhandled error in tool handler")
    return format_response(
        {
            "error": True,
            "code": "UNEXPECTED_ERROR",
            "message": str(error),
        }
    )


async def call_sub_tool(handler: Callable[..., Any], client: Any, **kwargs: Any) -> Any:
    """Call a sub-handler, parse JSON response, raise RuntimeError on error.

    Handles both structured JSON responses and the human-readable error
    format ``format_response`` produces for error dicts
    ("Error: <message>\\nSuggestion: <suggestion>"). Converts either shape
    into a clean RuntimeError for the composite caller instead of a
    cryptic JSONDecodeError ("Expecting value: line 1 column 1 (char 0)").

    Args:
        handler: Async tool function. Must accept ``client`` as first arg.
        client: LogicMonitor API client passed through to the handler.
        **kwargs: Forwarded to the handler.

    Returns:
        Parsed JSON payload from the sub-tool. For list/dict payloads the
        parsed structure is returned directly.

    Raises:
        RuntimeError: When the sub-tool returns an error envelope, a
            human-readable "Error: ..." line, or non-JSON text.
    """
    result = await handler(client, **kwargs)
    text = result[0].text

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        if text.startswith("Error:"):
            first_line = text.split("\n", 1)[0]
            message = first_line[len("Error:") :].strip() or "Sub-tool returned an error"
            raise RuntimeError(message) from None
        snippet = text[:200]
        raise RuntimeError(f"Sub-tool returned non-JSON response: {snippet}") from None

    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(data.get("message", "Sub-tool returned an error"))
    return data


def validation_error(
    code: str,
    message: str,
    suggestion: str | None = None,
) -> list[TextContent]:
    """Return a canonical input-validation error response.

    Use for argument validation that fails before any API call. Produces
    the same envelope shape as :func:`handle_error` so callers see a
    consistent structure regardless of where the error originated.

    Args:
        code: UPPER_SNAKE_CASE machine-readable code, e.g. ``VALIDATION_ERROR``.
        message: Human-readable description of the failure.
        suggestion: Optional remediation hint shown to the caller.

    Returns:
        List with a single TextContent carrying the formatted error envelope.
    """
    payload: dict[str, Any] = {
        "error": True,
        "code": code,
        "message": message,
    }
    if suggestion:
        payload["suggestion"] = suggestion
    return format_response(payload)


def strip_readonly(payload: dict, fields: tuple[str, ...]) -> dict:
    """Return a copy of ``payload`` without the given server-managed read-only fields.

    LogicMonitor rejects or ignores read-only fields echoed back on a write; stripping
    them before a PUT avoids intermittent 400s. The field list is caller-supplied so it
    stays specific to each resource.
    """
    return {k: v for k, v in payload.items() if k not in fields}


def require_write_permission(func: F) -> F:
    """Decorator to enforce write permission check.

    When LM_ENABLE_WRITE_OPERATIONS is false (default), decorated functions
    will return an error response instead of executing.

    Args:
        func: The async function to wrap.

    Returns:
        Wrapped function that checks write permission before executing.
    """

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        from lm_mcp.config import get_config

        config = get_config()
        if not config.enable_write_operations:
            return format_response(
                {
                    "error": True,
                    "code": "WRITE_DISABLED",
                    "message": "Write operations are disabled",
                    "suggestion": "Set LM_ENABLE_WRITE_OPERATIONS=true to enable write operations",
                }
            )
        if config.multi_portal:
            from lm_mcp import portals

            if not portals.has_active():
                return format_response(
                    {
                        "error": True,
                        "code": "NO_PORTAL_SELECTED",
                        "message": "No portal selected",
                        "suggestion": "Call use_portal(<customer>) first (see list_portals)",
                    }
                )
            if not portals.is_active_writable():
                return format_response(
                    {
                        "error": True,
                        "code": "PORTAL_READ_ONLY",
                        "message": "The active portal is read-only",
                        "suggestion": (
                            'Set "writable": true on this portal\'s vault record to allow writes'
                        ),
                    }
                )
        return await func(*args, **kwargs)

    return wrapper  # type: ignore[return-value]
