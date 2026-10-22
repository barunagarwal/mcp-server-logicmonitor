# Description: Tests for alert MCP tools.
# Description: Validates get_alerts, get_alert_details, acknowledge_alert, add_alert_note.

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


class TestGetAlerts:
    """Tests for get_alerts tool."""

    @respx.mock
    async def test_get_alerts_returns_formatted_response(self, client):
        """get_alerts returns properly formatted alert list."""
        from lm_mcp.tools.alerts import get_alerts

        respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "LMA123",
                            "severity": 4,
                            "monitorObjectName": "server01",
                            "alertValue": "CPU usage 95%",
                            "startEpoch": 1702400000,
                        }
                    ],
                    "total": 1,
                },
            )
        )

        result = await get_alerts(client)

        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["total"] == 1
        assert len(data["alerts"]) == 1
        assert data["alerts"][0]["id"] == "LMA123"

    @respx.mock
    async def test_get_alerts_negative_total_sanitized(self, client):
        """get_alerts converts negative API total sentinel to positive."""
        from lm_mcp.tools.alerts import get_alerts

        respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "LMA1",
                            "severity": 2,
                            "monitorObjectName": "srv01",
                            "alertValue": "high",
                            "startEpoch": 1702400000,
                        }
                    ],
                    "total": -501,
                },
            )
        )

        result = await get_alerts(client, limit=500)
        data = json.loads(result[0].text)
        assert data["total"] == 501

    @respx.mock
    async def test_get_alerts_with_severity_filter(self, client):
        """get_alerts passes severity filter to API."""
        from lm_mcp.tools.alerts import get_alerts

        route = respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        await get_alerts(client, severity="critical")

        assert "filter" in route.calls[0].request.url.params
        assert "severity:4" in route.calls[0].request.url.params.get("filter", "")

    @respx.mock
    async def test_get_alerts_with_limit(self, client):
        """get_alerts passes size parameter to API."""
        from lm_mcp.tools.alerts import get_alerts

        route = respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        await get_alerts(client, limit=10)

        assert route.calls[0].request.url.params.get("size") == "10"

    @respx.mock
    async def test_get_alerts_handles_error(self, client):
        """get_alerts returns error response on API failure."""
        from lm_mcp.tools.alerts import get_alerts

        respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=httpx.Response(401, json={"errorMessage": "Unauthorized"})
        )

        result = await get_alerts(client)

        assert len(result) == 1
        assert "Error:" in result[0].text

    @respx.mock
    async def test_get_alerts_with_raw_filter(self, client):
        """get_alerts passes raw filter expression to API."""
        from lm_mcp.tools.alerts import get_alerts

        route = respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        await get_alerts(client, filter="resourceTemplateName:CPU,severity>:3")

        params = dict(route.calls[0].request.url.params)
        assert "filter" in params
        assert "resourceTemplateName" in params["filter"]

    @respx.mock
    async def test_get_alerts_with_time_range(self, client):
        """get_alerts filters by time range."""
        from lm_mcp.tools.alerts import get_alerts

        route = respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        await get_alerts(client, start_epoch=1700000000, end_epoch=1700100000)

        params = dict(route.calls[0].request.url.params)
        assert "filter" in params
        assert "startEpoch" in params["filter"]
        assert "endEpoch" in params["filter"]

    @respx.mock
    async def test_get_alerts_with_cleared_filter(self, client):
        """get_alerts filters by cleared status."""
        from lm_mcp.tools.alerts import get_alerts

        route = respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        await get_alerts(client, cleared=True)

        params = dict(route.calls[0].request.url.params)
        assert "filter" in params
        assert "cleared:true" in params["filter"]

    @respx.mock
    async def test_get_alerts_with_datapoint_filter(self, client):
        """get_alerts filters by datapoint name."""
        from lm_mcp.tools.alerts import get_alerts

        route = respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        await get_alerts(client, datapoint="CPUBusyPercent")

        params = dict(route.calls[0].request.url.params)
        assert "filter" in params
        assert "dataPointName" in params["filter"]

    @respx.mock
    async def test_get_alerts_combined_filters(self, client):
        """get_alerts combines multiple filter parameters."""
        from lm_mcp.tools.alerts import get_alerts

        route = respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        await get_alerts(client, severity="critical", cleared=False, datapoint="CPU")

        params = dict(route.calls[0].request.url.params)
        assert "filter" in params
        assert "severity" in params["filter"]
        assert "cleared" in params["filter"]
        assert "dataPointName" in params["filter"]


class TestGetAlertsGroupAndDeviceId:
    """Tests for group_id and device_id filter parameters on get_alerts."""

    GROUP_PATH = "Dev Portal/AKS/Kubernetes Cluster: rm-aks-cluster"

    @respx.mock
    async def test_get_alerts_with_group_id(self, client):
        """get_alerts resolves group_id to monitorObjectGroups filter."""
        from lm_mcp.tools.alerts import get_alerts

        respx.get("https://test.logicmonitor.com/santaba/rest/device/groups/1977").mock(
            return_value=httpx.Response(200, json={"id": 1977, "fullPath": self.GROUP_PATH})
        )
        route = respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        await get_alerts(client, group_id=1977)

        params = dict(route.calls[0].request.url.params)
        assert params["filter"] == f'monitorObjectGroups~"{self.GROUP_PATH}"'

    @respx.mock
    async def test_get_alerts_with_device_id(self, client):
        """get_alerts filters by device ID using monitorObjectId."""
        from lm_mcp.tools.alerts import get_alerts

        route = respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        await get_alerts(client, device_id=9269)

        params = dict(route.calls[0].request.url.params)
        assert params["filter"] == "monitorObjectId:9269"

    @respx.mock
    async def test_get_alerts_group_id_with_severity(self, client):
        """get_alerts combines group_id with severity filter."""
        from lm_mcp.tools.alerts import get_alerts

        respx.get("https://test.logicmonitor.com/santaba/rest/device/groups/1977").mock(
            return_value=httpx.Response(200, json={"id": 1977, "fullPath": self.GROUP_PATH})
        )
        route = respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        await get_alerts(client, group_id=1977, severity="warning", cleared=False)

        params = dict(route.calls[0].request.url.params)
        filt = params["filter"]
        assert "severity:2" in filt
        assert "cleared:false" in filt
        assert f'monitorObjectGroups~"{self.GROUP_PATH}"' in filt

    @respx.mock
    async def test_get_alerts_group_id_and_device_id_together(self, client):
        """get_alerts combines group_id and device_id filters."""
        from lm_mcp.tools.alerts import get_alerts

        respx.get("https://test.logicmonitor.com/santaba/rest/device/groups/1977").mock(
            return_value=httpx.Response(200, json={"id": 1977, "fullPath": self.GROUP_PATH})
        )
        route = respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        await get_alerts(client, group_id=1977, device_id=9269)

        params = dict(route.calls[0].request.url.params)
        filt = params["filter"]
        assert f'monitorObjectGroups~"{self.GROUP_PATH}"' in filt
        assert "monitorObjectId:9269" in filt

    @respx.mock
    async def test_get_alerts_k8s_device_name(self, client):
        """get_alerts handles K8s-style hyphenated device names."""
        from lm_mcp.tools.alerts import get_alerts

        route = respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        await get_alerts(
            client,
            device="azure-vote-back-6dff9db5bb-8dqxc-pod-azure-vote-rm-aks-cluster",
        )

        params = dict(route.calls[0].request.url.params)
        expected = (
            'monitorObjectName~"azure-vote-back-6dff9db5bb-8dqxc-pod-azure-vote-rm-aks-cluster"'
        )
        assert params["filter"] == expected

    @respx.mock
    async def test_get_alerts_raw_filter_overrides_group_id(self, client):
        """Raw filter takes precedence over group_id and device_id."""
        from lm_mcp.tools.alerts import get_alerts

        route = respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        await get_alerts(
            client,
            group_id=1977,
            device_id=9269,
            filter="severity:4,cleared:false",
        )

        params = dict(route.calls[0].request.url.params)
        assert params["filter"] == "severity:4,cleared:false"
        assert "hostGroupIds" not in params["filter"]


class TestGetAlertDetails:
    """Tests for get_alert_details tool."""

    @respx.mock
    async def test_get_alert_details_returns_alert(self, client):
        """get_alert_details returns single alert details."""
        from lm_mcp.tools.alerts import get_alert_details

        respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts/123").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "LMA123",
                    "severity": 4,
                    "monitorObjectName": "server01",
                    "alertValue": "CPU usage 95%",
                    "resourceTemplateName": "CPU",
                    "instanceName": "cpu-0",
                },
            )
        )

        result = await get_alert_details(client, alert_id="123")

        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["id"] == "LMA123"
        assert data["severity"] == 4

    @respx.mock
    async def test_get_alert_details_strips_lma_prefix(self, client):
        """get_alert_details strips LMA prefix from alert ID."""
        from lm_mcp.tools.alerts import get_alert_details

        route = respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts/456").mock(
            return_value=httpx.Response(200, json={"id": "LMA456"})
        )

        await get_alert_details(client, alert_id="LMA456")

        assert "/alerts/456" in str(route.calls[0].request.url)

    @respx.mock
    async def test_get_alert_details_not_found(self, client):
        """get_alert_details returns error for missing alert."""
        from lm_mcp.tools.alerts import get_alert_details

        respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts/999").mock(
            return_value=httpx.Response(404, json={"errorMessage": "Alert not found"})
        )

        result = await get_alert_details(client, alert_id="999")

        assert "Error:" in result[0].text


class TestAcknowledgeAlert:
    """Tests for acknowledge_alert tool."""

    @respx.mock
    async def test_acknowledge_alert_blocked_by_default(self, client, monkeypatch):
        """acknowledge_alert is blocked when writes disabled."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "false")

        from importlib import reload

        import lm_mcp.config

        reload(lm_mcp.config)

        from lm_mcp.tools.alerts import acknowledge_alert

        result = await acknowledge_alert(client, alert_id="123")

        assert "Error:" in result[0].text
        assert "Write operations are disabled" in result[0].text

    @respx.mock
    async def test_acknowledge_alert_succeeds_when_enabled(self, client, monkeypatch):
        """acknowledge_alert works when writes enabled."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "true")

        from importlib import reload

        import lm_mcp.config

        reload(lm_mcp.config)

        from lm_mcp.tools.alerts import acknowledge_alert

        respx.post("https://test.logicmonitor.com/santaba/rest/alert/alerts/123/ack").mock(
            return_value=httpx.Response(200, json={"success": True})
        )

        result = await acknowledge_alert(client, alert_id="123", note="Investigating")

        assert len(result) == 1
        assert "Error:" not in result[0].text


class TestAddAlertNote:
    """Tests for add_alert_note tool."""

    @respx.mock
    async def test_add_alert_note_blocked_by_default(self, client, monkeypatch):
        """add_alert_note is blocked when writes disabled."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "false")

        from importlib import reload

        import lm_mcp.config

        reload(lm_mcp.config)

        from lm_mcp.tools.alerts import add_alert_note

        result = await add_alert_note(client, alert_id="123", note="Test note")

        assert "Error:" in result[0].text
        assert "Write operations are disabled" in result[0].text

    @respx.mock
    async def test_add_alert_note_succeeds_when_enabled(self, client, monkeypatch):
        """add_alert_note works when writes enabled."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "true")

        from importlib import reload

        import lm_mcp.config

        reload(lm_mcp.config)

        from lm_mcp.tools.alerts import add_alert_note

        respx.post("https://test.logicmonitor.com/santaba/rest/alert/alerts/123/note").mock(
            return_value=httpx.Response(200, json={"success": True})
        )

        result = await add_alert_note(client, alert_id="123", note="Test note")

        assert len(result) == 1
        assert "Error:" not in result[0].text

    @respx.mock
    async def test_add_alert_note_requires_note(self, client, monkeypatch):
        """add_alert_note validates note is not empty."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "true")

        from importlib import reload

        import lm_mcp.config

        reload(lm_mcp.config)

        from lm_mcp.tools.alerts import add_alert_note

        result = await add_alert_note(client, alert_id="123", note="")

        assert "Error:" in result[0].text
        assert "Note cannot be empty" in result[0].text


class TestBulkAcknowledgeAlerts:
    """Tests for bulk_acknowledge_alerts tool."""

    @respx.mock
    async def test_bulk_acknowledge_blocked_by_default(self, client, monkeypatch):
        """bulk_acknowledge_alerts is blocked when writes disabled."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "false")

        from importlib import reload

        import lm_mcp.config

        reload(lm_mcp.config)

        from lm_mcp.tools.alerts import bulk_acknowledge_alerts

        result = await bulk_acknowledge_alerts(client, alert_ids=["123", "456"])

        assert "Error:" in result[0].text
        assert "Write operations are disabled" in result[0].text

    @respx.mock
    async def test_bulk_acknowledge_succeeds(self, client, monkeypatch):
        """bulk_acknowledge_alerts acknowledges multiple alerts."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "true")

        from importlib import reload

        import lm_mcp.config

        reload(lm_mcp.config)

        from lm_mcp.tools.alerts import bulk_acknowledge_alerts

        respx.post("https://test.logicmonitor.com/santaba/rest/alert/alerts/123/ack").mock(
            return_value=httpx.Response(200, json={"success": True})
        )
        respx.post("https://test.logicmonitor.com/santaba/rest/alert/alerts/456/ack").mock(
            return_value=httpx.Response(200, json={"success": True})
        )

        result = await bulk_acknowledge_alerts(client, alert_ids=["123", "456"], note="Batch ack")

        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["total"] == 2
        assert data["acknowledged"] == 2
        assert data["failed"] == 0

    @respx.mock
    async def test_bulk_acknowledge_partial_failure(self, client, monkeypatch):
        """bulk_acknowledge_alerts handles partial failures."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "true")

        from importlib import reload

        import lm_mcp.config

        reload(lm_mcp.config)

        from lm_mcp.tools.alerts import bulk_acknowledge_alerts

        respx.post("https://test.logicmonitor.com/santaba/rest/alert/alerts/123/ack").mock(
            return_value=httpx.Response(200, json={"success": True})
        )
        respx.post("https://test.logicmonitor.com/santaba/rest/alert/alerts/999/ack").mock(
            return_value=httpx.Response(404, json={"errorMessage": "Alert not found"})
        )

        result = await bulk_acknowledge_alerts(client, alert_ids=["123", "999"])

        data = json.loads(result[0].text)
        assert data["total"] == 2
        assert data["acknowledged"] == 1
        assert data["failed"] == 1
        assert "123" in data["success_ids"]

    @respx.mock
    async def test_bulk_acknowledge_empty_list(self, client, monkeypatch):
        """bulk_acknowledge_alerts validates non-empty list."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "true")

        from importlib import reload

        import lm_mcp.config

        reload(lm_mcp.config)

        from lm_mcp.tools.alerts import bulk_acknowledge_alerts

        result = await bulk_acknowledge_alerts(client, alert_ids=[])

        assert "Error:" in result[0].text
        assert "No alert IDs provided" in result[0].text

    @respx.mock
    async def test_bulk_acknowledge_strips_lma_prefix(self, client, monkeypatch):
        """bulk_acknowledge_alerts strips LMA prefix from IDs."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "true")

        from importlib import reload

        import lm_mcp.config

        reload(lm_mcp.config)

        from lm_mcp.tools.alerts import bulk_acknowledge_alerts

        route = respx.post("https://test.logicmonitor.com/santaba/rest/alert/alerts/789/ack").mock(
            return_value=httpx.Response(200, json={"success": True})
        )

        await bulk_acknowledge_alerts(client, alert_ids=["LMA789"])

        assert route.called
        assert "/alerts/789/ack" in str(route.calls[0].request.url)


class TestIncludeMessageParam:
    """needMessage passthrough on get_alert_details."""

    @respx.mock
    async def test_include_message_passes_need_message(self, client):
        from lm_mcp.tools.alerts import get_alert_details

        route = respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts/1").mock(
            return_value=httpx.Response(200, json={"id": "LMA1", "message": "full body"})
        )

        await get_alert_details(client, "LMA1", include_message=True)
        assert route.calls[0].request.url.params["needMessage"] == "true"

        await get_alert_details(client, "LMA1")
        assert "needMessage" not in route.calls[1].request.url.params


def _window_alerts(n):
    """Build n distinct alerts for the paged alert responder."""
    return [{"id": f"LMA{i}", "severity": 3, "startEpoch": 1705276800 + i} for i in range(n)]


class TestPaginateAlerts:
    """R4.2: paginate_alerts pages to the API total and reports when the cap binds."""

    ALERTS_URL = "https://test.logicmonitor.com/santaba/rest/alert/alerts"

    @pytest.mark.parametrize("lower_bound", [False, True], ids=["exact", "lower_bound"])
    @respx.mock
    async def test_collects_every_page_below_the_cap(self, client, lower_bound):
        from lm_mcp.tools.alerts import paginate_alerts

        route = respx.get(self.ALERTS_URL).mock(
            side_effect=alert_pages(_window_alerts(2500), lower_bound=lower_bound)
        )

        alerts, truncated, api_total = await paginate_alerts(client, "cleared:false")

        assert len(alerts) == 2500
        assert len({a["id"] for a in alerts}) == 2500
        assert truncated is False
        assert api_total == 2500
        offsets = [call.request.url.params["offset"] for call in route.calls]
        assert offsets == ["0", "1000", "2000"]

    @respx.mock
    async def test_cap_binds_with_an_exact_total(self, client):
        from lm_mcp.tools.alerts import paginate_alerts

        respx.get(self.ALERTS_URL).mock(side_effect=alert_pages(_window_alerts(6000)))

        alerts, truncated, api_total = await paginate_alerts(client, "cleared:false")

        assert len(alerts) == 5000
        assert truncated is True
        assert api_total == 6000

    @respx.mock
    async def test_cap_binds_with_a_lower_bound_total(self, client):
        """The portal's last capped page says only that more exist, so the total is unknown."""
        from lm_mcp.tools.alerts import paginate_alerts

        respx.get(self.ALERTS_URL).mock(
            side_effect=alert_pages(_window_alerts(6000), lower_bound=True)
        )

        alerts, truncated, api_total = await paginate_alerts(client, "cleared:false")

        assert len(alerts) == 5000
        assert truncated is True
        assert api_total is None

    @pytest.mark.parametrize("lower_bound", [False, True], ids=["exact", "lower_bound"])
    @respx.mock
    async def test_a_window_of_exactly_the_cap_is_complete(self, client, lower_bound):
        from lm_mcp.tools.alerts import paginate_alerts

        respx.get(self.ALERTS_URL).mock(
            side_effect=alert_pages(_window_alerts(5000), lower_bound=lower_bound)
        )

        alerts, truncated, api_total = await paginate_alerts(client, "cleared:false")

        assert len(alerts) == 5000
        assert truncated is False
        assert api_total == 5000

    @respx.mock
    async def test_a_smaller_cap_sizes_the_request(self, client):
        from lm_mcp.tools.alerts import paginate_alerts

        route = respx.get(self.ALERTS_URL).mock(
            side_effect=alert_pages(_window_alerts(2500), lower_bound=True)
        )

        alerts, truncated, api_total = await paginate_alerts(client, "cleared:false", cap=100)

        assert len(alerts) == 100
        assert truncated is True
        assert api_total is None
        assert [call.request.url.params["size"] for call in route.calls] == ["100"]

    @respx.mock
    async def test_a_cap_of_zero_reads_nothing_and_knows_no_total(self, client):
        """No page was read, so the API's count is unknown, not zero."""
        from lm_mcp.tools.alerts import paginate_alerts

        route = respx.get(self.ALERTS_URL).mock(side_effect=alert_pages(_window_alerts(10)))

        alerts, truncated, api_total = await paginate_alerts(client, "cleared:false", cap=0)

        assert alerts == []
        assert truncated is False
        assert api_total is None
        assert route.call_count == 0

    @respx.mock
    async def test_a_larger_cap_is_clamped_to_the_hard_cap(self, client):
        from lm_mcp.tools.alerts import MAX_ALERTS_PER_WINDOW, paginate_alerts

        respx.get(self.ALERTS_URL).mock(side_effect=alert_pages(_window_alerts(6000)))

        alerts, truncated, _ = await paginate_alerts(client, "cleared:false", cap=10_000)

        assert MAX_ALERTS_PER_WINDOW == 5000
        assert len(alerts) == 5000
        assert truncated is True
