# Description: TopologySource tools for LogicMonitor MCP server.
# Description: Provides topology source query functions.

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


async def get_topologysources(
    client: LogicMonitorClient,
    name_filter: str | None = None,
    applies_to_filter: str | None = None,
    filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[TextContent]:
    """List TopologySources from LogicMonitor.

    Args:
        client: LogicMonitor API client.
        name_filter: Filter by name (supports wildcards).
        applies_to_filter: Filter by appliesTo expression.
        filter: Raw filter expression for advanced queries (overrides other filters).
            Supports LogicMonitor filter syntax with operators:
            : (equal), !: (not equal), > < >: <: (comparisons),
            ~ (contains), !~ (not contains).
            Examples: "name~Network,technology:snmp"
        limit: Maximum number of TopologySources to return.
        offset: Number of results to skip for pagination.

    Returns:
        List of TextContent with TopologySource data or error.
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

        result = await client.get("/setting/topologysources", params=params)

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
            "topologysources": sources,
        }
        if wildcards_stripped:
            response["note"] = WILDCARD_STRIP_NOTE
        return format_response(response)
    except Exception as e:
        return handle_error(e)


@require_write_permission
async def create_topologysource(
    client: LogicMonitorClient,
    definition: dict,
    overwrite: bool = False,
) -> list[TextContent]:
    """Create a TopologySource via REST API using a full definition dict.

    Accepts REST API format (same format returned by export_topologysource
    if one exists). Use this for creating TopologySources from definitions.
    For LM Exchange format imports, use import_topologysource instead.

    Args:
        client: LogicMonitor API client.
        definition: Full TopologySource definition dict in REST API format.
        overwrite: If True, delete existing TopologySource with the same name
            before creating.

    Returns:
        List of TextContent with created TopologySource info or error.
    """
    try:
        payload = normalize_definition_fields(definition)
        payload.pop("id", None)

        if overwrite and payload.get("name"):
            existing = await client.get(
                "/setting/topologysources",
                params={"filter": f"name:{quote_filter_value(payload['name'])}", "size": 1},
            )
            items = existing.get("items", [])
            if items:
                await client.delete(f"/setting/topologysources/{items[0]['id']}")

        result = await client.post("/setting/topologysources", json_body=payload)

        return format_response(
            {
                "success": True,
                "message": f"TopologySource '{result.get('name')}' created successfully",
                "topologysource": {
                    "id": result.get("id"),
                    "name": result.get("name"),
                    "display_name": result.get("displayName"),
                },
            }
        )
    except Exception as e:
        return handle_error(e)


@require_write_permission
async def update_topologysource(
    client: LogicMonitorClient,
    topologysource_id: int,
    definition: dict,
    confirm: bool = False,
) -> list[TextContent]:
    """Update an existing TopologySource via REST API (full replace).

    The LM API uses full-replace semantics: every field not included in the
    definition will be blanked. PREFER update_logicmodule for partial updates;
    it exports, deep-merges, and previews a diff before writing.

    Args:
        client: LogicMonitor API client.
        topologysource_id: TopologySource ID to update.
        definition: Full TopologySource definition dict with all fields.
        confirm: Must be True to proceed. Defaults to False to prevent
            accidental field-blanking via partial payloads.

    Returns:
        List of TextContent with updated TopologySource info or error.
    """
    if not confirm:
        return format_response(
            {
                "error": True,
                "code": "CONFIRMATION_REQUIRED",
                "message": (
                    "update_topologysource is full-replace -- any field omitted from "
                    "`definition` will be BLANKED. Set confirm=true to proceed, OR "
                    "use update_logicmodule(type='topologysource', id, changes, mode='preview') "
                    "for a safe partial update with diff preview."
                ),
            }
        )
    try:
        payload = normalize_definition_fields(definition)
        payload.pop("id", None)

        result = await client.put(
            f"/setting/topologysources/{topologysource_id}", json_body=payload
        )

        return format_response(
            {
                "success": True,
                "message": f"TopologySource '{result.get('name')}' updated successfully",
                "topologysource": {
                    "id": result.get("id"),
                    "name": result.get("name"),
                    "display_name": result.get("displayName"),
                },
            }
        )
    except Exception as e:
        return handle_error(e)


@require_write_permission
async def delete_topologysource(
    client: LogicMonitorClient,
    topologysource_id: int,
) -> list[TextContent]:
    """Delete a TopologySource from LogicMonitor.

    Removes the TopologySource definition. Existing topology data
    is retained but no new topology will be collected.

    Args:
        client: LogicMonitor API client.
        topologysource_id: TopologySource ID to delete.

    Returns:
        List of TextContent with deletion confirmation or error.
    """
    try:
        ts = await client.get(f"/setting/topologysources/{topologysource_id}")
        ts_name = ts.get("name", f"ID:{topologysource_id}")

        await client.delete(f"/setting/topologysources/{topologysource_id}")

        return format_response(
            {
                "success": True,
                "message": f"TopologySource '{ts_name}' deleted",
                "topologysource_id": topologysource_id,
            }
        )
    except Exception as e:
        return handle_error(e)


async def get_topologysource(
    client: LogicMonitorClient,
    topologysource_id: int,
) -> list[TextContent]:
    """Get detailed information about a specific TopologySource.

    Args:
        client: LogicMonitor API client.
        topologysource_id: TopologySource ID.

    Returns:
        List of TextContent with TopologySource details or error.
    """
    try:
        result = await client.get(f"/setting/topologysources/{topologysource_id}")

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
        }

        return format_response(source)
    except Exception as e:
        return handle_error(e)
