# Description: Usage and entitlement tools for LogicMonitor MCP server.
# Description: Exposes /usage/contractInfo, /usage/focusCostUsage and /metrics/usage.

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from mcp.types import TextContent

from lm_mcp.tools import format_response, handle_error

if TYPE_CHECKING:
    from lm_mcp.client import LogicMonitorClient

# focusCostUsage reports LOGS in bytes against a contract expressed in GB.
# Nothing in the response says so: ConsumedUnit is the literal "Units" for every
# feature. Without this conversion LOGS reads as several billion percent.
_BYTES_TO_GB = 1_000_000_000
_BYTE_REPORTED_FEATURES = {"LOGS"}

# The contract's own roll-up basis, carried per feature in aggregationType.
# Applying the wrong one is not a rounding difference: summing a rolling-average
# feature over 30 days overstates it thirtyfold.
_ROLLUP_BASIS = {
    "RAVG": "rolling average of complete daily values",
    "DSUM": "sum of daily values",
    "SUM": "total across the period",
}

# focusCostUsage ignores endTime and returns two or three daily rows anchored at
# startTime, so a period is covered by stepping startTime forward and stitching.
_PAGE_SIZE = 1000
_STITCH_STEP_DAYS = 2
_MAX_STITCH_CALLS = 40

_DAY_MS = 86_400_000

# Per-tenant mode. focusCostUsage takes tenantIds (repeatable) holding
# system.tenant.identifier values -- NOT the GUID sub-account id the portal-level
# line carries. It returns one line per id sent, echoed back as SubAccountId, plus
# an "Overall cumulative usage" line that is the sum of the ids requested.
#   - An id it does not recognise is echoed back reading zero, not rejected, so a
#     zero line means "no usage" OR "no such tenant" and the response cannot say which.
#   - Every line carries ~20 daily rows whatever window is asked for, so ids are sent
#     in batches that keep each response under the 1,000-row page.
_OVERALL_LINE = "Overall cumulative usage"
_TENANT_BATCH = 40
_DEFAULT_TENANT_PROPERTY = "system.tenant.identifier"

# Features whose usage LogicMonitor does not attribute to a tenant: the Usage page
# offers no tenant filter for them, and a tenant-filtered request reads zero.
# They are reported at portal level only rather than as a misleading 0 per tenant.
_NOT_SPLIT_BY_TENANT = {"CLOUD_NONCOMPUTE", "ADR"}


def _month_start_ms(now_ms: int) -> int:
    """Epoch ms for the first instant of the current calendar month, UTC.

    LogicMonitor bills the calendar month to date and resets on the 1st, so a figure
    meant to be compared with the usage page has to start there -- not N days back.
    """
    now = datetime.fromtimestamp(now_ms / 1000, tz=UTC)
    first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return int(first.timestamp() * 1000)


def _walk_contract(
    node: Any,
    acc: list[dict],
    parent_feature: str | None = None,
    parent_quantity: float | None = None,
) -> list[dict]:
    """Flatten the contract tree, keeping parentage.

    An entitlement is only real on a node whose aggregationType is non-null. Every
    metered product carries RAVG, DSUM or SUM; a node that repeats or subdivides its
    parent carries null. Flattening without that distinction promotes children to
    contract lines -- on a portal with nine wireless vendor children it manufactures a
    9,000-unit entitlement against a real 1,000.

    A null aggregationType is not the only way a child repeats its parent. Observed
    live: SAAS entitled 29,000 users with five per-product children -- Office 365,
    Salesforce, Slack, Webex, Zoom -- each carrying the SAME 29,000 and a non-null
    RAVG. Treating those as separate lines reports 145,000 users of entitlement
    against a pool of 29,000. The parent's quantity is therefore carried down so a
    child repeating it exactly can be recognised for what it is.

    aggregationType is doing semantic work LogicMonitor does not document. It has held
    on every contract sampled, but it is inferred, so unexpected shapes are surfaced
    rather than silently folded in.
    """
    if isinstance(node, list):
        for item in node:
            _walk_contract(item, acc, parent_feature, parent_quantity)
        return acc
    if not isinstance(node, dict):
        return acc

    feature = node.get("feature")
    next_parent = parent_feature
    next_quantity = parent_quantity

    if feature:
        acc.append(
            {
                "feature": feature,
                "node": node,
                "parent": parent_feature,
                "parent_quantity": parent_quantity,
            }
        )
        if node.get("aggregationType") is not None:
            next_parent = feature
            next_quantity, _ = _as_quantity(node.get("quantity"))

    _walk_contract(node.get("childProducts") or [], acc, next_parent, next_quantity)
    _walk_contract(node.get("nestedProducts") or [], acc, next_parent, next_quantity)
    return acc


def _as_quantity(value: Any) -> tuple[float, Any]:
    """Coerce a contract quantity to a number, returning (quantity, raw_if_odd).

    Live contracts wrap every quantity in a single-element list -- [2710], not 2710.
    Collapsing a one-element numeric list is not a reinterpretation, so raw is None
    there. A list with more than one entry IS ambiguous: it collapses to the max,
    matching the largest-quantity-wins behaviour seen elsewhere in the payload, and
    the original comes back so the caller can surface it rather than trust it.
    """
    if value is None:
        return 0.0, None
    if isinstance(value, bool):  # bool is an int subclass; not a quantity
        return 0.0, value
    if isinstance(value, (int, float)):
        return float(value), None
    if isinstance(value, str):
        try:
            return float(value.strip()), None
        except ValueError:
            return 0.0, value
    if isinstance(value, list):
        nums = []
        odd = False
        for item in value:
            q, raw = _as_quantity(item)
            nums.append(q)
            odd = odd or raw is not None
        if not nums:
            return 0.0, None
        collapsed = max(nums)
        # One numeric entry is the normal shape; more than one is worth showing.
        return collapsed, (value if (len(nums) > 1 or odd) else None)
    if isinstance(value, dict):
        for key in ("quantity", "value", "amount"):
            if key in value:
                q, _ = _as_quantity(value[key])
                return q, value
        return 0.0, value
    return 0.0, value


def _pair_units(quantity: Any, unit: Any) -> dict[str, float] | None:
    """Pair a multi-valued quantity with its units.

    A feature can be entitled in more than one unit at once. Observed live:
    quantity [29000, 0] against unit ["User", "Services"] -- 29,000 users and zero
    services, not a list of candidate numbers.

    The order is NOT fixed. Another portal returns unit ["Services", "User"] with
    quantity [1, 0] -- one service, zero users. So position means nothing on its own:
    reading index 0, or taking the largest, gives a number whose unit depends on
    which portal you asked.
    """
    if not (isinstance(quantity, list) and isinstance(unit, list)):
        return None
    if len(quantity) != len(unit) or len(quantity) < 2:
        return None
    paired: dict[str, float] = {}
    for qty, u in zip(quantity, unit, strict=True):
        value, _ = _as_quantity(qty)
        paired[str(u)] = value
    return paired


def _headline_entitlement(
    by_unit: dict[str, float] | None, fallback: float
) -> tuple[float, str | None, bool]:
    """Choose the single figure to report, and say which unit it is in.

    Where exactly one unit carries a quantity, that is unambiguously the
    entitlement and we can name its unit. Where more than one does, no single
    number is honest: the largest is reported and flagged, and the caller should
    read entitled_by_unit instead.
    """
    if not by_unit:
        return fallback, None, False
    non_zero = {u: q for u, q in by_unit.items() if q}
    if len(non_zero) == 1:
        unit, qty = next(iter(non_zero.items()))
        return qty, unit, False
    if not non_zero:
        return 0.0, None, False
    unit = max(non_zero, key=lambda u: non_zero[u])
    return non_zero[unit], unit, True


def _first(value: Any) -> Any:
    """Unwrap a single-element list. Units arrive as ["Resources"], not "Resources"."""
    if isinstance(value, list):
        return value[0] if len(value) == 1 else value
    return value


def _project_feature(entry: dict) -> dict:
    node = entry["node"]
    aggregation = node.get("aggregationType")
    quantity, quantity_raw = _as_quantity(node.get("quantity"))
    unpaid = bool(node.get("unpaid"))

    subscriptions = node.get("subscriptions") or []
    sku = next((s.get("sku") for s in subscriptions if isinstance(s, dict) and s.get("sku")), None)

    parent_quantity = entry.get("parent_quantity")
    repeats_parent = (
        entry.get("parent") is not None
        and parent_quantity is not None
        and quantity > 0
        and quantity == parent_quantity
    )

    if aggregation is None:
        role = "rollup_or_carveout"
    elif repeats_parent:
        # Same pool, restated per product. Counting it again multiplies the
        # entitlement by the number of children.
        role = "repeats_parent"
    elif unpaid:
        role = "metered_unpaid"
    elif quantity > 0:
        role = "billable_line"
    else:
        role = "metered_no_entitlement"

    by_unit = _pair_units(node.get("quantity"), node.get("unit"))
    quantity, headline_unit, ambiguous = _headline_entitlement(by_unit, quantity)

    projected = {
        "feature": entry["feature"],
        "parent": entry["parent"],
        "role": role,
        "entitled": quantity,
        "unit": headline_unit if by_unit else _first(node.get("unit")),
        "aggregation_type": aggregation,
        "basis": _ROLLUP_BASIS.get(aggregation or ""),
        "unpaid": unpaid,
        "sku": sku,
    }
    if by_unit is not None:
        projected["entitled_by_unit"] = by_unit
        if ambiguous:
            # More than one unit carries a quantity, so no single figure is honest.
            projected["entitled_ambiguous"] = True
    # Never quietly reinterpret a contract: if the quantity was not a plain number,
    # say so and show what it actually was.
    if quantity_raw is not None:
        projected["entitled_raw"] = quantity_raw
    return projected


async def get_usage_contract(
    client: LogicMonitorClient,
    billable_only: bool = False,
) -> list[TextContent]:
    """Get the portal's contracted entitlements from /usage/contractInfo.

    Returns every feature the contract mentions, including ones carrying no
    entitlement -- which is where LITE_RESOURCES, SAAS and DYNAMIC_SERVICE_INSIGHTS
    appear on portals that do not licence them. Those rows are invisible on the
    LogicMonitor usage page and are usually what a reconciliation is missing.

    Each feature is classified by its aggregationType:
      billable_line          metered, paid, non-zero entitlement
      metered_no_entitlement metered but entitled zero
      metered_unpaid         carries a quantity and is not billed
      repeats_parent         restates its parent's exact quantity, e.g. SAAS split
                             per product; never an additional commitment
      rollup_or_carveout     repeats or subdivides its parent; never a commitment

    Args:
        client: LogicMonitor API client.
        billable_only: Return only billable_line features.

    Returns:
        List of TextContent with contract features or error.
    """
    try:
        result = await client.get("/usage/contractInfo")

        entries = _walk_contract(result, [])

        # Project per node. A contract shape we have not seen before should cost us
        # that one line and name itself, not the whole reconciliation.
        features = []
        unreadable = []
        for entry in entries:
            try:
                features.append(_project_feature(entry))
            except Exception as exc:
                unreadable.append({"feature": entry.get("feature"), "reason": str(exc)})

        if billable_only:
            features = [f for f in features if f["role"] == "billable_line"]

        features.sort(key=lambda f: (f["parent"] or "", f["feature"]))

        billing_mode = "indeterminate"
        names = {f["feature"] for f in features if f["role"] == "billable_line"}
        if "HYBRID_UNITS" in names:
            billing_mode = "hybrid"
        elif names & {"STANDARD_RESOURCES", "CLOUD_IAAS", "CLOUD_PAAS", "WIRELESS_ACCESS_POINTS"}:
            billing_mode = "legacy"

        payload: dict[str, Any] = {
            "billing_mode": billing_mode,
            "count": len(features),
            "features": features,
        }
        if unreadable:
            payload["unreadable_nodes"] = unreadable

        return format_response(
            {
                **payload,
                "note": (
                    "billing_mode is detected from the contract, not configured. "
                    "rollup_or_carveout rows are never commitments -- a carve-out such "
                    "as LITE_RESOURCES is included in its parent's entitlement, so "
                    "summing a parent and its children double counts."
                ),
            }
        )
    except Exception as e:
        return handle_error(e)


def _day_of(row: dict) -> str:
    """The row's calendar day as YYYY-MM-DD.

    ChargePeriodStart is an ISO date STRING in the response ("2026-09-15T00:00:00Z"),
    even though startTime and endTime in the REQUEST are epoch milliseconds. Parsing
    it as a number silently discards every row.
    """
    return str(row.get("ChargePeriodStart") or "")[:10]


def _complete_days_only(rows: list[dict], now_ms: int) -> list[dict]:
    """Drop rows for today and for dates that have not happened.

    The feed pads forward past today and today's row is partial. Including either
    destroys a rolling average -- measured on a live portal it pulled 1,486 down to 811.

    Day boundaries are compared in UTC; a portal billing on local midnight can differ
    by one row at the edge of the window.
    """
    today = datetime.fromtimestamp(now_ms / 1000, tz=UTC).strftime("%Y-%m-%d")
    return [r for r in rows if len(_day_of(r)) == 10 and _day_of(r) < today]


def _dedupe(rows: list[dict]) -> list[dict]:
    """Adjacent stitched windows overlap; de-duplicate on (day, sub-account)."""
    seen: set[tuple] = set()
    out = []
    for row in rows:
        key = (_day_of(row), row.get("SubAccountId"))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _extract_items(body: Any) -> tuple[list[dict], int | None]:
    """Pull the row list out of whichever envelope this response used.

    LogicMonitor list responses arrive as items, data or rows at the top level, or
    nested one level under any of those. Checking only "items" loses the rest.
    """
    if not isinstance(body, dict):
        return [], None
    for key in ("items", "data", "rows"):
        value = body.get(key)
        if isinstance(value, list):
            total = body.get("total")
            try:
                total = int(total) if total is not None else None
            except (TypeError, ValueError):
                total = None
            return [r for r in value if isinstance(r, dict)], total
        if isinstance(value, dict) and isinstance(value.get("items"), list):
            inner = value["items"]
            return [r for r in inner if isinstance(r, dict)], value.get("total")
    return [], None


def _roll_up(daily_totals: list[float], basis: str | None) -> float | None:
    if not daily_totals:
        return None
    if basis == "RAVG":
        return sum(daily_totals) / len(daily_totals)
    if basis in ("DSUM", "SUM"):
        return sum(daily_totals)
    return None


def _batches(ids: list[str], size: int = _TENANT_BATCH) -> list[list[str]]:
    return [ids[i : i + size] for i in range(0, len(ids), size)]


async def _collect_actuals(
    client: LogicMonitorClient,
    feature: str,
    days: int,
    basis: str | None,
    tenant_ids: list[str] | None,
    month_to_date: bool = True,
) -> dict:
    """Stitch the daily series for one feature and roll it up.

    Without tenant_ids the feed returns one line for the whole portal. With them it
    returns one line per tenant plus an "Overall cumulative usage" line. The Overall
    line is the sum of the tenant lines, so it is dropped here: counting it as well
    doubles every figure, and with more than one batch each batch carries its own.

    Returns a plain dict so callers can use the numbers directly; only the tool
    wrapper formats it. Nothing parses formatted output back into maths.
    """
    now_ms = int(time.time() * 1000)
    start_ms = _month_start_ms(now_ms) if month_to_date else now_ms - (days * _DAY_MS)
    requested = [str(t) for t in (tenant_ids or []) if str(t).strip()]
    batches: list[list[str] | None] = [b for b in _batches(requested)] if requested else [None]

    rows: list[dict] = []
    calls = 0
    capped = False
    cursor = start_ms
    while cursor < now_ms:
        window_end = min(cursor + _STITCH_STEP_DAYS * _DAY_MS, now_ms)
        for batch in batches:
            offset = 0
            while True:
                if calls >= _MAX_STITCH_CALLS * len(batches):
                    capped = True
                    break
                params: dict[str, Any] = {
                    "feature": feature,
                    "dimensionKey": "tenant",  # the only accepted dimension
                    "startTime": cursor,
                    # endTime is REQUIRED even though it does not bound the window: the
                    # API rejects a request without it, then returns two or three daily
                    # rows anchored at startTime regardless of what endTime says.
                    "endTime": window_end,
                    "size": _PAGE_SIZE,
                    "offset": offset,
                }
                if batch:
                    params["tenantIds"] = batch
                page = await client.get("/usage/focusCostUsage", params=params)
                calls += 1
                items, total = _extract_items(page)
                rows.extend(
                    r
                    for r in items
                    if r.get("SubAccountId") != _OVERALL_LINE
                    and r.get("SubAccountName") != _OVERALL_LINE
                )
                offset += len(items)
                if not items or (total is not None and offset >= total):
                    break
        if capped:
            break
        cursor += _STITCH_STEP_DAYS * _DAY_MS

    rows = _dedupe(_complete_days_only(rows, now_ms))

    divisor = _BYTES_TO_GB if feature in _BYTE_REPORTED_FEATURES else 1

    by_day: dict[str, float] = {}
    line_days: dict[str, dict[str, float]] = {}
    for row in rows:
        try:
            qty = float(row.get("ConsumedQuantity") or 0) / divisor
        except (TypeError, ValueError):
            continue
        day = _day_of(row)
        by_day[day] = by_day.get(day, 0.0) + qty
        name = str(row.get("SubAccountId") or row.get("SubAccountName") or "(unattributed)")
        line_days.setdefault(name, {})
        line_days[name][day] = line_days[name].get(day, 0.0) + qty

    ordered = sorted(by_day.items())
    days_seen = [d for d, _ in ordered]
    rolled = _roll_up([v for _, v in ordered], basis)

    # Every line rolled up on the same basis and over the same days as the total, so
    # the per-line figures add up to it. A line missing a day counts it as zero.
    by_line: dict[str, float | None] = {}
    for name, series in line_days.items():
        value = _roll_up([series.get(d, 0.0) for d in days_seen], basis)
        by_line[name] = round(value, 4) if value is not None else None

    result: dict[str, Any] = {
        "feature": feature,
        "window": "calendar month to date" if month_to_date else f"last {days} days",
        "complete_days": len(ordered),
        "api_calls": calls,
        "basis": basis,
        "basis_meaning": _ROLLUP_BASIS.get(basis or ""),
        "rolled_up": round(rolled, 4) if rolled is not None else None,
        "unit": "GB" if divisor != 1 else "Units",
        "daily": [{"day": d, "quantity": round(v, 4)} for d, v in ordered],
        "by_tenant": dict(sorted(by_line.items(), key=lambda kv: -(kv[1] or 0))),
        "converted_from_bytes": divisor != 1,
    }
    if requested:
        # An unknown id and a tenant with no usage look identical in the response.
        reading_zero = [t for t in requested if not any(v for v in line_days.get(t, {}).values())]
        result["tenants_requested"] = len(requested)
        result["tenants_reading_zero"] = reading_zero
    if capped:
        result["truncated"] = True
    return result


async def get_usage_actuals(
    client: LogicMonitorClient,
    feature: str,
    days: int = 30,
    basis: str | None = None,
    tenant_ids: list[str] | None = None,
    month_to_date: bool = True,
) -> list[TextContent]:
    """Get month-to-date consumption for one feature from /usage/focusCostUsage.

    This endpoint has four undocumented behaviours, three of them traps, and they are
    handled here so callers do not have to know about them:

      1. Both feature and dimensionKey are required, and only "tenant" is accepted.
      2. Times are epoch MILLISECONDS; seconds are rejected.
      3. endTime is ignored -- any span returns two or three daily rows anchored at
         startTime, so a period is covered by stepping startTime forward and stitching,
         de-duplicating on (day, sub-account) because adjacent windows overlap.
      4. The feed pads forward past today and today's row is partial. Only complete
         days before today are counted.

    Units are not self-describing: ConsumedUnit is the literal "Units" for every
    feature. LOGS is contracted in GB and reported in bytes, and is converted here.

    Cost: roughly one call per two days requested, so a 30-day window is ~15 calls for
    a single feature.

    Args:
        client: LogicMonitor API client.
        feature: Contract feature name, e.g. HYBRID_UNITS or STANDARD_RESOURCES.
        days: Days back from today to cover.
        basis: Roll-up basis (RAVG, DSUM, SUM). Taken from get_usage_contract when
            omitted no roll-up is computed, only the daily series.
        tenant_ids: system.tenant.identifier values. Each gets its own line, rolled
            up on `basis`, and `daily` becomes the sum of those tenants only. An id
            LogicMonitor does not recognise reads zero rather than failing; such ids
            are listed under tenants_reading_zero. Sent in batches of 40.
        month_to_date: Cover the calendar month to date, which is the window
            LogicMonitor bills on. Set False to use `days` back from today instead.

    Returns:
        List of TextContent with the daily series, roll-up and per-line split.
        Without tenant_ids by_tenant holds the single portal line, keyed by its GUID
        sub-account id, which does not correspond to any tenant.
    """
    try:
        data = await _collect_actuals(client, feature, days, basis, tenant_ids, month_to_date)
        converted = data.pop("converted_from_bytes")
        data["note"] = (
            "Only complete days before today are counted; the feed pads forward past "
            "today and today's row is partial. "
            + ("LOGS converted from bytes to GB. " if converted else "")
            + (
                "No basis supplied, so only the daily series is returned -- take the "
                "basis from get_usage_contract."
                if basis is None
                else ""
            )
        ).strip()
        return format_response(data)
    except Exception as e:
        return handle_error(e)


async def get_usage_reconciliation(
    client: LogicMonitorClient,
    days: int = 30,
    features: list[str] | None = None,
    month_to_date: bool = True,
) -> list[TextContent]:
    """Reconcile contracted entitlements against actual consumption.

    Walks the contract, then pulls actuals for each billable line using that line's own
    aggregation basis, and reports utilisation. This is the view the LogicMonitor usage
    page shows, with the sub-allocations it hides: a carve-out such as LITE_RESOURCES
    can sit at 90% while the pool it belongs to reads a comfortable 43%.

    Cost: roughly 15 calls per feature for a 30-day window, so restrict `features` on a
    contract with many billable lines.

    Args:
        client: LogicMonitor API client.
        days: Days back from today to cover.
        features: Restrict to these feature names. Defaults to every billable line.
        month_to_date: Cover the calendar month to date, the window LogicMonitor
            bills on. Set False to use `days` back from today instead.

    Returns:
        List of TextContent with per-feature entitlement, usage and utilisation.
    """
    try:
        contract = await client.get("/usage/contractInfo")
        projected = [_project_feature(e) for e in _walk_contract(contract, [])]

        targets = [
            f
            for f in projected
            if f["role"] == "billable_line" and (features is None or f["feature"] in features)
        ]

        lines = []
        total_calls = 0
        for feat in targets:
            actual = await _collect_actuals(
                client, feat["feature"], days, feat["aggregation_type"], None, month_to_date
            )
            used = actual["rolled_up"]
            total_calls += actual["api_calls"]

            entitled = feat["entitled"] or 0
            lines.append(
                {
                    "feature": feat["feature"],
                    "entitled": entitled,
                    "used": used,
                    "unit": feat["unit"],
                    "basis": feat["aggregation_type"],
                    "utilisation_pct": (
                        round(used / entitled * 100, 1) if used is not None and entitled else None
                    ),
                    "carve_outs": [
                        c["feature"]
                        for c in projected
                        if c["parent"] == feat["feature"] and c["role"] == "rollup_or_carveout"
                    ],
                }
            )

        unentitled = [
            f["feature"]
            for f in projected
            if f["role"] in ("metered_no_entitlement", "metered_unpaid")
        ]

        return format_response(
            {
                "window": "calendar month to date" if month_to_date else f"last {days} days",
                "api_calls": total_calls,
                "lines": lines,
                "features_present_without_entitlement": unentitled,
                "note": (
                    "A feature absent from the contract emits nothing rather than zero: "
                    "zero would claim the feature exists and is unused. Carve-outs are "
                    "included in their parent's entitlement -- never sum a parent and "
                    "its children."
                ),
            }
        )
    except Exception as e:
        return handle_error(e)


_DISCOVERY_CACHE: dict[tuple[str, str], tuple[float, dict]] = {}
_DISCOVERY_TTL_S = 6 * 3600
_DISCOVERY_CONCURRENCY = 6


async def _list_all(client: LogicMonitorClient, path: str, fields: str) -> tuple[list[dict], int]:
    """Every item of a list endpoint, and the number of calls it took. The first page
    gives the total; the rest are fetched a few at a time in parallel, sorted by id so
    offsets stay stable."""
    import asyncio

    def params(offset: int) -> dict:
        return {"fields": fields, "size": _PAGE_SIZE, "offset": offset, "sort": "+id"}

    first = await client.get(path, params=params(0))
    calls = 1
    items, total = _extract_items(first)
    if total is None:
        # No total to plan from: page sequentially until a short page.
        out, offset = list(items), len(items)
        while items and len(items) == _PAGE_SIZE:
            items, _ = _extract_items(await client.get(path, params=params(offset)))
            calls += 1
            out.extend(items)
            offset += len(items)
        return out, calls

    out = list(items)
    offsets = list(range(len(items), total, _PAGE_SIZE)) if items else []
    sem = asyncio.Semaphore(_DISCOVERY_CONCURRENCY)

    async def fetch(offset: int) -> list[dict]:
        async with sem:
            return _extract_items(await client.get(path, params=params(offset)))[0]

    for page in await asyncio.gather(*(fetch(o) for o in offsets)):
        out.extend(page)
    return out, calls + len(offsets)


def _prop(obj: dict, name: str, buckets: tuple[str, ...]) -> str | None:
    for bucket in buckets:
        for p in obj.get(bucket) or []:
            if isinstance(p, dict) and p.get("name") == name:
                value = str(p.get("value") or "").strip()
                if value:
                    return value
    return None


async def _discover_tenants(client: LogicMonitorClient, prop: str) -> dict:
    """Find the tenant ids to ask for, and where they came from.

    The usage API will not list the tenants it knows: an unknown id just reads zero.
    So the ids come from where the property is set. Resource groups first -- one or two
    calls, and the property is normally set on a customer's group and inherited. Where
    no group carries it, every resource is read instead, which also counts the
    resources that have no tenant at all. That is tens of calls on a large portal, so
    the result is cached per portal for six hours.
    """
    key = (str(getattr(client, "base_url", "")), prop)
    cached = _DISCOVERY_CACHE.get(key)
    if cached and time.time() - cached[0] < _DISCOVERY_TTL_S:
        return {**cached[1], "cached": True, "api_calls": 0}

    groups, calls = await _list_all(client, "/device/groups", "id,customProperties")
    ids = sorted({v for g in groups if (v := _prop(g, prop, ("customProperties",)))})
    if ids:
        found: dict[str, Any] = {
            "tenant_ids": ids,
            "source": "resource groups",
            "untenanted_resources": None,
        }
    else:
        # autoProperties is the heaviest bucket and a tenant id is set by people, so
        # it is read from custom, inherited and system properties only.
        buckets = ("customProperties", "inheritedProperties", "systemProperties")
        devices, more = await _list_all(client, "/device/devices", "id," + ",".join(buckets))
        calls += more
        tenants: set[str] = set()
        untenanted = 0
        for d in devices:
            v = _prop(d, prop, buckets)
            if v:
                tenants.add(v)
            else:
                untenanted += 1
        found = {
            "tenant_ids": sorted(tenants),
            "source": "resources",
            "untenanted_resources": untenanted,
        }
    found["api_calls"] = calls
    _DISCOVERY_CACHE[key] = (time.time(), found)
    return found


def _basis_for(feature: str, projected: list[dict]) -> str | None:
    """The feature's own aggregationType, or its parent's for a carve-out.

    Feature names are NOT unique in a contract. Observed live: STANDARD_RESOURCES as
    the billable line (RAVG) and again as its own carve-out child (null), beside
    LITE_RESOURCES. Keying by name lets the child overwrite the parent and every
    lookup comes back empty, so any entry that carries a basis wins.
    """

    def own(name: str) -> str | None:
        return next(
            (
                f["aggregation_type"]
                for f in projected
                if f["feature"] == name and f.get("aggregation_type")
            ),
            None,
        )

    basis = own(feature)
    if basis:
        return basis
    for f in projected:
        if f["feature"] == feature and f.get("parent"):
            basis = own(f["parent"])
            if basis:
                return basis
    return None


async def get_usage_by_tenant(
    client: LogicMonitorClient,
    features: list[str] | None = None,
    tenant_ids: list[str] | None = None,
    tenant_property: str = _DEFAULT_TENANT_PROPERTY,
    days: int = 30,
    month_to_date: bool = True,
) -> list[TextContent]:
    """LogicMonitor's own billed usage, split by tenant, for one or more features.

    For each feature: the portal total, each tenant rolled up on the contract's own
    basis, and the untenanted remainder -- portal total minus the tenants, which is the
    only way to see it, because resources without a tenant have no id to ask for.

    Tenant ids are system.tenant.identifier values. When not given they are discovered
    from resource groups, falling back to every resource. CLOUD_NONCOMPUTE and ADR are
    not attributed to tenants by LogicMonitor and are reported at portal level only.

    Cost per feature: one call per two days of window for the portal line, plus the
    same again per batch of 40 tenants. Month to date on a 100-tenant portal is about
    60 calls per feature.

    Args:
        client: LogicMonitor API client.
        features: Feature names. Defaults to every billable line on the contract.
        tenant_ids: system.tenant.identifier values. Discovered when omitted.
        tenant_property: Property holding the tenant id, for discovery only.
        days: Days back when month_to_date is false.
        month_to_date: Cover the calendar month to date, the window LM bills on.

    Returns:
        List of TextContent with per-feature, per-tenant usage or error.
    """
    try:
        contract = await client.get("/usage/contractInfo")
        projected = []
        for entry in _walk_contract(contract, []):
            try:
                projected.append(_project_feature(entry))
            except Exception:
                continue

        targets = features or [f["feature"] for f in projected if f["role"] == "billable_line"]

        discovery: dict[str, Any]
        if tenant_ids:
            discovery = {
                "tenant_ids": [str(t) for t in tenant_ids],
                "source": "given",
                "untenanted_resources": None,
                "api_calls": 0,
            }
        else:
            discovery = await _discover_tenants(client, tenant_property)
        ids = discovery["tenant_ids"]

        # With a caller's own list the remainder is every tenant NOT asked for as well
        # as untenanted resources, so it is not labelled untenanted.
        remainder_key = "not_in_requested_tenants" if tenant_ids else "untenanted"
        lines = []
        total_calls = 1 + discovery.get("api_calls", 0)  # contract + discovery
        for feature in targets:
            basis = _basis_for(feature, projected)
            portal = await _collect_actuals(client, feature, days, basis, None, month_to_date)
            total_calls += portal["api_calls"]
            line: dict[str, Any] = {
                "feature": feature,
                "basis": basis,
                "unit": portal["unit"],
                "complete_days": portal["complete_days"],
                "portal_total": portal["rolled_up"],
            }
            if feature in _NOT_SPLIT_BY_TENANT:
                line["tenant_split"] = "not supported by LogicMonitor for this feature"
                lines.append(line)
                continue
            if basis is None:
                line["note"] = (
                    "feature not on this contract, so no roll-up basis; "
                    "see get_usage_actuals for its daily series"
                )
                lines.append(line)
                continue
            if not ids:
                line["tenant_split"] = f"no resource carries {tenant_property}"
                lines.append(line)
                continue

            split = await _collect_actuals(client, feature, days, basis, ids, month_to_date)
            total_calls += split["api_calls"]
            by_tenant = {k: v for k, v in split["by_tenant"].items() if v}
            tenants_sum = sum(v for v in by_tenant.values() if v is not None)
            line["tenants"] = by_tenant
            line["tenants_sum"] = round(tenants_sum, 4)
            if portal["rolled_up"] is not None:
                line[remainder_key] = round(portal["rolled_up"] - tenants_sum, 4)
                if portal["rolled_up"]:
                    line["coverage_pct"] = round(tenants_sum / portal["rolled_up"] * 100, 1)
            line["tenants_reading_zero"] = len(split.get("tenants_reading_zero", []))
            if split.get("truncated"):
                line["truncated"] = True
            lines.append(line)

        return format_response(
            {
                "window": "calendar month to date" if month_to_date else f"last {days} days",
                "tenant_property": tenant_property,
                "tenant_source": discovery["source"],
                "tenant_count": len(ids),
                "untenanted_resources": discovery["untenanted_resources"],
                "api_calls": total_calls,
                "discovery_api_calls": discovery.get("api_calls", 0),
                "discovery_cached": bool(discovery.get("cached")),
                "features": lines,
                "note": (
                    "Figures are LogicMonitor's billed usage. The remainder is portal "
                    "total minus the tenants listed: untenanted when tenants were "
                    "discovered, not_in_requested_tenants when a list was given. "
                    "A tenant reading zero may have no "
                    "usage of that feature or may be an id LogicMonitor does not know; "
                    "the API does not distinguish them. CLOUD_PAAS includes Kubernetes "
                    "pods with no separate split."
                ),
            }
        )
    except Exception as e:
        return handle_error(e)


async def get_usage_metrics(client: LogicMonitorClient) -> list[TextContent]:
    """Get portal-wide instantaneous usage counts from /metrics/usage.

    A point-in-time count, not a billing figure. LogicMonitor bills most resource
    features on a rolling average of daily values, so this will never equal what the
    usage page shows and is not a substitute for get_usage_reconciliation.

    Args:
        client: LogicMonitor API client.

    Returns:
        List of TextContent with portal-wide counts or error.
    """
    try:
        result = await client.get("/metrics/usage")
        return format_response(
            {
                "metrics": result,
                "note": (
                    "Instantaneous counts. Billing uses a rolling average of daily "
                    "values for most resource features, so these will not match the "
                    "usage page."
                ),
            }
        )
    except Exception as e:
        return handle_error(e)
