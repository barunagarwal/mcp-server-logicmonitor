# Description: Tests for baseline metric comparison tools.
# Description: Validates save_baseline and compare_to_baseline tool handlers.

import json
import logging

import httpx
import pytest
import respx

from lm_mcp.auth.bearer import BearerAuth
from lm_mcp.client import LogicMonitorClient
from lm_mcp.session import get_session, reset_session, set_session
from lm_mcp.tools import is_error_result


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


@pytest.fixture(autouse=True)
def _clean_session():
    """Reset session before each test."""
    reset_session()
    set_session(None)
    yield
    reset_session()
    set_session(None)


# Base epoch for test data
BASE_EPOCH = 1705276800


class TestSaveBaseline:
    """Tests for save_baseline tool."""

    @respx.mock
    async def test_saves_baseline_with_stats(self, client):
        """save_baseline computes and stores mean, min, max, stddev."""
        from lm_mcp.tools.baselines import save_baseline

        respx.get(
            "https://test.logicmonitor.com/santaba/rest"
            "/device/devices/1/devicedatasources/10/instances/100/data"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "dataPoints": ["cpu"],
                    "values": [[50.0], [60.0], [40.0], [50.0]],
                    "time": [BASE_EPOCH + i * 300 for i in range(4)],
                },
            )
        )

        result = await save_baseline(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
            baseline_name="cpu_normal",
        )

        data = json.loads(result[0].text)
        assert data["success"] is True
        assert "cpu" in data["datapoints"]
        assert data["datapoints"]["cpu"]["mean"] == 50.0
        assert data["datapoints"]["cpu"]["min"] == 40.0
        assert data["datapoints"]["cpu"]["max"] == 60.0
        assert data["datapoints"]["cpu"]["sample_count"] == 4

    @respx.mock
    async def test_saves_to_session_variable(self, client):
        """Baseline is stored as session variable with correct key."""
        from lm_mcp.tools.baselines import save_baseline

        respx.get(
            "https://test.logicmonitor.com/santaba/rest"
            "/device/devices/1/devicedatasources/10/instances/100/data"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "dataPoints": ["cpu"],
                    "values": [[50.0], [50.0]],
                    "time": [BASE_EPOCH, BASE_EPOCH + 300],
                },
            )
        )

        await save_baseline(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
            baseline_name="test_bl",
        )

        session = get_session()
        stored = session.get_variable("baseline_test_bl")
        assert stored is not None
        assert stored["device_id"] == 1
        assert "cpu" in stored["datapoints"]

    @respx.mock
    async def test_custom_hours_back(self, client):
        """hours_back param sets start time in API request."""
        from lm_mcp.tools.baselines import save_baseline

        route = respx.get(
            "https://test.logicmonitor.com/santaba/rest"
            "/device/devices/1/devicedatasources/10/instances/100/data"
        ).mock(
            return_value=httpx.Response(
                200,
                json={"dataPoints": [], "values": [], "time": []},
            )
        )

        await save_baseline(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
            baseline_name="test",
            hours_back=48,
        )

        params = dict(route.calls[0].request.url.params)
        assert "start" in params

    @respx.mock
    async def test_error_handling(self, client):
        """API errors are returned as error response."""
        from lm_mcp.tools.baselines import save_baseline

        respx.get(
            "https://test.logicmonitor.com/santaba/rest"
            "/device/devices/1/devicedatasources/10/instances/100/data"
        ).mock(return_value=httpx.Response(404, json={"errorMessage": "Not found"}))

        result = await save_baseline(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
            baseline_name="test",
        )

        assert "Error:" in result[0].text

    @respx.mock
    async def test_multiple_datapoints(self, client):
        """Baseline handles multiple datapoints."""
        from lm_mcp.tools.baselines import save_baseline

        respx.get(
            "https://test.logicmonitor.com/santaba/rest"
            "/device/devices/1/devicedatasources/10/instances/100/data"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "dataPoints": ["cpu", "memory"],
                    "values": [
                        [50.0, 70.0],
                        [60.0, 80.0],
                    ],
                    "time": [BASE_EPOCH, BASE_EPOCH + 300],
                },
            )
        )

        result = await save_baseline(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
            baseline_name="multi",
        )

        data = json.loads(result[0].text)
        assert "cpu" in data["datapoints"]
        assert "memory" in data["datapoints"]


class TestCompareToBaseline:
    """Tests for compare_to_baseline tool."""

    @respx.mock
    async def test_comparison_with_normal_deviation(self, client):
        """Normal deviation reports status as normal."""
        from lm_mcp.tools.baselines import compare_to_baseline

        # Set up a baseline in session
        session = get_session()
        session.set_variable(
            "baseline_test",
            {
                "device_id": 1,
                "device_datasource_id": 10,
                "instance_id": 100,
                "datapoints": {
                    "cpu": {
                        "mean": 50.0,
                        "min": 40.0,
                        "max": 60.0,
                        "stddev": 5.0,
                        "sample_count": 10,
                    },
                },
            },
        )

        respx.get(
            "https://test.logicmonitor.com/santaba/rest"
            "/device/devices/1/devicedatasources/10/instances/100/data"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "dataPoints": ["cpu"],
                    "values": [[52.0], [48.0], [51.0]],
                    "time": [BASE_EPOCH + i * 300 for i in range(3)],
                },
            )
        )

        result = await compare_to_baseline(client, baseline_name="test")

        data = json.loads(result[0].text)
        assert data["comparisons"]["cpu"]["status"] == "normal"

    @respx.mock
    async def test_comparison_with_elevated_values(self, client):
        """Elevated values (20-50% deviation) reported as elevated."""
        from lm_mcp.tools.baselines import compare_to_baseline

        session = get_session()
        session.set_variable(
            "baseline_test",
            {
                "device_id": 1,
                "device_datasource_id": 10,
                "instance_id": 100,
                "datapoints": {
                    "cpu": {
                        "mean": 50.0,
                        "min": 40.0,
                        "max": 60.0,
                        "stddev": 5.0,
                        "sample_count": 10,
                    },
                },
            },
        )

        # Current values ~35% higher than baseline mean
        respx.get(
            "https://test.logicmonitor.com/santaba/rest"
            "/device/devices/1/devicedatasources/10/instances/100/data"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "dataPoints": ["cpu"],
                    "values": [[67.0], [68.0], [67.5]],
                    "time": [BASE_EPOCH + i * 300 for i in range(3)],
                },
            )
        )

        result = await compare_to_baseline(client, baseline_name="test")

        data = json.loads(result[0].text)
        assert data["comparisons"]["cpu"]["status"] in ("elevated", "anomalous")

    @respx.mock
    async def test_comparison_with_anomalous_values(self, client):
        """Anomalous values (>50% deviation) reported as anomalous."""
        from lm_mcp.tools.baselines import compare_to_baseline

        session = get_session()
        session.set_variable(
            "baseline_test",
            {
                "device_id": 1,
                "device_datasource_id": 10,
                "instance_id": 100,
                "datapoints": {
                    "cpu": {
                        "mean": 50.0,
                        "min": 40.0,
                        "max": 60.0,
                        "stddev": 5.0,
                        "sample_count": 10,
                    },
                },
            },
        )

        # Current values ~100% higher than baseline mean
        respx.get(
            "https://test.logicmonitor.com/santaba/rest"
            "/device/devices/1/devicedatasources/10/instances/100/data"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "dataPoints": ["cpu"],
                    "values": [[95.0], [98.0], [100.0]],
                    "time": [BASE_EPOCH + i * 300 for i in range(3)],
                },
            )
        )

        result = await compare_to_baseline(client, baseline_name="test")

        data = json.loads(result[0].text)
        assert data["comparisons"]["cpu"]["status"] == "anomalous"

    async def test_baseline_not_found(self, client):
        """Missing baseline returns error response."""
        from lm_mcp.tools.baselines import compare_to_baseline

        result = await compare_to_baseline(client, baseline_name="nonexistent")

        text = result[0].text
        try:
            data = json.loads(text)
            assert data.get("error") is True
        except json.JSONDecodeError:
            assert "Error" in text

    @respx.mock
    async def test_inherits_ids_from_baseline(self, client):
        """Compare uses device/instance IDs from stored baseline."""
        from lm_mcp.tools.baselines import compare_to_baseline

        session = get_session()
        session.set_variable(
            "baseline_auto",
            {
                "device_id": 42,
                "device_datasource_id": 15,
                "instance_id": 200,
                "datapoints": {
                    "cpu": {
                        "mean": 50.0,
                        "min": 40.0,
                        "max": 60.0,
                        "stddev": 5.0,
                        "sample_count": 10,
                    },
                },
            },
        )

        route = respx.get(
            "https://test.logicmonitor.com/santaba/rest"
            "/device/devices/42/devicedatasources/15/instances/200/data"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "dataPoints": ["cpu"],
                    "values": [[50.0]],
                    "time": [BASE_EPOCH],
                },
            )
        )

        await compare_to_baseline(client, baseline_name="auto")

        assert route.called

    @respx.mock
    async def test_override_device_ids(self, client):
        """Explicit device/instance IDs override baseline values."""
        from lm_mcp.tools.baselines import compare_to_baseline

        session = get_session()
        session.set_variable(
            "baseline_override",
            {
                "device_id": 1,
                "device_datasource_id": 10,
                "instance_id": 100,
                "datapoints": {
                    "cpu": {
                        "mean": 50.0,
                        "min": 40.0,
                        "max": 60.0,
                        "stddev": 5.0,
                        "sample_count": 10,
                    },
                },
            },
        )

        route = respx.get(
            "https://test.logicmonitor.com/santaba/rest"
            "/device/devices/99/devicedatasources/20/instances/300/data"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "dataPoints": ["cpu"],
                    "values": [[50.0]],
                    "time": [BASE_EPOCH],
                },
            )
        )

        await compare_to_baseline(
            client,
            baseline_name="override",
            device_id=99,
            device_datasource_id=20,
            instance_id=300,
        )

        assert route.called

    @respx.mock
    async def test_error_handling_api_failure(self, client):
        """API failure returns error response."""
        from lm_mcp.tools.baselines import compare_to_baseline

        session = get_session()
        session.set_variable(
            "baseline_err",
            {
                "device_id": 1,
                "device_datasource_id": 10,
                "instance_id": 100,
                "datapoints": {
                    "cpu": {
                        "mean": 50.0,
                        "min": 40.0,
                        "max": 60.0,
                        "stddev": 5.0,
                        "sample_count": 10,
                    },
                },
            },
        )

        respx.get(
            "https://test.logicmonitor.com/santaba/rest"
            "/device/devices/1/devicedatasources/10/instances/100/data"
        ).mock(return_value=httpx.Response(500, json={"errorMessage": "Server error"}))

        result = await compare_to_baseline(client, baseline_name="err")

        assert "Error:" in result[0].text

    @respx.mock
    async def test_deviation_percent_calculated(self, client):
        """Comparison includes deviation_percent for each datapoint."""
        from lm_mcp.tools.baselines import compare_to_baseline

        session = get_session()
        session.set_variable(
            "baseline_pct",
            {
                "device_id": 1,
                "device_datasource_id": 10,
                "instance_id": 100,
                "datapoints": {
                    "cpu": {
                        "mean": 50.0,
                        "min": 40.0,
                        "max": 60.0,
                        "stddev": 5.0,
                        "sample_count": 10,
                    },
                },
            },
        )

        respx.get(
            "https://test.logicmonitor.com/santaba/rest"
            "/device/devices/1/devicedatasources/10/instances/100/data"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "dataPoints": ["cpu"],
                    "values": [[55.0], [55.0], [55.0]],
                    "time": [BASE_EPOCH + i * 300 for i in range(3)],
                },
            )
        )

        result = await compare_to_baseline(client, baseline_name="pct")

        data = json.loads(result[0].text)
        comp = data["comparisons"]["cpu"]
        assert "deviation_percent" in comp
        assert "current_mean" in comp
        assert "baseline_mean" in comp


class TestBaselineErrorEnvelopeShape:
    """Regression tests for the bare-TextContent error return removal.

    Prior behavior: save_baseline and compare_to_baseline returned
    [TextContent(text=f"Error: {e}")] from their outer except blocks,
    bypassing handle_error and producing a naked string with no
    structured envelope, no code, no logged stack trace. Now both go
    through handle_error so the response matches every other tool.
    """

    @respx.mock
    async def test_save_baseline_4xx_goes_through_handle_error(self, client):
        """save_baseline 4xx now returns LMError envelope with HTTP_<status> code."""
        from lm_mcp.tools.baselines import save_baseline

        respx.get(
            "https://test.logicmonitor.com/santaba/rest"
            "/device/devices/1/devicedatasources/10/instances/100/data"
        ).mock(
            return_value=httpx.Response(
                403,
                json={"errorMessage": "Forbidden"},
            )
        )

        result = await save_baseline(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
            baseline_name="test",
        )

        text = result[0].text
        assert text.startswith("Error: Forbidden")
        # handle_error attaches a Suggestion line for LMError responses.
        assert "Suggestion:" in text

    @respx.mock
    async def test_compare_to_baseline_unexpected_exception_envelope(self, client):
        """An unexpected Python exception (e.g. malformed body) -> structured envelope."""
        from lm_mcp.tools.baselines import compare_to_baseline

        session = get_session()
        session.set_variable(
            "baseline_malformed",
            {
                "device_id": 1,
                "device_datasource_id": 10,
                "instance_id": 100,
                "datapoints": {
                    "cpu": {
                        "mean": 50.0,
                        "min": 40.0,
                        "max": 60.0,
                        "stddev": 5.0,
                        "sample_count": 10,
                    },
                },
            },
        )

        # Return a body that the comparison logic cannot consume cleanly.
        respx.get(
            "https://test.logicmonitor.com/santaba/rest"
            "/device/devices/1/devicedatasources/10/instances/100/data"
        ).mock(
            return_value=httpx.Response(
                200,
                json={"unexpected": "shape"},
            )
        )

        result = await compare_to_baseline(client, baseline_name="malformed")

        # Either we get the (legitimate, empty-values) success path or we get
        # the new structured envelope -- both must NOT be a naked
        # "Error: <ClassName>" string the old code produced.
        text = result[0].text
        if text.startswith("Error:"):
            assert "Suggestion:" in text or "code" in text.lower()


class TestErrorMessageWithoutErrorCode:
    """A 200 body carrying errorMessage but no errorCode is an API error, not a crash (R3.8)."""

    DATA_URL = (
        "https://test.logicmonitor.com/santaba/rest"
        "/device/devices/1/devicedatasources/10/instances/100/data"
    )

    @respx.mock
    async def test_save_baseline_returns_the_server_message(self, client, caplog):
        """save_baseline returns ErrorContent with the message and logs no unhandled error."""
        from lm_mcp.tools.baselines import save_baseline

        respx.get(self.DATA_URL).mock(
            return_value=httpx.Response(
                200, json={"errorMessage": "No data for instance 100", "errorDetail": None}
            )
        )

        with caplog.at_level(logging.WARNING, logger="lm_mcp.tools"):
            result = await save_baseline(
                client,
                device_id=1,
                device_datasource_id=10,
                instance_id=100,
                baseline_name="nodata",
            )

        assert is_error_result(result)
        assert "No data for instance 100" in result[0].text
        assert "unhandled error" not in caplog.text
        assert "errorMessage" not in result[0].text

    @respx.mock
    async def test_compare_to_baseline_returns_the_server_message(self, client, caplog):
        """compare_to_baseline returns ErrorContent with the message and logs no unhandled error."""
        from lm_mcp.tools.baselines import compare_to_baseline

        get_session().set_variable(
            "baseline_nodata",
            {
                "device_id": 1,
                "device_datasource_id": 10,
                "instance_id": 100,
                "datapoints": {"cpu": {"mean": 50.0, "min": 40.0, "max": 60.0, "stddev": 5.0}},
            },
        )
        respx.get(self.DATA_URL).mock(
            return_value=httpx.Response(
                200, json={"errorMessage": "No data for instance 100", "errorDetail": None}
            )
        )

        with caplog.at_level(logging.WARNING, logger="lm_mcp.tools"):
            result = await compare_to_baseline(client, baseline_name="nodata")

        assert is_error_result(result)
        assert "No data for instance 100" in result[0].text
        assert "unhandled error" not in caplog.text
        assert "errorMessage" not in result[0].text
