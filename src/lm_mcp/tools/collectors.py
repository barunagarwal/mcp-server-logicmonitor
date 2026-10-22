# Description: Collector management tools for LogicMonitor MCP server.
# Description: Provides collector and collector group CRUD functions.

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from mcp.types import TextContent

from lm_mcp.tools import (
    WILDCARD_STRIP_NOTE,
    format_response,
    handle_error,
    paginated_response,
    quote_filter_value,
    require_write_permission,
    safe_total,
    sanitize_filter_value,
)

if TYPE_CHECKING:
    from lm_mcp.client import LogicMonitorClient

logger = logging.getLogger(__name__)


async def get_collectors(
    client: LogicMonitorClient,
    hostname_filter: str | None = None,
    collector_group_id: int | None = None,
    filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[TextContent]:
    """List collectors from LogicMonitor.

    Args:
        client: LogicMonitor API client.
        hostname_filter: Filter by hostname (supports wildcards).
        collector_group_id: Filter by collector group ID.
        filter: Raw filter expression for advanced queries (overrides other filters).
            Supports LogicMonitor filter syntax with operators:
            : (equal), !: (not equal), > < >: <: (comparisons),
            ~ (contains), !~ (not contains).
            Examples: "hostname~prod,collectorGroupId:1"
        limit: Maximum number of collectors to return.
        offset: Number of results to skip for pagination.

    Returns:
        List of TextContent with collector data or error.
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
            if hostname_filter:
                clean_hostname, was_modified = sanitize_filter_value(hostname_filter)
                wildcards_stripped = wildcards_stripped or was_modified
                filters.append(f"hostname~{quote_filter_value(clean_hostname)}")
            if collector_group_id is not None:
                filters.append(f"collectorGroupId:{collector_group_id}")

            if filters:
                params["filter"] = ",".join(filters)

        result = await client.get("/setting/collector/collectors", params=params)

        collectors = []
        for item in result.get("items", []):
            collectors.append(
                {
                    "id": item.get("id"),
                    "hostname": item.get("hostname"),
                    "status": item.get("status"),
                    "device_count": item.get("numberOfHosts"),
                }
            )

        response = {
            **paginated_response(collectors, result, offset),
            "collectors": collectors,
        }
        if wildcards_stripped:
            response["note"] = WILDCARD_STRIP_NOTE
        return format_response(response)
    except Exception as e:
        return handle_error(e)


async def get_collector(
    client: LogicMonitorClient,
    collector_id: int,
) -> list[TextContent]:
    """Get detailed information about a specific collector.

    Args:
        client: LogicMonitor API client.
        collector_id: Collector ID.

    Returns:
        List of TextContent with collector details or error.
    """
    try:
        result = await client.get(f"/setting/collector/collectors/{collector_id}")
        return format_response(result)
    except Exception as e:
        return handle_error(e)


async def get_collector_groups(
    client: LogicMonitorClient,
    name_filter: str | None = None,
    filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[TextContent]:
    """List collector groups from LogicMonitor.

    Args:
        client: LogicMonitor API client.
        name_filter: Filter by group name (supports wildcards).
        filter: Raw filter expression for advanced queries (overrides name_filter).
            Supports LogicMonitor filter syntax with operators:
            : (equal), !: (not equal), > < >: <: (comparisons),
            ~ (contains), !~ (not contains).
            Examples: "name~prod,autoBalance:true"
        limit: Maximum number of groups to return.
        offset: Number of results to skip for pagination.

    Returns:
        List of TextContent with collector group data or error.
    """
    try:
        params: dict = {"size": limit, "offset": offset}
        wildcards_stripped = False

        # If raw filter is provided, use it directly (power user mode)
        if filter:
            params["filter"] = filter
        elif name_filter:
            clean_name, was_modified = sanitize_filter_value(name_filter)
            wildcards_stripped = wildcards_stripped or was_modified
            params["filter"] = f"name~{quote_filter_value(clean_name)}"

        result = await client.get("/setting/collector/groups", params=params)

        groups = []
        for item in result.get("items", []):
            groups.append(
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "description": item.get("description"),
                    "num_of_collectors": item.get("numOfCollectors"),
                    "auto_balance": item.get("autoBalance"),
                    "auto_balance_strategy": item.get("autoBalanceStrategy"),
                }
            )

        response = {
            "total": result.get("total", 0),
            "count": len(groups),
            "collector_groups": groups,
        }
        if wildcards_stripped:
            response["note"] = WILDCARD_STRIP_NOTE
        return format_response(response)
    except Exception as e:
        return handle_error(e)


async def get_collector_group(
    client: LogicMonitorClient,
    group_id: int,
) -> list[TextContent]:
    """Get detailed information about a specific collector group.

    Args:
        client: LogicMonitor API client.
        group_id: Collector group ID.

    Returns:
        List of TextContent with collector group details or error.
    """
    try:
        result = await client.get(f"/setting/collector/groups/{group_id}")

        group = {
            "id": result.get("id"),
            "name": result.get("name"),
            "description": result.get("description"),
            "num_of_collectors": result.get("numOfCollectors"),
            "auto_balance": result.get("autoBalance"),
            "auto_balance_strategy": result.get("autoBalanceStrategy"),
            "auto_balance_instance_count_threshold": result.get(
                "autoBalanceInstanceCountThreshold"
            ),
            "custom_properties": [
                {"name": p.get("name"), "value": p.get("value")}
                for p in result.get("customProperties", [])
            ],
        }

        return format_response(group)
    except Exception as e:
        return handle_error(e)


async def get_collector_health(
    client: LogicMonitorClient,
    collector_id: int | None = None,
    collector_group_id: int | None = None,
    include_history: bool = False,
    history_days: int = 7,
) -> list[TextContent]:
    """Enriched collector status with downstream device count and CollectorDown history.

    Reports collector health signals critical for detecting site-level events
    (power outages, network partitions). Status is enriched with whether the
    collector is currently down, how many devices it monitors, and optionally
    the history of CollectorDown alerts over a lookback window.

    Args:
        client: LogicMonitor API client.
        collector_id: Single collector ID. If set, other scope args are ignored.
        collector_group_id: Restrict to collectors in this group.
        include_history: Include recent CollectorDown alert history (default: False).
        history_days: CollectorDown history lookback in days (default: 7).

    Returns:
        List of TextContent with enriched collector records.
    """
    try:
        if collector_id is not None:
            collectors = [await client.get(f"/setting/collector/collectors/{collector_id}")]
        else:
            params: dict = {"size": 100}
            if collector_group_id is not None:
                params["filter"] = f"collectorGroupId:{collector_group_id}"
            list_result = await client.get("/setting/collector/collectors", params=params)
            collectors = list_result.get("items", [])

        enriched: list[dict] = []
        for col in collectors:
            enriched.append(await _enrich_collector(client, col, include_history, history_days))

        down_count = sum(1 for c in enriched if c["is_down"])
        unknown_signal = sum(1 for c in enriched if c.get("down_signal_unavailable"))

        response: dict = {
            "total_collectors": len(enriched),
            "collectors_down": down_count,
            "include_history": include_history,
            "history_days": history_days if include_history else None,
            "collectors": enriched,
        }
        if unknown_signal:
            response["collectors_down_signal_unavailable"] = unknown_signal
            response["warning"] = (
                f"{unknown_signal} of {len(enriched)} collector(s) could not be checked "
                "for active CollectorDown alerts; collectors_down may be undercounted."
            )
        return format_response(response)
    except Exception as e:
        return handle_error(e)


async def _enrich_collector(
    client: LogicMonitorClient,
    col: dict,
    include_history: bool,
    history_days: int,
) -> dict:
    """Attach downstream device count and CollectorDown signals to a collector."""
    cid = col.get("id")
    hostname = col.get("hostname") or ""
    status = col.get("status")
    num_hosts_reported = col.get("numberOfHosts") or 0

    downstream_count = num_hosts_reported
    try:
        device_result = await client.get(
            "/device/devices",
            params={
                "size": 1,
                "filter": f"currentCollectorId:{cid}",
            },
        )
        downstream_count = safe_total(device_result)
    except Exception:
        # Fall back to numberOfHosts from the collector record when the
        # devices filter is not supported.
        logger.warning(
            "collector %s: downstream device count query failed; using reported "
            "numberOfHosts as fallback",
            cid,
            exc_info=True,
        )
        downstream_count = num_hosts_reported

    active_collector_down = await _active_collector_down_count(client, hostname)
    down_signal_unavailable = active_collector_down is None
    active_down = active_collector_down or 0

    history: list[dict] = []
    if include_history and hostname:
        history = await _collector_down_history(client, hostname, history_days)

    is_down = bool(active_down) or _status_indicates_down(status)

    record: dict = {
        "id": cid,
        "hostname": hostname,
        "collector_group_id": col.get("collectorGroupId"),
        "collector_group_name": col.get("collectorGroupName"),
        "platform": col.get("platform"),
        "status": status,
        "is_down": is_down,
        "downstream_device_count": downstream_count,
        "reported_numberOfHosts": num_hosts_reported,
        "active_collector_down_alerts": active_down,
        "up_time_seconds": col.get("upTime"),
    }
    if down_signal_unavailable:
        record["down_signal_unavailable"] = True
    if include_history:
        record["collector_down_history"] = history
    return record


def _status_indicates_down(status: int | str | None) -> bool:
    """Conservative interpretation of the LM collector status field.

    The LM API returns status as either an integer code or a short string
    depending on the portal generation. We treat anything that is not
    clearly a "normal"/"up" signal as not-down to avoid false positives;
    the authoritative signal is the presence of an active CollectorDown
    alert, which is checked separately.
    """
    if status is None:
        return False
    if isinstance(status, str):
        lowered = status.lower()
        return lowered in {"dead", "down", "critical"}
    return False


async def _active_collector_down_count(
    client: LogicMonitorClient,
    hostname: str,
) -> int | None:
    """Count active CollectorDown alerts for a collector hostname.

    Returns None (not 0) when the alert query fails, so the caller can distinguish "no
    active CollectorDown alerts" from "could not determine" and avoid reporting a real
    outage as zero collectors down.
    """
    if not hostname:
        return 0
    try:
        result = await client.get(
            "/alert/alerts",
            params={
                "size": 10,
                "filter": (
                    "type:alert,"
                    f"monitorObjectName:{quote_filter_value(hostname)},"
                    "cleared:false,"
                    'alertType~"CollectorDown"'
                ),
            },
        )
    except Exception:
        logger.exception(
            "collector-down alert query failed for hostname=%s; down signal unavailable",
            hostname,
        )
        return None
    return len(result.get("items", []))


async def _collector_down_history(
    client: LogicMonitorClient,
    hostname: str,
    history_days: int,
) -> list[dict]:
    """Fetch recent CollectorDown alerts for a collector hostname."""
    start_epoch = int(time.time()) - (history_days * 86400)
    try:
        result = await client.get(
            "/alert/alerts",
            params={
                "size": 100,
                "filter": (
                    f"monitorObjectName:{quote_filter_value(hostname)},"
                    f"startEpoch>:{start_epoch},"
                    'alertType~"CollectorDown"'
                ),
            },
        )
    except Exception:
        logger.warning(
            "collector history query failed for hostname=%s; returning empty history",
            hostname,
            exc_info=True,
        )
        return []

    history: list[dict] = []
    for item in result.get("items", []):
        history.append(
            {
                "alert_id": item.get("id"),
                "severity": item.get("severity"),
                "start_epoch": item.get("startEpoch"),
                "end_epoch": item.get("endEpoch"),
                "cleared": item.get("cleared", False),
                "alert_type": item.get("alertType"),
            }
        )
    return history


@require_write_permission
async def update_collector(
    client: LogicMonitorClient,
    collector_id: int,
    description: str | None = None,
    collector_group_id: int | None = None,
    enable_failback: bool | None = None,
    escalation_chain_id: int | None = None,
) -> list[TextContent]:
    """Update a collector in LogicMonitor.

    Args:
        client: LogicMonitor API client.
        collector_id: Collector ID to update.
        description: New description.
        collector_group_id: New collector group ID.
        enable_failback: Enable automatic failback.
        escalation_chain_id: Escalation chain ID for collector down alerts.

    Returns:
        List of TextContent with updated collector details or error.
    """
    try:
        body: dict = {}

        if description is not None:
            body["description"] = description
        if collector_group_id is not None:
            body["collectorGroupId"] = collector_group_id
        if enable_failback is not None:
            body["enableFailBack"] = enable_failback
        if escalation_chain_id is not None:
            body["escalatingChainId"] = escalation_chain_id

        if not body:
            return format_response(
                {
                    "error": True,
                    "code": "NO_CHANGES",
                    "message": "No updates provided",
                }
            )

        result = await client.patch(f"/setting/collector/collectors/{collector_id}", json_body=body)

        return format_response(
            {
                "message": "Collector updated successfully",
                "collector": {
                    "id": result.get("id"),
                    "hostname": result.get("hostname"),
                    "collector_group_id": result.get("collectorGroupId"),
                    "collector_group_name": result.get("collectorGroupName"),
                    "description": result.get("description"),
                },
            }
        )
    except Exception as e:
        return handle_error(e)


@require_write_permission
async def delete_collector(
    client: LogicMonitorClient,
    collector_id: int,
) -> list[TextContent]:
    """Delete a collector from LogicMonitor.

    Blocks deletion if the collector still has devices assigned to prevent
    orphaning monitored resources.

    Args:
        client: LogicMonitor API client.
        collector_id: Collector ID to delete.

    Returns:
        List of TextContent with deletion confirmation or error.
    """
    try:
        collector = await client.get(f"/setting/collector/collectors/{collector_id}")
        hostname = collector.get("hostname", f"ID:{collector_id}")
        device_count = collector.get("numberOfHosts", 0)

        if device_count > 0:
            return format_response(
                {
                    "error": True,
                    "code": "COLLECTOR_HAS_DEVICES",
                    "message": f"Collector '{hostname}' has {device_count} devices assigned. "
                    "Move or delete devices before removing the collector.",
                    "collector_id": collector_id,
                    "device_count": device_count,
                }
            )

        await client.delete(f"/setting/collector/collectors/{collector_id}")

        return format_response(
            {
                "success": True,
                "message": f"Collector '{hostname}' deleted",
                "collector_id": collector_id,
            }
        )
    except Exception as e:
        return handle_error(e)


@require_write_permission
async def create_collector_group(
    client: LogicMonitorClient,
    name: str,
    description: str | None = None,
    auto_balance: bool | None = None,
    auto_balance_strategy: str | None = None,
    custom_properties: dict[str, str] | None = None,
) -> list[TextContent]:
    """Create a collector group in LogicMonitor.

    Args:
        client: LogicMonitor API client.
        name: Name of the collector group.
        description: Optional description.
        auto_balance: Enable auto-balancing of devices across collectors.
        auto_balance_strategy: Strategy for auto-balance (e.g., roundRobin).
        custom_properties: Optional custom properties as key-value pairs.

    Returns:
        List of TextContent with created group info or error.
    """
    try:
        body: dict = {"name": name}

        if description is not None:
            body["description"] = description
        if auto_balance is not None:
            body["autoBalance"] = auto_balance
        if auto_balance_strategy is not None:
            body["autoBalanceStrategy"] = auto_balance_strategy
        if custom_properties is not None:
            body["customProperties"] = [
                {"name": k, "value": v} for k, v in custom_properties.items()
            ]

        result = await client.post("/setting/collector/groups", json_body=body)

        return format_response(
            {
                "success": True,
                "message": f"Collector group '{name}' created",
                "group_id": result.get("id"),
                "result": result,
            }
        )
    except Exception as e:
        return handle_error(e)


@require_write_permission
async def update_collector_group(
    client: LogicMonitorClient,
    group_id: int,
    name: str | None = None,
    description: str | None = None,
    auto_balance: bool | None = None,
    auto_balance_strategy: str | None = None,
    custom_properties: dict[str, str] | None = None,
) -> list[TextContent]:
    """Update a collector group in LogicMonitor.

    Args:
        client: LogicMonitor API client.
        group_id: Collector group ID to update.
        name: New group name.
        description: New description.
        auto_balance: Enable/disable auto-balancing.
        auto_balance_strategy: New auto-balance strategy.
        custom_properties: Custom properties to merge (adds/updates, does not remove).

    Returns:
        List of TextContent with updated group info or error.
    """
    try:
        body: dict = {}

        if name is not None:
            body["name"] = name
        if description is not None:
            body["description"] = description
        if auto_balance is not None:
            body["autoBalance"] = auto_balance
        if auto_balance_strategy is not None:
            body["autoBalanceStrategy"] = auto_balance_strategy
        if custom_properties is not None:
            existing = await client.get(f"/setting/collector/groups/{group_id}")
            existing_props = {p["name"]: p["value"] for p in existing.get("customProperties", [])}
            existing_props.update(custom_properties)
            body["customProperties"] = [{"name": k, "value": v} for k, v in existing_props.items()]

        if not body:
            return format_response(
                {
                    "error": True,
                    "code": "NO_CHANGES",
                    "message": "No updates provided",
                }
            )

        result = await client.patch(f"/setting/collector/groups/{group_id}", json_body=body)

        return format_response(
            {
                "success": True,
                "message": f"Collector group {group_id} updated",
                "result": result,
            }
        )
    except Exception as e:
        return handle_error(e)


@require_write_permission
async def delete_collector_group(
    client: LogicMonitorClient,
    group_id: int,
) -> list[TextContent]:
    """Delete a collector group from LogicMonitor.

    Blocks deletion if collectors are still assigned to the group.

    Args:
        client: LogicMonitor API client.
        group_id: Collector group ID to delete.

    Returns:
        List of TextContent with deletion confirmation or error.
    """
    try:
        group = await client.get(f"/setting/collector/groups/{group_id}")
        group_name = group.get("name", f"ID:{group_id}")
        collector_count = group.get("numOfCollectors", 0)

        if collector_count > 0:
            return format_response(
                {
                    "error": True,
                    "code": "GROUP_HAS_COLLECTORS",
                    "message": (
                        f"Collector group '{group_name}' has {collector_count} "
                        "collectors assigned. Move collectors before deleting the group."
                    ),
                    "group_id": group_id,
                    "collector_count": collector_count,
                }
            )

        await client.delete(f"/setting/collector/groups/{group_id}")

        return format_response(
            {
                "success": True,
                "message": f"Collector group '{group_name}' deleted",
                "group_id": group_id,
            }
        )
    except Exception as e:
        return handle_error(e)
