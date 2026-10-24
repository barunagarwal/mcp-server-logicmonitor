# Description: Tests for composite workflow tools.
# Description: Validates triage, health_check, capacity_plan, portal_overview, diagnose.

from __future__ import annotations

import json
import logging
import time
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from lm_mcp.auth.bearer import BearerAuth
from lm_mcp.client import LogicMonitorClient
from lm_mcp.tools import call_sub_tool
from lm_mcp.tools.workflows import (
    _resolve_device,
    _trim_detail,
    capacity_plan,
    check_required_tools,
    diagnose,
    health_check,
    portal_overview,
    search_tools,
    triage,
)
from tests.watsonx_sdk import real_watsonx_client


@pytest.fixture
def auth():
    """Create a BearerAuth instance for testing."""
    return BearerAuth("test-token")


@pytest.fixture
def client(auth):
    """Create a LogicMonitorClient instance for testing."""
    return LogicMonitorClient(
        base_url="https://test.logicmonitor.com/santaba/rest",
        auth=auth,
        timeout=30,
        api_version=3,
    )


# ---------------------------------------------------------------------------
# Helpers for building mock sub-tool responses
# ---------------------------------------------------------------------------


def _mock_text(data: dict) -> list:
    """Build a list matching the TextContent return format of tool handlers."""
    from mcp.types import TextContent

    return [TextContent(type="text", text=json.dumps(data))]


def _patch_sub(module_path: str, data: dict) -> patch:
    """Return an AsyncMock patch that returns TextContent wrapping *data*."""
    return patch(module_path, new_callable=AsyncMock, return_value=_mock_text(data))


# ---------------------------------------------------------------------------
# Helpers for driving detect_site_outage through respx
# ---------------------------------------------------------------------------

_BASE = "https://test.logicmonitor.com/santaba/rest"


def _ok(payload: dict) -> httpx.Response:
    return httpx.Response(200, json=payload)


def _portal_error() -> httpx.Response:
    return httpx.Response(500, json={"errorMessage": "portal unavailable"})


def _alert_window(*alerts: dict) -> httpx.Response:
    return _ok({"items": list(alerts), "total": len(alerts)})


def _power_alert() -> dict:
    return {
        "id": 7,
        "dataSourceName": "APC_UPS_Battery",
        "alertName": "OnBattery",
        "monitorObjectName": "ups-1",
        "startEpoch": int(time.time()) - 60,
        "severity": 4,
    }


def _mock_site_portal(
    devices: list[dict],
    collector_down: httpx.Response,
    burst: httpx.Response,
    power: httpx.Response,
) -> None:
    """Route one detect_site_outage run on group 42, served by collector 1.

    Burst detection and power events read the same alert window with the same
    filter, burst first, so the window reads are served in that order. The
    CollectorDown read is told apart by its filter.
    """

    def device_route(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("filter", "").startswith("currentCollectorId"):
            return _ok({"items": [], "total": len(devices)})
        return _ok({"items": devices, "total": len(devices)})

    window_reads = iter([burst, power])

    def alert_route(request: httpx.Request) -> httpx.Response:
        if "CollectorDown" in request.url.params.get("filter", ""):
            return collector_down
        return next(window_reads)

    respx.get(f"{_BASE}/device/devices").mock(side_effect=device_route)
    respx.get(f"{_BASE}/setting/collector/collectors/1").mock(
        return_value=_ok({"id": 1, "hostname": "col-01", "status": 1, "numberOfHosts": 5})
    )
    respx.get(f"{_BASE}/device/groups/42").mock(
        return_value=_ok({"id": 42, "fullPath": "Sites/HQ"})
    )
    respx.get(f"{_BASE}/alert/alerts").mock(side_effect=alert_route)


def _site_devices(count: int, status: str) -> list[dict]:
    return [
        {"id": i, "displayName": f"sw-{i}", "hostStatus": status, "currentCollectorId": 1}
        for i in range(1, count + 1)
    ]


@pytest.fixture
def lm_env(monkeypatch):
    """LM credentials and no tool filters, so composite tools pass check_required_tools."""
    monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
    monkeypatch.setenv("LM_BEARER_TOKEN", "test-bearer-token-value")
    monkeypatch.delenv("LM_ENABLED_TOOLS", raising=False)
    monkeypatch.delenv("LM_DISABLED_TOOLS", raising=False)
    monkeypatch.delenv("LM_MCP_CATEGORIES", raising=False)


_DS_URL = f"{_BASE}/device/devices/1/devicedatasources"


def _mock_capacity_portal(
    instance_data: dict[int, httpx.Response | list[httpx.Response]],
) -> None:
    """Route capacity_plan for device 1, datasource CPU (10).

    An instance given one response serves it to every data read; one given a list
    serves the reads in order (forecast, trend, seasonality, then change points).
    """
    respx.get(f"{_BASE}/device/devices/1").mock(
        return_value=_ok({"id": 1, "displayName": "server-01"})
    )
    respx.get(_DS_URL).mock(
        return_value=_ok({"items": [{"id": 10, "dataSourceName": "CPU"}], "total": 1})
    )
    respx.get(f"{_DS_URL}/10/instances").mock(
        return_value=_ok(
            {
                "items": [{"id": iid, "displayName": f"cpu{iid}"} for iid in instance_data],
                "total": len(instance_data),
            }
        )
    )
    for iid, response in instance_data.items():
        route = respx.get(f"{_DS_URL}/10/instances/{iid}/data")
        if isinstance(response, list):
            route.mock(side_effect=response)
        else:
            route.mock(return_value=response)


def _rising_cpu_and_sparse_mem() -> httpx.Response:
    """cpu climbs 10 per 5 minutes toward the 90 threshold; mem has one sample."""
    rows = [
        [10.0, "No Data"],
        [20.0, "No Data"],
        [30.0, 55.0],
        [40.0, "No Data"],
        [50.0, "No Data"],
    ]
    start = int(time.time()) - 3600
    return _ok(
        {
            "dataPoints": ["cpu", "mem"],
            "values": rows,
            "time": [(start + i * 300) * 1000 for i in range(len(rows))],
        }
    )


def _swinging_cpu() -> httpx.Response:
    """cpu swings between 5 and 95 every 5 minutes, which classify_trend calls volatile."""
    rows = [[5.0], [95.0], [5.0], [95.0], [5.0], [95.0]]
    start = int(time.time()) - 3600
    return _ok(
        {
            "dataPoints": ["cpu"],
            "values": rows,
            "time": [(start + i * 300) * 1000 for i in range(len(rows))],
        }
    )


# ---------------------------------------------------------------------------
# TestCheckRequiredTools
# ---------------------------------------------------------------------------


class TestCheckRequiredTools:
    """Tests for check_required_tools utility."""

    def test_all_tools_pass_returns_none(self, monkeypatch):
        """When no filtering is configured, all tools pass."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-bearer-token-value")
        monkeypatch.delenv("LM_ENABLED_TOOLS", raising=False)
        monkeypatch.delenv("LM_DISABLED_TOOLS", raising=False)
        from lm_mcp.config import reset_config

        reset_config()

        result = check_required_tools(["get_alerts", "correlate_alerts"])
        assert result is None
        reset_config()

    def test_blocked_with_enabled_tools(self, monkeypatch):
        """Tools not matching LM_ENABLED_TOOLS are blocked."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-bearer-token-value")
        monkeypatch.setenv("LM_ENABLED_TOOLS", "get_alerts,get_devices")
        monkeypatch.delenv("LM_DISABLED_TOOLS", raising=False)
        from lm_mcp.config import reset_config

        reset_config()

        result = check_required_tools(["get_alerts", "correlate_alerts"])
        assert result is not None
        text = result[0].text
        assert "correlate_alerts" in text
        reset_config()

    def test_blocked_with_disabled_tools(self, monkeypatch):
        """Tools matching LM_DISABLED_TOOLS are blocked."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-bearer-token-value")
        monkeypatch.setenv("LM_DISABLED_TOOLS", "correlate_*")
        monkeypatch.delenv("LM_ENABLED_TOOLS", raising=False)
        from lm_mcp.config import reset_config

        reset_config()

        result = check_required_tools(["get_alerts", "correlate_alerts"])
        assert result is not None
        text = result[0].text
        assert "correlate_alerts" in text
        reset_config()


# ---------------------------------------------------------------------------
# TestResolveDevice
# ---------------------------------------------------------------------------


class TestResolveDevice:
    """Tests for _resolve_device utility."""

    async def test_resolve_by_id(self, client):
        """Resolving by device_id calls get_device."""
        mock_device = {"id": 42, "displayName": "server-01"}
        with _patch_sub("lm_mcp.tools.devices.get_device", mock_device):
            dev_id, dev_data = await _resolve_device(client, device_id=42)
        assert dev_id == 42
        assert dev_data["displayName"] == "server-01"

    async def test_resolve_by_name(self, client):
        """Resolving by device_name calls get_devices and returns first match."""
        mock_result = {"devices": [{"id": 99, "displayName": "web-01"}]}
        with _patch_sub("lm_mcp.tools.devices.get_devices", mock_result):
            dev_id, _dev_data = await _resolve_device(client, device_name="web-01")
        assert dev_id == 99

    async def test_not_found_raises(self, client):
        """Raises ValueError when no device matches the name."""
        mock_result = {"devices": []}
        with (
            _patch_sub("lm_mcp.tools.devices.get_devices", mock_result),
            pytest.raises(ValueError, match="No device found"),
        ):
            await _resolve_device(client, device_name="ghost")

    async def test_missing_params_raises(self, client):
        """Raises ValueError when neither device_id nor device_name given."""
        with pytest.raises(ValueError, match="Either device_id or device_name"):
            await _resolve_device(client)


# ---------------------------------------------------------------------------
# TestTrimDetail
# ---------------------------------------------------------------------------


class TestTrimDetail:
    """Tests for _trim_detail utility."""

    def test_summary_strips_keys(self):
        report = {"a": 1, "b": 2, "c": 3}
        trimmed = _trim_detail(report, "summary", {"b", "c"})
        assert trimmed == {"a": 1}

    def test_full_keeps_all(self):
        report = {"a": 1, "b": 2, "c": 3}
        trimmed = _trim_detail(report, "full", {"b", "c"})
        assert trimmed == report


# ---------------------------------------------------------------------------
# TestTriage
# ---------------------------------------------------------------------------


class TestTriage:
    """Tests for the triage composite tool."""

    async def test_happy_path_summary(self, client, monkeypatch):
        """Triage returns a report with expected keys in summary mode."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-bearer-token-value")
        monkeypatch.delenv("LM_ENABLED_TOOLS", raising=False)
        monkeypatch.delenv("LM_DISABLED_TOOLS", raising=False)
        from lm_mcp.config import reset_config

        reset_config()

        stats_data = {"summary": {"total": 5}, "time_buckets": []}
        clusters_data = {"total_alerts": 5, "clusters": [], "cluster_count": 0}
        noise_data = {"noise_score": 10, "total_alerts": 5}
        changes_data = {"correlated_events": [], "total_alerts": 5}

        with (
            _patch_sub("lm_mcp.tools.correlation.get_alert_statistics", stats_data),
            _patch_sub("lm_mcp.tools.correlation.correlate_alerts", clusters_data),
            _patch_sub("lm_mcp.tools.scoring.score_alert_noise", noise_data),
            _patch_sub("lm_mcp.tools.event_correlation.correlate_changes", changes_data),
        ):
            result = await triage(client, detail_level="summary")

        data = json.loads(result[0].text)
        assert "statistics" in data
        assert "noise" in data
        # blast_radius stripped in summary mode
        assert "blast_radius" not in data
        reset_config()

    async def test_happy_path_full(self, client, monkeypatch):
        """Triage full mode includes blast_radius."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-bearer-token-value")
        monkeypatch.delenv("LM_ENABLED_TOOLS", raising=False)
        monkeypatch.delenv("LM_DISABLED_TOOLS", raising=False)
        from lm_mcp.config import reset_config

        reset_config()

        stats_data = {"summary": {"total": 0}, "time_buckets": []}
        clusters_data = {"total_alerts": 0, "clusters": [], "cluster_count": 0}
        noise_data = {"noise_score": 0, "total_alerts": 0}
        changes_data = {"correlated_events": [], "total_alerts": 0}

        with (
            _patch_sub("lm_mcp.tools.correlation.get_alert_statistics", stats_data),
            _patch_sub("lm_mcp.tools.correlation.correlate_alerts", clusters_data),
            _patch_sub("lm_mcp.tools.scoring.score_alert_noise", noise_data),
            _patch_sub("lm_mcp.tools.event_correlation.correlate_changes", changes_data),
        ):
            result = await triage(client, detail_level="full")

        data = json.loads(result[0].text)
        assert "blast_radius" in data
        reset_config()

    async def test_required_tool_blocked(self, client, monkeypatch):
        """Triage returns error when a required tool is disabled."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-bearer-token-value")
        monkeypatch.setenv("LM_DISABLED_TOOLS", "correlate_alerts")
        monkeypatch.delenv("LM_ENABLED_TOOLS", raising=False)
        from lm_mcp.config import reset_config

        reset_config()

        result = await triage(client)
        text = result[0].text
        assert "REQUIRED_TOOLS_DISABLED" in text or "correlate_alerts" in text
        reset_config()

    async def test_sub_tool_failure_partial_results(self, client, monkeypatch):
        """Triage returns partial results with warnings when a sub-tool fails."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-bearer-token-value")
        monkeypatch.delenv("LM_ENABLED_TOOLS", raising=False)
        monkeypatch.delenv("LM_DISABLED_TOOLS", raising=False)
        from lm_mcp.config import reset_config

        reset_config()

        clusters_data = {"total_alerts": 0, "clusters": [], "cluster_count": 0}
        noise_data = {"noise_score": 0, "total_alerts": 0}
        changes_data = {"correlated_events": [], "total_alerts": 0}

        with (
            patch(
                "lm_mcp.tools.correlation.get_alert_statistics",
                new_callable=AsyncMock,
                side_effect=RuntimeError("API timeout"),
            ),
            _patch_sub("lm_mcp.tools.correlation.correlate_alerts", clusters_data),
            _patch_sub("lm_mcp.tools.scoring.score_alert_noise", noise_data),
            _patch_sub("lm_mcp.tools.event_correlation.correlate_changes", changes_data),
        ):
            result = await triage(client, detail_level="full")

        data = json.loads(result[0].text)
        assert data["statistics"] is None
        assert "warnings" in data
        reset_config()


# ---------------------------------------------------------------------------
# TestHealthCheck
# ---------------------------------------------------------------------------


class TestHealthCheck:
    """Tests for the health_check composite tool."""

    async def test_happy_path_summary(self, client, monkeypatch):
        """Health check returns expected keys in summary mode."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-bearer-token-value")
        monkeypatch.delenv("LM_ENABLED_TOOLS", raising=False)
        monkeypatch.delenv("LM_DISABLED_TOOLS", raising=False)
        from lm_mcp.config import reset_config

        reset_config()

        device_data = {"id": 1, "displayName": "server-01"}
        ds_data = {"datasources": [{"id": 10, "name": "CPU"}]}
        inst_data = {"instances": [{"id": 100, "name": "main"}]}
        score_data = {"health_score": 85, "status": "healthy"}
        anomaly_data = {"anomaly_count": 0, "anomalies": []}
        alert_data = {"total": 0, "alerts": []}
        avail_data = {"availability_percent": 99.99}

        with (
            _patch_sub("lm_mcp.tools.devices.get_device", device_data),
            _patch_sub("lm_mcp.tools.metrics.get_device_datasources", ds_data),
            _patch_sub("lm_mcp.tools.metrics.get_device_instances", inst_data),
            _patch_sub("lm_mcp.tools.scoring.score_device_health", score_data),
            _patch_sub("lm_mcp.tools.correlation.get_metric_anomalies", anomaly_data),
            _patch_sub("lm_mcp.tools.alerts.get_alerts", alert_data),
            _patch_sub("lm_mcp.tools.scoring.calculate_availability", avail_data),
        ):
            result = await health_check(client, device_id=1, detail_level="summary")

        data = json.loads(result[0].text)
        assert data["device_id"] == 1
        assert "datasource_count" in data
        # anomalies and health_scores stripped in summary
        assert "anomalies" not in data
        assert "health_scores" not in data
        reset_config()

    async def test_happy_path_full(self, client, monkeypatch):
        """Health check full mode includes anomalies and health_scores."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-bearer-token-value")
        monkeypatch.delenv("LM_ENABLED_TOOLS", raising=False)
        monkeypatch.delenv("LM_DISABLED_TOOLS", raising=False)
        from lm_mcp.config import reset_config

        reset_config()

        device_data = {"id": 1, "displayName": "server-01"}
        ds_data = {"datasources": [{"id": 10, "name": "CPU"}]}
        inst_data = {"instances": [{"id": 100, "name": "main"}]}
        score_data = {"health_score": 85, "status": "healthy"}
        anomaly_data = {"anomaly_count": 0, "anomalies": []}
        alert_data = {"total": 0, "alerts": []}
        avail_data = {"availability_percent": 99.99}

        with (
            _patch_sub("lm_mcp.tools.devices.get_device", device_data),
            _patch_sub("lm_mcp.tools.metrics.get_device_datasources", ds_data),
            _patch_sub("lm_mcp.tools.metrics.get_device_instances", inst_data),
            _patch_sub("lm_mcp.tools.scoring.score_device_health", score_data),
            _patch_sub("lm_mcp.tools.correlation.get_metric_anomalies", anomaly_data),
            _patch_sub("lm_mcp.tools.alerts.get_alerts", alert_data),
            _patch_sub("lm_mcp.tools.scoring.calculate_availability", avail_data),
        ):
            result = await health_check(client, device_id=1, detail_level="full")

        data = json.loads(result[0].text)
        assert "anomalies" in data
        assert "health_scores" in data
        reset_config()

    async def test_required_tool_blocked(self, client, monkeypatch):
        """Health check returns error when a required tool is disabled."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-bearer-token-value")
        monkeypatch.setenv("LM_DISABLED_TOOLS", "get_device_datasources")
        monkeypatch.delenv("LM_ENABLED_TOOLS", raising=False)
        from lm_mcp.config import reset_config

        reset_config()

        result = await health_check(client, device_id=1)
        text = result[0].text
        assert "REQUIRED_TOOLS_DISABLED" in text or "get_device_datasources" in text
        reset_config()

    async def test_sub_tool_failure(self, client, monkeypatch):
        """Health check returns partial results with warnings on sub-tool failure."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-bearer-token-value")
        monkeypatch.delenv("LM_ENABLED_TOOLS", raising=False)
        monkeypatch.delenv("LM_DISABLED_TOOLS", raising=False)
        from lm_mcp.config import reset_config

        reset_config()

        device_data = {"id": 1, "displayName": "server-01"}
        alert_data = {"total": 0, "alerts": []}
        avail_data = {"availability_percent": 99.99}

        with (
            _patch_sub("lm_mcp.tools.devices.get_device", device_data),
            patch(
                "lm_mcp.tools.metrics.get_device_datasources",
                new_callable=AsyncMock,
                side_effect=RuntimeError("timeout"),
            ),
            _patch_sub("lm_mcp.tools.alerts.get_alerts", alert_data),
            _patch_sub("lm_mcp.tools.scoring.calculate_availability", avail_data),
        ):
            result = await health_check(client, device_id=1, detail_level="full")

        data = json.loads(result[0].text)
        assert data["datasource_count"] == 0
        assert "warnings" in data
        reset_config()


# ---------------------------------------------------------------------------
# TestCapacityPlan
# ---------------------------------------------------------------------------


class TestCapacityPlan:
    """Tests for the capacity_plan composite tool."""

    async def test_happy_path_summary(self, client, monkeypatch):
        """Capacity plan returns expected keys in summary mode."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-bearer-token-value")
        monkeypatch.delenv("LM_ENABLED_TOOLS", raising=False)
        monkeypatch.delenv("LM_DISABLED_TOOLS", raising=False)
        from lm_mcp.config import reset_config

        reset_config()

        device_data = {"id": 1, "displayName": "server-01"}
        ds_data = {"datasources": [{"id": 10, "name": "CPU"}]}
        inst_data = {"instances": [{"id": 100, "name": "main"}]}
        forecast_data = {"forecasts": {"cpu": {"trend": "increasing"}}}
        trend_data = {"classifications": {"cpu": {"classification": "stable"}}}
        season_data = {"seasonality": {"cpu": {"is_seasonal": False}}}

        with (
            _patch_sub("lm_mcp.tools.devices.get_device", device_data),
            _patch_sub("lm_mcp.tools.metrics.get_device_datasources", ds_data),
            _patch_sub("lm_mcp.tools.metrics.get_device_instances", inst_data),
            _patch_sub("lm_mcp.tools.forecasting.forecast_metric", forecast_data),
            _patch_sub("lm_mcp.tools.forecasting.classify_trend", trend_data),
            _patch_sub("lm_mcp.tools.forecasting.detect_seasonality", season_data),
        ):
            result = await capacity_plan(
                client,
                device_id=1,
                detail_level="summary",
            )

        data = json.loads(result[0].text)
        assert data["device_id"] == 1
        # datasources stripped in summary mode
        assert "datasources" not in data
        reset_config()

    async def test_happy_path_full(self, client, monkeypatch):
        """Capacity plan full mode includes datasources."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-bearer-token-value")
        monkeypatch.delenv("LM_ENABLED_TOOLS", raising=False)
        monkeypatch.delenv("LM_DISABLED_TOOLS", raising=False)
        from lm_mcp.config import reset_config

        reset_config()

        device_data = {"id": 1, "displayName": "server-01"}
        ds_data = {"datasources": [{"id": 10, "name": "CPU"}]}
        inst_data = {"instances": [{"id": 100, "name": "main"}]}
        forecast_data = {"forecasts": {"cpu": {"trend": "increasing"}}}
        trend_data = {"classifications": {"cpu": {"classification": "stable"}}}
        season_data = {"seasonality": {"cpu": {"is_seasonal": False}}}

        with (
            _patch_sub("lm_mcp.tools.devices.get_device", device_data),
            _patch_sub("lm_mcp.tools.metrics.get_device_datasources", ds_data),
            _patch_sub("lm_mcp.tools.metrics.get_device_instances", inst_data),
            _patch_sub("lm_mcp.tools.forecasting.forecast_metric", forecast_data),
            _patch_sub("lm_mcp.tools.forecasting.classify_trend", trend_data),
            _patch_sub("lm_mcp.tools.forecasting.detect_seasonality", season_data),
        ):
            result = await capacity_plan(
                client,
                device_id=1,
                detail_level="full",
            )

        data = json.loads(result[0].text)
        assert "datasources" in data
        assert len(data["datasources"]) == 1
        reset_config()

    @respx.mock
    async def test_summary_carries_forecast_headlines_and_instance_errors(self, auth, lm_env):
        """R4.4: the summary keeps each forecast's headline and every per-instance error.

        cpu100 forecasts; cpu101's data read fails, so its forecast, trend and
        seasonality each fail. The raw datasources block is still trimmed.
        """
        client = LogicMonitorClient(base_url=_BASE, auth=auth, max_retries=0)
        _mock_capacity_portal({100: _rising_cpu_and_sparse_mem(), 101: _portal_error()})

        result = await capacity_plan(client, device_id=1)

        data = json.loads(result[0].text)
        assert "datasources" not in data
        cpu, mem = data["forecast_summary"]
        assert cpu["datasource"] == "CPU"
        assert cpu["instance"] == "cpu100"
        assert cpu["datapoint"] == "cpu"
        assert cpu["method"] == "linear"
        assert cpu["trend"] == "increasing"
        assert cpu["days_until_breach"] > 0
        assert mem == {
            "datasource": "CPU",
            "instance": "cpu100",
            "datapoint": "mem",
            "status": "insufficient_data",
        }
        failed = [w for w in data["warnings"] if "CPU/cpu101" in w]
        assert [w.split(" for ")[0] for w in failed] == ["forecast", "trend", "seasonality"]
        assert all("portal unavailable" in w for w in failed)

    @respx.mock
    async def test_summary_carries_a_change_point_failure(self, auth, lm_env):
        """R4.4: a failed change-point read on a volatile instance reaches the summary warnings.

        cpu102's trend is volatile, so capacity_plan reads its series a fourth time
        for change points, and that read fails.
        """
        client = LogicMonitorClient(base_url=_BASE, auth=auth, max_retries=0)
        reads = [_swinging_cpu(), _swinging_cpu(), _swinging_cpu(), _portal_error()]
        _mock_capacity_portal({102: reads})

        result = await capacity_plan(client, device_id=1)

        data = json.loads(result[0].text)
        (warning,) = data["warnings"]
        assert warning.startswith("change_points for CPU/cpu102 failed:")
        assert "portal unavailable" in warning

    @respx.mock
    async def test_full_detail_is_unchanged(self, auth, lm_env):
        """R4.4: detail_level=full keeps the raw block and adds no summary or copied errors."""
        client = LogicMonitorClient(base_url=_BASE, auth=auth, max_retries=0)
        _mock_capacity_portal({100: _rising_cpu_and_sparse_mem(), 101: _portal_error()})

        result = await capacity_plan(client, device_id=1, detail_level="full")

        data = json.loads(result[0].text)
        assert "forecast_summary" not in data
        assert "warnings" not in data
        failed = data["datasources"][0]["instances"][1]
        assert failed["instance"] == "cpu101"
        assert "portal unavailable" in failed["forecast_error"]
        assert "portal unavailable" in failed["trend_error"]

    async def test_surfaces_forecast_failure(self, client, monkeypatch):
        """A failing forecast sub-tool is surfaced as forecast_error, not a silent None."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-bearer-token-value")
        monkeypatch.delenv("LM_ENABLED_TOOLS", raising=False)
        monkeypatch.delenv("LM_DISABLED_TOOLS", raising=False)
        from lm_mcp.config import reset_config

        reset_config()

        device_data = {"id": 1, "displayName": "server-01"}
        ds_data = {"datasources": [{"id": 10, "name": "CPU"}]}
        inst_data = {"instances": [{"id": 100, "name": "main"}]}
        trend_data = {"classifications": {"cpu": {"classification": "stable"}}}
        season_data = {"seasonality": {"cpu": {"is_seasonal": False}}}

        with (
            _patch_sub("lm_mcp.tools.devices.get_device", device_data),
            _patch_sub("lm_mcp.tools.metrics.get_device_datasources", ds_data),
            _patch_sub("lm_mcp.tools.metrics.get_device_instances", inst_data),
            patch(
                "lm_mcp.tools.forecasting.forecast_metric",
                new_callable=AsyncMock,
                side_effect=RuntimeError("ttm down"),
            ),
            _patch_sub("lm_mcp.tools.forecasting.classify_trend", trend_data),
            _patch_sub("lm_mcp.tools.forecasting.detect_seasonality", season_data),
        ):
            result = await capacity_plan(client, device_id=1, detail_level="full")

        data = json.loads(result[0].text)
        inst0 = data["datasources"][0]["instances"][0]
        assert inst0["forecast"] is None
        assert "ttm down" in inst0["forecast_error"]
        reset_config()

    async def test_required_tool_blocked(self, client, monkeypatch):
        """Capacity plan returns error when a required tool is disabled."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-bearer-token-value")
        monkeypatch.setenv("LM_DISABLED_TOOLS", "forecast_metric")
        monkeypatch.delenv("LM_ENABLED_TOOLS", raising=False)
        from lm_mcp.config import reset_config

        reset_config()

        result = await capacity_plan(client, device_id=1)
        text = result[0].text
        assert "REQUIRED_TOOLS_DISABLED" in text or "forecast_metric" in text
        reset_config()

    async def test_empty_datasources(self, client, monkeypatch):
        """Capacity plan handles a device with no datasources gracefully."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-bearer-token-value")
        monkeypatch.delenv("LM_ENABLED_TOOLS", raising=False)
        monkeypatch.delenv("LM_DISABLED_TOOLS", raising=False)
        from lm_mcp.config import reset_config

        reset_config()

        device_data = {"id": 1, "displayName": "server-01"}
        ds_data = {"datasources": []}

        with (
            _patch_sub("lm_mcp.tools.devices.get_device", device_data),
            _patch_sub("lm_mcp.tools.metrics.get_device_datasources", ds_data),
        ):
            result = await capacity_plan(
                client,
                device_id=1,
                detail_level="full",
            )

        data = json.loads(result[0].text)
        assert data["datasources"] == []
        reset_config()


class TestSummaryFailureWarnings:
    """R4.4: a requested NL summary that does not arrive is reported in warnings."""

    @respx.mock
    async def test_summary_without_a_model_is_warned(self, auth, lm_env):
        """R4.4: triage(summarize=True) with no summary model returns a warning saying so."""
        respx.get(url__startswith=_BASE).mock(return_value=_ok({"items": [], "total": 0}))
        client = LogicMonitorClient(base_url=_BASE, auth=auth, max_retries=0)

        result = await triage(client, summarize=True)

        data = json.loads(result[0].text)
        assert "nl_summary" not in data
        (warning,) = data["warnings"]
        assert warning.startswith("NL summary requested but")
        assert "not configured" in warning

    @respx.mock
    async def test_failing_summary_names_the_error(self, auth, lm_env, caplog):
        """R4.4: triage(summarize=True) with watsonx failing returns the error in warnings.

        The failure is also logged at WARNING on lm_mcp.audit with its traceback.
        """
        from lm_mcp.server import _set_watsonx_client

        respx.get(url__startswith=_BASE).mock(return_value=_ok({"items": [], "total": 0}))
        client = LogicMonitorClient(base_url=_BASE, auth=auth, max_retries=0)
        _set_watsonx_client(real_watsonx_client())

        with (
            patch("ibm_watsonx_ai.foundation_models.ModelInference", autospec=True) as model_cls,
            caplog.at_level(logging.WARNING, logger="lm_mcp.audit"),
        ):
            model_cls.return_value.generate_text.side_effect = RuntimeError(
                "503 Service Unavailable"
            )
            result = await triage(client, summarize=True)

        data = json.loads(result[0].text)
        assert "nl_summary" not in data
        (warning,) = data["warnings"]
        assert warning.startswith("NL summary failed")
        assert "503 Service Unavailable" in warning
        model_cls.return_value.generate_text.assert_called_once()
        (record,) = [r for r in caplog.records if "NL summary failed" in r.getMessage()]
        assert record.name == "lm_mcp.audit"
        assert record.levelno == logging.WARNING
        assert record.exc_info is not None
        assert "503 Service Unavailable" in record.getMessage()


# ---------------------------------------------------------------------------
# TestPortalOverview
# ---------------------------------------------------------------------------


class TestPortalOverview:
    """Tests for the portal_overview composite tool."""

    async def test_happy_path_summary(self, client, monkeypatch):
        """Portal overview returns expected keys in summary mode."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-bearer-token-value")
        monkeypatch.delenv("LM_ENABLED_TOOLS", raising=False)
        monkeypatch.delenv("LM_DISABLED_TOOLS", raising=False)
        from lm_mcp.config import reset_config

        reset_config()

        stats_data = {"summary": {"total": 10}}
        alert_data = {"total": 2, "alerts": []}
        coll_data = {"total": 3, "collectors": []}
        sdt_data = {"active_sdts": []}
        cluster_data = {"clusters": [], "total_alerts": 0}
        noise_data = {"noise_score": 5}
        dead_data = {"devices": [], "total": 0}

        with (
            _patch_sub("lm_mcp.tools.correlation.get_alert_statistics", stats_data),
            _patch_sub("lm_mcp.tools.alerts.get_alerts", alert_data),
            _patch_sub("lm_mcp.tools.collectors.get_collectors", coll_data),
            _patch_sub("lm_mcp.tools.sdts.get_active_sdts", sdt_data),
            _patch_sub("lm_mcp.tools.correlation.correlate_alerts", cluster_data),
            _patch_sub("lm_mcp.tools.scoring.score_alert_noise", noise_data),
            _patch_sub("lm_mcp.tools.devices.get_devices", dead_data),
        ):
            result = await portal_overview(client, detail_level="summary")

        data = json.loads(result[0].text)
        assert "alert_statistics" in data
        assert "noise" in data
        # summary strips detail lists
        assert "critical_alerts" not in data
        assert "dead_devices" not in data
        reset_config()

    async def test_happy_path_full(self, client, monkeypatch):
        """Portal overview full mode includes all keys."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-bearer-token-value")
        monkeypatch.delenv("LM_ENABLED_TOOLS", raising=False)
        monkeypatch.delenv("LM_DISABLED_TOOLS", raising=False)
        from lm_mcp.config import reset_config

        reset_config()

        stats_data = {"summary": {"total": 10}}
        alert_data = {"total": 2, "alerts": []}
        coll_data = {"total": 3, "collectors": []}
        sdt_data = {"active_sdts": []}
        cluster_data = {"clusters": [], "total_alerts": 0}
        noise_data = {"noise_score": 5}
        dead_data = {"devices": [], "total": 0}

        with (
            _patch_sub("lm_mcp.tools.correlation.get_alert_statistics", stats_data),
            _patch_sub("lm_mcp.tools.alerts.get_alerts", alert_data),
            _patch_sub("lm_mcp.tools.collectors.get_collectors", coll_data),
            _patch_sub("lm_mcp.tools.sdts.get_active_sdts", sdt_data),
            _patch_sub("lm_mcp.tools.correlation.correlate_alerts", cluster_data),
            _patch_sub("lm_mcp.tools.scoring.score_alert_noise", noise_data),
            _patch_sub("lm_mcp.tools.devices.get_devices", dead_data),
        ):
            result = await portal_overview(client, detail_level="full")

        data = json.loads(result[0].text)
        assert "critical_alerts" in data
        assert "dead_devices" in data
        reset_config()

    async def test_required_tool_blocked(self, client, monkeypatch):
        """Portal overview returns error when a required tool is disabled."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-bearer-token-value")
        monkeypatch.setenv("LM_DISABLED_TOOLS", "get_collectors")
        monkeypatch.delenv("LM_ENABLED_TOOLS", raising=False)
        from lm_mcp.config import reset_config

        reset_config()

        result = await portal_overview(client)
        text = result[0].text
        assert "REQUIRED_TOOLS_DISABLED" in text or "get_collectors" in text
        reset_config()


# ---------------------------------------------------------------------------
# TestDiagnose
# ---------------------------------------------------------------------------


class TestDiagnose:
    """Tests for the diagnose composite tool."""

    async def test_happy_path_with_alert_id(self, client, monkeypatch):
        """Diagnose by alert_id returns expected keys."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-bearer-token-value")
        monkeypatch.delenv("LM_ENABLED_TOOLS", raising=False)
        monkeypatch.delenv("LM_DISABLED_TOOLS", raising=False)
        from lm_mcp.config import reset_config

        reset_config()

        alert_detail = {
            "id": "LMA123",
            "severity": 4,
            "monitorObjectId": 42,
            "monitorObjectName": "server-01",
        }
        device_data = {"id": 42, "displayName": "server-01"}
        props_data = {"properties": [{"name": "os", "value": "linux"}]}
        corr_data = {"clusters": [], "total_alerts": 1}
        changes_data = {"correlated_events": []}
        blast_data = {"blast_radius_score": 10, "affected_devices": []}

        with (
            _patch_sub("lm_mcp.tools.alerts.get_alert_details", alert_detail),
            _patch_sub("lm_mcp.tools.devices.get_device", device_data),
            _patch_sub("lm_mcp.tools.resources.get_device_properties", props_data),
            _patch_sub("lm_mcp.tools.correlation.correlate_alerts", corr_data),
            _patch_sub("lm_mcp.tools.event_correlation.correlate_changes", changes_data),
            _patch_sub("lm_mcp.tools.topology_analysis.analyze_blast_radius", blast_data),
        ):
            result = await diagnose(client, alert_id="LMA123", detail_level="full")

        data = json.loads(result[0].text)
        assert data.get("alert", {}).get("id") == "LMA123"
        assert "device" in data
        assert "blast_radius" in data
        reset_config()

    async def test_happy_path_with_device_name(self, client, monkeypatch):
        """Diagnose by device_name resolves most recent critical alert."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-bearer-token-value")
        monkeypatch.delenv("LM_ENABLED_TOOLS", raising=False)
        monkeypatch.delenv("LM_DISABLED_TOOLS", raising=False)
        from lm_mcp.config import reset_config

        reset_config()

        alerts_list = {"total": 1, "alerts": [{"id": "LMA456", "severity": 4}]}
        alert_detail = {
            "id": "LMA456",
            "severity": 4,
            "monitorObjectId": 55,
        }
        device_data = {"id": 55, "displayName": "db-01"}
        props_data = {"properties": []}
        corr_data = {"clusters": []}
        changes_data = {"correlated_events": []}
        blast_data = {"blast_radius_score": 0, "affected_devices": []}

        with (
            _patch_sub("lm_mcp.tools.alerts.get_alerts", alerts_list),
            _patch_sub("lm_mcp.tools.alerts.get_alert_details", alert_detail),
            _patch_sub("lm_mcp.tools.devices.get_device", device_data),
            _patch_sub("lm_mcp.tools.resources.get_device_properties", props_data),
            _patch_sub("lm_mcp.tools.correlation.correlate_alerts", corr_data),
            _patch_sub("lm_mcp.tools.event_correlation.correlate_changes", changes_data),
            _patch_sub("lm_mcp.tools.topology_analysis.analyze_blast_radius", blast_data),
        ):
            result = await diagnose(client, device_name="db-01", detail_level="full")

        data = json.loads(result[0].text)
        assert data.get("alert", {}).get("id") == "LMA456"
        reset_config()

    async def test_missing_params(self, client, monkeypatch):
        """Diagnose returns error when neither alert_id nor device_name given."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-bearer-token-value")
        monkeypatch.delenv("LM_ENABLED_TOOLS", raising=False)
        monkeypatch.delenv("LM_DISABLED_TOOLS", raising=False)
        from lm_mcp.config import reset_config

        reset_config()

        result = await diagnose(client)
        text = result[0].text
        assert "MISSING_PARAMS" in text or "alert_id or device_name" in text
        reset_config()

    async def test_required_tool_blocked(self, client, monkeypatch):
        """Diagnose returns error when a required tool is disabled."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-bearer-token-value")
        monkeypatch.setenv("LM_DISABLED_TOOLS", "analyze_blast_radius")
        monkeypatch.delenv("LM_ENABLED_TOOLS", raising=False)
        from lm_mcp.config import reset_config

        reset_config()

        result = await diagnose(client, alert_id="LMA123")
        text = result[0].text
        assert "REQUIRED_TOOLS_DISABLED" in text or "analyze_blast_radius" in text
        reset_config()


# ---------------------------------------------------------------------------
# TestSearchTools
# ---------------------------------------------------------------------------


class TestSearchTools:
    """Tests for the search_tools discovery tool."""

    async def test_keyword_name_match(self, client):
        """Searching for a tool name returns it with high score."""
        result = await search_tools(client, query="get_alerts")
        data = json.loads(result[0].text)
        matches = data["matches"]
        assert len(matches) > 0
        # The exact name match should be first
        assert matches[0]["name"] == "get_alerts"

    async def test_description_match(self, client):
        """Searching for a word in descriptions returns relevant tools."""
        result = await search_tools(client, query="forecast")
        data = json.loads(result[0].text)
        assert data["total"] > 0
        tool_names = [m["name"] for m in data["matches"]]
        assert "forecast_metric" in tool_names

    async def test_configured_integration_tools_are_searchable(self, client):
        """AWX/Terraform tools (conditional) become searchable when their client is set.

        Regression for the drift where search_tools iterated only the core TOOLS list,
        leaving the AWX/watsonx/Terraform tools unsearchable even when configured.
        """
        from unittest.mock import patch

        # Not configured -> AWX tools are absent from the search corpus.
        result = await search_tools(client, query="ansible job template")
        names = [m["name"] for m in json.loads(result[0].text)["matches"]]
        assert "get_job_templates" not in names

        # Configured -> AWX tools are searchable.
        with patch("lm_mcp.server.get_awx_client", return_value=object()):
            result = await search_tools(client, query="ansible job template")
        names = [m["name"] for m in json.loads(result[0].text)["matches"]]
        assert "get_job_templates" in names

    async def test_category_filter(self, client):
        """Category filter restricts results to that category's tools."""
        result = await search_tools(client, query="alert", category="alerts")
        data = json.loads(result[0].text)
        # All results should be from the alerts category
        alert_tools = {
            "get_alerts",
            "get_alert_details",
            "acknowledge_alert",
            "add_alert_note",
            "bulk_acknowledge_alerts",
        }
        for match in data["matches"]:
            assert match["name"] in alert_tools

    async def test_limit(self, client):
        """Limit parameter caps the number of results."""
        result = await search_tools(client, query="get", limit=3)
        data = json.loads(result[0].text)
        assert len(data["matches"]) <= 3

    async def test_composite_suggestion(self, client):
        """Workflow-related queries suggest composite tools."""
        result = await search_tools(client, query="incident triage")
        data = json.loads(result[0].text)
        suggestions = data.get("suggestions") or []
        assert "triage" in suggestions or "diagnose" in suggestions

    async def test_no_matches(self, client):
        """Non-matching query returns empty results."""
        result = await search_tools(client, query="xyznonexistent123")
        data = json.loads(result[0].text)
        assert data["total"] == 0
        assert data["matches"] == []

    async def test_invalid_category(self, client):
        """Invalid category returns empty results with available categories."""
        result = await search_tools(
            client,
            query="alert",
            category="nonexistent_cat",
        )
        data = json.loads(result[0].text)
        assert data["total"] == 0
        assert "available_categories" in data


# ---------------------------------------------------------------------------
# TestCallSubTool (robustness against non-JSON / error-formatted responses)
# ---------------------------------------------------------------------------


class TestCallSubTool:
    """Direct tests for `call_sub_tool` parse and error-handling behavior."""

    async def test_happy_path_returns_parsed_json(self, client):
        from mcp.types import TextContent

        async def handler(_client):
            return [TextContent(type="text", text=json.dumps({"ok": True, "n": 42}))]

        data = await call_sub_tool(handler, client)
        assert data == {"ok": True, "n": 42}

    async def test_error_formatted_text_raises_runtime_error(self, client):
        """format_response renders errors as 'Error: ...' text, not JSON.

        `call_sub_tool` must detect that shape and raise a clean
        RuntimeError with the underlying message rather than leaking a
        JSONDecodeError from json.loads.
        """
        from mcp.types import TextContent

        async def handler(_client):
            return [
                TextContent(
                    type="text",
                    text="Error: collector 999 not found\nSuggestion: Verify the ID.",
                )
            ]

        with pytest.raises(RuntimeError, match="collector 999 not found"):
            await call_sub_tool(handler, client)

    async def test_non_json_non_error_text_raises_with_snippet(self, client):
        """Truly unexpected text (neither JSON nor 'Error:') surfaces a snippet."""
        from mcp.types import TextContent

        async def handler(_client):
            return [TextContent(type="text", text="<html>gateway timeout</html>")]

        with pytest.raises(RuntimeError, match="non-JSON response"):
            await call_sub_tool(handler, client)

    async def test_dict_with_error_field_raises(self, client):
        """A parsed dict carrying {'error': True} still triggers RuntimeError."""
        from mcp.types import TextContent

        async def handler(_client):
            return [
                TextContent(
                    type="text",
                    text=json.dumps({"error": True, "code": "SOMETHING", "message": "nope"}),
                )
            ]

        with pytest.raises(RuntimeError, match="nope"):
            await call_sub_tool(handler, client)


# ---------------------------------------------------------------------------
# TestSiteOutageHelpers (shape compatibility with get_devices formatted output)
# ---------------------------------------------------------------------------


class TestSiteOutageHelpers:
    """Direct tests for _collector_ids_from_devices and _count_dead_devices.

    These helpers receive output from the formatted `get_devices` sub-tool
    (which renames `currentCollectorId` -> `collector_id` and `hostStatus`
    -> `status`). The helpers must handle both shapes.
    """

    def test_collector_ids_from_formatted_shape(self):
        """Formatted get_devices output uses `collector_id`."""
        from lm_mcp.tools.workflows import _collector_ids_from_devices

        devices = [
            {"id": 1, "collector_id": 10},
            {"id": 2, "collector_id": 10},  # duplicate
            {"id": 3, "collector_id": 20},
            {"id": 4, "collector_id": None},  # unassigned
        ]
        assert _collector_ids_from_devices(devices) == [10, 20]

    def test_collector_ids_from_raw_shape(self):
        """Raw LM API items use `currentCollectorId`."""
        from lm_mcp.tools.workflows import _collector_ids_from_devices

        devices = [
            {"id": 1, "currentCollectorId": 11},
            {"id": 2, "preferredCollectorId": 22},
        ]
        assert _collector_ids_from_devices(devices) == [11, 22]

    def test_collector_ids_empty(self):
        """No collector fields present returns empty list."""
        from lm_mcp.tools.workflows import _collector_ids_from_devices

        assert _collector_ids_from_devices([{"id": 1}]) == []

    def test_dead_devices_counts_status_1_and_2(self):
        """Both hostStatus=1 (dead) and hostStatus=2 (dead-collector) count."""
        from lm_mcp.tools.workflows import _count_dead_devices

        devices = [
            {"id": 1, "status": 0},  # normal
            {"id": 2, "status": 1},  # dead
            {"id": 3, "status": 2},  # dead-collector
            {"id": 4, "status": 3},  # unmonitored, not counted
        ]
        assert _count_dead_devices(devices) == 2

    def test_dead_devices_accepts_raw_host_status_field(self):
        """Raw LM API shape uses `hostStatus` not `status`."""
        from lm_mcp.tools.workflows import _count_dead_devices

        devices = [
            {"id": 1, "hostStatus": 1},
            {"id": 2, "hostStatus": 2},
            {"id": 3, "hostStatus": 0},
        ]
        assert _count_dead_devices(devices) == 2

    def test_dead_devices_falls_back_to_alert_status(self):
        """When hostStatus absent, alertStatus strings still flag dead devices."""
        from lm_mcp.tools.workflows import _count_dead_devices

        devices = [
            {"id": 1, "alertStatus": "dead"},
            {"id": 2, "alertStatus": "dead-collector"},
            {"id": 3, "alertStatus": "normal"},
        ]
        assert _count_dead_devices(devices) == 2


# ---------------------------------------------------------------------------
# TestDetectSiteOutage
# ---------------------------------------------------------------------------


class TestDetectSiteOutage:
    """Tests for the detect_site_outage composite."""

    @pytest.fixture(autouse=True)
    def _reset_config(self, monkeypatch):
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-bearer-token-value")
        monkeypatch.delenv("LM_ENABLED_TOOLS", raising=False)
        monkeypatch.delenv("LM_DISABLED_TOOLS", raising=False)
        monkeypatch.delenv("LM_MCP_CATEGORIES", raising=False)
        from lm_mcp.config import reset_config

        reset_config()
        yield
        reset_config()

    async def test_all_signals_trigger_site_outage_detected(self, client):
        """CollectorDown + burst + power + silence → verdict = site_outage_detected.

        Uses the formatted `get_devices` shape (`status`, `collector_id`) that
        the composite actually receives from the sub-tool dispatch.
        """
        from lm_mcp.tools.workflows import detect_site_outage

        devices_data = {"devices": [{"id": i, "status": 1, "collector_id": 1} for i in range(10)]}
        collector_data = {
            "total_collectors": 1,
            "collectors_down": 1,
            "collectors": [{"id": 1, "hostname": "col-01", "is_down": True}],
        }
        burst_data = {
            "bursts_detected": 1,
            "bursts": [{"datasource": "SNMP_Network_Interfaces", "alert_count": 20}],
        }
        power_data = {
            "total_power_events": 3,
            "events": [
                {"id": 1, "datasource": "APC_UPS_Battery"},
                {"id": 2, "datasource": "APC_UPS_Battery"},
                {"id": 3, "datasource": "Liebert_UPS"},
            ],
        }

        with (
            _patch_sub("lm_mcp.tools.devices.get_devices", devices_data),
            _patch_sub("lm_mcp.tools.collectors.get_collector_health", collector_data),
            _patch_sub("lm_mcp.tools.networking.detect_alert_burst", burst_data),
            _patch_sub("lm_mcp.tools.networking.get_power_events", power_data),
        ):
            result = await detect_site_outage(client, group_id=42)

        data = json.loads(result[0].text)
        assert data["verdict"] == "site_outage_detected"
        assert data["confidence"] == 100
        assert data["signals"]["collector_down"]["triggered"] is True
        assert data["signals"]["interface_burst"]["triggered"] is True
        assert data["signals"]["power_events"]["triggered"] is True

    async def test_no_signals_returns_no_outage(self, client):
        """Clean state → verdict = no_outage_signature."""
        from lm_mcp.tools.workflows import detect_site_outage

        devices_data = {"devices": [{"id": 1, "status": 0, "collector_id": 1}]}
        collector_data = {
            "total_collectors": 1,
            "collectors_down": 0,
            "collectors": [{"id": 1, "hostname": "col-01", "is_down": False}],
        }
        burst_data = {"bursts_detected": 0, "bursts": []}
        power_data = {"total_power_events": 0, "events": []}

        with (
            _patch_sub("lm_mcp.tools.devices.get_devices", devices_data),
            _patch_sub("lm_mcp.tools.collectors.get_collector_health", collector_data),
            _patch_sub("lm_mcp.tools.networking.detect_alert_burst", burst_data),
            _patch_sub("lm_mcp.tools.networking.get_power_events", power_data),
        ):
            result = await detect_site_outage(client, group_id=42)

        data = json.loads(result[0].text)
        assert data["verdict"] == "no_outage_signature"
        assert data["confidence"] == 0

    async def test_possible_outage_at_boundary(self, client):
        """Burst + power (no collector down) → 50 confidence → possible_site_outage."""
        from lm_mcp.tools.workflows import detect_site_outage

        devices_data = {"devices": [{"id": 1, "status": 0, "collector_id": 1}]}
        collector_data = {
            "total_collectors": 1,
            "collectors_down": 0,
            "collectors": [{"id": 1, "hostname": "col-01", "is_down": False}],
        }
        burst_data = {"bursts_detected": 1, "bursts": []}
        power_data = {"total_power_events": 2, "events": []}

        with (
            _patch_sub("lm_mcp.tools.devices.get_devices", devices_data),
            _patch_sub("lm_mcp.tools.collectors.get_collector_health", collector_data),
            _patch_sub("lm_mcp.tools.networking.detect_alert_burst", burst_data),
            _patch_sub("lm_mcp.tools.networking.get_power_events", power_data),
        ):
            result = await detect_site_outage(client, group_id=42)

        data = json.loads(result[0].text)
        assert data["verdict"] == "possible_site_outage"
        assert data["confidence"] == 50

    async def test_sub_tool_failure_appends_warning(self, client):
        """Failure in one sub-tool is captured as warning, composite continues."""
        from lm_mcp.tools.workflows import detect_site_outage

        devices_data = {"devices": [{"id": 1, "status": 1, "collector_id": 1}]}

        async def failing_mock(*args, **kwargs):
            raise RuntimeError("sub-tool exploded")

        with (
            _patch_sub("lm_mcp.tools.devices.get_devices", devices_data),
            patch(
                "lm_mcp.tools.collectors.get_collector_health",
                new_callable=AsyncMock,
                side_effect=failing_mock,
            ),
            _patch_sub(
                "lm_mcp.tools.networking.detect_alert_burst",
                {"bursts_detected": 0, "bursts": []},
            ),
            _patch_sub(
                "lm_mcp.tools.networking.get_power_events",
                {"total_power_events": 0, "events": []},
            ),
        ):
            result = await detect_site_outage(client, group_id=42)

        data = json.loads(result[0].text)
        assert len(data["warnings"]) >= 1
        assert any("collector health probes failed" in w for w in data["warnings"])
        assert any("collector_id=1" in w for w in data["warnings"])
        # A failed probe leaves the CollectorDown signal unknown, not untriggered.
        assert data["signals"]["collector_down"]["triggered"] is None
        assert data["signals"]["collector_down"]["status"] == "unavailable"
        assert data["unavailable_signals"] == ["collector_down"]

    async def test_partial_collector_failures_do_not_abort_loop(self, client):
        """One bad collector probe no longer aborts the rest (v3.8.2 fix).

        Composite must continue probing remaining collector IDs and
        surface a single aggregate warning summarizing the failures.
        """
        from mcp.types import TextContent

        from lm_mcp.tools.workflows import detect_site_outage

        devices_data = {
            "devices": [
                {"id": 1, "status": 1, "collector_id": 10},
                {"id": 2, "status": 1, "collector_id": 20},
                {"id": 3, "status": 1, "collector_id": 30},
            ]
        }

        async def selective_health(_client, collector_id, **_kwargs):
            # Collector 20 fails; 10 and 30 succeed.
            if collector_id == 20:
                return [
                    TextContent(
                        type="text",
                        text="Error: collector 20 not found\nSuggestion: Verify ID.",
                    )
                ]
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "total_collectors": 1,
                            "collectors_down": 0,
                            "collectors": [
                                {
                                    "id": collector_id,
                                    "hostname": f"col-{collector_id}",
                                    "is_down": False,
                                }
                            ],
                        }
                    ),
                )
            ]

        with (
            _patch_sub("lm_mcp.tools.devices.get_devices", devices_data),
            patch(
                "lm_mcp.tools.collectors.get_collector_health",
                new_callable=AsyncMock,
                side_effect=selective_health,
            ),
            _patch_sub(
                "lm_mcp.tools.networking.detect_alert_burst",
                {"bursts_detected": 0, "bursts": []},
            ),
            _patch_sub(
                "lm_mcp.tools.networking.get_power_events",
                {"total_power_events": 0, "events": []},
            ),
        ):
            result = await detect_site_outage(client, group_id=42, detail_level="full")

        data = json.loads(result[0].text)
        # Composite kept going past collector 20 and probed 30.
        inspected_ids = [c.get("id") for c in data["collectors_inspected"]]
        assert 10 in inspected_ids
        assert 30 in inspected_ids
        assert 20 not in inspected_ids
        # Warning mentions the failed collector specifically.
        assert any("collector_id=20" in w for w in data["warnings"])
        assert any("1/3" in w for w in data["warnings"])

    @respx.mock
    async def test_failed_burst_read_is_unavailable_not_negative(self, auth):
        """R4.4: a failed burst read is unknown; power alone cannot settle the verdict.

        Power (25) is the only known trigger. Read as untriggered, the lost burst
        signal would have scored 25 and said no_outage_signature; known, it could
        have reached 50, so the verdict cannot be named.
        """
        from lm_mcp.tools.workflows import detect_site_outage

        client = LogicMonitorClient(base_url=_BASE, auth=auth, max_retries=0)
        _mock_site_portal(
            devices=_site_devices(1, "normal"),
            collector_down=_alert_window(),
            burst=_portal_error(),
            power=_alert_window(_power_alert()),
        )

        result = await detect_site_outage(client, group_id=42)

        data = json.loads(result[0].text)
        burst = data["signals"]["interface_burst"]
        assert burst["triggered"] is None
        assert burst["status"] == "unavailable"
        assert "portal unavailable" in burst["error"]
        assert data["signals"]["power_events"] == {"triggered": True, "count": 1, "weight": 25}
        assert data["confidence"] == 25
        assert data["confidence_level"] == "reduced"
        assert data["unavailable_signals"] == ["interface_burst"]
        assert data["verdict"] == "indeterminate"
        assert any("Burst detection failed" in w for w in data["warnings"])

    @respx.mock
    async def test_unavailable_signal_that_cannot_change_the_verdict_keeps_it(self, auth):
        """R4.4: the verdict comes from the signals that read when the lost one cannot move it.

        CollectorDown (40), power (25) and silence (10) score 75; the lost burst
        signal could only raise that, and site_outage_detected starts at 70.
        """
        from lm_mcp.tools.workflows import detect_site_outage

        client = LogicMonitorClient(base_url=_BASE, auth=auth, max_retries=0)
        _mock_site_portal(
            devices=_site_devices(5, "dead"),
            collector_down=_alert_window(
                {"id": 9, "alertType": "CollectorDown", "monitorObjectName": "col-01"}
            ),
            burst=_portal_error(),
            power=_alert_window(_power_alert()),
        )

        result = await detect_site_outage(client, group_id=42)

        data = json.loads(result[0].text)
        assert data["verdict"] == "site_outage_detected"
        assert data["confidence"] == 75
        assert data["confidence_level"] == "reduced"
        assert data["unavailable_signals"] == ["interface_burst"]
        assert data["signals"]["collector_down"]["triggered"] is True

    @respx.mock
    async def test_every_alert_read_failing_is_indeterminate(self, auth):
        """R4.4: with the CollectorDown, burst and power reads all failing, no verdict is named.

        Throttling during an outage fails exactly these reads; before R4.4 the run
        said no_outage_signature.
        """
        from lm_mcp.tools.workflows import detect_site_outage

        client = LogicMonitorClient(base_url=_BASE, auth=auth, max_retries=0)
        _mock_site_portal(
            devices=_site_devices(1, "normal"),
            collector_down=_portal_error(),
            burst=_portal_error(),
            power=_portal_error(),
        )

        result = await detect_site_outage(client, group_id=42)

        data = json.loads(result[0].text)
        assert data["verdict"] == "indeterminate"
        assert data["confidence"] == 0
        assert data["confidence_level"] == "reduced"
        assert data["unavailable_signals"] == [
            "collector_down",
            "interface_burst",
            "power_events",
        ]
        for name in ("collector_down", "interface_burst", "power_events"):
            assert data["signals"][name]["triggered"] is None
            assert data["signals"][name]["status"] == "unavailable"
        assert data["signals"]["device_silence"]["triggered"] is False
        assert not any("No outage signature" in r for r in data["recommendations"])

    @respx.mock
    async def test_all_signals_healthy_output_is_unchanged(self, auth):
        """R4.4: with every read answering, the report carries no unavailable-signal fields."""
        from lm_mcp.tools.workflows import detect_site_outage

        client = LogicMonitorClient(base_url=_BASE, auth=auth, max_retries=0)
        _mock_site_portal(
            devices=_site_devices(1, "normal"),
            collector_down=_alert_window(),
            burst=_alert_window(),
            power=_alert_window(),
        )

        result = await detect_site_outage(client, group_id=42)

        assert json.loads(result[0].text) == {
            "verdict": "no_outage_signature",
            "confidence": 0,
            "group_id": 42,
            "window_seconds": 300,
            "hours_back": 1,
            "scope": {"devices_in_group": 1, "dead_devices": 0, "collectors_serving_group": 1},
            "signals": {
                "collector_down": {"triggered": False, "count": 0},
                "interface_burst": {"triggered": False, "burst_count": 0},
                "power_events": {"triggered": False, "count": 0},
                "device_silence": {"triggered": False, "dead_devices": 0, "threshold": 3},
            },
            "recommendations": [
                "No outage signature detected. If symptoms persist, widen the group scope "
                "or lengthen the hours_back window."
            ],
            "warnings": [],
        }

    async def test_required_tools_disabled_blocks_composite(self, client, monkeypatch):
        """LM_DISABLED_TOOLS matching a required sub-tool blocks execution."""
        from lm_mcp.config import reset_config
        from lm_mcp.tools.workflows import detect_site_outage

        monkeypatch.setenv("LM_DISABLED_TOOLS", "detect_alert_burst")
        reset_config()

        result = await detect_site_outage(client, group_id=42)
        assert "requires disabled tools" in result[0].text
        assert "detect_alert_burst" in result[0].text
        reset_config()


# ---------------------------------------------------------------------------
# TestAuditNetworkMonitoringCoverage
# ---------------------------------------------------------------------------


class TestAuditNetworkMonitoringCoverage:
    """Tests for the audit_network_monitoring_coverage composite."""

    @pytest.fixture(autouse=True)
    def _reset_config(self, monkeypatch):
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-bearer-token-value")
        monkeypatch.delenv("LM_ENABLED_TOOLS", raising=False)
        monkeypatch.delenv("LM_DISABLED_TOOLS", raising=False)
        monkeypatch.delenv("LM_MCP_CATEGORIES", raising=False)
        from lm_mcp.config import reset_config

        reset_config()
        yield
        reset_config()

    async def test_reports_power_gap_when_no_ups_devices(self, client):
        """No UPS/PDU → high-severity power gap."""
        from lm_mcp.tools.workflows import audit_network_monitoring_coverage

        devices_data = {
            "devices": [
                {
                    "id": 1,
                    "displayName": "core-switch-01",
                    "systemCategories": "switch,network",
                    "customProperties": [{"name": "snmp.version", "value": "v2c"}],
                },
                {
                    "id": 2,
                    "displayName": "core-switch-02",
                    "systemCategories": "switch,network",
                    "customProperties": [{"name": "snmp.version", "value": "v2c"}],
                },
            ]
        }
        collectors_data = {"collectors": [{"id": 1, "hostname": "col-01", "status": "normal"}]}

        with (
            _patch_sub("lm_mcp.tools.devices.get_devices", devices_data),
            _patch_sub("lm_mcp.tools.collectors.get_collectors", collectors_data),
        ):
            result = await audit_network_monitoring_coverage(client, group_id=1)

        data = json.loads(result[0].text)
        power_gaps = [g for g in data["gaps"] if g["category"] == "power"]
        assert len(power_gaps) == 1
        assert power_gaps[0]["severity"] == "high"
        assert data["inventory"]["total_devices"] == 2
        assert data["coverage_counts"]["snmp_credentialed"] == 2

    async def test_flags_missing_netflow_exporters(self, client):
        """No NetFlow exporters on network gear → medium netflow gap."""
        from lm_mcp.tools.workflows import audit_network_monitoring_coverage

        devices_data = {
            "devices": [
                {
                    "id": 1,
                    "displayName": "router-01",
                    "systemCategories": "router",
                    "customProperties": [{"name": "snmp.version", "value": "v2c"}],
                }
            ]
        }
        collectors_data = {"collectors": [{"id": 1, "status": "normal"}]}

        with (
            _patch_sub("lm_mcp.tools.devices.get_devices", devices_data),
            _patch_sub("lm_mcp.tools.collectors.get_collectors", collectors_data),
        ):
            result = await audit_network_monitoring_coverage(client)

        data = json.loads(result[0].text)
        netflow_gaps = [g for g in data["gaps"] if g["category"] == "netflow"]
        assert len(netflow_gaps) == 1

    async def test_power_coverage_healthy_when_ups_present(self, client):
        """UPS device present → no power gap."""
        from lm_mcp.tools.workflows import audit_network_monitoring_coverage

        devices_data = {
            "devices": [
                {
                    "id": 1,
                    "displayName": "ups-01",
                    "systemCategories": "ups",
                    "customProperties": [],
                }
            ]
        }
        collectors_data = {"collectors": [{"id": 1, "status": "normal"}]}

        with (
            _patch_sub("lm_mcp.tools.devices.get_devices", devices_data),
            _patch_sub("lm_mcp.tools.collectors.get_collectors", collectors_data),
        ):
            result = await audit_network_monitoring_coverage(client)

        data = json.loads(result[0].text)
        assert data["coverage_counts"]["power_monitored_devices"] == 1
        power_gaps = [g for g in data["gaps"] if g["category"] == "power"]
        assert power_gaps == []

    async def test_critical_when_no_collectors(self, client):
        """Zero collectors → critical gap."""
        from lm_mcp.tools.workflows import audit_network_monitoring_coverage

        devices_data = {"devices": []}
        collectors_data = {"collectors": []}

        with (
            _patch_sub("lm_mcp.tools.devices.get_devices", devices_data),
            _patch_sub("lm_mcp.tools.collectors.get_collectors", collectors_data),
        ):
            result = await audit_network_monitoring_coverage(client)

        data = json.loads(result[0].text)
        critical = [g for g in data["gaps"] if g["severity"] == "critical"]
        assert len(critical) == 1
        assert critical[0]["category"] == "collectors"
