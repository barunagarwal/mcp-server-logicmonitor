# Description: Dashboard tools for LogicMonitor MCP server.
# Description: Provides dashboard and widget management tools.

from __future__ import annotations

import json
import logging
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
    strip_readonly,
)

if TYPE_CHECKING:
    from lm_mcp.client import LogicMonitorClient

logger = logging.getLogger(__name__)


def _count_widgets(item: dict) -> int:
    """Extract widget count from a dashboard record.

    Prefer ``numOfWidgets`` when present (most reliable on the list endpoint).
    Otherwise count ``widgetsConfig``, which real portals return as a dict keyed by
    widget id ({"21": {...}, ...}) and which older callers passed as a list of ids. A
    literal ``count`` key only appears in synthetic data; honor it if present.
    """
    if "numOfWidgets" in item:
        return int(item["numOfWidgets"])
    cfg = item.get("widgetsConfig")
    if isinstance(cfg, dict):
        count = cfg.get("count")
        if isinstance(count, int):
            return count
        return len(cfg)
    if isinstance(cfg, list):
        return len(cfg)
    return 0


# Server-managed fields that LogicMonitor rejects or ignores when echoed back on a
# write; strip them before a PUT to avoid intermittent 400s.
_DASHBOARD_READONLY_FIELDS = (
    "fullName",
    "userPermission",
    "groupName",
    "groupFullPath",
    "owner",
)
_WIDGET_READONLY_FIELDS = (
    "lastUpdatedOn",
    "lastUpdatedBy",
    "userPermission",
)


def _next_widget_row(config: dict) -> int:
    """First row below every existing widget, so a new widget appends at the bottom.

    ``config`` is the dashboard's widgetsConfig: a dict keyed by widget id whose
    values are {col, row, sizex, sizey}.
    """
    if not isinstance(config, dict) or not config:
        return 1
    bottoms = [
        pos.get("row", 1) + pos.get("sizey", 1) for pos in config.values() if isinstance(pos, dict)
    ]
    return max(bottoms) if bottoms else 1


async def _place_widget(
    client: LogicMonitorClient,
    dashboard_id: int,
    widget_id: int,
    *,
    col: int,
    sizex: int,
    sizey: int,
    row: int | None = None,
) -> dict:
    """Write a widget's grid position into the parent dashboard's widgetsConfig.

    Placement lives on the dashboard (keyed by widget id), not on the widget; the
    ``/dashboard/widgets`` body silently discards columnIdx/rowSpan/colSpan. This
    merges the one widget into the current widgetsConfig (preserving every sibling's
    position) and PATCHes it back so the placement takes effect. Returns the position
    written.
    """
    dashboard = await client.get(f"/dashboard/dashboards/{dashboard_id}")
    config = dashboard.get("widgetsConfig")
    if not isinstance(config, dict):
        config = {}
    if row is None:
        row = _next_widget_row(config)
    position = {"col": col, "row": row, "sizex": sizex, "sizey": sizey}
    config[str(widget_id)] = position
    await client.patch(
        f"/dashboard/dashboards/{dashboard_id}",
        json_body={"widgetsConfig": config},
    )
    return position


async def get_dashboards(
    client: LogicMonitorClient,
    name_filter: str | None = None,
    group_id: int | None = None,
    filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[TextContent]:
    """List dashboards from LogicMonitor.

    Args:
        client: LogicMonitor API client.
        name_filter: Filter by dashboard name (supports wildcards).
        group_id: Filter by dashboard group ID.
        filter: Raw filter expression for advanced queries (overrides other filters).
            Supports LogicMonitor filter syntax with operators:
            : (equal), !: (not equal), > < >: <: (comparisons),
            ~ (contains), !~ (not contains).
            Examples: "name~prod,owner:admin"
        limit: Maximum number of dashboards to return.
        offset: Number of results to skip for pagination.

    Returns:
        List of TextContent with dashboard data or error.
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

        result = await client.get("/dashboard/dashboards", params=params)

        dashboards = []
        for item in result.get("items", []):
            dashboards.append(
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "description": item.get("description"),
                    "group_id": item.get("groupId"),
                    "group_name": item.get("groupFullPath"),
                    "widget_count": _count_widgets(item),
                    "owner": item.get("owner"),
                }
            )

        response = {
            **paginated_response(dashboards, result, offset),
            "dashboards": dashboards,
        }
        if wildcards_stripped:
            response["note"] = WILDCARD_STRIP_NOTE
        return format_response(response)
    except Exception as e:
        return handle_error(e)


async def get_dashboard(
    client: LogicMonitorClient,
    dashboard_id: int,
) -> list[TextContent]:
    """Get detailed information about a specific dashboard.

    Args:
        client: LogicMonitor API client.
        dashboard_id: Dashboard ID.

    Returns:
        List of TextContent with dashboard details or error.
    """
    try:
        result = await client.get(f"/dashboard/dashboards/{dashboard_id}")
        result["portal_url"] = portal_url("dashboard", dashboard_id)
        return format_response(result)
    except Exception as e:
        return handle_error(e)


async def get_dashboard_widgets(
    client: LogicMonitorClient,
    dashboard_id: int,
    limit: int = 100,
) -> list[TextContent]:
    """Get widgets for a specific dashboard.

    Args:
        client: LogicMonitor API client.
        dashboard_id: Dashboard ID.
        limit: Maximum number of widgets to return.

    Returns:
        List of TextContent with widget data or error.
    """
    try:
        params: dict = {"size": limit}

        result = await client.get(f"/dashboard/dashboards/{dashboard_id}/widgets", params=params)

        # Position (column/row/spans) lives on the parent dashboard's widgetsConfig
        # keyed by widget id, not on the widget objects -- which is why these came back
        # null before. Fetch the dashboard and map placement onto each widget.
        dashboard = await client.get(f"/dashboard/dashboards/{dashboard_id}")
        config = dashboard.get("widgetsConfig")
        if not isinstance(config, dict):
            config = {}

        widgets = []
        for item in result.get("items", []):
            pos = config.get(str(item.get("id")))
            if not isinstance(pos, dict):
                pos = {}
            widgets.append(
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "type": item.get("type"),
                    "description": item.get("description"),
                    "column": pos.get("col"),
                    "row": pos.get("row"),
                    "col_span": pos.get("sizex"),
                    "row_span": pos.get("sizey"),
                }
            )

        return format_response(
            {
                "dashboard_id": dashboard_id,
                "total": result.get("total", 0),
                "count": len(widgets),
                "widgets": widgets,
            }
        )
    except Exception as e:
        return handle_error(e)


@require_write_permission
async def create_dashboard(
    client: LogicMonitorClient,
    name: str,
    group_id: int = 1,
    description: str | None = None,
    sharable: bool = True,
    widget_tokens: list[dict] | None = None,
    template: dict | None = None,
    template_path: str | None = None,
) -> list[TextContent]:
    """Create a new dashboard, optionally cloning widgets from an exported template.

    The template (an exported dashboard definition from ``export_dashboard``) can be
    passed inline via ``template`` or loaded by reference from a local file via
    ``template_path`` -- the latter keeps a large exported definition out of the model
    context. An ``export_dashboard`` envelope (``{..., "definition": {...}}``) is
    unwrapped automatically. When the template has widgets, the shell is created first,
    then each widget in ``widgets_full`` is recreated on the new dashboard and the
    exported ``widgetsConfig`` placement is re-applied with the new widget ids. Explicit
    parameters (group_id, description, widget_tokens) override template values.

    There is no separate "import_dashboard": dashboards have no LM Exchange format, so
    recreating an exported dashboard is a create, not an import.

    Args:
        client: LogicMonitor API client.
        name: Dashboard name.
        group_id: Dashboard group ID (default: 1 for root).
        description: Dashboard description.
        sharable: Whether dashboard is sharable (default: True).
        widget_tokens: List of token dicts (e.g., [{"name": "##host##", "value": "server1"}]).
        template: Full dashboard definition to use as base (from export_dashboard).
        template_path: Path to a local JSON file holding the dashboard definition or an
            export_dashboard envelope. Ignored when ``template`` is provided.

    Returns:
        List of TextContent with created dashboard details or error.
    """
    try:
        # Load the template by reference if a path was given (keeps a large exported
        # definition out of the model context); unwrap an export_dashboard envelope.
        if template is None and template_path:
            with open(template_path, encoding="utf-8") as fh:
                loaded = json.loads(fh.read())
            if isinstance(loaded, dict) and isinstance(loaded.get("definition"), dict):
                loaded = loaded["definition"]
            template = loaded

        widgets_to_create: list[dict] = []
        template_config: dict = {}

        if template:
            payload = strip_readonly(dict(template), _DASHBOARD_READONLY_FIELDS)
            payload.pop("id", None)
            # Widgets and their placement are recreated in follow-up calls, not on the
            # dashboard create body (which silently discards them).
            embedded = payload.pop("widgets_full", None) or payload.pop("widgets", None)
            if isinstance(embedded, list):
                widgets_to_create = [w for w in embedded if isinstance(w, dict)]
            cfg = payload.pop("widgetsConfig", None)
            if isinstance(cfg, dict):
                template_config = cfg
            payload["name"] = name
            payload["groupId"] = group_id
            payload["sharable"] = sharable
            if description:
                payload["description"] = description
            if widget_tokens is not None:
                payload["widgetTokens"] = widget_tokens
        else:
            payload = {
                "name": name,
                "groupId": group_id,
                "sharable": sharable,
            }
            if description:
                payload["description"] = description
            if widget_tokens is not None:
                payload["widgetTokens"] = widget_tokens

        result = await client.post("/dashboard/dashboards", json_body=payload)
        new_dashboard_id = result.get("id")

        response: dict = {
            "success": True,
            "message": f"Dashboard '{name}' created successfully",
            "dashboard": {
                "id": new_dashboard_id,
                "name": result.get("name"),
                "group_id": result.get("groupId"),
            },
        }

        if widgets_to_create and new_dashboard_id is not None:
            id_map: dict[str, str] = {}
            warnings: list[str] = []
            for widget in widgets_to_create:
                old_id = widget.get("id")
                body = strip_readonly(dict(widget), _WIDGET_READONLY_FIELDS)
                body.pop("id", None)
                body["dashboardId"] = new_dashboard_id
                try:
                    created = await client.post("/dashboard/widgets", json_body=body)
                except Exception as widget_error:
                    # One bad widget must not abort the clone or vanish silently:
                    # log the stack and surface a warning, then keep going.
                    logger.exception(
                        "create_dashboard: widget %r failed on dashboard %s",
                        widget.get("name"),
                        new_dashboard_id,
                    )
                    warnings.append(f"widget '{widget.get('name')}' failed: {widget_error}")
                    continue
                new_id = created.get("id")
                if old_id is not None and new_id is not None:
                    id_map[str(old_id)] = str(new_id)

            # Re-apply placement keyed by the NEW widget ids.
            new_config = {id_map[old]: pos for old, pos in template_config.items() if old in id_map}
            if new_config:
                await client.patch(
                    f"/dashboard/dashboards/{new_dashboard_id}",
                    json_body={"widgetsConfig": new_config},
                )

            response["widgets_created"] = len(id_map)
            response["widgets_requested"] = len(widgets_to_create)
            if warnings:
                response["widget_warnings"] = warnings

        return format_response(response)
    except Exception as e:
        return handle_error(e)


@require_write_permission
async def update_dashboard(
    client: LogicMonitorClient,
    dashboard_id: int,
    name: str | None = None,
    description: str | None = None,
    group_id: int | None = None,
    sharable: bool | None = None,
) -> list[TextContent]:
    """Update an existing dashboard.

    Args:
        client: LogicMonitor API client.
        dashboard_id: Dashboard ID to update.
        name: New dashboard name.
        description: New dashboard description.
        group_id: New dashboard group ID.
        sharable: Whether dashboard is sharable.

    Returns:
        List of TextContent with updated dashboard details or error.
    """
    try:
        # Get current dashboard to preserve unmodified fields, stripping the
        # server-managed read-only fields so the PUT does not 400 on echoed values.
        current = await client.get(f"/dashboard/dashboards/{dashboard_id}")

        payload = strip_readonly(dict(current), _DASHBOARD_READONLY_FIELDS)
        if name is not None:
            payload["name"] = name
        if description is not None:
            payload["description"] = description
        if group_id is not None:
            payload["groupId"] = group_id
        if sharable is not None:
            payload["sharable"] = sharable

        result = await client.put(f"/dashboard/dashboards/{dashboard_id}", json_body=payload)

        return format_response(
            {
                "success": True,
                "message": f"Dashboard {dashboard_id} updated",
                "dashboard": {
                    "id": result.get("id"),
                    "name": result.get("name"),
                    "group_id": result.get("groupId"),
                },
            }
        )
    except Exception as e:
        return handle_error(e)


@require_write_permission
async def delete_dashboard(
    client: LogicMonitorClient,
    dashboard_id: int,
) -> list[TextContent]:
    """Delete a dashboard.

    WARNING: This permanently deletes the dashboard and all its widgets.

    Args:
        client: LogicMonitor API client.
        dashboard_id: Dashboard ID to delete.

    Returns:
        List of TextContent with deletion result or error.
    """
    try:
        # Get dashboard info first for confirmation message
        dashboard = await client.get(f"/dashboard/dashboards/{dashboard_id}")
        dashboard_name = dashboard.get("name", f"ID:{dashboard_id}")
        widget_count = _count_widgets(dashboard)

        await client.delete(f"/dashboard/dashboards/{dashboard_id}")

        return format_response(
            {
                "success": True,
                "message": f"Dashboard '{dashboard_name}' deleted",
                "details": {
                    "dashboard_id": dashboard_id,
                    "widgets_removed": widget_count,
                },
            }
        )
    except Exception as e:
        return handle_error(e)


async def get_widget(
    client: LogicMonitorClient,
    dashboard_id: int,
    widget_id: int,
) -> list[TextContent]:
    """Get detailed information about a specific widget.

    Args:
        client: LogicMonitor API client.
        dashboard_id: Dashboard ID containing the widget.
        widget_id: Widget ID.

    Returns:
        List of TextContent with widget details or error.
    """
    try:
        result = await client.get(f"/dashboard/widgets/{widget_id}")
        return format_response(result)
    except Exception as e:
        return handle_error(e)


@require_write_permission
async def add_widget(
    client: LogicMonitorClient,
    dashboard_id: int,
    name: str,
    widget_type: str,
    column_index: int | None = None,
    row_span: int | None = None,
    col_span: int | None = None,
    row: int | None = None,
    description: str | None = None,
    config: dict | None = None,
) -> list[TextContent]:
    """Add a widget to a dashboard.

    Placement (column_index, row, row_span, col_span) is written to the parent
    dashboard's widgetsConfig, which is where LogicMonitor stores widget position; the
    widget body itself discards those fields. When no placement is given the portal
    auto-places the widget.

    Args:
        client: LogicMonitor API client.
        dashboard_id: Dashboard ID to add widget to.
        name: Widget name.
        widget_type: Widget type (e.g., cgraph, sgraph, text, html, alert, etc.).
        column_index: Start column, 1-12.
        row_span: Height in rows.
        col_span: Width in columns, 1-12.
        row: Start row (defaults to below existing widgets).
        description: Widget description.
        config: Additional widget configuration (type-specific).

    Returns:
        List of TextContent with created widget details or error.
    """
    try:
        payload: dict = {
            "name": name,
            "type": widget_type,
            "dashboardId": dashboard_id,
        }

        if description:
            payload["description"] = description

        # Validate config field names for common widget types to catch
        # silent data loss from field name mismatches (the LM API accepts
        # unknown fields but discards them without error)
        if config:
            _field_aliases: dict[str, dict[str, str]] = {
                "deviceSLA": {
                    "deviceGroupFullPath": "groupName",
                    "hostGroup": "groupName",
                    "device": "deviceName",
                    "dataSource": "dataSourceFullName",
                },
                "text": {
                    "html": "content",
                },
            }
            aliases = _field_aliases.get(widget_type, {})
            remapped = {}
            for key, val in config.items():
                if key in aliases:
                    remapped[aliases[key]] = val
                else:
                    remapped[key] = val
            payload.update(remapped)

        # Apply deviceSLA defaults for fields the portal UI sets automatically
        if widget_type == "deviceSLA":
            _sla_defaults = {
                "daysInWeek": "1,2,3,4,5,6,7",
                "periodInOneDay": "0:00-23:59",
                "displayType": 0,
                "calculationMethod": 0,
                "unmonitoredTimeAlertStatus": 0,
            }
            for key, val in _sla_defaults.items():
                payload.setdefault(key, val)

        result = await client.post(
            "/dashboard/widgets",
            json_body=payload,
        )

        widget_id = result.get("id")
        # Position is not accepted on the widget body; write it to the parent
        # dashboard's widgetsConfig so the widget is actually placed (and does not
        # overlap existing widgets). Only when the caller asked for a position --
        # otherwise the portal auto-places the new widget.
        position = None
        position_requested = any(v is not None for v in (column_index, row, row_span, col_span))
        if widget_id is not None and position_requested:
            position = await _place_widget(
                client,
                dashboard_id,
                widget_id,
                col=min(12, max(1, column_index)) if column_index is not None else 1,
                sizex=min(12, max(1, col_span)) if col_span is not None else 6,
                sizey=max(1, row_span) if row_span is not None else 1,
                row=row,
            )

        widget = {
            "id": widget_id,
            "name": result.get("name"),
            "type": result.get("type"),
            "dashboard_id": dashboard_id,
        }
        if position is not None:
            widget["position"] = position

        return format_response(
            {
                "success": True,
                "message": f"Widget '{name}' added to dashboard {dashboard_id}",
                "widget": widget,
            }
        )
    except Exception as e:
        return handle_error(e)


@require_write_permission
async def update_widget(
    client: LogicMonitorClient,
    dashboard_id: int,
    widget_id: int,
    name: str | None = None,
    description: str | None = None,
    column_index: int | None = None,
    row: int | None = None,
    row_span: int | None = None,
    col_span: int | None = None,
    config: dict | None = None,
) -> list[TextContent]:
    """Update an existing widget's content and/or its placement.

    Content fields (name, description, config) are written to the widget. Placement
    (column_index, row, row_span, col_span) is written to the parent dashboard's
    widgetsConfig, which is where LogicMonitor actually stores widget position.

    Args:
        client: LogicMonitor API client.
        dashboard_id: Dashboard ID containing the widget.
        widget_id: Widget ID to update.
        name: New widget name.
        description: New widget description.
        column_index: New start column (1-12).
        row: New start row.
        row_span: New height in rows.
        col_span: New width in columns (1-12).
        config: Additional configuration to update.

    Returns:
        List of TextContent with updated widget details or error.
    """
    try:
        content_changed = name is not None or description is not None or bool(config)
        position_changed = any(v is not None for v in (column_index, row, row_span, col_span))

        widget_summary: dict = {"id": widget_id}

        if content_changed:
            # Preserve unmodified fields but drop server-managed read-only ones so the
            # PUT does not 400 on echoed values.
            current = await client.get(f"/dashboard/widgets/{widget_id}")
            payload = strip_readonly(dict(current), _WIDGET_READONLY_FIELDS)
            if name is not None:
                payload["name"] = name
            if description is not None:
                payload["description"] = description
            if config:
                payload.update(config)

            result = await client.put(
                f"/dashboard/widgets/{widget_id}",
                json_body=payload,
            )
            widget_summary = {
                "id": result.get("id"),
                "name": result.get("name"),
                "type": result.get("type"),
            }

        if position_changed:
            dashboard = await client.get(f"/dashboard/dashboards/{dashboard_id}")
            config_map = dashboard.get("widgetsConfig")
            if not isinstance(config_map, dict):
                config_map = {}
            pos = config_map.get(str(widget_id))
            pos = dict(pos) if isinstance(pos, dict) else {}
            if column_index is not None:
                pos["col"] = min(12, max(1, column_index))
            if row is not None:
                pos["row"] = max(1, row)
            if col_span is not None:
                pos["sizex"] = min(12, max(1, col_span))
            if row_span is not None:
                pos["sizey"] = max(1, row_span)
            pos.setdefault("col", 1)
            pos.setdefault("row", _next_widget_row(config_map))
            pos.setdefault("sizex", 6)
            pos.setdefault("sizey", 1)
            config_map[str(widget_id)] = pos
            await client.patch(
                f"/dashboard/dashboards/{dashboard_id}",
                json_body={"widgetsConfig": config_map},
            )
            widget_summary["position"] = pos

        return format_response(
            {
                "success": True,
                "message": f"Widget {widget_id} updated",
                "widget": widget_summary,
            }
        )
    except Exception as e:
        return handle_error(e)


@require_write_permission
async def delete_widget(
    client: LogicMonitorClient,
    dashboard_id: int,
    widget_id: int,
) -> list[TextContent]:
    """Delete a widget from a dashboard.

    Args:
        client: LogicMonitor API client.
        dashboard_id: Dashboard ID containing the widget.
        widget_id: Widget ID to delete.

    Returns:
        List of TextContent with deletion result or error.
    """
    try:
        await client.delete(f"/dashboard/widgets/{widget_id}")

        return format_response(
            {
                "success": True,
                "message": f"Widget {widget_id} deleted from dashboard {dashboard_id}",
            }
        )
    except Exception as e:
        return handle_error(e)
