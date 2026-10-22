# Description: Error handling tests for undertested tool modules.
# Description: Validates error responses for cost, topology, batchjob, and audit tools.

import logging

import httpx
import pytest
import respx

from lm_mcp.auth.bearer import BearerAuth
from lm_mcp.client import LogicMonitorClient
from lm_mcp.exceptions import LMPermissionError
from lm_mcp.tools import handle_error, is_error_result


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
        max_retries=0,
    )


class TestCostToolErrors:
    """Error handling tests for cost tools."""

    @respx.mock
    async def test_get_cost_recommendations_500(self, client):
        """get_cost_recommendations handles 500 response."""
        from lm_mcp.tools.cost import get_cost_recommendations

        respx.get(
            "https://test.logicmonitor.com/santaba/rest/cost-optimization/recommendations"
        ).mock(return_value=httpx.Response(500, json={"errorMessage": "Internal server error"}))

        result = await get_cost_recommendations(client)
        assert "Error" in result[0].text or "error" in result[0].text.lower()


class TestTopologyToolErrors:
    """Error handling tests for topology tools."""

    @respx.mock
    async def test_get_device_neighbors_404(self, client):
        """get_device_neighbors handles 404 for invalid device."""
        from lm_mcp.tools.topology import get_device_neighbors

        respx.get("https://test.logicmonitor.com/santaba/rest/device/devices/9999/neighbors").mock(
            return_value=httpx.Response(404, json={"errorMessage": "Device not found"})
        )

        result = await get_device_neighbors(client, device_id=9999)
        assert "Error" in result[0].text or "error" in result[0].text.lower()

    @respx.mock
    async def test_get_topology_map_500(self, client):
        """get_topology_map handles 500 response."""
        from lm_mcp.tools.topology import get_topology_map

        respx.get("https://test.logicmonitor.com/santaba/rest/topology/topologies").mock(
            return_value=httpx.Response(500, json={"errorMessage": "Server error"})
        )

        result = await get_topology_map(client)
        assert "Error" in result[0].text or "error" in result[0].text.lower()


class TestBatchjobToolErrors:
    """Error handling tests for batchjob tools."""

    @respx.mock
    async def test_get_batchjob_404(self, client):
        """get_batchjob handles 404 for invalid job ID."""
        from lm_mcp.tools.batchjobs import get_batchjob

        respx.get("https://test.logicmonitor.com/santaba/rest/setting/batchjobs/9999").mock(
            return_value=httpx.Response(404, json={"errorMessage": "Not found"})
        )

        result = await get_batchjob(client, batchjob_id=9999)
        assert "Error" in result[0].text or "error" in result[0].text.lower()

    @respx.mock
    async def test_get_batchjobs_500(self, client):
        """get_batchjobs handles 500 response."""
        from lm_mcp.tools.batchjobs import get_batchjobs

        respx.get("https://test.logicmonitor.com/santaba/rest/setting/batchjobs").mock(
            return_value=httpx.Response(500, json={"errorMessage": "Server error"})
        )

        result = await get_batchjobs(client)
        assert "Error" in result[0].text or "error" in result[0].text.lower()

    @respx.mock
    async def test_get_device_batchjobs_404(self, client):
        """get_device_batchjobs handles 404 for invalid device."""
        from lm_mcp.tools.batchjobs import get_device_batchjobs

        respx.get(
            "https://test.logicmonitor.com/santaba/rest/device/devices/9999/devicedatasources"
        ).mock(return_value=httpx.Response(404, json={"errorMessage": "Device not found"}))

        result = await get_device_batchjobs(client, device_id=9999)
        assert "Error" in result[0].text or "error" in result[0].text.lower()


class TestAuditToolErrors:
    """Tests for audit tool bug fix where happenedOn is epoch int, not string."""

    @respx.mock
    async def test_get_change_audit_handles_int_happened_on(self, client):
        """get_change_audit handles happenedOn as epoch integer."""
        from lm_mcp.tools.audit import get_change_audit

        respx.get("https://test.logicmonitor.com/santaba/rest/setting/accesslogs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "log1",
                            "username": "admin",
                            "happenedOn": 1702500000,
                            "happenedOnLocal": "2023-12-14 10:00:00",
                            "description": '"Action=Update"; "Type=Device"',
                            "ip": "192.168.1.1",
                        },
                        {
                            "id": "log2",
                            "username": "admin",
                            "happenedOn": 1702500060,
                            "happenedOnLocal": "2023-12-14 10:01:00",
                            "description": "User logged in",
                            "ip": "192.168.1.1",
                        },
                    ],
                    "total": 2,
                },
            )
        )

        result = await get_change_audit(client)
        assert len(result) == 1
        # Only the Update entry should be included, not the login
        assert "Update" in result[0].text
        assert "logged in" not in result[0].text

    @respx.mock
    async def test_get_change_audit_empty_items(self, client):
        """get_change_audit handles empty results gracefully."""
        from lm_mcp.tools.audit import get_change_audit

        respx.get("https://test.logicmonitor.com/santaba/rest/setting/accesslogs").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        result = await get_change_audit(client)
        assert len(result) == 1
        assert "0" in result[0].text


def _tools_records(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "lm_mcp.tools"]


class TestHandleErrorLogsLMErrors:
    """handle_error logs every LMError at WARNING with its code and details (R3.7)."""

    def test_permission_error_logs_code_and_details(self, caplog):
        """A 403 leaves one WARNING on lm_mcp.tools carrying the code and the details text."""
        error = LMPermissionError("Permission denied")
        error.details = "Token lacks the Manage role on group 42"

        with caplog.at_level(logging.WARNING, logger="lm_mcp.tools"):
            result = handle_error(error)

        assert is_error_result(result)
        records = _tools_records(caplog)
        assert len(records) == 1
        assert records[0].levelno == logging.WARNING
        assert "PERMISSION_DENIED" in records[0].getMessage()
        assert "Token lacks the Manage role on group 42" in records[0].getMessage()
        assert "unhandled error" not in caplog.text

    @respx.mock
    async def test_server_error_after_retries_logs_the_raw_message(self, auth, caplog):
        """A 500 that exhausted its retries logs the server's own message at WARNING."""
        from lm_mcp.tools.batchjobs import get_batchjobs

        client = LogicMonitorClient(
            base_url="https://test.logicmonitor.com/santaba/rest",
            auth=auth,
            timeout=30,
            api_version=3,
            max_retries=0,
        )
        respx.get("https://test.logicmonitor.com/santaba/rest/setting/batchjobs").mock(
            return_value=httpx.Response(
                500, json={"errorMessage": "Backend unavailable: shard 3 is read-only"}
            )
        )

        with caplog.at_level(logging.WARNING, logger="lm_mcp.tools"):
            result = await get_batchjobs(client)

        assert is_error_result(result)
        records = _tools_records(caplog)
        assert len(records) == 1
        assert "SERVER_ERROR" in records[0].getMessage()
        assert "Backend unavailable: shard 3 is read-only" in records[0].getMessage()
