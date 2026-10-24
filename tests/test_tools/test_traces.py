# Description: Tests for APM trace tools.
# Description: Validates service discovery, metrics, alerts, and property retrieval.

import json

import httpx
import pytest
import respx

from lm_mcp.auth.bearer import BearerAuth
from lm_mcp.client import LogicMonitorClient


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


# --- get_trace_services ---


class TestGetTraceServices:
    """Tests for get_trace_services tool."""

    @respx.mock
    async def test_returns_service_list(self, client):
        """get_trace_services returns APM service devices."""
        from lm_mcp.tools.traces import get_trace_services

        respx.get("https://test.logicmonitor.com/santaba/rest/device/devices").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": 101,
                            "displayName": "order-service",
                            "name": "order-service",
                            "hostGroupIds": "1,2",
                        },
                        {
                            "id": 102,
                            "displayName": "payment-service",
                            "name": "payment-service",
                            "hostGroupIds": "1",
                        },
                    ],
                    "total": 2,
                },
            )
        )

        result = await get_trace_services(client)

        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["total"] == 2
        assert len(data["services"]) == 2
        assert data["services"][0]["name"] == "order-service"
        assert data["services"][1]["name"] == "payment-service"

    @respx.mock
    async def test_filters_by_devicetype_6(self, client):
        """get_trace_services sends deviceType:6 filter."""
        from lm_mcp.tools.traces import get_trace_services

        route = respx.get("https://test.logicmonitor.com/santaba/rest/device/devices").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        await get_trace_services(client)

        params = route.calls[0].request.url.params
        assert "deviceType:6" in params["filter"]

    @respx.mock
    async def test_with_namespace_filter(self, client):
        """get_trace_services applies namespace filter."""
        from lm_mcp.tools.traces import get_trace_services

        route = respx.get("https://test.logicmonitor.com/santaba/rest/device/devices").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        await get_trace_services(client, namespace="order")

        params = route.calls[0].request.url.params
        assert "deviceType:6" in params["filter"]
        assert "displayName" in params["filter"]

    @respx.mock
    async def test_empty_results(self, client):
        """get_trace_services handles empty result set."""
        from lm_mcp.tools.traces import get_trace_services

        respx.get("https://test.logicmonitor.com/santaba/rest/device/devices").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        result = await get_trace_services(client)

        data = json.loads(result[0].text)
        assert data["total"] == 0
        assert data["services"] == []

    @respx.mock
    async def test_handles_error(self, client):
        """get_trace_services handles API error."""
        from lm_mcp.tools.traces import get_trace_services

        respx.get("https://test.logicmonitor.com/santaba/rest/device/devices").mock(
            return_value=httpx.Response(500, json={"errorMessage": "Internal error"})
        )

        result = await get_trace_services(client)

        assert "Error:" in result[0].text


# --- get_trace_service ---


class TestGetTraceService:
    """Tests for get_trace_service tool."""

    @respx.mock
    async def test_returns_service_detail(self, client):
        """get_trace_service returns full device detail."""
        from lm_mcp.tools.traces import get_trace_service

        respx.get("https://test.logicmonitor.com/santaba/rest/device/devices/101").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 101,
                    "displayName": "order-service",
                    "name": "order-service",
                    "deviceType": 6,
                    "hostStatus": "normal",
                },
            )
        )

        result = await get_trace_service(client, service_id=101)

        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["id"] == 101
        assert data["displayName"] == "order-service"

    @respx.mock
    async def test_handles_not_found(self, client):
        """get_trace_service handles 404 for missing service."""
        from lm_mcp.tools.traces import get_trace_service

        respx.get("https://test.logicmonitor.com/santaba/rest/device/devices/999").mock(
            return_value=httpx.Response(404, json={"errorMessage": "Device not found"})
        )

        result = await get_trace_service(client, service_id=999)

        assert "Error:" in result[0].text


# --- get_trace_service_alerts ---


class TestGetTraceServiceAlerts:
    """Tests for get_trace_service_alerts tool."""

    @respx.mock
    async def test_returns_alerts(self, client):
        """get_trace_service_alerts returns active alerts."""
        from lm_mcp.tools.traces import get_trace_service_alerts

        respx.get("https://test.logicmonitor.com/santaba/rest/device/devices/101/alerts").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "LMA5001",
                            "severity": 4,
                            "monitorObjectName": "order-service",
                            "dataPointName": "Duration",
                            "alertValue": "500",
                        }
                    ],
                    "total": 1,
                },
            )
        )

        result = await get_trace_service_alerts(client, service_id=101)

        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["service_id"] == 101
        assert data["total"] == 1
        assert len(data["alerts"]) == 1

    @respx.mock
    async def test_with_severity_filter(self, client):
        """get_trace_service_alerts filters by severity."""
        from lm_mcp.tools.traces import get_trace_service_alerts

        route = respx.get(
            "https://test.logicmonitor.com/santaba/rest/device/devices/101/alerts"
        ).mock(return_value=httpx.Response(200, json={"items": [], "total": 0}))

        await get_trace_service_alerts(client, service_id=101, severity="critical")

        params = route.calls[0].request.url.params
        assert "filter" in params
        assert "severity:4" in params["filter"]

    @respx.mock
    async def test_empty_alerts(self, client):
        """get_trace_service_alerts handles no alerts."""
        from lm_mcp.tools.traces import get_trace_service_alerts

        respx.get("https://test.logicmonitor.com/santaba/rest/device/devices/101/alerts").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        result = await get_trace_service_alerts(client, service_id=101)

        data = json.loads(result[0].text)
        assert data["total"] == 0
        assert data["alerts"] == []

    @respx.mock
    async def test_handles_error(self, client):
        """get_trace_service_alerts handles API error."""
        from lm_mcp.tools.traces import get_trace_service_alerts

        respx.get("https://test.logicmonitor.com/santaba/rest/device/devices/999/alerts").mock(
            return_value=httpx.Response(404, json={"errorMessage": "Device not found"})
        )

        result = await get_trace_service_alerts(client, service_id=999)

        assert "Error:" in result[0].text


# --- get_trace_service_datasources ---


class TestGetTraceServiceDatasources:
    """Tests for get_trace_service_datasources tool."""

    @respx.mock
    async def test_returns_datasources(self, client):
        """get_trace_service_datasources returns applied datasources."""
        from lm_mcp.tools.traces import get_trace_service_datasources

        respx.get(
            "https://test.logicmonitor.com/santaba/rest/device/devices/101/devicedatasources"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": 2001,
                            "dataSourceId": 500,
                            "dataSourceName": "LogicMonitor_APM_Services",
                            "instanceNumber": 1,
                            "monitoringInstanceNumber": 1,
                        },
                        {
                            "id": 2002,
                            "dataSourceId": 501,
                            "dataSourceName": "LogicMonitor_APM_Operations",
                            "instanceNumber": 5,
                            "monitoringInstanceNumber": 5,
                        },
                    ],
                    "total": 2,
                },
            )
        )

        result = await get_trace_service_datasources(client, service_id=101)

        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["service_id"] == 101
        assert data["total"] == 2
        assert len(data["datasources"]) == 2
        assert data["datasources"][0]["name"] == "LogicMonitor_APM_Services"

    @respx.mock
    async def test_with_name_filter(self, client):
        """get_trace_service_datasources passes name filter."""
        from lm_mcp.tools.traces import get_trace_service_datasources

        route = respx.get(
            "https://test.logicmonitor.com/santaba/rest/device/devices/101/devicedatasources"
        ).mock(return_value=httpx.Response(200, json={"items": [], "total": 0}))

        await get_trace_service_datasources(client, service_id=101, name_filter="APM")

        params = route.calls[0].request.url.params
        assert "filter" in params

    @respx.mock
    async def test_empty_results(self, client):
        """get_trace_service_datasources handles empty results."""
        from lm_mcp.tools.traces import get_trace_service_datasources

        respx.get(
            "https://test.logicmonitor.com/santaba/rest/device/devices/101/devicedatasources"
        ).mock(return_value=httpx.Response(200, json={"items": [], "total": 0}))

        result = await get_trace_service_datasources(client, service_id=101)

        data = json.loads(result[0].text)
        assert data["total"] == 0
        assert data["datasources"] == []

    @respx.mock
    async def test_handles_error(self, client):
        """get_trace_service_datasources handles API error."""
        from lm_mcp.tools.traces import get_trace_service_datasources

        respx.get(
            "https://test.logicmonitor.com/santaba/rest/device/devices/999/devicedatasources"
        ).mock(return_value=httpx.Response(404, json={"errorMessage": "Device not found"}))

        result = await get_trace_service_datasources(client, service_id=999)

        assert "Error:" in result[0].text


# --- get_trace_operations ---


class TestGetTraceOperations:
    """Tests for get_trace_operations tool."""

    @respx.mock
    async def test_returns_operations(self, client):
        """get_trace_operations returns operation instances."""
        from lm_mcp.tools.traces import get_trace_operations

        respx.get(
            "https://test.logicmonitor.com/santaba/rest/device/devices/101/devicedatasources/2002/instances"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": 3001,
                            "displayName": "/get-quote",
                            "description": "GET quote endpoint",
                            "groupName": "",
                            "lockDescription": False,
                            "stopMonitoring": False,
                        },
                        {
                            "id": 3002,
                            "displayName": "/ship-order",
                            "description": "POST ship order",
                            "groupName": "",
                            "lockDescription": False,
                            "stopMonitoring": False,
                        },
                    ],
                    "total": 2,
                },
            )
        )

        result = await get_trace_operations(client, service_id=101, device_datasource_id=2002)

        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["service_id"] == 101
        assert data["device_datasource_id"] == 2002
        assert data["total"] == 2
        assert len(data["operations"]) == 2
        assert data["operations"][0]["name"] == "/get-quote"

    @respx.mock
    async def test_with_name_filter(self, client):
        """get_trace_operations passes name filter."""
        from lm_mcp.tools.traces import get_trace_operations

        route = respx.get(
            "https://test.logicmonitor.com/santaba/rest/device/devices/101/devicedatasources/2002/instances"
        ).mock(return_value=httpx.Response(200, json={"items": [], "total": 0}))

        await get_trace_operations(
            client,
            service_id=101,
            device_datasource_id=2002,
            name_filter="quote",
        )

        params = route.calls[0].request.url.params
        assert "filter" in params

    @respx.mock
    async def test_empty_results(self, client):
        """get_trace_operations handles empty results."""
        from lm_mcp.tools.traces import get_trace_operations

        respx.get(
            "https://test.logicmonitor.com/santaba/rest/device/devices/101/devicedatasources/2002/instances"
        ).mock(return_value=httpx.Response(200, json={"items": [], "total": 0}))

        result = await get_trace_operations(client, service_id=101, device_datasource_id=2002)

        data = json.loads(result[0].text)
        assert data["total"] == 0
        assert data["operations"] == []

    @respx.mock
    async def test_handles_error(self, client):
        """get_trace_operations handles API error."""
        from lm_mcp.tools.traces import get_trace_operations

        respx.get(
            "https://test.logicmonitor.com/santaba/rest/device/devices/999/devicedatasources/9999/instances"
        ).mock(return_value=httpx.Response(404, json={"errorMessage": "Not found"}))

        result = await get_trace_operations(client, service_id=999, device_datasource_id=9999)

        assert "Error:" in result[0].text


# --- get_trace_service_metrics ---


class TestGetTraceServiceMetrics:
    """Tests for get_trace_service_metrics tool."""

    @respx.mock
    async def test_returns_metrics(self, client):
        """get_trace_service_metrics returns time-series data."""
        from lm_mcp.tools.traces import get_trace_service_metrics

        respx.get(
            "https://test.logicmonitor.com/santaba/rest/device/devices/101/devicedatasources/2001/instances/3001/data"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "dataPoints": [
                        "Duration",
                        "ErrorOperationCount",
                        "OperationCount",
                    ],
                    "values": {
                        "Duration": [120.5, 130.2, 115.8],
                        "ErrorOperationCount": [0, 1, 0],
                        "OperationCount": [50, 55, 48],
                    },
                    "time": [1702500000, 1702500060, 1702500120],
                },
            )
        )

        result = await get_trace_service_metrics(
            client,
            service_id=101,
            device_datasource_id=2001,
            instance_id=3001,
        )

        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["service_id"] == 101
        assert "Duration" in data["datapoints"]
        assert len(data["time"]) == 3

    @respx.mock
    async def test_with_time_range(self, client):
        """get_trace_service_metrics passes time range params."""
        from lm_mcp.tools.traces import get_trace_service_metrics

        route = respx.get(
            "https://test.logicmonitor.com/santaba/rest/device/devices/101/devicedatasources/2001/instances/3001/data"
        ).mock(
            return_value=httpx.Response(
                200,
                json={"dataPoints": [], "values": {}, "time": []},
            )
        )

        await get_trace_service_metrics(
            client,
            service_id=101,
            device_datasource_id=2001,
            instance_id=3001,
            start_time=1702500000,
            end_time=1702503600,
        )

        params = route.calls[0].request.url.params
        assert "start" in params
        assert "end" in params

    @respx.mock
    async def test_with_datapoints_filter(self, client):
        """get_trace_service_metrics passes datapoints filter."""
        from lm_mcp.tools.traces import get_trace_service_metrics

        route = respx.get(
            "https://test.logicmonitor.com/santaba/rest/device/devices/101/devicedatasources/2001/instances/3001/data"
        ).mock(
            return_value=httpx.Response(
                200,
                json={"dataPoints": [], "values": {}, "time": []},
            )
        )

        await get_trace_service_metrics(
            client,
            service_id=101,
            device_datasource_id=2001,
            instance_id=3001,
            datapoints="Duration,OperationCount",
        )

        params = route.calls[0].request.url.params
        assert "datapoints" in params

    @respx.mock
    async def test_handles_error(self, client):
        """get_trace_service_metrics handles API error."""
        from lm_mcp.tools.traces import get_trace_service_metrics

        respx.get(
            "https://test.logicmonitor.com/santaba/rest/device/devices/999/devicedatasources/9999/instances/8888/data"
        ).mock(return_value=httpx.Response(404, json={"errorMessage": "Not found"}))

        result = await get_trace_service_metrics(
            client,
            service_id=999,
            device_datasource_id=9999,
            instance_id=8888,
        )

        assert "Error:" in result[0].text


# --- get_trace_operation_metrics ---


class TestGetTraceOperationMetrics:
    """Tests for get_trace_operation_metrics tool."""

    @respx.mock
    async def test_returns_metrics(self, client):
        """get_trace_operation_metrics returns operation-level data."""
        from lm_mcp.tools.traces import get_trace_operation_metrics

        respx.get(
            "https://test.logicmonitor.com/santaba/rest/device/devices/101/devicedatasources/2002/instances/3002/data"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "dataPoints": ["Duration", "OperationCount"],
                    "values": {
                        "Duration": [45.1, 50.3],
                        "OperationCount": [20, 25],
                    },
                    "time": [1702500000, 1702500060],
                },
            )
        )

        result = await get_trace_operation_metrics(
            client,
            service_id=101,
            device_datasource_id=2002,
            instance_id=3002,
        )

        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["service_id"] == 101
        assert data["instance_id"] == 3002
        assert "Duration" in data["datapoints"]

    @respx.mock
    async def test_with_time_range(self, client):
        """get_trace_operation_metrics passes time range params."""
        from lm_mcp.tools.traces import get_trace_operation_metrics

        route = respx.get(
            "https://test.logicmonitor.com/santaba/rest/device/devices/101/devicedatasources/2002/instances/3002/data"
        ).mock(
            return_value=httpx.Response(
                200,
                json={"dataPoints": [], "values": {}, "time": []},
            )
        )

        await get_trace_operation_metrics(
            client,
            service_id=101,
            device_datasource_id=2002,
            instance_id=3002,
            start_time=1702500000,
            end_time=1702503600,
        )

        params = route.calls[0].request.url.params
        assert "start" in params
        assert "end" in params

    @respx.mock
    async def test_with_datapoints_filter(self, client):
        """get_trace_operation_metrics passes datapoints filter."""
        from lm_mcp.tools.traces import get_trace_operation_metrics

        route = respx.get(
            "https://test.logicmonitor.com/santaba/rest/device/devices/101/devicedatasources/2002/instances/3002/data"
        ).mock(
            return_value=httpx.Response(
                200,
                json={"dataPoints": [], "values": {}, "time": []},
            )
        )

        await get_trace_operation_metrics(
            client,
            service_id=101,
            device_datasource_id=2002,
            instance_id=3002,
            datapoints="Duration",
        )

        params = route.calls[0].request.url.params
        assert "datapoints" in params

    @respx.mock
    async def test_handles_error(self, client):
        """get_trace_operation_metrics handles API error."""
        from lm_mcp.tools.traces import get_trace_operation_metrics

        respx.get(
            "https://test.logicmonitor.com/santaba/rest/device/devices/999/devicedatasources/9999/instances/8888/data"
        ).mock(return_value=httpx.Response(404, json={"errorMessage": "Not found"}))

        result = await get_trace_operation_metrics(
            client,
            service_id=999,
            device_datasource_id=9999,
            instance_id=8888,
        )

        assert "Error:" in result[0].text


# --- get_trace_service_properties ---


class TestGetTraceServiceProperties:
    """Tests for get_trace_service_properties tool."""

    @respx.mock
    async def test_returns_properties(self, client):
        """get_trace_service_properties returns device properties."""
        from lm_mcp.tools.traces import get_trace_service_properties

        respx.get("https://test.logicmonitor.com/santaba/rest/device/devices/101/properties").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "name": "system.displayname",
                            "value": "order-service",
                            "type": "system",
                        },
                        {
                            "name": "auto.namespace",
                            "value": "production",
                            "type": "auto",
                        },
                    ],
                    "total": 2,
                },
            )
        )

        result = await get_trace_service_properties(client, service_id=101)

        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["service_id"] == 101
        assert data["total"] == 2
        assert len(data["properties"]) == 2
        assert data["properties"][0]["name"] == "system.displayname"

    @respx.mock
    async def test_with_name_filter(self, client):
        """get_trace_service_properties filters by property name."""
        from lm_mcp.tools.traces import get_trace_service_properties

        route = respx.get(
            "https://test.logicmonitor.com/santaba/rest/device/devices/101/properties"
        ).mock(return_value=httpx.Response(200, json={"items": [], "total": 0}))

        await get_trace_service_properties(client, service_id=101, name_filter="namespace")

        params = route.calls[0].request.url.params
        assert "filter" in params

    @respx.mock
    async def test_empty_results(self, client):
        """get_trace_service_properties handles empty results."""
        from lm_mcp.tools.traces import get_trace_service_properties

        respx.get("https://test.logicmonitor.com/santaba/rest/device/devices/101/properties").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        result = await get_trace_service_properties(client, service_id=101)

        data = json.loads(result[0].text)
        assert data["total"] == 0
        assert data["properties"] == []

    @respx.mock
    async def test_handles_error(self, client):
        """get_trace_service_properties handles API error."""
        from lm_mcp.tools.traces import get_trace_service_properties

        respx.get("https://test.logicmonitor.com/santaba/rest/device/devices/999/properties").mock(
            return_value=httpx.Response(404, json={"errorMessage": "Device not found"})
        )

        result = await get_trace_service_properties(client, service_id=999)

        assert "Error:" in result[0].text
