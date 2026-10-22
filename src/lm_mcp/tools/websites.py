# Description: Website/Synthetic monitoring tools for LogicMonitor MCP server.
# Description: Provides CRUD operations for websites and website groups.

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp.types import TextContent

from lm_mcp.tools import (
    WILDCARD_STRIP_NOTE,
    format_response,
    handle_error,
    paginated_response,
    portal_url,
    quote_filter_value,
    require_write_permission,
    sanitize_filter_value,
)

if TYPE_CHECKING:
    from lm_mcp.client import LogicMonitorClient


async def get_websites(
    client: LogicMonitorClient,
    name_filter: str | None = None,
    group_id: int | None = None,
    filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[TextContent]:
    """List websites/synthetic checks from LogicMonitor.

    Args:
        client: LogicMonitor API client.
        name_filter: Filter by website name (supports wildcards).
        group_id: Filter by website group ID.
        filter: Raw filter expression for advanced queries (overrides other filters).
            Supports LogicMonitor filter syntax with operators:
            : (equal), !: (not equal), > < >: <: (comparisons),
            ~ (contains), !~ (not contains).
            Examples: "name~prod,type:webcheck"
        limit: Maximum number of websites to return.
        offset: Number of results to skip for pagination.

    Returns:
        List of TextContent with website data or error.
    """
    try:
        params: dict = {"size": limit, "offset": offset}
        wildcards_stripped = False

        # If raw filter is provided, use it directly (power user mode)
        if filter:
            params["filter"] = filter
        else:
            # Build filter from named parameters
            filters = []
            if name_filter:
                clean_name, was_modified = sanitize_filter_value(name_filter)
                wildcards_stripped = wildcards_stripped or was_modified
                filters.append(f"name~{quote_filter_value(clean_name)}")
            if group_id is not None:
                filters.append(f"groupId:{group_id}")

            if filters:
                params["filter"] = ",".join(filters)

        result = await client.get("/website/websites", params=params)

        websites = []
        for item in result.get("items", []):
            websites.append(
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "type": item.get("type"),
                    "description": item.get("description"),
                    "group_id": item.get("groupId"),
                    "status": item.get("status"),
                    "alert_status": item.get("alertStatus"),
                    "overall_status": item.get("overallAlertLevel"),
                    "polling_interval": item.get("pollingInterval"),
                    "host": item.get("host") or item.get("domain"),
                }
            )

        response = {
            **paginated_response(websites, result, offset),
            "websites": websites,
        }
        if wildcards_stripped:
            response["note"] = WILDCARD_STRIP_NOTE
        return format_response(response)
    except Exception as e:
        return handle_error(e)


async def get_website(
    client: LogicMonitorClient,
    website_id: int,
) -> list[TextContent]:
    """Get detailed information about a specific website.

    Args:
        client: LogicMonitor API client.
        website_id: Website ID.

    Returns:
        List of TextContent with website details or error.
    """
    try:
        result = await client.get(f"/website/websites/{website_id}")

        website = {
            "id": result.get("id"),
            "name": result.get("name"),
            "type": result.get("type"),
            "description": result.get("description"),
            "group_id": result.get("groupId"),
            "status": result.get("status"),
            "alert_status": result.get("alertStatus"),
            "host": result.get("host") or result.get("domain"),
            "polling_interval": result.get("pollingInterval"),
            "use_default_alert_setting": result.get("useDefaultAlertSetting"),
            "use_default_location_setting": result.get("useDefaultLocationSetting"),
            "portal_url": portal_url("website", website_id),
            "checkpoints": [
                {
                    "id": cp.get("id"),
                    "geo_info": cp.get("geoInfo"),
                    "smg_id": cp.get("smgId"),
                }
                for cp in result.get("checkpoints", [])
            ],
            "steps": [
                {
                    "url": step.get("url"),
                    "http_method": step.get("HTTPMethod"),
                    "status_code": step.get("statusCode"),
                    "timeout": step.get("timeout"),
                }
                for step in result.get("steps", [])
            ],
        }

        return format_response(website)
    except Exception as e:
        return handle_error(e)


async def get_website_groups(
    client: LogicMonitorClient,
    parent_id: int | None = None,
    name_filter: str | None = None,
    limit: int = 50,
) -> list[TextContent]:
    """List website groups from LogicMonitor.

    Args:
        client: LogicMonitor API client.
        parent_id: Filter by parent group ID.
        name_filter: Filter by group name (supports wildcards).
        limit: Maximum number of groups to return.

    Returns:
        List of TextContent with group data or error.
    """
    try:
        params: dict = {"size": limit}
        wildcards_stripped = False

        filters = []
        if parent_id is not None:
            filters.append(f"parentId:{parent_id}")
        if name_filter:
            clean_name, was_modified = sanitize_filter_value(name_filter)
            wildcards_stripped = wildcards_stripped or was_modified
            filters.append(f"name~{quote_filter_value(clean_name)}")

        if filters:
            params["filter"] = ",".join(filters)

        result = await client.get("/website/groups", params=params)

        groups = []
        for item in result.get("items", []):
            groups.append(
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "description": item.get("description"),
                    "parent_id": item.get("parentId"),
                    "full_path": item.get("fullPath"),
                    "website_count": item.get("numOfWebsites"),
                    "has_websites_disabled": item.get("hasWebsitesDisabled"),
                }
            )

        response = {
            "total": result.get("total", 0),
            "count": len(groups),
            "groups": groups,
        }
        if wildcards_stripped:
            response["note"] = WILDCARD_STRIP_NOTE
        return format_response(response)
    except Exception as e:
        return handle_error(e)


async def get_website_data(
    client: LogicMonitorClient,
    website_id: int,
    checkpoint_id: int,
    start_time: int | None = None,
    end_time: int | None = None,
) -> list[TextContent]:
    """Get monitoring data for a website checkpoint.

    Args:
        client: LogicMonitor API client.
        website_id: Website ID.
        checkpoint_id: Checkpoint (location) ID.
        start_time: Start time in epoch seconds (optional).
        end_time: End time in epoch seconds (optional).

    Returns:
        List of TextContent with website data or error.
    """
    try:
        params: dict = {}

        if start_time:
            params["start"] = start_time
        if end_time:
            params["end"] = end_time

        result = await client.get(
            f"/website/websites/{website_id}/checkpoints/{checkpoint_id}/data",
            params=params if params else None,
        )

        return format_response(
            {
                "website_id": website_id,
                "checkpoint_id": checkpoint_id,
                "datapoints": result.get("dataPoints", []),
                "values": result.get("values", {}),
                "time": result.get("time", []),
            }
        )
    except Exception as e:
        return handle_error(e)


@require_write_permission
async def create_website(
    client: LogicMonitorClient,
    name: str,
    website_type: str,
    domain: str,
    description: str | None = None,
    group_id: int | None = None,
    polling_interval: int = 5,
    is_internal: bool = False,
) -> list[TextContent]:
    """Create a website check in LogicMonitor.

    Args:
        client: LogicMonitor API client.
        name: Name of the website check.
        website_type: Type of check (webcheck, pingcheck).
        domain: Domain or host to check.
        description: Optional description.
        group_id: Website group ID to place website in.
        polling_interval: Check interval in minutes (default 5).
        is_internal: Whether this is an internal website.

    Returns:
        List of TextContent with result or error.
    """
    try:
        body: dict = {
            "name": name,
            "type": website_type,
            "host": domain,
            "pollingInterval": polling_interval,
            "isInternal": is_internal,
        }

        if description:
            body["description"] = description
        if group_id is not None:
            body["groupId"] = group_id

        result = await client.post("/website/websites", json_body=body)

        return format_response(
            {
                "success": True,
                "message": f"Website '{name}' created",
                "website_id": result.get("id"),
                "result": result,
            }
        )
    except Exception as e:
        return handle_error(e)


@require_write_permission
async def update_website(
    client: LogicMonitorClient,
    website_id: int,
    name: str | None = None,
    description: str | None = None,
    polling_interval: int | None = None,
    is_internal: bool | None = None,
    disable_alerting: bool | None = None,
) -> list[TextContent]:
    """Update a website check in LogicMonitor.

    Args:
        client: LogicMonitor API client.
        website_id: ID of the website to update.
        name: Updated name.
        description: Updated description.
        polling_interval: Updated polling interval in minutes.
        is_internal: Updated internal website flag.
        disable_alerting: Whether to disable alerting.

    Returns:
        List of TextContent with result or error.
    """
    try:
        body: dict = {}

        if name is not None:
            body["name"] = name
        if description is not None:
            body["description"] = description
        if polling_interval is not None:
            body["pollingInterval"] = polling_interval
        if is_internal is not None:
            body["isInternal"] = is_internal
        if disable_alerting is not None:
            body["disableAlerting"] = disable_alerting

        if not body:
            return format_response(
                {
                    "error": True,
                    "code": "VALIDATION_ERROR",
                    "message": "No fields provided to update",
                }
            )

        result = await client.patch(f"/website/websites/{website_id}", json_body=body)

        return format_response(
            {
                "success": True,
                "message": f"Website {website_id} updated",
                "result": result,
            }
        )
    except Exception as e:
        return handle_error(e)


@require_write_permission
async def delete_website(
    client: LogicMonitorClient,
    website_id: int,
) -> list[TextContent]:
    """Delete a website check from LogicMonitor.

    Args:
        client: LogicMonitor API client.
        website_id: ID of the website to delete.

    Returns:
        List of TextContent with result or error.
    """
    try:
        await client.delete(f"/website/websites/{website_id}")

        return format_response(
            {
                "success": True,
                "message": f"Website {website_id} deleted",
            }
        )
    except Exception as e:
        return handle_error(e)


@require_write_permission
async def create_website_group(
    client: LogicMonitorClient,
    name: str,
    parent_id: int | None = None,
    description: str | None = None,
) -> list[TextContent]:
    """Create a website group in LogicMonitor.

    Args:
        client: LogicMonitor API client.
        name: Name of the website group.
        parent_id: Parent group ID (optional).
        description: Optional description.

    Returns:
        List of TextContent with result or error.
    """
    try:
        body: dict = {"name": name}

        if parent_id is not None:
            body["parentId"] = parent_id
        if description:
            body["description"] = description

        result = await client.post("/website/groups", json_body=body)

        return format_response(
            {
                "success": True,
                "message": f"Website group '{name}' created",
                "group_id": result.get("id"),
                "result": result,
            }
        )
    except Exception as e:
        return handle_error(e)


@require_write_permission
async def delete_website_group(
    client: LogicMonitorClient,
    group_id: int,
) -> list[TextContent]:
    """Delete a website group from LogicMonitor.

    Args:
        client: LogicMonitor API client.
        group_id: ID of the group to delete.

    Returns:
        List of TextContent with result or error.
    """
    try:
        await client.delete(f"/website/groups/{group_id}")

        return format_response(
            {
                "success": True,
                "message": f"Website group {group_id} deleted",
            }
        )
    except Exception as e:
        return handle_error(e)
