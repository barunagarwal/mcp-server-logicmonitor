# Description: Tests for diagnostic source MCP tools.
# Description: Validates diagnostic source read functions against /setting/diagnosticsources.

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


class TestGetDiagnosticSources:
    """Tests for get_diagnosticsources tool."""

    @respx.mock
    async def test_get_diagnosticsources_returns_list(self, client):
        """get_diagnosticsources reads /setting/diagnosticsources and projects items."""
        from lm_mcp.tools.diagnosticsources import get_diagnosticsources

        respx.get("https://test.logicmonitor.com/santaba/rest/setting/diagnosticsources").mock(
            return_value=httpx.Response(
                200,
                json={
                    "total": 2,
                    "items": [
                        {
                            "id": 1,
                            "name": "Disk_Check",
                            "displayName": "Disk Check",
                            "description": "Check disk utilization",
                            "appliesTo": "isLinux()",
                            "group": "Storage",
                            "collectMethod": "script",
                            "tags": ["disk", "storage"],
                            "technicalNotes": "Uses df command",
                        },
                        {
                            "id": 2,
                            "name": "CPU_Check",
                            "displayName": "CPU Check",
                            "description": "Check CPU usage",
                            "group": "Compute",
                            "collectMethod": "script",
                            "tags": ["cpu"],
                        },
                    ],
                },
            )
        )

        result = await get_diagnosticsources(client)

        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["total"] == 2
        assert data["count"] == 2
        assert data["offset"] == 0
        assert data["has_more"] is False
        assert len(data["diagnosticsources"]) == 2
        names = {s["name"] for s in data["diagnosticsources"]}
        assert names == {"Disk_Check", "CPU_Check"}

    @respx.mock
    async def test_get_diagnosticsources_with_name_filter(self, client):
        """name_filter builds a server-side filter clause."""
        from lm_mcp.tools.diagnosticsources import get_diagnosticsources

        route = respx.get(
            "https://test.logicmonitor.com/santaba/rest/setting/diagnosticsources"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "total": 1,
                    "items": [
                        {
                            "id": 1,
                            "name": "Disk_Check",
                            "displayName": "Disk Check",
                            "group": "Storage",
                        }
                    ],
                },
            )
        )

        result = await get_diagnosticsources(client, name_filter="Disk")

        assert route.called
        filter_param = route.calls.last.request.url.params.get("filter", "")
        assert "name~" in filter_param
        assert "Disk" in filter_param

        data = json.loads(result[0].text)
        assert data["count"] == 1
        assert data["diagnosticsources"][0]["name"] == "Disk_Check"

    @respx.mock
    async def test_get_diagnosticsources_with_group_filter(self, client):
        """group_filter builds a server-side filter clause."""
        from lm_mcp.tools.diagnosticsources import get_diagnosticsources

        route = respx.get(
            "https://test.logicmonitor.com/santaba/rest/setting/diagnosticsources"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "total": 1,
                    "items": [
                        {
                            "id": 2,
                            "name": "CPU_Check",
                            "group": "Compute",
                        }
                    ],
                },
            )
        )

        result = await get_diagnosticsources(client, group_filter="Compute")

        assert route.called
        filter_param = route.calls.last.request.url.params.get("filter", "")
        assert "group~" in filter_param

        data = json.loads(result[0].text)
        assert data["count"] == 1
        assert data["diagnosticsources"][0]["group"] == "Compute"

    @respx.mock
    async def test_get_diagnosticsources_raw_filter_overrides_typed(self, client):
        """Raw filter parameter overrides typed name/group filters."""
        from lm_mcp.tools.diagnosticsources import get_diagnosticsources

        route = respx.get(
            "https://test.logicmonitor.com/santaba/rest/setting/diagnosticsources"
        ).mock(return_value=httpx.Response(200, json={"total": 0, "items": []}))

        await get_diagnosticsources(
            client,
            name_filter="ignored",
            filter='collectMethod:"script"',
        )

        params = route.calls.last.request.url.params
        assert params.get("filter") == 'collectMethod:"script"'

    @respx.mock
    async def test_get_diagnosticsources_pagination_passed_to_api(self, client):
        """limit/offset map to size/offset query params."""
        from lm_mcp.tools.diagnosticsources import get_diagnosticsources

        route = respx.get(
            "https://test.logicmonitor.com/santaba/rest/setting/diagnosticsources"
        ).mock(return_value=httpx.Response(200, json={"total": 200, "items": []}))

        result = await get_diagnosticsources(client, limit=25, offset=50)

        params = route.calls.last.request.url.params
        assert params.get("size") == "25"
        assert params.get("offset") == "50"

        data = json.loads(result[0].text)
        assert data["offset"] == 50
        assert data["has_more"] is True

    @respx.mock
    async def test_get_diagnosticsources_empty_response(self, client):
        """get_diagnosticsources handles an empty items list."""
        from lm_mcp.tools.diagnosticsources import get_diagnosticsources

        respx.get("https://test.logicmonitor.com/santaba/rest/setting/diagnosticsources").mock(
            return_value=httpx.Response(200, json={"total": 0, "items": []})
        )

        result = await get_diagnosticsources(client)

        data = json.loads(result[0].text)
        assert data["total"] == 0
        assert data["count"] == 0
        assert data["diagnosticsources"] == []

    @respx.mock
    async def test_get_diagnosticsources_handles_error(self, client):
        """get_diagnosticsources returns a structured error on API failure."""
        from lm_mcp.tools.diagnosticsources import get_diagnosticsources

        respx.get("https://test.logicmonitor.com/santaba/rest/setting/diagnosticsources").mock(
            return_value=httpx.Response(500, json={"errorMessage": "Server error"})
        )

        result = await get_diagnosticsources(client)

        assert "Error:" in result[0].text


class TestGetDiagnosticSource:
    """Tests for get_diagnosticsource tool."""

    @respx.mock
    async def test_get_diagnosticsource_returns_details(self, client):
        """get_diagnosticsource returns detailed source info."""
        from lm_mcp.tools.diagnosticsources import get_diagnosticsource

        respx.get("https://test.logicmonitor.com/santaba/rest/setting/diagnosticsources/10").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 10,
                    "name": "Disk_Check",
                    "displayName": "Disk Check",
                    "description": "Check disk utilization",
                    "appliesTo": "isLinux()",
                    "group": "Storage",
                    "collectMethod": "script",
                    "collectInterval": 300,
                    "tags": ["disk"],
                    "technicalNotes": "Uses df",
                    "dataPoints": [{"id": 1, "name": "usage", "type": 1, "description": "% used"}],
                },
            )
        )

        result = await get_diagnosticsource(client, source_id=10)

        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["id"] == 10
        assert data["name"] == "Disk_Check"
        assert data["display_name"] == "Disk Check"
        assert data["group"] == "Storage"
        assert data["collect_interval"] == 300
        assert len(data["datapoints"]) == 1
        assert data["datapoints"][0]["name"] == "usage"

    @respx.mock
    async def test_get_diagnosticsource_not_found(self, client):
        """get_diagnosticsource returns error for missing source."""
        from lm_mcp.tools.diagnosticsources import get_diagnosticsource

        respx.get("https://test.logicmonitor.com/santaba/rest/setting/diagnosticsources/999").mock(
            return_value=httpx.Response(404, json={"errorMessage": "Not found"})
        )

        result = await get_diagnosticsource(client, source_id=999)

        assert "Error:" in result[0].text


class TestDiagnosticSourceToolRegistration:
    """Tests for diagnostic source tool registration."""

    def test_get_diagnosticsources_registered(self):
        """get_diagnosticsources is registered in tool registry."""
        from lm_mcp.registry import TOOLS

        tool_names = [t.name for t in TOOLS]
        assert "get_diagnosticsources" in tool_names

    def test_get_diagnosticsource_registered(self):
        """get_diagnosticsource is registered in tool registry."""
        from lm_mcp.registry import TOOLS

        tool_names = [t.name for t in TOOLS]
        assert "get_diagnosticsource" in tool_names

    def test_get_diagnosticsources_handler_registered(self):
        """get_diagnosticsources handler is registered."""
        from lm_mcp.registry import get_tool_handler

        handler = get_tool_handler("get_diagnosticsources")
        assert handler is not None

    def test_get_diagnosticsource_handler_registered(self):
        """get_diagnosticsource handler is registered."""
        from lm_mcp.registry import get_tool_handler

        handler = get_tool_handler("get_diagnosticsource")
        assert handler is not None

    def test_get_diagnosticsources_schema_includes_pagination(self):
        """Schema advertises limit/offset/filter for the public REST surface."""
        from lm_mcp.registry import TOOLS

        tool = next(t for t in TOOLS if t.name == "get_diagnosticsources")
        props = tool.inputSchema["properties"]
        for required in ("name_filter", "group_filter", "filter", "limit", "offset"):
            assert required in props

    def test_descriptions_drop_preview_marker(self):
        """[PREVIEW] prefix is gone now that the tools call the public REST endpoint."""
        from lm_mcp.registry import TOOLS

        for name in ("get_diagnosticsources", "get_diagnosticsource"):
            tool = next(t for t in TOOLS if t.name == name)
            assert "[PREVIEW]" not in tool.description


@pytest.fixture
def enable_writes(monkeypatch):
    """Enable write operations for testing."""
    monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
    monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
    monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "true")

    from importlib import reload

    import lm_mcp.config

    reload(lm_mcp.config)


BASE_URL = "https://test.logicmonitor.com/santaba/rest"


def _mock_execute_prechecks(host_status="normal", build="39.300"):
    """Stub the shared pre-execution check endpoints for execute_diagnostic."""
    respx.get(f"{BASE_URL}/device/devices/1786").mock(
        return_value=httpx.Response(
            200, json={"id": 1786, "hostStatus": host_status, "preferredCollectorId": 5}
        )
    )
    respx.get(f"{BASE_URL}/setting/collector/collectors/5").mock(
        return_value=httpx.Response(200, json={"id": 5, "build": build})
    )
    respx.get(f"{BASE_URL}/setting/diagnosticsources/12").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 12,
                "name": "Top CPU",
                "appliesTo": "isLinux()",
                "groovyScript": "println 'top cpu'",
            },
        )
    )


class TestExecuteDiagnostic:
    """Tests for execute_diagnostic tool."""

    async def test_execute_diagnostic_requires_write_permission(self, client, monkeypatch):
        """execute_diagnostic is blocked when writes are disabled."""
        from lm_mcp.tools.diagnosticsources import execute_diagnostic

        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "false")
        from importlib import reload

        import lm_mcp.config

        reload(lm_mcp.config)

        result = await execute_diagnostic(client, host_id=1786, diagnostic_source_id=12)

        assert "Write operations are disabled" in result[0].text

    @respx.mock
    async def test_execute_diagnostic_posts_manual_trigger(self, client, enable_writes):
        """execute_diagnostic posts hostId/diagnosticId/triggerType to executemanually."""
        from lm_mcp.tools.diagnosticsources import execute_diagnostic

        _mock_execute_prechecks()
        route = respx.post(f"{BASE_URL}/setting/diagnosticsources/executemanually").mock(
            return_value=httpx.Response(
                200, json={"executionId": "abc-123", "executionStatus": "SCHEDULED"}
            )
        )

        result = await execute_diagnostic(
            client, host_id=1786, diagnostic_source_id=12, alert_id="DS99"
        )

        body = json.loads(route.calls[0].request.content)
        assert body == {
            "hostId": 1786,
            "diagnosticId": 12,
            "triggerType": "manual",
            "alertId": "DS99",
        }
        data = json.loads(result[0].text)
        assert data["success"] is True
        assert data["execution_response"]["executionId"] == "abc-123"
        assert "get_diagnostic_remediation_results" in data["next_step"]

    @respx.mock
    async def test_execute_diagnostic_blocks_dead_device(self, client, enable_writes):
        """execute_diagnostic refuses to run against a dead device."""
        from lm_mcp.tools.diagnosticsources import execute_diagnostic

        _mock_execute_prechecks(host_status=1)

        result = await execute_diagnostic(client, host_id=1786, diagnostic_source_id=12)

        assert "DEVICE_UNREACHABLE" in result[0].text or "dead" in result[0].text

    @respx.mock
    async def test_execute_diagnostic_blocks_old_collector(self, client, enable_writes):
        """execute_diagnostic refuses when collector build < 39.200."""
        from lm_mcp.tools.diagnosticsources import execute_diagnostic

        _mock_execute_prechecks(build="36.100")

        result = await execute_diagnostic(client, host_id=1786, diagnostic_source_id=12)

        assert "39.2" in result[0].text
        assert "below" in result[0].text.lower()


class TestCreateDiagnosticSource:
    """Tests for create_diagnosticsource tool."""

    async def test_create_requires_write_permission(self, client, monkeypatch):
        """create_diagnosticsource is blocked when writes are disabled."""
        from lm_mcp.tools.diagnosticsources import create_diagnosticsource

        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "false")
        from importlib import reload

        import lm_mcp.config

        reload(lm_mcp.config)

        result = await create_diagnosticsource(client, definition={"name": "X"})

        assert "Write operations are disabled" in result[0].text

    @respx.mock
    async def test_create_posts_definition(self, client, enable_writes):
        """create_diagnosticsource posts the normalized definition."""
        from lm_mcp.tools.diagnosticsources import create_diagnosticsource

        route = respx.post(f"{BASE_URL}/setting/diagnosticsources").mock(
            return_value=httpx.Response(
                200, json={"id": 77, "name": "DiskDiag", "displayName": "Disk Diagnostics"}
            )
        )

        definition = {
            "name": "DiskDiag",
            "displayName": "Disk Diagnostics",
            "appliesTo": "isLinux()",
            "groovyScript": "println 'df -h'",
        }
        result = await create_diagnosticsource(client, definition=definition)

        body = json.loads(route.calls[0].request.content)
        assert body["name"] == "DiskDiag"
        assert body["groovyScript"] == "println 'df -h'"
        data = json.loads(result[0].text)
        assert data["success"] is True
        assert data["diagnosticsource"]["id"] == 77

    @respx.mock
    async def test_create_strips_id(self, client, enable_writes):
        """create_diagnosticsource drops any id field from the definition."""
        from lm_mcp.tools.diagnosticsources import create_diagnosticsource

        route = respx.post(f"{BASE_URL}/setting/diagnosticsources").mock(
            return_value=httpx.Response(200, json={"id": 78, "name": "X"})
        )

        await create_diagnosticsource(client, definition={"id": 12, "name": "X"})

        body = json.loads(route.calls[0].request.content)
        assert "id" not in body

    @respx.mock
    async def test_create_handles_api_error(self, client, enable_writes):
        """create_diagnosticsource surfaces 400 errors."""
        from lm_mcp.tools.diagnosticsources import create_diagnosticsource

        respx.post(f"{BASE_URL}/setting/diagnosticsources").mock(
            return_value=httpx.Response(400, json={"errorMessage": "name required"})
        )

        result = await create_diagnosticsource(client, definition={"displayName": "X"})

        assert "error" in result[0].text.lower()


class TestUpdateDiagnosticSource:
    """Tests for update_diagnosticsource tool."""

    async def test_update_without_confirm_is_guarded(self, client, enable_writes):
        """update_diagnosticsource without confirm=True returns CONFIRMATION_REQUIRED."""
        from lm_mcp.tools.diagnosticsources import update_diagnosticsource

        result = await update_diagnosticsource(
            client, diagnosticsource_id=12, definition={"name": "X"}
        )

        text = result[0].text
        assert "confirm" in text.lower()
        assert "update_logicmodule" in text

    @respx.mock
    async def test_update_with_confirm_puts_definition(self, client, enable_writes):
        """update_diagnosticsource with confirm=True PUTs the full definition."""
        from lm_mcp.tools.diagnosticsources import update_diagnosticsource

        route = respx.put(f"{BASE_URL}/setting/diagnosticsources/12").mock(
            return_value=httpx.Response(200, json={"id": 12, "name": "Top CPU"})
        )

        definition = {"name": "Top CPU", "displayName": "Top CPU", "groovyScript": "x"}
        result = await update_diagnosticsource(
            client, diagnosticsource_id=12, definition=definition, confirm=True
        )

        body = json.loads(route.calls[0].request.content)
        assert body["name"] == "Top CPU"
        data = json.loads(result[0].text)
        assert data["success"] is True

    async def test_update_requires_write_permission(self, client, monkeypatch):
        """update_diagnosticsource is blocked when writes are disabled."""
        from lm_mcp.tools.diagnosticsources import update_diagnosticsource

        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "false")
        from importlib import reload

        import lm_mcp.config

        reload(lm_mcp.config)

        result = await update_diagnosticsource(
            client, diagnosticsource_id=12, definition={"name": "X"}, confirm=True
        )

        assert "Write operations are disabled" in result[0].text


class TestDeleteDiagnosticSource:
    """Tests for delete_diagnosticsource tool."""

    @respx.mock
    async def test_delete_success(self, client, enable_writes):
        """delete_diagnosticsource deletes and reports the source name."""
        from lm_mcp.tools.diagnosticsources import delete_diagnosticsource

        respx.get(f"{BASE_URL}/setting/diagnosticsources/12").mock(
            return_value=httpx.Response(200, json={"id": 12, "name": "Top CPU"})
        )
        respx.delete(f"{BASE_URL}/setting/diagnosticsources/12").mock(
            return_value=httpx.Response(200, json={})
        )

        result = await delete_diagnosticsource(client, diagnosticsource_id=12)

        data = json.loads(result[0].text)
        assert data["success"] is True
        assert "Top CPU" in data["message"]

    @respx.mock
    async def test_delete_not_found(self, client, enable_writes):
        """delete_diagnosticsource surfaces 404."""
        from lm_mcp.tools.diagnosticsources import delete_diagnosticsource

        respx.get(f"{BASE_URL}/setting/diagnosticsources/999").mock(
            return_value=httpx.Response(404, json={"errorMessage": "Not found"})
        )

        result = await delete_diagnosticsource(client, diagnosticsource_id=999)

        assert "error" in result[0].text.lower()
