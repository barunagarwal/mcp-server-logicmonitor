# Description: Scoring and availability analysis tools for LogicMonitor.
# Description: Provides scoring, availability, health, and error budget tools.

from __future__ import annotations

import logging
import math
import time
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from mcp.types import TextContent

from lm_mcp.exceptions import LMError, NotFoundError
from lm_mcp.tools import (
    SEVERITY_MAP,
    call_sub_tool,
    format_response,
    handle_error,
    quote_filter_value,
    resolve_group_filter,
    sanitize_filter_value,
)
from lm_mcp.tools.alerts import paginate_alerts
from lm_mcp.tools.stats_helpers import (
    fetch_metric_series,
    shannon_entropy,
)

if TYPE_CHECKING:
    from lm_mcp.client import LogicMonitorClient

logger = logging.getLogger(__name__)


async def score_alert_noise(
    client: LogicMonitorClient,
    hours_back: int = 24,
    device: str | None = None,
    group_id: int | None = None,
) -> list[TextContent]:
    """Score alert noise level using Shannon entropy and flap detection.

    Analyzes alert frequency distribution and identifies flapping alerts
    (alerts that clear and re-fire within 30 minutes). Produces a noise
    score from 0 (quiet) to 100 (extremely noisy).

    Args:
        client: LogicMonitor API client.
        hours_back: Hours to look back (default: 24).
        device: Optional device name filter.
        group_id: Optional device group ID filter.

    Returns:
        Noise score with entropy, flapping alerts, and recommendations;
        truncated says whether the 5000-alert cap cut the active or the cleared
        read short and api_total is the sum of both reads' API counts, null
        when either reported only a lower bound.
    """
    try:
        now_epoch = int(time.time())
        start_epoch = now_epoch - (hours_back * 3600)

        # Fetch the window's active and cleared alerts; flap detection needs the cleared ones
        filters = [f"startEpoch>:{start_epoch}"]
        if device:
            clean_val, _ = sanitize_filter_value(device)
            filters.append(f"monitorObjectName~{quote_filter_value(clean_val)}")
        if group_id is not None:
            filters.append(await resolve_group_filter(client, group_id))

        alerts, truncated, api_total = await _read_cleared_and_active(client, ",".join(filters))

        if not alerts:
            return format_response(
                {
                    "noise_score": 0,
                    "entropy": 0.0,
                    "total_alerts": 0,
                    "truncated": truncated,
                    "api_total": api_total,
                    "flapping_alerts": [],
                    "top_noisy_devices": [],
                    "top_noisy_datasources": [],
                    "recommendations": ["No alerts in the time window."],
                    "hours_back": hours_back,
                }
            )

        # Count alerts by datasource+datapoint combo for entropy
        combo_counts: dict[str, int] = defaultdict(int)
        device_counts: dict[str, int] = defaultdict(int)
        ds_counts: dict[str, int] = defaultdict(int)

        for alert in alerts:
            ds = alert.get("resourceTemplateName", "unknown")
            dp = alert.get("dataPointName", "unknown")
            dev = alert.get("monitorObjectName", "unknown")
            combo_counts[f"{ds}:{dp}"] += 1
            device_counts[dev] += 1
            ds_counts[ds] += 1

        # Shannon entropy of alert frequency distribution
        total = sum(combo_counts.values())
        probabilities = [c / total for c in combo_counts.values()]
        entropy = shannon_entropy(probabilities)
        # Normalize: max entropy = log2(num combos)
        max_entropy = math.log2(len(combo_counts)) if len(combo_counts) > 1 else 1.0
        normalized_entropy = entropy / max_entropy if max_entropy > 0 else 0.0

        # Flap detection: same device+datapoint clears then re-fires within 30 min
        alert_events: dict[str, list[dict]] = defaultdict(list)
        for alert in alerts:
            dev = alert.get("monitorObjectName", "unknown")
            dp = alert.get("dataPointName", "unknown")
            key = f"{dev}:{dp}"
            alert_events[key].append(alert)

        flapping_alerts = []
        flap_count = 0
        for key, events in alert_events.items():
            # Sort by start time
            sorted_events = sorted(events, key=lambda a: a.get("startEpoch", 0))
            for i in range(1, len(sorted_events)):
                prev = sorted_events[i - 1]
                curr = sorted_events[i]
                prev_end = prev.get("endEpoch", 0)
                curr_start = curr.get("startEpoch", 0)
                # endEpoch=0 means still active, skip for flap detection; an alert
                # that starts before the previous one cleared overlaps it, no re-fire
                if prev_end > 0 and 0 <= curr_start - prev_end < 1800:
                    flap_count += 1
                    if len(flapping_alerts) < 10:
                        flapping_alerts.append(
                            {
                                "key": key,
                                "gap_seconds": curr_start - prev_end,
                                "alert_id": curr.get("id"),
                            }
                        )

        # Repeat ratio: alerts from same combo appearing 3+ times
        repeat_count = sum(1 for c in combo_counts.values() if c >= 3)
        repeat_ratio = repeat_count / len(combo_counts) if combo_counts else 0.0

        flap_ratio = flap_count / len(alerts) if alerts else 0.0

        # Noise score: weighted combination (entropy 40%, flap 30%, repeat 30%)
        noise_score = min(100, int(normalized_entropy * 40 + flap_ratio * 30 + repeat_ratio * 30))

        # Top noisy devices and datasources
        top_devices = sorted(device_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        top_datasources = sorted(ds_counts.items(), key=lambda x: x[1], reverse=True)[:5]

        # Recommendations
        recommendations = []
        if flap_count > 0:
            recommendations.append(
                f"{flap_count} flapping alert(s) detected. "
                "Consider adding alert delay or hysteresis."
            )
        if repeat_ratio > 0.5:
            recommendations.append(
                "High repeat ratio. Review alert thresholds and consider consolidation rules."
            )
        if noise_score > 70:
            recommendations.append(
                "Very high noise level. Review top noisy devices "
                "and datasources for tuning opportunities."
            )
        if not recommendations:
            recommendations.append("Alert noise levels are acceptable.")

        # Best practice guardrails
        from lm_mcp.resources.best_practices import get_best_practices

        if noise_score > 50:
            bp = get_best_practices("high_alert_noise").get("high_alert_noise", {})
            structured_recs = bp.get("recommended_actions", [])
            anti_patterns = bp.get("anti_patterns", [])
        else:
            structured_recs = []
            anti_patterns = []

        result_data: dict = {
            "noise_score": noise_score,
            "entropy": round(entropy, 4),
            "normalized_entropy": round(normalized_entropy, 4),
            "total_alerts": len(alerts),
            "truncated": truncated,
            "api_total": api_total,
            "flap_count": flap_count,
            "flapping_alerts": flapping_alerts,
            "repeat_ratio": round(repeat_ratio, 4),
            "top_noisy_devices": [{"device": d, "count": c} for d, c in top_devices],
            "top_noisy_datasources": [{"datasource": ds, "count": c} for ds, c in top_datasources],
            "recommendations": recommendations,
            "structured_recommendations": structured_recs,
            "hours_back": hours_back,
        }
        if noise_score > 50:
            result_data["anti_patterns"] = anti_patterns

        return format_response(result_data)
    except Exception as e:
        return handle_error(e)


async def calculate_availability(
    client: LogicMonitorClient,
    device_id: int | None = None,
    device_name: str | None = None,
    group_id: int | None = None,
    hours_back: int = 720,
    severity_threshold: str = "error",
) -> list[TextContent]:
    """Calculate availability percentage from alert history.

    Fetches cleared and active alerts at or above the severity threshold,
    computes downtime windows, merges overlapping incidents, and calculates
    SLA-style availability metrics.

    Args:
        client: LogicMonitor API client.
        device_id: Optional device ID filter.
        device_name: Optional device display name filter.
        group_id: Optional device group ID filter; not with a device.
        hours_back: Hours to look back (default: 720 = 30 days).
        severity_threshold: Minimum severity to count as downtime
            (critical, error, warning, info). Default: error.

    Returns:
        Availability percentage, downtime, MTTR, and per-device breakdown;
        a device that does not resolve is an error, never 100 percent.
    """
    try:
        now_epoch = int(time.time())
        start_epoch = now_epoch - (hours_back * 3600)
        total_window_minutes = hours_back * 60

        # A device's alert list ignores group filters, so a device and a group
        # together have no single scope to read.
        if group_id is not None and (device_id is not None or device_name is not None):
            return format_response(
                {
                    "error": True,
                    "code": "INVALID_PARAMETER",
                    "message": (
                        "Pass a device (device_id or device_name) or group_id, not both: "
                        "a device's alert list cannot be filtered by group."
                    ),
                    "suggestion": (
                        "Drop group_id for the device's availability, "
                        "or drop the device for the group's."
                    ),
                }
            )

        # Resolve the device before reading any alert. A device that does not
        # exist is an error, not a clean 100 percent, and a failed lookup must
        # not fall through to availability for an unfiltered alert set.
        device: dict | None = None
        if device_id is not None or device_name is not None:
            device = await _resolve_device(client, device_id, device_name)
            if device.get("error"):
                return format_response(device)

        # Build filter for alerts at or above severity threshold
        min_severity = SEVERITY_MAP.get(severity_threshold.lower(), 3)
        filters = [f"startEpoch>:{start_epoch}"]

        if min_severity < 4:
            filters.append(f"severity>:{min_severity}")
        else:
            filters.append(f"severity:{min_severity}")

        if group_id is not None:
            filters.append(await resolve_group_filter(client, group_id))

        # The /alert/alerts filters ignore a device id, so a resolved device
        # reads its own alert list, which keeps alerts recorded under an
        # earlier display name.
        alert_path = "/alert/alerts" if device is None else f"/device/devices/{device['id']}/alerts"
        alerts, truncated, api_total = await _read_cleared_and_active(
            client, ",".join(filters), path=alert_path
        )

        scope: dict[str, Any] = {"truncated": truncated, "api_total": api_total}
        if device is not None:
            scope["device_resolved"] = True
            scope["device_id"] = device["id"]

        if not alerts:
            return format_response(
                {
                    "availability_percent": 100.0,
                    "total_downtime_minutes": 0,
                    "total_uptime_minutes": total_window_minutes,
                    "mttr_minutes": 0,
                    "incident_count": 0,
                    "longest_incident_minutes": 0,
                    "by_device": {},
                    "hours_back": hours_back,
                    "severity_threshold": severity_threshold,
                    **scope,
                }
            )

        # Group alerts by device and compute downtime windows; a resolved
        # device's alerts all count under its current display name.
        device_alerts: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for alert in alerts:
            if device is not None:
                dev = device.get("displayName") or str(device["id"])
            else:
                dev = alert.get("monitorObjectName", "unknown")
            alert_start = max(alert.get("startEpoch", 0), start_epoch)
            alert_end = alert.get("endEpoch", 0)
            if alert_end == 0:
                alert_end = now_epoch  # Still active
            alert_end = min(alert_end, now_epoch)
            if alert_start < alert_end:
                device_alerts[dev].append((alert_start, alert_end))

        # Merge overlapping intervals per device
        by_device = {}
        total_downtime_seconds = 0
        incident_count = 0
        longest_incident = 0
        incident_durations = []

        for dev, intervals in device_alerts.items():
            merged = _merge_intervals(intervals)
            dev_downtime = sum(end - start for start, end in merged)
            dev_downtime_min = dev_downtime / 60.0
            dev_availability = max(
                0.0,
                (1.0 - dev_downtime / (total_window_minutes * 60)) * 100,
            )

            for start, end in merged:
                dur = (end - start) / 60.0
                incident_durations.append(dur)
                if dur > longest_incident:
                    longest_incident = dur

            total_downtime_seconds += dev_downtime
            incident_count += len(merged)

            by_device[dev] = {
                "availability_percent": round(dev_availability, 4),
                "downtime_minutes": round(dev_downtime_min, 2),
                "incident_count": len(merged),
            }

        # Aggregate availability across all devices
        # Use worst-device availability as the aggregate
        if by_device:
            worst_availability = min(d["availability_percent"] for d in by_device.values())
        else:
            worst_availability = 100.0

        mttr = sum(incident_durations) / len(incident_durations) if incident_durations else 0

        # Measurement window context for low availability
        measurement_context: dict = {}
        if worst_availability < 99.9:
            from lm_mcp.resources.best_practices import get_best_practices

            bp = get_best_practices("availability_low").get("availability_low", {})
            measurement_context = {
                "measurement_window_hours": hours_back,
                "severity_threshold": severity_threshold,
                "recommendations": bp.get("recommended_actions", []),
                "anti_patterns": bp.get("anti_patterns", []),
            }

        return format_response(
            {
                "availability_percent": round(worst_availability, 4),
                "total_downtime_minutes": round(total_downtime_seconds / 60.0, 2),
                "total_uptime_minutes": round(
                    max(0.0, total_window_minutes - total_downtime_seconds / 60.0), 2
                ),
                "mttr_minutes": round(mttr, 2),
                "incident_count": incident_count,
                "longest_incident_minutes": round(longest_incident, 2),
                "by_device": by_device,
                "hours_back": hours_back,
                "severity_threshold": severity_threshold,
                "measurement_window_context": measurement_context,
                **scope,
            }
        )
    except Exception as e:
        return handle_error(e)


async def _read_cleared_and_active(
    client: LogicMonitorClient,
    filter_str: str,
    path: str = "/alert/alerts",
) -> tuple[list[dict], bool, int | None]:
    """Read a window's active and cleared alerts as one list.

    Both alert lists return active alerts only unless the filter carries
    cleared:true, so the window takes two reads, each under the alert cap. An
    alert that clears between the reads appears in both and is kept once, as
    the cleared copy, which carries its endEpoch.

    Args:
        client: LogicMonitor API client.
        filter_str: Filter string for the active read; the cleared read adds
            cleared:true to it.
        path: Alert list to read, as paginate_alerts takes it.

    Returns:
        The alerts, whether the cap cut either read short, and the sum of both
        API totals, or None when either reported only a lower bound.
    """
    active, active_cut, active_total = await paginate_alerts(client, filter_str, path=path)
    cleared, cleared_cut, cleared_total = await paginate_alerts(
        client, f"{filter_str},cleared:true", path=path
    )
    cleared_ids = {alert["id"] for alert in cleared if alert.get("id") is not None}
    alerts = [alert for alert in active if alert.get("id") not in cleared_ids] + cleared
    api_total = (
        None if active_total is None or cleared_total is None else active_total + cleared_total
    )
    return alerts, active_cut or cleared_cut, api_total


async def _resolve_device(
    client: LogicMonitorClient,
    device_id: int | None,
    device_name: str | None,
) -> dict:
    """Resolve a device by id, or by exact display name, to its id and display name.

    Args:
        client: LogicMonitor API client.
        device_id: Device ID; takes precedence over device_name.
        device_name: Exact device display name.

    Returns:
        The device with id and displayName, or an error dict with code
        DEVICE_NOT_FOUND or DEVICE_LOOKUP_FAILED.
    """
    target = f"device {device_id}" if device_id is not None else f"device named '{device_name}'"
    try:
        if device_id is not None:
            found: dict | None = await client.get(f"/device/devices/{device_id}")
        else:
            result = await client.get(
                "/device/devices",
                params={
                    "filter": f"displayName:{quote_filter_value(device_name or '')}",
                    "fields": "id,displayName",
                    "size": 1,
                },
            )
            items = result.get("items", [])
            found = items[0] if items else None
    except NotFoundError:
        found = None
    except LMError as exc:
        logger.warning("Could not look up %s for availability", target, exc_info=True)
        return {
            "error": True,
            "code": "DEVICE_LOOKUP_FAILED",
            "message": (
                f"Could not look up {target}: {exc}. "
                "Availability cannot be computed without confirming the device."
            ),
            "suggestion": "Verify the device exists and the API token has read access.",
        }
    if not found:
        return {
            "error": True,
            "code": "DEVICE_NOT_FOUND",
            "message": f"{target.capitalize()} not found, so its availability is unknown.",
            "suggestion": (
                "Check the device_id, or pass the exact display name; get_devices lists both."
            ),
        }
    return found


def _merge_intervals(
    intervals: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    """Merge overlapping time intervals using sort-by-start greedy merge.

    Args:
        intervals: List of (start, end) epoch pairs.

    Returns:
        Merged list of non-overlapping intervals.
    """
    if not intervals:
        return []

    sorted_intervals = sorted(intervals, key=lambda x: x[0])
    merged = [sorted_intervals[0]]

    for start, end in sorted_intervals[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))

    return merged


async def score_device_health(
    client: LogicMonitorClient,
    device_id: int,
    device_datasource_id: int,
    instance_id: int,
    datapoints: str | None = None,
    hours_back: int = 4,
    weights: dict[str, float] | None = None,
) -> list[TextContent]:
    """Compute a composite health score (0-100) for a device instance.

    Fetches metric data, computes z-scores for the latest value of each
    datapoint against its historical distribution, and aggregates into
    a single health score.

    Args:
        client: LogicMonitor API client.
        device_id: Device ID.
        device_datasource_id: Device-DataSource ID.
        instance_id: Instance ID.
        datapoints: Comma-separated datapoint names (all if omitted).
        hours_back: Hours of historical data for z-score baseline (default: 4).
        weights: Optional dict of datapoint_name -> weight for scoring.

    Returns:
        Health score with status, contributing factors, and anomaly count.
    """
    try:
        series = await fetch_metric_series(
            client,
            device_id,
            device_datasource_id,
            instance_id,
            datapoints=datapoints,
            hours_back=hours_back,
        )

        if not series:
            return format_response(
                {
                    "device_id": device_id,
                    "health_score": 100,
                    "status": "unknown",
                    "message": "No metric data available",
                    "contributing_factors": [],
                    "anomaly_count": 0,
                }
            )

        factors = []
        anomaly_count = 0

        for dp_name, dp_data in series.items():
            values = dp_data["values"]

            if len(values) < 2:
                continue

            mean = sum(values) / len(values)
            variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
            stddev = math.sqrt(variance) if variance > 0 else 0.0

            latest = values[-1]

            z_score = abs(latest - mean) / stddev if stddev > 0 else 0.0

            weight = 1.0
            if weights and dp_name in weights:
                weight = weights[dp_name]

            if z_score > 2.0:
                anomaly_count += 1

            factors.append(
                {
                    "datapoint": dp_name,
                    "latest_value": round(latest, 4),
                    "mean": round(mean, 4),
                    "stddev": round(stddev, 4),
                    "z_score": round(z_score, 2),
                    "weight": weight,
                    "weighted_impact": round(z_score * weight, 4),
                }
            )

        # Sort by weighted impact (most impactful first)
        factors.sort(key=lambda f: f["weighted_impact"], reverse=True)

        # Health score: start at 100, subtract weighted z-scores
        if factors:
            total_weight = sum(f["weight"] for f in factors)
            weighted_z_sum = sum(f["z_score"] * f["weight"] for f in factors)
            avg_weighted_z = weighted_z_sum / total_weight if total_weight > 0 else 0
            health_score = max(0, int(100 - avg_weighted_z * 15))
        else:
            health_score = 100

        # Status classification
        if health_score >= 80:
            status = "healthy"
        elif health_score >= 50:
            status = "degraded"
        else:
            status = "critical"

        # Best practice guardrails
        from lm_mcp.resources.best_practices import get_best_practices

        structured_recs: list[dict] = []
        anti_patterns: list[str] = []
        if health_score < 50:
            bp = get_best_practices("device_health_low").get("device_health_low", {})
            structured_recs = bp.get("recommended_actions", [])
            anti_patterns = bp.get("anti_patterns", [])
        elif health_score < 80:
            structured_recs = [
                {
                    "action": "Monitor trend",
                    "how": "Re-check health score in 1-2 hours to detect worsening",
                    "priority": "low",
                }
            ]

        result_data: dict = {
            "device_id": device_id,
            "device_datasource_id": device_datasource_id,
            "instance_id": instance_id,
            "health_score": health_score,
            "status": status,
            "contributing_factors": factors,
            "anomaly_count": anomaly_count,
            "recommendations": structured_recs,
            "hours_back": hours_back,
        }
        if health_score < 50:
            result_data["anti_patterns"] = anti_patterns

        return format_response(result_data)
    except Exception as e:
        return handle_error(e)


async def calculate_error_budget(
    client: LogicMonitorClient,
    device_id: int | None = None,
    group_id: int | None = None,
    target_slo: float = 99.9,
    period_days: int = 30,
) -> list[TextContent]:
    """Calculate SLO error budget consumption and projected exhaustion.

    Calls calculate_availability internally, then computes remaining
    error budget based on the target SLO.

    Args:
        client: LogicMonitor API client.
        device_id: Optional device ID filter.
        group_id: Optional device group ID filter.
        target_slo: Target SLO percentage (default: 99.9).
        period_days: SLO measurement period in days (default: 30).

    Returns:
        Error budget status with remaining minutes and burn rate.
    """
    try:
        # Route through call_sub_tool so an upstream error from
        # calculate_availability (e.g. DEVICE_LOOKUP_FAILED above) surfaces
        # as a clean RuntimeError rather than a JSONDecodeError -- this is
        # the same hardening v3.8.2 added to workflow composites.
        avail_data = await call_sub_tool(
            calculate_availability,
            client,
            device_id=device_id,
            group_id=group_id,
            hours_back=period_days * 24,
        )

        total_minutes = period_days * 24 * 60
        total_budget_minutes = total_minutes * (1 - target_slo / 100)
        consumed_minutes = avail_data.get("total_downtime_minutes", 0)
        remaining_minutes = max(0.0, total_budget_minutes - consumed_minutes)

        # Calculate elapsed days in the period
        elapsed_days = period_days  # Full period for historical calculation

        # Burn rate: how fast we are consuming the budget
        if elapsed_days > 0 and total_budget_minutes > 0:
            burn_rate = consumed_minutes / (elapsed_days * (total_budget_minutes / period_days))
        else:
            burn_rate = 0.0

        # Projected exhaustion
        if burn_rate > 0 and remaining_minutes > 0:
            daily_consumption = consumed_minutes / elapsed_days if elapsed_days > 0 else 0
            projected_exhaustion_days = (
                remaining_minutes / daily_consumption if daily_consumption > 0 else None
            )
        else:
            projected_exhaustion_days = None

        # Budget consumption percentage
        budget_consumed_percent = (
            (consumed_minutes / total_budget_minutes * 100) if total_budget_minutes > 0 else 0.0
        )

        # Status classification
        # Edge case: 100% SLO means zero budget. If no downtime
        # occurred, treat it as healthy rather than exhausted.
        if total_budget_minutes == 0 and consumed_minutes == 0:
            status = "healthy"
        elif remaining_minutes <= 0:
            status = "exhausted"
        elif budget_consumed_percent > 90:
            status = "critical"
        elif budget_consumed_percent > 50:
            status = "warning"
        else:
            status = "healthy"

        return format_response(
            {
                "target_slo": target_slo,
                "period_days": period_days,
                "actual_availability": avail_data.get("availability_percent", 100.0),
                "total_budget_minutes": round(total_budget_minutes, 2),
                "consumed_minutes": round(consumed_minutes, 2),
                "remaining_minutes": round(remaining_minutes, 2),
                "budget_consumed_percent": round(budget_consumed_percent, 2),
                "burn_rate": round(burn_rate, 4),
                "projected_exhaustion_days": (
                    round(projected_exhaustion_days, 1)
                    if projected_exhaustion_days is not None
                    else None
                ),
                "status": status,
                "incident_count": avail_data.get("incident_count", 0),
            }
        )
    except Exception as e:
        return handle_error(e)
