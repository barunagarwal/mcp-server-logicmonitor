# Description: Usage and entitlement tools for LogicMonitor MCP server.
# Description: Exposes /usage/contractInfo and /metrics/usage.

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from mcp.types import TextContent

from lm_mcp.exceptions import NotFoundError
from lm_mcp.tools import format_response, handle_error

if TYPE_CHECKING:
    from lm_mcp.client import LogicMonitorClient

logger = logging.getLogger(__name__)

# The contract's own roll-up basis, carried per feature in aggregationType.
# Applying the wrong one is not a rounding difference: summing a rolling-average
# feature over 30 days overstates it thirtyfold.
_ROLLUP_BASIS = {
    "RAVG": "rolling average of complete daily values",
    "DSUM": "sum of daily values",
    "SUM": "total across the period",
}

# Features whose presence as a billable line marks the billing model.
_HYBRID_FEATURE = "HYBRID_UNITS"
_LEGACY_FEATURES = {"STANDARD_RESOURCES", "CLOUD_IAAS", "CLOUD_PAAS", "WIRELESS_ACCESS_POINTS"}


def _usage_error(error: Exception, path: str) -> list[TextContent]:
    """Handle an error from a usage endpoint.

    A 404 here is not a missing ID, as the generic suggestion says: these endpoints
    take none, so it means the portal does not answer on that path.
    """
    if isinstance(error, NotFoundError):
        error.suggestion = (
            f"The portal answered not found for {path}; it may not offer this endpoint "
            "on this account or API version."
        )
    return handle_error(error)


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
    contract lines: wireless vendor children that each repeat their parent's cap
    multiply the entitlement by the number of vendors.

    A null aggregationType is not the only way a child repeats its parent. Observed
    live: SAAS with five per-product children (Office 365, Salesforce, Slack, Webex,
    Zoom), each carrying the parent's SAME user pool and a non-null RAVG. Treating
    those as separate lines reports five times the pool. The parent's quantity is
    therefore carried down so a child repeating it exactly can be recognised for what
    it is.

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

    Live contracts wrap every quantity in a single-element list: [100], not 100.
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
    quantity [Q, 0] against unit ["User", "Services"]: Q users and no services, not
    a list of candidate numbers.

    The order is NOT fixed. Another portal returns unit ["Services", "User"] with
    quantity [Q, 0]: Q services and no users. So position means nothing on its own:
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
    """Unwrap a unit list. Units arrive as ["Resources"], not "Resources".

    An empty list is no unit at all, so it reads as None rather than [].
    """
    if isinstance(value, list):
        if not value:
            return None
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
    # The walk sets parent_quantity only under a metered parent.
    repeats_parent = parent_quantity is not None and quantity > 0 and quantity == parent_quantity

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
    # say so and show what it actually was. A list its units pair one to one is not
    # a reinterpretation, unless an entry in it was not a number either.
    if quantity_raw is not None and (
        by_unit is None or any(_as_quantity(q)[1] is not None for q in node.get("quantity") or [])
    ):
        projected["entitled_raw"] = quantity_raw
    return projected


def _billing_mode(features: list[dict]) -> str:
    """Detect the billing model from the contract's billable lines."""
    names = {f["feature"] for f in features if f["role"] == "billable_line"}
    if _HYBRID_FEATURE in names:
        return "hybrid"
    if names & _LEGACY_FEATURES:
        return "legacy"
    return "indeterminate"


async def get_usage_contract(
    client: LogicMonitorClient,
    billable_only: bool = False,
) -> list[TextContent]:
    """Get the portal's contracted entitlements from /usage/contractInfo.

    Returns every feature the contract mentions, including ones carrying no
    entitlement, which is where LITE_RESOURCES, SAAS and DYNAMIC_SERVICE_INSIGHTS
    appear on portals that do not licence them. Those rows are invisible on the
    LogicMonitor usage page and are usually what a reconciliation is missing.

    Each feature is classified by its aggregationType:
      billable_line          metered, paid, non-zero entitlement
      metered_no_entitlement metered but entitled zero
      metered_unpaid         carries a quantity and is not billed
      repeats_parent         restates its parent's exact quantity, e.g. SAAS split
                             per product; never an additional commitment
      rollup_or_carveout     repeats or subdivides its parent; never a commitment

    Each line keeps the contract's unit, and entitled_ambiguous when more than one
    unit carries a quantity, since no single figure describes such a line.

    Args:
        client: LogicMonitor API client.
        billable_only: Return only billable_line features.

    Returns:
        List of TextContent with contract features or error.
    """
    try:
        result = await client.get("/usage/contractInfo")

        entries = _walk_contract(result, [])

        # Project per node. A contract shape we have not seen before should cost that
        # one line and name itself, not the whole answer.
        features = []
        unreadable = []
        for entry in entries:
            try:
                features.append(_project_feature(entry))
            except Exception as exc:
                logger.warning(
                    "usage contract: could not read feature %r", entry.get("feature"), exc_info=True
                )
                unreadable.append(
                    {"feature": entry.get("feature"), "reason": f"{type(exc).__name__}: {exc}"}
                )

        # An answer with no features must not read as an empty contract. Either the
        # response held none (empty, or a shape the walk does not know) or none could
        # be read; both say nothing about what the portal is entitled to.
        warnings = []
        if not entries:
            logger.warning(
                "usage contract: no features in the response (%s, keys %s)",
                type(result).__name__,
                sorted(result)[:10] if isinstance(result, dict) else None,
            )
            warnings.append(
                "The /usage/contractInfo response held no contract features. This is not "
                "an empty contract: the response was empty or in a shape this tool does "
                "not read, so no entitlement can be concluded from it."
            )
        elif not features:
            warnings.append(
                "No contract feature could be read (see unreadable_nodes), so no "
                "entitlement can be concluded from this response."
            )

        billing_mode = _billing_mode(features)
        if billable_only:
            features = [f for f in features if f["role"] == "billable_line"]

        features.sort(key=lambda f: (f["parent"] or "", f["feature"]))

        payload: dict[str, Any] = {
            "billing_mode": billing_mode,
            "count": len(features),
            "features": features,
        }
        if unreadable:
            payload["unreadable_nodes"] = unreadable
        if warnings:
            payload["warnings"] = warnings

        return format_response(
            {
                **payload,
                "note": (
                    "billing_mode is detected from the contract, not configured. "
                    "rollup_or_carveout rows are never commitments: a carve-out such "
                    "as LITE_RESOURCES is included in its parent's entitlement, so "
                    "summing a parent and its children double counts."
                ),
            }
        )
    except Exception as e:
        return _usage_error(e, "/usage/contractInfo")


async def get_usage_metrics(client: LogicMonitorClient) -> list[TextContent]:
    """Get portal-wide instantaneous usage counts from /metrics/usage.

    A point-in-time count, not a billing figure. LogicMonitor bills most resource
    features on a rolling average of daily values (see each feature's basis in
    get_usage_contract), so this will not equal what the usage page shows.

    Args:
        client: LogicMonitor API client.

    Returns:
        List of TextContent with portal-wide counts or error.
    """
    try:
        result = await client.get("/metrics/usage")
        payload: dict[str, Any] = {
            "metrics": result,
            "note": (
                "Instantaneous counts, not billing figures. Billing uses each "
                "feature's own basis, a rolling average of daily values for most "
                "resource features, so these will not match the usage page."
            ),
        }
        # An empty or non-object answer is not a portal with nothing in it.
        if not isinstance(result, dict) or not result:
            logger.warning("usage metrics: no counts in the response (%s)", type(result).__name__)
            payload["warnings"] = [
                "The /metrics/usage response held no counts (it was empty or not an "
                "object), so it says nothing about the portal's usage."
            ]
        return format_response(payload)
    except Exception as e:
        return _usage_error(e, "/metrics/usage")
