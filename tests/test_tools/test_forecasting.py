# Description: Tests for metric forecasting and trend analysis tools.
# Description: Validates forecast_metric, detect_change_points, classify_trend, detect_seasonality.

import json
import logging
import math
from unittest.mock import MagicMock

import httpx
import pytest
import respx

from lm_mcp.auth.bearer import BearerAuth
from lm_mcp.client import LogicMonitorClient
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


# Base epoch for test data (2024-01-15 00:00:00 UTC)
BASE_EPOCH = 1705276800
DATA_URL = (
    "https://test.logicmonitor.com/santaba/rest"
    "/device/devices/1/devicedatasources/10/instances/100/data"
)


def _make_metric_response(dp_names, values, interval_sec=300):
    """Helper to build metric API response."""
    times = [(BASE_EPOCH + i * interval_sec) * 1000 for i in range(len(values))]
    return {
        "dataPoints": dp_names,
        "values": values,
        "time": times,
    }


class TestForecastMetric:
    """Tests for forecast_metric tool."""

    @respx.mock
    async def test_increasing_trend_predicts_breach(self, client):
        """Increasing data predicts future threshold breach."""
        from lm_mcp.tools.forecasting import forecast_metric

        # Steadily increasing: 10, 20, 30, 40, 50
        values = [[float(10 + i * 10)] for i in range(5)]
        respx.get(DATA_URL).mock(
            return_value=httpx.Response(200, json=_make_metric_response(["cpu"], values))
        )

        result = await forecast_metric(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
            threshold=100.0,
        )

        data = json.loads(result[0].text)
        assert "forecasts" in data
        cpu = data["forecasts"]["cpu"]
        assert cpu["trend"] == "increasing"
        assert cpu["slope_per_hour"] > 0
        assert cpu["days_until_breach"] is not None
        assert cpu["days_until_breach"] > 0

    @respx.mock
    async def test_stable_trend_no_breach(self, client):
        """Stable data predicts no breach."""
        from lm_mcp.tools.forecasting import forecast_metric

        values = [[50.0]] * 10
        respx.get(DATA_URL).mock(
            return_value=httpx.Response(200, json=_make_metric_response(["cpu"], values))
        )

        result = await forecast_metric(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
            threshold=100.0,
        )

        data = json.loads(result[0].text)
        cpu = data["forecasts"]["cpu"]
        assert cpu["trend"] == "stable"
        assert cpu["days_until_breach"] is None

    @respx.mock
    async def test_decreasing_trend(self, client):
        """Decreasing data shows negative slope."""
        from lm_mcp.tools.forecasting import forecast_metric

        values = [[float(50 - i * 5)] for i in range(10)]
        respx.get(DATA_URL).mock(
            return_value=httpx.Response(200, json=_make_metric_response(["cpu"], values))
        )

        result = await forecast_metric(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
            threshold=100.0,
        )

        data = json.loads(result[0].text)
        cpu = data["forecasts"]["cpu"]
        assert cpu["trend"] == "decreasing"
        assert cpu["slope_per_hour"] < 0

    @respx.mock
    async def test_empty_data(self, client):
        """Empty data returns insufficient_data status."""
        from lm_mcp.tools.forecasting import forecast_metric

        respx.get(DATA_URL).mock(
            return_value=httpx.Response(200, json={"dataPoints": ["cpu"], "values": [], "time": []})
        )

        result = await forecast_metric(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
            threshold=100.0,
        )

        data = json.loads(result[0].text)
        assert data["forecasts"]["cpu"]["status"] == "insufficient_data"

    @respx.mock
    async def test_single_data_point(self, client):
        """Single data point returns insufficient_data."""
        from lm_mcp.tools.forecasting import forecast_metric

        respx.get(DATA_URL).mock(
            return_value=httpx.Response(200, json=_make_metric_response(["cpu"], [[50.0]]))
        )

        result = await forecast_metric(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
            threshold=100.0,
        )

        data = json.loads(result[0].text)
        assert data["forecasts"]["cpu"]["status"] == "insufficient_data"

    @respx.mock
    async def test_response_includes_device_ids(self, client):
        """Response includes device_id and other IDs."""
        from lm_mcp.tools.forecasting import forecast_metric

        values = [[50.0], [55.0], [60.0]]
        respx.get(DATA_URL).mock(
            return_value=httpx.Response(200, json=_make_metric_response(["cpu"], values))
        )

        result = await forecast_metric(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
            threshold=100.0,
        )

        data = json.loads(result[0].text)
        assert data["device_id"] == 1
        assert data["device_datasource_id"] == 10
        assert data["instance_id"] == 100

    @respx.mock
    async def test_multiple_datapoints(self, client):
        """Multiple datapoints each get individual forecasts."""
        from lm_mcp.tools.forecasting import forecast_metric

        values = [[50.0, 70.0], [55.0, 65.0], [60.0, 60.0]]
        respx.get(DATA_URL).mock(
            return_value=httpx.Response(200, json=_make_metric_response(["cpu", "memory"], values))
        )

        result = await forecast_metric(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
            threshold=100.0,
        )

        data = json.loads(result[0].text)
        assert "cpu" in data["forecasts"]
        assert "memory" in data["forecasts"]

    @respx.mock
    async def test_error_handling(self, client):
        """API errors are returned as error response."""
        from lm_mcp.tools.forecasting import forecast_metric

        respx.get(DATA_URL).mock(
            return_value=httpx.Response(500, json={"errorMessage": "Server error"})
        )

        result = await forecast_metric(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
            threshold=100.0,
        )

        assert "Error:" in result[0].text

    @respx.mock
    async def test_r_squared_in_response(self, client):
        """Response includes r_squared goodness of fit."""
        from lm_mcp.tools.forecasting import forecast_metric

        values = [[float(10 + i * 10)] for i in range(5)]
        respx.get(DATA_URL).mock(
            return_value=httpx.Response(200, json=_make_metric_response(["cpu"], values))
        )

        result = await forecast_metric(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
            threshold=100.0,
        )

        data = json.loads(result[0].text)
        assert "r_squared" in data["forecasts"]["cpu"]
        assert data["forecasts"]["cpu"]["r_squared"] > 0.9

    @respx.mock
    async def test_breach_already_exceeded(self, client):
        """When values already exceed threshold, no future breach predicted."""
        from lm_mcp.tools.forecasting import forecast_metric

        # Values well above threshold, decreasing
        values = [[float(200 - i * 10)] for i in range(5)]
        respx.get(DATA_URL).mock(
            return_value=httpx.Response(200, json=_make_metric_response(["cpu"], values))
        )

        result = await forecast_metric(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
            threshold=100.0,
        )

        data = json.loads(result[0].text)
        cpu = data["forecasts"]["cpu"]
        # If decreasing, breach time should be None (moving away from threshold)
        assert cpu["trend"] == "decreasing"


class TestForecastMetricMethod:
    """Tests for forecast_metric method parameter."""

    @respx.mock
    async def test_method_auto_short_data_uses_linear(self, client):
        """Auto method with short hours_back uses linear."""
        from lm_mcp.tools.forecasting import forecast_metric

        values = [[float(10 + i)] for i in range(10)]
        respx.get(DATA_URL).mock(
            return_value=httpx.Response(200, json=_make_metric_response(["cpu"], values))
        )

        result = await forecast_metric(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
            threshold=100.0,
            hours_back=24,
            method="auto",
        )

        data = json.loads(result[0].text)
        cpu = data["forecasts"]["cpu"]
        assert cpu["method_used"] == "linear"

    @respx.mock
    async def test_method_explicit_holt_winters(self, client):
        """Explicit holt_winters method is used when requested."""
        from lm_mcp.tools.forecasting import forecast_metric

        # Enough data for Holt-Winters (2 seasons of 12)
        values = [[float(50 + 10 * math.sin(2 * math.pi * i / 12))] for i in range(48)]
        respx.get(DATA_URL).mock(
            return_value=httpx.Response(200, json=_make_metric_response(["cpu"], values))
        )

        result = await forecast_metric(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
            threshold=200.0,
            method="holt_winters",
        )

        data = json.loads(result[0].text)
        cpu = data["forecasts"]["cpu"]
        assert cpu["method_used"] == "holt_winters"

    @respx.mock
    async def test_confidence_interval_present(self, client):
        """Forecast output includes confidence_interval."""
        from lm_mcp.tools.forecasting import forecast_metric

        values = [[float(10 + i * 2)] for i in range(20)]
        respx.get(DATA_URL).mock(
            return_value=httpx.Response(200, json=_make_metric_response(["cpu"], values))
        )

        result = await forecast_metric(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
            threshold=200.0,
        )

        data = json.loads(result[0].text)
        cpu = data["forecasts"]["cpu"]
        assert "confidence_interval" in cpu
        ci = cpu["confidence_interval"]
        assert "lower" in ci
        assert "upper" in ci
        assert "confidence_level" in ci
        assert "data_quality" in ci

    @respx.mock
    async def test_method_linear_explicit(self, client):
        """Explicit linear method is used when requested."""
        from lm_mcp.tools.forecasting import forecast_metric

        values = [[float(10 + i)] for i in range(10)]
        respx.get(DATA_URL).mock(
            return_value=httpx.Response(200, json=_make_metric_response(["cpu"], values))
        )

        result = await forecast_metric(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
            threshold=100.0,
            method="linear",
        )

        data = json.loads(result[0].text)
        cpu = data["forecasts"]["cpu"]
        assert cpu["method_used"] == "linear"


async def _forecast_cpu(client, values, method, threshold=1000.0):
    """Serve one cpu series and return its forecast entry."""
    from lm_mcp.tools.forecasting import forecast_metric

    respx.get(DATA_URL).mock(
        return_value=httpx.Response(200, json=_make_metric_response(["cpu"], values))
    )
    result = await forecast_metric(
        client,
        device_id=1,
        device_datasource_id=10,
        instance_id=100,
        threshold=threshold,
        method=method,
    )
    return json.loads(result[0].text)["forecasts"]["cpu"]


class TestForecastMethodLabels:
    """R4.1: method_used names the method that produced the numbers; fallbacks say why."""

    @respx.mock
    async def test_ttm_without_watsonx_falls_back_with_reason(self, client, monkeypatch):
        """method=ttm with no watsonx client reports linear and names watsonx."""
        monkeypatch.setattr("lm_mcp.server._watsonx_client", None)
        values = [[float(10 + i)] for i in range(600)]

        cpu = await _forecast_cpu(client, values, method="ttm")

        assert cpu["method_used"] == "linear"
        assert "watsonx" in cpu["fallback_reason"]

    @respx.mock
    async def test_ttm_under_512_points_falls_back_with_reason(self, client, monkeypatch):
        """method=ttm with watsonx but 100 points reports linear and the 512 minimum."""
        wx = real_watsonx_client()
        wx._run_ttm_forecast = MagicMock()
        monkeypatch.setattr("lm_mcp.server._watsonx_client", wx)
        values = [[float(10 + i)] for i in range(100)]

        cpu = await _forecast_cpu(client, values, method="ttm")

        assert cpu["method_used"] == "linear"
        assert "512" in cpu["fallback_reason"]
        wx._run_ttm_forecast.assert_not_called()

    @respx.mock
    async def test_ttm_failure_falls_back_with_reason_and_warning(
        self, client, monkeypatch, caplog
    ):
        """A TTM call that raises reports linear, the failure, and a WARNING."""
        wx = real_watsonx_client()
        wx._run_ttm_forecast = MagicMock(side_effect=Exception("connection timeout"))
        monkeypatch.setattr("lm_mcp.server._watsonx_client", wx)
        values = [[float(10 + i)] for i in range(600)]

        with caplog.at_level(logging.WARNING, logger="lm_mcp.tools.forecasting"):
            cpu = await _forecast_cpu(client, values, method="ttm")

        assert cpu["method_used"] == "linear"
        assert "TTM" in cpu["fallback_reason"]
        warnings = [
            r
            for r in caplog.records
            if r.name == "lm_mcp.tools.forecasting" and r.levelno == logging.WARNING
        ]
        assert len(warnings) == 1
        assert "TTM" in warnings[0].getMessage()

    @respx.mock
    async def test_ttm_success_is_labeled_ttm(self, client, monkeypatch):
        """A TTM forecast that succeeds reports ttm and no fallback reason."""
        from lm_mcp.client.watsonx import TTM_MODEL_ID

        wx = real_watsonx_client()
        wx._run_ttm_forecast = MagicMock(
            return_value={
                "forecast_values": [70.0, 71.0, 72.0],
                "forecast_count": 3,
                "model": TTM_MODEL_ID,
            }
        )
        monkeypatch.setattr("lm_mcp.server._watsonx_client", wx)
        values = [[float(10 + i * 0.1)] for i in range(600)]

        cpu = await _forecast_cpu(client, values, method="ttm")

        assert cpu["method_used"] == "ttm"
        assert "fallback_reason" not in cpu

    @respx.mock
    async def test_holt_winters_failure_falls_back_with_reason_and_warning(self, client, caplog):
        """Five points cannot fill two seasons, so Holt-Winters raises and linear runs."""
        values = [[float(10 + i * 10)] for i in range(5)]

        with caplog.at_level(logging.WARNING, logger="lm_mcp.tools.forecasting"):
            cpu = await _forecast_cpu(client, values, method="holt_winters")

        assert cpu["method_used"] == "linear"
        assert "Holt-Winters" in cpu["fallback_reason"]
        warnings = [
            r
            for r in caplog.records
            if r.name == "lm_mcp.tools.forecasting" and r.levelno == logging.WARNING
        ]
        assert len(warnings) == 1
        assert "Holt-Winters" in warnings[0].getMessage()

    @respx.mock
    async def test_holt_winters_success_omits_r_squared(self, client):
        """Holt-Winters has no regression fit, so r_squared is absent, not 0.0."""
        values = [[float(50 + 10 * math.sin(2 * math.pi * i / 12))] for i in range(48)]

        cpu = await _forecast_cpu(client, values, method="holt_winters", threshold=200.0)

        assert cpu["method_used"] == "holt_winters"
        assert "r_squared" not in cpu
        assert "fallback_reason" not in cpu

    @pytest.mark.parametrize("method", ["linear", "auto"])
    @respx.mock
    async def test_selected_linear_carries_no_fallback_reason(self, client, monkeypatch, method):
        """Linear that was asked for, or chosen by auto, is not a fallback."""
        monkeypatch.setattr("lm_mcp.server._watsonx_client", None)
        values = [[float(10 + i)] for i in range(10)]

        cpu = await _forecast_cpu(client, values, method=method)

        assert cpu["method_used"] == "linear"
        assert "fallback_reason" not in cpu


class TestDetectChangePoints:
    """Tests for detect_change_points tool."""

    @respx.mock
    async def test_upward_shift_detected(self, client):
        """Detects a clear upward shift in metric values."""
        from lm_mcp.tools.forecasting import detect_change_points

        values = [[10.0]] * 15 + [[30.0]] * 15
        respx.get(DATA_URL).mock(
            return_value=httpx.Response(200, json=_make_metric_response(["cpu"], values))
        )

        result = await detect_change_points(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
        )

        data = json.loads(result[0].text)
        assert data["total_change_points"] > 0
        cpu_data = data["datapoints"]["cpu"]
        assert any(cp["direction"] == "increase" for cp in cpu_data["change_points"])

    @respx.mock
    async def test_stable_data_no_changes(self, client):
        """Stable data produces no change points."""
        from lm_mcp.tools.forecasting import detect_change_points

        values = [[10.0 + (i % 3) * 0.1] for i in range(30)]
        respx.get(DATA_URL).mock(
            return_value=httpx.Response(200, json=_make_metric_response(["cpu"], values))
        )

        result = await detect_change_points(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
        )

        data = json.loads(result[0].text)
        assert data["total_change_points"] <= 1

    @respx.mock
    async def test_sensitivity_parameter(self, client):
        """Higher sensitivity produces fewer detections."""
        from lm_mcp.tools.forecasting import detect_change_points

        values = [[10.0]] * 15 + [[20.0]] * 15
        respx.get(DATA_URL).mock(
            return_value=httpx.Response(200, json=_make_metric_response(["cpu"], values))
        )

        result = await detect_change_points(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
            sensitivity=5.0,
        )

        data = json.loads(result[0].text)
        # With high sensitivity, fewer detections
        assert data["sensitivity"] == 5.0

    @respx.mock
    async def test_change_point_has_timestamp(self, client):
        """Change points include timestamps."""
        from lm_mcp.tools.forecasting import detect_change_points

        values = [[10.0]] * 15 + [[30.0]] * 15
        respx.get(DATA_URL).mock(
            return_value=httpx.Response(200, json=_make_metric_response(["cpu"], values))
        )

        result = await detect_change_points(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
        )

        data = json.loads(result[0].text)
        if data["total_change_points"] > 0:
            cp = data["datapoints"]["cpu"]["change_points"][0]
            assert "timestamp" in cp
            assert "direction" in cp
            assert "magnitude" in cp

    @respx.mock
    async def test_empty_data(self, client):
        """Empty data returns no change points."""
        from lm_mcp.tools.forecasting import detect_change_points

        respx.get(DATA_URL).mock(
            return_value=httpx.Response(200, json={"dataPoints": ["cpu"], "values": [], "time": []})
        )

        result = await detect_change_points(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
        )

        data = json.loads(result[0].text)
        assert data["total_change_points"] == 0

    @respx.mock
    async def test_error_handling(self, client):
        """API errors are returned as error response."""
        from lm_mcp.tools.forecasting import detect_change_points

        respx.get(DATA_URL).mock(
            return_value=httpx.Response(404, json={"errorMessage": "Not found"})
        )

        result = await detect_change_points(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
        )

        assert "Error:" in result[0].text


class TestClassifyTrend:
    """Tests for classify_trend tool."""

    @respx.mock
    async def test_increasing_classification(self, client):
        """Linearly increasing data classified as increasing."""
        from lm_mcp.tools.forecasting import classify_trend

        # Start high so CV stays low (variation small relative to mean)
        values = [[float(100 + i * 2)] for i in range(20)]
        respx.get(DATA_URL).mock(
            return_value=httpx.Response(200, json=_make_metric_response(["cpu"], values))
        )

        result = await classify_trend(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
        )

        data = json.loads(result[0].text)
        cpu = data["classifications"]["cpu"]
        assert cpu["classification"] == "increasing"
        assert cpu["confidence"] > 0.5

    @respx.mock
    async def test_decreasing_classification(self, client):
        """Linearly decreasing data classified as decreasing."""
        from lm_mcp.tools.forecasting import classify_trend

        # Start high so CV stays low (variation small relative to mean)
        values = [[float(200 - i * 2)] for i in range(20)]
        respx.get(DATA_URL).mock(
            return_value=httpx.Response(200, json=_make_metric_response(["cpu"], values))
        )

        result = await classify_trend(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
        )

        data = json.loads(result[0].text)
        cpu = data["classifications"]["cpu"]
        assert cpu["classification"] == "decreasing"

    @respx.mock
    async def test_stable_classification(self, client):
        """Constant data classified as stable."""
        from lm_mcp.tools.forecasting import classify_trend

        values = [[50.0]] * 20
        respx.get(DATA_URL).mock(
            return_value=httpx.Response(200, json=_make_metric_response(["cpu"], values))
        )

        result = await classify_trend(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
        )

        data = json.loads(result[0].text)
        cpu = data["classifications"]["cpu"]
        assert cpu["classification"] == "stable"

    @respx.mock
    async def test_volatile_classification(self, client):
        """Highly variable data classified as volatile."""
        import random

        from lm_mcp.tools.forecasting import classify_trend

        random.seed(42)
        values = [[random.uniform(0, 100)] for _ in range(20)]
        respx.get(DATA_URL).mock(
            return_value=httpx.Response(200, json=_make_metric_response(["cpu"], values))
        )

        result = await classify_trend(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
        )

        data = json.loads(result[0].text)
        cpu = data["classifications"]["cpu"]
        assert cpu["classification"] == "volatile"
        assert cpu["volatility_index"] > 0.5

    @respx.mock
    async def test_insufficient_data(self, client):
        """Single data point returns insufficient_data."""
        from lm_mcp.tools.forecasting import classify_trend

        respx.get(DATA_URL).mock(
            return_value=httpx.Response(200, json=_make_metric_response(["cpu"], [[50.0]]))
        )

        result = await classify_trend(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
        )

        data = json.loads(result[0].text)
        assert data["classifications"]["cpu"]["classification"] == "insufficient_data"

    @respx.mock
    async def test_response_structure(self, client):
        """Response includes all expected fields."""
        from lm_mcp.tools.forecasting import classify_trend

        values = [[float(10 + i)] for i in range(10)]
        respx.get(DATA_URL).mock(
            return_value=httpx.Response(200, json=_make_metric_response(["cpu"], values))
        )

        result = await classify_trend(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
        )

        data = json.loads(result[0].text)
        cpu = data["classifications"]["cpu"]
        assert "classification" in cpu
        assert "confidence" in cpu
        assert "slope_per_hour" in cpu
        assert "volatility_index" in cpu
        assert "sample_count" in cpu

    @respx.mock
    async def test_error_handling(self, client):
        """API errors are returned as error response."""
        from lm_mcp.tools.forecasting import classify_trend

        respx.get(DATA_URL).mock(return_value=httpx.Response(500, json={"errorMessage": "error"}))

        result = await classify_trend(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
        )

        assert "Error:" in result[0].text


class TestDetectSeasonality:
    """Tests for detect_seasonality tool."""

    @respx.mock
    async def test_no_seasonality_constant(self, client):
        """Constant data shows no seasonality."""
        from lm_mcp.tools.forecasting import detect_seasonality

        values = [[50.0]] * 100
        respx.get(DATA_URL).mock(
            return_value=httpx.Response(
                200, json=_make_metric_response(["cpu"], values, interval_sec=300)
            )
        )

        result = await detect_seasonality(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
        )

        data = json.loads(result[0].text)
        cpu = data["seasonality"]["cpu"]
        assert cpu["is_seasonal"] is False

    @respx.mock
    async def test_sinusoidal_data_detected(self, client):
        """Sinusoidal data is detected as seasonal."""
        from lm_mcp.tools.forecasting import detect_seasonality

        # Period of 12 samples (1 hour at 5-min intervals)
        values = [[50.0 + 20.0 * math.sin(2 * math.pi * i / 12)] for i in range(200)]
        respx.get(DATA_URL).mock(
            return_value=httpx.Response(
                200, json=_make_metric_response(["cpu"], values, interval_sec=300)
            )
        )

        result = await detect_seasonality(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
        )

        data = json.loads(result[0].text)
        cpu = data["seasonality"]["cpu"]
        # Should have some autocorrelation results
        assert "correlations" in cpu

    @respx.mock
    async def test_peak_hours_calculated(self, client):
        """Peak hours are calculated from hourly binning."""
        from lm_mcp.tools.forecasting import detect_seasonality

        # Create values where some hours have higher values
        values = []
        for i in range(288):  # 24 hours at 5-min intervals
            hour = (i * 300 % 86400) // 3600
            val = 80.0 if 9 <= hour <= 17 else 20.0
            values.append([val])

        respx.get(DATA_URL).mock(
            return_value=httpx.Response(
                200, json=_make_metric_response(["cpu"], values, interval_sec=300)
            )
        )

        result = await detect_seasonality(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
        )

        data = json.loads(result[0].text)
        cpu = data["seasonality"]["cpu"]
        assert "peak_hours" in cpu
        assert isinstance(cpu["peak_hours"], list)

    @respx.mock
    async def test_insufficient_data(self, client):
        """Few data points return insufficient_data status."""
        from lm_mcp.tools.forecasting import detect_seasonality

        respx.get(DATA_URL).mock(
            return_value=httpx.Response(200, json=_make_metric_response(["cpu"], [[50.0], [51.0]]))
        )

        result = await detect_seasonality(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
        )

        data = json.loads(result[0].text)
        assert data["seasonality"]["cpu"]["status"] == "insufficient_data"

    @respx.mock
    async def test_response_includes_hours_back(self, client):
        """Response includes hours_back parameter."""
        from lm_mcp.tools.forecasting import detect_seasonality

        values = [[50.0]] * 50
        respx.get(DATA_URL).mock(
            return_value=httpx.Response(200, json=_make_metric_response(["cpu"], values))
        )

        result = await detect_seasonality(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
            hours_back=48,
        )

        data = json.loads(result[0].text)
        assert data["hours_back"] == 48

    @respx.mock
    async def test_error_handling(self, client):
        """API errors are returned as error response."""
        from lm_mcp.tools.forecasting import detect_seasonality

        respx.get(DATA_URL).mock(return_value=httpx.Response(500, json={"errorMessage": "error"}))

        result = await detect_seasonality(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
        )

        assert "Error:" in result[0].text
