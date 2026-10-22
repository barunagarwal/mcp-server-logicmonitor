# Description: Remediation source tools for LogicMonitor MCP server.
# Description: Provides read, execution, and history access for remediation sources.

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from mcp.types import TextContent

from lm_mcp.tools import (
    WILDCARD_STRIP_NOTE,
    format_response,
    handle_error,
    normalize_definition_fields,
    quote_filter_value,
    require_write_permission,
    safe_total,
    sanitize_filter_value,
)
from lm_mcp.tools.diagnostic_remediation import run_pre_execution_checks

if TYPE_CHECKING:
    from lm_mcp.client import LogicMonitorClient

logger = logging.getLogger(__name__)


async def get_remediationsources(
    client: LogicMonitorClient,
    name_filter: str | None = None,
    group_filter: str | None = None,
    filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[TextContent]:
    """List RemediationSources from LogicMonitor.

    Calls the public REST endpoint ``/setting/remediationsources``. Filters
    and pagination are pushed down to the server. Mirrors :func:`get_datasources`
    so consumers get the same shape across every LogicModule resource family.

    Args:
        client: LogicMonitor API client.
        name_filter: Filter by RemediationSource name (substring, server-side).
        group_filter: Filter by group (substring, server-side).
        filter: Raw LM filter expression (overrides typed filters).
        limit: Maximum sources to return per page.
        offset: Number of results to skip for pagination.

    Returns:
        List of TextContent with RemediationSource data or error.
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

        result = await client.get("/setting/remediationsources", params=params)

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

        total = safe_total(result)
        has_more = (offset + len(sources)) < total

        response = {
            "total": total,
            "count": len(sources),
            "offset": offset,
            "has_more": has_more,
            "remediationsources": sources,
        }
        if wildcards_stripped:
            response["note"] = WILDCARD_STRIP_NOTE
        return format_response(response)
    except Exception as e:
        return handle_error(e)


async def get_remediationsource(
    client: LogicMonitorClient,
    source_id: int,
) -> list[TextContent]:
    """Get details for a specific RemediationSource.

    Calls ``/setting/remediationsources/{id}`` and projects the fields most
    useful to callers (metadata + script content). The same endpoint is
    already exercised by ``execute_remediation`` for pre-flight checks.

    Args:
        client: LogicMonitor API client.
        source_id: RemediationSource ID.

    Returns:
        List of TextContent with source details or error.
    """
    try:
        result = await client.get(f"/setting/remediationsources/{source_id}")

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
            "groovy_script": result.get("groovyScript"),
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
async def execute_remediation(
    client: LogicMonitorClient,
    host_id: int,
    remediation_source_id: int,
    alert_id: str | None = None,
) -> list[TextContent]:
    """Execute a RemediationSource script on a target device.

    Performs an 8-point pre-execution checklist before running:
    1. Collector version >= 39.200
    2. Device reachable (not dead)
    3. Write permission (enforced by decorator)
    4. Audit logging (handled by server middleware)
    5. AppliesTo script included for review
    6. Concurrency warning
    7. Script preview
    8. State mutation warning for dangerous keywords

    Args:
        client: LogicMonitor API client.
        host_id: Device/host ID to execute on.
        remediation_source_id: Remediation source ID to execute.
        alert_id: Optional alert ID to associate with the execution.

    Returns:
        Execution result with pre-check details and warnings.
    """
    try:
        error, checks = await run_pre_execution_checks(
            client, host_id, remediation_source_id, source_kind="remediation"
        )
        if error:
            return format_response(error)

        # Execute the remediation
        payload: dict = {
            "hostId": host_id,
            "remediationId": remediation_source_id,
            "triggerType": "manual",
        }
        if alert_id:
            payload["alertId"] = alert_id

        exec_result = await client.post(
            "/setting/remediationsources/executemanually",
            json_body=payload,
        )

        # Build response
        response = {
            "success": True,
            "message": "Remediation execution initiated",
            "host_id": host_id,
            "remediation_source_id": remediation_source_id,
            "alert_id": alert_id,
            "collector_version": checks["collector_version"],
            "applies_to": checks["applies_to"],
            "script_preview": checks["script_preview"],
            "execution_response": exec_result,
            "warnings": checks["warnings"],
            "important_notes": [
                "Cannot pause or cancel once execution starts.",
                "Success does not guarantee resolution -- verify independently.",
            ],
        }

        if checks["mutation_warning"]:
            response["mutation_warning"] = checks["mutation_warning"]

        # Concurrency warning
        response["concurrency_note"] = (
            "Concurrent executions not prevented. "
            "Verify no execution is in progress on this device."
        )

        return format_response(response)
    except Exception as e:
        return handle_error(e)


@require_write_permission
async def create_remediationsource(
    client: LogicMonitorClient,
    definition: dict,
    overwrite: bool = False,
) -> list[TextContent]:
    """Create a RemediationSource via REST API using a full definition dict.

    Accepts REST API format (same format returned by export_remediationsource).
    There is no LM Exchange import endpoint for RemediationSources; this is
    the only programmatic creation path.

    Args:
        client: LogicMonitor API client.
        definition: Full RemediationSource definition dict in REST API format.
        overwrite: If True, delete existing RemediationSource with the same
            name before creating.

    Returns:
        List of TextContent with created RemediationSource info or error.
    """
    try:
        payload = normalize_definition_fields(definition)
        payload.pop("id", None)

        if overwrite and payload.get("name"):
            existing = await client.get(
                "/setting/remediationsources",
                params={"filter": f"name:{quote_filter_value(payload['name'])}", "size": 1},
            )
            items = existing.get("items", [])
            if items:
                await client.delete(f"/setting/remediationsources/{items[0]['id']}")

        result = await client.post("/setting/remediationsources", json_body=payload)

        return format_response(
            {
                "success": True,
                "message": f"RemediationSource '{result.get('name')}' created successfully",
                "remediationsource": {
                    "id": result.get("id"),
                    "name": result.get("name"),
                    "display_name": result.get("displayName"),
                },
            }
        )
    except Exception as e:
        return handle_error(e)


@require_write_permission
async def update_remediationsource(
    client: LogicMonitorClient,
    remediationsource_id: int,
    definition: dict,
    confirm: bool = False,
) -> list[TextContent]:
    """Update an existing RemediationSource via REST API (full replace).

    The LM API uses full-replace semantics: every field not included in the
    definition will be blanked, including the Groovy script. PREFER
    update_logicmodule(type='remediationsource', ...) for partial updates;
    it exports, deep-merges, and previews a diff before writing.

    Args:
        client: LogicMonitor API client.
        remediationsource_id: RemediationSource ID to update.
        definition: Full RemediationSource definition dict with all fields.
        confirm: Must be True to proceed. Defaults to False to prevent
            accidental field-blanking via partial payloads.

    Returns:
        List of TextContent with updated RemediationSource info or error.
    """
    if not confirm:
        return format_response(
            {
                "error": True,
                "code": "CONFIRMATION_REQUIRED",
                "message": (
                    "update_remediationsource is full-replace -- any field omitted "
                    "from `definition` will be BLANKED, including the script. Set "
                    "confirm=true to proceed, OR use update_logicmodule"
                    "(type='remediationsource', id, changes, mode='preview') for a "
                    "safe partial update with diff preview."
                ),
            }
        )
    try:
        payload = normalize_definition_fields(definition)
        payload.pop("id", None)

        result = await client.put(
            f"/setting/remediationsources/{remediationsource_id}", json_body=payload
        )

        return format_response(
            {
                "success": True,
                "message": f"RemediationSource '{result.get('name')}' updated successfully",
                "remediationsource": {
                    "id": result.get("id"),
                    "name": result.get("name"),
                    "display_name": result.get("displayName"),
                },
            }
        )
    except Exception as e:
        return handle_error(e)


@require_write_permission
async def delete_remediationsource(
    client: LogicMonitorClient,
    remediationsource_id: int,
) -> list[TextContent]:
    """Delete a RemediationSource from LogicMonitor.

    WARNING: This removes the RemediationSource definition; any action chains
    referencing it as a stage will lose that stage.

    Args:
        client: LogicMonitor API client.
        remediationsource_id: RemediationSource ID to delete.

    Returns:
        List of TextContent with deletion confirmation or error.
    """
    try:
        source = await client.get(f"/setting/remediationsources/{remediationsource_id}")
        source_name = source.get("name", f"ID:{remediationsource_id}")

        await client.delete(f"/setting/remediationsources/{remediationsource_id}")

        return format_response(
            {
                "success": True,
                "message": f"RemediationSource '{source_name}' deleted",
                "remediationsource_id": remediationsource_id,
            }
        )
    except Exception as e:
        return handle_error(e)
