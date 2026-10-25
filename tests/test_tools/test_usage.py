# Description: Tests for the usage contract and usage metrics MCP tools.
# Description: Synthetic contracts in the live shape: list quantities and list units.

import json
import logging

import httpx
import pytest
import respx

from lm_mcp.auth.bearer import BearerAuth
from lm_mcp.client import LogicMonitorClient
from lm_mcp.tools import is_error_result
from lm_mcp.tools.usage import (
    _as_quantity,
    _first,
    _headline_entitlement,
    _pair_units,
    _project_feature,
    _walk_contract,
    get_usage_contract,
    get_usage_metrics,
)

BASE = "https://test.logicmonitor.com/santaba/rest"
CONTRACT_URL = f"{BASE}/usage/contractInfo"
METRICS_URL = f"{BASE}/metrics/usage"

# /metrics/usage answers with a flat object of counts; these values are invented.
COUNTS = {
    "numberOfDevices": 120,
    "numberOfStandardDevices": 80,
    "numberOfKubernetesDevices": 3,
    "numOfAWSDevices": 0,
    "numOfWebsites": 0,
    "numOfServices": 7,
}


@pytest.fixture
def client():
    return LogicMonitorClient(
        base_url=BASE, auth=BearerAuth("test-token"), timeout=30, api_version=3
    )


def node(feature, quantity, unit, aggregation="RAVG", **extra):
    """A contract node as the live API returns it: quantity and unit are lists."""
    return {
        "feature": feature,
        "quantity": quantity,
        "unit": unit,
        "aggregationType": aggregation,
        **extra,
    }


def _hybrid_contract() -> dict:
    """Synthetic hybrid contract: a parent with vendor children that repeat its cap,
    a carve-out, a feature with no entitlement and an unpaid one."""
    return {
        "product": "PLATFORM",
        "childProducts": [
            node("HYBRID_UNITS", [1200], ["Units"], subscriptions=[{"sku": "SKU-HYB"}]),
            node("LOGS", [750.5], ["GB"], "SUM", subscriptions=[{"sku": "SKU-LOG"}]),
            node(
                "WIRELESS_ACCESS_POINTS",
                [400],
                ["Resources"],
                childProducts=[
                    node("VENDOR_A_AP", [400], ["Resources"], None),
                    node("VENDOR_B_AP", [400], ["Resources"], None),
                ],
            ),
            node(
                "STANDARD_RESOURCES",
                [5000],
                ["Resources"],
                nestedProducts=[node("LITE_RESOURCES", [600], ["Resources"], None)],
            ),
            node("SAAS", [0], ["Users"]),
            node("DYNAMIC_SERVICE_INSIGHTS", [12], ["Services"], unpaid=True),
            node("COMBINEDMETRICS", [0], [], None),
        ],
    }


def _saas_contract() -> dict:
    """SAAS entitled in two units at once, restated per product."""
    products = ("SAAS_OFFICE365", "SAAS_SALESFORCE", "SAAS_SLACK", "SAAS_WEBEX", "SAAS_ZOOM")
    return {
        "childProducts": [
            node(
                "SAAS",
                [1500, 0],
                ["User", "Services"],
                childProducts=[node(p, [1500, 0], ["User", "Services"]) for p in products],
            ),
        ]
    }


def _projected(contract: dict) -> dict:
    entries = _walk_contract(contract, [])
    return {(e["feature"], e["parent"]): _project_feature(e) for e in entries}


def _by_feature(data: dict) -> dict:
    return {f["feature"]: f for f in data["features"]}


def assert_error(result, message: str, suggestion: str):
    """A refusal is an ErrorContent carrying the server's words and a suggestion."""
    assert is_error_result(result)
    text = result[0].text
    assert text.startswith("Error: ")
    assert message in text
    assert f"Suggestion: {suggestion}" in text


class TestContractWalk:
    def test_vendor_children_never_become_entitlements(self):
        p = _projected(_hybrid_contract())
        assert p[("WIRELESS_ACCESS_POINTS", None)]["entitled"] == 400.0
        # Counted as lines, children repeating the cap would multiply it.
        assert p[("VENDOR_A_AP", "WIRELESS_ACCESS_POINTS")]["role"] == "rollup_or_carveout"
        assert p[("VENDOR_B_AP", "WIRELESS_ACCESS_POINTS")]["role"] == "rollup_or_carveout"

    def test_a_node_under_a_carve_out_keeps_the_metered_ancestor(self):
        # A carve-out (null aggregationType) never becomes a parent: what sits under it
        # still belongs to the metered line, and is compared with that line's pool.
        contract = {
            "childProducts": [
                node(
                    "DEVICES",
                    [500],
                    ["Resources"],
                    childProducts=[
                        node(
                            "STANDARD_RESOURCES",
                            [300],
                            ["Resources"],
                            None,
                            childProducts=[node("STANDARD_SUB", [500], ["Resources"])],
                        )
                    ],
                )
            ]
        }
        p = _projected(contract)
        sub = p[("STANDARD_SUB", "DEVICES")]
        assert sub["role"] == "repeats_parent"

    def test_nested_products_are_walked_with_their_parent(self):
        p = _projected(_hybrid_contract())
        assert ("LITE_RESOURCES", "STANDARD_RESOURCES") in p
        assert p[("HYBRID_UNITS", None)]["parent"] is None

    def test_roles(self):
        p = _projected(_hybrid_contract())
        assert p[("HYBRID_UNITS", None)]["role"] == "billable_line"
        assert p[("SAAS", None)]["role"] == "metered_no_entitlement"
        assert p[("DYNAMIC_SERVICE_INSIGHTS", None)]["role"] == "metered_unpaid"
        assert p[("LITE_RESOURCES", "STANDARD_RESOURCES")]["role"] == "rollup_or_carveout"

    def test_sku_unit_and_basis_are_kept(self):
        logs = _projected(_hybrid_contract())[("LOGS", None)]
        assert logs["sku"] == "SKU-LOG"
        assert logs["unit"] == "GB"
        assert logs["aggregation_type"] == "SUM"
        assert logs["basis"] == "total across the period"

    def test_a_wrapped_quantity_is_the_normal_shape(self):
        hybrid = _projected(_hybrid_contract())[("HYBRID_UNITS", None)]
        assert hybrid["entitled"] == 1200.0
        assert "entitled_raw" not in hybrid

    def test_malformed_nodes_do_not_raise(self):
        assert _walk_contract(None, []) == []
        assert _walk_contract("string", []) == []
        assert _walk_contract({"childProducts": [None, 7]}, []) == []


class TestQuantityCoercion:
    def test_one_element_lists_are_not_reinterpretations(self):
        assert _as_quantity([1200]) == (1200.0, None)
        assert _as_quantity([750.5]) == (750.5, None)

    def test_scalars_and_strings(self):
        assert _as_quantity(1200) == (1200.0, None)
        assert _as_quantity(None) == (0.0, None)
        assert _as_quantity(" 600 ") == (600.0, None)
        assert _as_quantity("n/a") == (0.0, "n/a")

    def test_multi_element_list_collapses_to_max_and_keeps_raw(self):
        assert _as_quantity([100, 1200, 50]) == (1200.0, [100, 1200, 50])

    def test_empty_nested_and_dict_shapes(self):
        assert _as_quantity([]) == (0.0, None)
        assert _as_quantity([[5], [9]])[0] == 9.0
        assert _as_quantity({"quantity": [42]}) == (42.0, {"quantity": [42]})
        assert _as_quantity({"other": 1}) == (0.0, {"other": 1})

    def test_bool_is_not_a_quantity(self):
        # bool subclasses int; True must not read as an entitlement of 1.
        assert _as_quantity(True) == (0.0, True)

    def test_an_unpaired_multi_value_quantity_is_surfaced(self):
        projected = _project_feature(
            {"feature": "X", "node": node("X", [1000, 2000], ["Units"]), "parent": None}
        )
        assert projected["entitled"] == 2000.0
        assert projected["entitled_raw"] == [1000, 2000]


class TestUnits:
    def test_unit_lists_are_unwrapped(self):
        assert _first(["Resources"]) == "Resources"
        assert _first("Resources") == "Resources"
        assert _first(["A", "B"]) == ["A", "B"]

    def test_an_empty_unit_list_is_no_unit(self):
        assert _first([]) is None
        combined = _projected(_hybrid_contract())[("COMBINEDMETRICS", None)]
        assert combined["unit"] is None

    def test_pairs_quantity_with_unit(self):
        assert _pair_units([1500, 0], ["User", "Services"]) == {"User": 1500.0, "Services": 0.0}

    def test_pairing_needs_two_parallel_lists(self):
        assert _pair_units([1, 2], ["a"]) is None
        assert _pair_units([5], ["Resources"]) is None
        assert _pair_units(5, "Resources") is None

    def test_opposite_orders_both_resolve_correctly(self):
        qty_a, unit_a, amb_a = _headline_entitlement(
            _pair_units([1500, 0], ["User", "Services"]), 0
        )
        qty_b, unit_b, amb_b = _headline_entitlement(_pair_units([3, 0], ["Services", "User"]), 0)
        assert (qty_a, unit_a, amb_a) == (1500.0, "User", False)
        assert (qty_b, unit_b, amb_b) == (3.0, "Services", False)

    def test_two_non_zero_units_are_flagged_not_guessed(self):
        assert _headline_entitlement({"User": 250.0, "Services": 40.0}, 0.0) == (
            250.0,
            "User",
            True,
        )

    def test_all_zero_is_zero_and_no_fallback_is_unchanged(self):
        assert _headline_entitlement({"User": 0.0, "Services": 0.0}, 9.0) == (0.0, None, False)
        assert _headline_entitlement(None, 77.0) == (77.0, None, False)

    def test_a_list_its_units_pair_is_not_a_reinterpretation(self):
        saas = _projected(_saas_contract())[("SAAS", None)]
        assert saas["entitled"] == 1500.0
        assert saas["unit"] == "User"
        assert saas["entitled_by_unit"] == {"User": 1500.0, "Services": 0.0}
        assert "entitled_raw" not in saas
        zero = _project_feature(
            {"feature": "S", "node": node("S", [0, 0], ["Services", "User"]), "parent": None}
        )
        assert "entitled_raw" not in zero

    def test_a_paired_list_holding_junk_still_shows_the_raw_value(self):
        projected = _project_feature(
            {"feature": "S", "node": node("S", ["n/a", 5], ["User", "Services"]), "parent": None}
        )
        assert projected["entitled_by_unit"] == {"User": 0.0, "Services": 5.0}
        assert projected["entitled_raw"] == ["n/a", 5]

    def test_ambiguous_entitlement_names_the_unit_it_reported(self):
        projected = _project_feature(
            {"feature": "S", "node": node("S", [250, 40], ["User", "Services"]), "parent": None}
        )
        assert (projected["entitled"], projected["unit"]) == (250.0, "User")
        assert projected["entitled_ambiguous"] is True


class TestRepeatedParentQuantity:
    def test_per_product_children_are_marked_as_repeats(self):
        p = _projected(_saas_contract())
        assert p[("SAAS", None)]["role"] == "billable_line"
        for name in ("SAAS_OFFICE365", "SAAS_SALESFORCE", "SAAS_SLACK", "SAAS_WEBEX", "SAAS_ZOOM"):
            assert p[(name, "SAAS")]["role"] == "repeats_parent", name

    def test_entitlement_is_not_multiplied_by_the_children(self):
        billable = [
            v for v in _projected(_saas_contract()).values() if v["role"] == "billable_line"
        ]
        assert sum(v["entitled"] for v in billable) == 1500.0

    def test_a_carve_out_subdivides_and_is_not_a_repeat(self):
        lite = _projected(_hybrid_contract())[("LITE_RESOURCES", "STANDARD_RESOURCES")]
        assert lite["role"] == "rollup_or_carveout"
        assert lite["entitled"] == 600.0

    def test_a_zero_child_under_a_zero_parent_is_not_a_repeat(self):
        contract = {
            "childProducts": [node("P", [0], ["Units"], childProducts=[node("C", [0], ["Units"])])]
        }
        assert _projected(contract)[("C", "P")]["role"] == "metered_no_entitlement"


class TestGetUsageContract:
    @respx.mock
    async def test_detects_hybrid_and_keeps_unentitled_rows(self, client):
        route = respx.get(CONTRACT_URL).mock(
            return_value=httpx.Response(200, json=_hybrid_contract())
        )
        data = json.loads((await get_usage_contract(client))[0].text)

        assert route.call_count == 1
        assert data["billing_mode"] == "hybrid"
        assert data["count"] == len(data["features"]) == 10
        names = set(_by_feature(data))
        # The whole point: features with no entitlement are still reported.
        assert {"SAAS", "LITE_RESOURCES", "DYNAMIC_SERVICE_INSIGHTS"} <= names
        assert "unreadable_nodes" not in data
        assert "warnings" not in data

    @respx.mock
    async def test_unit_and_ambiguity_reach_the_output(self, client):
        contract = {"childProducts": [node("SAAS", [250, 40], ["User", "Services"])]}
        respx.get(CONTRACT_URL).mock(return_value=httpx.Response(200, json=contract))
        saas = _by_feature(json.loads((await get_usage_contract(client))[0].text))["SAAS"]
        assert saas["unit"] == "User"
        assert saas["entitled_ambiguous"] is True
        assert saas["entitled_by_unit"] == {"User": 250.0, "Services": 40.0}

    @respx.mock
    async def test_detects_legacy_and_indeterminate(self, client):
        legacy = {"childProducts": [node("STANDARD_RESOURCES", [900], ["Resources"])]}
        respx.get(CONTRACT_URL).mock(return_value=httpx.Response(200, json=legacy))
        assert json.loads((await get_usage_contract(client))[0].text)["billing_mode"] == "legacy"

        # STANDARD_RESOURCES as a carve-out, and CLOUD_PAAS unpaid, are not billable.
        unpaid = {
            "childProducts": [
                node(
                    "DEVICES",
                    [0],
                    ["Resources"],
                    unpaid=True,
                    childProducts=[node("STANDARD_RESOURCES", [0], ["Resources"], None)],
                ),
                node("CLOUD_PAAS", [60], ["Resources"], unpaid=True),
            ]
        }
        respx.get(CONTRACT_URL).mock(return_value=httpx.Response(200, json=unpaid))
        data = json.loads((await get_usage_contract(client))[0].text)
        assert data["billing_mode"] == "indeterminate"

    @respx.mock
    async def test_billable_only_filters_without_changing_the_billing_mode(self, client):
        respx.get(CONTRACT_URL).mock(return_value=httpx.Response(200, json=_hybrid_contract()))
        data = json.loads((await get_usage_contract(client, billable_only=True))[0].text)
        assert {f["role"] for f in data["features"]} == {"billable_line"}
        assert set(_by_feature(data)) == {
            "HYBRID_UNITS",
            "LOGS",
            "WIRELESS_ACCESS_POINTS",
            "STANDARD_RESOURCES",
        }
        assert data["count"] == 4
        assert data["billing_mode"] == "hybrid"

    @respx.mock
    async def test_billable_only_keeps_a_billable_child_line(self, client):
        contract = {
            "childProducts": [
                node(
                    "CLOUD_IAAS",
                    [400],
                    ["Resources"],
                    childProducts=[node("CLOUD_NONCOMPUTE", [90], ["Resources"])],
                )
            ]
        }
        respx.get(CONTRACT_URL).mock(return_value=httpx.Response(200, json=contract))
        data = json.loads((await get_usage_contract(client, billable_only=True))[0].text)
        lines = {(f["feature"], f["parent"]) for f in data["features"]}
        assert lines == {("CLOUD_IAAS", None), ("CLOUD_NONCOMPUTE", "CLOUD_IAAS")}
        assert data["billing_mode"] == "legacy"

    @respx.mock
    async def test_billable_only_excludes_repeats(self, client):
        respx.get(CONTRACT_URL).mock(return_value=httpx.Response(200, json=_saas_contract()))
        data = json.loads((await get_usage_contract(client, billable_only=True))[0].text)
        assert set(_by_feature(data)) == {"SAAS"}

    @respx.mock
    async def test_features_are_sorted_by_parent_then_name(self, client):
        respx.get(CONTRACT_URL).mock(return_value=httpx.Response(200, json=_hybrid_contract()))
        data = json.loads((await get_usage_contract(client))[0].text)
        keys = [(f["parent"] or "", f["feature"]) for f in data["features"]]
        assert keys == sorted(keys)

    @respx.mock
    async def test_an_unreadable_node_costs_one_line_and_is_logged(self, client, caplog):
        payload = {
            "childProducts": [
                node("OK", [1], ["Units"]),
                # subscriptions must be a list; an int cannot be iterated.
                node("ODD", [1], ["Units"], subscriptions=7),
            ]
        }
        respx.get(CONTRACT_URL).mock(return_value=httpx.Response(200, json=payload))
        with caplog.at_level(logging.WARNING, logger="lm_mcp.tools.usage"):
            result = await get_usage_contract(client)

        assert not is_error_result(result)
        data = json.loads(result[0].text)
        assert set(_by_feature(data)) == {"OK"}
        assert data["count"] == 1
        assert data["unreadable_nodes"] == [
            {"feature": "ODD", "reason": "TypeError: 'int' object is not iterable"}
        ]
        records = [r for r in caplog.records if r.name == "lm_mcp.tools.usage"]
        assert len(records) == 1
        assert records[0].levelno == logging.WARNING
        assert "'ODD'" in records[0].getMessage()
        assert records[0].exc_info and records[0].exc_info[0] is TypeError  # traceback kept

    @pytest.mark.parametrize(
        "body",
        [{}, [], {"data": {"childProducts": []}}, {"items": [{"name": "X"}]}],
        ids=["empty-object", "empty-list", "wrapped", "unknown-shape"],
    )
    @respx.mock
    async def test_no_features_is_not_an_empty_contract(self, client, caplog, body):
        respx.get(CONTRACT_URL).mock(return_value=httpx.Response(200, json=body))
        with caplog.at_level(logging.WARNING, logger="lm_mcp.tools.usage"):
            result = await get_usage_contract(client)

        assert not is_error_result(result)
        data = json.loads(result[0].text)
        assert data["count"] == 0
        assert len(data["warnings"]) == 1
        assert "This is not an empty contract" in data["warnings"][0]
        records = [r for r in caplog.records if r.name == "lm_mcp.tools.usage"]
        assert [r.levelno for r in records] == [logging.WARNING]
        assert "no features in the response" in records[0].getMessage()

    @respx.mock
    async def test_no_readable_feature_is_flagged(self, client):
        payload = {"childProducts": [node("ODD", [1], ["Units"], subscriptions=7)]}
        respx.get(CONTRACT_URL).mock(return_value=httpx.Response(200, json=payload))
        data = json.loads((await get_usage_contract(client))[0].text)
        assert data["count"] == 0
        assert [n["feature"] for n in data["unreadable_nodes"]] == ["ODD"]
        assert data["warnings"] == [
            "No contract feature could be read (see unreadable_nodes), so no "
            "entitlement can be concluded from this response."
        ]

    @respx.mock
    async def test_no_billable_line_is_an_answer_not_a_warning(self, client):
        unpaid = {"childProducts": [node("DEVICES", [0], ["Resources"], unpaid=True)]}
        respx.get(CONTRACT_URL).mock(return_value=httpx.Response(200, json=unpaid))
        data = json.loads((await get_usage_contract(client, billable_only=True))[0].text)
        assert data["count"] == 0
        assert "warnings" not in data

    @respx.mock
    async def test_403_is_an_error_with_the_servers_words(self, client, caplog):
        respx.get(CONTRACT_URL).mock(
            return_value=httpx.Response(403, json={"errorMessage": "Permission denied"})
        )
        with caplog.at_level(logging.WARNING):
            result = await get_usage_contract(client)
        assert_error(
            result,
            "Permission denied",
            "Your API token may lack required permissions. Contact your LM admin.",
        )
        assert any("PERMISSION_DENIED" in r.getMessage() for r in caplog.records)

    @respx.mock
    async def test_404_is_an_error_naming_the_endpoint(self, client, caplog):
        respx.get(CONTRACT_URL).mock(
            return_value=httpx.Response(404, json={"errorMessage": "Not found"})
        )
        with caplog.at_level(logging.WARNING):
            result = await get_usage_contract(client)
        assert_error(
            result,
            "Not found",
            "The portal answered not found for /usage/contractInfo; it may not offer this "
            "endpoint on this account or API version.",
        )
        assert any("NOT_FOUND" in r.getMessage() for r in caplog.records)
        assert "Verify the ID" not in result[0].text


class TestGetUsageMetrics:
    @respx.mock
    async def test_returns_the_counts_with_a_note(self, client):
        route = respx.get(METRICS_URL).mock(return_value=httpx.Response(200, json=COUNTS))
        result = await get_usage_metrics(client)

        assert route.call_count == 1
        assert not is_error_result(result)
        data = json.loads(result[0].text)
        assert data["metrics"] == COUNTS
        assert "not billing figures" in data["note"]
        assert "warnings" not in data

    @pytest.mark.parametrize(
        "body", [{}, [], [{"numberOfDevices": 3}]], ids=["empty-object", "empty-list", "list"]
    )
    @respx.mock
    async def test_no_counts_is_flagged(self, client, caplog, body):
        respx.get(METRICS_URL).mock(return_value=httpx.Response(200, json=body))
        with caplog.at_level(logging.WARNING, logger="lm_mcp.tools.usage"):
            result = await get_usage_metrics(client)

        assert not is_error_result(result)
        data = json.loads(result[0].text)
        assert data["metrics"] == body
        assert data["warnings"] == [
            "The /metrics/usage response held no counts (it was empty or not an "
            "object), so it says nothing about the portal's usage."
        ]
        records = [r for r in caplog.records if r.name == "lm_mcp.tools.usage"]
        assert [r.levelno for r in records] == [logging.WARNING]

    @respx.mock
    async def test_all_zero_counts_are_an_answer(self, client):
        zeros = dict.fromkeys(COUNTS, 0)
        respx.get(METRICS_URL).mock(return_value=httpx.Response(200, json=zeros))
        data = json.loads((await get_usage_metrics(client))[0].text)
        assert data["metrics"] == zeros
        assert "warnings" not in data

    @respx.mock
    async def test_zero_counts_are_kept(self, client):
        respx.get(METRICS_URL).mock(return_value=httpx.Response(200, json=COUNTS))
        data = json.loads((await get_usage_metrics(client))[0].text)
        assert data["metrics"]["numOfAWSDevices"] == 0

    @respx.mock
    async def test_403_is_an_error_with_the_servers_words(self, client):
        respx.get(METRICS_URL).mock(
            return_value=httpx.Response(403, json={"errorMessage": "Permission denied"})
        )
        assert_error(
            await get_usage_metrics(client),
            "Permission denied",
            "Your API token may lack required permissions. Contact your LM admin.",
        )

    @respx.mock
    async def test_404_is_an_error_naming_the_endpoint(self, client):
        respx.get(METRICS_URL).mock(
            return_value=httpx.Response(404, json={"errorMessage": "Not found"})
        )
        assert_error(
            await get_usage_metrics(client),
            "Not found",
            "The portal answered not found for /metrics/usage; it may not offer this "
            "endpoint on this account or API version.",
        )
