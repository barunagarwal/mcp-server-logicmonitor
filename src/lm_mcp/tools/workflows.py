# Description: Composite workflow tools for LogicMonitor MCP server.
# Description: Provides triage, diagnose, capacity_plan, portal_overview, update_logicmodule.

from __future__ import annotations

import logging
import re
from fnmatch import fnmatch
from typing import TYPE_CHECKING

from mcp.types import TextContent

from lm_mcp.tools import call_sub_tool, format_response, handle_error

# Audit logger for write workflows. Configured via standard logging; if no
# handler is attached, records propagate to the root logger.
_AUDIT = logging.getLogger("lm_mcp.audit")

if TYPE_CHECKING:
    from lm_mcp.client import LogicMonitorClient


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------


def check_required_tools(required: list[str]) -> list[TextContent] | None:
    """Check all sub-tools pass LM_ENABLED_TOOLS, LM_DISABLED_TOOLS, and LM_MCP_CATEGORIES.

    Returns None if OK, error TextContent list if any tool is blocked.
    """
    from lm_mcp.config import get_config

    config = get_config()
    blocked: list[str] = []

    if config.enabled_tools:
        patterns = [p.strip() for p in config.enabled_tools.split(",") if p.strip()]
        blocked = [t for t in required if not any(fnmatch(t, p) for p in patterns)]
    elif config.disabled_tools:
        patterns = [p.strip() for p in config.disabled_tools.split(",") if p.strip()]
        blocked = [t for t in required if any(fnmatch(t, p) for p in patterns)]

    if not blocked and config.mcp_categories:
        from lm_mcp.categories import tool_in_categories
        from lm_mcp.registry import AWX_TOOLS, TF_TOOLS, TOOLS, WATSONX_TOOLS

        tools_index = {t.name: t for t in TOOLS}
        tools_index.update({t.name: t for t in AWX_TOOLS})
        tools_index.update({t.name: t for t in WATSONX_TOOLS})
        tools_index.update({t.name: t for t in TF_TOOLS})
        blocked = [
            t for t in required if not tool_in_categories(t, tools_index, config.mcp_categories)
        ]
        if blocked:
            return format_response(
                {
                    "error": True,
                    "code": "REQUIRED_TOOLS_FILTERED_BY_CATEGORY",
                    "message": (
                        f"Composite tool requires tools excluded by LM_MCP_CATEGORIES="
                        f"{config.mcp_categories}: {', '.join(blocked)}"
                    ),
                    "suggestion": (
                        "Add the required category (e.g., 'read') to LM_MCP_CATEGORIES, "
                        "or unset it to allow all categories."
                    ),
                }
            )

    if blocked:
        return format_response(
            {
                "error": True,
                "code": "REQUIRED_TOOLS_DISABLED",
                "message": f"Composite tool requires disabled tools: {', '.join(blocked)}",
                "suggestion": "Enable these tools or use individual tools instead",
            }
        )
    return None


async def _resolve_device(
    client: LogicMonitorClient,
    device_id: int | None = None,
    device_name: str | None = None,
) -> tuple[int, dict]:
    """Resolve device by ID or name search. Returns (id, device_dict)."""
    from lm_mcp.tools.devices import get_device, get_devices

    if device_id is not None:
        data = await call_sub_tool(get_device, client, device_id=device_id)
        return device_id, data
    if device_name:
        data = await call_sub_tool(
            get_devices,
            client,
            name_filter=device_name,
            limit=1,
        )
        devices = data.get("devices", [])
        if not devices:
            raise ValueError(f"No device found matching name '{device_name}'")
        dev = devices[0]
        return dev["id"], dev
    raise ValueError("Either device_id or device_name is required")


def _trim_detail(report: dict, detail_level: str, full_keys: set[str]) -> dict:
    """Remove full_keys from report when detail_level is 'summary'."""
    if detail_level == "summary":
        return {k: v for k, v in report.items() if k not in full_keys}
    return report


async def _maybe_summarize(
    report: dict,
    workflow_name: str,
    summarize: bool,
    warnings: list[str],
) -> None:
    """Optionally append NL summary to a workflow report via watsonx.

    Does nothing if summarize is False. When no summary model is configured, or
    the summary call fails, appends a warning and attaches the warnings list to
    the report, so the warning is returned even if it is the only one.
    """
    if not summarize:
        return

    try:
        from lm_mcp.server import get_watsonx_client
        from lm_mcp.tools.watsonx import nl_summarize_helper

        wx = get_watsonx_client()
        if wx is None:
            warnings.append(
                "NL summary requested but not configured: set WATSONX_API_KEY or "
                "install the HuggingFace fallback"
            )
            report["warnings"] = warnings
            return

        summary = await nl_summarize_helper(wx, report, workflow_name)
        report["nl_summary"] = summary
    except Exception as exc:
        _AUDIT.warning("%s: NL summary failed: %s", workflow_name, exc, exc_info=True)
        warnings.append(f"NL summary failed: {exc}")
        report["warnings"] = warnings


# ---------------------------------------------------------------------------
# Composite tool: triage
# ---------------------------------------------------------------------------

_TRIAGE_REQUIRED = [
    "get_alerts",
    "get_alert_statistics",
    "correlate_alerts",
    "score_alert_noise",
    "analyze_blast_radius",
    "correlate_changes",
]


async def triage(
    client: LogicMonitorClient,
    severity: str | None = None,
    device: str | None = None,
    group_id: int | None = None,
    hours_back: int = 4,
    detail_level: str = "summary",
    summarize: bool = False,
) -> list[TextContent]:
    """Composite triage: correlate, cluster, score, and assess alerts.

    Fetches active alerts, builds time-bucketed statistics, clusters
    related alerts, scores noise, analyzes blast radius for critical
    clusters, and cross-references recent changes.

    Args:
        client: LogicMonitor API client.
        severity: Filter alerts by severity.
        device: Filter by device name.
        group_id: Filter by device group ID.
        hours_back: Hours to look back (default: 4).
        detail_level: 'summary' or 'full' (default: summary).

    Returns:
        Prioritized incident report as TextContent list.
    """
    blocked = check_required_tools(_TRIAGE_REQUIRED)
    if blocked:
        return blocked

    try:
        from lm_mcp.tools.correlation import correlate_alerts, get_alert_statistics
        from lm_mcp.tools.event_correlation import correlate_changes
        from lm_mcp.tools.scoring import score_alert_noise
        from lm_mcp.tools.topology_analysis import analyze_blast_radius

        warnings: list[str] = []
        report: dict = {"hours_back": hours_back, "detail_level": detail_level}

        # 1. Get alert statistics
        try:
            stats = await call_sub_tool(
                get_alert_statistics,
                client,
                hours_back=hours_back,
                device=device,
                group_id=group_id,
            )
            report["statistics"] = stats
        except Exception as exc:
            warnings.append(f"get_alert_statistics failed: {exc}")
            report["statistics"] = None

        # 2. Correlate alerts (clusters)
        clusters_data: dict = {}
        try:
            clusters_data = await call_sub_tool(
                correlate_alerts,
                client,
                hours_back=hours_back,
                severity=severity,
                device=device,
                group_id=group_id,
            )
            report["clusters"] = clusters_data
        except Exception as exc:
            warnings.append(f"correlate_alerts failed: {exc}")
            report["clusters"] = None

        # 3. Score alert noise
        try:
            noise = await call_sub_tool(
                score_alert_noise,
                client,
                hours_back=hours_back,
                device=device,
                group_id=group_id,
            )
            report["noise"] = noise
        except Exception as exc:
            warnings.append(f"score_alert_noise failed: {exc}")
            report["noise"] = None

        # 4. Blast radius for critical clusters (up to 3 devices)
        blast_results: list[dict] = []
        clusters = clusters_data.get("clusters", []) if clusters_data else []
        device_clusters = [c for c in clusters if c.get("type") == "device"]
        for cluster in device_clusters[:3]:
            device_key = cluster.get("key", "")
            # Resolve device name to ID via search
            try:
                from lm_mcp.tools.devices import get_devices

                dev_data = await call_sub_tool(
                    get_devices,
                    client,
                    name_filter=device_key,
                    limit=1,
                )
                devs = dev_data.get("devices", [])
                if devs:
                    br = await call_sub_tool(
                        analyze_blast_radius,
                        client,
                        device_id=devs[0]["id"],
                    )
                    blast_results.append(
                        {
                            "device": device_key,
                            "blast_radius": br,
                        }
                    )
            except Exception as exc:
                _AUDIT.warning(
                    "triage: blast radius failed for %s: %s", device_key, exc, exc_info=True
                )
                warnings.append(f"blast_radius for {device_key} failed: {exc}")
        report["blast_radius"] = blast_results

        # 5. Correlate changes
        try:
            changes = await call_sub_tool(
                correlate_changes,
                client,
                hours_back=hours_back,
            )
            report["changes"] = changes
        except Exception as exc:
            warnings.append(f"correlate_changes failed: {exc}")
            report["changes"] = None

        if warnings:
            report["warnings"] = warnings

        # Trim for summary mode
        full_keys = {
            "blast_radius",
        }
        report = _trim_detail(report, detail_level, full_keys)
        await _maybe_summarize(report, "triage", summarize, warnings)

        return format_response(report)
    except Exception as e:
        return handle_error(e)


# ---------------------------------------------------------------------------
# Composite tool: health_check
# ---------------------------------------------------------------------------

_HEALTH_CHECK_REQUIRED = [
    "get_devices",
    "get_device",
    "get_device_datasources",
    "get_device_instances",
    "score_device_health",
    "get_metric_anomalies",
    "get_alerts",
    "calculate_availability",
]


async def health_check(
    client: LogicMonitorClient,
    device_id: int | None = None,
    device_name: str | None = None,
    summarize: bool = False,
    detail_level: str = "summary",
) -> list[TextContent]:
    """Composite health check for a single device.

    Resolves the device, gathers datasource coverage, scores health,
    detects anomalies, checks active alerts, and calculates availability.

    Args:
        client: LogicMonitor API client.
        device_id: Device ID.
        device_name: Device display name (used if device_id not provided).
        detail_level: 'summary' or 'full' (default: summary).

    Returns:
        Device health report as TextContent list.
    """
    blocked = check_required_tools(_HEALTH_CHECK_REQUIRED)
    if blocked:
        return blocked

    try:
        from lm_mcp.tools.alerts import get_alerts
        from lm_mcp.tools.correlation import get_metric_anomalies
        from lm_mcp.tools.metrics import get_device_datasources, get_device_instances
        from lm_mcp.tools.scoring import calculate_availability, score_device_health

        warnings: list[str] = []

        # 1. Resolve device
        resolved_id, device_info = await _resolve_device(
            client,
            device_id=device_id,
            device_name=device_name,
        )
        report: dict = {
            "device_id": resolved_id,
            "device_name": device_info.get("displayName", device_info.get("name", "")),
            "detail_level": detail_level,
        }

        # 2. Get datasources
        ds_list: list[dict] = []
        try:
            ds_data = await call_sub_tool(
                get_device_datasources,
                client,
                device_id=resolved_id,
            )
            ds_list = ds_data.get("datasources", [])
            report["datasource_count"] = len(ds_list)
        except Exception as exc:
            warnings.append(f"get_device_datasources failed: {exc}")
            report["datasource_count"] = 0

        # 3. Score health for first 5 datasources (skip those with no instances)
        health_scores: list[dict] = []
        primary_ds_id: int | None = None
        primary_instance_id: int | None = None

        for ds in ds_list[:5]:
            ds_id = ds.get("id")
            if ds_id is None:
                continue
            try:
                inst_data = await call_sub_tool(
                    get_device_instances,
                    client,
                    device_id=resolved_id,
                    device_datasource_id=ds_id,
                )
                instances = inst_data.get("instances", [])
                if not instances:
                    continue

                inst_id = instances[0].get("id")
                if primary_ds_id is None and inst_id is not None:
                    primary_ds_id = ds_id
                    primary_instance_id = inst_id

                try:
                    score = await call_sub_tool(
                        score_device_health,
                        client,
                        device_id=resolved_id,
                        device_datasource_id=ds_id,
                        instance_id=inst_id,
                    )
                    health_scores.append(
                        {
                            "datasource": ds.get("name", ""),
                            "score": score,
                        }
                    )
                except Exception as exc:
                    _AUDIT.warning(
                        "health: score failed for datasource %s: %s",
                        ds.get("name", ds_id),
                        exc,
                        exc_info=True,
                    )
                    warnings.append(
                        f"score_device_health for {ds.get('name', ds_id)} failed: {exc}"
                    )
            except Exception as exc:
                _AUDIT.warning("health: datasource processing failed: %s", exc, exc_info=True)
                warnings.append(f"datasource processing failed: {exc}")
                continue

        report["health_scores"] = health_scores

        # 4. Metric anomalies for primary datasource
        if primary_ds_id is not None and primary_instance_id is not None:
            try:
                anomalies = await call_sub_tool(
                    get_metric_anomalies,
                    client,
                    device_id=resolved_id,
                    device_datasource_id=primary_ds_id,
                    instance_id=primary_instance_id,
                )
                report["anomalies"] = anomalies
            except Exception as exc:
                warnings.append(f"get_metric_anomalies failed: {exc}")
        else:
            report["anomalies"] = None

        # 5. Active alerts for the device
        try:
            device_display = report["device_name"]
            alert_data = await call_sub_tool(
                get_alerts,
                client,
                device=device_display,
                cleared=False,
            )
            report["active_alerts"] = alert_data
        except Exception as exc:
            warnings.append(f"get_alerts failed: {exc}")
            report["active_alerts"] = None

        # 6. Availability (30-day)
        try:
            avail = await call_sub_tool(
                calculate_availability,
                client,
                device_id=resolved_id,
            )
            report["availability"] = avail
        except Exception as exc:
            warnings.append(f"calculate_availability failed: {exc}")
            report["availability"] = None

        if warnings:
            report["warnings"] = warnings

        full_keys = {"anomalies", "health_scores"}
        report = _trim_detail(report, detail_level, full_keys)
        await _maybe_summarize(report, "health_check", summarize, warnings)

        return format_response(report)
    except Exception as e:
        return handle_error(e)


# ---------------------------------------------------------------------------
# Composite tool: capacity_plan
# ---------------------------------------------------------------------------

_CAPACITY_PLAN_REQUIRED = [
    "get_devices",
    "get_device",
    "get_device_datasources",
    "forecast_metric",
    "classify_trend",
    "detect_seasonality",
    "detect_change_points",
]


async def capacity_plan(
    client: LogicMonitorClient,
    device_id: int | None = None,
    device_name: str | None = None,
    datasource: str | None = None,
    hours_back: int = 168,
    detail_level: str = "summary",
    summarize: bool = False,
) -> list[TextContent]:
    """Composite capacity planning for a device.

    Forecasts metric breach dates, classifies trends, detects seasonality
    and change points across datasources and instances.

    Args:
        client: LogicMonitor API client.
        device_id: Device ID.
        device_name: Device display name (used if device_id not provided).
        datasource: Filter to a specific datasource name.
        hours_back: Hours of historical data (default: 168 = 1 week).
        detail_level: 'summary' or 'full' (default: summary).

    Returns:
        Per-datasource capacity projections as TextContent list.
    """
    blocked = check_required_tools(_CAPACITY_PLAN_REQUIRED)
    if blocked:
        return blocked

    try:
        from lm_mcp.tools.forecasting import (
            classify_trend,
            detect_change_points,
            detect_seasonality,
            forecast_metric,
        )
        from lm_mcp.tools.metrics import get_device_datasources, get_device_instances

        warnings: list[str] = []

        # 1. Resolve device
        resolved_id, device_info = await _resolve_device(
            client,
            device_id=device_id,
            device_name=device_name,
        )
        report: dict = {
            "device_id": resolved_id,
            "device_name": device_info.get("displayName", device_info.get("name", "")),
            "hours_back": hours_back,
            "detail_level": detail_level,
        }

        # 2. Get datasources (filtered if datasource param given)
        try:
            ds_data = await call_sub_tool(
                get_device_datasources,
                client,
                device_id=resolved_id,
                name_filter=datasource,
            )
            ds_list = ds_data.get("datasources", [])
        except Exception as exc:
            warnings.append(f"get_device_datasources failed: {exc}")
            ds_list = []

        # 3. Per datasource (up to 5), per instance (up to 3): forecast + trend
        ds_reports: list[dict] = []
        for ds in ds_list[:5]:
            ds_id = ds.get("id")
            if ds_id is None:
                continue

            ds_report: dict = {"datasource": ds.get("name", ""), "instances": []}

            try:
                inst_data = await call_sub_tool(
                    get_device_instances,
                    client,
                    device_id=resolved_id,
                    device_datasource_id=ds_id,
                )
                instances = inst_data.get("instances", [])
            except Exception as exc:
                _AUDIT.warning(
                    "capacity_plan: instance fetch failed for datasource %s: %s",
                    ds.get("name", ds_id),
                    exc,
                    exc_info=True,
                )
                warnings.append(f"instance fetch for {ds.get('name', ds_id)} failed: {exc}")
                instances = []

            for inst in instances[:3]:
                inst_id = inst.get("id")
                if inst_id is None:
                    continue

                inst_report: dict = {"instance": inst.get("name", "")}
                common_kwargs = {
                    "device_id": resolved_id,
                    "device_datasource_id": ds_id,
                    "instance_id": inst_id,
                    "hours_back": hours_back,
                }

                # Forecast (use threshold=90 as default capacity threshold)
                try:
                    fc = await call_sub_tool(
                        forecast_metric,
                        client,
                        threshold=90.0,
                        **common_kwargs,
                    )
                    inst_report["forecast"] = fc
                except Exception as exc:
                    _AUDIT.warning(
                        "capacity_plan: forecast failed for instance %s: %s",
                        inst_id,
                        exc,
                        exc_info=True,
                    )
                    inst_report["forecast"] = None
                    inst_report["forecast_error"] = str(exc)

                # Classify trend
                try:
                    trend = await call_sub_tool(
                        classify_trend,
                        client,
                        **common_kwargs,
                    )
                    inst_report["trend"] = trend
                except Exception as exc:
                    _AUDIT.warning(
                        "capacity_plan: trend failed for instance %s: %s",
                        inst_id,
                        exc,
                        exc_info=True,
                    )
                    inst_report["trend"] = None
                    inst_report["trend_error"] = str(exc)

                # Seasonality
                try:
                    season = await call_sub_tool(
                        detect_seasonality,
                        client,
                        **common_kwargs,
                    )
                    inst_report["seasonality"] = season
                except Exception as exc:
                    _AUDIT.warning(
                        "capacity_plan: seasonality failed for instance %s: %s",
                        inst_id,
                        exc,
                        exc_info=True,
                    )
                    inst_report["seasonality"] = None
                    inst_report["seasonality_error"] = str(exc)

                # Change points (only if volatile trend detected)
                is_volatile = False
                if inst_report.get("trend"):
                    classifications = inst_report["trend"].get("classifications", {})
                    for _dp, info in classifications.items():
                        if info.get("classification") == "volatile":
                            is_volatile = True
                            break

                if is_volatile:
                    try:
                        cps = await call_sub_tool(
                            detect_change_points,
                            client,
                            **common_kwargs,
                        )
                        inst_report["change_points"] = cps
                    except Exception as exc:
                        _AUDIT.warning(
                            "capacity_plan: change points failed for instance %s: %s",
                            inst_id,
                            exc,
                            exc_info=True,
                        )
                        inst_report["change_points"] = None
                        inst_report["change_points_error"] = str(exc)

                ds_report["instances"].append(inst_report)

            ds_reports.append(ds_report)

        report["datasources"] = ds_reports

        # The summary level trims the raw datasources block, so it keeps each
        # forecast's headline and every per-instance error in its place.
        if detail_level == "summary":
            report["forecast_summary"] = _forecast_summary(ds_reports)
            warnings.extend(_instance_errors(ds_reports))

        if warnings:
            report["warnings"] = warnings

        full_keys = {"datasources"}
        report = _trim_detail(report, detail_level, full_keys)
        await _maybe_summarize(report, "capacity_plan", summarize, warnings)

        return format_response(report)
    except Exception as e:
        return handle_error(e)


# Per-instance error keys capacity_plan records, one per analysis.
_INSTANCE_ERROR_KEYS = ("forecast_error", "trend_error", "seasonality_error", "change_points_error")


def _forecast_summary(ds_reports: list[dict]) -> list[dict]:
    """One headline row per forecast datapoint: method, days to breach, trend.

    A datapoint the forecast could not run on carries its status instead.
    """
    rows: list[dict] = []
    for ds in ds_reports:
        for inst in ds["instances"]:
            forecasts = (inst.get("forecast") or {}).get("forecasts") or {}
            for datapoint, fc in forecasts.items():
                row = {
                    "datasource": ds["datasource"],
                    "instance": inst["instance"],
                    "datapoint": datapoint,
                }
                if "status" in fc:
                    row["status"] = fc["status"]
                else:
                    row["method"] = fc.get("method_used")
                    row["days_until_breach"] = fc.get("days_until_breach")
                    row["trend"] = fc.get("trend")
                    if fc.get("fallback_reason"):
                        row["fallback_reason"] = fc["fallback_reason"]
                rows.append(row)
    return rows


def _instance_errors(ds_reports: list[dict]) -> list[str]:
    """Every per-instance analysis error, as warning lines naming datasource and instance."""
    errors: list[str] = []
    for ds in ds_reports:
        for inst in ds["instances"]:
            for key in _INSTANCE_ERROR_KEYS:
                if key in inst:
                    analysis = key.removesuffix("_error")
                    errors.append(
                        f"{analysis} for {ds['datasource']}/{inst['instance']} failed: {inst[key]}"
                    )
    return errors


# ---------------------------------------------------------------------------
# Composite tool: portal_overview
# ---------------------------------------------------------------------------

_PORTAL_OVERVIEW_REQUIRED = [
    "get_alert_statistics",
    "get_alerts",
    "get_collectors",
    "get_active_sdts",
    "correlate_alerts",
    "score_alert_noise",
    "get_devices",
]


async def portal_overview(
    client: LogicMonitorClient,
    hours_back: int = 4,
    detail_level: str = "summary",
    summarize: bool = False,
) -> list[TextContent]:
    """Composite portal overview for shift-handoff reporting.

    Aggregates alert statistics, collector health, maintenance windows,
    noise scores, and dead/unmonitored devices.

    Args:
        client: LogicMonitor API client.
        hours_back: Hours to look back (default: 4).
        detail_level: 'summary' or 'full' (default: summary).

    Returns:
        Portal overview report as TextContent list.
    """
    blocked = check_required_tools(_PORTAL_OVERVIEW_REQUIRED)
    if blocked:
        return blocked

    try:
        from lm_mcp.tools.alerts import get_alerts
        from lm_mcp.tools.collectors import get_collectors
        from lm_mcp.tools.correlation import correlate_alerts, get_alert_statistics
        from lm_mcp.tools.devices import get_devices
        from lm_mcp.tools.scoring import score_alert_noise
        from lm_mcp.tools.sdts import get_active_sdts

        warnings: list[str] = []
        report: dict = {"hours_back": hours_back, "detail_level": detail_level}

        # 1. Alert statistics
        try:
            stats = await call_sub_tool(
                get_alert_statistics,
                client,
                hours_back=hours_back,
            )
            report["alert_statistics"] = stats
        except Exception as exc:
            warnings.append(f"get_alert_statistics failed: {exc}")
            report["alert_statistics"] = None

        # 2. High-severity active alerts (critical + error)
        try:
            crit_alerts = await call_sub_tool(
                get_alerts,
                client,
                severity="critical",
                cleared=False,
                limit=20,
            )
            err_alerts = await call_sub_tool(
                get_alerts,
                client,
                severity="error",
                cleared=False,
                limit=20,
            )
            report["critical_alerts"] = crit_alerts
            report["error_alerts"] = err_alerts
        except Exception as exc:
            warnings.append(f"get_alerts failed: {exc}")
            report["critical_alerts"] = None
            report["error_alerts"] = None

        # 3. Collector health
        try:
            coll_data = await call_sub_tool(get_collectors, client)
            report["collectors"] = coll_data
        except Exception as exc:
            warnings.append(f"get_collectors failed: {exc}")
            report["collectors"] = None

        # 4. Active SDTs
        try:
            sdt_data = await call_sub_tool(get_active_sdts, client)
            report["active_sdts"] = sdt_data
        except Exception as exc:
            warnings.append(f"get_active_sdts failed: {exc}")
            report["active_sdts"] = None

        # 5. Correlate alerts
        try:
            cluster_data = await call_sub_tool(
                correlate_alerts,
                client,
                hours_back=hours_back,
            )
            report["alert_clusters"] = cluster_data
        except Exception as exc:
            warnings.append(f"correlate_alerts failed: {exc}")
            report["alert_clusters"] = None

        # 6. Noise assessment
        try:
            noise = await call_sub_tool(
                score_alert_noise,
                client,
                hours_back=hours_back,
            )
            report["noise"] = noise
        except Exception as exc:
            warnings.append(f"score_alert_noise failed: {exc}")
            report["noise"] = None

        # 7. Dead/unmonitored devices
        try:
            dead = await call_sub_tool(get_devices, client, status="dead", limit=20)
            report["dead_devices"] = dead
        except Exception as exc:
            warnings.append(f"get_devices (dead) failed: {exc}")
            report["dead_devices"] = None

        if warnings:
            report["warnings"] = warnings

        full_keys = {"critical_alerts", "error_alerts", "dead_devices"}
        report = _trim_detail(report, detail_level, full_keys)
        await _maybe_summarize(report, "portal_overview", summarize, warnings)

        return format_response(report)
    except Exception as e:
        return handle_error(e)


# ---------------------------------------------------------------------------
# Composite tool: diagnose
# ---------------------------------------------------------------------------

_DIAGNOSE_REQUIRED = [
    "get_alerts",
    "get_alert_details",
    "get_device",
    "get_device_properties",
    "correlate_alerts",
    "correlate_changes",
    "analyze_blast_radius",
    "score_device_health",
]


async def diagnose(
    client: LogicMonitorClient,
    alert_id: str | None = None,
    device_name: str | None = None,
    detail_level: str = "summary",
    summarize: bool = False,
) -> list[TextContent]:
    """Composite diagnosis for an alert or device.

    Gathers alert details, device context, correlated alerts, recent
    changes, blast radius, and health score. Produces a diagnosis
    report with probable root cause indicators.

    Args:
        client: LogicMonitor API client.
        alert_id: Alert ID to diagnose.
        device_name: Device name (finds most recent critical alert).
        detail_level: 'summary' or 'full' (default: summary).

    Returns:
        Diagnosis report as TextContent list.
    """
    blocked = check_required_tools(_DIAGNOSE_REQUIRED)
    if blocked:
        return blocked

    try:
        from lm_mcp.tools.alerts import get_alert_details, get_alerts
        from lm_mcp.tools.correlation import correlate_alerts
        from lm_mcp.tools.devices import get_device
        from lm_mcp.tools.event_correlation import correlate_changes
        from lm_mcp.tools.resources import get_device_properties
        from lm_mcp.tools.topology_analysis import analyze_blast_radius

        warnings: list[str] = []
        report: dict = {"detail_level": detail_level}

        # 1. Resolve target
        alert_data: dict | None = None
        target_device_id: int | None = None

        if alert_id:
            try:
                alert_data = await call_sub_tool(
                    get_alert_details,
                    client,
                    alert_id=alert_id,
                )
                target_device_id = alert_data.get("monitorObjectId")
                report["alert"] = alert_data
            except Exception as exc:
                warnings.append(f"get_alert_details failed: {exc}")
        elif device_name:
            try:
                alerts_data = await call_sub_tool(
                    get_alerts,
                    client,
                    device=device_name,
                    severity="critical",
                    cleared=False,
                    limit=1,
                )
                alert_list = alerts_data.get("alerts", [])
                if alert_list:
                    resolved_alert_id = alert_list[0].get("id", "")
                    alert_data = await call_sub_tool(
                        get_alert_details,
                        client,
                        alert_id=str(resolved_alert_id),
                    )
                    target_device_id = alert_data.get("monitorObjectId")
                    report["alert"] = alert_data
                else:
                    report["alert"] = None
                    warnings.append(f"No critical alerts found for device '{device_name}'")
            except Exception as exc:
                warnings.append(f"get_alerts/get_alert_details failed: {exc}")
        else:
            return format_response(
                {
                    "error": True,
                    "code": "MISSING_PARAMS",
                    "message": "Either alert_id or device_name is required",
                }
            )

        # 2. Device context
        if target_device_id is not None:
            try:
                dev = await call_sub_tool(
                    get_device,
                    client,
                    device_id=target_device_id,
                )
                report["device"] = dev
            except Exception as exc:
                warnings.append(f"get_device failed: {exc}")

            try:
                props = await call_sub_tool(
                    get_device_properties,
                    client,
                    device_id=target_device_id,
                )
                report["device_properties"] = props
            except Exception as exc:
                warnings.append(f"get_device_properties failed: {exc}")

        # 3. Correlated alerts
        try:
            corr = await call_sub_tool(
                correlate_alerts,
                client,
                hours_back=4,
            )
            report["correlated_alerts"] = corr
        except Exception as exc:
            warnings.append(f"correlate_alerts failed: {exc}")

        # 4. Change correlation
        try:
            changes = await call_sub_tool(
                correlate_changes,
                client,
                hours_back=4,
            )
            report["changes"] = changes
        except Exception as exc:
            warnings.append(f"correlate_changes failed: {exc}")

        # 5. Blast radius
        if target_device_id is not None:
            try:
                blast = await call_sub_tool(
                    analyze_blast_radius,
                    client,
                    device_id=target_device_id,
                )
                report["blast_radius"] = blast
            except Exception as exc:
                warnings.append(f"analyze_blast_radius failed: {exc}")

        if warnings:
            report["warnings"] = warnings

        full_keys = {"device_properties", "blast_radius"}
        report = _trim_detail(report, detail_level, full_keys)
        await _maybe_summarize(report, "diagnose", summarize, warnings)

        return format_response(report)
    except Exception as e:
        return handle_error(e)


# ---------------------------------------------------------------------------
# Discovery tool: search_tools
# ---------------------------------------------------------------------------

# Keyword aliases map workflow concepts to composite tool names
_WORKFLOW_ALIASES: dict[str, list[str]] = {
    "incident": ["triage", "diagnose"],
    "outage": ["triage", "diagnose"],
    "issue": ["triage", "diagnose"],
    "health": ["health_check"],
    "status": ["health_check", "portal_overview"],
    "capacity": ["capacity_plan"],
    "forecast": ["capacity_plan"],
    "growth": ["capacity_plan"],
    "overview": ["portal_overview"],
    "shift": ["portal_overview"],
    "handoff": ["portal_overview"],
    "rca": ["diagnose"],
    "root cause": ["diagnose"],
    "diagnos": ["diagnose"],
    "troubleshoot": ["diagnose"],
    # Reference-layer aliases (map schema/filter/syntax lookups to get_reference,
    # prompt/workflow lookups to get_workflow)
    "schema": ["get_reference"],
    "filter": ["get_reference"],
    "syntax": ["get_reference"],
    "reference": ["get_reference"],
    "guide": ["get_reference"],
    "workflow": ["get_workflow"],
    "prompt": ["get_workflow"],
}


async def search_tools(
    client: LogicMonitorClient,
    query: str,
    category: str | None = None,
    limit: int = 10,
) -> list[TextContent]:
    """Search available MCP tools by keyword or category.

    Searches tool names and descriptions using word-level tokenization.
    Scores matches by: exact name match (highest), word in name (medium),
    word in description (lower). Suggests composite tools when the query
    matches workflow concepts.

    Args:
        client: LogicMonitor API client (unused, required by convention).
        query: Search keywords.
        category: Filter to a specific category.
        limit: Maximum results (default: 10).

    Returns:
        Matching tools with relevance scores.
    """
    try:
        from lm_mcp.registry import AWX_TOOLS, TF_TOOLS, TOOLS, WATSONX_TOOLS
        from lm_mcp.resources.guides import TOOL_CATEGORIES
        from lm_mcp.server import get_awx_client, get_tf_runner, get_watsonx_client

        # Mirror the server's advertised tool surface so configured AWX / watsonx /
        # Terraform tools are searchable, not just the core TOOLS list.
        search_corpus = list(TOOLS)
        if get_awx_client() is not None:
            search_corpus.extend(AWX_TOOLS)
        if get_watsonx_client() is not None:
            search_corpus.extend(WATSONX_TOOLS)
        if get_tf_runner() is not None:
            search_corpus.extend(TF_TOOLS)

        # Tokenize query into lowercase words
        query_words = re.findall(r"[a-z0-9_]+", query.lower())
        if not query_words:
            return format_response(
                {
                    "matches": [],
                    "total": 0,
                    "query": query,
                    "suggestions": [],
                }
            )

        # Optionally filter by category
        category_tool_names: set[str] | None = None
        if category:
            cats = TOOL_CATEGORIES.get("categories", {})
            cat_data = cats.get(category)
            if cat_data:
                category_tool_names = set(cat_data.get("tools", []))
            else:
                return format_response(
                    {
                        "matches": [],
                        "total": 0,
                        "query": query,
                        "category": category,
                        "available_categories": list(cats.keys()),
                        "suggestions": [],
                    }
                )

        # Score each tool
        scored: list[tuple[float, dict]] = []
        for tool in search_corpus:
            name = tool.name
            desc = (tool.description or "").lower()

            if category_tool_names is not None and name not in category_tool_names:
                continue

            score = 0.0
            name_lower = name.lower()
            name_parts = re.findall(r"[a-z0-9]+", name_lower)

            for word in query_words:
                # Exact name match
                if word == name_lower:
                    score += 10.0
                # Word appears in name parts
                elif word in name_parts:
                    score += 5.0
                # Partial match in name
                elif word in name_lower:
                    score += 3.0
                # Word in description
                elif word in desc:
                    score += 1.0

            if score > 0:
                scored.append(
                    (
                        score,
                        {
                            "name": name,
                            "description": tool.description,
                            "score": round(score, 1),
                        },
                    )
                )

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)
        matches = [item for _, item in scored[:limit]]

        # Suggest composite tools if query matches workflow concepts
        suggestions: list[str] = []
        query_joined = " ".join(query_words)
        for keyword, tools in _WORKFLOW_ALIASES.items():
            if keyword in query_joined or any(keyword in w for w in query_words):
                for t in tools:
                    if t not in suggestions:
                        suggestions.append(t)

        return format_response(
            {
                "matches": matches,
                "total": len(scored),
                "query": query,
                "category": category,
                "suggestions": suggestions if suggestions else None,
            }
        )
    except Exception as e:
        return handle_error(e)


# ---------------------------------------------------------------------------
# Composite tool: update_logicmodule (safe export-modify-update for source types)
# ---------------------------------------------------------------------------

# Map of LogicModule type -> (export tool name, update tool name, id arg name).
# Diagnostic and Remediation sources are intentionally excluded:
# DiagnosticSource is read-only; RemediationSource has its own execute path.
_LM_TYPES: dict[str, tuple[str, str, str]] = {
    "configsource": ("export_configsource", "update_configsource", "configsource_id"),
    "datasource": ("export_datasource", "update_datasource", "datasource_id"),
    "eventsource": ("export_eventsource", "update_eventsource", "eventsource_id"),
    "logsource": ("export_logsource", "update_logsource", "logsource_id"),
    "propertysource": ("export_propertysource", "update_propertysource", "propertysource_id"),
    "topologysource": ("export_topologysource", "update_topologysource", "topologysource_id"),
    "diagnosticsource": (
        "export_diagnosticsource",
        "update_diagnosticsource",
        "diagnosticsource_id",
    ),
    "remediationsource": (
        "export_remediationsource",
        "update_remediationsource",
        "remediationsource_id",
    ),
}


def _deep_merge(base: dict, overlay: dict, *, path: str = "") -> tuple[dict, list[str]]:
    """Merge overlay onto base for safe partial logicmodule updates.

    Semantics:
    - dict + dict: recurse
    - list + list: REPLACE wholesale (LM treats dataPoints, instanceLevelAttribute,
      etc. as atomic collections; by-id merging would require per-collection
      schema knowledge that is not available)
    - primitive + anything (compatible types): overlay wins
    - None in overlay: explicit delete (pop key from result); emits a warning
      if the key was not present, to surface typo'd field names
    - type conflicts (e.g., dict in base, list in overlay) raise ValueError

    Returns the merged dict plus a list of human-readable warnings about
    no-op deletions or other notable merge events.
    """
    out = dict(base)
    warnings: list[str] = []
    for k, v in overlay.items():
        full = f"{path}.{k}" if path else k
        if v is None:
            if k in out:
                out.pop(k)
            else:
                warnings.append(f"deletion of missing key '{full}' was a no-op")
            continue
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            sub, sub_warns = _deep_merge(out[k], v, path=full)
            out[k] = sub
            warnings.extend(sub_warns)
        elif k in out and out[k] is not None and type(out[k]) is not type(v):
            raise ValueError(
                f"type conflict at '{full}': base is {type(out[k]).__name__}, "
                f"overlay is {type(v).__name__}"
            )
        else:
            out[k] = v
    return out, warnings


def _diff(before: dict, after: dict, path: str = "") -> list[dict]:
    """Compute a flat list of diff entries between two dicts.

    Each entry: {"path": "a.b.c", "op": "add" | "remove" | "change",
                 "before": <value or None>, "after": <value or None>}.
    Lists are compared by equality only; nested dict diffs recurse.
    """
    entries: list[dict] = []
    keys = set(before) | set(after)
    for k in sorted(keys):
        full = f"{path}.{k}" if path else k
        if k not in before:
            entries.append({"path": full, "op": "add", "before": None, "after": after[k]})
        elif k not in after:
            entries.append({"path": full, "op": "remove", "before": before[k], "after": None})
        elif before[k] == after[k]:
            continue
        elif isinstance(before[k], dict) and isinstance(after[k], dict):
            entries.extend(_diff(before[k], after[k], path=full))
        else:
            entries.append({"path": full, "op": "change", "before": before[k], "after": after[k]})
    return entries


async def update_logicmodule(
    client: LogicMonitorClient,
    type: str,
    id: int,
    changes: dict,
    mode: str = "preview",
) -> list[TextContent]:
    """Safe partial update for LogicMonitor source types.

    Workflow: export the current full definition, deep-merge the provided
    changes onto it, validate that LM-required fields (name, displayName)
    are present, then either return a dry-run diff (mode='preview') or
    apply the merged definition via the existing update_<type> handler
    (mode='apply').

    This avoids the full-replace blanking footgun documented in lessons.md:
    naive update_<type> calls wipe any field not in the payload.

    Args:
        client: LogicMonitor API client.
        type: One of configsource, datasource, diagnosticsource, eventsource,
            logsource, propertysource, remediationsource, topologysource.
        id: LogicModule ID.
        changes: Partial update — only the fields to modify. Use None as a
            value to explicitly delete a key.
        mode: "preview" (default, returns diff without writing) or "apply"
            (writes the merged definition).

    Returns:
        TextContent with diff preview or apply result; or error info.
    """
    try:
        if type not in _LM_TYPES:
            return format_response(
                {
                    "error": True,
                    "code": "UNKNOWN_TYPE",
                    "message": f"type must be one of {sorted(_LM_TYPES)}",
                }
            )
        if mode not in ("preview", "apply"):
            return format_response(
                {
                    "error": True,
                    "code": "INVALID_MODE",
                    "message": "mode must be 'preview' or 'apply'",
                }
            )
        if not isinstance(changes, dict):
            return format_response(
                {
                    "error": True,
                    "code": "INVALID_CHANGES",
                    "message": "changes must be a dict (partial update with field overrides)",
                }
            )

        export_name, update_name, id_arg = _LM_TYPES[type]

        blocked = check_required_tools([export_name, update_name])
        if blocked:
            return blocked

        from lm_mcp.registry import get_tool_handler

        export_handler = get_tool_handler(export_name)
        update_handler = get_tool_handler(update_name)

        current = await call_sub_tool(export_handler, client, **{id_arg: id})
        # DO NOT use `.get("definition") or current` -- an empty dict definition
        # is falsy and would silently fall through to the envelope wrapper.
        # `.get(key, default)` returns the value when key is present (even if
        # falsy) and the default only when key is absent.
        base = current.get("definition", current)

        merged, merge_warnings = _deep_merge(base, changes)

        for required in ("name", "displayName"):
            if not merged.get(required):
                return format_response(
                    {
                        "error": True,
                        "code": "MISSING_REQUIRED_FIELD",
                        "message": (
                            f"merged definition missing required field '{required}'. "
                            "LM API will reject the update. Either keep it from the "
                            "exported definition or set it explicitly in changes."
                        ),
                    }
                )

        diff = _diff(base, merged)
        preview = {
            "type": type,
            "id": id,
            "mode": mode,
            "diff": diff,
            "merged_field_count": len(merged),
            "warnings": merge_warnings,
        }

        if mode == "preview":
            preview["dry_run"] = True
            preview["next_step"] = (
                "Re-call with mode='apply' to push the merged definition. "
                "Note: the underlying update is full-replace; the merged payload "
                "becomes the new full definition."
            )
            return format_response(preview)

        # mode == "apply"
        _AUDIT.info(
            "update_logicmodule attempting type=%s id=%s diff_count=%d",
            type,
            id,
            len(diff),
        )
        try:
            result = await call_sub_tool(
                update_handler, client, **{id_arg: id, "definition": merged, "confirm": True}
            )
        except Exception as exc:
            _AUDIT.error("update_logicmodule failed type=%s id=%s error=%s", type, id, exc)
            raise

        # Audit log "applied" only after the underlying PUT succeeded.
        _AUDIT.info("update_logicmodule applied type=%s id=%s", type, id)
        return format_response({**preview, "applied": True, "result": result})
    except Exception as e:
        return handle_error(e)


# ---------------------------------------------------------------------------
# Composite tool: detect_site_outage
# ---------------------------------------------------------------------------

_SITE_OUTAGE_REQUIRED = [
    "get_alerts",
    "get_devices",
    "get_collector_health",
    "detect_alert_burst",
    "get_power_events",
]

_POWER_KEYWORDS = ("ups", "pdu", "battery", "power")

# Confidence each triggered signal adds to the site-outage score.
_SITE_OUTAGE_WEIGHTS = {
    "collector_down": 40,
    "interface_burst": 25,
    "power_events": 25,
    "device_silence": 10,
}


def _site_outage_verdict(score: int) -> str:
    """Map a site-outage confidence score to its verdict."""
    if score >= 70:
        return "site_outage_detected"
    if score >= 40:
        return "possible_site_outage"
    return "no_outage_signature"


def _unavailable_signal(error: str) -> dict:
    """Breakdown entry for a signal whose read failed: unknown, not untriggered."""
    return {"triggered": None, "status": "unavailable", "error": error}


async def detect_site_outage(
    client: LogicMonitorClient,
    group_id: int,
    window_seconds: int = 300,
    hours_back: int = 1,
    detail_level: str = "summary",
) -> list[TextContent]:
    """Composite detector for site-level outages across a device group.

    Chains four signals into a single verdict:
      A) CollectorDown — any collector serving devices in this group is down
      B) Mass interface-down burst — detect_alert_burst on Interface-family DSes
      C) Power events — UPS/PDU alerts in the last hour
      D) Device silence — count of dead devices in the group

    Confidence score (0-100):
      A>0: +40  |  B>0: +25  |  C>0: +25  |  D>threshold: +10

    Verdict: >=70 site_outage_detected; >=40 possible_site_outage; else no.

    A signal whose read fails is reported with status "unavailable" and its
    error, and is left out of the score. The report then carries
    confidence_level "reduced" and unavailable_signals; when the lost signals'
    weights could change the verdict, the verdict is "indeterminate".

    Args:
        client: LogicMonitor API client.
        group_id: Site = device group ID. Devices in this group define the
            scope of the analysis.
        window_seconds: Burst window size in seconds (default: 300).
        hours_back: Context window for power events in hours (default: 1).
        detail_level: "summary" or "full" (default: summary).

    Returns:
        TextContent list with verdict, confidence, signal breakdown, and
        affected-scope details.
    """
    blocked = check_required_tools(_SITE_OUTAGE_REQUIRED)
    if blocked:
        return blocked

    try:
        from lm_mcp.tools.collectors import get_collector_health
        from lm_mcp.tools.devices import get_devices
        from lm_mcp.tools.networking import detect_alert_burst, get_power_events

        warnings: list[str] = []

        # Scope: enumerate devices in the group once.
        devices_data = await call_sub_tool(
            get_devices,
            client,
            group_id=group_id,
            limit=500,
        )
        devices = devices_data.get("devices", [])
        device_count = len(devices)
        dead_devices = _count_dead_devices(devices)
        collector_ids = _collector_ids_from_devices(devices)

        # Signals whose read failed, by signal name, with the error. They are left
        # out of the score instead of being scored as not triggered.
        unavailable: dict[str, str] = {}

        # Signal A: CollectorDown on collectors serving this group. Each
        # collector is probed independently so a single bad collector ID
        # (e.g., orphaned reference to a deleted collector) does not abort
        # the rest of the signal.
        collector_down_count = 0
        collectors_unknown = 0
        collectors_inspected: list[dict] = []
        collector_probe_failures: list[str] = []
        for cid in collector_ids:
            try:
                health_data = await call_sub_tool(
                    get_collector_health,
                    client,
                    collector_id=cid,
                    include_history=False,
                )
                entry = (health_data.get("collectors") or [{}])[0]
                collectors_inspected.append(entry)
                if entry.get("is_down"):
                    collector_down_count += 1
                elif entry.get("is_down") is None:
                    collectors_unknown += 1
            except Exception as exc:
                collector_probe_failures.append(f"collector_id={cid}: {exc}")

        if collector_probe_failures:
            failures_shown = "; ".join(collector_probe_failures[:5])
            suffix = "..." if len(collector_probe_failures) > 5 else ""
            warnings.append(
                f"{len(collector_probe_failures)}/{len(collector_ids)} "
                f"collector health probes failed: {failures_shown}{suffix}"
            )

        # One collector known to be down triggers the signal; otherwise any
        # collector whose state is unknown could have triggered it.
        collectors_unchecked = collectors_unknown + len(collector_probe_failures)
        if collector_down_count == 0 and collectors_unchecked:
            unavailable["collector_down"] = (
                f"{collectors_unchecked}/{len(collector_ids)} collector(s) could not be "
                "checked for CollectorDown"
            )

        # Signal B: mass interface-down burst in the window.
        burst_signal: dict | None = None
        try:
            burst_data = await call_sub_tool(
                detect_alert_burst,
                client,
                group_id=group_id,
                datasource_pattern="interface",
                window_seconds=window_seconds,
                min_alerts=5,
                min_devices=3,
                hours_back=hours_back,
            )
            burst_signal = burst_data
        except Exception as exc:
            warnings.append(f"Burst detection failed: {exc}")
            unavailable["interface_burst"] = f"Burst detection failed: {exc}"

        # Signal C: power events (UPS/PDU on-battery, battery-runtime, etc.).
        power_events_count = 0
        power_events_preview: list[dict] = []
        try:
            power_data = await call_sub_tool(
                get_power_events,
                client,
                group_id=group_id,
                hours_back=hours_back,
            )
            power_events_count = int(power_data.get("total_power_events", 0))
            power_events_preview = list(power_data.get("events", []))[:10]
        except Exception as exc:
            warnings.append(f"Power event query failed: {exc}")
            unavailable["power_events"] = f"Power event query failed: {exc}"

        # Score and verdict.
        silence_threshold = max(3, device_count // 5)  # 20% of group or 3 whichever higher
        confidence = 0
        signals_breakdown = {}
        if "collector_down" in unavailable:
            signals_breakdown["collector_down"] = _unavailable_signal(unavailable["collector_down"])
        elif collector_down_count > 0:
            confidence += _SITE_OUTAGE_WEIGHTS["collector_down"]
            signals_breakdown["collector_down"] = {
                "triggered": True,
                "count": collector_down_count,
                "weight": _SITE_OUTAGE_WEIGHTS["collector_down"],
            }
        else:
            signals_breakdown["collector_down"] = {"triggered": False, "count": 0}

        burst_count = int((burst_signal or {}).get("bursts_detected", 0))
        if "interface_burst" in unavailable:
            signals_breakdown["interface_burst"] = _unavailable_signal(
                unavailable["interface_burst"]
            )
        elif burst_count > 0:
            confidence += _SITE_OUTAGE_WEIGHTS["interface_burst"]
            signals_breakdown["interface_burst"] = {
                "triggered": True,
                "burst_count": burst_count,
                "weight": _SITE_OUTAGE_WEIGHTS["interface_burst"],
            }
        else:
            signals_breakdown["interface_burst"] = {"triggered": False, "burst_count": 0}

        if "power_events" in unavailable:
            signals_breakdown["power_events"] = _unavailable_signal(unavailable["power_events"])
        elif power_events_count > 0:
            confidence += _SITE_OUTAGE_WEIGHTS["power_events"]
            signals_breakdown["power_events"] = {
                "triggered": True,
                "count": power_events_count,
                "weight": _SITE_OUTAGE_WEIGHTS["power_events"],
            }
        else:
            signals_breakdown["power_events"] = {"triggered": False, "count": 0}

        if dead_devices >= silence_threshold:
            confidence += _SITE_OUTAGE_WEIGHTS["device_silence"]
            signals_breakdown["device_silence"] = {
                "triggered": True,
                "dead_devices": dead_devices,
                "threshold": silence_threshold,
                "weight": _SITE_OUTAGE_WEIGHTS["device_silence"],
            }
        else:
            signals_breakdown["device_silence"] = {
                "triggered": False,
                "dead_devices": dead_devices,
                "threshold": silence_threshold,
            }

        confidence = min(confidence, 100)
        verdict = _site_outage_verdict(confidence)
        # The lost signals could have added at most their weights. When that
        # ceiling names a different verdict, the signals that read cannot decide.
        ceiling = min(confidence + sum(_SITE_OUTAGE_WEIGHTS[name] for name in unavailable), 100)
        if _site_outage_verdict(ceiling) != verdict:
            verdict = "indeterminate"

        recommendations = _site_outage_recommendations(
            verdict, signals_breakdown, power_events_count, collector_down_count
        )

        report: dict = {
            "verdict": verdict,
            "confidence": confidence,
            **(
                {"confidence_level": "reduced", "unavailable_signals": list(unavailable)}
                if unavailable
                else {}
            ),
            "group_id": group_id,
            "window_seconds": window_seconds,
            "hours_back": hours_back,
            "scope": {
                "devices_in_group": device_count,
                "dead_devices": dead_devices,
                "collectors_serving_group": len(collector_ids),
            },
            "signals": signals_breakdown,
            "recommendations": recommendations,
            "warnings": warnings,
            "collectors_inspected": collectors_inspected,
            "interface_burst_detail": burst_signal,
            "power_events_preview": power_events_preview,
        }

        report = _trim_detail(
            report,
            detail_level,
            {"collectors_inspected", "interface_burst_detail", "power_events_preview"},
        )
        return format_response(report)
    except Exception as e:
        return handle_error(e)


def _count_dead_devices(devices: list[dict]) -> int:
    """Count devices in dead or dead-collector status.

    LM hostStatus codes: 0=normal, 1=dead, 2=dead-collector, 3=unmonitored,
    4=disabled. Both 1 and 2 count as dead because the device is not
    reporting metrics in either case. The formatted `get_devices` response
    surfaces hostStatus as `status`; the raw API item keeps `hostStatus`.
    """
    count = 0
    for dev in devices:
        status = dev.get("hostStatus")
        if status is None:
            status = dev.get("status")
        alert_status = (dev.get("alertStatus") or "").lower()
        if status in (1, 2, "1", "2", "dead", "dead-collector") or alert_status in (
            "dead",
            "dead-collector",
            "unreachable",
        ):
            count += 1
    return count


def _collector_ids_from_devices(devices: list[dict]) -> list[int]:
    """Distinct collector IDs from a device list.

    Accepts both the formatted `get_devices` shape (`collector_id`) and the
    raw LM API shape (`currentCollectorId` / `preferredCollectorId`) so the
    helper works whether the caller passes formatted sub-tool output or raw
    API items. Formatted shape is preferred because that's what the composite
    sub-tool dispatch produces today.
    """
    seen: set[int] = set()
    ordered: list[int] = []
    for dev in devices:
        cid = (
            dev.get("collector_id")
            or dev.get("currentCollectorId")
            or dev.get("preferredCollectorId")
        )
        if cid and cid not in seen:
            seen.add(cid)
            ordered.append(cid)
    return ordered


def _site_outage_recommendations(
    verdict: str,
    signals: dict,
    power_events: int,
    collector_down: int,
) -> list[str]:
    """Actionable next steps based on which signals fired."""
    recs: list[str] = []
    if verdict == "site_outage_detected":
        recs.append("Treat as a single site-level incident; do not triage individual alerts.")
    if verdict == "indeterminate":
        lost = [name for name, sig in signals.items() if sig.get("status") == "unavailable"]
        recs.append(
            f"Signals could not be read ({', '.join(lost)}), and they could change the "
            "verdict. Re-run once the failed reads in warnings succeed."
        )
    if collector_down > 0:
        recs.append(
            "Verify collector host connectivity — collector is the typical first signal "
            "of site-level power or network loss."
        )
    if power_events > 0:
        recs.append(
            "Review UPS/PDU events for on-battery transitions and runtime-remaining "
            "alerts to confirm power-infrastructure involvement."
        )
    if signals.get("interface_burst", {}).get("triggered"):
        recs.append(
            "Mass interface-down detected — correlate affected ports to a common rack, "
            "switch, or uplink to localize the fault domain."
        )
    if signals.get("device_silence", {}).get("triggered"):
        recs.append(
            "Elevated count of dead devices — expect delayed alert clearing; "
            "re-run after site recovery to confirm scope."
        )
    if not recs:
        recs.append(
            "No outage signature detected. If symptoms persist, widen the group scope "
            "or lengthen the hours_back window."
        )
    return recs


# ---------------------------------------------------------------------------
# Composite tool: audit_network_monitoring_coverage
# ---------------------------------------------------------------------------

_AUDIT_COVERAGE_REQUIRED = [
    "get_devices",
    "get_collectors",
]


async def audit_network_monitoring_coverage(
    client: LogicMonitorClient,
    group_id: int | None = None,
) -> list[TextContent]:
    """Audit portal monitoring coverage and surface actionable gaps.

    Inventories devices, collectors, and coverage indicators (power
    monitoring, SNMP credentials, NetFlow exporters). Returns a gap list
    with specific recommendations — turns "you can't detect X" into
    "here's how to enable detection of X."

    Args:
        client: LogicMonitor API client.
        group_id: Scope the audit to a device group. None = portal-wide.

    Returns:
        TextContent list with inventory, coverage percentages, and prioritized gaps.
    """
    blocked = check_required_tools(_AUDIT_COVERAGE_REQUIRED)
    if blocked:
        return blocked

    try:
        from lm_mcp.tools.collectors import get_collectors
        from lm_mcp.tools.devices import get_devices

        warnings: list[str] = []

        devices_data = await call_sub_tool(
            get_devices,
            client,
            group_id=group_id,
            limit=1000,
        )
        devices = devices_data.get("devices", [])
        collectors_data = await call_sub_tool(get_collectors, client, limit=200)
        collectors = collectors_data.get("collectors", [])

        inventory = _build_inventory(devices, collectors)
        coverage = _compute_coverage(devices, collectors)
        gaps = _derive_gaps(inventory, coverage)

        return format_response(
            {
                "scope": {"group_id": group_id, "portal_wide": group_id is None},
                "inventory": inventory,
                "coverage_percentages": coverage["percentages"],
                "coverage_counts": coverage["counts"],
                "gaps": gaps,
                "summary": _audit_summary(inventory, coverage, gaps),
                "warnings": warnings,
            }
        )
    except Exception as e:
        return handle_error(e)


def _build_inventory(devices: list[dict], collectors: list[dict]) -> dict:
    """Counts by deviceType and likely power infrastructure."""
    total_devices = len(devices)
    power_like = 0
    network_like = 0
    server_like = 0
    unknown = 0

    for dev in devices:
        name = (dev.get("displayName") or dev.get("name") or "").lower()
        system_categories = (dev.get("systemCategories") or "").lower()
        combined = f"{name} {system_categories}"
        if any(kw in combined for kw in _POWER_KEYWORDS):
            power_like += 1
        elif any(kw in combined for kw in ("switch", "router", "firewall", "wlan")):
            network_like += 1
        elif any(kw in combined for kw in ("server", "linux", "windows", "host")):
            server_like += 1
        else:
            unknown += 1

    return {
        "total_devices": total_devices,
        "likely_power_infrastructure": power_like,
        "likely_network_gear": network_like,
        "likely_servers": server_like,
        "unclassified": unknown,
        "total_collectors": len(collectors),
    }


def _compute_coverage(devices: list[dict], collectors: list[dict]) -> dict:
    """Count devices with specific monitoring properties set."""
    total = len(devices) or 1
    snmp_count = 0
    netflow_count = 0
    power_monitored = 0

    for dev in devices:
        props = _properties_dict(dev)
        categories = (dev.get("systemCategories") or "").lower()
        name = (dev.get("displayName") or dev.get("name") or "").lower()

        if props.get("snmp.version") or props.get("snmp.community"):
            snmp_count += 1
        if (
            props.get("netflow.enabled")
            or "netflow" in categories
            or "netflowexporter" in categories
        ):
            netflow_count += 1
        if any(kw in f"{name} {categories}" for kw in _POWER_KEYWORDS):
            power_monitored += 1

    collectors_up = sum(1 for c in collectors if c.get("status") not in ("dead", "down"))

    return {
        "counts": {
            "snmp_credentialed": snmp_count,
            "netflow_exporters": netflow_count,
            "power_monitored_devices": power_monitored,
            "collectors_up": collectors_up,
            "collectors_total": len(collectors),
        },
        "percentages": {
            "snmp_coverage_pct": round(100.0 * snmp_count / total, 1),
            "netflow_coverage_pct": round(100.0 * netflow_count / total, 1),
            "power_monitoring_coverage_pct": round(100.0 * power_monitored / total, 1),
        },
    }


def _properties_dict(device: dict) -> dict[str, str]:
    """Flatten a device's customProperties list into a name->value dict."""
    result: dict[str, str] = {}
    for prop in device.get("customProperties", []) or []:
        name = prop.get("name")
        if name:
            result[name] = prop.get("value", "")
    for prop in device.get("systemProperties", []) or []:
        name = prop.get("name")
        if name and name not in result:
            result[name] = prop.get("value", "")
    return result


def _derive_gaps(inventory: dict, coverage: dict) -> list[dict]:
    """Prioritized list of coverage gaps with concrete recommendations."""
    gaps: list[dict] = []
    counts = coverage["counts"]

    if counts["power_monitored_devices"] == 0 and inventory["total_devices"] > 0:
        gaps.append(
            {
                "severity": "high",
                "category": "power",
                "finding": (
                    "No UPS/PDU/battery devices detected in this scope. Power outage "
                    "correlation cannot use UPS-state signals."
                ),
                "recommendation": (
                    "Onboard UPS and PDU devices (APC, Liebert, Eaton). Apply the "
                    "APC_UPS_Battery, Liebert_UPS, or Eaton_UPS DataSources so "
                    "on-battery and runtime-remaining events surface as alerts."
                ),
            }
        )

    total = max(inventory["total_devices"], 1)
    snmp_pct = coverage["percentages"]["snmp_coverage_pct"]
    if snmp_pct < 25 and inventory["likely_network_gear"] > 0:
        gaps.append(
            {
                "severity": "high",
                "category": "snmp",
                "finding": (
                    f"SNMP credentials set on only {snmp_pct}% of devices while "
                    f"{inventory['likely_network_gear']} network devices are present. "
                    "Interface metrics and link-flap detection depend on SNMP."
                ),
                "recommendation": (
                    "Apply snmp.version and snmp.community properties to network "
                    "devices at the group level to enable Interface DataSources."
                ),
            }
        )

    if counts["netflow_exporters"] == 0 and inventory["likely_network_gear"] > 0:
        gaps.append(
            {
                "severity": "medium",
                "category": "netflow",
                "finding": "No NetFlow exporters detected. Traffic intelligence unavailable.",
                "recommendation": (
                    "Enable NetFlow export on core and WAN devices. Set "
                    "netflow.enabled=true on the device or add the NetflowExporter "
                    "DataSource so the /netflow/flows endpoint receives records."
                ),
            }
        )

    if counts["collectors_total"] == 0:
        gaps.append(
            {
                "severity": "critical",
                "category": "collectors",
                "finding": "No collectors registered. Nothing can be monitored.",
                "recommendation": "Deploy at least one collector and assign it to devices.",
            }
        )
    elif counts["collectors_up"] < counts["collectors_total"]:
        down = counts["collectors_total"] - counts["collectors_up"]
        gaps.append(
            {
                "severity": "high",
                "category": "collectors",
                "finding": f"{down} collector(s) are down or unreachable.",
                "recommendation": (
                    "Restore collectors before relying on alert data — downstream "
                    "device alerts are suppressed while their collector is down."
                ),
            }
        )

    if inventory["unclassified"] > total * 0.5:
        gaps.append(
            {
                "severity": "low",
                "category": "inventory",
                "finding": (
                    f"{inventory['unclassified']} devices are unclassified by "
                    "systemCategories. Device grouping and filtering accuracy is limited."
                ),
                "recommendation": (
                    "Apply systemCategories property at the device-group level so "
                    "audit and correlation tools can partition inventory."
                ),
            }
        )

    return gaps


def _audit_summary(inventory: dict, coverage: dict, gaps: list[dict]) -> str:
    """One-line human-readable summary."""
    total = inventory["total_devices"]
    critical = sum(1 for g in gaps if g["severity"] in ("critical", "high"))
    if critical == 0:
        return f"Coverage looks solid across {total} devices ({len(gaps)} low-priority findings)."
    return (
        f"{critical} high-priority coverage gaps detected across {total} devices. "
        "Review gap list for specific onboarding actions."
    )
