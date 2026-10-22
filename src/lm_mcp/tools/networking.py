# Description: Network intelligence tools for LogicMonitor MCP server.
# Description: Interface metrics, top talkers, alert bursts, link flaps, power events.

from __future__ import annotations

import re
import time
from collections import defaultdict
from typing import TYPE_CHECKING

from mcp.types import TextContent

from lm_mcp.tools import (
    SEVERITY_MAP,
    format_response,
    handle_error,
    quote_filter_value,
    resolve_group_filter,
    sanitize_filter_value,
)
from lm_mcp.tools.alerts import ALERT_WINDOW_TRUNCATED_WARNING, paginate_alerts

if TYPE_CHECKING:
    from lm_mcp.client import LogicMonitorClient


# Interface-family DataSource name patterns for interface metric resolution.
_INTERFACE_DATASOURCE_PATTERNS = ("interface", "interfaces", "if-", "port", "ethernet")

# Preferred Interface DataSource when multiple match.
_PREFERRED_INTERFACE_DATASOURCE = "SNMP_Network_Interfaces"

# Default datapoints pulled when caller does not specify.
_DEFAULT_INTERFACE_METRICS = (
    "RxRate,TxRate,ErrorsIn,ErrorsOut,DiscardsIn,DiscardsOut,InterfaceStatus"
)

# UPS/PDU DataSource name patterns used by get_power_events.
_DEFAULT_POWER_PATTERNS = (
    "UPS",
    "PDU",
    "APC",
    "Liebert",
    "Eaton",
    "Battery",
    "PowerSupply",
    "Power_",
)

# Flows requested per get_top_talkers call.
_FLOWS_PAGE_SIZE = 1000

# Valid group_by values for get_top_talkers.
_TOP_TALKERS_GROUP_BY = frozenset({"src_ip", "dst_ip", "application", "protocol", "src_dst_pair"})


async def get_interface_metrics(
    client: LogicMonitorClient,
    device_id: int,
    interface: str,
    metrics: str | None = None,
    hours_back: int = 1,
) -> list[TextContent]:
    """Fetch per-interface time-series metrics for a device.

    Resolves the Interface-family DataSource applied to the device, matches
    the interface name (contains match, case-insensitive) against its
    instances, then fetches the requested datapoints over the time window.

    Args:
        client: LogicMonitor API client.
        device_id: Device ID.
        interface: Interface name or partial match (e.g., "Gi0/1", "eth0").
        metrics: Comma-separated datapoint names. Defaults to a common set
            (RxRate, TxRate, ErrorsIn, ErrorsOut, DiscardsIn, DiscardsOut,
            InterfaceStatus).
        hours_back: How many hours of history to pull (default: 1).

    Returns:
        List of TextContent with metric data or error.
    """
    try:
        ds_result = await client.get(
            f"/device/devices/{device_id}/devicedatasources",
            params={"size": 200},
        )
        interface_ds = _pick_interface_datasource(ds_result.get("items", []))
        if interface_ds is None:
            return format_response(
                {
                    "error": True,
                    "code": "INTERFACE_DATASOURCE_NOT_FOUND",
                    "message": (f"No Interface-family DataSource found on device {device_id}"),
                    "suggestion": (
                        "Verify SNMP monitoring is configured and that "
                        "SNMP_Network_Interfaces (or equivalent) is applied to the device."
                    ),
                }
            )

        dsid = interface_ds["id"]
        ds_name = interface_ds.get("dataSourceName")

        instances_result = await client.get(
            f"/device/devices/{device_id}/devicedatasources/{dsid}/instances",
            params={"size": 500},
        )
        instances = instances_result.get("items", [])
        instance = _match_interface_instance(instances, interface)
        if instance is None:
            available = [item.get("displayName") or item.get("name") for item in instances[:50]]
            return format_response(
                {
                    "error": True,
                    "code": "INTERFACE_NOT_FOUND",
                    "message": (
                        f"Interface '{interface}' not found among instances on device "
                        f"{device_id} (DataSource: {ds_name})"
                    ),
                    "available_instances": available,
                    "suggestion": (
                        "Check the interface name case and format. The match is "
                        "case-insensitive substring on name and displayName."
                    ),
                }
            )

        end_time = int(time.time())
        start_time = end_time - (hours_back * 3600)
        datapoints = metrics or _DEFAULT_INTERFACE_METRICS

        data_result = await client.get(
            f"/device/devices/{device_id}/devicedatasources/{dsid}/instances/{instance['id']}/data",
            params={
                "datapoints": datapoints,
                "start": start_time,
                "end": end_time,
            },
        )

        return format_response(
            {
                "device_id": device_id,
                "interface": interface,
                "resolved_datasource": ds_name,
                "resolved_datasource_id": dsid,
                "resolved_instance": instance.get("displayName") or instance.get("name"),
                "resolved_instance_id": instance["id"],
                "window_hours": hours_back,
                "datapoints": data_result.get("dataPoints", []),
                "values": data_result.get("values", {}),
                "time": data_result.get("time", []),
            }
        )
    except Exception as e:
        return handle_error(e)


def _pick_interface_datasource(items: list[dict]) -> dict | None:
    """Pick the best Interface-family DataSource from a device's DataSource list."""
    matches = [
        item
        for item in items
        if any(
            p in (item.get("dataSourceName") or "").lower() for p in _INTERFACE_DATASOURCE_PATTERNS
        )
    ]
    if not matches:
        return None
    for item in matches:
        if item.get("dataSourceName") == _PREFERRED_INTERFACE_DATASOURCE:
            return item
    return matches[0]


def _match_interface_instance(instances: list[dict], interface: str) -> dict | None:
    """Case-insensitive contains match on name or displayName."""
    needle = interface.lower()
    for item in instances:
        name = (item.get("name") or "").lower()
        display = (item.get("displayName") or "").lower()
        if needle in name or needle in display:
            return item
    return None


async def get_top_talkers(
    client: LogicMonitorClient,
    exporter_device_id: int,
    hours_back: int = 1,
    n: int = 10,
    group_by: str = "src_ip",
    min_bytes: int = 0,
) -> list[TextContent]:
    """Rank NetFlow flows for an exporter by bandwidth.

    Aggregates raw flow records client-side by the requested dimension and
    returns the top-N by total bytes.

    Args:
        client: LogicMonitor API client.
        exporter_device_id: NetFlow exporter device ID.
        hours_back: Time window to aggregate (default: 1 hour).
        n: Number of top entries to return (default: 10).
        group_by: Aggregation dimension. One of src_ip, dst_ip, application,
            protocol, src_dst_pair.
        min_bytes: Drop aggregated entries below this byte threshold (default: 0).

    Returns:
        List of TextContent with top-talker ranking or error.
    """
    if group_by not in _TOP_TALKERS_GROUP_BY:
        return format_response(
            {
                "error": True,
                "code": "INVALID_PARAMETER",
                "message": f"group_by must be one of {sorted(_TOP_TALKERS_GROUP_BY)}",
                "suggestion": "Use src_ip, dst_ip, application, protocol, or src_dst_pair.",
            }
        )

    try:
        end_epoch = int(time.time())
        start_epoch = end_epoch - (hours_back * 3600)

        params: dict = {
            "size": _FLOWS_PAGE_SIZE,
            "filter": (
                f"exporterDeviceId:{exporter_device_id},"
                f"startEpoch>:{start_epoch},startEpoch<:{end_epoch}"
            ),
        }
        result = await client.get("/netflow/flows", params=params)
        flows = result.get("items", [])

        # The flow list is read as one page. A negative total (a lower bound),
        # a total past the page, or a full page with no total means flows were
        # left unread.
        raw_total = result.get("total")
        if raw_total is None:
            truncated = len(flows) >= _FLOWS_PAGE_SIZE
        else:
            truncated = raw_total < 0 or len(flows) < raw_total
        api_total = raw_total if raw_total is not None and raw_total >= 0 else None

        aggregated: dict[str, dict] = defaultdict(
            lambda: {"total_bytes": 0, "total_packets": 0, "flow_count": 0}
        )
        total_bytes = 0

        for flow in flows:
            key = _flow_group_key(flow, group_by)
            if key is None:
                continue
            flow_bytes = int(flow.get("bytes") or 0)
            flow_packets = int(flow.get("packets") or 0)
            aggregated[key]["total_bytes"] += flow_bytes
            aggregated[key]["total_packets"] += flow_packets
            aggregated[key]["flow_count"] += 1
            total_bytes += flow_bytes

        ranked = []
        for key, stats in aggregated.items():
            if stats["total_bytes"] < min_bytes:
                continue
            percentage = (
                round(100.0 * stats["total_bytes"] / total_bytes, 2) if total_bytes > 0 else 0.0
            )
            ranked.append(
                {
                    "key": key,
                    "total_bytes": stats["total_bytes"],
                    "total_packets": stats["total_packets"],
                    "flow_count": stats["flow_count"],
                    "percentage_of_total": percentage,
                }
            )

        ranked.sort(key=lambda x: x["total_bytes"], reverse=True)
        top = ranked[:n]

        response: dict = {
            "exporter_device_id": exporter_device_id,
            "window_hours": hours_back,
            "group_by": group_by,
            "flows_analyzed": len(flows),
            "truncated": truncated,
            "api_total": api_total,
            "total_bytes_in_window": total_bytes,
            "top_talkers": top,
        }
        if not flows:
            response["note"] = (
                "No flows exported in window — check NetFlow exporter configuration "
                "and ensure the device is forwarding flow records."
            )
        return format_response(response)
    except Exception as e:
        return handle_error(e)


def _flow_group_key(flow: dict, group_by: str) -> str | None:
    """Derive aggregation key from a flow record."""
    if group_by == "src_ip":
        return flow.get("srcIP")
    if group_by == "dst_ip":
        return flow.get("dstIP")
    if group_by == "protocol":
        return flow.get("protocol")
    if group_by == "src_dst_pair":
        src = flow.get("srcIP")
        dst = flow.get("dstIP")
        if src and dst:
            return f"{src}->{dst}"
        return None
    if group_by == "application":
        app = flow.get("application") or flow.get("nbar2")
        if app:
            return str(app)
        proto = flow.get("protocol") or "unknown"
        port = flow.get("dstPort") or "unknown"
        return f"{proto}:{port}"
    return None


async def detect_alert_burst(
    client: LogicMonitorClient,
    group_id: int | None = None,
    device: str | None = None,
    datasource_pattern: str | None = None,
    window_seconds: int = 60,
    min_alerts: int = 10,
    min_devices: int = 3,
    hours_back: int = 1,
    severity: str | None = None,
) -> list[TextContent]:
    """Sliding-window detector for mass alert events.

    Pulls alerts in the lookback window, buckets them by DataSource, and
    identifies windows where alert count and distinct device count both
    exceed thresholds. Used for detecting cascading failures like mass
    interface-down events during a site outage.

    Args:
        client: LogicMonitor API client.
        group_id: Scope burst detection to a device group.
        device: Scope to a device name (substring match).
        datasource_pattern: Substring match on dataSourceName (case-insensitive).
        window_seconds: Sliding window size in seconds (default: 60).
        min_alerts: Minimum alerts in the window to qualify as burst (default: 10).
        min_devices: Minimum distinct devices in the window (default: 3).
        hours_back: Lookback window in hours (default: 1).
        severity: Filter by severity name (critical, error, warning, info).

    Returns:
        List of TextContent with detected bursts or error.
    """
    try:
        now = int(time.time())
        start_epoch = now - (hours_back * 3600)
        filters: list[str] = [f"startEpoch>:{start_epoch}"]
        wildcards_stripped = False

        if severity and severity.lower() in SEVERITY_MAP:
            filters.append(f"severity:{SEVERITY_MAP[severity.lower()]}")
        if group_id is not None:
            filters.append(await resolve_group_filter(client, group_id))
        if device:
            clean_device, was_modified = sanitize_filter_value(device)
            wildcards_stripped = wildcards_stripped or was_modified
            filters.append(f"monitorObjectName~{quote_filter_value(clean_device)}")

        alerts, truncated, _ = await paginate_alerts(client, ",".join(filters))

        if datasource_pattern:
            needle = datasource_pattern.lower()
            alerts = [a for a in alerts if needle in (a.get("dataSourceName") or "").lower()]

        alerts.sort(key=lambda a: int(a.get("startEpoch") or 0))
        bursts = _detect_bursts_in_alerts(alerts, window_seconds, min_alerts, min_devices)

        response: dict = {
            "params": {
                "group_id": group_id,
                "device": device,
                "datasource_pattern": datasource_pattern,
                "window_seconds": window_seconds,
                "min_alerts": min_alerts,
                "min_devices": min_devices,
                "hours_back": hours_back,
                "severity": severity,
            },
            "total_alerts_in_window": len(alerts),
            "bursts_detected": len(bursts),
            "bursts": bursts,
        }
        if truncated:
            response["warning"] = ALERT_WINDOW_TRUNCATED_WARNING
        if wildcards_stripped:
            response["note"] = (
                "Wildcard characters stripped from device filter — the ~ operator "
                "already performs substring matching."
            )
        return format_response(response)
    except Exception as e:
        return handle_error(e)


def _detect_bursts_in_alerts(
    alerts: list[dict],
    window_seconds: int,
    min_alerts: int,
    min_devices: int,
) -> list[dict]:
    """Identify burst windows using per-DataSource sliding window analysis."""
    by_datasource: dict[str, list[dict]] = defaultdict(list)
    for alert in alerts:
        ds_name = alert.get("dataSourceName") or "unknown"
        by_datasource[ds_name].append(alert)

    bursts: list[dict] = []
    for ds_name, ds_alerts in by_datasource.items():
        ds_alerts.sort(key=lambda a: int(a.get("startEpoch") or 0))
        n = len(ds_alerts)
        if n < min_alerts:
            continue

        i = 0
        while i < n:
            window_end = int(ds_alerts[i].get("startEpoch") or 0) + window_seconds
            j = i
            window_alerts: list[dict] = []
            while j < n and int(ds_alerts[j].get("startEpoch") or 0) <= window_end:
                window_alerts.append(ds_alerts[j])
                j += 1

            distinct_devices = {a.get("monitorObjectName") for a in window_alerts}
            distinct_devices.discard(None)

            if len(window_alerts) >= min_alerts and len(distinct_devices) >= min_devices:
                device_counts: dict[str, int] = defaultdict(int)
                for a in window_alerts:
                    name = a.get("monitorObjectName") or "unknown"
                    device_counts[name] += 1
                top_devices = sorted(device_counts.items(), key=lambda x: x[1], reverse=True)[:10]

                bursts.append(
                    {
                        "datasource": ds_name,
                        "window_start": int(ds_alerts[i].get("startEpoch") or 0),
                        "window_end": window_end,
                        "alert_count": len(window_alerts),
                        "device_count": len(distinct_devices),
                        "alert_ids": [a.get("id") for a in window_alerts[:50]],
                        "top_devices": [
                            {"device": name, "count": count} for name, count in top_devices
                        ],
                    }
                )
                # Jump past this burst window to avoid overlapping duplicates.
                i = j
            else:
                i += 1
    bursts.sort(key=lambda b: b["window_start"])
    return bursts


async def get_link_flaps(
    client: LogicMonitorClient,
    group_id: int | None = None,
    device: str | None = None,
    hours_back: int = 24,
    min_transitions: int = 4,
    interface_pattern: str = "interface|interfaces|if-|port|ethernet",
) -> list[TextContent]:
    """Identify interfaces with repeated up/down transitions.

    Pulls interface-family alerts (both active and cleared) in the window,
    groups by (device, instance), counts transitions, and returns the
    noisiest flapping interfaces.

    Args:
        client: LogicMonitor API client.
        group_id: Scope to a device group.
        device: Scope to a device name (substring match).
        hours_back: Lookback window in hours (default: 24).
        min_transitions: Minimum alert fires to qualify as flapping (default: 4).
        interface_pattern: Regex (case-insensitive) matching interface
            DataSource names (default covers common interface DS names).

    Returns:
        List of TextContent with flap rankings or error.
    """
    try:
        now = int(time.time())
        start_epoch = now - (hours_back * 3600)
        filters: list[str] = [f"startEpoch>:{start_epoch}"]
        wildcards_stripped = False

        if group_id is not None:
            filters.append(await resolve_group_filter(client, group_id))
        if device:
            clean_device, was_modified = sanitize_filter_value(device)
            wildcards_stripped = wildcards_stripped or was_modified
            filters.append(f"monitorObjectName~{quote_filter_value(clean_device)}")

        alerts, truncated, _ = await paginate_alerts(client, ",".join(filters))

        pattern_re = re.compile(interface_pattern, re.IGNORECASE)
        interface_alerts = [a for a in alerts if pattern_re.search(a.get("dataSourceName") or "")]

        grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for alert in interface_alerts:
            dev = alert.get("monitorObjectName") or "unknown"
            inst = alert.get("instanceName") or alert.get("resourceInstanceName") or "unknown"
            grouped[(dev, inst)].append(alert)

        flaps: list[dict] = []
        for (dev, inst), group_alerts in grouped.items():
            if len(group_alerts) < min_transitions:
                continue
            group_alerts.sort(key=lambda a: int(a.get("startEpoch") or 0))
            still_active = any(not a.get("cleared", False) for a in group_alerts)
            first_epoch = int(group_alerts[0].get("startEpoch") or 0)
            last_epoch = int(group_alerts[-1].get("startEpoch") or 0)

            flaps.append(
                {
                    "device": dev,
                    "interface": inst,
                    "transitions": len(group_alerts),
                    "first_transition": first_epoch,
                    "last_transition": last_epoch,
                    "still_active": still_active,
                    "datasource": group_alerts[0].get("dataSourceName"),
                }
            )

        flaps.sort(key=lambda f: f["transitions"], reverse=True)
        top_flaps = flaps[:50]

        response: dict = {
            "window_hours": hours_back,
            "min_transitions": min_transitions,
            "total_interface_alerts": len(interface_alerts),
            "flapping_interfaces": len(flaps),
            "results": top_flaps,
        }
        if truncated:
            response["warning"] = ALERT_WINDOW_TRUNCATED_WARNING
        if wildcards_stripped:
            response["note"] = (
                "Wildcard characters stripped from device filter — the ~ operator "
                "already performs substring matching."
            )
        return format_response(response)
    except Exception as e:
        return handle_error(e)


async def get_power_events(
    client: LogicMonitorClient,
    group_id: int | None = None,
    device: str | None = None,
    hours_back: int = 2,
    severity: str | None = None,
    patterns: list[str] | None = None,
) -> list[TextContent]:
    """Filter alerts for UPS, PDU, and power-infrastructure signatures.

    Queries alerts in the lookback window, then client-side filters by
    substring match on dataSourceName or alertName against UPS/PDU/battery
    patterns. Patterns are case-insensitive.

    Args:
        client: LogicMonitor API client.
        group_id: Scope to a device group.
        device: Scope to a device name (substring match).
        hours_back: Lookback window in hours (default: 2).
        severity: Filter by severity name.
        patterns: Override default patterns. Default covers APC, Liebert, Eaton,
            UPS, PDU, Battery, PowerSupply, Power_.

    Returns:
        List of TextContent with power events or error.
    """
    try:
        now = int(time.time())
        start_epoch = now - (hours_back * 3600)
        filters: list[str] = [f"startEpoch>:{start_epoch}"]
        wildcards_stripped = False

        if severity and severity.lower() in SEVERITY_MAP:
            filters.append(f"severity:{SEVERITY_MAP[severity.lower()]}")
        if group_id is not None:
            filters.append(await resolve_group_filter(client, group_id))
        if device:
            clean_device, was_modified = sanitize_filter_value(device)
            wildcards_stripped = wildcards_stripped or was_modified
            filters.append(f"monitorObjectName~{quote_filter_value(clean_device)}")

        alerts, truncated, _ = await paginate_alerts(client, ",".join(filters))

        active_patterns = patterns or list(_DEFAULT_POWER_PATTERNS)
        lower_patterns = [p.lower() for p in active_patterns]
        pattern_counts: dict[str, int] = defaultdict(int)
        matched: list[dict] = []

        for alert in alerts:
            ds_name = (alert.get("dataSourceName") or "").lower()
            alert_name = (alert.get("alertName") or "").lower()
            combined = f"{ds_name} {alert_name}"
            matching_patterns = [p for p in lower_patterns if p in combined]
            if not matching_patterns:
                continue
            for p in matching_patterns:
                pattern_counts[p] += 1
            matched.append(
                {
                    "id": alert.get("id"),
                    "severity": alert.get("severity"),
                    "device": alert.get("monitorObjectName"),
                    "datasource": alert.get("dataSourceName"),
                    "datapoint": alert.get("dataPointName"),
                    "alert_value": alert.get("alertValue"),
                    "start_epoch": alert.get("startEpoch"),
                    "cleared": alert.get("cleared", False),
                    "matched_patterns": matching_patterns,
                }
            )

        response: dict = {
            "window_hours": hours_back,
            "patterns_used": active_patterns,
            "total_alerts_scanned": len(alerts),
            "total_power_events": len(matched),
            "patterns_matched_counts": dict(pattern_counts),
            "events": matched,
        }
        if truncated:
            response["warning"] = ALERT_WINDOW_TRUNCATED_WARNING
        if wildcards_stripped:
            response["note"] = (
                "Wildcard characters stripped from device filter — the ~ operator "
                "already performs substring matching."
            )
        return format_response(response)
    except Exception as e:
        return handle_error(e)
