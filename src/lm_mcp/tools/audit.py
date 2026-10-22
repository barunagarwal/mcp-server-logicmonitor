# Description: Audit log tools for LogicMonitor MCP server.
# Description: Provides access to system audit logs and activity tracking.

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp.types import TextContent

from lm_mcp.tools import (
    WILDCARD_STRIP_NOTE,
    format_response,
    handle_error,
    paginated_response,
    quote_filter_value,
    sanitize_filter_value,
)

if TYPE_CHECKING:
    from lm_mcp.client import LogicMonitorClient


async def get_audit_logs(
    client: LogicMonitorClient,
    username: str | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    start_time: int | None = None,
    end_time: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[TextContent]:
    """Get audit logs from LogicMonitor.

    Args:
        client: LogicMonitor API client.
        username: Filter by username who performed the action.
        action: Filter by action type (create, update, delete, login, etc.).
        resource_type: Filter by resource type (device, dashboard, alert, etc.).
        start_time: Start time filter (epoch seconds).
        end_time: End time filter (epoch seconds).
        limit: Maximum number of logs to return.
        offset: Number of results to skip for pagination.

    Returns:
        List of TextContent with audit log data or error.
    """
    try:
        params: dict = {"size": limit, "offset": offset}
        wildcards_stripped = False

        filters = []
        if username:
            clean_username, was_modified = sanitize_filter_value(username)
            wildcards_stripped = wildcards_stripped or was_modified
            filters.append(f"username:{quote_filter_value(clean_username)}")
        if action:
            clean_action, was_modified = sanitize_filter_value(action)
            wildcards_stripped = wildcards_stripped or was_modified
            filters.append(f"happenedOn:{quote_filter_value(clean_action)}")
        if resource_type:
            clean_type, was_modified = sanitize_filter_value(resource_type)
            wildcards_stripped = wildcards_stripped or was_modified
            filters.append(f"description~{quote_filter_value(clean_type)}")
        if start_time:
            filters.append(f"happenedOnLocal>:{start_time}")
        if end_time:
            filters.append(f"happenedOnLocal<:{end_time}")

        if filters:
            params["filter"] = ",".join(filters)

        result = await client.get("/setting/accesslogs", params=params)

        logs = []
        for item in result.get("items", []):
            logs.append(
                {
                    "id": item.get("id"),
                    "username": item.get("username"),
                    "ip_address": item.get("ip"),
                    "action": item.get("happenedOn"),
                    "description": item.get("description"),
                    "timestamp": item.get("happenedOnLocal"),
                    "session_id": item.get("sessionId"),
                }
            )

        response = {
            **paginated_response(logs, result, offset),
            "audit_logs": logs,
        }
        if wildcards_stripped:
            response["note"] = WILDCARD_STRIP_NOTE
        return format_response(response)
    except Exception as e:
        return handle_error(e)


async def get_api_token_audit(
    client: LogicMonitorClient,
    token_id: int | None = None,
    limit: int = 50,
) -> list[TextContent]:
    """Get API token usage audit logs.

    Args:
        client: LogicMonitor API client.
        token_id: Filter by specific API token ID.
        limit: Maximum number of logs to return.

    Returns:
        List of TextContent with API token audit data or error.
    """
    try:
        params: dict = {"size": limit}

        if token_id:
            params["filter"] = f"apiTokenId:{token_id}"

        result = await client.get("/setting/accesslogs", params=params)

        # Filter to API token related entries
        logs = []
        for item in result.get("items", []):
            desc = item.get("description", "").lower()
            if "api" in desc or "token" in desc or item.get("username", "").startswith("api."):
                logs.append(
                    {
                        "id": item.get("id"),
                        "username": item.get("username"),
                        "ip_address": item.get("ip"),
                        "action": item.get("happenedOn"),
                        "description": item.get("description"),
                        "timestamp": item.get("happenedOnLocal"),
                    }
                )

        return format_response(
            {
                "total": len(logs),
                "count": len(logs),
                "api_token_logs": logs,
            }
        )
    except Exception as e:
        return handle_error(e)


async def get_login_audit(
    client: LogicMonitorClient,
    username: str | None = None,
    success_only: bool = False,
    failed_only: bool = False,
    limit: int = 50,
) -> list[TextContent]:
    """Get login/authentication audit logs.

    Args:
        client: LogicMonitor API client.
        username: Filter by specific username.
        success_only: Only show successful logins.
        failed_only: Only show failed login attempts.
        limit: Maximum number of logs to return.

    Returns:
        List of TextContent with login audit data or error.
    """
    try:
        params: dict = {"size": limit}

        wildcards_stripped = False

        filters = [f"happenedOn:{quote_filter_value('login')}"]
        if username:
            clean_username, was_modified = sanitize_filter_value(username)
            wildcards_stripped = wildcards_stripped or was_modified
            filters.append(f"username:{quote_filter_value(clean_username)}")

        params["filter"] = ",".join(filters)

        result = await client.get("/setting/accesslogs", params=params)

        logs = []
        for item in result.get("items", []):
            desc = item.get("description", "").lower()
            is_success = "success" in desc or "logged in" in desc
            is_failed = "fail" in desc or "invalid" in desc

            if success_only and not is_success:
                continue
            if failed_only and not is_failed:
                continue

            logs.append(
                {
                    "id": item.get("id"),
                    "username": item.get("username"),
                    "ip_address": item.get("ip"),
                    "status": "success" if is_success else "failed" if is_failed else "unknown",
                    "description": item.get("description"),
                    "timestamp": item.get("happenedOnLocal"),
                }
            )

        response = {
            "total": len(logs),
            "count": len(logs),
            "login_logs": logs,
        }
        if wildcards_stripped:
            response["note"] = WILDCARD_STRIP_NOTE
        return format_response(response)
    except Exception as e:
        return handle_error(e)


async def get_change_audit(
    client: LogicMonitorClient,
    resource_type: str | None = None,
    change_type: str | None = None,
    limit: int = 50,
) -> list[TextContent]:
    """Get configuration change audit logs.

    Args:
        client: LogicMonitor API client.
        resource_type: Filter by resource type (device, dashboard, user, etc.).
        change_type: Filter by change type (create, update, delete).
        limit: Maximum number of logs to return.

    Returns:
        List of TextContent with change audit data or error.
    """
    try:
        params: dict = {"size": limit}
        wildcards_stripped = False

        filters = []
        if change_type:
            clean_type, was_modified = sanitize_filter_value(change_type)
            wildcards_stripped = wildcards_stripped or was_modified
            filters.append(f"happenedOn:{quote_filter_value(clean_type)}")
        if resource_type:
            clean_type, was_modified = sanitize_filter_value(resource_type)
            wildcards_stripped = wildcards_stripped or was_modified
            filters.append(f"description~{quote_filter_value(clean_type)}")

        if filters:
            params["filter"] = ",".join(filters)

        result = await client.get("/setting/accesslogs", params=params)

        # Change action keywords to match in the description field
        change_keywords = ["create", "add", "update", "delete", "remove", "modify"]

        logs = []
        for item in result.get("items", []):
            desc = str(item.get("description", "")).lower()
            # Filter to actual changes by checking description for action keywords
            if any(kw in desc for kw in change_keywords):
                logs.append(
                    {
                        "id": item.get("id"),
                        "username": item.get("username"),
                        "action": item.get("happenedOn"),
                        "description": item.get("description"),
                        "timestamp": item.get("happenedOnLocal"),
                        "ip_address": item.get("ip"),
                    }
                )

        response = {
            "total": len(logs),
            "count": len(logs),
            "change_logs": logs,
        }
        if wildcards_stripped:
            response["note"] = WILDCARD_STRIP_NOTE
        return format_response(response)
    except Exception as e:
        return handle_error(e)
