# Description: Tests for the assess_collector_health tool and its pure classifier.
# Description: Synthetic collectors and devices only; no portal data.

import json
from collections import Counter

import httpx
import pytest
import respx

from lm_mcp.auth.bearer import BearerAuth
from lm_mcp.client import LogicMonitorClient
from lm_mcp.tools import collector_debug as cd
from lm_mcp.tools.collector_assessment import (
    NOT_A_RESOURCE,
    assess_collector_health,
    classify_collector,
    own_resource_status,
)

BASE = "https://test.logicmonitor.com/santaba/rest"
NOW = 1_800_000_000


@pytest.fixture
def client():
    return LogicMonitorClient(
        base_url=BASE, auth=BearerAuth("test-token"), timeout=30, api_version=3
    )


def row(cid, **kw):
    """A synthetic collector list row: live watchdog, monitored as a resource, 100 hosts."""
    base = {
        "id": cid,
        "hostname": f"collector-example-{cid}",
        "collectorGroupName": "SiteA",
        "platform": "linux",
        "build": "39200",
        "numberOfHosts": 100,
        "createdOn": NOW - 90 * 86400,
        "watchdogUpdatedOn": NOW - 30,
        "updatedOn": NOW - 10,
        "upTime": 3600,
        "collectorDeviceId": 9000 + cid,
        "backupAgentId": 0,
        "hasFailOverDevice": False,
    }
    base.update(kw)
    return base


def classify(r, **kw):
    args = {
        "now": NOW,
        "down_ids": set(),
        "own_resource": "not dead",
        "dead": Counter(),
        "dead_collector": Counter(),
        "self_alerts": [],
    }
    args.update(kw)
    return classify_collector(r, **args)


class TestClassifier:
    def test_healthy_when_every_signal_is_read_and_clean(self):
        out = classify(row(1))
        assert out["state"] == "healthy"
        assert out["unknowns"] == []
        assert out["failover"] == "none configured"

    def test_down_from_the_down_set(self):
        out = classify(row(1), down_ids={1}, dead_collector=Counter({1: 80}))
        assert out["state"] == "down"
        assert any("filter=isDown:true" in e for e in out["evidence"])
        assert any("80 device(s) at hostStatus dead-collector" in e for e in out["evidence"])

    def test_down_from_the_collectors_own_resource(self):
        out = classify(row(1), own_resource="dead")
        assert out["state"] == "down"
        assert any("own resource is at hostStatus dead" in e for e in out["evidence"])

    def test_watchdog_never_reported_is_silent_even_with_fresh_updated_on(self):
        r = row(1, watchdogUpdatedOn=NOW - 90 * 86400, updatedOn=NOW - 12)
        out = classify(r)
        assert out["state"] == "silent_reported_up"
        assert any("never reported" in e for e in out["evidence"])

    def test_stale_watchdog_is_silent(self):
        out = classify(row(1, watchdogUpdatedOn=NOW - 7200))
        assert out["state"] == "silent_reported_up"

    def test_down_outranks_silent(self):
        out = classify(row(1, watchdogUpdatedOn=NOW - 7200), down_ids={1})
        assert out["state"] == "down"

    def test_live_collector_with_dark_devices_is_a_path_fault(self):
        out = classify(row(1), dead=Counter({1: 88}))
        assert out["state"] == "up_devices_unreachable"
        assert any("88 of 100 devices" in e for e in out["evidence"])

    def test_silent_outranks_dark_devices(self):
        out = classify(row(1, watchdogUpdatedOn=NOW - 7200), dead=Counter({1: 95}))
        assert out["state"] == "silent_reported_up"

    def test_min_dark_guards_tiny_collectors(self):
        out = classify(row(1, numberOfHosts=2), dead=Counter({1: 2}))
        assert out["state"] == "healthy"
        assert any("below the dark_share rule" in e for e in out["evidence"])

    def test_partial_dark_is_evidence_not_a_state(self):
        out = classify(row(1), dead=Counter({1: 30}))
        assert out["state"] == "healthy"
        assert any("30 device(s) at hostStatus dead (30%)" in e for e in out["evidence"])

    def test_thresholds_are_parameters(self):
        out = classify(row(1), dead=Counter({1: 30}), dark_share=0.25)
        assert out["state"] == "up_devices_unreachable"

    def test_self_monitoring_alerts_are_losing_work(self):
        alert = {
            "resourceTemplateName": "LogicMonitor_Collector_DataCollectingTasks",
            "dataPointName": "UnavailableScheduleTaskRate",
            "alertValue": 7,
            "severity": 3,
        }
        out = classify(row(1), self_alerts=[alert])
        assert out["state"] == "up_losing_work"
        assert any("UnavailableScheduleTaskRate" in e for e in out["evidence"])

    def test_missing_watchdog_is_unknown_never_healthy(self):
        r = row(1)
        del r["watchdogUpdatedOn"]
        out = classify(r)
        assert out["state"] == "unknown"
        assert any("watchdogUpdatedOn absent" in u for u in out["unknowns"])

    def test_unreadable_down_set_is_unknown_never_healthy(self):
        out = classify(row(1), down_ids=None)
        assert out["state"] == "unknown"

    def test_unreadable_device_status_is_unknown(self):
        out = classify(row(1), dead=None, dead_collector=None)
        assert out["state"] == "unknown"

    def test_not_a_resource_is_called_out_but_does_not_block_healthy(self):
        out = classify(row(1, collectorDeviceId=0), own_resource=NOT_A_RESOURCE)
        assert out["state"] == "healthy"
        assert out["monitored_as_resource"] is False
        assert any("not monitored as a resource" in u for u in out["unknowns"])

    def test_own_resource_status_from_dead_sets(self):
        assert own_resource_status(row(1), {9001}, set()) == "dead"
        assert own_resource_status(row(1), set(), {9001}) == "dead-collector"
        assert own_resource_status(row(1), set(), set()) == "not dead"
        assert own_resource_status(row(1), None, None) is None
        assert own_resource_status(row(1, collectorDeviceId=0), set(), set()) == NOT_A_RESOURCE
        assert own_resource_status(row(1, collectorDeviceId=None), set(), set()) == NOT_A_RESOURCE


def portal(
    fleet,
    dead=(),
    dead_collector=(),
    down=(),
    self_alerts=(),
    fail=(),
    devices=None,
    or_filter=True,
    debug=None,
):
    """Mount a synthetic portal on respx. Returns the list of requests seen."""
    seen = []
    devices = devices or {}

    def handler(request: httpx.Request):
        url = request.url
        path = url.path.replace("/santaba/rest", "")
        params = dict(url.params)
        flt = params.get("filter", "")
        seen.append((request.method, path, flt))
        offset = int(params.get("offset", "0"))
        if any(f in path + flt for f in fail):
            return httpx.Response(500, json={"errorMessage": "synthetic failure"})
        if request.method == "POST" and path == "/debug":
            cid = int(params["collectorId"])
            if debug and debug.get(cid) == "refuse":
                return httpx.Response(403, json={"errorMessage": "no debug right"})
            return httpx.Response(200, json={"sessionId": f"s{cid}"})
        if path.startswith("/debug/"):
            cid = int(path.split("/s")[-1])
            mode = (debug or {}).get(cid, "ok")
            if mode == "slow":
                return httpx.Response(200, json={"output": "pending"})
            if "collectorId" in params:
                return httpx.Response(200, json={"output": "cancelled"})
            return httpx.Response(200, json={"output": f"health check for {cid}\nline 2"})
        if offset:
            return httpx.Response(200, json={"items": []})
        if path == "/setting/collector/collectors":
            if flt == "isDown:true":
                return httpx.Response(200, json={"items": [{"id": i} for i in down]})
            return httpx.Response(200, json={"items": fleet})
        if path == "/device/devices":
            if flt == 'hostStatus:"dead"':
                return httpx.Response(200, json={"items": list(dead)})
            if flt == 'hostStatus:"dead-collector"':
                return httpx.Response(200, json={"items": list(dead_collector)})
            if flt.startswith("id:"):
                if not or_filter:
                    return httpx.Response(200, json={"items": []})
                ids = [int(x) for x in flt[3:].split("|")]
                return httpx.Response(
                    200,
                    json={
                        "items": [
                            {"id": i, "currentCollectorId": devices[i]} for i in ids if i in devices
                        ]
                    },
                )
        if path.startswith("/device/devices/"):
            did = int(path.rsplit("/", 1)[-1])
            if did in devices:
                return httpx.Response(200, json={"id": did, "currentCollectorId": devices[did]})
            return httpx.Response(404, json={"errorMessage": "not found"})
        if path == "/alert/alerts":
            return httpx.Response(200, json={"items": list(self_alerts)})
        return httpx.Response(404, json={"errorMessage": f"unmocked {path}"})

    respx.route(host="test.logicmonitor.com").mock(side_effect=handler)
    return seen


def now_rows():
    import time

    t = time.time()
    fleet = [
        row(1, watchdogUpdatedOn=t - 20, createdOn=t - 9e6),  # healthy
        row(2, watchdogUpdatedOn=t - 20, createdOn=t - 9e6),  # down
        row(3, watchdogUpdatedOn=t - 9e6, createdOn=t - 9e6),  # silent: never reported
        row(4, watchdogUpdatedOn=t - 20, createdOn=t - 9e6),  # devices dark
        row(5, watchdogUpdatedOn=t - 20, createdOn=t - 9e6, collectorDeviceId=0),  # not a resource
    ]
    dead = [{"id": 100 + i, "currentCollectorId": 4} for i in range(90)]
    dead_collector = [{"id": 500 + i, "currentCollectorId": 2} for i in range(60)]
    return fleet, dead, dead_collector


class TestAssessFleet:
    @respx.mock
    async def test_fleet_states_calls_and_callouts(self, client):
        fleet, dead, dc = now_rows()
        seen = portal(fleet, dead=dead, dead_collector=dc, down=[2])
        data = json.loads((await assess_collector_health(client))[0].text)
        states = {c["collector_id"]: c["state"] for c in data["collectors"]}
        assert states == {2: "down", 3: "silent_reported_up", 4: "up_devices_unreachable"}
        assert data["state_counts"]["healthy"] == 2
        assert data["healthy_collectors_omitted"] == 2
        assert data["collectors_not_monitored_as_resource"] == [
            {"collector_id": 5, "hostname": "collector-example-5"}
        ]
        assert data["assumptions"] and data["signals_unavailable"] == []
        assert data["api_calls"] == 5
        assert isinstance(data["elapsed_ms"], int)
        assert data["tier2"] == "not requested"
        # Collector-down alerts are not in /alert/alerts, so they are never asked for there.
        assert not any("CollectorDown" in f for _, _, f in seen)

    @respx.mock
    async def test_include_healthy_lists_everyone(self, client):
        fleet, dead, dc = now_rows()
        portal(fleet, dead=dead, dead_collector=dc, down=[2])
        data = json.loads((await assess_collector_health(client, include_healthy=True))[0].text)
        assert len(data["collectors"]) == 5

    @respx.mock
    async def test_unreadable_device_status_turns_healthy_into_unknown(self, client):
        fleet, _, _ = now_rows()
        portal(fleet, down=[2], fail=('hostStatus:"dead"',))
        data = json.loads((await assess_collector_health(client, include_healthy=True))[0].text)
        states = {c["collector_id"]: c["state"] for c in data["collectors"]}
        assert states[1] == "unknown"
        assert states[2] == "down"
        assert any("hostStatus dead" in s for s in data["signals_unavailable"])

    @respx.mock
    async def test_self_monitoring_alert_maps_through_collector_device_id(self, client):
        fleet, _, _ = now_rows()
        alert = {
            "monitorObjectId": 9001,
            "resourceTemplateName": "LogicMonitor_Collector_ExecutorQueue",
            "dataPointName": "QueueSize",
            "alertValue": 900,
            "severity": 3,
        }
        portal(fleet, down=[2], self_alerts=[alert])
        data = json.loads((await assess_collector_health(client, collector_ids=[1]))[0].text)
        assert data["collectors"][0]["state"] == "up_losing_work"


class TestAssessInsight:
    @respx.mock
    async def test_concentration_and_lead(self, client):
        fleet, dead, dc = now_rows()
        devices = {d: 4 for d in range(1, 38)}
        devices.update({d: 1 for d in range(38, 42)})
        portal(fleet, dead=dead, dead_collector=dc, down=[2], devices=devices)
        data = json.loads(
            (await assess_collector_health(client, device_ids=list(range(1, 42))))[0].text
        )
        assert data["scope"] == "insight devices"
        assert data["insight_devices"]["resolved"] == 41
        top = data["collectors"][0]
        assert top["collector_id"] == 4
        assert top["state"] == "up_devices_unreachable"
        assert top["insight_devices_here"] == 37
        assert top["concentration"] == round(37 / 41, 3)
        assert "37 of 41" in data["lead"]

    @respx.mock
    async def test_falls_back_when_or_filter_is_not_honoured(self, client):
        fleet, dead, dc = now_rows()
        devices = {11: 4, 12: 4, 13: 1}
        portal(fleet, dead=dead, dead_collector=dc, devices=devices, or_filter=False)
        data = json.loads(
            (await assess_collector_health(client, device_ids=[11, 12, 13, 99]))[0].text
        )
        assert data["insight_devices"]["resolved"] == 3
        assert data["insight_devices"]["unresolved_device_ids"] == [99]


class TestTier2:
    @respx.mock
    async def test_reads_both_forms_in_parallel_and_never_changes_state(self, client, monkeypatch):
        monkeypatch.setattr(cd, "POLL_SECONDS", 0.01)
        fleet, dead, dc = now_rows()
        portal(fleet, dead=dead, dead_collector=dc, down=[2])
        data = json.loads(
            (await assess_collector_health(client, collector_ids=[1, 2, 3, 4], use_debug=True))[
                0
            ].text
        )
        by = {c["collector_id"]: c for c in data["collectors"]}
        assert by[1]["tier2_health_check"]["status"] == "answered"
        assert "health check for 1" in by[1]["tier2_health_check"]["output_excerpt"]
        assert by[4]["state"] == "up_devices_unreachable"
        assert "tier2_health_check" not in by[2]  # down: not asked
        assert "tier2_health_check" not in by[3]  # silent: not asked
        assert data["tier2"]["collectors_read"] == 2

    @respx.mock
    async def test_budget_bounds_a_collector_that_never_answers(self, client, monkeypatch):
        monkeypatch.setattr(cd, "POLL_SECONDS", 0.05)
        fleet, dead, dc = now_rows()
        portal(fleet, dead=dead, dead_collector=dc, debug={1: "slow"})
        data = json.loads(
            (
                await assess_collector_health(
                    client, collector_ids=[1, 4], use_debug=True, debug_budget_seconds=1
                )
            )[0].text
        )
        by = {c["collector_id"]: c for c in data["collectors"]}
        assert by[1]["tier2_health_check"]["status"] == "no_reply"
        assert by[4]["tier2_health_check"]["status"] == "answered"
        assert data["tier2"]["elapsed_ms"] < 2500

    @respx.mock
    async def test_refused_debug_is_a_result(self, client, monkeypatch):
        monkeypatch.setattr(cd, "POLL_SECONDS", 0.01)
        fleet, dead, dc = now_rows()
        portal(fleet, dead=dead, dead_collector=dc, debug={1: "refuse"})
        data = json.loads(
            (await assess_collector_health(client, collector_ids=[1], use_debug=True))[0].text
        )
        t2 = data["collectors"][0]["tier2_health_check"]
        assert t2["status"] == "refused"
        assert data["collectors"][0]["state"] == "healthy"
