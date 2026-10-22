# Description: ConfigSource tools for LogicMonitor MCP server.
# Description: Provides ConfigSource definitions and device config data retrieval.

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


async def get_configsources(
    client: LogicMonitorClient,
    name_filter: str | None = None,
    applies_to_filter: str | None = None,
    filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[TextContent]:
    """List ConfigSources from LogicMonitor.

    Args:
        client: LogicMonitor API client.
        name_filter: Filter by name (supports wildcards).
        applies_to_filter: Filter by appliesTo expression.
        filter: Raw filter expression for advanced queries (overrides other filters).
            Supports LogicMonitor filter syntax with operators:
            : (equal), !: (not equal), > < >: <: (comparisons),
            ~ (contains), !~ (not contains).
            Examples: "name~Cisco,technology:snmp"
        limit: Maximum number of ConfigSources to return.
        offset: Number of results to skip for pagination.

    Returns:
        List of TextContent with ConfigSource data or error.
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

        result = await client.get("/setting/configsources", params=params)

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
                    "collect_method": item.get("collectMethod"),
                    "collect_interval": item.get("collectInterval"),
                    "version": item.get("version"),
                }
            )

        response = {
            **paginated_response(sources, result, offset),
            "configsources": sources,
        }
        if wildcards_stripped:
            response["note"] = WILDCARD_STRIP_NOTE
        return format_response(response)
    except Exception as e:
        return handle_error(e)


@require_write_permission
async def create_configsource(
    client: LogicMonitorClient,
    definition: dict,
    overwrite: bool = False,
) -> list[TextContent]:
    """Create a ConfigSource via REST API using a full definition dict.

    Accepts REST API format (same format returned by export_configsource).
    Use this for creating ConfigSources from exported definitions or from
    scratch. For LM Exchange format imports, use import_configsource instead.

    Args:
        client: LogicMonitor API client.
        definition: Full ConfigSource definition dict in REST API format.
        overwrite: If True, delete existing ConfigSource with the same name
            before creating.

    Returns:
        List of TextContent with created ConfigSource info or error.
    """
    try:
        payload = normalize_definition_fields(definition)
        payload.pop("id", None)

        if overwrite and payload.get("name"):
            existing = await client.get(
                "/setting/configsources",
                params={"filter": f"name:{quote_filter_value(payload['name'])}", "size": 1},
            )
            items = existing.get("items", [])
            if items:
                await client.delete(f"/setting/configsources/{items[0]['id']}")

        result = await client.post("/setting/configsources", json_body=payload)

        return format_response(
            {
                "success": True,
                "message": f"ConfigSource '{result.get('name')}' created successfully",
                "configsource": {
                    "id": result.get("id"),
                    "name": result.get("name"),
                    "display_name": result.get("displayName"),
                },
            }
        )
    except Exception as e:
        return handle_error(e)


@require_write_permission
async def update_configsource(
    client: LogicMonitorClient,
    configsource_id: int,
    definition: dict,
    confirm: bool = False,
) -> list[TextContent]:
    """Update an existing ConfigSource via REST API (full replace).

    The LM API uses full-replace semantics: every field not included in the
    definition will be blanked. PREFER update_logicmodule for partial updates;
    it exports, deep-merges, and previews a diff before writing.

    Args:
        client: LogicMonitor API client.
        configsource_id: ConfigSource ID to update.
        definition: Full ConfigSource definition dict with all fields.
        confirm: Must be True to proceed. Defaults to False to prevent
            accidental field-blanking via partial payloads.

    Returns:
        List of TextContent with updated ConfigSource info or error.
    """
    if not confirm:
        return format_response(
            {
                "error": True,
                "code": "CONFIRMATION_REQUIRED",
                "message": (
                    "update_configsource is full-replace -- any field omitted from "
                    "`definition` will be BLANKED. Set confirm=true to proceed, OR "
                    "use update_logicmodule(type='configsource', id, changes, mode='preview') "
                    "for a safe partial update with diff preview."
                ),
            }
        )
    try:
        payload = normalize_definition_fields(definition)
        payload.pop("id", None)

        result = await client.put(f"/setting/configsources/{configsource_id}", json_body=payload)

        return format_response(
            {
                "success": True,
                "message": f"ConfigSource '{result.get('name')}' updated successfully",
                "configsource": {
                    "id": result.get("id"),
                    "name": result.get("name"),
                    "display_name": result.get("displayName"),
                },
            }
        )
    except Exception as e:
        return handle_error(e)


async def get_configsource(
    client: LogicMonitorClient,
    configsource_id: int,
) -> list[TextContent]:
    """Get detailed information about a specific ConfigSource.

    Args:
        client: LogicMonitor API client.
        configsource_id: ConfigSource ID.

    Returns:
        List of TextContent with ConfigSource details or error.
    """
    try:
        result = await client.get(f"/setting/configsources/{configsource_id}")

        source = {
            "id": result.get("id"),
            "name": result.get("name"),
            "display_name": result.get("displayName"),
            "description": result.get("description"),
            "applies_to": result.get("appliesTo"),
            "technology": result.get("technology"),
            "collect_method": result.get("collectMethod"),
            "collect_interval": result.get("collectInterval"),
            "version": result.get("version"),
            "tags": result.get("tags"),
            "audit_version": result.get("auditVersion"),
            "install_date": result.get("installDate"),
            "config_checks": result.get("configChecks", []),
        }

        return format_response(source)
    except Exception as e:
        return handle_error(e)


async def get_configsource_update_reasons(
    client: LogicMonitorClient,
    configsource_id: int,
    limit: int = 50,
    offset: int = 0,
) -> list[TextContent]:
    """Get the update history and reasons for a ConfigSource.

    Returns an audit trail of changes made to the ConfigSource definition,
    including timestamps and reason descriptions.

    Args:
        client: LogicMonitor API client.
        configsource_id: ConfigSource ID.
        limit: Maximum number of entries to return.
        offset: Number of results to skip for pagination.

    Returns:
        List of TextContent with update reason entries or error.
    """
    try:
        params: dict = {"size": limit, "offset": offset}
        result = await client.get(
            f"/setting/configsources/{configsource_id}/updatereasons",
            params=params,
        )

        reasons = []
        for item in result.get("items", []):
            reasons.append(
                {
                    "version": item.get("version"),
                    "reason": item.get("reason"),
                    "date_time": item.get("dateTime"),
                    "user_name": item.get("userName"),
                }
            )

        return format_response(
            {
                "configsource_id": configsource_id,
                **paginated_response(reasons, result, offset),
                "update_reasons": reasons,
            }
        )
    except Exception as e:
        return handle_error(e)


# -- Device config data (instance-level) --------------------------------------


async def get_device_config(
    client: LogicMonitorClient,
    device_id: int,
    device_datasource_id: int,
    instance_id: int,
    limit: int = 10,
    offset: int = 0,
) -> list[TextContent]:
    """List config versions collected for a device instance.

    Returns paginated config snapshots from the LM Config Archive, including
    timestamps and change status. Use get_device_config_version to retrieve
    the full config text and diffs for a specific version.

    Typical workflow: get_device_datasources (filter by ConfigSource name) ->
    get_device_instances -> get_device_config -> get_device_config_version.

    Args:
        client: LogicMonitor API client.
        device_id: Device ID.
        device_datasource_id: Device-DataSource ID for the ConfigSource
            (from get_device_datasources).
        instance_id: Instance ID (e.g. Running-Config instance).
        limit: Maximum number of config versions to return.
        offset: Number of results to skip for pagination.

    Returns:
        List of TextContent with config version summaries or error.
    """
    try:
        params: dict = {"size": limit, "offset": offset}
        base = (
            f"/device/devices/{device_id}/devicedatasources"
            f"/{device_datasource_id}/instances/{instance_id}/config"
        )
        result = await client.get(base, params=params)

        configs = []
        for item in result.get("items", []):
            configs.append(
                {
                    "id": item.get("id"),
                    "version": item.get("version"),
                    "poll_timestamp": item.get("pollTimestamp"),
                    "change_status": item.get("changeStatus"),
                    "config_status": item.get("configStatus"),
                    "config_error_message": item.get("configErrMsg"),
                    "device_display_name": item.get("deviceDisplayName"),
                    "instance_name": item.get("instanceName"),
                    "datasource_name": item.get("dataSourceName"),
                }
            )

        return format_response(
            {
                "device_id": device_id,
                "device_datasource_id": device_datasource_id,
                "instance_id": instance_id,
                **paginated_response(configs, result, offset),
                "configs": configs,
            }
        )
    except Exception as e:
        return handle_error(e)


async def get_device_config_version(
    client: LogicMonitorClient,
    device_id: int,
    device_datasource_id: int,
    instance_id: int,
    config_id: str,
    start_epoch: int = 0,
) -> list[TextContent]:
    """Get a specific config version with full content and diffs.

    Returns the complete configuration text, line-by-line diffs from the
    previous version, and any alerts triggered by the config change.

    Args:
        client: LogicMonitor API client.
        device_id: Device ID.
        device_datasource_id: Device-DataSource ID for the ConfigSource.
        instance_id: Instance ID.
        config_id: Config version ID (from get_device_config).
        start_epoch: Epoch timestamp to compare against. Use 0 to compare
            against the immediately previous version. Use a specific epoch
            to see diffs relative to a point in time.

    Returns:
        List of TextContent with config content, diffs, and alerts or error.
    """
    try:
        params: dict = {"startEpoch": start_epoch}

        base = (
            f"/device/devices/{device_id}/devicedatasources"
            f"/{device_datasource_id}/instances/{instance_id}/config/{config_id}"
        )
        result = await client.get(base, params=params)

        # Extract diff entries
        diffs = []
        for diff in result.get("deltaConfig", []):
            diffs.append(
                {
                    "row_number": diff.get("rowNo"),
                    "type": diff.get("type"),
                    "content": diff.get("content"),
                }
            )

        # Extract associated alerts
        alerts = []
        for alert in result.get("alerts", []):
            alerts.append(
                {
                    "alert_id": alert.get("alertId"),
                    "alert_level": alert.get("alertLevel"),
                    "alert_summary": alert.get("alertSummary"),
                    "timestamp": alert.get("timestamp"),
                }
            )

        return format_response(
            {
                "device_id": device_id,
                "instance_id": instance_id,
                "config_id": config_id,
                "version": result.get("version"),
                "poll_timestamp": result.get("pollTimestamp"),
                "change_status": result.get("changeStatus"),
                "compared_with": result.get("comparedWith"),
                "config": result.get("config"),
                "delta_config": diffs,
                "alerts": alerts,
                "device_display_name": result.get("deviceDisplayName"),
                "instance_name": result.get("instanceName"),
                "datasource_name": result.get("dataSourceName"),
            }
        )
    except Exception as e:
        return handle_error(e)


@require_write_permission
async def collect_device_config(
    client: LogicMonitorClient,
    device_id: int,
    device_datasource_id: int,
    instance_id: int,
) -> list[TextContent]:
    """Trigger an on-demand config collection for a device instance.

    Forces the collector to immediately gather a new config snapshot,
    rather than waiting for the next scheduled collection interval.

    Args:
        client: LogicMonitor API client.
        device_id: Device ID.
        device_datasource_id: Device-DataSource ID for the ConfigSource.
        instance_id: Instance ID.

    Returns:
        List of TextContent with collection confirmation or error.
    """
    try:
        base = (
            f"/device/devices/{device_id}/devicedatasources"
            f"/{device_datasource_id}/instances/{instance_id}"
            "/config/configCollection"
        )
        await client.post(base)

        return format_response(
            {
                "success": True,
                "message": "Config collection triggered",
                "device_id": device_id,
                "device_datasource_id": device_datasource_id,
                "instance_id": instance_id,
            }
        )
    except Exception as e:
        return handle_error(e)


@require_write_permission
async def delete_configsource(
    client: LogicMonitorClient,
    configsource_id: int,
) -> list[TextContent]:
    """Delete a ConfigSource from LogicMonitor.

    Removes the ConfigSource definition. Existing collected config data
    is retained on devices but no new configs will be collected.

    Args:
        client: LogicMonitor API client.
        configsource_id: ConfigSource ID to delete.

    Returns:
        List of TextContent with deletion confirmation or error.
    """
    try:
        cs = await client.get(f"/setting/configsources/{configsource_id}")
        cs_name = cs.get("name", f"ID:{configsource_id}")

        await client.delete(f"/setting/configsources/{configsource_id}")

        return format_response(
            {
                "success": True,
                "message": f"ConfigSource '{cs_name}' deleted",
                "configsource_id": configsource_id,
            }
        )
    except Exception as e:
        return handle_error(e)
