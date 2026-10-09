# Description: Tests for remediation source MCP tools.
# Description: Validates read, execution, status, and history functions.

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


@pytest.fixture
def enable_writes(monkeypatch):
    """Enable write operations for testing."""
    monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
    monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
    monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "true")

    from importlib import reload

    import lm_mcp.config

    reload(lm_mcp.config)


class TestGetRemediationSources:
    """Tests for get_remediationsources tool."""

    @respx.mock
    async def test_get_remediationsources_returns_list(self, client):
        """get_remediationsources reads /setting/remediationsources and projects items."""
        from lm_mcp.tools.remediationsources import get_remediationsources

        respx.get("https://test.logicmonitor.com/santaba/rest/setting/remediationsources").mock(
            return_value=httpx.Response(
                200,
                json={
                    "total": 2,
                    "items": [
                        {
                            "id": 1,
                            "name": "Restart_Service",
                            "displayName": "Restart Service",
                            "description": "Restart a failed service",
                            "appliesTo": "isLinux()",
                            "group": "Services",
                            "collectMethod": "script",
                            "tags": ["restart", "service"],
                            "technicalNotes": "Uses systemctl",
                        },
                        {
                            "id": 2,
                            "name": "Clear_Disk",
                            "displayName": "Clear Disk",
                            "description": "Clear temp files",
                            "group": "Storage",
                            "collectMethod": "script",
                            "tags": ["disk", "cleanup"],
                        },
                    ],
                },
            )
        )

        result = await get_remediationsources(client)

        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["total"] == 2
        assert data["count"] == 2
        assert data["offset"] == 0
        assert data["has_more"] is False
        names = {s["name"] for s in data["remediationsources"]}
        assert names == {"Restart_Service", "Clear_Disk"}

    @respx.mock
    async def test_get_remediationsources_with_name_filter(self, client):
        """name_filter builds a server-side filter clause."""
        from lm_mcp.tools.remediationsources import get_remediationsources

        route = respx.get(
            "https://test.logicmonitor.com/santaba/rest/setting/remediationsources"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "total": 1,
                    "items": [{"id": 1, "name": "Restart_Service", "group": "Services"}],
                },
            )
        )

        result = await get_remediationsources(client, name_filter="Restart")

        assert route.called
        filter_param = route.calls.last.request.url.params.get("filter", "")
        assert "name~" in filter_param
        assert "Restart" in filter_param

        data = json.loads(result[0].text)
        assert data["count"] == 1
        assert data["remediationsources"][0]["name"] == "Restart_Service"

    @respx.mock
    async def test_get_remediationsources_with_group_filter(self, client):
        """group_filter builds a server-side filter clause."""
        from lm_mcp.tools.remediationsources import get_remediationsources

        route = respx.get(
            "https://test.logicmonitor.com/santaba/rest/setting/remediationsources"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "total": 1,
                    "items": [{"id": 2, "name": "Clear_Disk", "group": "Storage"}],
                },
            )
        )

        result = await get_remediationsources(client, group_filter="Storage")

        assert route.called
        filter_param = route.calls.last.request.url.params.get("filter", "")
        assert "group~" in filter_param

        data = json.loads(result[0].text)
        assert data["count"] == 1
        assert data["remediationsources"][0]["group"] == "Storage"

    @respx.mock
    async def test_get_remediationsources_raw_filter_overrides_typed(self, client):
        """Raw filter parameter overrides typed name/group filters."""
        from lm_mcp.tools.remediationsources import get_remediationsources

        route = respx.get(
            "https://test.logicmonitor.com/santaba/rest/setting/remediationsources"
        ).mock(return_value=httpx.Response(200, json={"total": 0, "items": []}))

        await get_remediationsources(
            client,
            name_filter="ignored",
            filter='group:"Custom"',
        )

        params = route.calls.last.request.url.params
        assert params.get("filter") == 'group:"Custom"'

    @respx.mock
    async def test_get_remediationsources_pagination_passed_to_api(self, client):
        """limit/offset map to size/offset query params."""
        from lm_mcp.tools.remediationsources import get_remediationsources

        route = respx.get(
            "https://test.logicmonitor.com/santaba/rest/setting/remediationsources"
        ).mock(return_value=httpx.Response(200, json={"total": 200, "items": []}))

        result = await get_remediationsources(client, limit=25, offset=50)

        params = route.calls.last.request.url.params
        assert params.get("size") == "25"
        assert params.get("offset") == "50"

        data = json.loads(result[0].text)
        assert data["offset"] == 50
        assert data["has_more"] is True

    @respx.mock
    async def test_get_remediationsources_empty_response(self, client):
        """get_remediationsources handles an empty items list."""
        from lm_mcp.tools.remediationsources import get_remediationsources

        respx.get("https://test.logicmonitor.com/santaba/rest/setting/remediationsources").mock(
            return_value=httpx.Response(200, json={"total": 0, "items": []})
        )

        result = await get_remediationsources(client)

        data = json.loads(result[0].text)
        assert data["total"] == 0
        assert data["count"] == 0
        assert data["remediationsources"] == []

    @respx.mock
    async def test_get_remediationsources_handles_error(self, client):
        """get_remediationsources returns a structured error on API failure."""
        from lm_mcp.tools.remediationsources import get_remediationsources

        respx.get("https://test.logicmonitor.com/santaba/rest/setting/remediationsources").mock(
            return_value=httpx.Response(500, json={"errorMessage": "Server error"})
        )

        result = await get_remediationsources(client)

        assert "Error:" in result[0].text


class TestGetRemediationSource:
    """Tests for get_remediationsource tool."""

    @respx.mock
    async def test_get_remediationsource_returns_details(self, client):
        """get_remediationsource returns detailed source info."""
        from lm_mcp.tools.remediationsources import get_remediationsource

        respx.get("https://test.logicmonitor.com/santaba/rest/setting/remediationsources/10").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 10,
                    "name": "Restart_Service",
                    "displayName": "Restart Service",
                    "description": "Restart a systemd service",
                    "appliesTo": "isLinux()",
                    "group": "Services",
                    "collectMethod": "script",
                    "collectInterval": 300,
                    "tags": ["restart"],
                    "technicalNotes": "Uses systemctl restart",
                    "groovyScript": "println 'restart'",
                },
            )
        )

        result = await get_remediationsource(client, source_id=10)

        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["id"] == 10
        assert data["name"] == "Restart_Service"
        assert data["display_name"] == "Restart Service"
        assert data["group"] == "Services"
        assert data["collect_interval"] == 300
        assert data["groovy_script"] == "println 'restart'"

    @respx.mock
    async def test_get_remediationsource_not_found(self, client):
        """get_remediationsource returns error for missing source."""
        from lm_mcp.tools.remediationsources import get_remediationsource

        respx.get("https://test.logicmonitor.com/santaba/rest/setting/remediationsources/999").mock(
            return_value=httpx.Response(404, json={"errorMessage": "Not found"})
        )

        result = await get_remediationsource(client, source_id=999)

        assert "Error:" in result[0].text


class TestRemediationSourceToolRegistration:
    """Tests for remediation source tool registration."""

    def test_get_remediationsources_registered(self):
        """get_remediationsources is registered in tool registry."""
        from lm_mcp.registry import TOOLS

        tool_names = [t.name for t in TOOLS]
        assert "get_remediationsources" in tool_names

    def test_get_remediationsource_registered(self):
        """get_remediationsource is registered in tool registry."""
        from lm_mcp.registry import TOOLS

        tool_names = [t.name for t in TOOLS]
        assert "get_remediationsource" in tool_names

    def test_get_remediationsources_handler_registered(self):
        """get_remediationsources handler is registered."""
        from lm_mcp.registry import get_tool_handler

        handler = get_tool_handler("get_remediationsources")
        assert handler is not None

    def test_get_remediationsource_handler_registered(self):
        """get_remediationsource handler is registered."""
        from lm_mcp.registry import get_tool_handler

        handler = get_tool_handler("get_remediationsource")
        assert handler is not None

    def test_execute_remediation_registered(self):
        """execute_remediation is registered in tool registry."""
        from lm_mcp.registry import TOOLS

        tool_names = [t.name for t in TOOLS]
        assert "execute_remediation" in tool_names

    def test_execute_remediation_handler_registered(self):
        """execute_remediation handler is registered."""
        from lm_mcp.registry import get_tool_handler

        handler = get_tool_handler("execute_remediation")
        assert handler is not None

    def test_get_remediationsources_schema_includes_pagination(self):
        """Schema advertises limit/offset/filter for the public REST surface."""
        from lm_mcp.registry import TOOLS

        tool = next(t for t in TOOLS if t.name == "get_remediationsources")
        props = tool.inputSchema["properties"]
        for required in ("name_filter", "group_filter", "filter", "limit", "offset"):
            assert required in props

    def test_descriptions_drop_preview_marker(self):
        """[PREVIEW] prefix is gone now that the tools call the public REST endpoint."""
        from lm_mcp.registry import TOOLS

        for name in ("get_remediationsources", "get_remediationsource"):
            tool = next(t for t in TOOLS if t.name == name)
            assert "[PREVIEW]" not in tool.description


class TestExecuteRemediation:
    """Tests for execute_remediation tool."""

    async def test_execute_remediation_requires_write_permission(self, client, monkeypatch):
        """execute_remediation requires write permission."""
        from lm_mcp.tools.remediationsources import execute_remediation

        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "false")

        from importlib import reload

        import lm_mcp.config

        reload(lm_mcp.config)

        result = await execute_remediation(client, host_id=1, remediation_source_id=100)
        assert "Write operations are disabled" in result[0].text

    @respx.mock
    async def test_execute_remediation_dead_device_blocked(self, client, enable_writes):
        """execute_remediation blocks execution on dead devices."""
        from lm_mcp.tools.remediationsources import execute_remediation

        respx.get("https://test.logicmonitor.com/santaba/rest/device/devices/1").mock(
            return_value=httpx.Response(
                200,
                json={"id": 1, "hostStatus": 1, "preferredCollectorId": 10},
            )
        )

        result = await execute_remediation(client, host_id=1, remediation_source_id=100)
        data = result[0].text
        assert "dead" in data.lower() or "DEVICE_UNREACHABLE" in data

    @respx.mock
    async def test_execute_remediation_dead_device_word_form_blocked(self, client, enable_writes):
        """The v3 API reports hostStatus as the word "dead"; that must block too."""
        from lm_mcp.tools.remediationsources import execute_remediation

        respx.get("https://test.logicmonitor.com/santaba/rest/device/devices/1").mock(
            return_value=httpx.Response(
                200,
                json={"id": 1, "hostStatus": "dead", "preferredCollectorId": 10},
            )
        )

        result = await execute_remediation(client, host_id=1, remediation_source_id=100)
        assert "is dead (hostStatus=dead)" in result[0].text

    @respx.mock
    async def test_execute_remediation_old_collector_blocked(self, client, enable_writes):
        """execute_remediation blocks when collector version is too old."""
        from lm_mcp.tools.remediationsources import execute_remediation

        respx.get("https://test.logicmonitor.com/santaba/rest/device/devices/1").mock(
            return_value=httpx.Response(
                200,
                json={"id": 1, "hostStatus": 0, "preferredCollectorId": 10},
            )
        )
        respx.get(
            "https://test.logicmonitor.com/santaba/rest/setting/collector/collectors/10"
        ).mock(
            return_value=httpx.Response(
                200,
                json={"id": 10, "build": "35.100"},
            )
        )

        result = await execute_remediation(client, host_id=1, remediation_source_id=100)
        data = result[0].text
        assert "COLLECTOR_VERSION_LOW" in data or "39.200" in data

    @respx.mock
    async def test_execute_remediation_happy_path(self, client, enable_writes):
        """execute_remediation succeeds with valid device and collector."""
        from lm_mcp.tools.remediationsources import execute_remediation

        respx.get("https://test.logicmonitor.com/santaba/rest/device/devices/1").mock(
            return_value=httpx.Response(
                200,
                json={"id": 1, "hostStatus": 0, "preferredCollectorId": 10},
            )
        )
        respx.get(
            "https://test.logicmonitor.com/santaba/rest/setting/collector/collectors/10"
        ).mock(
            return_value=httpx.Response(
                200,
                json={"id": 10, "build": "40.100"},
            )
        )
        respx.get("https://test.logicmonitor.com/santaba/rest/setting/remediationsources/100").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 100,
                    "name": "RestartApache",
                    "appliesTo": "isLinux()",
                    "groovyScript": "def cmd = 'systemctl restart httpd'.execute()",
                },
            )
        )
        respx.post(
            "https://test.logicmonitor.com/santaba/rest/setting/remediationsources/executemanually"
        ).mock(
            return_value=httpx.Response(
                200,
                json={"status": "initiated"},
            )
        )

        result = await execute_remediation(client, host_id=1, remediation_source_id=100)
        data = json.loads(result[0].text)
        assert data["success"] is True
        assert data["host_id"] == 1
        assert "restart" in data.get("mutation_warning", "").lower()

    @respx.mock
    async def test_execute_remediation_with_alert_id(self, client, enable_writes):
        """execute_remediation passes alert_id in the request payload."""
        from lm_mcp.tools.remediationsources import execute_remediation

        respx.get("https://test.logicmonitor.com/santaba/rest/device/devices/1").mock(
            return_value=httpx.Response(
                200,
                json={"id": 1, "hostStatus": 0, "preferredCollectorId": 10},
            )
        )
        respx.get(
            "https://test.logicmonitor.com/santaba/rest/setting/collector/collectors/10"
        ).mock(
            return_value=httpx.Response(
                200,
                json={"id": 10, "build": "40.100"},
            )
        )
        respx.get("https://test.logicmonitor.com/santaba/rest/setting/remediationsources/100").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 100,
                    "name": "CheckDisk",
                    "appliesTo": "true()",
                    "groovyScript": "println 'checking disk'",
                },
            )
        )
        post_route = respx.post(
            "https://test.logicmonitor.com/santaba/rest/setting/remediationsources/executemanually"
        ).mock(
            return_value=httpx.Response(
                200,
                json={"status": "initiated"},
            )
        )

        result = await execute_remediation(
            client, host_id=1, remediation_source_id=100, alert_id="LMA12345"
        )
        data = json.loads(result[0].text)
        assert data["alert_id"] == "LMA12345"
        # Verify alert_id was sent in the POST body
        request_body = json.loads(post_route.calls[0].request.content)
        assert request_body["alertId"] == "LMA12345"

    @respx.mock
    async def test_execute_remediation_api_error(self, client, enable_writes):
        """execute_remediation handles API errors gracefully."""
        from lm_mcp.tools.remediationsources import execute_remediation

        respx.get("https://test.logicmonitor.com/santaba/rest/device/devices/1").mock(
            return_value=httpx.Response(
                200,
                json={"id": 1, "hostStatus": 0, "preferredCollectorId": 10},
            )
        )
        respx.get(
            "https://test.logicmonitor.com/santaba/rest/setting/collector/collectors/10"
        ).mock(
            return_value=httpx.Response(
                200,
                json={"id": 10, "build": "40.100"},
            )
        )
        respx.get("https://test.logicmonitor.com/santaba/rest/setting/remediationsources/100").mock(
            return_value=httpx.Response(
                200,
                json={"id": 100, "name": "Test", "groovyScript": "test"},
            )
        )
        respx.post(
            "https://test.logicmonitor.com/santaba/rest/setting/remediationsources/executemanually"
        ).mock(
            return_value=httpx.Response(
                500,
                json={"errorMessage": "Internal server error"},
            )
        )

        result = await execute_remediation(client, host_id=1, remediation_source_id=100)
        assert "Error:" in result[0].text


class TestCreateRemediationSource:
    """Tests for create_remediationsource tool."""

    async def test_create_requires_write_permission(self, client, monkeypatch):
        """create_remediationsource is blocked when writes are disabled."""
        from lm_mcp.tools.remediationsources import create_remediationsource

        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "false")
        from importlib import reload

        import lm_mcp.config

        reload(lm_mcp.config)

        result = await create_remediationsource(client, definition={"name": "X"})

        assert "Write operations are disabled" in result[0].text

    @respx.mock
    async def test_create_posts_definition(self, client, enable_writes):
        """create_remediationsource posts the normalized definition."""
        from lm_mcp.tools.remediationsources import create_remediationsource

        route = respx.post(
            "https://test.logicmonitor.com/santaba/rest/setting/remediationsources"
        ).mock(
            return_value=httpx.Response(
                200, json={"id": 88, "name": "RestartSvc", "displayName": "Restart Service"}
            )
        )

        definition = {
            "name": "RestartSvc",
            "displayName": "Restart Service",
            "appliesTo": "false()",
            "groovyScript": "println 'restart'",
        }
        result = await create_remediationsource(client, definition=definition)

        body = json.loads(route.calls[0].request.content)
        assert body["name"] == "RestartSvc"
        assert "id" not in body
        data = json.loads(result[0].text)
        assert data["success"] is True
        assert data["remediationsource"]["id"] == 88

    @respx.mock
    async def test_create_handles_api_error(self, client, enable_writes):
        """create_remediationsource surfaces 400 errors."""
        from lm_mcp.tools.remediationsources import create_remediationsource

        respx.post("https://test.logicmonitor.com/santaba/rest/setting/remediationsources").mock(
            return_value=httpx.Response(400, json={"errorMessage": "name required"})
        )

        result = await create_remediationsource(client, definition={"displayName": "X"})

        assert "error" in result[0].text.lower()


class TestUpdateRemediationSource:
    """Tests for update_remediationsource tool."""

    async def test_update_without_confirm_is_guarded(self, client, enable_writes):
        """update_remediationsource without confirm=True returns CONFIRMATION_REQUIRED."""
        from lm_mcp.tools.remediationsources import update_remediationsource

        result = await update_remediationsource(
            client, remediationsource_id=3, definition={"name": "X"}
        )

        text = result[0].text
        assert "confirm" in text.lower()
        assert "update_logicmodule" in text

    @respx.mock
    async def test_update_with_confirm_puts_definition(self, client, enable_writes):
        """update_remediationsource with confirm=True PUTs the full definition."""
        from lm_mcp.tools.remediationsources import update_remediationsource

        route = respx.put(
            "https://test.logicmonitor.com/santaba/rest/setting/remediationsources/3"
        ).mock(return_value=httpx.Response(200, json={"id": 3, "name": "RestartSvc"}))

        definition = {"name": "RestartSvc", "displayName": "Restart", "groovyScript": "x"}
        result = await update_remediationsource(
            client, remediationsource_id=3, definition=definition, confirm=True
        )

        body = json.loads(route.calls[0].request.content)
        assert body["name"] == "RestartSvc"
        data = json.loads(result[0].text)
        assert data["success"] is True

    async def test_update_requires_write_permission(self, client, monkeypatch):
        """update_remediationsource is blocked when writes are disabled."""
        from lm_mcp.tools.remediationsources import update_remediationsource

        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "false")
        from importlib import reload

        import lm_mcp.config

        reload(lm_mcp.config)

        result = await update_remediationsource(
            client, remediationsource_id=3, definition={"name": "X"}, confirm=True
        )

        assert "Write operations are disabled" in result[0].text


class TestDeleteRemediationSource:
    """Tests for delete_remediationsource tool."""

    @respx.mock
    async def test_delete_success(self, client, enable_writes):
        """delete_remediationsource deletes and reports the source name."""
        from lm_mcp.tools.remediationsources import delete_remediationsource

        respx.get("https://test.logicmonitor.com/santaba/rest/setting/remediationsources/3").mock(
            return_value=httpx.Response(200, json={"id": 3, "name": "RestartSvc"})
        )
        respx.delete(
            "https://test.logicmonitor.com/santaba/rest/setting/remediationsources/3"
        ).mock(return_value=httpx.Response(200, json={}))

        result = await delete_remediationsource(client, remediationsource_id=3)

        data = json.loads(result[0].text)
        assert data["success"] is True
        assert "RestartSvc" in data["message"]

    @respx.mock
    async def test_delete_not_found(self, client, enable_writes):
        """delete_remediationsource surfaces 404."""
        from lm_mcp.tools.remediationsources import delete_remediationsource

        respx.get("https://test.logicmonitor.com/santaba/rest/setting/remediationsources/999").mock(
            return_value=httpx.Response(404, json={"errorMessage": "Not found"})
        )

        result = await delete_remediationsource(client, remediationsource_id=999)

        assert "error" in result[0].text.lower()
