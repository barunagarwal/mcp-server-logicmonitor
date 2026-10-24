# Description: Tests for collector MCP tools.
# Description: Validates collector read, update, and delete functions.

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


class TestGetCollectors:
    """Tests for get_collectors tool."""

    @respx.mock
    async def test_get_collectors_returns_formatted_response(self, client):
        """get_collectors returns properly formatted collector list."""
        from lm_mcp.tools.collectors import get_collectors

        respx.get("https://test.logicmonitor.com/santaba/rest/setting/collector/collectors").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": 1,
                            "hostname": "collector01.example.com",
                            "status": 1,
                            "numberOfHosts": 50,
                        }
                    ],
                    "total": 1,
                },
            )
        )

        result = await get_collectors(client)

        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["total"] == 1
        assert data["collectors"][0]["hostname"] == "collector01.example.com"

    @respx.mock
    async def test_get_collectors_with_limit(self, client):
        """get_collectors passes size parameter to API."""
        from lm_mcp.tools.collectors import get_collectors

        route = respx.get(
            "https://test.logicmonitor.com/santaba/rest/setting/collector/collectors"
        ).mock(return_value=httpx.Response(200, json={"items": [], "total": 0}))

        await get_collectors(client, limit=10)

        assert route.calls[0].request.url.params.get("size") == "10"


class TestGetCollector:
    """Tests for get_collector tool."""

    @respx.mock
    async def test_get_collector_returns_details(self, client):
        """get_collector returns single collector details."""
        from lm_mcp.tools.collectors import get_collector

        respx.get("https://test.logicmonitor.com/santaba/rest/setting/collector/collectors/5").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 5,
                    "hostname": "collector05.example.com",
                    "status": 1,
                    "numberOfHosts": 100,
                    "platform": "linux",
                },
            )
        )

        result = await get_collector(client, collector_id=5)

        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["id"] == 5

    @respx.mock
    async def test_get_collector_not_found(self, client):
        """get_collector returns error for missing collector."""
        from lm_mcp.tools.collectors import get_collector

        respx.get(
            "https://test.logicmonitor.com/santaba/rest/setting/collector/collectors/999"
        ).mock(return_value=httpx.Response(404, json={"errorMessage": "Collector not found"}))

        result = await get_collector(client, collector_id=999)

        assert "Error:" in result[0].text


class TestGetCollectorsFilters:
    """Tests for get_collectors filter parameters."""

    @respx.mock
    async def test_get_collectors_with_hostname_filter(self, client):
        """get_collectors filters by hostname."""
        from lm_mcp.tools.collectors import get_collectors

        route = respx.get(
            "https://test.logicmonitor.com/santaba/rest/setting/collector/collectors"
        ).mock(return_value=httpx.Response(200, json={"items": [], "total": 0}))

        await get_collectors(client, hostname_filter="prod")

        params = dict(route.calls[0].request.url.params)
        assert "filter" in params
        assert 'hostname~"prod"' in params["filter"]

    @respx.mock
    async def test_get_collectors_with_group_id(self, client):
        """get_collectors filters by collector group ID."""
        from lm_mcp.tools.collectors import get_collectors

        route = respx.get(
            "https://test.logicmonitor.com/santaba/rest/setting/collector/collectors"
        ).mock(return_value=httpx.Response(200, json={"items": [], "total": 0}))

        await get_collectors(client, collector_group_id=5)

        params = dict(route.calls[0].request.url.params)
        assert "filter" in params
        assert "collectorGroupId:5" in params["filter"]

    @respx.mock
    async def test_get_collectors_with_raw_filter(self, client):
        """get_collectors passes raw filter expression to API."""
        from lm_mcp.tools.collectors import get_collectors

        route = respx.get(
            "https://test.logicmonitor.com/santaba/rest/setting/collector/collectors"
        ).mock(return_value=httpx.Response(200, json={"items": [], "total": 0}))

        await get_collectors(client, filter="hostname~prod,collectorGroupId:1")

        params = dict(route.calls[0].request.url.params)
        assert params["filter"] == "hostname~prod,collectorGroupId:1"

    @respx.mock
    async def test_get_collectors_with_offset(self, client):
        """get_collectors passes offset for pagination."""
        from lm_mcp.tools.collectors import get_collectors

        route = respx.get(
            "https://test.logicmonitor.com/santaba/rest/setting/collector/collectors"
        ).mock(return_value=httpx.Response(200, json={"items": [], "total": 0}))

        await get_collectors(client, offset=50)

        params = dict(route.calls[0].request.url.params)
        assert params["offset"] == "50"

    @respx.mock
    async def test_get_collectors_pagination_info(self, client):
        """get_collectors returns pagination info."""
        from lm_mcp.tools.collectors import get_collectors

        respx.get("https://test.logicmonitor.com/santaba/rest/setting/collector/collectors").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [{"id": 1, "hostname": "collector01"}],
                    "total": 100,
                },
            )
        )

        result = await get_collectors(client, limit=10, offset=0)

        data = json.loads(result[0].text)
        assert data["total"] == 100
        assert data["has_more"] is True
        assert data["offset"] == 0


class TestGetCollectorGroupsFilters:
    """Tests for get_collector_groups filter parameters."""

    @respx.mock
    async def test_get_collector_groups_with_raw_filter(self, client):
        """get_collector_groups passes raw filter expression to API."""
        from lm_mcp.tools.collectors import get_collector_groups

        route = respx.get(
            "https://test.logicmonitor.com/santaba/rest/setting/collector/groups"
        ).mock(return_value=httpx.Response(200, json={"items": [], "total": 0}))

        await get_collector_groups(client, filter="name~prod,autoBalance:true")

        params = dict(route.calls[0].request.url.params)
        assert params["filter"] == "name~prod,autoBalance:true"

    @respx.mock
    async def test_get_collector_groups_with_offset(self, client):
        """get_collector_groups passes offset for pagination."""
        from lm_mcp.tools.collectors import get_collector_groups

        route = respx.get(
            "https://test.logicmonitor.com/santaba/rest/setting/collector/groups"
        ).mock(return_value=httpx.Response(200, json={"items": [], "total": 0}))

        await get_collector_groups(client, offset=25)

        params = dict(route.calls[0].request.url.params)
        assert params["offset"] == "25"


class TestUpdateCollector:
    """Tests for update_collector tool."""

    @respx.mock
    async def test_update_collector_group(self, client, monkeypatch):
        """update_collector sends correct PATCH body for group change."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "true")
        from lm_mcp.tools.collectors import update_collector

        respx.patch(
            "https://test.logicmonitor.com/santaba/rest/setting/collector/collectors/121"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 121,
                    "hostname": "argus-0",
                    "collectorGroupId": 34,
                    "collectorGroupName": "AKS Cluster",
                    "description": "",
                },
            )
        )

        result = await update_collector(client, collector_id=121, collector_group_id=34)
        data = json.loads(result[0].text)
        assert data["message"] == "Collector updated successfully"
        assert data["collector"]["collector_group_id"] == 34

    @respx.mock
    async def test_update_collector_no_changes(self, client, monkeypatch):
        """update_collector returns error when no updates provided."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "true")
        from lm_mcp.tools.collectors import update_collector

        result = await update_collector(client, collector_id=121)
        assert "No updates provided" in result[0].text


class TestDeleteCollector:
    """Tests for delete_collector tool."""

    @respx.mock
    async def test_delete_collector_blocked_with_devices(self, client, monkeypatch):
        """delete_collector blocks when collector has devices."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "true")
        from lm_mcp.tools.collectors import delete_collector

        respx.get(
            "https://test.logicmonitor.com/santaba/rest/setting/collector/collectors/121"
        ).mock(
            return_value=httpx.Response(
                200,
                json={"id": 121, "hostname": "argus-0", "numberOfHosts": 50},
            )
        )

        result = await delete_collector(client, collector_id=121)
        assert "50 devices assigned" in result[0].text
        assert "Move or delete devices" in result[0].text

    @respx.mock
    async def test_delete_collector_succeeds_empty(self, client, monkeypatch):
        """delete_collector succeeds when collector has no devices."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "true")
        from lm_mcp.tools.collectors import delete_collector

        respx.get(
            "https://test.logicmonitor.com/santaba/rest/setting/collector/collectors/121"
        ).mock(
            return_value=httpx.Response(
                200,
                json={"id": 121, "hostname": "argus-0", "numberOfHosts": 0},
            )
        )
        respx.delete(
            "https://test.logicmonitor.com/santaba/rest/setting/collector/collectors/121"
        ).mock(return_value=httpx.Response(200, json={}))

        result = await delete_collector(client, collector_id=121)
        data = json.loads(result[0].text)
        assert data["success"] is True


class TestGetCollectorHealth:
    """Tests for get_collector_health tool."""

    @respx.mock
    async def test_reports_healthy_collector(self, client):
        from lm_mcp.tools.collectors import get_collector_health

        respx.get("https://test.logicmonitor.com/santaba/rest/setting/collector/collectors/1").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 1,
                    "hostname": "col-01",
                    "status": "normal",
                    "numberOfHosts": 42,
                    "collectorGroupId": 5,
                    "collectorGroupName": "prod",
                    "platform": "linux",
                    "upTime": 86400,
                },
            )
        )
        respx.get("https://test.logicmonitor.com/santaba/rest/device/devices").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 42})
        )
        respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=httpx.Response(200, json={"items": []})
        )

        result = await get_collector_health(client, collector_id=1)
        data = json.loads(result[0].text)

        assert data["total_collectors"] == 1
        col = data["collectors"][0]
        assert col["hostname"] == "col-01"
        assert col["is_down"] is False
        assert col["downstream_device_count"] == 42
        assert col["active_collector_down_alerts"] == 0

    @respx.mock
    async def test_flags_collector_with_active_collector_down_alert(self, client):
        from lm_mcp.tools.collectors import get_collector_health

        respx.get("https://test.logicmonitor.com/santaba/rest/setting/collector/collectors/2").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 2,
                    "hostname": "col-02",
                    "status": "normal",
                    "numberOfHosts": 30,
                },
            )
        )
        respx.get("https://test.logicmonitor.com/santaba/rest/device/devices").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 30})
        )
        respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": 999,
                            "alertType": "CollectorDown",
                            "monitorObjectName": "col-02",
                            "cleared": False,
                        }
                    ]
                },
            )
        )

        result = await get_collector_health(client, collector_id=2)
        data = json.loads(result[0].text)

        assert data["collectors_down"] == 1
        assert data["collectors"][0]["is_down"] is True
        assert data["collectors"][0]["active_collector_down_alerts"] == 1

    @respx.mock
    async def test_alert_query_failure_surfaces_unknown_down_signal(self, client):
        """A failed CollectorDown query is surfaced, not reported as zero collectors down."""
        from lm_mcp.tools.collectors import get_collector_health

        respx.get("https://test.logicmonitor.com/santaba/rest/setting/collector/collectors/3").mock(
            return_value=httpx.Response(
                200,
                json={"id": 3, "hostname": "col-03", "status": "normal", "numberOfHosts": 10},
            )
        )
        respx.get("https://test.logicmonitor.com/santaba/rest/device/devices").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 10})
        )
        # The CollectorDown alert query fails (e.g. 500/429/403).
        respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=httpx.Response(500, json={"errorMessage": "boom"})
        )

        result = await get_collector_health(client, collector_id=3)
        data = json.loads(result[0].text)

        # The down signal is unknown, surfaced as such -- not a confident zero.
        assert data["collectors_down_signal_unavailable"] == 1
        assert "undercounted" in data["warning"]
        col = data["collectors"][0]
        assert col["down_signal_unavailable"] is True
        assert col["active_collector_down_alerts"] is None

    @respx.mock
    async def test_alert_query_failure_makes_is_down_unknown(self, auth):
        """R4.4: a failed CollectorDown read leaves is_down null, whatever the status says.

        The status word is not consulted once the alert read failed, so the
        "dead" collector is unknown too, and neither counts as down.
        """
        from lm_mcp.tools.collectors import get_collector_health

        client = LogicMonitorClient(
            base_url="https://test.logicmonitor.com/santaba/rest",
            auth=auth,
            max_retries=0,
        )
        respx.get("https://test.logicmonitor.com/santaba/rest/setting/collector/collectors").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {"id": 1, "hostname": "col-a", "status": "dead", "numberOfHosts": 4},
                        {"id": 2, "hostname": "col-b", "status": "normal", "numberOfHosts": 6},
                    ]
                },
            )
        )
        respx.get("https://test.logicmonitor.com/santaba/rest/device/devices").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 5})
        )
        respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=httpx.Response(500, json={"errorMessage": "boom"})
        )

        result = await get_collector_health(client)
        data = json.loads(result[0].text)

        for col in data["collectors"]:
            assert col["is_down"] is None
            assert col["down_signal_unavailable"] is True
            assert col["active_collector_down_alerts"] is None
        assert data["collectors_down"] == 0
        assert data["collectors_down_signal_unavailable"] == 2

    @respx.mock
    async def test_lists_all_collectors_when_no_scope(self, client):
        from lm_mcp.tools.collectors import get_collector_health

        respx.get("https://test.logicmonitor.com/santaba/rest/setting/collector/collectors").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {"id": 1, "hostname": "col-a", "status": "normal", "numberOfHosts": 10},
                        {"id": 2, "hostname": "col-b", "status": "normal", "numberOfHosts": 20},
                    ]
                },
            )
        )
        respx.get("https://test.logicmonitor.com/santaba/rest/device/devices").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )
        respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=httpx.Response(200, json={"items": []})
        )

        result = await get_collector_health(client)
        data = json.loads(result[0].text)
        assert data["total_collectors"] == 2

    @respx.mock
    async def test_includes_history_when_requested(self, client):
        from lm_mcp.tools.collectors import get_collector_health

        respx.get("https://test.logicmonitor.com/santaba/rest/setting/collector/collectors/3").mock(
            return_value=httpx.Response(
                200,
                json={"id": 3, "hostname": "col-03", "status": "normal"},
            )
        )
        respx.get("https://test.logicmonitor.com/santaba/rest/device/devices").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )
        respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": 500,
                            "alertType": "CollectorDown",
                            "monitorObjectName": "col-03",
                            "startEpoch": 1700000000,
                            "severity": 4,
                            "cleared": True,
                        }
                    ]
                },
            )
        )

        result = await get_collector_health(
            client, collector_id=3, include_history=True, history_days=3
        )
        data = json.loads(result[0].text)
        assert data["include_history"] is True
        history = data["collectors"][0]["collector_down_history"]
        assert len(history) == 1
        assert history[0]["alert_type"] == "CollectorDown"
