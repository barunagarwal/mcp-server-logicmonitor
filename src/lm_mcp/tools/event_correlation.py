# Description: Event and change correlation tools for LogicMonitor.
# Description: Cross-references alert spikes with audit/change logs.

from __future__ import annotations

import logging
import math
import time
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from mcp.types import TextContent

from lm_mcp.tools import format_response, handle_error
from lm_mcp.tools.alerts import paginate_alerts

if TYPE_CHECKING:
    from lm_mcp.client import LogicMonitorClient

logger = logging.getLogger(__name__)


async def correlate_changes(
    client: LogicMonitorClient,
    hours_back: int = 24,
    correlation_window_minutes: int = 30,
) -> list[TextContent]:
    """Cross-reference alert spikes with audit/change logs.

    Fetches alerts and audit logs, identifies alert spikes (5-min buckets
    exceeding mean + 1 stddev), and correlates them with change events
    within a configurable time window.

    Args:
        client: LogicMonitor API client.
        hours_back: Hours to look back (default: 24).
        correlation_window_minutes: Minutes after a change to look for
            alert spikes (default: 30).

    Returns:
        Correlated events, uncorrelated changes, and uncorrelated spikes.
    """
    try:
        now_epoch = int(time.time())
        start_epoch = now_epoch - (hours_back * 3600)
        window_seconds = correlation_window_minutes * 60

        # Fetch the window's alerts; with no cleared filter the list holds active alerts only
        alerts, truncated, api_total = await paginate_alerts(client, f"startEpoch>:{start_epoch}")

        # Fetch audit/change logs
        audit_params: dict[str, Any] = {
            "size": 300,
            "filter": f"happenedOn>:{start_epoch}",
            "sort": "-happenedOn",
        }
        audit_read_failed = False
        try:
            audit_result = await client.get("/setting/accesslogs", params=audit_params)
            changes = audit_result.get("items", [])
        except Exception:
            logger.warning(
                "correlate_changes: audit log read failed; change correlation "
                "unavailable (treating as zero changes)",
                exc_info=True,
            )
            changes = []
            audit_read_failed = True

        # Bucket alerts into 5-minute windows
        bucket_size = 300  # 5 minutes in seconds
        buckets: dict[int, int] = defaultdict(int)
        for alert in alerts:
            ts = alert.get("startEpoch", 0)
            bucket_key = (ts // bucket_size) * bucket_size
            buckets[bucket_key] = buckets.get(bucket_key, 0) + 1

        # Identify spikes: buckets with count > mean + 1*stddev
        spike_buckets = []
        if buckets:
            counts = list(buckets.values())
            mean_count = sum(counts) / len(counts)
            if len(counts) > 1:
                variance = sum((c - mean_count) ** 2 for c in counts) / (len(counts) - 1)
                stddev_count = math.sqrt(variance)
            else:
                stddev_count = 0.0

            spike_threshold = mean_count + stddev_count
            for bucket_ts, count in sorted(buckets.items()):
                if count > spike_threshold and count > 1:
                    spike_buckets.append(
                        {
                            "timestamp": bucket_ts,
                            "alert_count": count,
                        }
                    )

        # Correlate changes with alert spikes
        correlated_events = []
        correlated_change_ids = set()
        correlated_spike_ts = set()

        for change in changes:
            change_ts = change.get("happenedOn", 0)
            # Convert milliseconds if needed
            if change_ts > 1e12:
                change_ts = int(change_ts / 1000)

            for spike in spike_buckets:
                spike_ts = spike["timestamp"]
                # Check if spike occurred within window after the change
                time_diff = spike_ts - change_ts
                if 0 <= time_diff <= window_seconds:
                    # Confidence: linear decay from 1.0 at 0 to 0.5 at window edge
                    confidence = max(
                        0.5,
                        1.0 - 0.5 * (time_diff / window_seconds),
                    )

                    change_id = change.get("id", id(change))
                    if change_id not in correlated_change_ids:
                        correlated_change_ids.add(change_id)
                        correlated_spike_ts.add(spike_ts)
                        correlated_events.append(
                            {
                                "change": {
                                    "timestamp": change_ts,
                                    "user": change.get(
                                        "username",
                                        change.get("userName", "unknown"),
                                    ),
                                    "description": change.get("description", "unknown"),
                                },
                                "spike": {
                                    "timestamp": spike_ts,
                                    "alert_count": spike["alert_count"],
                                },
                                "time_gap_minutes": round(time_diff / 60.0, 1),
                                "confidence": round(confidence, 2),
                            }
                        )

        # Uncorrelated items
        uncorrelated_changes = [
            {
                "timestamp": c.get("happenedOn", 0),
                "user": c.get("username", c.get("userName", "unknown")),
                "description": c.get("description", "unknown"),
            }
            for c in changes
            if c.get("id", id(c)) not in correlated_change_ids
        ][:20]

        uncorrelated_spikes = [
            s for s in spike_buckets if s["timestamp"] not in correlated_spike_ts
        ]

        response: dict[str, Any] = {
            "total_alerts": len(alerts),
            "truncated": truncated,
            "api_total": api_total,
            "total_changes": len(changes),
            "total_spikes": len(spike_buckets),
            "correlated_events": correlated_events,
            "uncorrelated_changes": uncorrelated_changes[:10],
            "uncorrelated_spikes": uncorrelated_spikes[:10],
            "hours_back": hours_back,
            "correlation_window_minutes": correlation_window_minutes,
        }
        if audit_read_failed:
            response["audit_read_failed"] = True
            response["warning"] = (
                "Audit/change log read failed; change correlation is unavailable for "
                "this window (no changes does NOT mean none occurred)."
            )
        return format_response(response)
    except Exception as e:
        return handle_error(e)
