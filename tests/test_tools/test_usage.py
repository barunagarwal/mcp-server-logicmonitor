# Description: Tests for usage and entitlement MCP tools.
# Description: Validates contract walking, roll-up basis, day filtering and stitching.

import json
from datetime import UTC

import httpx
import pytest
import respx

from lm_mcp.auth.bearer import BearerAuth
from lm_mcp.client import LogicMonitorClient
from lm_mcp.tools.usage import (
    _DAY_MS,
    _as_quantity,
    _basis_for,
    _collect_actuals,
    _complete_days_only,
    _day_of,
    _dedupe,
    _discover_tenants,
    _extract_items,
    _headline_entitlement,
    _pair_units,
    _project_feature,
    _roll_up,
    _walk_contract,
    get_usage_actuals,
    get_usage_by_tenant,
    get_usage_contract,
    get_usage_reconciliation,
)


@pytest.fixture(autouse=True)
def _clear_discovery_cache():
    """Tenant discovery is cached per portal; tests must not see each other's."""
    from lm_mcp.tools import usage as mod

    mod._DISCOVERY_CACHE.clear()
    yield
    mod._DISCOVERY_CACHE.clear()


@pytest.fixture
def auth():
    return BearerAuth("test-token")


@pytest.fixture
def client(auth):
    return LogicMonitorClient(
        base_url="https://test.logicmonitor.com/santaba/rest",
        auth=auth,
        timeout=30,
        api_version=3,
    )


def _hybrid_contract() -> dict:
    """Synthetic hybrid contract: a parent with vendor children that repeat its cap,
    plus a carve-out and a feature carrying no entitlement."""
    return {
        "product": "PLATFORM",
        "childProducts": [
            {
                "feature": "HYBRID_UNITS",
                "quantity": 2710,
                "unit": "Units",
                "aggregationType": "RAVG",
                "subscriptions": [{"sku": "HYB"}],
            },
            {
                "feature": "LOGS",
                "quantity": 2032.5,
                "unit": "GB",
                "aggregationType": "DSUM",
                "subscriptions": [{"sku": "LGE"}],
            },
            {
                "feature": "WIRELESS_ACCESS_POINTS",
                "quantity": 1000,
                "unit": "Units",
                "aggregationType": "RAVG",
                "childProducts": [
                    {"feature": "VENDOR_A_AP", "quantity": 1000, "aggregationType": None},
                    {"feature": "VENDOR_B_AP", "quantity": 1000, "aggregationType": None},
                ],
            },
            {
                "feature": "STANDARD_RESOURCES",
                "quantity": 28700,
                "unit": "Units",
                "aggregationType": "RAVG",
                "nestedProducts": [
                    {"feature": "LITE_RESOURCES", "quantity": 1700, "aggregationType": None},
                ],
            },
            {
                "feature": "SAAS",
                "quantity": 0,
                "unit": "Users",
                "aggregationType": "RAVG",
            },
            {
                "feature": "DYNAMIC_SERVICE_INSIGHTS",
                "quantity": 27,
                "unit": "Units",
                "aggregationType": "RAVG",
                "unpaid": True,
            },
        ],
    }


class TestContractWalk:
    def test_vendor_children_never_become_entitlements(self):
        entries = _walk_contract(_hybrid_contract(), [])
        projected = {f["feature"]: f for f in (_project_feature(e) for e in entries)}

        assert projected["WIRELESS_ACCESS_POINTS"]["entitled"] == 1000
        # Nine children each repeating 1,000 is how a 9,000-unit phantom appears.
        assert projected["VENDOR_A_AP"]["role"] == "rollup_or_carveout"
        assert projected["VENDOR_B_AP"]["role"] == "rollup_or_carveout"

    def test_parentage_is_kept(self):
        entries = _walk_contract(_hybrid_contract(), [])
        projected = {f["feature"]: f for f in (_project_feature(e) for e in entries)}

        assert projected["VENDOR_A_AP"]["parent"] == "WIRELESS_ACCESS_POINTS"
        assert projected["LITE_RESOURCES"]["parent"] == "STANDARD_RESOURCES"
        assert projected["HYBRID_UNITS"]["parent"] is None

    def test_nested_products_are_walked(self):
        features = {e["feature"] for e in _walk_contract(_hybrid_contract(), [])}
        assert "LITE_RESOURCES" in features

    def test_roles(self):
        entries = _walk_contract(_hybrid_contract(), [])
        projected = {f["feature"]: f for f in (_project_feature(e) for e in entries)}

        assert projected["HYBRID_UNITS"]["role"] == "billable_line"
        assert projected["SAAS"]["role"] == "metered_no_entitlement"
        assert projected["DYNAMIC_SERVICE_INSIGHTS"]["role"] == "metered_unpaid"
        assert projected["LITE_RESOURCES"]["role"] == "rollup_or_carveout"

    def test_sku_is_captured(self):
        entries = _walk_contract(_hybrid_contract(), [])
        projected = {f["feature"]: f for f in (_project_feature(e) for e in entries)}
        assert projected["LOGS"]["sku"] == "LGE"

    def test_malformed_nodes_do_not_raise(self):
        assert _walk_contract(None, []) == []
        assert _walk_contract("string", []) == []
        assert _walk_contract({"childProducts": [None, 7]}, []) == []


class TestQuantityCoercion:
    """A live contract returned a list where a scalar quantity was expected, and the
    comparison in _project_feature raised. Every fixture here used a scalar, so
    nothing caught it until the first real call."""

    def test_scalars_pass_through_untouched(self):
        assert _as_quantity(2710) == (2710.0, None)
        assert _as_quantity(52.5) == (52.5, None)
        assert _as_quantity(None) == (0.0, None)

    def test_numeric_string_is_accepted(self):
        assert _as_quantity(" 1700 ") == (1700.0, None)

    def test_junk_string_is_zero_and_keeps_the_raw_value(self):
        assert _as_quantity("n/a") == (0.0, "n/a")

    def test_single_element_list_is_the_normal_shape(self):
        # Live contracts wrap every quantity: [2710], not 2710. That is not odd,
        # so it must not be flagged as a reinterpretation.
        assert _as_quantity([2710]) == (2710.0, None)
        assert _as_quantity([2032.5]) == (2032.5, None)

    def test_multi_element_list_collapses_to_max_and_keeps_raw(self):
        qty, raw = _as_quantity([100, 2710, 50])
        assert qty == 2710.0
        assert raw == [100, 2710, 50]

    def test_empty_and_nested_lists(self):
        assert _as_quantity([])[0] == 0.0
        assert _as_quantity([[5], [9]])[0] == 9.0

    def test_dict_with_quantity_key(self):
        assert _as_quantity({"quantity": 42})[0] == 42.0

    def test_bool_is_not_a_quantity(self):
        # bool subclasses int; True must not read as an entitlement of 1.
        assert _as_quantity(True)[0] == 0.0

    def test_list_quantity_classifies_instead_of_raising(self):
        # The exact crash: a wrapped quantity must classify, not raise.
        node = {"feature": "X", "quantity": [1000], "aggregationType": "RAVG"}
        projected = _project_feature({"feature": "X", "node": node, "parent": None})
        assert projected["role"] == "billable_line"
        assert projected["entitled"] == 1000.0
        assert "entitled_raw" not in projected

    def test_ambiguous_multi_value_quantity_is_surfaced(self):
        node = {"feature": "X", "quantity": [1000, 2000], "aggregationType": "RAVG"}
        projected = _project_feature({"feature": "X", "node": node, "parent": None})
        assert projected["entitled"] == 2000.0
        assert projected["entitled_raw"] == [1000, 2000]

    def test_unit_is_unwrapped(self):
        node = {"feature": "X", "quantity": [5], "unit": ["Resources"], "aggregationType": "RAVG"}
        projected = _project_feature({"feature": "X", "node": node, "parent": None})
        assert projected["unit"] == "Resources"

    def test_scalar_quantity_has_no_raw_field(self):
        node = {"feature": "Y", "quantity": 5, "aggregationType": "RAVG"}
        projected = _project_feature({"feature": "Y", "node": node, "parent": None})
        assert "entitled_raw" not in projected


def _saas_contract() -> dict:
    """Live-shaped: SAAS entitled in two units at once, restated per product."""
    per_product = lambda name: {  # noqa: E731
        "feature": name,
        "quantity": [29000, 0],
        "unit": ["User", "Services"],
        "aggregationType": "RAVG",
    }
    return {
        "childProducts": [
            {
                "feature": "SAAS",
                "quantity": [29000, 0],
                "unit": ["User", "Services"],
                "aggregationType": "RAVG",
                "childProducts": [
                    per_product("SAAS_OFFICE365"),
                    per_product("SAAS_SALESFORCE"),
                    per_product("SAAS_SLACK"),
                    per_product("SAAS_WEBEX"),
                    per_product("SAAS_ZOOM"),
                ],
            },
        ]
    }


class TestUnitPairing:
    """quantity and unit are PARALLEL arrays. Observed live: [29000, 0] against
    ["User", "Services"] -- 29,000 users and zero services, not two candidate
    numbers. Taking the max loses which unit the number is even in."""

    def test_pairs_quantity_with_unit(self):
        assert _pair_units([29000, 0], ["User", "Services"]) == {
            "User": 29000.0,
            "Services": 0.0,
        }

    def test_ignores_mismatched_lengths(self):
        assert _pair_units([1, 2], ["a"]) is None

    def test_ignores_the_ordinary_single_valued_shape(self):
        assert _pair_units([5], ["Resources"]) is None

    def test_ignores_non_lists(self):
        assert _pair_units(5, "Resources") is None

    def test_projection_exposes_the_split(self):
        entries = _walk_contract(_saas_contract(), [])
        saas = next(_project_feature(e) for e in entries if e["feature"] == "SAAS")
        assert saas["entitled"] == 29000.0
        assert saas["entitled_by_unit"] == {"User": 29000.0, "Services": 0.0}


class TestUnitOrderIsNotFixed:
    """The same feature returns its units in different orders on different portals:
    ["User", "Services"] on one, ["Services", "User"] on another. Reading index 0, or
    taking the largest, yields a number whose unit depends on which portal you asked."""

    def test_opposite_orders_both_resolve_correctly(self):
        users_first = _pair_units([29000, 0], ["User", "Services"])
        services_first = _pair_units([1, 0], ["Services", "User"])

        qty_a, unit_a, amb_a = _headline_entitlement(users_first, 0.0)
        qty_b, unit_b, amb_b = _headline_entitlement(services_first, 0.0)

        assert (qty_a, unit_a) == (29000.0, "User")
        assert (qty_b, unit_b) == (1.0, "Services")
        assert not amb_a and not amb_b

    def test_two_non_zero_units_are_flagged_not_guessed(self):
        qty, unit, ambiguous = _headline_entitlement({"User": 500.0, "Services": 20.0}, 0.0)
        assert ambiguous is True
        # Still names the unit of whatever figure it reported.
        assert (qty, unit) == (500.0, "User")

    def test_all_zero_is_zero_not_ambiguous(self):
        assert _headline_entitlement({"User": 0.0, "Services": 0.0}, 0.0) == (0.0, None, False)

    def test_falls_back_when_there_is_no_pairing(self):
        assert _headline_entitlement(None, 77.0) == (77.0, None, False)

    def test_projection_names_the_unit_it_reported(self):
        node = {
            "feature": "SAAS",
            "quantity": [1, 0],
            "unit": ["Services", "User"],
            "aggregationType": "RAVG",
        }
        projected = _project_feature(
            {"feature": "SAAS", "node": node, "parent": None, "parent_quantity": None}
        )
        assert projected["entitled"] == 1.0
        assert projected["unit"] == "Services"
        assert projected["entitled_by_unit"] == {"Services": 1.0, "User": 0.0}
        assert "entitled_ambiguous" not in projected


class TestRepeatedParentQuantity:
    """A null aggregationType is not the only way a child repeats its parent.
    SAAS has five per-product children, each carrying the parent's full 29,000 with
    a non-null RAVG. Counted as separate lines they report 145,000 of entitlement
    against a pool of 29,000."""

    def test_per_product_children_are_marked_as_repeats(self):
        entries = _walk_contract(_saas_contract(), [])
        projected = {e["feature"]: _project_feature(e) for e in entries}

        assert projected["SAAS"]["role"] == "billable_line"
        for name in ("SAAS_OFFICE365", "SAAS_SALESFORCE", "SAAS_SLACK", "SAAS_WEBEX", "SAAS_ZOOM"):
            assert projected[name]["role"] == "repeats_parent", name

    def test_entitlement_is_not_multiplied_by_the_children(self):
        entries = _walk_contract(_saas_contract(), [])
        billable = [
            p for p in (_project_feature(e) for e in entries) if p["role"] == "billable_line"
        ]
        assert sum(p["entitled"] for p in billable) == 29000.0

    def test_a_carve_out_subdivides_and_is_not_a_repeat(self):
        # 27,000 + 1,700 = 28,700: children that split a pool, not restate it.
        entries = _walk_contract(_hybrid_contract(), [])
        projected = {(e["feature"], e["parent"]): _project_feature(e) for e in entries}
        lite = projected[("LITE_RESOURCES", "STANDARD_RESOURCES")]
        assert lite["role"] == "rollup_or_carveout"
        assert lite["entitled"] == 1700.0

    @respx.mock
    async def test_billable_only_excludes_repeats(self, client):
        respx.get("https://test.logicmonitor.com/santaba/rest/usage/contractInfo").mock(
            return_value=httpx.Response(200, json=_saas_contract())
        )
        data = json.loads((await get_usage_contract(client, billable_only=True))[0].text)
        assert {f["feature"] for f in data["features"]} == {"SAAS"}


class TestGetUsageContract:
    @respx.mock
    async def test_detects_hybrid_and_keeps_unentitled_rows(self, client):
        respx.get("https://test.logicmonitor.com/santaba/rest/usage/contractInfo").mock(
            return_value=httpx.Response(200, json=_hybrid_contract())
        )
        result = await get_usage_contract(client)
        data = json.loads(result[0].text)

        assert data["billing_mode"] == "hybrid"
        names = {f["feature"] for f in data["features"]}
        # The whole point: features with no entitlement are still reported.
        assert "SAAS" in names
        assert "LITE_RESOURCES" in names

    @respx.mock
    async def test_detects_legacy(self, client):
        legacy = {
            "childProducts": [
                {"feature": "STANDARD_RESOURCES", "quantity": 7500, "aggregationType": "RAVG"},
                {"feature": "CLOUD_PAAS", "quantity": 550, "aggregationType": "RAVG"},
            ]
        }
        respx.get("https://test.logicmonitor.com/santaba/rest/usage/contractInfo").mock(
            return_value=httpx.Response(200, json=legacy)
        )
        data = json.loads((await get_usage_contract(client))[0].text)
        assert data["billing_mode"] == "legacy"

    @respx.mock
    async def test_billable_only_filters(self, client):
        respx.get("https://test.logicmonitor.com/santaba/rest/usage/contractInfo").mock(
            return_value=httpx.Response(200, json=_hybrid_contract())
        )
        data = json.loads((await get_usage_contract(client, billable_only=True))[0].text)
        assert {f["role"] for f in data["features"]} == {"billable_line"}

    @respx.mock
    async def test_unprojectable_node_costs_one_line_not_the_call(self, client):
        payload = {
            "childProducts": [
                {"feature": "OK", "quantity": 1, "aggregationType": "RAVG"},
                {"feature": "ODD", "quantity": {"nested": {"deep": 1}}, "aggregationType": "RAVG"},
            ]
        }
        respx.get("https://test.logicmonitor.com/santaba/rest/usage/contractInfo").mock(
            return_value=httpx.Response(200, json=payload)
        )
        data = json.loads((await get_usage_contract(client))[0].text)
        assert "OK" in {f["feature"] for f in data["features"]}

    @respx.mock
    async def test_api_error_is_handled(self, client):
        respx.get("https://test.logicmonitor.com/santaba/rest/usage/contractInfo").mock(
            return_value=httpx.Response(500, json={"errmsg": "boom"})
        )
        result = await get_usage_contract(client)
        assert result and result[0].text


def _iso(offset_days: int) -> str:
    """A ChargePeriodStart as the API really sends it: an ISO date STRING.

    startTime and endTime in the REQUEST are epoch milliseconds, but this field in
    the RESPONSE is a string. Parsing it as a number discards every row silently.
    """
    from datetime import datetime, timedelta

    return (datetime.now(UTC) + timedelta(days=offset_days)).strftime("%Y-%m-%dT00:00:00Z")


class TestDayFiltering:
    def test_iso_date_string_is_parsed(self):
        from datetime import datetime, timedelta

        expected = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")
        assert _day_of({"ChargePeriodStart": _iso(-1)}) == expected

    def test_missing_field_is_empty_not_an_error(self):
        assert _day_of({}) == ""

    def test_today_and_future_rows_are_dropped(self):
        import time as _time

        now = int(_time.time() * 1000)
        rows = [
            {"ChargePeriodStart": _iso(-2), "ConsumedQuantity": 10},
            {"ChargePeriodStart": _iso(-1), "ConsumedQuantity": 10},
            {"ChargePeriodStart": _iso(0), "ConsumedQuantity": 3},  # partial
            {"ChargePeriodStart": _iso(1), "ConsumedQuantity": 0},  # padded forward
        ]
        kept = _complete_days_only(rows, now)
        assert len(kept) == 2
        assert all(r["ConsumedQuantity"] == 10 for r in kept)

    def test_unparseable_dates_are_dropped_not_crashed(self):
        import time as _time

        assert (
            _complete_days_only([{"ChargePeriodStart": "nope"}, {}], int(_time.time() * 1000)) == []
        )

    def test_dedupe_on_day_and_subaccount(self):
        rows = [
            {"ChargePeriodStart": _iso(-1), "SubAccountId": "a", "ConsumedQuantity": 5},
            {"ChargePeriodStart": _iso(-1), "SubAccountId": "a", "ConsumedQuantity": 5},
            {"ChargePeriodStart": _iso(-1), "SubAccountId": "b", "ConsumedQuantity": 7},
            {"ChargePeriodStart": _iso(-2), "SubAccountId": "a", "ConsumedQuantity": 5},
        ]
        assert len(_dedupe(rows)) == 3


class TestResponseEnvelope:
    """List responses arrive as items, data or rows, or nested one level under any
    of those. Checking only "items" loses the rest."""

    def test_top_level_shapes(self):
        assert _extract_items({"items": [{"a": 1}], "total": 1})[0] == [{"a": 1}]
        assert _extract_items({"data": [{"a": 1}]})[0] == [{"a": 1}]
        assert _extract_items({"rows": [{"a": 1}]})[0] == [{"a": 1}]

    def test_nested_shape(self):
        assert _extract_items({"data": {"items": [{"a": 1}], "total": 1}})[0] == [{"a": 1}]

    def test_absent_or_non_dict(self):
        assert _extract_items({"nope": 1})[0] == []
        assert _extract_items(None)[0] == []

    def test_total_is_coerced_and_bad_total_tolerated(self):
        assert _extract_items({"items": [], "total": "7"})[1] == 7
        assert _extract_items({"items": [], "total": "x"})[1] is None


class TestRollUp:
    def test_ravg_averages_and_dsum_sums(self):
        daily = [10.0] * 30
        assert _roll_up(daily, "RAVG") == 10.0
        # Summing a rolling-average feature over 30 days overstates it thirtyfold.
        assert _roll_up(daily, "DSUM") == 300.0

    def test_sum_totals(self):
        assert _roll_up([1.0, 2.0, 3.0], "SUM") == 6.0

    def test_unknown_or_missing_basis_returns_none(self):
        assert _roll_up([1.0], None) is None
        assert _roll_up([1.0], "MYSTERY") is None

    def test_empty_series_returns_none(self):
        assert _roll_up([], "RAVG") is None


def _usage_rows(now_ms: int, qty: float, sub: str = "tenant-1") -> dict:
    """Live-shaped focusCostUsage response: ISO date strings, total present."""
    return {
        "items": [
            {
                "ChargePeriodStart": _iso(-2),
                "SubAccountId": sub,
                "SubAccountName": "TenantX",
                "ConsumedQuantity": qty,
                "ConsumedUnit": "Units",
            },
            {
                "ChargePeriodStart": _iso(-1),
                "SubAccountId": sub,
                "SubAccountName": "TenantX",
                "ConsumedQuantity": qty,
                "ConsumedUnit": "Units",
            },
            # Padded forward past today; must not be counted.
            {
                "ChargePeriodStart": _iso(1),
                "SubAccountId": sub,
                "SubAccountName": "TenantX",
                "ConsumedQuantity": 0,
                "ConsumedUnit": "Units",
            },
        ],
        "total": 3,
    }


class TestGetUsageActuals:
    @respx.mock
    async def test_stitches_dedupes_and_rolls_up(self, client):
        import time as _time

        now_ms = int(_time.time() * 1000)
        respx.get("https://test.logicmonitor.com/santaba/rest/usage/focusCostUsage").mock(
            return_value=httpx.Response(200, json=_usage_rows(now_ms, 100.0))
        )
        # Pin the window to "last 6 days". The default (calendar month to date) is only
        # hours long on the 1st of a month, which collapses to a single call and made
        # this test fail on that day.
        result = await get_usage_actuals(
            client, "HYBRID_UNITS", days=6, basis="RAVG", month_to_date=False
        )
        data = json.loads(result[0].text)

        # Every stitched window returns the same rows; de-duplication must collapse
        # them to the two complete days.
        assert data["complete_days"] == 2
        assert data["rolled_up"] == 100.0
        assert data["api_calls"] >= 2
        # Per-line figures roll up on the same basis as the total, keyed by id.
        assert data["by_tenant"]["tenant-1"] == 100.0

    @respx.mock
    async def test_logs_converted_from_bytes_to_gb(self, client):
        import time as _time

        now_ms = int(_time.time() * 1000)
        respx.get("https://test.logicmonitor.com/santaba/rest/usage/focusCostUsage").mock(
            return_value=httpx.Response(200, json=_usage_rows(now_ms, 2_000_000_000.0))
        )
        data = json.loads((await get_usage_actuals(client, "LOGS", days=4, basis="DSUM"))[0].text)

        assert data["unit"] == "GB"
        assert data["rolled_up"] == 4.0  # 2 GB on each of two complete days
        assert "bytes to GB" in data["note"]

    @respx.mock
    async def test_missing_basis_returns_series_without_rollup(self, client):
        import time as _time

        now_ms = int(_time.time() * 1000)
        respx.get("https://test.logicmonitor.com/santaba/rest/usage/focusCostUsage").mock(
            return_value=httpx.Response(200, json=_usage_rows(now_ms, 10.0))
        )
        data = json.loads((await get_usage_actuals(client, "HYBRID_UNITS", days=4))[0].text)

        assert data["rolled_up"] is None
        assert data["daily"]
        assert "get_usage_contract" in data["note"]

    @respx.mock
    async def test_required_params_are_sent(self, client):
        import time as _time

        now_ms = int(_time.time() * 1000)
        route = respx.get("https://test.logicmonitor.com/santaba/rest/usage/focusCostUsage").mock(
            return_value=httpx.Response(200, json=_usage_rows(now_ms, 1.0))
        )

        await get_usage_actuals(client, "HYBRID_UNITS", days=4, basis="RAVG")

        sent = route.calls[0].request.url.params
        # Both are required and only "tenant" is accepted as the dimension.
        assert sent["feature"] == "HYBRID_UNITS"
        assert sent["dimensionKey"] == "tenant"
        # Times are epoch MILLISECONDS; seconds are rejected by the API.
        assert int(sent["startTime"]) > 1_000_000_000_000
        # endTime does not bound the window but the API rejects a request without it.
        assert int(sent["endTime"]) > int(sent["startTime"])

    @respx.mock
    async def test_empty_feed_does_not_crash(self, client):
        respx.get("https://test.logicmonitor.com/santaba/rest/usage/focusCostUsage").mock(
            return_value=httpx.Response(200, json={"items": []})
        )
        data = json.loads((await get_usage_actuals(client, "X", days=4, basis="RAVG"))[0].text)
        assert data["complete_days"] == 0
        assert data["rolled_up"] is None


class TestBillingWindow:
    """LogicMonitor bills the calendar month to date and resets on the 1st, so a
    figure meant to match the usage page cannot start N days back."""

    def test_month_start_is_first_of_month_utc(self):
        from datetime import datetime

        from lm_mcp.tools.usage import _month_start_ms

        now = int(datetime(2026, 9, 17, 11, 30, tzinfo=UTC).timestamp() * 1000)
        start = _month_start_ms(now)
        as_dt = datetime.fromtimestamp(start / 1000, tz=UTC)
        assert (as_dt.day, as_dt.hour, as_dt.minute, as_dt.second) == (1, 0, 0, 0)
        assert (as_dt.year, as_dt.month) == (2026, 9)

    def test_month_start_on_the_first_is_that_midnight(self):
        from datetime import datetime

        from lm_mcp.tools.usage import _month_start_ms

        now = int(datetime(2026, 3, 1, 0, 5, tzinfo=UTC).timestamp() * 1000)
        as_dt = datetime.fromtimestamp(_month_start_ms(now) / 1000, tz=UTC)
        assert (as_dt.month, as_dt.day, as_dt.hour) == (3, 1, 0)

    @respx.mock
    async def test_month_to_date_starts_at_the_first_not_days_back(self, client):
        import time as _time

        now_ms = int(_time.time() * 1000)
        route = respx.get("https://test.logicmonitor.com/santaba/rest/usage/focusCostUsage").mock(
            return_value=httpx.Response(200, json=_usage_rows(now_ms, 1.0))
        )

        await get_usage_actuals(client, "HYBRID_UNITS", days=30, basis="RAVG")

        from lm_mcp.tools.usage import _month_start_ms

        first_start = int(route.calls[0].request.url.params["startTime"])
        assert first_start == _month_start_ms(now_ms)

    @respx.mock
    async def test_days_back_is_available_when_asked_for(self, client):
        import time as _time

        now_ms = int(_time.time() * 1000)
        route = respx.get("https://test.logicmonitor.com/santaba/rest/usage/focusCostUsage").mock(
            return_value=httpx.Response(200, json=_usage_rows(now_ms, 1.0))
        )

        await get_usage_actuals(client, "HYBRID_UNITS", days=4, basis="RAVG", month_to_date=False)
        first_start = int(route.calls[0].request.url.params["startTime"])
        assert abs(first_start - (now_ms - 4 * _DAY_MS)) < 5000


class TestReconciliation:
    @respx.mock
    async def test_uses_each_lines_own_basis_and_lists_carveouts(self, client):
        import time as _time

        now_ms = int(_time.time() * 1000)
        respx.get("https://test.logicmonitor.com/santaba/rest/usage/contractInfo").mock(
            return_value=httpx.Response(200, json=_hybrid_contract())
        )
        respx.get("https://test.logicmonitor.com/santaba/rest/usage/focusCostUsage").mock(
            return_value=httpx.Response(200, json=_usage_rows(now_ms, 1355.0))
        )

        data = json.loads(
            (await get_usage_reconciliation(client, days=4, features=["HYBRID_UNITS"]))[0].text
        )

        line = data["lines"][0]
        assert line["feature"] == "HYBRID_UNITS"
        assert line["basis"] == "RAVG"
        assert line["entitled"] == 2710
        assert line["used"] == 1355.0
        assert line["utilisation_pct"] == 50.0

    @respx.mock
    async def test_carveouts_are_attached_to_their_parent(self, client):
        import time as _time

        now_ms = int(_time.time() * 1000)
        respx.get("https://test.logicmonitor.com/santaba/rest/usage/contractInfo").mock(
            return_value=httpx.Response(200, json=_hybrid_contract())
        )
        respx.get("https://test.logicmonitor.com/santaba/rest/usage/focusCostUsage").mock(
            return_value=httpx.Response(200, json=_usage_rows(now_ms, 1.0))
        )
        result = await get_usage_reconciliation(client, days=4, features=["STANDARD_RESOURCES"])
        data = json.loads(result[0].text)
        assert data["lines"][0]["carve_outs"] == ["LITE_RESOURCES"]

    @respx.mock
    async def test_unentitled_features_are_surfaced(self, client):
        import time as _time

        now_ms = int(_time.time() * 1000)
        respx.get("https://test.logicmonitor.com/santaba/rest/usage/contractInfo").mock(
            return_value=httpx.Response(200, json=_hybrid_contract())
        )
        respx.get("https://test.logicmonitor.com/santaba/rest/usage/focusCostUsage").mock(
            return_value=httpx.Response(200, json=_usage_rows(now_ms, 1.0))
        )
        data = json.loads(
            (await get_usage_reconciliation(client, days=4, features=["HYBRID_UNITS"]))[0].text
        )
        surfaced = set(data["features_present_without_entitlement"])
        assert "SAAS" in surfaced
        assert "DYNAMIC_SERVICE_INSIGHTS" in surfaced


class TestCollectActualsDirectly:
    @respx.mock
    async def test_returns_plain_dict_not_textcontent(self, client):
        import time as _time

        now_ms = int(_time.time() * 1000)
        respx.get("https://test.logicmonitor.com/santaba/rest/usage/focusCostUsage").mock(
            return_value=httpx.Response(200, json=_usage_rows(now_ms, 5.0))
        )
        data = await _collect_actuals(client, "HYBRID_UNITS", 4, "RAVG", None)
        assert isinstance(data, dict)
        assert data["rolled_up"] == 5.0


# ---------------------------------------------------------------- per-tenant mode
_BASE = "https://test.logicmonitor.com/santaba/rest"
_TENANT_QTY = {"tenant-x": 60.0, "tenant-y": 25.0, "tenant-z": 0.0}
_PORTAL_QTY = 100.0


def _tenant_feed(request):
    """Synthetic focusCostUsage that behaves like the live per-tenant mode.

    No tenantIds -> one portal line under a GUID. tenantIds -> one line per id sent,
    echoed back (unknown ids read zero), plus an Overall line summing them.
    """
    ids = request.url.params.get_list("tenantIds")
    rows = []
    for offset_days in (-2, -1, 1):  # two complete days and one padded
        day = _iso(offset_days)
        if not ids:
            rows.append(
                {
                    "ChargePeriodStart": day,
                    "SubAccountId": "0f0f0f0f",
                    "SubAccountName": "0f0f0f0f",
                    "ConsumedQuantity": _PORTAL_QTY,
                }
            )
            continue
        for t in ids:
            q = _TENANT_QTY.get(t, 0.0)
            rows.append(
                {
                    "ChargePeriodStart": day,
                    "SubAccountId": t,
                    "SubAccountName": t,
                    "ConsumedQuantity": q,
                }
            )
        rows.append(
            {
                "ChargePeriodStart": day,
                "SubAccountId": "Overall cumulative usage",
                "SubAccountName": "Overall cumulative usage",
                "ConsumedQuantity": sum(_TENANT_QTY.get(t, 0.0) for t in ids),
            }
        )
    return httpx.Response(200, json={"items": rows, "total": len(rows)})


class TestTenantMode:
    @respx.mock
    async def test_overall_line_is_not_counted_twice(self, client):
        respx.get(f"{_BASE}/usage/focusCostUsage").mock(side_effect=_tenant_feed)
        data = await _collect_actuals(
            client, "HYBRID_UNITS", 4, "RAVG", ["tenant-x", "tenant-y"], month_to_date=False
        )
        # 60 + 25 per day. Counting the Overall line as well would give 170.
        assert {d["quantity"] for d in data["daily"]} == {85.0}
        assert data["rolled_up"] == 85.0
        assert "Overall cumulative usage" not in data["by_tenant"]

    @respx.mock
    async def test_each_tenant_rolls_up_on_the_basis(self, client):
        respx.get(f"{_BASE}/usage/focusCostUsage").mock(side_effect=_tenant_feed)
        data = await _collect_actuals(
            client, "HYBRID_UNITS", 4, "RAVG", ["tenant-x", "tenant-y"], month_to_date=False
        )
        # A rolling average per tenant, not a sum over the days.
        assert data["by_tenant"] == {"tenant-x": 60.0, "tenant-y": 25.0}

    @respx.mock
    async def test_unknown_or_idle_ids_are_named(self, client):
        respx.get(f"{_BASE}/usage/focusCostUsage").mock(side_effect=_tenant_feed)
        data = await _collect_actuals(
            client,
            "HYBRID_UNITS",
            4,
            "RAVG",
            ["tenant-x", "tenant-z", "no-such-id"],
            month_to_date=False,
        )
        assert data["tenants_requested"] == 3
        assert set(data["tenants_reading_zero"]) == {"tenant-z", "no-such-id"}

    @respx.mock
    async def test_ids_are_sent_in_batches_of_forty(self, client):
        route = respx.get(f"{_BASE}/usage/focusCostUsage").mock(side_effect=_tenant_feed)
        ids = [f"tenant-{i}" for i in range(85)]
        await _collect_actuals(client, "HYBRID_UNITS", 2, "RAVG", ids, month_to_date=False)
        sizes = sorted({len(c.request.url.params.get_list("tenantIds")) for c in route.calls})
        assert sizes == [5, 40]
        sent = set()
        for c in route.calls:
            sent.update(c.request.url.params.get_list("tenantIds"))
        assert sent == set(ids)

    @respx.mock
    async def test_portal_mode_is_unchanged(self, client):
        respx.get(f"{_BASE}/usage/focusCostUsage").mock(side_effect=_tenant_feed)
        data = await _collect_actuals(client, "HYBRID_UNITS", 4, "RAVG", None, month_to_date=False)
        assert data["rolled_up"] == _PORTAL_QTY
        assert "tenants_reading_zero" not in data


class TestBasisFor:
    def test_carveout_inherits_its_parents_basis(self):
        projected = [_project_feature(e) for e in _walk_contract(_hybrid_contract(), [])]
        assert _basis_for("LITE_RESOURCES", projected) == _basis_for(
            "STANDARD_RESOURCES", projected
        )
        assert _basis_for("LOGS", projected) == "DSUM"
        assert _basis_for("NOT_ON_CONTRACT", projected) is None


def _groups(with_tenants: bool) -> dict:
    items = [{"id": 1, "customProperties": []}]
    if with_tenants:
        items += [
            {
                "id": 2,
                "customProperties": [{"name": "system.tenant.identifier", "value": "tenant-x"}],
            },
            {
                "id": 3,
                "customProperties": [{"name": "system.tenant.identifier", "value": "tenant-y"}],
            },
        ]
    return {"items": items, "total": len(items)}


def _devices() -> dict:
    items = [
        {
            "id": 1,
            "inheritedProperties": [{"name": "system.tenant.identifier", "value": "tenant-x"}],
        },
        {"id": 2, "customProperties": [{"name": "system.tenant.identifier", "value": "tenant-y"}]},
        {"id": 3, "customProperties": []},
        {"id": 4, "systemProperties": [{"name": "other", "value": "v"}]},
    ]
    return {"items": items, "total": len(items)}


class TestDiscoverTenants:
    @respx.mock
    async def test_groups_first(self, client):
        respx.get(f"{_BASE}/device/groups").mock(
            return_value=httpx.Response(200, json=_groups(True))
        )
        devices = respx.get(f"{_BASE}/device/devices").mock(
            return_value=httpx.Response(200, json=_devices())
        )
        found = await _discover_tenants(client, "system.tenant.identifier")
        assert found["tenant_ids"] == ["tenant-x", "tenant-y"]
        assert found["source"] == "resource groups"
        assert not devices.called

    @respx.mock
    async def test_falls_back_to_resources_and_counts_untenanted(self, client):
        respx.get(f"{_BASE}/device/groups").mock(
            return_value=httpx.Response(200, json=_groups(False))
        )
        respx.get(f"{_BASE}/device/devices").mock(return_value=httpx.Response(200, json=_devices()))
        found = await _discover_tenants(client, "system.tenant.identifier")
        assert found["tenant_ids"] == ["tenant-x", "tenant-y"]
        assert found["source"] == "resources"
        assert found["untenanted_resources"] == 2


class TestGetUsageByTenant:
    @respx.mock
    async def test_split_with_untenanted_remainder(self, client):
        respx.get(f"{_BASE}/usage/contractInfo").mock(
            return_value=httpx.Response(200, json=_hybrid_contract())
        )
        respx.get(f"{_BASE}/usage/focusCostUsage").mock(side_effect=_tenant_feed)
        data = json.loads(
            (
                await get_usage_by_tenant(
                    client,
                    features=["HYBRID_UNITS"],
                    tenant_ids=["tenant-x", "tenant-y"],
                    days=4,
                    month_to_date=False,
                )
            )[0].text
        )
        line = data["features"][0]
        assert line["basis"] == "RAVG"
        assert line["portal_total"] == 100.0
        assert line["tenants"] == {"tenant-x": 60.0, "tenant-y": 25.0}
        # A caller's own list: the remainder includes tenants not asked for.
        assert line["not_in_requested_tenants"] == 15.0
        assert "untenanted" not in line
        assert line["coverage_pct"] == 85.0
        assert data["tenant_source"] == "given"

    @respx.mock
    async def test_features_lm_does_not_split_are_portal_only(self, client):
        respx.get(f"{_BASE}/usage/contractInfo").mock(
            return_value=httpx.Response(200, json=_hybrid_contract())
        )
        route = respx.get(f"{_BASE}/usage/focusCostUsage").mock(side_effect=_tenant_feed)
        data = json.loads(
            (
                await get_usage_by_tenant(
                    client, features=["ADR"], tenant_ids=["tenant-x"], days=4, month_to_date=False
                )
            )[0].text
        )
        assert "not supported" in data["features"][0]["tenant_split"]
        assert "tenants" not in data["features"][0]
        assert all(not c.request.url.params.get_list("tenantIds") for c in route.calls)

    @respx.mock
    async def test_portal_with_no_tenants_says_so(self, client):
        respx.get(f"{_BASE}/usage/contractInfo").mock(
            return_value=httpx.Response(200, json=_hybrid_contract())
        )
        respx.get(f"{_BASE}/device/groups").mock(
            return_value=httpx.Response(200, json=_groups(False))
        )
        respx.get(f"{_BASE}/device/devices").mock(
            return_value=httpx.Response(200, json={"items": [{"id": 1}], "total": 1})
        )
        respx.get(f"{_BASE}/usage/focusCostUsage").mock(side_effect=_tenant_feed)
        data = json.loads(
            (
                await get_usage_by_tenant(
                    client, features=["HYBRID_UNITS"], days=4, month_to_date=False
                )
            )[0].text
        )
        assert data["tenant_count"] == 0
        assert "no resource carries" in data["features"][0]["tenant_split"]
        assert data["features"][0]["portal_total"] == 100.0


class TestBasisWithDuplicateNames:
    def test_parent_and_same_named_carveout(self):
        """A contract naming STANDARD_RESOURCES twice: the billable parent and its own
        carve-out child. The child must not hide the parent's basis."""
        contract = {
            "childProducts": [
                {
                    "feature": "STANDARD_RESOURCES",
                    "quantity": [28700],
                    "aggregationType": "RAVG",
                    "childProducts": [
                        {"feature": "LITE_RESOURCES", "quantity": [1700], "aggregationType": None},
                        {
                            "feature": "STANDARD_RESOURCES",
                            "quantity": [27000],
                            "aggregationType": None,
                        },
                    ],
                }
            ]
        }
        projected = [_project_feature(e) for e in _walk_contract(contract, [])]
        assert _basis_for("STANDARD_RESOURCES", projected) == "RAVG"
        assert _basis_for("LITE_RESOURCES", projected) == "RAVG"


class TestDiscoveryCache:
    @respx.mock
    async def test_second_call_is_served_from_cache(self, client):
        from lm_mcp.tools import usage as mod

        mod._DISCOVERY_CACHE.clear()
        respx.get(f"{_BASE}/device/groups").mock(
            return_value=httpx.Response(200, json=_groups(False))
        )
        devices = respx.get(f"{_BASE}/device/devices").mock(
            return_value=httpx.Response(200, json=_devices())
        )
        first = await _discover_tenants(client, "system.tenant.identifier")
        second = await _discover_tenants(client, "system.tenant.identifier")
        assert devices.call_count == 1
        assert second["cached"] is True
        assert second["tenant_ids"] == first["tenant_ids"]
        mod._DISCOVERY_CACHE.clear()

    @respx.mock
    async def test_pages_after_the_first_are_all_fetched(self, client):
        from lm_mcp.tools import usage as mod

        mod._DISCOVERY_CACHE.clear()
        total = 2500

        def page(request):
            off = int(request.url.params["offset"])
            n = min(1000, total - off)
            items = [
                {
                    "id": off + i,
                    "customProperties": [
                        {"name": "system.tenant.identifier", "value": f"tenant-{(off + i) % 7}"}
                    ],
                }
                for i in range(n)
            ]
            return httpx.Response(200, json={"items": items, "total": total})

        respx.get(f"{_BASE}/device/groups").mock(
            return_value=httpx.Response(200, json=_groups(False))
        )
        route = respx.get(f"{_BASE}/device/devices").mock(side_effect=page)
        found = await _discover_tenants(client, "system.tenant.identifier")
        assert route.call_count == 3
        assert len(found["tenant_ids"]) == 7
        assert found["untenanted_resources"] == 0
        mod._DISCOVERY_CACHE.clear()


class TestRemainderAndCallCount:
    def _mock(self):
        respx.get(f"{_BASE}/usage/contractInfo").mock(
            return_value=httpx.Response(200, json=_hybrid_contract())
        )
        respx.get(f"{_BASE}/device/groups").mock(
            return_value=httpx.Response(200, json=_groups(True))
        )
        return respx.get(f"{_BASE}/usage/focusCostUsage").mock(side_effect=_tenant_feed)

    @respx.mock
    async def test_discovered_tenants_leave_an_untenanted_remainder(self, client):
        self._mock()
        data = json.loads(
            (
                await get_usage_by_tenant(
                    client, features=["HYBRID_UNITS"], days=4, month_to_date=False
                )
            )[0].text
        )
        line = data["features"][0]
        assert line["untenanted"] == 15.0
        assert "not_in_requested_tenants" not in line

    @respx.mock
    async def test_api_calls_include_contract_and_discovery(self, client):
        usage_route = self._mock()
        data = json.loads(
            (
                await get_usage_by_tenant(
                    client, features=["HYBRID_UNITS"], days=4, month_to_date=False
                )
            )[0].text
        )
        assert data["discovery_api_calls"] == 1  # one page of groups
        assert data["discovery_cached"] is False
        assert data["api_calls"] == 1 + 1 + usage_route.call_count

    @respx.mock
    async def test_cached_discovery_costs_nothing(self, client):
        self._mock()
        await get_usage_by_tenant(client, features=["HYBRID_UNITS"], days=4, month_to_date=False)
        data = json.loads(
            (
                await get_usage_by_tenant(
                    client, features=["HYBRID_UNITS"], days=4, month_to_date=False
                )
            )[0].text
        )
        assert data["discovery_cached"] is True
        assert data["discovery_api_calls"] == 0
