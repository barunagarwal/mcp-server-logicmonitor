# Description: Tests for network intelligence MCP tools.
# Description: Validates interface metrics, top talkers, burst, flap, power event tools.

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
    return BearerAuth("test-token")


@pytest.fixture
def client(auth):
    return LogicMonitorClient(
        base_url="https://test.logicmonitor.com/santaba/rest",
        auth=auth,
        timeout=30,
        api_version=3,
    )


BASE = "https://test.logicmonitor.com/santaba/rest"


class TestGetInterfaceMetrics:
    @respx.mock
    async def test_returns_metrics_for_matching_interface(self, client):
        from lm_mcp.tools.networking import get_interface_metrics

        respx.get(f"{BASE}/device/devices/123/devicedatasources").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": 9001,
                            "dataSourceName": "SNMP_Network_Interfaces",
                            "instanceNumber": 24,
                        },
                        {
                            "id": 9002,
                            "dataSourceName": "CPU",
                            "instanceNumber": 1,
                        },
                    ]
                },
            )
        )
        respx.get(f"{BASE}/device/devices/123/devicedatasources/9001/instances").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {"id": 1, "name": "Gi0/1", "displayName": "Gi0/1 Uplink"},
                        {"id": 2, "name": "Gi0/2", "displayName": "Gi0/2"},
                    ]
                },
            )
        )
        respx.get(f"{BASE}/device/devices/123/devicedatasources/9001/instances/1/data").mock(
            return_value=httpx.Response(
                200,
                json={
                    "dataPoints": ["RxRate", "TxRate"],
                    "values": [[100.0, 200.0]],
                    "time": [1700000000000],
                },
            )
        )

        result = await get_interface_metrics(client, device_id=123, interface="Gi0/1")
        data = json.loads(result[0].text)

        assert data["resolved_datasource"] == "SNMP_Network_Interfaces"
        assert data["resolved_datasource_id"] == 9001
        assert data["resolved_instance_id"] == 1
        assert data["datapoints"] == ["RxRate", "TxRate"]

    @respx.mock
    async def test_returns_error_when_no_interface_datasource(self, client):
        from lm_mcp.tools.networking import get_interface_metrics

        respx.get(f"{BASE}/device/devices/456/devicedatasources").mock(
            return_value=httpx.Response(
                200,
                json={"items": [{"id": 1, "dataSourceName": "CPU"}]},
            )
        )

        result = await get_interface_metrics(client, device_id=456, interface="eth0")
        assert "No Interface-family DataSource found" in result[0].text

    @respx.mock
    async def test_returns_error_when_interface_not_matched(self, client):
        from lm_mcp.tools.networking import get_interface_metrics

        respx.get(f"{BASE}/device/devices/789/devicedatasources").mock(
            return_value=httpx.Response(
                200,
                json={"items": [{"id": 9001, "dataSourceName": "SNMP_Network_Interfaces"}]},
            )
        )
        respx.get(f"{BASE}/device/devices/789/devicedatasources/9001/instances").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {"id": 1, "name": "eth0", "displayName": "eth0"},
                    ]
                },
            )
        )

        result = await get_interface_metrics(client, device_id=789, interface="Gi99")
        assert "not found among instances" in result[0].text


class TestGetTopTalkers:
    @respx.mock
    async def test_ranks_by_bytes(self, client):
        from lm_mcp.tools.networking import get_top_talkers

        respx.get(f"{BASE}/netflow/flows").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {"srcIP": "10.0.0.1", "dstIP": "8.8.8.8", "bytes": 1000, "packets": 10},
                        {"srcIP": "10.0.0.1", "dstIP": "8.8.8.8", "bytes": 2000, "packets": 20},
                        {"srcIP": "10.0.0.2", "dstIP": "8.8.8.8", "bytes": 500, "packets": 5},
                    ]
                },
            )
        )

        result = await get_top_talkers(client, exporter_device_id=42, n=2, group_by="src_ip")
        data = json.loads(result[0].text)
        assert data["flows_analyzed"] == 3
        assert data["top_talkers"][0]["key"] == "10.0.0.1"
        assert data["top_talkers"][0]["total_bytes"] == 3000
        assert data["top_talkers"][0]["flow_count"] == 2

    async def test_rejects_invalid_group_by(self, client):
        from lm_mcp.tools.networking import get_top_talkers

        result = await get_top_talkers(client, exporter_device_id=42, group_by="invalid")
        assert "group_by must be one of" in result[0].text

    @respx.mock
    async def test_handles_empty_flows(self, client):
        from lm_mcp.tools.networking import get_top_talkers

        respx.get(f"{BASE}/netflow/flows").mock(
            return_value=httpx.Response(200, json={"items": []})
        )

        result = await get_top_talkers(client, exporter_device_id=42)
        data = json.loads(result[0].text)
        assert data["flows_analyzed"] == 0
        assert "No flows exported" in data["note"]

    @respx.mock
    async def test_group_by_src_dst_pair(self, client):
        from lm_mcp.tools.networking import get_top_talkers

        respx.get(f"{BASE}/netflow/flows").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {"srcIP": "10.0.0.1", "dstIP": "8.8.8.8", "bytes": 100, "packets": 1},
                        {"srcIP": "10.0.0.1", "dstIP": "8.8.8.8", "bytes": 200, "packets": 2},
                    ]
                },
            )
        )

        result = await get_top_talkers(client, exporter_device_id=42, group_by="src_dst_pair")
        data = json.loads(result[0].text)
        assert data["top_talkers"][0]["key"] == "10.0.0.1->8.8.8.8"
        assert data["top_talkers"][0]["total_bytes"] == 300


class TestDetectAlertBurst:
    @respx.mock
    async def test_detects_burst(self, client):
        from lm_mcp.tools.networking import detect_alert_burst

        now = int(time.time())
        # 10 alerts across 4 devices within 30 seconds, all same DataSource.
        alerts = [
            {
                "id": i,
                "startEpoch": now - 60 + i * 3,
                "dataSourceName": "SNMP_Network_Interfaces",
                "monitorObjectName": f"switch-{i % 4}",
            }
            for i in range(12)
        ]
        respx.get(f"{BASE}/alert/alerts").mock(
            return_value=httpx.Response(200, json={"items": alerts, "total": 12})
        )

        result = await detect_alert_burst(
            client,
            window_seconds=60,
            min_alerts=10,
            min_devices=3,
        )
        data = json.loads(result[0].text)
        assert data["total_alerts_in_window"] == 12
        assert data["bursts_detected"] >= 1
        assert data["bursts"][0]["datasource"] == "SNMP_Network_Interfaces"
        assert data["bursts"][0]["alert_count"] >= 10

    @respx.mock
    async def test_no_burst_when_below_threshold(self, client):
        from lm_mcp.tools.networking import detect_alert_burst

        now = int(time.time())
        alerts = [
            {
                "id": i,
                "startEpoch": now - 60 + i,
                "dataSourceName": "CPU",
                "monitorObjectName": f"host-{i}",
            }
            for i in range(5)
        ]
        respx.get(f"{BASE}/alert/alerts").mock(
            return_value=httpx.Response(200, json={"items": alerts, "total": 5})
        )

        result = await detect_alert_burst(client, window_seconds=60, min_alerts=10, min_devices=3)
        data = json.loads(result[0].text)
        assert data["bursts_detected"] == 0

    @respx.mock
    async def test_datasource_pattern_filter(self, client):
        from lm_mcp.tools.networking import detect_alert_burst

        now = int(time.time())
        alerts = [
            {
                "id": i,
                "startEpoch": now - 30 + i,
                "dataSourceName": "SNMP_Network_Interfaces" if i < 12 else "CPU",
                "monitorObjectName": f"dev-{i}",
            }
            for i in range(16)
        ]
        respx.get(f"{BASE}/alert/alerts").mock(
            return_value=httpx.Response(200, json={"items": alerts, "total": 16})
        )

        result = await detect_alert_burst(
            client,
            window_seconds=60,
            min_alerts=10,
            min_devices=3,
            datasource_pattern="interface",
        )
        data = json.loads(result[0].text)
        # Only interface alerts should qualify.
        assert data["total_alerts_in_window"] == 12


class TestDetectAlertBurstTruncation:
    """R4.2: detect_alert_burst warns only when the cap cut the window short."""

    @staticmethod
    def _alerts(n):
        now = int(time.time())
        return [
            {
                "id": i,
                "startEpoch": now - 3000 + (i % 3000),
                "dataSourceName": "CPU",
                "monitorObjectName": f"host-{i % 50}",
            }
            for i in range(n)
        ]

    @respx.mock
    async def test_warns_when_the_cap_binds(self, client):
        from lm_mcp.tools.networking import detect_alert_burst

        respx.get(f"{BASE}/alert/alerts").mock(
            side_effect=alert_pages(self._alerts(6000), lower_bound=True)
        )

        result = await detect_alert_burst(client)
        data = json.loads(result[0].text)
        assert data["total_alerts_in_window"] == 5000
        assert "Truncated at 5000 alerts" in data["warning"]

    @respx.mock
    async def test_no_warning_for_a_window_of_exactly_the_cap(self, client):
        from lm_mcp.tools.networking import detect_alert_burst

        respx.get(f"{BASE}/alert/alerts").mock(
            side_effect=alert_pages(self._alerts(5000), lower_bound=True)
        )

        result = await detect_alert_burst(client)
        data = json.loads(result[0].text)
        assert data["total_alerts_in_window"] == 5000
        assert "warning" not in data


class TestGetLinkFlaps:
    @respx.mock
    async def test_identifies_flapping_interfaces(self, client):
        from lm_mcp.tools.networking import get_link_flaps

        now = int(time.time())
        alerts = [
            {
                "id": i,
                "startEpoch": now - 3600 + i * 60,
                "dataSourceName": "SNMP_Network_Interfaces",
                "monitorObjectName": "sw1",
                "instanceName": "Gi0/1",
                "cleared": i % 2 == 0,
            }
            for i in range(6)
        ]
        respx.get(f"{BASE}/alert/alerts").mock(
            return_value=httpx.Response(200, json={"items": alerts, "total": 6})
        )

        result = await get_link_flaps(client, min_transitions=4)
        data = json.loads(result[0].text)
        assert data["flapping_interfaces"] >= 1
        top = data["results"][0]
        assert top["device"] == "sw1"
        assert top["interface"] == "Gi0/1"
        assert top["transitions"] >= 4

    @respx.mock
    async def test_no_flaps_when_below_threshold(self, client):
        from lm_mcp.tools.networking import get_link_flaps

        now = int(time.time())
        alerts = [
            {
                "id": 1,
                "startEpoch": now - 100,
                "dataSourceName": "SNMP_Network_Interfaces",
                "monitorObjectName": "sw1",
                "instanceName": "Gi0/1",
            }
        ]
        respx.get(f"{BASE}/alert/alerts").mock(
            return_value=httpx.Response(200, json={"items": alerts, "total": 1})
        )

        result = await get_link_flaps(client, min_transitions=4)
        data = json.loads(result[0].text)
        assert data["flapping_interfaces"] == 0


class TestGetPowerEvents:
    @respx.mock
    async def test_matches_default_patterns(self, client):
        from lm_mcp.tools.networking import get_power_events

        now = int(time.time())
        alerts = [
            {
                "id": 1,
                "severity": 4,
                "startEpoch": now - 100,
                "dataSourceName": "APC_UPS_Battery",
                "alertName": "UPS On Battery",
                "monitorObjectName": "ups-01",
                "dataPointName": "BatteryStatus",
            },
            {
                "id": 2,
                "severity": 3,
                "startEpoch": now - 200,
                "dataSourceName": "Liebert_UPS",
                "alertName": "Runtime Remaining Low",
                "monitorObjectName": "ups-02",
                "dataPointName": "RuntimeRemaining",
            },
            {
                "id": 3,
                "severity": 2,
                "startEpoch": now - 300,
                "dataSourceName": "CPU",
                "alertName": "CPU high",
                "monitorObjectName": "server-01",
                "dataPointName": "CpuPercent",
            },
        ]
        respx.get(f"{BASE}/alert/alerts").mock(
            return_value=httpx.Response(200, json={"items": alerts, "total": 3})
        )

        result = await get_power_events(client)
        data = json.loads(result[0].text)
        assert data["total_alerts_scanned"] == 3
        assert data["total_power_events"] == 2
        assert "ups" in data["patterns_matched_counts"]

    @respx.mock
    async def test_custom_patterns_override_defaults(self, client):
        from lm_mcp.tools.networking import get_power_events

        now = int(time.time())
        alerts = [
            {
                "id": 1,
                "startEpoch": now - 100,
                "dataSourceName": "CustomPowerSensor",
                "alertName": "Power loss",
                "monitorObjectName": "sensor-1",
            }
        ]
        respx.get(f"{BASE}/alert/alerts").mock(
            return_value=httpx.Response(200, json={"items": alerts, "total": 1})
        )

        result = await get_power_events(client, patterns=["customPower"])
        data = json.loads(result[0].text)
        assert data["total_power_events"] == 1

    @respx.mock
    async def test_no_matches_returns_empty(self, client):
        from lm_mcp.tools.networking import get_power_events

        now = int(time.time())
        alerts = [
            {
                "id": 1,
                "startEpoch": now - 100,
                "dataSourceName": "CPU",
                "alertName": "CPU high",
                "monitorObjectName": "server-01",
            }
        ]
        respx.get(f"{BASE}/alert/alerts").mock(
            return_value=httpx.Response(200, json={"items": alerts, "total": 1})
        )

        result = await get_power_events(client)
        data = json.loads(result[0].text)
        assert data["total_power_events"] == 0


class TestNetworkingErrorHandling:
    @respx.mock
    async def test_api_error_on_interface_lookup_returns_error(self, client):
        from lm_mcp.tools.networking import get_interface_metrics

        respx.get(f"{BASE}/device/devices/111/devicedatasources").mock(
            return_value=httpx.Response(500, json={"errorMessage": "boom"})
        )

        result = await get_interface_metrics(client, device_id=111, interface="eth0")
        # handle_error produces a readable error string.
        assert "Error" in result[0].text

    @respx.mock
    async def test_burst_tolerates_empty_alert_list(self, client):
        from lm_mcp.tools.networking import detect_alert_burst

        respx.get(f"{BASE}/alert/alerts").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        result = await detect_alert_burst(client)
        data = json.loads(result[0].text)
        assert data["bursts_detected"] == 0
        assert data["total_alerts_in_window"] == 0


class TestTopTalkersTruncation:
    """R4.2: the flow list is read as one page, so get_top_talkers says when it is partial."""

    @staticmethod
    def _flows(n):
        return [
            {"srcIP": f"10.0.{i // 250}.{i % 250}", "dstIP": "8.8.8.8", "bytes": 10, "packets": 1}
            for i in range(n)
        ]

    @respx.mock
    async def test_one_page_of_more_flows_declares_truncation_since_flows_are_not_paged(
        self, client
    ):
        from lm_mcp.tools.networking import get_top_talkers

        flows = self._flows(1500)
        route = respx.get(f"{BASE}/netflow/flows").mock(
            return_value=httpx.Response(200, json={"items": flows[:1000], "total": 1500})
        )

        result = await get_top_talkers(client, exporter_device_id=42)
        data = json.loads(result[0].text)
        assert data["flows_analyzed"] == 1000
        assert data["total_bytes_in_window"] == 10_000
        assert data["truncated"] is True
        assert data["api_total"] == 1500
        assert "offset" not in route.calls[0].request.url.params

    @respx.mock
    async def test_lower_bound_total_declares_truncation(self, client):
        from lm_mcp.tools.networking import get_top_talkers

        respx.get(f"{BASE}/netflow/flows").mock(
            return_value=httpx.Response(200, json={"items": self._flows(1000), "total": -1001})
        )

        result = await get_top_talkers(client, exporter_device_id=42)
        data = json.loads(result[0].text)
        assert data["truncated"] is True
        assert data["api_total"] is None

    @respx.mock
    async def test_full_page_without_a_total_declares_truncation(self, client):
        from lm_mcp.tools.networking import get_top_talkers

        respx.get(f"{BASE}/netflow/flows").mock(
            return_value=httpx.Response(200, json={"items": self._flows(1000)})
        )

        result = await get_top_talkers(client, exporter_device_id=42)
        data = json.loads(result[0].text)
        assert data["truncated"] is True
        assert data["api_total"] is None

    @respx.mock
    async def test_complete_window_is_not_truncated(self, client):
        from lm_mcp.tools.networking import get_top_talkers

        respx.get(f"{BASE}/netflow/flows").mock(
            return_value=httpx.Response(200, json={"items": self._flows(3), "total": 3})
        )

        result = await get_top_talkers(client, exporter_device_id=42)
        data = json.loads(result[0].text)
        assert data["truncated"] is False
        assert data["api_total"] == 3


def _interface_power_alerts(n):
    """Alerts that are both interface flaps and power events, spread over the last hour."""
    now = int(time.time())
    return [
        {
            "id": i,
            "startEpoch": now - 3000 + i % 2900,
            "dataSourceName": "SNMP_Network_Interfaces UPS",
            "alertName": "UPS on battery",
            "monitorObjectName": f"sw-{i % 40}",
            "instanceName": f"Gi0/{i % 8}",
            "cleared": True,
        }
        for i in range(n)
    ]


class TestCappedAlertToolsWarn:
    """R4.2: get_link_flaps and get_power_events carry detect_alert_burst's cap warning."""

    @pytest.mark.parametrize("tool_name", ["get_link_flaps", "get_power_events"])
    @respx.mock
    async def test_warns_when_the_cap_binds(self, client, tool_name):
        from lm_mcp.tools import networking
        from lm_mcp.tools.alerts import ALERT_WINDOW_TRUNCATED_WARNING

        respx.get(f"{BASE}/alert/alerts").mock(
            side_effect=alert_pages(_interface_power_alerts(6000), lower_bound=True)
        )

        result = await getattr(networking, tool_name)(client)
        data = json.loads(result[0].text)
        assert data["warning"] == ALERT_WINDOW_TRUNCATED_WARNING
        assert "Truncated at 5000 alerts" in data["warning"]

    @pytest.mark.parametrize("tool_name", ["get_link_flaps", "get_power_events"])
    @respx.mock
    async def test_no_warning_for_a_complete_window(self, client, tool_name):
        from lm_mcp.tools import networking

        respx.get(f"{BASE}/alert/alerts").mock(
            side_effect=alert_pages(_interface_power_alerts(5000), lower_bound=True)
        )

        result = await getattr(networking, tool_name)(client)
        data = json.loads(result[0].text)
        assert "warning" not in data
