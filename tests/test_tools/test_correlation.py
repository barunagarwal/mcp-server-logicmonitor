# Description: Tests for correlation analysis MCP tools.
# Description: Validates correlate_alerts, get_alert_statistics, get_metric_anomalies.

import json

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


def _make_alert(alert_id, device, datasource, severity=4, start_epoch=None):
    """Helper to create mock alert data."""
    return {
        "id": f"LMA{alert_id}",
        "severity": severity,
        "monitorObjectName": device,
        "resourceTemplateName": datasource,
        "alertValue": f"Alert {alert_id}",
        "startEpoch": start_epoch or BASE_EPOCH,
        "endEpoch": 0,
        "cleared": False,
    }


class TestCorrelateAlerts:
    """Tests for correlate_alerts tool."""

    @respx.mock
    async def test_basic_device_clustering(self, client):
        """Alerts from same device are grouped into a cluster."""
        from lm_mcp.tools.correlation import correlate_alerts

        respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        _make_alert(1, "server01", "CPU"),
                        _make_alert(2, "server01", "Memory"),
                        _make_alert(3, "server02", "CPU"),
                    ],
                    "total": 3,
                },
            )
        )

        result = await correlate_alerts(client)

        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["total_alerts"] == 3
        assert data["cluster_count"] > 0

        # Find the server01 device cluster
        device_clusters = [c for c in data["clusters"] if c["type"] == "device"]
        server01_cluster = [c for c in device_clusters if c["key"] == "server01"]
        assert len(server01_cluster) == 1
        assert server01_cluster[0]["count"] == 2

    @respx.mock
    async def test_datasource_clustering(self, client):
        """Alerts from same datasource across devices are grouped."""
        from lm_mcp.tools.correlation import correlate_alerts

        respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        _make_alert(1, "server01", "CPU"),
                        _make_alert(2, "server02", "CPU"),
                        _make_alert(3, "server03", "CPU"),
                    ],
                    "total": 3,
                },
            )
        )

        result = await correlate_alerts(client)

        data = json.loads(result[0].text)
        ds_clusters = [c for c in data["clusters"] if c["type"] == "datasource"]
        cpu_cluster = [c for c in ds_clusters if c["key"] == "CPU"]
        assert len(cpu_cluster) == 1
        assert cpu_cluster[0]["count"] == 3

    @respx.mock
    async def test_temporal_clustering(self, client):
        """Alerts starting within 5 minutes are grouped temporally."""
        from lm_mcp.tools.correlation import correlate_alerts

        respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        _make_alert(1, "server01", "CPU", start_epoch=BASE_EPOCH),
                        _make_alert(2, "server02", "Memory", start_epoch=BASE_EPOCH + 120),
                        # 2 hours later - separate temporal group
                        _make_alert(3, "server03", "Disk", start_epoch=BASE_EPOCH + 7200),
                    ],
                    "total": 3,
                },
            )
        )

        result = await correlate_alerts(client)

        data = json.loads(result[0].text)
        temporal_clusters = [c for c in data["clusters"] if c["type"] == "temporal"]
        # Should have at least one temporal cluster for the first two alerts
        assert len(temporal_clusters) >= 1

    @respx.mock
    async def test_with_severity_filter(self, client):
        """Severity filter is passed to the API."""
        from lm_mcp.tools.correlation import correlate_alerts

        route = respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        await correlate_alerts(client, severity="critical")

        params = dict(route.calls[0].request.url.params)
        assert "severity:4" in params.get("filter", "")

    @respx.mock
    async def test_with_device_filter(self, client):
        """Device filter is passed to the API."""
        from lm_mcp.tools.correlation import correlate_alerts

        route = respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        await correlate_alerts(client, device="server01")

        params = dict(route.calls[0].request.url.params)
        assert "monitorObjectName" in params.get("filter", "")

    @respx.mock
    async def test_with_group_id_filter(self, client):
        """Group ID filter resolves to monitorObjectGroups in the API call."""
        from lm_mcp.tools.correlation import correlate_alerts

        respx.get("https://test.logicmonitor.com/santaba/rest/device/groups/5").mock(
            return_value=httpx.Response(200, json={"id": 5, "fullPath": "Dev Portal/Test Group"})
        )
        route = respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        await correlate_alerts(client, group_id=5)

        params = dict(route.calls[0].request.url.params)
        assert 'monitorObjectGroups~"Dev Portal/Test Group"' in params.get("filter", "")

    @respx.mock
    async def test_empty_alerts(self, client):
        """Empty alert list returns zero clusters."""
        from lm_mcp.tools.correlation import correlate_alerts

        respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        result = await correlate_alerts(client)

        data = json.loads(result[0].text)
        assert data["total_alerts"] == 0
        assert data["cluster_count"] == 0
        assert data["clusters"] == []

    @respx.mock
    async def test_error_handling(self, client):
        """API errors are returned as error response."""
        from lm_mcp.tools.correlation import correlate_alerts

        respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=httpx.Response(401, json={"errorMessage": "Unauthorized"})
        )

        result = await correlate_alerts(client)

        assert len(result) == 1
        assert "Error:" in result[0].text

    @respx.mock
    async def test_hours_back_epoch_filter(self, client):
        """hours_back is converted to startEpoch filter."""
        from lm_mcp.tools.correlation import correlate_alerts

        route = respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        await correlate_alerts(client, hours_back=2)

        params = dict(route.calls[0].request.url.params)
        assert "startEpoch" in params.get("filter", "")

    @respx.mock
    async def test_limit_parameter(self, client):
        """Limit is passed as size parameter."""
        from lm_mcp.tools.correlation import correlate_alerts

        route = respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        await correlate_alerts(client, limit=100)

        params = dict(route.calls[0].request.url.params)
        assert params.get("size") == "100"

    @respx.mock
    async def test_time_window_in_response(self, client):
        """Response includes time_window_hours."""
        from lm_mcp.tools.correlation import correlate_alerts

        respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        result = await correlate_alerts(client, hours_back=6)

        data = json.loads(result[0].text)
        assert data["time_window_hours"] == 6


class TestGetAlertStatistics:
    """Tests for get_alert_statistics tool."""

    @respx.mock
    async def test_severity_aggregation(self, client):
        """Alerts are aggregated by severity."""
        from lm_mcp.tools.correlation import get_alert_statistics

        respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        _make_alert(1, "s1", "CPU", severity=4),
                        _make_alert(2, "s2", "CPU", severity=4),
                        _make_alert(3, "s3", "Mem", severity=3),
                        _make_alert(4, "s4", "Disk", severity=2),
                    ],
                    "total": 4,
                },
            )
        )

        result = await get_alert_statistics(client)

        data = json.loads(result[0].text)
        assert data["summary"]["total"] == 4
        assert data["summary"]["by_severity"]["critical"] == 2
        assert data["summary"]["by_severity"]["error"] == 1
        assert data["summary"]["by_severity"]["warning"] == 1

    @respx.mock
    async def test_device_aggregation(self, client):
        """Alerts are aggregated by device (top 10)."""
        from lm_mcp.tools.correlation import get_alert_statistics

        respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        _make_alert(1, "server01", "CPU"),
                        _make_alert(2, "server01", "Memory"),
                        _make_alert(3, "server01", "Disk"),
                        _make_alert(4, "server02", "CPU"),
                    ],
                    "total": 4,
                },
            )
        )

        result = await get_alert_statistics(client)

        data = json.loads(result[0].text)
        by_device = data["summary"]["by_device"]
        assert by_device[0]["device"] == "server01"
        assert by_device[0]["count"] == 3

    @respx.mock
    async def test_datasource_aggregation(self, client):
        """Alerts are aggregated by datasource (top 10)."""
        from lm_mcp.tools.correlation import get_alert_statistics

        respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        _make_alert(1, "s1", "CPU"),
                        _make_alert(2, "s2", "CPU"),
                        _make_alert(3, "s3", "Memory"),
                    ],
                    "total": 3,
                },
            )
        )

        result = await get_alert_statistics(client)

        data = json.loads(result[0].text)
        by_ds = data["summary"]["by_datasource"]
        assert by_ds[0]["datasource"] == "CPU"
        assert by_ds[0]["count"] == 2

    @respx.mock
    async def test_time_bucketing(self, client):
        """Alerts are bucketed by time intervals."""
        from lm_mcp.tools.correlation import get_alert_statistics

        respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        _make_alert(1, "s1", "CPU", start_epoch=BASE_EPOCH),
                        _make_alert(2, "s2", "CPU", start_epoch=BASE_EPOCH + 1800),
                        _make_alert(3, "s3", "Mem", start_epoch=BASE_EPOCH + 3700),
                    ],
                    "total": 3,
                },
            )
        )

        result = await get_alert_statistics(client, hours_back=3, bucket_size_hours=1)

        data = json.loads(result[0].text)
        assert "time_buckets" in data
        assert len(data["time_buckets"]) == 3

    @respx.mock
    async def test_custom_bucket_size(self, client):
        """Custom bucket_size_hours changes bucket count."""
        from lm_mcp.tools.correlation import get_alert_statistics

        respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        result = await get_alert_statistics(client, hours_back=6, bucket_size_hours=2)

        data = json.loads(result[0].text)
        assert len(data["time_buckets"]) == 3

    @respx.mock
    async def test_empty_result(self, client):
        """Empty alerts return zero-filled statistics."""
        from lm_mcp.tools.correlation import get_alert_statistics

        respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        result = await get_alert_statistics(client)

        data = json.loads(result[0].text)
        assert data["summary"]["total"] == 0
        assert data["summary"]["by_severity"]["critical"] == 0

    @respx.mock
    async def test_error_handling(self, client):
        """API errors are returned as error response."""
        from lm_mcp.tools.correlation import get_alert_statistics

        respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=httpx.Response(500, json={"errorMessage": "Server error"})
        )

        result = await get_alert_statistics(client)

        assert "Error:" in result[0].text

    @respx.mock
    async def test_with_device_filter(self, client):
        """Device filter is passed to API."""
        from lm_mcp.tools.correlation import get_alert_statistics

        route = respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        await get_alert_statistics(client, device="server01")

        params = dict(route.calls[0].request.url.params)
        assert "monitorObjectName" in params.get("filter", "")

    @respx.mock
    async def test_time_window_in_response(self, client):
        """Response includes time_window_hours."""
        from lm_mcp.tools.correlation import get_alert_statistics

        respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        result = await get_alert_statistics(client, hours_back=12)

        data = json.loads(result[0].text)
        assert data["time_window_hours"] == 12


ALERTS_URL = "https://test.logicmonitor.com/santaba/rest/alert/alerts"


def _paged_alerts(n):
    """Build n alerts spread over four devices and two datasources."""
    return [
        _make_alert(i, f"dev-{i % 4}", f"DS-{i % 2}", start_epoch=BASE_EPOCH + i) for i in range(n)
    ]


class TestAlertWindowPaging:
    """R4.2: alert statistics and correlation page through the window or say they stopped."""

    @respx.mock
    async def test_statistics_counts_every_page(self, client):
        from lm_mcp.tools.correlation import get_alert_statistics

        respx.get(ALERTS_URL).mock(side_effect=alert_pages(_paged_alerts(2500), lower_bound=True))

        result = await get_alert_statistics(client, limit=5000)

        summary = json.loads(result[0].text)["summary"]
        assert summary["total"] == 2500
        assert summary["truncated"] is False
        assert summary["api_total"] == 2500
        assert sum(d["count"] for d in summary["by_datasource"]) == 2500

    @respx.mock
    async def test_statistics_default_limit_declares_truncation(self, client):
        from lm_mcp.tools.correlation import get_alert_statistics

        respx.get(ALERTS_URL).mock(side_effect=alert_pages(_paged_alerts(2500), lower_bound=True))

        result = await get_alert_statistics(client)

        summary = json.loads(result[0].text)["summary"]
        assert summary["total"] == 1000
        assert summary["truncated"] is True
        assert summary["api_total"] is None

    @respx.mock
    async def test_correlate_alerts_declares_truncation_and_api_total(self, client):
        from lm_mcp.tools.correlation import correlate_alerts

        respx.get(ALERTS_URL).mock(side_effect=alert_pages(_paged_alerts(6000)))

        result = await correlate_alerts(client, limit=5000)

        data = json.loads(result[0].text)
        assert data["total_alerts"] == 5000
        assert data["truncated"] is True
        assert data["api_total"] == 6000

    @respx.mock
    async def test_correlate_alerts_complete_window(self, client):
        from lm_mcp.tools.correlation import correlate_alerts

        respx.get(ALERTS_URL).mock(side_effect=alert_pages(_paged_alerts(1500), lower_bound=True))

        result = await correlate_alerts(client, limit=5000)

        data = json.loads(result[0].text)
        assert data["total_alerts"] == 1500
        assert data["truncated"] is False
        assert data["api_total"] == 1500


class TestGetMetricAnomalies:
    """Tests for get_metric_anomalies tool."""

    @respx.mock
    async def test_normal_data_no_anomalies(self, client):
        """Normal data produces no anomalies."""
        from lm_mcp.tools.correlation import get_metric_anomalies

        respx.get(
            "https://test.logicmonitor.com/santaba/rest"
            "/device/devices/1/devicedatasources/10/instances/100/data"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "dataPoints": ["cpu"],
                    "values": [[50.0], [51.0], [49.0], [50.5], [50.2]],
                    "time": [BASE_EPOCH + i * 300 for i in range(5)],
                },
            )
        )

        result = await get_metric_anomalies(
            client, device_id=1, device_datasource_id=10, instance_id=100
        )

        data = json.loads(result[0].text)
        assert data["anomaly_count"] == 0
        assert data["total_datapoints_checked"] == 1

    @respx.mock
    async def test_data_with_obvious_outlier(self, client):
        """Obvious outlier is detected as anomaly."""
        from lm_mcp.tools.correlation import get_metric_anomalies

        # 9 normal values around 50, one extreme spike at 200
        respx.get(
            "https://test.logicmonitor.com/santaba/rest"
            "/device/devices/1/devicedatasources/10/instances/100/data"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "dataPoints": ["cpu"],
                    "values": [
                        [50.0],
                        [51.0],
                        [49.0],
                        [50.0],
                        [50.5],
                        [49.5],
                        [50.2],
                        [50.1],
                        [49.8],
                        [200.0],
                    ],
                    "time": [BASE_EPOCH + i * 300 for i in range(10)],
                },
            )
        )

        result = await get_metric_anomalies(
            client, device_id=1, device_datasource_id=10, instance_id=100
        )

        data = json.loads(result[0].text)
        assert data["anomaly_count"] >= 1
        assert any(a["datapoint"] == "cpu" for a in data["anomalies"])

    @respx.mock
    async def test_custom_threshold(self, client):
        """Higher threshold reduces anomaly sensitivity."""
        from lm_mcp.tools.correlation import get_metric_anomalies

        # Moderate outlier that passes at threshold=5 but fails at threshold=1
        respx.get(
            "https://test.logicmonitor.com/santaba/rest"
            "/device/devices/1/devicedatasources/10/instances/100/data"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "dataPoints": ["cpu"],
                    "values": [[50.0], [51.0], [49.0], [50.0], [55.0]],
                    "time": [BASE_EPOCH + i * 300 for i in range(5)],
                },
            )
        )

        # With high threshold, the slight deviation should not be anomalous
        result = await get_metric_anomalies(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
            threshold=5.0,
        )

        data = json.loads(result[0].text)
        assert data["anomaly_count"] == 0

    @respx.mock
    async def test_multiple_datapoints(self, client):
        """Multiple datapoints are each checked independently."""
        from lm_mcp.tools.correlation import get_metric_anomalies

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
                        [51.0, 71.0],
                        [49.0, 69.0],
                        [50.0, 70.0],
                        [50.5, 70.5],
                    ],
                    "time": [BASE_EPOCH + i * 300 for i in range(5)],
                },
            )
        )

        result = await get_metric_anomalies(
            client, device_id=1, device_datasource_id=10, instance_id=100
        )

        data = json.loads(result[0].text)
        assert data["total_datapoints_checked"] == 2

    @respx.mock
    async def test_empty_data(self, client):
        """Empty metric data returns zero anomalies."""
        from lm_mcp.tools.correlation import get_metric_anomalies

        respx.get(
            "https://test.logicmonitor.com/santaba/rest"
            "/device/devices/1/devicedatasources/10/instances/100/data"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "dataPoints": [],
                    "values": [],
                    "time": [],
                },
            )
        )

        result = await get_metric_anomalies(
            client, device_id=1, device_datasource_id=10, instance_id=100
        )

        data = json.loads(result[0].text)
        assert data["anomaly_count"] == 0
        assert data["total_datapoints_checked"] == 0

    @respx.mock
    async def test_constant_data_stddev_zero(self, client):
        """Constant data (stddev=0) does not produce false anomalies."""
        from lm_mcp.tools.correlation import get_metric_anomalies

        respx.get(
            "https://test.logicmonitor.com/santaba/rest"
            "/device/devices/1/devicedatasources/10/instances/100/data"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "dataPoints": ["cpu"],
                    "values": [[50.0], [50.0], [50.0], [50.0], [50.0]],
                    "time": [BASE_EPOCH + i * 300 for i in range(5)],
                },
            )
        )

        result = await get_metric_anomalies(
            client, device_id=1, device_datasource_id=10, instance_id=100
        )

        data = json.loads(result[0].text)
        assert data["anomaly_count"] == 0

    @respx.mock
    async def test_single_data_point_skipped(self, client):
        """Single data point is skipped (cannot compute stats)."""
        from lm_mcp.tools.correlation import get_metric_anomalies

        respx.get(
            "https://test.logicmonitor.com/santaba/rest"
            "/device/devices/1/devicedatasources/10/instances/100/data"
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

        result = await get_metric_anomalies(
            client, device_id=1, device_datasource_id=10, instance_id=100
        )

        data = json.loads(result[0].text)
        assert data["anomaly_count"] == 0

    @respx.mock
    async def test_error_handling(self, client):
        """API errors are returned as error response."""
        from lm_mcp.tools.correlation import get_metric_anomalies

        respx.get(
            "https://test.logicmonitor.com/santaba/rest"
            "/device/devices/1/devicedatasources/10/instances/100/data"
        ).mock(return_value=httpx.Response(404, json={"errorMessage": "Not found"}))

        result = await get_metric_anomalies(
            client, device_id=1, device_datasource_id=10, instance_id=100
        )

        assert "Error:" in result[0].text

    @respx.mock
    async def test_hours_back_time_window(self, client):
        """hours_back param sets start time in request."""
        from lm_mcp.tools.correlation import get_metric_anomalies

        route = respx.get(
            "https://test.logicmonitor.com/santaba/rest"
            "/device/devices/1/devicedatasources/10/instances/100/data"
        ).mock(
            return_value=httpx.Response(
                200,
                json={"dataPoints": [], "values": [], "time": []},
            )
        )

        await get_metric_anomalies(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
            hours_back=12,
        )

        params = dict(route.calls[0].request.url.params)
        assert "start" in params

    @respx.mock
    async def test_response_includes_device_id(self, client):
        """Response includes the device_id for context."""
        from lm_mcp.tools.correlation import get_metric_anomalies

        respx.get(
            "https://test.logicmonitor.com/santaba/rest"
            "/device/devices/42/devicedatasources/10/instances/100/data"
        ).mock(
            return_value=httpx.Response(
                200,
                json={"dataPoints": [], "values": [], "time": []},
            )
        )

        result = await get_metric_anomalies(
            client, device_id=42, device_datasource_id=10, instance_id=100
        )

        data = json.loads(result[0].text)
        assert data["device_id"] == 42

    @respx.mock
    async def test_anomaly_includes_z_score(self, client):
        """Detected anomalies include z_score and statistics."""
        from lm_mcp.tools.correlation import get_metric_anomalies

        respx.get(
            "https://test.logicmonitor.com/santaba/rest"
            "/device/devices/1/devicedatasources/10/instances/100/data"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "dataPoints": ["cpu"],
                    "values": [
                        [50.0],
                        [50.0],
                        [50.0],
                        [50.0],
                        [50.0],
                        [50.0],
                        [50.0],
                        [50.0],
                        [50.0],
                        [200.0],
                    ],
                    "time": [BASE_EPOCH + i * 300 for i in range(10)],
                },
            )
        )

        result = await get_metric_anomalies(
            client, device_id=1, device_datasource_id=10, instance_id=100
        )

        data = json.loads(result[0].text)
        assert data["anomaly_count"] >= 1
        anomaly = data["anomalies"][0]
        assert "z_score" in anomaly
        assert "mean" in anomaly
        assert "stddev" in anomaly
        assert "value" in anomaly
        assert "timestamp" in anomaly


class TestGetMetricAnomaliesMethod:
    """Tests for get_metric_anomalies method parameter."""

    @respx.mock
    async def test_method_auto_present_in_output(self, client):
        """Auto-selected method is included in output."""
        from lm_mcp.tools.correlation import get_metric_anomalies

        respx.get(
            "https://test.logicmonitor.com/santaba/rest"
            "/device/devices/1/devicedatasources/10/instances/100/data"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "dataPoints": ["cpu"],
                    "values": [[50.0], [51.0], [49.0], [50.5], [50.2]],
                    "time": [BASE_EPOCH + i * 300 for i in range(5)],
                },
            )
        )

        result = await get_metric_anomalies(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
        )

        data = json.loads(result[0].text)
        assert "method_used" in data
        assert data["method_used"] in ("zscore", "iqr", "mad")

    @respx.mock
    async def test_method_iqr_explicit(self, client):
        """Explicit IQR method is used when requested."""
        from lm_mcp.tools.correlation import get_metric_anomalies

        # Data with an outlier that IQR should catch
        respx.get(
            "https://test.logicmonitor.com/santaba/rest"
            "/device/devices/1/devicedatasources/10/instances/100/data"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "dataPoints": ["cpu"],
                    "values": [
                        [50.0],
                        [51.0],
                        [49.0],
                        [50.0],
                        [50.5],
                        [49.5],
                        [50.2],
                        [50.1],
                        [49.8],
                        [200.0],
                    ],
                    "time": [BASE_EPOCH + i * 300 for i in range(10)],
                },
            )
        )

        result = await get_metric_anomalies(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
            method="iqr",
        )

        data = json.loads(result[0].text)
        assert data["method_used"] == "iqr"
        assert data["anomaly_count"] >= 1

    @respx.mock
    async def test_method_mad_explicit(self, client):
        """Explicit MAD method is used when requested."""
        from lm_mcp.tools.correlation import get_metric_anomalies

        # Use data with variation so MAD is nonzero, plus an extreme outlier
        respx.get(
            "https://test.logicmonitor.com/santaba/rest"
            "/device/devices/1/devicedatasources/10/instances/100/data"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "dataPoints": ["cpu"],
                    "values": [
                        [50.0],
                        [52.0],
                        [48.0],
                        [51.0],
                        [49.0],
                        [50.5],
                        [49.5],
                        [51.5],
                        [48.5],
                        [200.0],
                    ],
                    "time": [BASE_EPOCH + i * 300 for i in range(10)],
                },
            )
        )

        result = await get_metric_anomalies(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
            method="mad",
        )

        data = json.loads(result[0].text)
        assert data["method_used"] == "mad"
        assert data["anomaly_count"] >= 1

    @respx.mock
    async def test_data_quality_in_output(self, client):
        """Output includes data_quality assessment."""
        from lm_mcp.tools.correlation import get_metric_anomalies

        respx.get(
            "https://test.logicmonitor.com/santaba/rest"
            "/device/devices/1/devicedatasources/10/instances/100/data"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "dataPoints": ["cpu"],
                    "values": [[50.0], [51.0], [49.0]],
                    "time": [BASE_EPOCH + i * 300 for i in range(3)],
                },
            )
        )

        result = await get_metric_anomalies(
            client,
            device_id=1,
            device_datasource_id=10,
            instance_id=100,
        )

        data = json.loads(result[0].text)
        assert "data_quality" in data
        assert data["data_quality"] in ("insufficient", "limited", "good")


class TestCorrelateMetrics:
    """Tests for correlate_metrics tool."""

    @respx.mock
    async def test_perfect_positive_correlation(self, client):
        """Perfectly correlated metrics return r=1."""
        from lm_mcp.tools.correlation import correlate_metrics

        for dev_id in [1, 2]:
            respx.get(
                f"https://test.logicmonitor.com/santaba/rest"
                f"/device/devices/{dev_id}/devicedatasources/10/instances/100/data"
            ).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "dataPoints": ["cpu"],
                        "values": [[float(10 + i * 5)] for i in range(10)],
                        "time": [(BASE_EPOCH + i * 300) * 1000 for i in range(10)],
                    },
                )
            )

        sources = [
            {"device_id": 1, "device_datasource_id": 10, "instance_id": 100, "datapoint": "cpu"},
            {"device_id": 2, "device_datasource_id": 10, "instance_id": 100, "datapoint": "cpu"},
        ]

        result = await correlate_metrics(client, sources=sources)

        data = json.loads(result[0].text)
        assert data["correlation_matrix"][0][1] == 1.0
        assert len(data["strong_correlations"]) > 0

    @respx.mock
    async def test_negative_correlation(self, client):
        """Inversely correlated metrics return negative r."""
        from lm_mcp.tools.correlation import correlate_metrics

        respx.get(
            "https://test.logicmonitor.com/santaba/rest"
            "/device/devices/1/devicedatasources/10/instances/100/data"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "dataPoints": ["cpu"],
                    "values": [[float(10 + i * 5)] for i in range(10)],
                    "time": [(BASE_EPOCH + i * 300) * 1000 for i in range(10)],
                },
            )
        )
        respx.get(
            "https://test.logicmonitor.com/santaba/rest"
            "/device/devices/2/devicedatasources/10/instances/100/data"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "dataPoints": ["cpu"],
                    "values": [[float(100 - i * 5)] for i in range(10)],
                    "time": [(BASE_EPOCH + i * 300) * 1000 for i in range(10)],
                },
            )
        )

        sources = [
            {"device_id": 1, "device_datasource_id": 10, "instance_id": 100, "datapoint": "cpu"},
            {"device_id": 2, "device_datasource_id": 10, "instance_id": 100, "datapoint": "cpu"},
        ]

        result = await correlate_metrics(client, sources=sources)

        data = json.loads(result[0].text)
        assert data["correlation_matrix"][0][1] < -0.7

    @respx.mock
    async def test_too_many_sources_rejected(self, client):
        """More than 10 sources returns error."""
        from lm_mcp.tools.correlation import correlate_metrics

        sources = [
            {"device_id": i, "device_datasource_id": 10, "instance_id": 100, "datapoint": "cpu"}
            for i in range(11)
        ]

        result = await correlate_metrics(client, sources=sources)

        assert "Error:" in result[0].text or "Maximum 10" in result[0].text

    @respx.mock
    async def test_fewer_than_two_sources_rejected(self, client):
        """Fewer than 2 sources returns error."""
        from lm_mcp.tools.correlation import correlate_metrics

        sources = [
            {"device_id": 1, "device_datasource_id": 10, "instance_id": 100, "datapoint": "cpu"},
        ]

        result = await correlate_metrics(client, sources=sources)

        assert "Error:" in result[0].text or "At least 2" in result[0].text

    @respx.mock
    async def test_diagonal_is_one(self, client):
        """Diagonal of correlation matrix is all 1.0."""
        from lm_mcp.tools.correlation import correlate_metrics

        for dev_id in [1, 2, 3]:
            respx.get(
                f"https://test.logicmonitor.com/santaba/rest"
                f"/device/devices/{dev_id}/devicedatasources/10/instances/100/data"
            ).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "dataPoints": ["cpu"],
                        "values": [[float(10 + i + dev_id)] for i in range(10)],
                        "time": [(BASE_EPOCH + i * 300) * 1000 for i in range(10)],
                    },
                )
            )

        sources = [
            {"device_id": d, "device_datasource_id": 10, "instance_id": 100, "datapoint": "cpu"}
            for d in [1, 2, 3]
        ]

        result = await correlate_metrics(client, sources=sources)

        data = json.loads(result[0].text)
        for i in range(3):
            assert data["correlation_matrix"][i][i] == 1.0

    @respx.mock
    async def test_response_includes_labels(self, client):
        """Response includes labels for each source."""
        from lm_mcp.tools.correlation import correlate_metrics

        for dev_id in [1, 2]:
            respx.get(
                f"https://test.logicmonitor.com/santaba/rest"
                f"/device/devices/{dev_id}/devicedatasources/10/instances/100/data"
            ).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "dataPoints": ["cpu"],
                        "values": [[50.0 + i] for i in range(5)],
                        "time": [(BASE_EPOCH + i * 300) * 1000 for i in range(5)],
                    },
                )
            )

        sources = [
            {"device_id": 1, "device_datasource_id": 10, "instance_id": 100, "datapoint": "cpu"},
            {"device_id": 2, "device_datasource_id": 10, "instance_id": 100, "datapoint": "cpu"},
        ]

        result = await correlate_metrics(client, sources=sources)

        data = json.loads(result[0].text)
        assert "labels" in data
        assert len(data["labels"]) == 2

    @respx.mock
    async def test_sample_count_in_response(self, client):
        """Response includes the sample count used for correlation."""
        from lm_mcp.tools.correlation import correlate_metrics

        for dev_id in [1, 2]:
            respx.get(
                f"https://test.logicmonitor.com/santaba/rest"
                f"/device/devices/{dev_id}/devicedatasources/10/instances/100/data"
            ).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "dataPoints": ["cpu"],
                        "values": [[50.0 + i] for i in range(8)],
                        "time": [(BASE_EPOCH + i * 300) * 1000 for i in range(8)],
                    },
                )
            )

        sources = [
            {"device_id": 1, "device_datasource_id": 10, "instance_id": 100, "datapoint": "cpu"},
            {"device_id": 2, "device_datasource_id": 10, "instance_id": 100, "datapoint": "cpu"},
        ]

        result = await correlate_metrics(client, sources=sources)

        data = json.loads(result[0].text)
        assert data["sample_count"] == 8

    @respx.mock
    async def test_insufficient_data(self, client):
        """Insufficient overlapping data returns error."""
        from lm_mcp.tools.correlation import correlate_metrics

        for dev_id in [1, 2]:
            respx.get(
                f"https://test.logicmonitor.com/santaba/rest"
                f"/device/devices/{dev_id}/devicedatasources/10/instances/100/data"
            ).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "dataPoints": ["cpu"],
                        "values": [[50.0]],
                        "time": [BASE_EPOCH * 1000],
                    },
                )
            )

        sources = [
            {"device_id": 1, "device_datasource_id": 10, "instance_id": 100, "datapoint": "cpu"},
            {"device_id": 2, "device_datasource_id": 10, "instance_id": 100, "datapoint": "cpu"},
        ]

        result = await correlate_metrics(client, sources=sources)

        assert "Insufficient" in result[0].text or "Error:" in result[0].text

    @respx.mock
    async def test_error_handling(self, client):
        """API errors are returned as error response."""
        from lm_mcp.tools.correlation import correlate_metrics

        respx.get(
            "https://test.logicmonitor.com/santaba/rest"
            "/device/devices/1/devicedatasources/10/instances/100/data"
        ).mock(return_value=httpx.Response(500, json={"errorMessage": "error"}))

        sources = [
            {"device_id": 1, "device_datasource_id": 10, "instance_id": 100, "datapoint": "cpu"},
            {"device_id": 2, "device_datasource_id": 10, "instance_id": 100, "datapoint": "cpu"},
        ]

        result = await correlate_metrics(client, sources=sources)

        assert "Error:" in result[0].text
