# Description: Integration tests for resource tools workflow.
# Description: Tests SDT lifecycle and device/collector queries.

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


class TestSdtLifecycle:
    """Integration tests for SDT lifecycle."""

    @respx.mock
    async def test_sdt_create_verify_delete(self, client, monkeypatch):
        """Test complete SDT lifecycle: create -> verify -> delete."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "true")

        from importlib import reload

        import lm_mcp.config

        reload(lm_mcp.config)

        from lm_mcp.tools.sdts import create_sdt, delete_sdt, list_sdts

        # Mock: Create SDT
        respx.post("https://test.logicmonitor.com/santaba/rest/sdt/sdts").mock(
            return_value=httpx.Response(
                200,
                json={"id": "SDT_NEW", "type": "DeviceSDT"},
            )
        )

        # Mock: List SDTs (includes the new one)
        respx.get("https://test.logicmonitor.com/santaba/rest/sdt/sdts").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [{"id": "SDT_NEW", "type": "DeviceSDT", "comment": "Test SDT"}],
                    "total": 1,
                },
            )
        )

        # Mock: Delete SDT
        respx.delete("https://test.logicmonitor.com/santaba/rest/sdt/sdts/SDT_NEW").mock(
            return_value=httpx.Response(200, json={})
        )

        # Step 1: Create SDT
        create_result = await create_sdt(
            client,
            sdt_type="DeviceSDT",
            device_id=123,
            duration_minutes=30,
            comment="Test SDT",
        )
        create_data = json.loads(create_result[0].text)
        assert create_data["success"] is True
        sdt_id = create_data["sdt_id"]

        # Step 2: Verify SDT exists
        list_result = await list_sdts(client)
        list_data = json.loads(list_result[0].text)
        assert list_data["total"] >= 1

        # Step 3: Delete SDT
        delete_result = await delete_sdt(client, sdt_id=sdt_id)
        delete_data = json.loads(delete_result[0].text)
        assert delete_data["success"] is True


class TestDeviceQueries:
    """Integration tests for device queries."""

    @respx.mock
    async def test_device_discovery_workflow(self, client):
        """Test device discovery: groups -> devices -> details."""
        from lm_mcp.tools.devices import get_device, get_device_groups, get_devices

        # Mock: Get device groups
        respx.get("https://test.logicmonitor.com/santaba/rest/device/groups").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {"id": 1, "name": "Production", "numOfHosts": 10},
                        {"id": 2, "name": "Development", "numOfHosts": 5},
                    ],
                    "total": 2,
                },
            )
        )

        # Mock: Get devices in Production group
        respx.get("https://test.logicmonitor.com/santaba/rest/device/devices").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {"id": 100, "displayName": "prod-db-01", "hostStatus": "dead"},
                        {"id": 101, "displayName": "prod-web-01", "hostStatus": "dead"},
                    ],
                    "total": 2,
                },
            )
        )

        # Mock: Get device details
        respx.get("https://test.logicmonitor.com/santaba/rest/device/devices/100").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 100,
                    "displayName": "prod-db-01",
                    "hostStatus": "dead",
                    "systemProperties": [],
                },
            )
        )

        # Step 1: List groups
        groups_result = await get_device_groups(client)
        groups_data = json.loads(groups_result[0].text)
        assert groups_data["total"] == 2
        prod_group_id = groups_data["groups"][0]["id"]

        # Step 2: List devices in group
        devices_result = await get_devices(client, group_id=prod_group_id)
        devices_data = json.loads(devices_result[0].text)
        assert devices_data["total"] == 2

        # Step 3: Get device details
        device_result = await get_device(client, device_id=100)
        device_data = json.loads(device_result[0].text)
        assert device_data["displayName"] == "prod-db-01"


class TestCollectorQueries:
    """Integration tests for collector queries."""

    @respx.mock
    async def test_collector_health_check(self, client):
        """Test collector health check workflow."""
        from lm_mcp.tools.collectors import get_collector, get_collectors

        # Mock: List collectors
        respx.get("https://test.logicmonitor.com/santaba/rest/setting/collector/collectors").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {"id": 1, "hostname": "collector01", "status": 1, "numberOfHosts": 50},
                        {"id": 2, "hostname": "collector02", "status": 0, "numberOfHosts": 30},
                    ],
                    "total": 2,
                },
            )
        )

        # Mock: Get collector details
        respx.get("https://test.logicmonitor.com/santaba/rest/setting/collector/collectors/2").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 2,
                    "hostname": "collector02",
                    "status": 0,
                    "numberOfHosts": 30,
                    "platform": "linux",
                },
            )
        )

        # Step 1: List all collectors
        collectors_result = await get_collectors(client)
        collectors_data = json.loads(collectors_result[0].text)
        assert collectors_data["total"] == 2

        # Find collector with status 0 (down)
        down_collectors = [c for c in collectors_data["collectors"] if c["status"] == 0]
        assert len(down_collectors) == 1

        # Step 2: Get details on down collector
        detail_result = await get_collector(client, collector_id=down_collectors[0]["id"])
        detail_data = json.loads(detail_result[0].text)
        assert detail_data["hostname"] == "collector02"
