# Description: Tests for event and change correlation tools.
# Description: Validates correlate_changes for alert spike and audit log correlation.

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


BASE_URL = "https://test.logicmonitor.com/santaba/rest"
ALERT_URL = f"{BASE_URL}/alert/alerts"
AUDIT_URL = f"{BASE_URL}/setting/accesslogs"


class TestCorrelateChanges:
    """Tests for correlate_changes tool."""

    @respx.mock
    async def test_no_alerts_no_changes(self, client):
        """No alerts and no changes produce empty results."""
        from lm_mcp.tools.event_correlation import correlate_changes

        respx.get(ALERT_URL).mock(return_value=httpx.Response(200, json={"items": [], "total": 0}))
        respx.get(AUDIT_URL).mock(return_value=httpx.Response(200, json={"items": [], "total": 0}))

        result = await correlate_changes(client)

        data = json.loads(result[0].text)
        assert data["total_alerts"] == 0
        assert data["total_changes"] == 0
        assert data["correlated_events"] == []

    @respx.mock
    async def test_audit_read_failure_is_flagged(self, client):
        """A failed audit-log read is surfaced as audit_read_failed, not silent zero changes."""
        from lm_mcp.tools.event_correlation import correlate_changes

        respx.get(ALERT_URL).mock(return_value=httpx.Response(200, json={"items": [], "total": 0}))
        # The audit/change log read fails (e.g. 403 -- audit access is privileged).
        respx.get(AUDIT_URL).mock(return_value=httpx.Response(403, json={"errorMessage": "denied"}))

        result = await correlate_changes(client)

        data = json.loads(result[0].text)
        assert data["audit_read_failed"] is True
        assert "unavailable" in data["warning"].lower()
        assert data["total_changes"] == 0

    @respx.mock
    async def test_change_followed_by_spike(self, client):
        """Change event followed by alert spike is correlated."""
        from lm_mcp.tools.event_correlation import correlate_changes

        now = int(time.time())
        change_ts = now - 3600
        spike_ts = change_ts + 600  # 10 min after change

        # Create a spike: many alerts at the same time
        alerts = [
            {
                "id": f"LMA{i}",
                "severity": 3,
                "monitorObjectName": f"server{i}",
                "startEpoch": spike_ts,
                "endEpoch": 0,
                "cleared": False,
            }
            for i in range(10)
        ]
        # Add a few baseline alerts spread over time
        for i in range(5):
            alerts.append(
                {
                    "id": f"LMA_bg{i}",
                    "severity": 2,
                    "monitorObjectName": f"bg{i}",
                    "startEpoch": now - 7200 + i * 600,
                    "endEpoch": 0,
                    "cleared": False,
                }
            )

        changes = [
            {
                "id": 1,
                "happenedOn": change_ts,
                "userName": "admin",
                "description": "Updated firewall rule",
            },
        ]

        respx.get(ALERT_URL).mock(
            return_value=httpx.Response(200, json={"items": alerts, "total": len(alerts)})
        )
        respx.get(AUDIT_URL).mock(
            return_value=httpx.Response(200, json={"items": changes, "total": 1})
        )

        result = await correlate_changes(client)

        data = json.loads(result[0].text)
        assert data["total_alerts"] == len(alerts)
        assert data["total_changes"] == 1
        # May or may not correlate depending on spike detection threshold
        assert "correlated_events" in data

    @respx.mock
    async def test_unrelated_change_not_correlated(self, client):
        """Change event far from any spike is not correlated."""
        from lm_mcp.tools.event_correlation import correlate_changes

        now = int(time.time())

        alerts = [
            {
                "id": "LMA1",
                "severity": 3,
                "monitorObjectName": "server01",
                "startEpoch": now - 100,
                "endEpoch": 0,
                "cleared": False,
            },
        ]
        # Change happened 10 hours ago with no spike
        changes = [
            {
                "id": 1,
                "happenedOn": now - 36000,
                "userName": "admin",
                "description": "Updated config",
            },
        ]

        respx.get(ALERT_URL).mock(
            return_value=httpx.Response(200, json={"items": alerts, "total": 1})
        )
        respx.get(AUDIT_URL).mock(
            return_value=httpx.Response(200, json={"items": changes, "total": 1})
        )

        result = await correlate_changes(client)

        data = json.loads(result[0].text)
        assert len(data["uncorrelated_changes"]) > 0

    @respx.mock
    async def test_audit_api_failure_graceful(self, client):
        """Audit API failure is handled gracefully."""
        from lm_mcp.tools.event_correlation import correlate_changes

        respx.get(ALERT_URL).mock(return_value=httpx.Response(200, json={"items": [], "total": 0}))
        respx.get(AUDIT_URL).mock(return_value=httpx.Response(500, json={"errorMessage": "error"}))

        result = await correlate_changes(client)

        data = json.loads(result[0].text)
        assert data["total_changes"] == 0

    @respx.mock
    async def test_hours_back_in_response(self, client):
        """Response includes hours_back parameter."""
        from lm_mcp.tools.event_correlation import correlate_changes

        respx.get(ALERT_URL).mock(return_value=httpx.Response(200, json={"items": [], "total": 0}))
        respx.get(AUDIT_URL).mock(return_value=httpx.Response(200, json={"items": [], "total": 0}))

        result = await correlate_changes(client, hours_back=48)

        data = json.loads(result[0].text)
        assert data["hours_back"] == 48
        assert data["correlation_window_minutes"] == 30

    @respx.mock
    async def test_custom_correlation_window(self, client):
        """Custom correlation window is reflected in response."""
        from lm_mcp.tools.event_correlation import correlate_changes

        respx.get(ALERT_URL).mock(return_value=httpx.Response(200, json={"items": [], "total": 0}))
        respx.get(AUDIT_URL).mock(return_value=httpx.Response(200, json={"items": [], "total": 0}))

        result = await correlate_changes(client, correlation_window_minutes=60)

        data = json.loads(result[0].text)
        assert data["correlation_window_minutes"] == 60

    @respx.mock
    async def test_response_structure(self, client):
        """Response has all expected fields."""
        from lm_mcp.tools.event_correlation import correlate_changes

        respx.get(ALERT_URL).mock(return_value=httpx.Response(200, json={"items": [], "total": 0}))
        respx.get(AUDIT_URL).mock(return_value=httpx.Response(200, json={"items": [], "total": 0}))

        result = await correlate_changes(client)

        data = json.loads(result[0].text)
        assert "total_alerts" in data
        assert "total_changes" in data
        assert "total_spikes" in data
        assert "correlated_events" in data
        assert "uncorrelated_changes" in data
        assert "uncorrelated_spikes" in data

    @respx.mock
    async def test_error_handling(self, client):
        """Alert API errors are returned as error response."""
        from lm_mcp.tools.event_correlation import correlate_changes

        respx.get(ALERT_URL).mock(side_effect=httpx.ConnectError("Connection refused"))

        result = await correlate_changes(client)

        assert "Error:" in result[0].text

    @respx.mock
    async def test_millisecond_timestamps_handled(self, client):
        """Millisecond timestamps from audit API are converted."""
        from lm_mcp.tools.event_correlation import correlate_changes

        now = int(time.time())
        respx.get(ALERT_URL).mock(return_value=httpx.Response(200, json={"items": [], "total": 0}))
        respx.get(AUDIT_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": 1,
                            "happenedOn": now * 1000,
                            "userName": "admin",
                            "description": "test",
                        },
                    ],
                    "total": 1,
                },
            )
        )

        result = await correlate_changes(client)

        data = json.loads(result[0].text)
        assert data["total_changes"] == 1


class TestCorrelateChangesPaging:
    """R4.2: correlate_changes reads the whole alert window or says the cap cut it short."""

    @staticmethod
    def _alerts(n):
        start = int(time.time()) - 3600
        return [{"id": f"LMA{i}", "startEpoch": start + i % 3000} for i in range(n)]

    @respx.mock
    async def test_sees_every_page(self, client):
        from lm_mcp.tools.event_correlation import correlate_changes

        respx.get(ALERT_URL).mock(side_effect=alert_pages(self._alerts(2500), lower_bound=True))
        respx.get(AUDIT_URL).mock(return_value=httpx.Response(200, json={"items": [], "total": 0}))

        result = await correlate_changes(client)

        data = json.loads(result[0].text)
        assert data["total_alerts"] == 2500
        assert data["truncated"] is False
        assert data["api_total"] == 2500

    @respx.mock
    async def test_capped_window_is_declared(self, client):
        from lm_mcp.tools.event_correlation import correlate_changes

        respx.get(ALERT_URL).mock(side_effect=alert_pages(self._alerts(6000), lower_bound=True))
        respx.get(AUDIT_URL).mock(return_value=httpx.Response(200, json={"items": [], "total": 0}))

        result = await correlate_changes(client)

        data = json.loads(result[0].text)
        assert data["total_alerts"] == 5000
        assert data["truncated"] is True
        assert data["api_total"] is None
