# Description: Automated Diagnostics & Remediation (ADR) composite tools.
# Description: Lists assigned ADR sources and structured execution results.

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp.types import TextContent

from lm_mcp.tools import format_response, handle_error, safe_total

# The v3 API returns hostStatus as a word ("dead"); older payloads used 1. Accept both.
_DEAD_HOST_STATUS = {1, "1", "dead"}


def is_dead_host_status(value: object) -> bool:
    """True when a device's hostStatus says it is dead, in either the word or numeric form."""
    if isinstance(value, str):
        value = value.strip().lower()
    return value in _DEAD_HOST_STATUS


if TYPE_CHECKING:
    from lm_mcp.client import LogicMonitorClient

# Individual script outputs are capped so one verbose run cannot flood the
# response; the full output remains available in the portal UI.
_OUTPUT_CHAR_LIMIT = 10000

# ADR manual execution requires this collector build or newer.
_MIN_COLLECTOR_BUILD = 39.200

_MUTATION_KEYWORDS = [
    "restart",
    "rm ",
    "rm\t",
    "delete",
    "stop",
    "kill",
    "reboot",
    "shutdown",
]

_SOURCE_PATHS = {
    "diagnostic": "/setting/diagnosticsources",
    "remediation": "/setting/remediationsources",
}


async def run_pre_execution_checks(
    client: LogicMonitorClient,
    host_id: int,
    source_id: int,
    source_kind: str,
) -> tuple[dict | None, dict]:
    """Run the shared ADR pre-execution checklist for manual executions.

    Shared by execute_remediation and execute_diagnostic: verifies the
    device is reachable, the collector build supports ADR execution, and
    surfaces the source's appliesTo, a script preview, and a warning for
    state-mutating keywords.

    Args:
        client: LogicMonitor API client.
        host_id: Target device/host ID.
        source_id: DiagnosticSource or RemediationSource ID.
        source_kind: "diagnostic" or "remediation" (selects the settings
            path and error wording).

    Returns:
        Tuple of (error, context). When error is not None the caller must
        return it via format_response without executing. Context carries
        warnings, collector_version, applies_to, script_preview, and
        mutation_warning.
    """
    context: dict = {
        "warnings": [],
        "collector_version": "unknown",
        "applies_to": "",
        "script_preview": "",
        "mutation_warning": None,
    }

    # Check: device reachable
    device = await client.get(f"/device/devices/{host_id}")
    if is_dead_host_status(device.get("hostStatus")):
        return (
            {
                "error": True,
                "code": "DEVICE_UNREACHABLE",
                "message": (
                    f"Device {host_id} is dead (hostStatus={device.get('hostStatus')}). "
                    f"Cannot execute {source_kind}."
                ),
                "suggestion": f"Verify device connectivity before executing {source_kind}.",
            },
            context,
        )

    # Check: collector build version
    collector_id = device.get("preferredCollectorId")
    if collector_id:
        try:
            collector = await client.get(f"/setting/collector/collectors/{collector_id}")
            build = collector.get("build", "0")
            context["collector_version"] = str(build)
            try:
                version_num = float(str(build).replace(",", ""))
                if version_num < _MIN_COLLECTOR_BUILD:
                    return (
                        {
                            "error": True,
                            "code": "COLLECTOR_VERSION_LOW",
                            "message": (
                                f"Collector {collector_id} build {build} is below "
                                f"minimum {_MIN_COLLECTOR_BUILD:.3f} required for "
                                f"{source_kind} execution."
                            ),
                            "suggestion": (
                                f"Upgrade the collector before executing {source_kind}."
                            ),
                        },
                        context,
                    )
            except (ValueError, TypeError):
                context["warnings"].append(
                    f"Could not parse collector build version '{build}'. Proceeding with caution."
                )
        except Exception:
            context["warnings"].append(
                f"Could not verify collector {collector_id} version. Proceeding with caution."
            )

    # Review: appliesTo, script preview, state-mutation keywords
    try:
        source = await client.get(f"{_SOURCE_PATHS[source_kind]}/{source_id}")
        context["applies_to"] = source.get("appliesTo", source.get("appliesToScript", ""))
        script_content = source.get("groovyScript", source.get("script", ""))

        if script_content:
            preview = script_content[:500]
            if len(script_content) > 500:
                preview += "... [truncated]"
            context["script_preview"] = preview

            found_keywords = [
                kw.strip() for kw in _MUTATION_KEYWORDS if kw.lower() in script_content.lower()
            ]
            if found_keywords:
                context["mutation_warning"] = (
                    f"This script performs state-mutating operations: "
                    f"{', '.join(found_keywords)}. "
                    "Review carefully before proceeding."
                )
    except Exception:
        context["warnings"].append(
            f"Could not retrieve {source_kind} source details for pre-checks. "
            "Proceeding with execution."
        )

    return None, context


async def get_diagnostic_remediation_assignments(
    client: LogicMonitorClient,
    resource_id: int | None = None,
    alert_id: str | None = None,
    module_type: str | None = None,
    limit: int = 50,
) -> list[TextContent]:
    """List diagnostic/remediation sources assigned to a resource or alert.

    Wraps GET /setting/diagnosticRemediation/list. The API requires a
    resource id or an alert id (or both) and resolves which ADR modules
    actually apply to that target, unlike get_diagnosticsources /
    get_remediationsources which list portal-wide module definitions.

    Args:
        client: LogicMonitor API client.
        resource_id: Device/resource ID to list assigned sources for.
        alert_id: Alert ID to list assigned sources for.
        module_type: Restrict to one type (diagnosticsource or
            remediationsource); both when omitted.
        limit: Maximum number of sources to return.

    Returns:
        List of TextContent with assigned ADR sources or error.
    """
    if resource_id is None and alert_id is None:
        return format_response(
            {
                "error": True,
                "code": "VALIDATION_ERROR",
                "message": "Provide resource_id or alert_id (or both).",
            }
        )
    try:
        params: dict = {}
        if resource_id is not None:
            params["resourceId"] = resource_id
        if alert_id is not None:
            params["alertId"] = alert_id
        if module_type:
            params["moduleType"] = module_type

        result = await client.get("/setting/diagnosticRemediation/list", params=params)

        sources = []
        for item in result.get("items", [])[:limit]:
            sources.append(
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "description": item.get("description"),
                    "applies_to": item.get("appliesTo"),
                    "type": item.get("type"),
                    "group": item.get("group"),
                }
            )

        return format_response(
            {
                "total": safe_total(result),
                "count": len(sources),
                "assigned_sources": sources,
            }
        )
    except Exception as e:
        return handle_error(e)


async def get_diagnostic_remediation_results(
    client: LogicMonitorClient,
    alert_id: str | None = None,
    host_id: int | None = None,
    module_type: str = "both",
    diagnostic_source_id: int | None = None,
    diagnostic_source_name: str | None = None,
    remediation_source_id: int | None = None,
    remediation_source_name: str | None = None,
    start_time_ms: int | None = None,
    end_time_ms: int | None = None,
    limit: int = 50,
    offset: int = 0,
    cursor: str | None = None,
    remediation_cursor: str | None = None,
) -> list[TextContent]:
    """Get structured ADR execution results (status, output, timing).

    Wraps GET /setting/diagnosticRemediation/executionResults. Provide
    exactly one of alert_id or host_id. Alert mode without a time window
    returns the latest execution in the alert window; with start/end
    times it returns windowed history. The request window is in epoch
    MILLISECONDS while result timestamps are epoch SECONDS. Cursors are
    not supported when module_type is "both".

    Args:
        client: LogicMonitor API client.
        alert_id: Alert ID (exactly one of alert_id/host_id).
        host_id: Device/host ID (exactly one of alert_id/host_id).
        module_type: diagnostic, remediation, or both.
        diagnostic_source_id: Filter to one DiagnosticSource by ID.
        diagnostic_source_name: Filter to one DiagnosticSource by name.
        remediation_source_id: Filter to one RemediationSource by ID.
        remediation_source_name: Filter to one RemediationSource by name.
        start_time_ms: Window start, epoch milliseconds.
        end_time_ms: Window end, epoch milliseconds.
        limit: Maximum results per page.
        offset: Page offset.
        cursor: Diagnostic-side cursor from a previous response.
        remediation_cursor: Remediation-side cursor from a previous response.

    Returns:
        List of TextContent with execution results or error.
    """
    if (alert_id is None) == (host_id is None):
        return format_response(
            {
                "error": True,
                "code": "VALIDATION_ERROR",
                "message": "Provide exactly one of alert_id or host_id.",
            }
        )
    if module_type == "both" and (cursor or remediation_cursor):
        return format_response(
            {
                "error": True,
                "code": "VALIDATION_ERROR",
                "message": (
                    'Cursors are not supported when module_type is "both"; '
                    "set module_type to diagnostic or remediation to use cursors."
                ),
            }
        )
    try:
        params: dict = {
            "moduleType": module_type,
            "perPageCount": limit,
            "pageOffsetCount": offset,
        }
        if alert_id is not None:
            params["alertId"] = alert_id
        if host_id is not None:
            params["hostId"] = host_id
        if diagnostic_source_id is not None:
            params["diagnosticSourceId"] = diagnostic_source_id
        if diagnostic_source_name:
            params["diagnosticSourceName"] = diagnostic_source_name
        if remediation_source_id is not None:
            params["remediationSourceId"] = remediation_source_id
        if remediation_source_name:
            params["remediationSourceName"] = remediation_source_name
        if start_time_ms is not None:
            params["startTimeMs"] = start_time_ms
        if end_time_ms is not None:
            params["endTimeMs"] = end_time_ms
        if cursor:
            params["cursor"] = cursor
        if remediation_cursor:
            params["remediationCursor"] = remediation_cursor

        result = await client.get("/setting/diagnosticRemediation/executionResults", params=params)

        executions = []
        for item in result.get("items", []):
            output = item.get("output")
            output_truncated = False
            if isinstance(output, str) and len(output) > _OUTPUT_CHAR_LIMIT:
                output = output[:_OUTPUT_CHAR_LIMIT]
                output_truncated = True
            execution = {
                "execution_id": item.get("executionId"),
                "source_type": item.get("sourceType"),
                "diagnostic_source_id": item.get("diagnosticSourceId"),
                "remediation_source_id": item.get("remediationSourceId"),
                "module_name": item.get("moduleName"),
                "host_id": item.get("hostId"),
                "alert_id": item.get("alertId"),
                "status": item.get("executionStatus"),
                "triggered_type": item.get("triggeredType"),
                "executed_by": item.get("executedBy"),
                "output": output,
                "start_time_epoch": item.get("startTime"),
                "end_time_epoch": item.get("endTime"),
            }
            if output_truncated:
                execution["output_truncated"] = True
            executions.append(execution)

        response: dict = {
            "total": safe_total(result),
            "count": len(executions),
            "executions": executions,
        }
        if result.get("sort"):
            response["sort"] = result.get("sort")
        if result.get("cursor"):
            response["cursor"] = result.get("cursor")
        if result.get("remediationCursor"):
            response["remediation_cursor"] = result.get("remediationCursor")
        return format_response(response)
    except Exception as e:
        return handle_error(e)
