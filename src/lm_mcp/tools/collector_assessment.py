# Description: Collector health assessment for AI investigations (Edwin AI, Claude, any client).
# Description: Puts every collector in scope into one evidence-backed state in few API calls.

"""Collector health assessment.

When an alert correlation groups many devices that sit behind one collector, the first question
is whether the collector is the cause. This module answers it from the read-only REST API in a
fixed number of calls, whatever the size of the fleet:

    collectors (paged) · the down set (filter=isDown:true) · devices at hostStatus dead
    · devices at hostStatus dead-collector · active alerts on the collectors' self-monitoring

plus, only when device IDs are given, a lookup of those devices' current collector.

Each collector gets exactly one state, the first rule that matches:

    down                    LM holds it down (isDown), or the collector's own resource
                            (collectorDeviceId) is at hostStatus dead or dead-collector
    silent_reported_up      the watchdog has not reported for over an hour, or never since
                            creation, while LM still reports the collector up
    up_devices_unreachable  the collector is live and a large share of its devices are dead:
                            the path between collector and devices, not the collector
    up_losing_work          LM's own thresholds on the collector's self-monitoring modules
                            are breached (queues, unavailable task rate, heap)
    healthy                 none of the above, with every required signal read
    unknown                 none of the above, and a required signal could not be read

A missing signal never reads as healthy. Facts this code relies on, each verified on live
portals during the collector-health work:

- isDown is NOT on list rows. Asking for the down set server-side is the only safe source.
- updatedOn advances even when the agent is not running. watchdogUpdatedOn is the liveness
  signal: older than an hour, or not past createdOn, means the agent is not running.
- A collector that stops talking leaves its devices stale rather than down, so device status
  is only trusted once the watchdog is known to be current.
- Devices are keyed on currentCollectorId, which follows auto-balanced moves.
- Collector-down alerts are NOT returned by /alert/alerts. A collector monitored as a resource
  has its own host status (and host-down alert) like any other device, reached through
  collectorDeviceId.

The default assumption, stated in every response: each collector is monitored in LM as a
resource and LM's LogicMonitor_Collector modules apply to it. A collector that is not monitored
as a resource is called out by name. Its own host status and self-monitoring rungs are reported
as unknown, never as clean. Whether the modules actually collect on a given collector resource
(they gate on the "collector" category) is not checked per collector, and the response says so.

Optional tier 2: with use_debug, the tool also reads the collector's stored health check
(!shealthcheck func=detail, which reads the last scheduled result and starts nothing) for a few
collectors in scope, and returns a parsed summary (per-method all-NaN rates, checkpoints not
OK, modules carrying NaN) with a short raw excerpt. Tier 2 never changes a state.

Timing. An AI investigation waits on this tool, so speed is part of the contract. Tier 1 issues
its fleet reads concurrently and its cost does not grow with the number of collectors. Tier 2
goes through the collector debug channel: a command is queued, the collector picks it up on its
next check-in, and the reply has to be polled for. That takes seconds per collector at best and
does not complete at all on a collector that is not checking in. So tier 2 is off by default,
its reads run in parallel, and all of them share one wall-clock budget (debug_budget_seconds,
default 15). A read that does not answer inside the budget is returned as no_reply with its
elapsed time, and the tier-1 result is returned regardless. Every response carries elapsed_ms.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import Counter
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from mcp.types import TextContent

from lm_mcp.tools import format_response, handle_error
from lm_mcp.tools.collector_debug import parse_health_check, run_debug

if TYPE_CHECKING:
    from lm_mcp.client import LogicMonitorClient

logger = logging.getLogger(__name__)

STATE_ORDER = (
    "down",
    "silent_reported_up",
    "up_devices_unreachable",
    "up_losing_work",
    "unknown",
    "healthy",
)

PAGE_SIZE = 1000
MAX_ROWS = 50_000
MAX_INSIGHT_DEVICES = 1000
DEVICE_LOOKUP_CONCURRENCY = 10
# The v3 API returns hostStatus as a word and filters on the word. The numeric codes found in
# older docs (1 = dead, 2 = dead-collector) match nothing on a live portal, so a numeric filter
# silently reports zero dead devices.
HOST_STATUS_DEAD = '"dead"'
HOST_STATUS_DEAD_COLLECTOR = '"dead-collector"'
SELF_MONITORING_MODULE_PREFIX = "LogicMonitor_Collector"
SELF_ALERT_FILTER = f'cleared:false,resourceTemplateName~"{SELF_MONITORING_MODULE_PREFIX}"'
NOT_A_RESOURCE = "not monitored as a resource"

DEBUG_COLLECTOR_CAP = 5
DEBUG_EXCERPT_CHARS = 1500
DEBUG_BUDGET_DEFAULT = 15.0
DEBUG_BUDGET_MAX = 60.0

ASSUMPTIONS = [
    "Each collector is expected to be monitored in LM as a resource (collectorDeviceId set), "
    "with LM's LogicMonitor_Collector modules applied. Collectors that are not are listed under "
    "collectors_not_monitored_as_resource, and their own host status and self-monitoring are "
    "reported as unknown.",
    "Whether the LogicMonitor_Collector modules actually collect on each collector resource "
    "(they apply only where the resource carries the 'collector' category) is not checked per "
    "collector. No self-monitoring alert is therefore not proof the modules ran.",
    "Collector-down alerts are not in /alert/alerts. A collector's own host-down condition is "
    "read from its resource's hostStatus.",
]


class _Calls:
    """Counts API calls so the response can state what the assessment cost."""

    def __init__(self, client: LogicMonitorClient) -> None:
        self.client = client
        self.count = 0

    async def get(self, path: str, params: dict | None = None) -> dict:
        self.count += 1
        return await self.client.get(path, params=params)

    async def request(self, method: str, path: str, **kwargs: Any) -> dict:
        self.count += 1
        return await self.client.request(method, path, **kwargs)

    async def paged(self, path: str, params: dict | None = None) -> list[dict]:
        out: list[dict] = []
        offset = 0
        while offset < MAX_ROWS:
            page_params = dict(params or {})
            page_params["size"] = PAGE_SIZE
            page_params["offset"] = offset
            result = await self.get(path, params=page_params)
            items = (result or {}).get("items") or []
            out.extend(items)
            if len(items) < PAGE_SIZE:
                break
            offset += len(items)
        return out


def _num(value: Any) -> float | None:
    """A numeric field, or None when it is absent or not a number. Zero stays zero."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _span(seconds: float) -> str:
    """Seconds as a readable span: 7200 -> '2.0 h', 38774146 -> '448.8 days'."""
    if seconds < 120:
        return f"{int(seconds)} s"
    if seconds < 7200:
        return f"{seconds / 60:.0f} min"
    if seconds < 172800:
        return f"{seconds / 3600:.1f} h"
    return f"{seconds / 86400:.1f} days"


def _failover(row: dict) -> str:
    backup = _num(row.get("backupAgentId"))
    has_fo = row.get("hasFailOverDevice")
    if (backup is not None and backup > 0) or has_fo is True:
        return "configured"
    if backup is None and has_fo is None:
        return "unknown: the response did not carry the failover fields"
    return "none configured"


def own_resource_status(
    row: dict, dead_ids: set | None, dead_collector_ids: set | None
) -> str | None:
    """Host status of the collector's own resource, from the dead sets already fetched.

    Returns "dead", "dead-collector", "not dead", NOT_A_RESOURCE, or None when unreadable.
    """
    device_id = _num(row.get("collectorDeviceId"))
    if not device_id or device_id <= 0:
        return NOT_A_RESOURCE
    if dead_ids is None or dead_collector_ids is None:
        return None
    if int(device_id) in dead_ids:
        return "dead"
    if int(device_id) in dead_collector_ids:
        return "dead-collector"
    return "not dead"


def classify_collector(
    row: dict,
    *,
    now: float,
    down_ids: set | None,
    own_resource: str | None,
    dead: Counter | None,
    dead_collector: Counter | None,
    self_alerts: list[dict] | None,
    dark_share: float = 0.8,
    min_dark: int = 5,
    watchdog_stale_seconds: int = 3600,
) -> dict:
    """Put one collector into exactly one state. Pure: no I/O, tested on synthetic rows.

    A ``None`` for any signal means that signal could not be read. down_ids, the watchdog and
    the dead-device counts are required: when one is missing and no rule fired, the state is
    ``unknown``. The collector's own resource status and its self-monitoring alerts corroborate:
    when missing they are listed under ``unknowns`` but do not block ``healthy``.
    """
    cid = row.get("id")
    evidence: list[str] = []
    unknowns: list[str] = []
    required_missing = False

    # Rung 1: held down by LogicMonitor, or its own resource is down.
    if down_ids is not None:
        is_down: bool | None = cid in down_ids
        if is_down:
            evidence.append("isDown true (asked for with filter=isDown:true, not read off the row)")
    elif "isDown" in row:
        is_down = bool(row.get("isDown"))
        if is_down:
            evidence.append("isDown true on the collector object")
    else:
        is_down = None
        required_missing = True
        unknowns.append("isDown: the down set could not be read, and list rows do not carry it")

    own_down = own_resource in ("dead", "dead-collector")
    if own_resource is None:
        unknowns.append("the host status of the collector's own resource could not be read")
    elif own_resource == NOT_A_RESOURCE:
        unknowns.append(
            "not monitored as a resource (no collectorDeviceId): it has no host status or "
            "host-down alert of its own, and no self-monitoring modules"
        )
    elif own_down:
        evidence.append(f"the collector's own resource is at hostStatus {own_resource}")

    # Rung 2: the watchdog.
    watchdog = _num(row.get("watchdogUpdatedOn"))
    created = _num(row.get("createdOn"))
    watchdog_age: float | None = None
    watchdog_silent = False
    if watchdog is None or watchdog <= 0:
        required_missing = True
        unknowns.append(
            "watchdogUpdatedOn absent: whether the agent is running is unknown "
            "(updatedOn cannot answer it; it advances even when the agent is not running)"
        )
    else:
        watchdog_age = max(0.0, float(now) - watchdog)
        if created is not None and watchdog <= created:
            watchdog_silent = True
            evidence.append("watchdog has never reported since the collector was created")
        elif watchdog_age > watchdog_stale_seconds:
            watchdog_silent = True
            evidence.append(
                f"watchdog last reported {_span(watchdog_age)} ago "
                f"(limit {_span(watchdog_stale_seconds)})"
            )
        else:
            evidence.append(f"watchdog reported {_span(watchdog_age)} ago")

    # Rung 3: its devices.
    hosts = _num(row.get("numberOfHosts"))
    n_dead: int | None = None
    n_dead_collector: int | None = None
    share: float | None = None
    if dead is None or dead_collector is None:
        required_missing = True
        unknowns.append("device status could not be read")
    else:
        n_dead = int(dead.get(cid, 0))
        n_dead_collector = int(dead_collector.get(cid, 0))
        if hosts and hosts > 0:
            share = n_dead / hosts
    if hosts is None:
        unknowns.append("numberOfHosts absent: the dead share cannot be computed")

    # Rung 4: LM's own thresholds on the collector's self-monitoring modules.
    if self_alerts is None and own_resource != NOT_A_RESOURCE:
        unknowns.append("self-monitoring alerts could not be read")

    # The first rule that matches decides.
    if is_down or own_down:
        state = "down"
        if n_dead_collector:
            evidence.append(f"{n_dead_collector} device(s) at hostStatus dead-collector")
    elif watchdog_silent:
        state = "silent_reported_up"
        evidence.append("LM still reports this collector up; its devices read stale, not down")
    elif (
        share is not None
        and n_dead is not None
        and hosts
        and n_dead >= min_dark
        and share >= dark_share
    ):
        state = "up_devices_unreachable"
        evidence.append(f"{n_dead} of {int(hosts)} devices at hostStatus dead ({share:.0%})")
    elif self_alerts:
        state = "up_losing_work"
        for alert in self_alerts[:10]:
            module = alert.get("resourceTemplateName") or alert.get("dataSourceName") or "?"
            evidence.append(
                f"active alert on {module} {alert.get('dataPointName') or '?'} = "
                f"{alert.get('alertValue')} (severity {alert.get('severity')})"
            )
    elif required_missing:
        state = "unknown"
    else:
        state = "healthy"

    if state not in ("down", "up_devices_unreachable") and n_dead:
        pct = f" ({share:.0%})" if share is not None else ""
        evidence.append(f"{n_dead} device(s) at hostStatus dead{pct}, below the dark_share rule")

    return {
        "collector_id": cid,
        "hostname": row.get("hostname"),
        "group": row.get("collectorGroupName"),
        "platform": row.get("platform"),
        "build": row.get("build"),
        "state": state,
        "evidence": evidence,
        "unknowns": unknowns,
        "monitored_as_resource": own_resource != NOT_A_RESOURCE,
        "own_resource_host_status": own_resource,
        "number_of_hosts": int(hosts) if hosts is not None else None,
        "devices_dead": n_dead,
        "devices_dead_collector": n_dead_collector,
        "dead_share": round(share, 3) if share is not None else None,
        "watchdog_age_seconds": int(watchdog_age) if watchdog_age is not None else None,
        "up_time_seconds": row.get("upTime"),
        "in_sdt": row.get("inSDT"),
        "failover": _failover(row),
    }


async def _resolve_devices(calls: _Calls, device_ids: list[int]) -> tuple[dict, list]:
    """Map each requested device to its currentCollectorId.

    Tries an id:a|b|c filter in chunks and accepts only rows whose id was asked for, then looks
    up anything still missing one by one. Correct whether or not the portal honours the OR form.
    """
    wanted = {int(d) for d in device_ids}
    found: dict[int, Any] = {}
    ids = sorted(wanted)
    for i in range(0, len(ids), 50):
        chunk = ids[i : i + 50]
        try:
            rows = await calls.paged(
                "/device/devices",
                {
                    "filter": "id:" + "|".join(str(x) for x in chunk),
                    "fields": "id,currentCollectorId",
                },
            )
        except Exception:
            logger.info("device OR-filter lookup failed; using single lookups", exc_info=True)
            rows = []
        for row in rows:
            rid = row.get("id")
            if rid in wanted and rid not in found:
                found[rid] = row.get("currentCollectorId")

    missing = [d for d in ids if d not in found]
    sem = asyncio.Semaphore(DEVICE_LOOKUP_CONCURRENCY)

    async def one(device_id: int) -> None:
        async with sem:
            try:
                row = await calls.get(
                    f"/device/devices/{device_id}", params={"fields": "id,currentCollectorId"}
                )
                found[device_id] = row.get("currentCollectorId")
            except Exception:
                logger.info("device %s could not be resolved", device_id, exc_info=True)

    await asyncio.gather(*(one(d) for d in missing))
    resolved = {d: c for d, c in found.items() if c not in (None, 0, -1)}
    unresolved = [d for d in ids if d not in resolved]
    return resolved, unresolved


async def _read_health_check(calls: _Calls, collector_id: int, deadline: float) -> dict:
    """Tier 2: read the stored health check through the shared debug transport.

    Starts no work on the collector. Returns the parsed summary (per-method all-NaN rates,
    checkpoints not OK, modules carrying NaN) and a short raw excerpt, never the whole reply:
    a full reply runs past 20,000 characters, too much for an agent to carry.
    """
    command = f"!shealthcheck func=detail collector={collector_id}"
    counter = [0]
    res = await run_debug(calls.client, collector_id, command, deadline, counter)
    calls.count += counter[0]
    output = res.pop("output", "")
    out = {
        "command": command,
        "status": res.get("status"),
        "elapsed_ms": res.get("elapsed_ms"),
    }
    for key in ("read_form", "detail"):
        if res.get(key):
            out[key] = res[key]
    if output:
        out["parsed"] = parse_health_check(output)
        out["output_chars"] = len(output)
        out["output_excerpt"] = output[:DEBUG_EXCERPT_CHARS]
    return out


async def assess_collector_health(
    client: LogicMonitorClient,
    device_ids: list[int] | None = None,
    collector_ids: list[int] | None = None,
    dark_share: float = 0.8,
    min_dark: int = 5,
    watchdog_stale_seconds: int = 3600,
    include_healthy: bool = False,
    use_debug: bool = False,
    debug_budget_seconds: float = DEBUG_BUDGET_DEFAULT,
) -> list[TextContent]:
    """Assess collector health for an investigation. See the module docstring for the rules."""
    try:
        calls = _Calls(client)
        now = time.time()
        started = time.monotonic()
        signals_unavailable: list[str] = []

        async def soft(name: str, coro):
            try:
                return await coro
            except Exception as e:
                logger.warning("collector assessment: %s unavailable", name, exc_info=True)
                signals_unavailable.append(f"{name}: {type(e).__name__}: {e}"[:300])
                return None

        if device_ids and len(device_ids) > MAX_INSIGHT_DEVICES:
            device_ids = list(device_ids)[:MAX_INSIGHT_DEVICES]
            signals_unavailable.append(f"device_ids capped at {MAX_INSIGHT_DEVICES}")

        # Tier 1: the fleet reads run concurrently. Only the collector list is fatal.
        collectors, down_rows, dead_rows, dc_rows, self_alert_rows = await asyncio.gather(
            calls.paged("/setting/collector/collectors"),
            soft(
                "down set (filter=isDown:true)",
                calls.paged(
                    "/setting/collector/collectors", {"filter": "isDown:true", "fields": "id"}
                ),
            ),
            soft(
                "devices at hostStatus dead",
                calls.paged(
                    "/device/devices",
                    {
                        "filter": f"hostStatus:{HOST_STATUS_DEAD}",
                        "fields": "id,currentCollectorId",
                    },
                ),
            ),
            soft(
                "devices at hostStatus dead-collector",
                calls.paged(
                    "/device/devices",
                    {
                        "filter": f"hostStatus:{HOST_STATUS_DEAD_COLLECTOR}",
                        "fields": "id,currentCollectorId",
                    },
                ),
            ),
            soft(
                "active self-monitoring alerts",
                calls.paged("/alert/alerts", {"filter": SELF_ALERT_FILTER}),
            ),
        )
        tier1_ms = int((time.monotonic() - started) * 1000)

        down_ids = {r.get("id") for r in down_rows} if down_rows is not None else None
        dead: Counter | None = None
        if dead_rows is not None:
            dead = Counter(r.get("currentCollectorId") for r in dead_rows)
        dead_collector: Counter | None = None
        if dc_rows is not None:
            dead_collector = Counter(r.get("currentCollectorId") for r in dc_rows)
        dead_ids = {r.get("id") for r in dead_rows} if dead_rows is not None else None
        dc_ids = {r.get("id") for r in dc_rows} if dc_rows is not None else None
        self_by_device: dict | None = None
        if self_alert_rows is not None:
            self_by_device = {}
            for alert in self_alert_rows:
                self_by_device.setdefault(alert.get("monitorObjectId"), []).append(alert)

        # Scope.
        insight: dict | None = None
        per_collector_insight: Counter = Counter()
        by_id = {c.get("id"): c for c in collectors}
        if device_ids:
            mapping, unresolved = await _resolve_devices(calls, list(device_ids))
            per_collector_insight = Counter(mapping.values())
            insight = {
                "requested": len({int(d) for d in device_ids}),
                "resolved": len(mapping),
                "unresolved_device_ids": unresolved,
            }
            scope_ids = [cid for cid in per_collector_insight if cid in by_id]
            scope = "insight devices"
        elif collector_ids:
            scope_ids = [int(c) for c in collector_ids if int(c) in by_id]
            missing = [int(c) for c in collector_ids if int(c) not in by_id]
            if missing:
                signals_unavailable.append(f"collector ids not found: {missing}")
            scope = "collector ids"
        else:
            scope_ids = list(by_id)
            scope = "fleet"

        records: list[dict] = []
        for cid in scope_ids:
            row = by_id[cid]
            own = own_resource_status(row, dead_ids, dc_ids)
            self_alerts = None
            if own == NOT_A_RESOURCE:
                self_alerts = []
            elif self_by_device is not None:
                self_alerts = self_by_device.get(int(_num(row.get("collectorDeviceId")) or 0), [])
            record = classify_collector(
                row,
                now=now,
                down_ids=down_ids,
                own_resource=own,
                dead=dead,
                dead_collector=dead_collector,
                self_alerts=self_alerts,
                dark_share=dark_share,
                min_dark=min_dark,
                watchdog_stale_seconds=watchdog_stale_seconds,
            )
            if insight is not None:
                here = per_collector_insight.get(cid, 0)
                record["insight_devices_here"] = here
                record["concentration"] = (
                    round(here / insight["resolved"], 3) if insight["resolved"] else None
                )
            records.append(record)

        rank = {s: i for i, s in enumerate(STATE_ORDER)}
        records.sort(
            key=lambda r: (
                rank[r["state"]],
                -(r.get("concentration") or 0),
                -(r.get("number_of_hosts") or 0),
            )
        )
        state_counts = dict(Counter(r["state"] for r in records))
        not_resources = [
            {"collector_id": r["collector_id"], "hostname": r["hostname"]}
            for r in records
            if not r["monitored_as_resource"]
        ]

        lead = None
        if insight is not None and records:
            top = max(records, key=lambda r: r.get("concentration") or 0)
            lead = (
                f"{top['insight_devices_here']} of {insight['resolved']} resolved insight devices "
                f"sit on collector {top['hostname']} (id {top['collector_id']}), "
                f"state {top['state']}."
            )

        tier2: Any = "not requested"
        if use_debug:
            budget = min(max(float(debug_budget_seconds), 1.0), DEBUG_BUDGET_MAX)
            # Down and silent collectors are not asked: neither will pick the command up.
            candidates = [r for r in records if r["state"] not in ("down", "silent_reported_up")][
                :DEBUG_COLLECTOR_CAP
            ]
            if not candidates:
                tier2 = "no collector in scope to read (down and silent collectors are not asked)"
            else:
                t2_start = time.monotonic()
                deadline = t2_start + budget
                results = await asyncio.gather(
                    *(_read_health_check(calls, r["collector_id"], deadline) for r in candidates)
                )
                for r, res in zip(candidates, results, strict=True):
                    r["tier2_health_check"] = res
                tier2 = {
                    "collectors_read": len(candidates),
                    "budget_seconds": budget,
                    "elapsed_ms": int((time.monotonic() - t2_start) * 1000),
                    "note": "reads run in parallel under one budget; tier 2 never changes a state",
                }

        if include_healthy or scope != "fleet":
            shown = records
        else:
            shown = [r for r in records if r["state"] != "healthy"]
        response = {
            "assessed_at": datetime.fromtimestamp(now, tz=UTC).isoformat(),
            "scope": scope,
            "collectors_in_portal": len(collectors),
            "collectors_assessed": len(records),
            "state_counts": state_counts,
            "lead": lead,
            "insight_devices": insight,
            "collectors": shown,
            "healthy_collectors_omitted": len(records) - len(shown),
            "collectors_not_monitored_as_resource": not_resources,
            "assumptions": ASSUMPTIONS,
            "signals_unavailable": signals_unavailable,
            "thresholds": {
                "dark_share": dark_share,
                "min_dark": min_dark,
                "watchdog_stale_seconds": watchdog_stale_seconds,
            },
            "tier2": tier2,
            "api_calls": calls.count,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "tier1_fleet_reads_ms": tier1_ms,
            "reading_notes": (
                "One state per collector, the first rule that matches: down, silent_reported_up, "
                "up_devices_unreachable, up_losing_work, then healthy or unknown. unknown means a "
                "required signal was missing; it is never healthy. A state with high "
                "concentration explains the insight; the same state at low concentration is "
                "background."
            ),
        }
        return format_response(response)
    except Exception as e:
        return handle_error(e)
