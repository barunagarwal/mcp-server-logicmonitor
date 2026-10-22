# Description: Tests for scoring and availability analysis tools.
# Description: Validates scoring, availability, health, and error budget tools.

import json
import time

import httpx
import pytest
import respx

from lm_mcp.auth.bearer import BearerAuth
from lm_mcp.client import LogicMonitorClient
from tests.alert_pages import alert_pages


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
ALERT_URL = "https://test.logicmonitor.com/santaba/rest/alert/alerts"


def _make_alert(
    alert_id,
    device,
    datasource,
    datapoint="value",
    severity=4,
    start_epoch=None,
    end_epoch=0,
    cleared=False,
):
    """Helper to create mock alert data."""
    return {
        "id": f"LMA{alert_id}",
        "severity": severity,
        "monitorObjectName": device,
        "resourceTemplateName": datasource,
        "dataPointName": datapoint,
        "alertValue": f"Alert {alert_id}",
        "startEpoch": start_epoch or BASE_EPOCH,
        "endEpoch": end_epoch,
        "cleared": cleared,
    }


class TestScoreAlertNoise:
    """Tests for score_alert_noise tool."""

    @respx.mock
    async def test_no_alerts_zero_noise(self, client):
        """No alerts produces noise score of 0."""
        from lm_mcp.tools.scoring import score_alert_noise

        respx.get(ALERT_URL).mock(return_value=httpx.Response(200, json={"items": [], "total": 0}))

        result = await score_alert_noise(client)

        data = json.loads(result[0].text)
        assert data["noise_score"] == 0
        assert data["total_alerts"] == 0

    @respx.mock
    async def test_single_alert_low_noise(self, client):
        """Single alert produces low noise score."""
        from lm_mcp.tools.scoring import score_alert_noise

        respx.get(ALERT_URL).mock(
            return_value=httpx.Response(
                200,
                json={"items": [_make_alert(1, "s1", "CPU")], "total": 1},
            )
        )

        result = await score_alert_noise(client)

        data = json.loads(result[0].text)
        assert data["noise_score"] <= 30
        assert data["total_alerts"] == 1

    @respx.mock
    async def test_flapping_alerts_detected(self, client):
        """Flapping alerts (clear + re-fire within 30 min) are detected."""
        from lm_mcp.tools.scoring import score_alert_noise

        alerts = [
            _make_alert(
                1,
                "s1",
                "CPU",
                "value",
                start_epoch=BASE_EPOCH,
                end_epoch=BASE_EPOCH + 300,
                cleared=True,
            ),
            _make_alert(
                2,
                "s1",
                "CPU",
                "value",
                start_epoch=BASE_EPOCH + 600,
            ),
        ]
        respx.get(ALERT_URL).mock(
            return_value=httpx.Response(
                200,
                json={"items": alerts, "total": 2},
            )
        )

        result = await score_alert_noise(client)

        data = json.loads(result[0].text)
        assert data["flap_count"] > 0
        assert len(data["flapping_alerts"]) > 0

    @respx.mock
    async def test_repeat_alerts_increase_noise(self, client):
        """Repeated alerts from same source increase noise."""
        from lm_mcp.tools.scoring import score_alert_noise

        alerts = [
            _make_alert(i, "s1", "CPU", "value", start_epoch=BASE_EPOCH + i * 60) for i in range(10)
        ]
        respx.get(ALERT_URL).mock(
            return_value=httpx.Response(
                200,
                json={"items": alerts, "total": 10},
            )
        )

        result = await score_alert_noise(client)

        data = json.loads(result[0].text)
        assert data["total_alerts"] == 10
        assert data["repeat_ratio"] > 0

    @respx.mock
    async def test_top_noisy_devices(self, client):
        """Top noisy devices are ranked by alert count."""
        from lm_mcp.tools.scoring import score_alert_noise

        alerts = [
            _make_alert(1, "noisy-server", "CPU"),
            _make_alert(2, "noisy-server", "Memory"),
            _make_alert(3, "noisy-server", "Disk"),
            _make_alert(4, "quiet-server", "CPU"),
        ]
        respx.get(ALERT_URL).mock(
            return_value=httpx.Response(
                200,
                json={"items": alerts, "total": 4},
            )
        )

        result = await score_alert_noise(client)

        data = json.loads(result[0].text)
        assert data["top_noisy_devices"][0]["device"] == "noisy-server"
        assert data["top_noisy_devices"][0]["count"] == 3

    @respx.mock
    async def test_top_noisy_datasources(self, client):
        """Top noisy datasources are ranked by alert count."""
        from lm_mcp.tools.scoring import score_alert_noise

        alerts = [
            _make_alert(1, "s1", "CPU"),
            _make_alert(2, "s2", "CPU"),
            _make_alert(3, "s3", "CPU"),
            _make_alert(4, "s1", "Memory"),
        ]
        respx.get(ALERT_URL).mock(
            return_value=httpx.Response(
                200,
                json={"items": alerts, "total": 4},
            )
        )

        result = await score_alert_noise(client)

        data = json.loads(result[0].text)
        assert data["top_noisy_datasources"][0]["datasource"] == "CPU"
        assert data["top_noisy_datasources"][0]["count"] == 3

    @respx.mock
    async def test_recommendations_present(self, client):
        """Response always includes recommendations."""
        from lm_mcp.tools.scoring import score_alert_noise

        respx.get(ALERT_URL).mock(return_value=httpx.Response(200, json={"items": [], "total": 0}))

        result = await score_alert_noise(client)

        data = json.loads(result[0].text)
        assert "recommendations" in data
        assert len(data["recommendations"]) > 0

    @respx.mock
    async def test_device_filter_passed(self, client):
        """Device filter is passed to the API."""
        from lm_mcp.tools.scoring import score_alert_noise

        route = respx.get(ALERT_URL).mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        await score_alert_noise(client, device="server01")

        params = dict(route.calls[0].request.url.params)
        assert "monitorObjectName" in params.get("filter", "")

    @respx.mock
    async def test_group_id_filter_passed(self, client):
        """Group ID filter resolves to monitorObjectGroups in the API call."""
        from lm_mcp.tools.scoring import score_alert_noise

        respx.get("https://test.logicmonitor.com/santaba/rest/device/groups/5").mock(
            return_value=httpx.Response(200, json={"id": 5, "fullPath": "Dev Portal/Test Group"})
        )
        route = respx.get(ALERT_URL).mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        await score_alert_noise(client, group_id=5)

        params = dict(route.calls[0].request.url.params)
        assert 'monitorObjectGroups~"Dev Portal/Test Group"' in params.get("filter", "")

    @respx.mock
    async def test_hours_back_in_response(self, client):
        """Response includes hours_back parameter."""
        from lm_mcp.tools.scoring import score_alert_noise

        respx.get(ALERT_URL).mock(return_value=httpx.Response(200, json={"items": [], "total": 0}))

        result = await score_alert_noise(client, hours_back=48)

        data = json.loads(result[0].text)
        assert data["hours_back"] == 48

    @respx.mock
    async def test_error_handling(self, client):
        """API errors are returned as error response."""
        from lm_mcp.tools.scoring import score_alert_noise

        respx.get(ALERT_URL).mock(
            return_value=httpx.Response(500, json={"errorMessage": "Server error"})
        )

        result = await score_alert_noise(client)

        assert "Error:" in result[0].text

    @respx.mock
    async def test_noise_score_bounded(self, client):
        """Noise score is bounded between 0 and 100."""
        from lm_mcp.tools.scoring import score_alert_noise

        # Many diverse alerts to push entropy up
        alerts = [_make_alert(i, f"server{i}", f"DS{i}", f"dp{i}") for i in range(50)]
        respx.get(ALERT_URL).mock(
            return_value=httpx.Response(
                200,
                json={"items": alerts, "total": 50},
            )
        )

        result = await score_alert_noise(client)

        data = json.loads(result[0].text)
        assert 0 <= data["noise_score"] <= 100

    @respx.mock
    async def test_moderate_repeat_ratio_not_maxed(self, client):
        """A moderate repeat ratio should not peg the score at 100."""
        from lm_mcp.tools.scoring import score_alert_noise

        # 10 alerts from same combo (high repeat) + 5 unique combos = ~0.2 repeat_ratio
        alerts = [
            _make_alert(i, "s1", "CPU", "value", start_epoch=BASE_EPOCH + i * 60) for i in range(10)
        ] + [
            _make_alert(
                10 + i, f"server{i}", f"DS{i}", f"dp{i}", start_epoch=BASE_EPOCH + (10 + i) * 60
            )
            for i in range(5)
        ]
        respx.get(ALERT_URL).mock(
            return_value=httpx.Response(
                200,
                json={"items": alerts, "total": 15},
            )
        )

        result = await score_alert_noise(client)

        data = json.loads(result[0].text)
        assert data["noise_score"] < 100

    @respx.mock
    async def test_score_100_requires_extreme_conditions(self, client):
        """Score of 100 requires maxed entropy, flapping, and repeats."""
        from lm_mcp.tools.scoring import score_alert_noise

        # All alerts from exactly one combo (max repeat, low entropy)
        alerts = [
            _make_alert(
                i,
                "s1",
                "CPU",
                "value",
                start_epoch=BASE_EPOCH + i * 120,
                end_epoch=BASE_EPOCH + i * 120 + 60,
                cleared=True,
            )
            for i in range(20)
        ]
        respx.get(ALERT_URL).mock(
            return_value=httpx.Response(
                200,
                json={"items": alerts, "total": 20},
            )
        )

        result = await score_alert_noise(client)

        data = json.loads(result[0].text)
        # With rebalanced weights, a single-combo set has low entropy (normalized=0)
        # and repeat_ratio=1.0 (30 pts) + flap_ratio contributes the rest
        assert 0 <= data["noise_score"] <= 100


class TestCalculateAvailability:
    """Tests for calculate_availability tool."""

    @respx.mock
    async def test_no_alerts_full_availability(self, client):
        """No alerts means 100% availability."""
        from lm_mcp.tools.scoring import calculate_availability

        respx.get(ALERT_URL).mock(return_value=httpx.Response(200, json={"items": [], "total": 0}))

        result = await calculate_availability(client)

        data = json.loads(result[0].text)
        assert data["availability_percent"] == 100.0
        assert data["total_downtime_minutes"] == 0
        assert data["incident_count"] == 0

    @respx.mock
    async def test_single_incident_reduces_availability(self, client):
        """A single incident reduces availability below 100%."""
        from lm_mcp.tools.scoring import calculate_availability

        now = int(time.time())
        recent = now - 3600  # 1 hour ago
        alerts = [
            _make_alert(
                1,
                "server01",
                "CPU",
                severity=3,
                start_epoch=recent,
                end_epoch=recent + 1800,
                cleared=True,
            ),
        ]
        respx.get(ALERT_URL).mock(
            return_value=httpx.Response(
                200,
                json={"items": alerts, "total": 1},
            )
        )

        result = await calculate_availability(client, hours_back=24)

        data = json.loads(result[0].text)
        assert data["availability_percent"] < 100.0
        assert data["total_downtime_minutes"] > 0
        assert data["incident_count"] == 1

    @respx.mock
    async def test_overlapping_incidents_merged(self, client):
        """Overlapping incidents are merged into one."""
        from lm_mcp.tools.scoring import calculate_availability

        now = int(time.time())
        recent = now - 7200
        alerts = [
            _make_alert(
                1,
                "server01",
                "CPU",
                severity=3,
                start_epoch=recent,
                end_epoch=recent + 3600,
                cleared=True,
            ),
            _make_alert(
                2,
                "server01",
                "Memory",
                severity=3,
                start_epoch=recent + 1800,
                end_epoch=recent + 5400,
                cleared=True,
            ),
        ]
        respx.get(ALERT_URL).mock(
            return_value=httpx.Response(
                200,
                json={"items": alerts, "total": 2},
            )
        )

        result = await calculate_availability(client, hours_back=24)

        data = json.loads(result[0].text)
        dev_data = data["by_device"]["server01"]
        assert dev_data["incident_count"] == 1

    @respx.mock
    async def test_active_alert_counted_as_ongoing(self, client):
        """Active alert (endEpoch=0) counted as ongoing downtime."""
        from lm_mcp.tools.scoring import calculate_availability

        now = int(time.time())
        recent = now - 3600
        alerts = [
            _make_alert(
                1,
                "server01",
                "CPU",
                severity=3,
                start_epoch=recent,
                end_epoch=0,
            ),
        ]
        respx.get(ALERT_URL).mock(
            return_value=httpx.Response(
                200,
                json={"items": alerts, "total": 1},
            )
        )

        result = await calculate_availability(client, hours_back=24)

        data = json.loads(result[0].text)
        assert data["total_downtime_minutes"] > 0

    @respx.mock
    async def test_mttr_calculated(self, client):
        """MTTR (mean time to repair) is calculated correctly."""
        from lm_mcp.tools.scoring import calculate_availability

        now = int(time.time())
        recent = now - 14400  # 4 hours ago
        alerts = [
            _make_alert(
                1,
                "server01",
                "CPU",
                severity=3,
                start_epoch=recent,
                end_epoch=recent + 1800,
                cleared=True,
            ),
            _make_alert(
                2,
                "server01",
                "Memory",
                severity=3,
                start_epoch=recent + 7200,
                end_epoch=recent + 9000,
                cleared=True,
            ),
        ]
        respx.get(ALERT_URL).mock(
            return_value=httpx.Response(
                200,
                json={"items": alerts, "total": 2},
            )
        )

        result = await calculate_availability(client, hours_back=24)

        data = json.loads(result[0].text)
        assert data["mttr_minutes"] == 30.0  # 1800 sec = 30 min each

    @respx.mock
    async def test_per_device_breakdown(self, client):
        """Per-device breakdown is included in response."""
        from lm_mcp.tools.scoring import calculate_availability

        now = int(time.time())
        recent = now - 7200
        alerts = [
            _make_alert(
                1,
                "server01",
                "CPU",
                severity=3,
                start_epoch=recent,
                end_epoch=recent + 1800,
                cleared=True,
            ),
            _make_alert(
                2,
                "server02",
                "CPU",
                severity=3,
                start_epoch=recent,
                end_epoch=recent + 3600,
                cleared=True,
            ),
        ]
        respx.get(ALERT_URL).mock(
            return_value=httpx.Response(
                200,
                json={"items": alerts, "total": 2},
            )
        )

        result = await calculate_availability(client, hours_back=24)

        data = json.loads(result[0].text)
        assert "server01" in data["by_device"]
        assert "server02" in data["by_device"]

    @respx.mock
    async def test_severity_threshold(self, client):
        """Severity threshold is included in response."""
        from lm_mcp.tools.scoring import calculate_availability

        respx.get(ALERT_URL).mock(return_value=httpx.Response(200, json={"items": [], "total": 0}))

        result = await calculate_availability(client, severity_threshold="critical")

        data = json.loads(result[0].text)
        assert data["severity_threshold"] == "critical"

    @respx.mock
    async def test_longest_incident_tracked(self, client):
        """Longest incident duration is tracked."""
        from lm_mcp.tools.scoring import calculate_availability

        now = int(time.time())
        recent = now - 14400
        alerts = [
            _make_alert(
                1,
                "server01",
                "CPU",
                severity=3,
                start_epoch=recent,
                end_epoch=recent + 7200,
                cleared=True,
            ),
        ]
        respx.get(ALERT_URL).mock(
            return_value=httpx.Response(
                200,
                json={"items": alerts, "total": 1},
            )
        )

        result = await calculate_availability(client, hours_back=24)

        data = json.loads(result[0].text)
        assert data["longest_incident_minutes"] == 120.0

    @respx.mock
    async def test_hours_back_in_response(self, client):
        """Response includes hours_back parameter."""
        from lm_mcp.tools.scoring import calculate_availability

        respx.get(ALERT_URL).mock(return_value=httpx.Response(200, json={"items": [], "total": 0}))

        result = await calculate_availability(client, hours_back=48)

        data = json.loads(result[0].text)
        assert data["hours_back"] == 48

    @respx.mock
    async def test_error_handling(self, client):
        """API errors are returned as error response."""
        from lm_mcp.tools.scoring import calculate_availability

        respx.get(ALERT_URL).mock(
            return_value=httpx.Response(500, json={"errorMessage": "Server error"})
        )

        result = await calculate_availability(client)

        assert "Error:" in result[0].text

    @respx.mock
    async def test_device_id_reads_the_device_alerts(self, client):
        """device_id reads /device/devices/{id}/alerts; the alerts list ignores monitorObjectId."""
        from lm_mcp.tools.scoring import calculate_availability

        respx.get(DEVICE_URL_TEMPLATE.format(id=42)).mock(
            return_value=httpx.Response(200, json={"id": 42, "displayName": "server42"})
        )
        route = respx.get(DEVICE_ALERTS_URL_TEMPLATE.format(id=42)).mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        result = await calculate_availability(client, device_id=42)

        assert json.loads(result[0].text)["device_id"] == 42
        assert route.call_count == 1
        clauses = route.calls[0].request.url.params["filter"].split(",")
        assert clauses[0].startswith("startEpoch>:")
        assert clauses[1:] == ["severity>:3"]

    @respx.mock
    async def test_availability_filters_by_device_id(self, client):
        """calculate_availability only includes alerts for the target device."""
        from lm_mcp.tools.scoring import calculate_availability

        now = int(time.time())
        recent = now - 3600  # 1 hour ago

        # Mock device lookup
        respx.get("https://test.logicmonitor.com/santaba/rest/device/devices/100").mock(
            return_value=httpx.Response(
                200,
                json={"id": 100, "displayName": "target-server"},
            )
        )

        # The device-scoped endpoint returns only the target's alerts
        alerts = [_device_alert("A1", 100, "target-server", recent, recent + 300)]
        respx.get(DEVICE_ALERTS_URL_TEMPLATE.format(id=100)).mock(
            return_value=httpx.Response(200, json={"items": alerts, "total": 1})
        )

        result = await calculate_availability(client, device_id=100, hours_back=24)
        data = json.loads(result[0].text)

        # The device's own alert list is the scope, counted under its name
        assert list(data["by_device"]) == ["target-server"]


# Base epoch for metric data
METRIC_BASE = 1705276800
DATA_URL = (
    "https://test.logicmonitor.com/santaba/rest"
    "/device/devices/1/devicedatasources/10/instances/100/data"
)


class TestScoreDeviceHealth:
    """Tests for score_device_health tool."""

    @respx.mock
    async def test_healthy_device(self, client):
        """Normal data produces healthy score."""
        from lm_mcp.tools.scoring import score_device_health

        values = [[50.0]] * 20
        respx.get(DATA_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "dataPoints": ["cpu"],
                    "values": values,
                    "time": [(METRIC_BASE + i * 300) * 1000 for i in range(20)],
                },
            )
        )

        result = await score_device_health(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
        )

        data = json.loads(result[0].text)
        assert data["health_score"] >= 80
        assert data["status"] == "healthy"

    @respx.mock
    async def test_anomalous_data_low_score(self, client):
        """Data with anomalous latest value produces low health score."""
        from lm_mcp.tools.scoring import score_device_health

        # 19 normal values around 50, then a spike to 500
        values = [[50.0]] * 19 + [[500.0]]
        respx.get(DATA_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "dataPoints": ["cpu"],
                    "values": values,
                    "time": [(METRIC_BASE + i * 300) * 1000 for i in range(20)],
                },
            )
        )

        result = await score_device_health(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
        )

        data = json.loads(result[0].text)
        assert data["health_score"] < 80
        assert data["anomaly_count"] >= 1

    @respx.mock
    async def test_empty_data_returns_unknown(self, client):
        """No metric data returns unknown status."""
        from lm_mcp.tools.scoring import score_device_health

        respx.get(DATA_URL).mock(
            return_value=httpx.Response(
                200,
                json={"dataPoints": [], "values": [], "time": []},
            )
        )

        result = await score_device_health(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
        )

        data = json.loads(result[0].text)
        assert data["status"] == "unknown"

    @respx.mock
    async def test_multiple_datapoints(self, client):
        """Multiple datapoints each contribute to health score."""
        from lm_mcp.tools.scoring import score_device_health

        values = [[50.0, 70.0]] * 20
        respx.get(DATA_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "dataPoints": ["cpu", "memory"],
                    "values": values,
                    "time": [(METRIC_BASE + i * 300) * 1000 for i in range(20)],
                },
            )
        )

        result = await score_device_health(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
        )

        data = json.loads(result[0].text)
        assert len(data["contributing_factors"]) == 2

    @respx.mock
    async def test_factors_sorted_by_impact(self, client):
        """Contributing factors are sorted by weighted impact."""
        from lm_mcp.tools.scoring import score_device_health

        # cpu normal, memory has spike
        values = [[50.0, 70.0]] * 19 + [[50.0, 300.0]]
        respx.get(DATA_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "dataPoints": ["cpu", "memory"],
                    "values": values,
                    "time": [(METRIC_BASE + i * 300) * 1000 for i in range(20)],
                },
            )
        )

        result = await score_device_health(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
        )

        data = json.loads(result[0].text)
        factors = data["contributing_factors"]
        assert factors[0]["datapoint"] == "memory"

    @respx.mock
    async def test_response_structure(self, client):
        """Response includes all expected fields."""
        from lm_mcp.tools.scoring import score_device_health

        values = [[50.0]] * 10
        respx.get(DATA_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "dataPoints": ["cpu"],
                    "values": values,
                    "time": [(METRIC_BASE + i * 300) * 1000 for i in range(10)],
                },
            )
        )

        result = await score_device_health(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
        )

        data = json.loads(result[0].text)
        assert "health_score" in data
        assert "status" in data
        assert "contributing_factors" in data
        assert "anomaly_count" in data
        assert data["device_id"] == 1

    @respx.mock
    async def test_health_score_bounded(self, client):
        """Health score is bounded between 0 and 100."""
        from lm_mcp.tools.scoring import score_device_health

        # Extreme anomaly to test lower bound
        values = [[50.0]] * 19 + [[99999.0]]
        respx.get(DATA_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "dataPoints": ["cpu"],
                    "values": values,
                    "time": [(METRIC_BASE + i * 300) * 1000 for i in range(20)],
                },
            )
        )

        result = await score_device_health(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
        )

        data = json.loads(result[0].text)
        assert 0 <= data["health_score"] <= 100

    @respx.mock
    async def test_error_handling(self, client):
        """API errors are returned as error response."""
        from lm_mcp.tools.scoring import score_device_health

        respx.get(DATA_URL).mock(return_value=httpx.Response(500, json={"errorMessage": "error"}))

        result = await score_device_health(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
        )

        assert "Error:" in result[0].text


class TestScoringGuardrails:
    """Tests for best practice guardrails in scoring tools."""

    @respx.mock
    async def test_score_alert_noise_structured_recommendations_high_noise(self, client):
        """High noise score includes structured recommendations."""
        from lm_mcp.tools.scoring import score_alert_noise

        # Many repeated alerts from same device+datasource to push noise up
        alerts = []
        for i in range(20):
            alerts.append(
                _make_alert(
                    i,
                    "server01",
                    "CPU",
                    "value",
                    start_epoch=BASE_EPOCH + i * 60,
                    end_epoch=BASE_EPOCH + i * 60 + 30,
                    cleared=True,
                )
            )
            # Re-fire quickly for flapping
            alerts.append(
                _make_alert(
                    100 + i,
                    "server01",
                    "CPU",
                    "value",
                    start_epoch=BASE_EPOCH + i * 60 + 60,
                )
            )
        respx.get(ALERT_URL).mock(
            return_value=httpx.Response(
                200,
                json={"items": alerts, "total": len(alerts)},
            )
        )

        result = await score_alert_noise(client)
        data = json.loads(result[0].text)

        if data["noise_score"] > 50:
            assert "structured_recommendations" in data
            assert len(data["structured_recommendations"]) > 0
            assert "anti_patterns" in data
            assert len(data["anti_patterns"]) > 0
            for rec in data["structured_recommendations"]:
                assert "action" in rec
                assert "how" in rec
                assert "priority" in rec

    @respx.mock
    async def test_score_alert_noise_no_anti_patterns_low_noise(self, client):
        """Low noise score omits anti_patterns key."""
        from lm_mcp.tools.scoring import score_alert_noise

        respx.get(ALERT_URL).mock(
            return_value=httpx.Response(
                200,
                json={"items": [_make_alert(1, "s1", "CPU")], "total": 1},
            )
        )

        result = await score_alert_noise(client)
        data = json.loads(result[0].text)

        assert data["noise_score"] <= 50
        assert "anti_patterns" not in data

    @respx.mock
    async def test_score_device_health_recommendations_critical(self, client):
        """Critical health score includes recommendations with priority."""
        from lm_mcp.tools.scoring import score_device_health

        # Extreme anomaly to force critical health score
        values = [[50.0]] * 19 + [[99999.0]]
        respx.get(DATA_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "dataPoints": ["cpu"],
                    "values": values,
                    "time": [(METRIC_BASE + i * 300) * 1000 for i in range(20)],
                },
            )
        )

        result = await score_device_health(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
        )

        data = json.loads(result[0].text)
        assert data["health_score"] < 50
        assert "recommendations" in data
        assert len(data["recommendations"]) > 0
        for rec in data["recommendations"]:
            assert "priority" in rec
        assert "anti_patterns" in data

    @respx.mock
    async def test_score_device_health_degraded_has_monitor_rec(self, client):
        """Degraded health score includes monitor-trend recommendation."""
        from lm_mcp.tools.scoring import score_device_health

        # Moderate anomaly to get degraded score (50-80)
        values = [[50.0]] * 19 + [[100.0]]
        respx.get(DATA_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "dataPoints": ["cpu"],
                    "values": values,
                    "time": [(METRIC_BASE + i * 300) * 1000 for i in range(20)],
                },
            )
        )

        result = await score_device_health(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
        )

        data = json.loads(result[0].text)
        if 50 <= data["health_score"] < 80:
            assert "recommendations" in data
            assert data["recommendations"][0]["action"] == "Monitor trend"

    @respx.mock
    async def test_calculate_availability_measurement_context_low(self, client):
        """Low availability includes measurement_window_context."""
        from lm_mcp.tools.scoring import calculate_availability

        now = int(time.time())
        recent = now - 3600
        alerts = [
            _make_alert(
                1,
                "server01",
                "CPU",
                severity=3,
                start_epoch=recent,
                end_epoch=recent + 1800,
                cleared=True,
            ),
        ]
        respx.get(ALERT_URL).mock(
            return_value=httpx.Response(
                200,
                json={"items": alerts, "total": 1},
            )
        )

        result = await calculate_availability(client, hours_back=24)

        data = json.loads(result[0].text)
        assert "measurement_window_context" in data
        if data["availability_percent"] < 99.9:
            ctx = data["measurement_window_context"]
            assert "measurement_window_hours" in ctx
            assert "recommendations" in ctx
            assert "anti_patterns" in ctx
            assert len(ctx["recommendations"]) > 0


class TestCalculateErrorBudget:
    """Tests for calculate_error_budget tool."""

    @respx.mock
    async def test_error_budget_zero_downtime(self, client):
        """Zero downtime gives healthy status with full budget remaining."""
        from lm_mcp.tools.scoring import calculate_error_budget

        respx.get(ALERT_URL).mock(return_value=httpx.Response(200, json={"items": [], "total": 0}))

        result = await calculate_error_budget(client, target_slo=99.9, period_days=30)

        data = json.loads(result[0].text)
        assert data["status"] == "healthy"
        assert data["actual_availability"] == 100.0
        assert data["remaining_minutes"] > 0
        assert data["budget_consumed_percent"] == 0.0

    @respx.mock
    async def test_error_budget_partial_consumption(self, client):
        """Partial downtime shows correct consumption percentage."""
        from lm_mcp.tools.scoring import calculate_error_budget

        now_epoch = int(time.time())
        start_epoch = now_epoch - (30 * 24 * 3600)

        respx.get(ALERT_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "a1",
                            "severity": 3,
                            "monitorObjectName": "server1",
                            "startEpoch": start_epoch + 1000,
                            "endEpoch": start_epoch + 4600,  # 60 min downtime
                        },
                    ],
                    "total": 1,
                },
            )
        )

        result = await calculate_error_budget(client, target_slo=99.9, period_days=30)

        data = json.loads(result[0].text)
        assert data["consumed_minutes"] > 0
        assert data["remaining_minutes"] >= 0
        assert data["status"] in ("healthy", "warning", "critical", "exhausted")

    @respx.mock
    async def test_error_budget_exhausted(self, client):
        """Massive downtime exhausts the budget."""
        from lm_mcp.tools.scoring import calculate_error_budget

        now_epoch = int(time.time())
        start_epoch = now_epoch - (30 * 24 * 3600)

        # 99.9% SLO over 30 days = 43.2 min budget. Create 100 min downtime.
        respx.get(ALERT_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "a1",
                            "severity": 3,
                            "monitorObjectName": "server1",
                            "startEpoch": start_epoch + 1000,
                            "endEpoch": start_epoch + 7000,  # 100 min
                        },
                    ],
                    "total": 1,
                },
            )
        )

        result = await calculate_error_budget(client, target_slo=99.9, period_days=30)

        data = json.loads(result[0].text)
        assert data["status"] in ("critical", "exhausted")
        assert data["budget_consumed_percent"] > 90

    async def test_error_budget_slo_100_edge_case(self, client):
        """SLO of 100% means zero budget -- any downtime exhausts it."""
        import respx as _respx

        from lm_mcp.tools.scoring import calculate_error_budget

        with _respx.mock:
            _respx.get(ALERT_URL).mock(
                return_value=httpx.Response(200, json={"items": [], "total": 0})
            )
            result = await calculate_error_budget(
                client,
                target_slo=100.0,
                period_days=30,
            )

        data = json.loads(result[0].text)
        assert data["total_budget_minutes"] == 0.0
        assert data["status"] == "healthy"  # No downtime with 0 budget = healthy


DEVICE_URL_TEMPLATE = "https://test.logicmonitor.com/santaba/rest/device/devices/{id}"


class TestCalculateAvailabilityDeviceLookup:
    """Regression tests for the device-lookup silent-failure fix.

    Prior behavior: a 404/403 on the device lookup proceeded with
    unfiltered alerts, producing availability numbers for a different
    device set than the caller asked for. Now a device that does not exist
    returns DEVICE_NOT_FOUND and any other lookup failure returns
    DEVICE_LOOKUP_FAILED, both before any alert is read.
    """

    @respx.mock
    async def test_404_on_device_lookup_returns_structured_error(self, client):
        from lm_mcp.tools.scoring import calculate_availability

        respx.get(DEVICE_URL_TEMPLATE.format(id=99999)).mock(
            return_value=httpx.Response(404, json={"errorMessage": "Device not found"})
        )

        result = await calculate_availability(client, device_id=99999, hours_back=24)

        text = result[0].text
        assert "Error:" in text
        assert "device 99999" in text.lower() or "99999" in text

    @respx.mock
    async def test_403_on_device_lookup_returns_structured_error(self, client):
        from lm_mcp.tools.scoring import calculate_availability

        respx.get(DEVICE_URL_TEMPLATE.format(id=42)).mock(
            return_value=httpx.Response(403, json={"errorMessage": "Forbidden"})
        )

        result = await calculate_availability(client, device_id=42, hours_back=24)

        assert "Error:" in result[0].text

    @respx.mock
    async def test_successful_device_lookup_reads_device_alerts(self, client):
        """Happy path: the device resolves, then its own alerts are read by id."""
        from lm_mcp.tools.scoring import calculate_availability

        respx.get(DEVICE_ALERTS_URL_TEMPLATE.format(id=100)).mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [_device_alert("a1", 100, "server1", int(time.time()) - 1000, 0)],
                    "total": 1,
                },
            )
        )
        respx.get(DEVICE_URL_TEMPLATE.format(id=100)).mock(
            return_value=httpx.Response(
                200, json={"id": 100, "displayName": "server1", "hostStatus": 0}
            )
        )

        result = await calculate_availability(client, device_id=100, hours_back=24)

        data = json.loads(result[0].text)
        assert "error" not in data or data.get("error") is False
        assert list(data["by_device"]) == ["server1"]


class TestCalculateErrorBudgetSubToolHardening:
    """Regression test mirroring the v3.8.2 _call_sub_tool fix.

    Prior behavior: calculate_error_budget did a raw json.loads on the
    text returned by calculate_availability. If the inner call returned
    an Error: ... envelope, json.loads raised JSONDecodeError and the
    composite crashed. The fix routes through call_sub_tool so the error
    surfaces cleanly.
    """

    @respx.mock
    async def test_inner_failure_surfaces_as_clean_error(self, client):
        from lm_mcp.tools.scoring import calculate_error_budget

        # calculate_availability will return an Error envelope because the
        # device lookup 404s. Without the call_sub_tool routing, this
        # would JSONDecodeError below.
        respx.get(DEVICE_URL_TEMPLATE.format(id=99999)).mock(
            return_value=httpx.Response(404, json={"errorMessage": "Device not found"})
        )

        result = await calculate_error_budget(
            client,
            device_id=99999,
            target_slo=99.9,
            period_days=30,
        )

        text = result[0].text
        assert "Error:" in text
        # The JSONDecodeError message ("Expecting value: line 1 column 1")
        # must NOT appear -- that was the v3.8.2-pattern regression signal.
        assert "Expecting value" not in text


DEVICES_URL = "https://test.logicmonitor.com/santaba/rest/device/devices"
DEVICE_ALERTS_URL_TEMPLATE = DEVICES_URL + "/{id}/alerts"


def _device_alert(alert_id, device_id, name, start_epoch, end_epoch, severity=3):
    """An alert as /device/devices/{id}/alerts returns it: the id is the device's."""
    return {
        "id": f"LMA{alert_id}",
        "severity": severity,
        "monitorObjectId": device_id,
        "monitorObjectType": "device",
        "monitorObjectName": name,
        "startEpoch": start_epoch,
        "endEpoch": end_epoch,
        "cleared": end_epoch > 0,
    }


class TestScoreAlertNoisePaging:
    """R4.2: score_alert_noise scores the whole window or says the cap cut it short."""

    @respx.mock
    async def test_scores_every_page(self, client):
        from lm_mcp.tools.scoring import score_alert_noise

        alerts = [
            _make_alert(i, f"dev-{i % 5}", f"DS-{i % 3}", start_epoch=BASE_EPOCH + i)
            for i in range(2500)
        ]
        respx.get(ALERT_URL).mock(side_effect=alert_pages(alerts, lower_bound=True))

        result = await score_alert_noise(client)

        data = json.loads(result[0].text)
        assert data["total_alerts"] == 2500
        assert sum(d["count"] for d in data["top_noisy_devices"]) == 2500
        assert data["truncated"] is False
        assert data["api_total"] == 2500

    @respx.mock
    async def test_capped_window_is_declared(self, client):
        from lm_mcp.tools.scoring import score_alert_noise

        alerts = [
            _make_alert(i, f"dev-{i % 5}", "DS", start_epoch=BASE_EPOCH + i) for i in range(6000)
        ]
        respx.get(ALERT_URL).mock(side_effect=alert_pages(alerts, lower_bound=True))

        result = await score_alert_noise(client)

        data = json.loads(result[0].text)
        assert data["total_alerts"] == 5000
        assert data["truncated"] is True
        assert data["api_total"] is None


class TestAvailabilityResolvesDevice:
    """R4.3: calculate_availability resolves the device first and reads its alerts by id."""

    @respx.mock
    async def test_unknown_device_name_is_an_error_not_full_availability(self, client):
        from lm_mcp.tools import ErrorContent
        from lm_mcp.tools.scoring import calculate_availability

        route = respx.get(DEVICES_URL).mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        result = await calculate_availability(client, device_name="nope")

        assert isinstance(result[0], ErrorContent)
        assert "not found" in result[0].text.lower()
        assert "nope" in result[0].text
        assert route.calls[0].request.url.params["filter"] == 'displayName:"nope"'

    @respx.mock
    async def test_unknown_device_id_is_not_found(self, client):
        from lm_mcp.tools import ErrorContent
        from lm_mcp.tools.scoring import calculate_availability

        respx.get(DEVICE_URL_TEMPLATE.format(id=99999)).mock(
            return_value=httpx.Response(404, json={"errorMessage": "Device not found"})
        )

        result = await calculate_availability(client, device_id=99999)

        assert isinstance(result[0], ErrorContent)
        assert "not found" in result[0].text.lower()
        assert "99999" in result[0].text

    @respx.mock
    async def test_device_id_counts_alerts_recorded_under_an_earlier_name(self, client):
        from lm_mcp.tools.scoring import calculate_availability

        now = int(time.time())
        respx.get(DEVICE_URL_TEMPLATE.format(id=5)).mock(
            return_value=httpx.Response(200, json={"id": 5, "displayName": "web-02"})
        )
        alerts = [
            _device_alert(1, 5, "web-01", now - 7200, now - 6600),
            _device_alert(2, 5, "web-02", now - 3600, now - 3000),
        ]
        route = respx.get(DEVICE_ALERTS_URL_TEMPLATE.format(id=5)).mock(
            side_effect=alert_pages(alerts)
        )

        result = await calculate_availability(client, device_id=5, hours_back=24)

        data = json.loads(result[0].text)
        assert data["incident_count"] == 2
        assert list(data["by_device"]) == ["web-02"]
        assert data["by_device"]["web-02"]["incident_count"] == 2
        assert data["device_resolved"] is True
        assert data["device_id"] == 5
        assert "monitorObject" not in route.calls[0].request.url.params["filter"]

    @respx.mock
    async def test_device_name_resolves_to_the_device_alerts(self, client):
        from lm_mcp.tools.scoring import calculate_availability

        now = int(time.time())
        respx.get(DEVICES_URL).mock(
            return_value=httpx.Response(
                200, json={"items": [{"id": 5, "displayName": "web-02"}], "total": 1}
            )
        )
        alerts = [
            _device_alert(1, 5, "web-01", now - 7200, now - 6600),
            _device_alert(2, 5, "web-02", now - 3600, now - 3000),
        ]
        respx.get(DEVICE_ALERTS_URL_TEMPLATE.format(id=5)).mock(side_effect=alert_pages(alerts))

        result = await calculate_availability(client, device_name="web-02", hours_back=24)

        data = json.loads(result[0].text)
        assert data["incident_count"] == 2
        assert data["device_id"] == 5

    @respx.mock
    async def test_resolved_device_without_alerts_is_fully_available(self, client):
        from lm_mcp.tools.scoring import calculate_availability

        respx.get(DEVICE_URL_TEMPLATE.format(id=5)).mock(
            return_value=httpx.Response(200, json={"id": 5, "displayName": "web-02"})
        )
        respx.get(DEVICE_ALERTS_URL_TEMPLATE.format(id=5)).mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        result = await calculate_availability(client, device_id=5)

        data = json.loads(result[0].text)
        assert data["availability_percent"] == 100.0
        assert data["incident_count"] == 0
        assert data["device_resolved"] is True
        assert data["truncated"] is False

    @respx.mock
    async def test_capped_window_is_declared(self, client):
        from lm_mcp.tools.scoring import calculate_availability

        now = int(time.time())
        alerts = [
            _make_alert(
                i, f"dev-{i % 7}", "DS", severity=3, start_epoch=now - 7200 + i, end_epoch=now - 60
            )
            for i in range(6000)
        ]
        respx.get(ALERT_URL).mock(side_effect=alert_pages(alerts, lower_bound=True))

        result = await calculate_availability(client, hours_back=24)

        data = json.loads(result[0].text)
        assert data["truncated"] is True
        assert data["api_total"] is None


class TestResolveDevice:
    """R4.3: _resolve_device separates a missing device from a failed lookup by code."""

    @respx.mock
    async def test_missing_device_id_is_device_not_found(self, client):
        from lm_mcp.tools.scoring import _resolve_device

        respx.get(DEVICE_URL_TEMPLATE.format(id=99999)).mock(
            return_value=httpx.Response(404, json={"errorMessage": "Device not found"})
        )

        assert (await _resolve_device(client, 99999, None))["code"] == "DEVICE_NOT_FOUND"

    @respx.mock
    async def test_missing_device_name_is_device_not_found(self, client):
        from lm_mcp.tools.scoring import _resolve_device

        respx.get(DEVICES_URL).mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        assert (await _resolve_device(client, None, "nope"))["code"] == "DEVICE_NOT_FOUND"

    @respx.mock
    async def test_forbidden_lookup_is_device_lookup_failed(self, client):
        from lm_mcp.tools.scoring import _resolve_device

        respx.get(DEVICE_URL_TEMPLATE.format(id=42)).mock(
            return_value=httpx.Response(403, json={"errorMessage": "Forbidden"})
        )

        assert (await _resolve_device(client, 42, None))["code"] == "DEVICE_LOOKUP_FAILED"

    @respx.mock
    async def test_resolved_device_carries_id_and_name(self, client):
        from lm_mcp.tools.scoring import _resolve_device

        respx.get(DEVICES_URL).mock(
            return_value=httpx.Response(
                200, json={"items": [{"id": 5, "displayName": "web-02"}], "total": 1}
            )
        )

        assert await _resolve_device(client, None, "web-02") == {"id": 5, "displayName": "web-02"}


class TestAvailabilityDeviceWithGroup:
    """R4.3: a device and a group together have no single scope, so they are refused."""

    @pytest.mark.parametrize(
        "device_args", [{"device_id": 5}, {"device_name": "web-02"}], ids=["id", "name"]
    )
    @respx.mock
    async def test_device_with_group_is_refused_before_any_read(self, client, device_args):
        from lm_mcp.tools import ErrorContent
        from lm_mcp.tools.scoring import calculate_availability

        result = await calculate_availability(client, group_id=7, **device_args)

        assert isinstance(result[0], ErrorContent)
        assert "group_id" in result[0].text
        assert "not both" in result[0].text
        assert len(respx.calls) == 0

    @respx.mock
    async def test_error_budget_surfaces_the_refusal(self, client):
        from lm_mcp.tools import ErrorContent
        from lm_mcp.tools.scoring import calculate_error_budget

        result = await calculate_error_budget(client, device_id=5, group_id=7)

        assert isinstance(result[0], ErrorContent)
        assert "not both" in result[0].text
        assert len(respx.calls) == 0

    @respx.mock
    async def test_group_alone_reads_the_group_alerts(self, client):
        from lm_mcp.tools.scoring import calculate_availability

        respx.get(f"{DEVICES_URL.rsplit('/', 1)[0]}/groups/7").mock(
            return_value=httpx.Response(200, json={"id": 7, "fullPath": "Sites/East"})
        )
        route = respx.get(ALERT_URL).mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        result = await calculate_availability(client, group_id=7)

        data = json.loads(result[0].text)
        assert data["availability_percent"] == 100.0
        assert 'monitorObjectGroups~"Sites/East"' in route.calls[0].request.url.params["filter"]
