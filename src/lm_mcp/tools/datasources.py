# Description: DataSource tools for LogicMonitor MCP server.
# Description: Provides DataSource CRUD functions including list, get, create, update, delete.

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp.types import TextContent

from lm_mcp.tools import (
    WILDCARD_STRIP_NOTE,
    format_response,
    handle_error,
    normalize_definition_fields,
    quote_filter_value,
    require_write_permission,
    sanitize_filter_value,
)

if TYPE_CHECKING:
    from lm_mcp.client import LogicMonitorClient


async def get_datasources(
    client: LogicMonitorClient,
    name_filter: str | None = None,
    applies_to_filter: str | None = None,
    filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[TextContent]:
    """List DataSources (LogicModules) from LogicMonitor.

    Args:
        client: LogicMonitor API client.
        name_filter: Filter by DataSource name (supports wildcards).
        applies_to_filter: Filter by appliesTo expression.
        filter: Raw filter expression for advanced queries (overrides other filters).
            Supports LogicMonitor filter syntax with operators:
            : (equal), !: (not equal), > < >: <: (comparisons),
            ~ (contains), !~ (not contains).
            Examples: "name~CPU,group:Core"
        limit: Maximum number of DataSources to return.
        offset: Number of results to skip for pagination.

    Returns:
        List of TextContent with DataSource data or error.
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

        result = await client.get("/setting/datasources", params=params)

        datasources = []
        for item in result.get("items", []):
            datasources.append(
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "display_name": item.get("displayName"),
                    "description": item.get("description"),
                    "applies_to": item.get("appliesTo"),
                    "group": item.get("group"),
                    "collect_method": item.get("collectMethod"),
                    "has_multi_instances": item.get("hasMultiInstances"),
                }
            )

        total = result.get("total", 0)
        has_more = (offset + len(datasources)) < total

        response = {
            "total": total,
            "count": len(datasources),
            "offset": offset,
            "has_more": has_more,
            "datasources": datasources,
        }
        if wildcards_stripped:
            response["note"] = WILDCARD_STRIP_NOTE
        return format_response(response)
    except Exception as e:
        return handle_error(e)


async def get_datasource(
    client: LogicMonitorClient,
    datasource_id: int,
) -> list[TextContent]:
    """Get detailed information about a specific DataSource.

    Args:
        client: LogicMonitor API client.
        datasource_id: DataSource ID.

    Returns:
        List of TextContent with DataSource details or error.
    """
    try:
        result = await client.get(f"/setting/datasources/{datasource_id}")

        # Extract key details for a cleaner response
        datasource = {
            "id": result.get("id"),
            "name": result.get("name"),
            "display_name": result.get("displayName"),
            "description": result.get("description"),
            "applies_to": result.get("appliesTo"),
            "group": result.get("group"),
            "collect_method": result.get("collectMethod"),
            "collect_interval": result.get("collectInterval"),
            "has_multi_instances": result.get("hasMultiInstances"),
            "datapoints": [
                {
                    "id": dp.get("id"),
                    "name": dp.get("name"),
                    "description": dp.get("description"),
                    "type": dp.get("type"),
                    "alert_expr": dp.get("alertExpr"),
                    "post_processor_method": dp.get("postProcessorMethod", ""),
                    "post_processor_param": dp.get("postProcessorParam", ""),
                }
                for dp in result.get("dataPoints", [])
            ],
            "graphs": [
                {
                    "id": g.get("id"),
                    "name": g.get("name"),
                    "title": g.get("title"),
                }
                for g in result.get("graphs", [])
            ],
        }

        return format_response(datasource)
    except Exception as e:
        return handle_error(e)


@require_write_permission
async def create_datasource(
    client: LogicMonitorClient,
    definition: dict,
    overwrite: bool = False,
) -> list[TextContent]:
    """Create a DataSource via REST API using a full definition dict.

    Accepts REST API format (same format returned by export_datasource).
    Use this for creating DataSources from exported definitions or from
    scratch. For LM Exchange format imports, use import_datasource instead.

    Note: script DataSource datapoints require appropriate type values.

    Args:
        client: LogicMonitor API client.
        definition: Full DataSource definition dict in REST API format.
        overwrite: If True, delete existing DataSource with the same name before creating.

    Returns:
        List of TextContent with created DataSource info or error.
    """
    try:
        payload = normalize_definition_fields(definition)
        payload.pop("id", None)

        if overwrite and payload.get("name"):
            # Look up existing by name and delete if found
            existing = await client.get(
                "/setting/datasources",
                params={"filter": f"name:{quote_filter_value(payload['name'])}", "size": 1},
            )
            items = existing.get("items", [])
            if items:
                await client.delete(f"/setting/datasources/{items[0]['id']}")

        result = await client.post("/setting/datasources", json_body=payload)

        return format_response(
            {
                "success": True,
                "message": f"DataSource '{result.get('name')}' created successfully",
                "datasource": {
                    "id": result.get("id"),
                    "name": result.get("name"),
                    "display_name": result.get("displayName"),
                },
            }
        )
    except Exception as e:
        return handle_error(e)


@require_write_permission
async def update_datasource(
    client: LogicMonitorClient,
    datasource_id: int,
    definition: dict,
    confirm: bool = False,
) -> list[TextContent]:
    """Update an existing DataSource via REST API (full replace).

    The LM API uses full-replace semantics: every field not included in the
    definition will be blanked. The name and displayName fields are required
    even for targeted changes. Two prior production incidents wiped Groovy
    scripts via this tool. PREFER update_logicmodule for partial updates;
    it exports, deep-merges, and previews a diff before writing.

    Args:
        client: LogicMonitor API client.
        datasource_id: DataSource ID to update.
        definition: Full DataSource definition dict with all fields.
        confirm: Must be True to proceed. Defaults to False to prevent
            accidental field-blanking via partial payloads.

    Returns:
        List of TextContent with updated DataSource info or error.
    """
    if not confirm:
        return format_response(
            {
                "error": True,
                "code": "CONFIRMATION_REQUIRED",
                "message": (
                    "update_datasource is full-replace -- any field omitted from "
                    "`definition` will be BLANKED. Set confirm=true to proceed, OR "
                    "use update_logicmodule(type='datasource', id, changes, mode='preview') "
                    "for a safe partial update with diff preview."
                ),
            }
        )
    try:
        payload = normalize_definition_fields(definition)
        payload.pop("id", None)

        result = await client.put(f"/setting/datasources/{datasource_id}", json_body=payload)

        return format_response(
            {
                "success": True,
                "message": f"DataSource '{result.get('name')}' updated successfully",
                "datasource": {
                    "id": result.get("id"),
                    "name": result.get("name"),
                    "display_name": result.get("displayName"),
                },
            }
        )
    except Exception as e:
        return handle_error(e)


@require_write_permission
async def delete_datasource(
    client: LogicMonitorClient,
    datasource_id: int,
) -> list[TextContent]:
    """Delete a DataSource from LogicMonitor.

    WARNING: This removes the DataSource definition. Monitoring data collected
    by this DataSource is retained on devices but no new data will be collected.

    Args:
        client: LogicMonitor API client.
        datasource_id: DataSource ID to delete.

    Returns:
        List of TextContent with deletion confirmation or error.
    """
    try:
        # Get DataSource info for confirmation
        ds = await client.get(f"/setting/datasources/{datasource_id}")
        ds_name = ds.get("name", f"ID:{datasource_id}")

        await client.delete(f"/setting/datasources/{datasource_id}")

        return format_response(
            {
                "success": True,
                "message": f"DataSource '{ds_name}' deleted",
                "datasource_id": datasource_id,
            }
        )
    except Exception as e:
        return handle_error(e)
