# Description: Diagnostic source tools for LogicMonitor MCP server.
# Description: CRUD and manual execution for /setting/diagnosticsources REST endpoints.

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
from lm_mcp.tools.diagnostic_remediation import run_pre_execution_checks

if TYPE_CHECKING:
    from lm_mcp.client import LogicMonitorClient


async def get_diagnosticsources(
    client: LogicMonitorClient,
    name_filter: str | None = None,
    group_filter: str | None = None,
    filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[TextContent]:
    """List DiagnosticSources from LogicMonitor.

    Calls the public REST endpoint ``/setting/diagnosticsources``. Filters
    and pagination are pushed down to the server. The implementation mirrors
    :func:`get_datasources` so consumers get a consistent shape across
    every LogicModule resource family.

    Args:
        client: LogicMonitor API client.
        name_filter: Filter by DiagnosticSource name (substring, server-side).
        group_filter: Filter by group (substring, server-side).
        filter: Raw LM filter expression (overrides typed filters).
        limit: Maximum sources to return per page.
        offset: Number of results to skip for pagination.

    Returns:
        List of TextContent with DiagnosticSource data or error.
    """
    try:
        params: dict = {"size": limit, "offset": offset}
        wildcards_stripped = False

        if filter:
            params["filter"] = filter
        else:
            filters: list[str] = []
            if name_filter:
                clean_name, was_modified = sanitize_filter_value(name_filter)
                wildcards_stripped = wildcards_stripped or was_modified
                filters.append(f"name~{quote_filter_value(clean_name)}")
            if group_filter:
                clean_group, was_modified = sanitize_filter_value(group_filter)
                wildcards_stripped = wildcards_stripped or was_modified
                filters.append(f"group~{quote_filter_value(clean_group)}")
            if filters:
                params["filter"] = ",".join(filters)

        result = await client.get("/setting/diagnosticsources", params=params)

        sources = []
        for item in result.get("items", []):
            sources.append(
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "display_name": item.get("displayName"),
                    "description": item.get("description"),
                    "applies_to": item.get("appliesTo"),
                    "group": item.get("group"),
                    "collect_method": item.get("collectMethod"),
                    "tags": item.get("tags", []),
                    "technical_notes": item.get("technicalNotes"),
                }
            )

        response = {
            **paginated_response(sources, result, offset),
            "diagnosticsources": sources,
        }
        if wildcards_stripped:
            response["note"] = WILDCARD_STRIP_NOTE
        return format_response(response)
    except Exception as e:
        return handle_error(e)


async def get_diagnosticsource(
    client: LogicMonitorClient,
    source_id: int,
) -> list[TextContent]:
    """Get details for a specific DiagnosticSource.

    Calls ``/setting/diagnosticsources/{id}`` and projects the fields most
    useful to callers (metadata + script content).

    Args:
        client: LogicMonitor API client.
        source_id: DiagnosticSource ID.

    Returns:
        List of TextContent with source details or error.
    """
    try:
        result = await client.get(f"/setting/diagnosticsources/{source_id}")

        detail = {
            "id": result.get("id"),
            "name": result.get("name"),
            "display_name": result.get("displayName"),
            "description": result.get("description"),
            "applies_to": result.get("appliesTo"),
            "group": result.get("group"),
            "collect_method": result.get("collectMethod"),
            "collect_interval": result.get("collectInterval"),
            "tags": result.get("tags", []),
            "technical_notes": result.get("technicalNotes"),
            "datapoints": [
                {
                    "id": dp.get("id"),
                    "name": dp.get("name"),
                    "description": dp.get("description"),
                    "type": dp.get("type"),
                }
                for dp in result.get("dataPoints", [])
            ],
        }

        return format_response(detail)
    except Exception as e:
        return handle_error(e)


@require_write_permission
async def execute_diagnostic(
    client: LogicMonitorClient,
    host_id: int,
    diagnostic_source_id: int,
    alert_id: str | None = None,
) -> list[TextContent]:
    """Execute a DiagnosticSource script on a target device.

    Runs the shared ADR pre-execution checklist (device reachable,
    collector build >= 39.200, appliesTo and script review with
    state-mutation warning) before triggering manual execution via
    POST /setting/diagnosticsources/executemanually.

    Args:
        client: LogicMonitor API client.
        host_id: Device/host ID to execute on.
        diagnostic_source_id: DiagnosticSource ID to execute.
        alert_id: Optional alert ID to associate with the execution.

    Returns:
        Execution result with pre-check details and warnings.
    """
    try:
        error, checks = await run_pre_execution_checks(
            client, host_id, diagnostic_source_id, source_kind="diagnostic"
        )
        if error:
            return format_response(error)

        payload: dict = {
            "hostId": host_id,
            "diagnosticId": diagnostic_source_id,
            "triggerType": "manual",
        }
        if alert_id:
            payload["alertId"] = alert_id

        exec_result = await client.post(
            "/setting/diagnosticsources/executemanually",
            json_body=payload,
        )

        response = {
            "success": True,
            "message": "Diagnostic execution initiated",
            "host_id": host_id,
            "diagnostic_source_id": diagnostic_source_id,
            "alert_id": alert_id,
            "collector_version": checks["collector_version"],
            "applies_to": checks["applies_to"],
            "script_preview": checks["script_preview"],
            "execution_response": exec_result,
            "warnings": checks["warnings"],
            "next_step": (
                "Poll get_diagnostic_remediation_results with this host_id for "
                "execution status and script output."
            ),
        }

        if checks["mutation_warning"]:
            response["mutation_warning"] = checks["mutation_warning"]

        return format_response(response)
    except Exception as e:
        return handle_error(e)


@require_write_permission
async def create_diagnosticsource(
    client: LogicMonitorClient,
    definition: dict,
    overwrite: bool = False,
) -> list[TextContent]:
    """Create a DiagnosticSource via REST API using a full definition dict.

    Accepts REST API format (same format returned by export_diagnosticsource).
    For LM Exchange format imports, use import_diagnosticsource instead.

    Args:
        client: LogicMonitor API client.
        definition: Full DiagnosticSource definition dict in REST API format.
        overwrite: If True, delete existing DiagnosticSource with the same
            name before creating.

    Returns:
        List of TextContent with created DiagnosticSource info or error.
    """
    try:
        payload = normalize_definition_fields(definition)
        payload.pop("id", None)

        if overwrite and payload.get("name"):
            existing = await client.get(
                "/setting/diagnosticsources",
                params={"filter": f"name:{quote_filter_value(payload['name'])}", "size": 1},
            )
            items = existing.get("items", [])
            if items:
                await client.delete(f"/setting/diagnosticsources/{items[0]['id']}")

        result = await client.post("/setting/diagnosticsources", json_body=payload)

        return format_response(
            {
                "success": True,
                "message": f"DiagnosticSource '{result.get('name')}' created successfully",
                "diagnosticsource": {
                    "id": result.get("id"),
                    "name": result.get("name"),
                    "display_name": result.get("displayName"),
                },
            }
        )
    except Exception as e:
        return handle_error(e)


@require_write_permission
async def update_diagnosticsource(
    client: LogicMonitorClient,
    diagnosticsource_id: int,
    definition: dict,
    confirm: bool = False,
) -> list[TextContent]:
    """Update an existing DiagnosticSource via REST API (full replace).

    The LM API uses full-replace semantics: every field not included in the
    definition will be blanked, including the Groovy script. PREFER
    update_logicmodule(type='diagnosticsource', ...) for partial updates;
    it exports, deep-merges, and previews a diff before writing.

    Args:
        client: LogicMonitor API client.
        diagnosticsource_id: DiagnosticSource ID to update.
        definition: Full DiagnosticSource definition dict with all fields.
        confirm: Must be True to proceed. Defaults to False to prevent
            accidental field-blanking via partial payloads.

    Returns:
        List of TextContent with updated DiagnosticSource info or error.
    """
    if not confirm:
        return format_response(
            {
                "error": True,
                "code": "CONFIRMATION_REQUIRED",
                "message": (
                    "update_diagnosticsource is full-replace -- any field omitted "
                    "from `definition` will be BLANKED, including the script. Set "
                    "confirm=true to proceed, OR use update_logicmodule"
                    "(type='diagnosticsource', id, changes, mode='preview') for a "
                    "safe partial update with diff preview."
                ),
            }
        )
    try:
        payload = normalize_definition_fields(definition)
        payload.pop("id", None)

        result = await client.put(
            f"/setting/diagnosticsources/{diagnosticsource_id}", json_body=payload
        )

        return format_response(
            {
                "success": True,
                "message": f"DiagnosticSource '{result.get('name')}' updated successfully",
                "diagnosticsource": {
                    "id": result.get("id"),
                    "name": result.get("name"),
                    "display_name": result.get("displayName"),
                },
            }
        )
    except Exception as e:
        return handle_error(e)


@require_write_permission
async def delete_diagnosticsource(
    client: LogicMonitorClient,
    diagnosticsource_id: int,
) -> list[TextContent]:
    """Delete a DiagnosticSource from LogicMonitor.

    WARNING: This removes the DiagnosticSource definition; any action chains
    referencing it as a stage will lose that stage.

    Args:
        client: LogicMonitor API client.
        diagnosticsource_id: DiagnosticSource ID to delete.

    Returns:
        List of TextContent with deletion confirmation or error.
    """
    try:
        source = await client.get(f"/setting/diagnosticsources/{diagnosticsource_id}")
        source_name = source.get("name", f"ID:{diagnosticsource_id}")

        await client.delete(f"/setting/diagnosticsources/{diagnosticsource_id}")

        return format_response(
            {
                "success": True,
                "message": f"DiagnosticSource '{source_name}' deleted",
                "diagnosticsource_id": diagnosticsource_id,
            }
        )
    except Exception as e:
        return handle_error(e)
