# Description: Tests for device MCP tools.
# Description: Validates device and device group CRUD functions, including bulk operations.

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


class TestGetDevices:
    """Tests for get_devices tool."""

    @respx.mock
    async def test_get_devices_returns_formatted_response(self, client):
        """get_devices returns properly formatted device list."""
        from lm_mcp.tools.devices import get_devices

        respx.get("https://test.logicmonitor.com/santaba/rest/device/devices").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": 1,
                            "displayName": "server01",
                            "hostStatus": 1,
                            "currentCollectorId": 5,
                        }
                    ],
                    "total": 1,
                },
            )
        )

        result = await get_devices(client)

        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["total"] == 1
        assert data["devices"][0]["name"] == "server01"

    @respx.mock
    async def test_get_devices_with_name_filter(self, client):
        """get_devices passes name filter to API."""
        from lm_mcp.tools.devices import get_devices

        route = respx.get("https://test.logicmonitor.com/santaba/rest/device/devices").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        await get_devices(client, name_filter="prod*")

        assert "filter" in route.calls[0].request.url.params

    @respx.mock
    async def test_get_devices_with_group_filter(self, client):
        """get_devices filters by group ID."""
        from lm_mcp.tools.devices import get_devices

        route = respx.get("https://test.logicmonitor.com/santaba/rest/device/devices").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        await get_devices(client, group_id=10)

        assert "filter" in route.calls[0].request.url.params

    @respx.mock
    async def test_get_devices_with_raw_filter(self, client):
        """get_devices passes raw filter expression to API."""
        from lm_mcp.tools.devices import get_devices

        route = respx.get("https://test.logicmonitor.com/santaba/rest/device/devices").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        await get_devices(client, filter="systemProperties.name:system.hostname")

        params = dict(route.calls[0].request.url.params)
        assert "filter" in params
        assert "systemProperties" in params["filter"]

    @respx.mock
    async def test_get_devices_with_status_filter(self, client):
        """get_devices filters by device status using string values."""
        from lm_mcp.tools.devices import get_devices

        route = respx.get("https://test.logicmonitor.com/santaba/rest/device/devices").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        await get_devices(client, status="dead")

        params = dict(route.calls[0].request.url.params)
        assert "filter" in params
        assert 'hostStatus:"dead"' in params["filter"]

    @respx.mock
    async def test_get_devices_status_dead_collector(self, client):
        """get_devices filters by dead-collector status."""
        from lm_mcp.tools.devices import get_devices

        route = respx.get("https://test.logicmonitor.com/santaba/rest/device/devices").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        await get_devices(client, status="dead-collector")

        params = dict(route.calls[0].request.url.params)
        assert "filter" in params
        assert 'hostStatus:"dead-collector"' in params["filter"]

    @respx.mock
    async def test_get_devices_negative_total_sanitized(self, client):
        """get_devices converts negative API total to positive."""
        from lm_mcp.tools.devices import get_devices

        respx.get("https://test.logicmonitor.com/santaba/rest/device/devices").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": 1,
                            "displayName": "srv",
                            "hostStatus": "normal",
                            "currentCollectorId": 1,
                        }
                    ],
                    "total": -51,
                },
            )
        )

        result = await get_devices(client, limit=50)
        data = json.loads(result[0].text)
        assert data["total"] == 51

    @respx.mock
    async def test_get_devices_combined_filters(self, client):
        """get_devices combines multiple filter parameters."""
        from lm_mcp.tools.devices import get_devices

        route = respx.get("https://test.logicmonitor.com/santaba/rest/device/devices").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        await get_devices(client, name_filter="prod*", status="normal", group_id=5)

        params = dict(route.calls[0].request.url.params)
        assert "filter" in params
        # Should contain all three filters combined with AND
        assert "displayName" in params["filter"]
        assert "hostStatus" in params["filter"]
        assert "hostGroupIds" in params["filter"]

    @respx.mock
    async def test_get_devices_with_hostname_filter(self, client):
        """get_devices filters by hostname/IP via the name field."""
        from lm_mcp.tools.devices import get_devices

        route = respx.get("https://test.logicmonitor.com/santaba/rest/device/devices").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        await get_devices(client, hostname_filter="192.168.1")

        params = dict(route.calls[0].request.url.params)
        assert "filter" in params
        # Should filter on the 'name' field (hostname/IP), not displayName
        assert "name~" in params["filter"]
        assert "displayName" not in params["filter"]

    @respx.mock
    async def test_get_devices_hostname_and_name_filter_combined(self, client):
        """get_devices combines hostname_filter and name_filter."""
        from lm_mcp.tools.devices import get_devices

        route = respx.get("https://test.logicmonitor.com/santaba/rest/device/devices").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        await get_devices(client, name_filter="prod", hostname_filter="10.0")

        params = dict(route.calls[0].request.url.params)
        assert "displayName" in params["filter"]
        assert "name~" in params["filter"]

    @respx.mock
    async def test_get_devices_raw_filter_overrides_named(self, client):
        """Raw filter takes precedence when provided."""
        from lm_mcp.tools.devices import get_devices

        route = respx.get("https://test.logicmonitor.com/santaba/rest/device/devices").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        await get_devices(client, name_filter="ignored", filter="customProperties.name:env")

        params = dict(route.calls[0].request.url.params)
        assert "customProperties" in params["filter"]
        # Raw filter should be used, not the named filter
        assert "displayName~ignored" not in params["filter"]


class TestGetDevice:
    """Tests for get_device tool."""

    @respx.mock
    async def test_get_device_returns_details(self, client):
        """get_device returns single device details."""
        from lm_mcp.tools.devices import get_device

        respx.get("https://test.logicmonitor.com/santaba/rest/device/devices/123").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 123,
                    "displayName": "server01",
                    "hostStatus": 1,
                    "systemProperties": [
                        {"name": "system.hostname", "value": "server01.example.com"}
                    ],
                },
            )
        )

        result = await get_device(client, device_id=123)

        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["id"] == 123

    @respx.mock
    async def test_get_device_not_found(self, client):
        """get_device returns error for missing device."""
        from lm_mcp.tools.devices import get_device

        respx.get("https://test.logicmonitor.com/santaba/rest/device/devices/999").mock(
            return_value=httpx.Response(404, json={"errorMessage": "Device not found"})
        )

        result = await get_device(client, device_id=999)

        assert "Error:" in result[0].text


class TestGetDeviceGroups:
    """Tests for get_device_groups tool."""

    @respx.mock
    async def test_get_device_groups_returns_list(self, client):
        """get_device_groups returns group list."""
        from lm_mcp.tools.devices import get_device_groups

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

        result = await get_device_groups(client)

        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["total"] == 2
        assert len(data["groups"]) == 2

    @respx.mock
    async def test_get_device_groups_with_parent_filter(self, client):
        """get_device_groups filters by parent ID."""
        from lm_mcp.tools.devices import get_device_groups

        route = respx.get("https://test.logicmonitor.com/santaba/rest/device/groups").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        await get_device_groups(client, parent_id=1)

        assert "filter" in route.calls[0].request.url.params


class TestCreateDevice:
    """Tests for create_device tool."""

    @respx.mock
    async def test_create_device_returns_blocked_when_disabled(self, client, monkeypatch):
        """create_device returns error when write operations disabled."""
        from lm_mcp.tools.devices import create_device

        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "false")

        result = await create_device(
            client, name="10.0.0.1", display_name="test-server", preferred_collector_id=1
        )

        assert "Write operations are disabled" in result[0].text

    @respx.mock
    async def test_create_device_success(self, client, monkeypatch):
        """create_device creates device when write enabled."""
        from lm_mcp.tools.devices import create_device

        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "true")

        respx.post("https://test.logicmonitor.com/santaba/rest/device/devices").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 100,
                    "name": "10.0.0.1",
                    "displayName": "test-server",
                    "currentCollectorId": 1,
                },
            )
        )

        result = await create_device(
            client, name="10.0.0.1", display_name="test-server", preferred_collector_id=1
        )

        data = json.loads(result[0].text)
        assert data["message"] == "Device created successfully"
        assert data["device"]["id"] == 100


class TestUpdateDevice:
    """Tests for update_device tool."""

    @respx.mock
    async def test_update_device_returns_blocked_when_disabled(self, client, monkeypatch):
        """update_device returns error when write operations disabled."""
        from lm_mcp.tools.devices import update_device

        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "false")

        result = await update_device(client, device_id=100, display_name="new-name")

        assert "Write operations are disabled" in result[0].text

    @respx.mock
    async def test_update_device_success(self, client, monkeypatch):
        """update_device updates device when write enabled."""
        from lm_mcp.tools.devices import update_device

        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "true")

        respx.patch("https://test.logicmonitor.com/santaba/rest/device/devices/100").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 100,
                    "displayName": "new-name",
                    "description": "Updated description",
                },
            )
        )

        result = await update_device(
            client, device_id=100, display_name="new-name", description="Updated description"
        )

        data = json.loads(result[0].text)
        assert data["message"] == "Device updated successfully"
        assert data["device"]["name"] == "new-name"

    @respx.mock
    async def test_update_device_no_changes(self, client, monkeypatch):
        """update_device returns error when no updates provided."""
        from lm_mcp.tools.devices import update_device

        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "true")

        result = await update_device(client, device_id=100)

        assert "No updates provided" in result[0].text

    @respx.mock
    async def test_update_device_merges_custom_properties(self, client, monkeypatch):
        """update_device merges custom_properties with existing instead of replacing."""
        from lm_mcp.tools.devices import update_device

        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "true")

        # GET to fetch existing custom properties
        respx.get("https://test.logicmonitor.com/santaba/rest/device/devices/100").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 100,
                    "displayName": "server01",
                    "customProperties": [
                        {"name": "env", "value": "prod"},
                        {"name": "team", "value": "platform"},
                        {"name": "region", "value": "us-east"},
                    ],
                },
            )
        )

        # PATCH with merged properties
        route = respx.patch("https://test.logicmonitor.com/santaba/rest/device/devices/100").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 100,
                    "displayName": "server01",
                    "description": "",
                },
            )
        )

        # Only update env and add a new property "owner"
        result = await update_device(
            client,
            device_id=100,
            custom_properties={"env": "staging", "owner": "ryan"},
        )

        data = json.loads(result[0].text)
        assert data["message"] == "Device updated successfully"

        # Verify the PATCH body contains merged properties
        request_body = json.loads(route.calls[0].request.content)
        sent_props = {p["name"]: p["value"] for p in request_body["customProperties"]}
        # Existing "team" and "region" should be preserved
        assert sent_props["team"] == "platform"
        assert sent_props["region"] == "us-east"
        # "env" should be overridden, "owner" should be added
        assert sent_props["env"] == "staging"
        assert sent_props["owner"] == "ryan"

    @respx.mock
    async def test_update_device_custom_properties_without_existing(self, client, monkeypatch):
        """update_device handles devices with no existing custom properties."""
        from lm_mcp.tools.devices import update_device

        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "true")

        # GET returns device with no custom properties
        respx.get("https://test.logicmonitor.com/santaba/rest/device/devices/101").mock(
            return_value=httpx.Response(
                200,
                json={"id": 101, "displayName": "new-server", "customProperties": []},
            )
        )

        route = respx.patch("https://test.logicmonitor.com/santaba/rest/device/devices/101").mock(
            return_value=httpx.Response(
                200,
                json={"id": 101, "displayName": "new-server", "description": ""},
            )
        )

        result = await update_device(
            client,
            device_id=101,
            custom_properties={"env": "dev"},
        )

        data = json.loads(result[0].text)
        assert data["message"] == "Device updated successfully"

        request_body = json.loads(route.calls[0].request.content)
        sent_props = {p["name"]: p["value"] for p in request_body["customProperties"]}
        assert sent_props == {"env": "dev"}


class TestDeleteDevice:
    """Tests for delete_device tool."""

    @respx.mock
    async def test_delete_device_returns_blocked_when_disabled(self, client, monkeypatch):
        """delete_device returns error when write operations disabled."""
        from lm_mcp.tools.devices import delete_device

        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "false")

        result = await delete_device(client, device_id=100)

        assert "Write operations are disabled" in result[0].text

    @respx.mock
    async def test_delete_device_success(self, client, monkeypatch):
        """delete_device deletes device when write enabled."""
        from lm_mcp.tools.devices import delete_device

        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "true")

        # GET device info first
        respx.get("https://test.logicmonitor.com/santaba/rest/device/devices/100").mock(
            return_value=httpx.Response(
                200, json={"id": 100, "displayName": "test-server", "name": "192.168.1.1"}
            )
        )
        respx.delete("https://test.logicmonitor.com/santaba/rest/device/devices/100").mock(
            return_value=httpx.Response(200, json={})
        )

        result = await delete_device(client, device_id=100)

        data = json.loads(result[0].text)
        assert data["success"] is True
        assert "test-server" in data["message"]
        assert data["hard_delete"] is False
        assert data["recoverable"] is True


class TestCreateDeviceGroup:
    """Tests for create_device_group tool."""

    @respx.mock
    async def test_create_device_group_returns_blocked_when_disabled(self, client, monkeypatch):
        """create_device_group returns error when write operations disabled."""
        from lm_mcp.tools.devices import create_device_group

        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "false")

        result = await create_device_group(client, name="Test Group")

        assert "Write operations are disabled" in result[0].text

    @respx.mock
    async def test_create_device_group_success(self, client, monkeypatch):
        """create_device_group creates group when write enabled."""
        from lm_mcp.tools.devices import create_device_group

        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "true")

        respx.post("https://test.logicmonitor.com/santaba/rest/device/groups").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 50,
                    "name": "Test Group",
                    "parentId": 1,
                    "fullPath": "/Test Group",
                },
            )
        )

        result = await create_device_group(client, name="Test Group", description="Test")

        data = json.loads(result[0].text)
        assert data["message"] == "Device group created successfully"
        assert data["group"]["id"] == 50


class TestDeleteDeviceGroup:
    """Tests for delete_device_group tool."""

    @respx.mock
    async def test_delete_device_group_returns_blocked_when_disabled(self, client, monkeypatch):
        """delete_device_group returns error when write operations disabled."""
        from lm_mcp.tools.devices import delete_device_group

        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "false")

        result = await delete_device_group(client, group_id=50)

        assert "Write operations are disabled" in result[0].text

    @respx.mock
    async def test_delete_device_group_success(self, client, monkeypatch):
        """delete_device_group deletes group when write enabled."""
        from lm_mcp.tools.devices import delete_device_group

        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "true")

        # GET group info first for impact assessment
        respx.get("https://test.logicmonitor.com/santaba/rest/device/groups/50").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 50,
                    "name": "Test Group",
                    "fullPath": "/Test Group",
                    "numOfHosts": 0,
                    "numOfDirectSubGroups": 0,
                },
            )
        )
        respx.delete("https://test.logicmonitor.com/santaba/rest/device/groups/50").mock(
            return_value=httpx.Response(200, json={})
        )

        result = await delete_device_group(client, group_id=50)

        data = json.loads(result[0].text)
        assert data["success"] is True
        assert "Test Group" in data["message"]
        assert data["recoverable"] is True


class TestGetDeviceGroup:
    """Tests for get_device_group tool."""

    @respx.mock
    async def test_get_device_group_returns_full_detail(self, client):
        """get_device_group returns full group details including appliesTo."""
        from lm_mcp.tools.devices import get_device_group

        respx.get("https://test.logicmonitor.com/santaba/rest/device/groups/493").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 493,
                    "name": "OpenShift",
                    "parentId": 106,
                    "appliesTo": "",
                    "numOfHosts": 1911,
                    "description": "OpenShift clusters",
                },
            )
        )

        result = await get_device_group(client, group_id=493)
        data = json.loads(result[0].text)
        assert data["id"] == 493
        assert data["parentId"] == 106
        assert "appliesTo" in data


class TestRecoverDevice:
    """Tests for recover_device tool."""

    @respx.mock
    async def test_recover_device_success(self, client, monkeypatch):
        """recover_device restores a soft-deleted device."""
        from lm_mcp.tools.devices import recover_device

        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "true")

        respx.patch("https://test.logicmonitor.com/santaba/rest/device/devices/12345").mock(
            return_value=httpx.Response(
                200,
                json={"id": 12345, "displayName": "restored-server", "hostStatus": "normal"},
            )
        )

        result = await recover_device(client, device_id=12345)
        data = json.loads(result[0].text)
        assert data["success"] is True
        assert data["device_name"] == "restored-server"


class TestDeleteDeviceGuardrails:
    """Tests for delete_device guardrails."""

    @respx.mock
    async def test_delete_k8s_device_warns(self, client, monkeypatch):
        """delete_device warns when deleting a Kubernetes-managed device."""
        from lm_mcp.tools.devices import delete_device

        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "true")

        respx.get("https://test.logicmonitor.com/santaba/rest/device/devices/999").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 999,
                    "displayName": "k8s-pod",
                    "deviceType": 8,
                    "hostStatus": "normal",
                    "currentCollectorId": 94,
                    "hostGroupIds": "1977,120",
                },
            )
        )
        respx.delete("https://test.logicmonitor.com/santaba/rest/device/devices/999").mock(
            return_value=httpx.Response(200, json={})
        )

        result = await delete_device(client, device_id=999)
        data = json.loads(result[0].text)
        assert data["success"] is True
        assert "warnings" in data
        assert any("Kubernetes" in w for w in data["warnings"])
        assert data["deleted_device"]["type"] == 8


class TestUpdateDeviceK8sWarning:
    """Tests for update_device K8S group change warning."""

    @respx.mock
    async def test_update_k8s_device_group_warns(self, client, monkeypatch):
        """update_device warns when group change fails on K8S device."""
        from lm_mcp.tools.devices import update_device

        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "true")

        # Mock the property fetch for custom_properties merge
        respx.get("https://test.logicmonitor.com/santaba/rest/device/devices/999").mock(
            return_value=httpx.Response(200, json={"customProperties": []})
        )
        respx.patch("https://test.logicmonitor.com/santaba/rest/device/devices/999").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 999,
                    "displayName": "k8s-pod",
                    "description": "",
                    "deviceType": 8,
                    "hostGroupIds": "1977,2015,120",
                },
            )
        )

        result = await update_device(client, device_id=999, host_group_ids=[1977, 120])
        data = json.loads(result[0].text)
        assert "warning" in data
        assert "Kubernetes" in data["warning"]


class TestBulkDeleteDevices:
    """Tests for bulk_delete_devices tool."""

    @respx.mock
    async def test_bulk_delete_empty_list(self, client, monkeypatch):
        """bulk_delete_devices returns error for empty list."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "true")
        from lm_mcp.tools.devices import bulk_delete_devices

        result = await bulk_delete_devices(client, device_ids=[])
        assert "No device IDs provided" in result[0].text

    @respx.mock
    async def test_bulk_delete_exceeds_limit(self, client, monkeypatch):
        """bulk_delete_devices returns error when exceeding 100 device limit."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "true")
        from lm_mcp.tools.devices import bulk_delete_devices

        result = await bulk_delete_devices(client, device_ids=list(range(101)))
        assert "Too many devices" in result[0].text
        assert "Max 100" in result[0].text

    @respx.mock
    async def test_bulk_delete_success_with_k8s_warning(self, client, monkeypatch):
        """bulk_delete_devices includes K8S warnings for deviceType 8."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "true")
        from lm_mcp.tools.devices import bulk_delete_devices

        base_url = "https://test.logicmonitor.com/santaba/rest"
        respx.get(f"{base_url}/device/devices/1").mock(
            return_value=httpx.Response(
                200, json={"id": 1, "displayName": "k8s-pod", "deviceType": 8}
            )
        )
        respx.delete(f"{base_url}/device/devices/1").mock(return_value=httpx.Response(200, json={}))
        respx.get(f"{base_url}/device/devices/2").mock(
            return_value=httpx.Response(
                200, json={"id": 2, "displayName": "normal-srv", "deviceType": 0}
            )
        )
        respx.delete(f"{base_url}/device/devices/2").mock(return_value=httpx.Response(200, json={}))

        result = await bulk_delete_devices(client, device_ids=[1, 2])
        data = json.loads(result[0].text)
        assert data["succeeded"] == 2
        assert data["failed"] == 0
        assert len(data["warnings"]) == 1
        assert "Kubernetes" in data["warnings"][0]

    @respx.mock
    async def test_bulk_delete_partial_failure(self, client, monkeypatch):
        """bulk_delete_devices handles partial failures."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "true")
        from lm_mcp.tools.devices import bulk_delete_devices

        base_url = "https://test.logicmonitor.com/santaba/rest"
        respx.get(f"{base_url}/device/devices/1").mock(
            return_value=httpx.Response(200, json={"id": 1, "displayName": "srv1", "deviceType": 0})
        )
        respx.delete(f"{base_url}/device/devices/1").mock(return_value=httpx.Response(200, json={}))
        respx.get(f"{base_url}/device/devices/999").mock(
            return_value=httpx.Response(404, json={"errorMessage": "Not found"})
        )

        result = await bulk_delete_devices(client, device_ids=[1, 999])
        data = json.loads(result[0].text)
        assert data["succeeded"] == 1
        assert data["failed"] == 1


class TestHostStatusFilterForm:
    """The v3 API filters hostStatus on the quoted word; numeric codes match nothing."""

    def test_every_status_maps_to_a_quoted_word(self):
        from lm_mcp.tools.devices import DEVICE_STATUS_MAP

        for name, value in DEVICE_STATUS_MAP.items():
            assert value == f'"{name}"'

    def test_dead_guard_accepts_word_and_number(self):
        from lm_mcp.tools.diagnostic_remediation import is_dead_host_status

        assert is_dead_host_status("dead") and is_dead_host_status("Dead ")
        assert is_dead_host_status(1) and is_dead_host_status("1")
        assert not is_dead_host_status("normal") and not is_dead_host_status(0)
        assert not is_dead_host_status(None)

    def test_resources_teach_no_numeric_host_status(self):
        import json
        import re

        from lm_mcp.resources import enums, filters, guides

        text = json.dumps(
            [getattr(m, n) for m in (enums, filters, guides) for n in dir(m) if n.isupper()],
            default=str,
        )
        assert not re.search(r"hostStatus!?:\d", text)
