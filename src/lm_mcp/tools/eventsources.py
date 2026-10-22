# Description: EventSource tools for LogicMonitor MCP server.
# Description: Provides event source query functions.

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp.types import TextContent

from lm_mcp.tools import (
    WILDCARD_STRIP_NOTE,
    format_response,
    handle_error,
    normalize_definition_fields,
    paginated_response,
    quote_filter_value,
    require_write_permission,
    sanitize_filter_value,
)

if TYPE_CHECKING:
    from lm_mcp.client import LogicMonitorClient


async def get_eventsources(
    client: LogicMonitorClient,
    name_filter: str | None = None,
    applies_to_filter: str | None = None,
    filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[TextContent]:
    """List EventSources from LogicMonitor.

    Args:
        client: LogicMonitor API client.
        name_filter: Filter by name (supports wildcards).
        applies_to_filter: Filter by appliesTo expression.
        filter: Raw filter expression for advanced queries (overrides other filters).
            Supports LogicMonitor filter syntax with operators:
            : (equal), !: (not equal), > < >: <: (comparisons),
            ~ (contains), !~ (not contains).
            Examples: "name~Windows,group:Events"
        limit: Maximum number of EventSources to return.
        offset: Number of results to skip for pagination.

    Returns:
        List of TextContent with EventSource data or error.
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
            if applies_to_filter:
                clean_val, was_modified = sanitize_filter_value(applies_to_filter)
                wildcards_stripped = wildcards_stripped or was_modified
                filters.append(f"appliesTo~{quote_filter_value(clean_val)}")

            if filters:
                params["filter"] = ",".join(filters)

        result = await client.get("/setting/eventsources", params=params)

        sources = []
        for item in result.get("items", []):
            sources.append(
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "display_name": item.get("displayName"),
                    "description": item.get("description"),
                    "applies_to": item.get("appliesTo"),
                    "technology": item.get("technology"),
                    "group": item.get("group"),
                    "version": item.get("version"),
                }
            )

        response = {
            **paginated_response(sources, result, offset),
            "eventsources": sources,
        }
        if wildcards_stripped:
            response["note"] = WILDCARD_STRIP_NOTE
        return format_response(response)
    except Exception as e:
        return handle_error(e)


@require_write_permission
async def create_eventsource(
    client: LogicMonitorClient,
    definition: dict,
    overwrite: bool = False,
) -> list[TextContent]:
    """Create an EventSource via REST API using a full definition dict.

    Accepts REST API format (same format returned by export_eventsource).
    Use this for creating EventSources from exported definitions or from
    scratch. For LM Exchange format imports, use import_eventsource instead.

    Args:
        client: LogicMonitor API client.
        definition: Full EventSource definition dict in REST API format.
        overwrite: If True, delete existing EventSource with the same name
            before creating.

    Returns:
        List of TextContent with created EventSource info or error.
    """
    try:
        payload = normalize_definition_fields(definition)
        payload.pop("id", None)

        if overwrite and payload.get("name"):
            existing = await client.get(
                "/setting/eventsources",
                params={"filter": f"name:{quote_filter_value(payload['name'])}", "size": 1},
            )
            items = existing.get("items", [])
            if items:
                await client.delete(f"/setting/eventsources/{items[0]['id']}")

        result = await client.post("/setting/eventsources", json_body=payload)

        return format_response(
            {
                "success": True,
                "message": f"EventSource '{result.get('name')}' created successfully",
                "eventsource": {
                    "id": result.get("id"),
                    "name": result.get("name"),
                    "display_name": result.get("displayName"),
                },
            }
        )
    except Exception as e:
        return handle_error(e)


@require_write_permission
async def update_eventsource(
    client: LogicMonitorClient,
    eventsource_id: int,
    definition: dict,
    confirm: bool = False,
) -> list[TextContent]:
    """Update an existing EventSource via REST API (full replace).

    The LM API uses full-replace semantics: every field not included in the
    definition will be blanked. PREFER update_logicmodule for partial updates;
    it exports, deep-merges, and previews a diff before writing.

    Args:
        client: LogicMonitor API client.
        eventsource_id: EventSource ID to update.
        definition: Full EventSource definition dict with all fields.
        confirm: Must be True to proceed. Defaults to False to prevent
            accidental field-blanking via partial payloads.

    Returns:
        List of TextContent with updated EventSource info or error.
    """
    if not confirm:
        return format_response(
            {
                "error": True,
                "code": "CONFIRMATION_REQUIRED",
                "message": (
                    "update_eventsource is full-replace -- any field omitted from "
                    "`definition` will be BLANKED. Set confirm=true to proceed, OR "
                    "use update_logicmodule(type='eventsource', id, changes, mode='preview') "
                    "for a safe partial update with diff preview."
                ),
            }
        )
    try:
        payload = normalize_definition_fields(definition)
        payload.pop("id", None)

        result = await client.put(f"/setting/eventsources/{eventsource_id}", json_body=payload)

        return format_response(
            {
                "success": True,
                "message": f"EventSource '{result.get('name')}' updated successfully",
                "eventsource": {
                    "id": result.get("id"),
                    "name": result.get("name"),
                    "display_name": result.get("displayName"),
                },
            }
        )
    except Exception as e:
        return handle_error(e)


async def get_eventsource(
    client: LogicMonitorClient,
    eventsource_id: int,
) -> list[TextContent]:
    """Get detailed information about a specific EventSource.

    Args:
        client: LogicMonitor API client.
        eventsource_id: EventSource ID.

    Returns:
        List of TextContent with EventSource details or error.
    """
    try:
        result = await client.get(f"/setting/eventsources/{eventsource_id}")

        source = {
            "id": result.get("id"),
            "name": result.get("name"),
            "display_name": result.get("displayName"),
            "description": result.get("description"),
            "applies_to": result.get("appliesTo"),
            "technology": result.get("technology"),
            "group": result.get("group"),
            "version": result.get("version"),
            "tags": result.get("tags"),
            "audit_version": result.get("auditVersion"),
            "install_date": result.get("installDate"),
            "filters": result.get("filters", []),
        }

        return format_response(source)
    except Exception as e:
        return handle_error(e)


async def get_device_eventsources(
    client: LogicMonitorClient,
    device_id: int,
    limit: int = 50,
) -> list[TextContent]:
    """Get EventSources applied to a device.

    Args:
        client: LogicMonitor API client.
        device_id: Device ID.
        limit: Maximum results.

    Returns:
        List of TextContent with device EventSource associations or error.
    """
    try:
        params: dict = {"size": limit}
        result = await client.get(f"/device/devices/{device_id}/deviceeventsources", params=params)

        eventsources = []
        for item in result.get("items", []):
            eventsources.append(
                {
                    "id": item.get("id"),
                    "eventsource_id": item.get("eventSourceId"),
                    "name": item.get("eventSourceDisplayName")
                    or item.get("dataSourceDisplayName", ""),
                    "alerting_disabled": item.get("alertDisableStatus", "none"),
                    "alert_status": item.get("alertStatus", "none"),
                }
            )

        return format_response(
            {
                "device_id": device_id,
                "total": result.get("total", 0),
                "count": len(eventsources),
                "eventsources": eventsources,
            }
        )
    except Exception as e:
        return handle_error(e)


@require_write_permission
async def update_device_eventsource(
    client: LogicMonitorClient,
    device_id: int,
    device_eventsource_id: int,
    disable_alerting: bool | None = None,
) -> list[TextContent]:
    """Update a device-level EventSource association.

    Allows enabling or disabling alerting for an EventSource on a specific device.

    Args:
        client: LogicMonitor API client.
        device_id: Device ID.
        device_eventsource_id: Device-EventSource association ID (from get_device_eventsources).
        disable_alerting: Set True to disable alerting, False to enable.

    Returns:
        List of TextContent with updated association or error.
    """
    try:
        body: dict = {}

        if disable_alerting is not None:
            body["disableAlerting"] = disable_alerting

        if not body:
            return format_response(
                {
                    "error": True,
                    "code": "NO_CHANGES",
                    "message": "No updates provided",
                }
            )

        result = await client.patch(
            f"/device/devices/{device_id}/deviceeventsources/{device_eventsource_id}",
            json_body=body,
        )

        return format_response(
            {
                "message": "Device EventSource updated successfully",
                "device_id": device_id,
                "device_eventsource_id": device_eventsource_id,
                "name": result.get("eventSourceDisplayName")
                or result.get("dataSourceDisplayName", ""),
                "alerting_disabled": result.get("alertDisableStatus", ""),
            }
        )
    except Exception as e:
        return handle_error(e)


@require_write_permission
async def delete_eventsource(
    client: LogicMonitorClient,
    eventsource_id: int,
) -> list[TextContent]:
    """Delete an EventSource from LogicMonitor.

    Removes the EventSource definition. Existing collected event data
    is retained on devices but no new events will be collected.

    Args:
        client: LogicMonitor API client.
        eventsource_id: EventSource ID to delete.

    Returns:
        List of TextContent with deletion confirmation or error.
    """
    try:
        es = await client.get(f"/setting/eventsources/{eventsource_id}")
        es_name = es.get("name", f"ID:{eventsource_id}")

        await client.delete(f"/setting/eventsources/{eventsource_id}")

        return format_response(
            {
                "success": True,
                "message": f"EventSource '{es_name}' deleted",
                "eventsource_id": eventsource_id,
            }
        )
    except Exception as e:
        return handle_error(e)
