# Description: Tests for the shared execute_tool middleware function.
# Description: Validates tool filtering, write audit, and session recording.

import json
import logging
import tomllib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx
from mcp.types import CallToolRequest, CallToolRequestParams, CallToolResult, TextContent

from lm_mcp.tools import ErrorContent, is_error_result


class TestExecuteToolMiddleware:
    """Tests for execute_tool applying the full middleware chain."""

    @pytest.fixture
    def mock_handler(self):
        """Create a mock tool handler returning TextContent."""
        return AsyncMock(return_value=[TextContent(type="text", text=json.dumps({"id": 1}))])

    @pytest.fixture
    def mock_client(self):
        """Create a mock LogicMonitor client."""
        return MagicMock()

    @pytest.mark.asyncio
    async def test_calls_handler_with_client(self, monkeypatch, mock_handler, mock_client):
        """execute_tool passes client and arguments to the handler."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")

        with (
            patch("lm_mcp.server.get_tool_handler", return_value=mock_handler),
            patch("lm_mcp.server.get_client", return_value=mock_client),
        ):
            from lm_mcp.server import execute_tool

            result = await execute_tool("get_devices", {"limit": 10})

        mock_handler.assert_called_once_with(mock_client, limit=10)
        assert len(result) == 1
        assert json.loads(result[0].text) == {"id": 1}

    @pytest.mark.asyncio
    async def test_session_tool_called_without_client(self, monkeypatch, mock_handler):
        """execute_tool calls session tools without the LM client."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")

        with patch("lm_mcp.server.get_tool_handler", return_value=mock_handler):
            from lm_mcp.server import execute_tool

            result = await execute_tool("get_session_context", {})

        mock_handler.assert_called_once_with()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_rejects_disabled_tool(self, monkeypatch):
        """execute_tool rejects tools matching disabled_tools pattern."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_DISABLED_TOOLS", "delete_*")

        from lm_mcp.server import execute_tool

        result = await execute_tool("delete_device", {"device_id": 1})

        assert "disabled" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_rejects_non_enabled_tool(self, monkeypatch):
        """execute_tool rejects tools not in enabled_tools list."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_ENABLED_TOOLS", "get_devices,get_alerts")

        from lm_mcp.server import execute_tool

        result = await execute_tool("delete_device", {"device_id": 1})

        assert "not enabled" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_allows_enabled_tool(self, monkeypatch, mock_handler, mock_client):
        """execute_tool allows tools in the enabled_tools list."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_ENABLED_TOOLS", "get_devices,get_alerts")

        with (
            patch("lm_mcp.server.get_tool_handler", return_value=mock_handler),
            patch("lm_mcp.server.get_client", return_value=mock_client),
        ):
            from lm_mcp.server import execute_tool

            result = await execute_tool("get_devices", {"limit": 5})

        mock_handler.assert_called_once()
        assert json.loads(result[0].text) == {"id": 1}

    @pytest.mark.asyncio
    async def test_logs_write_operation_on_success(self, monkeypatch, mock_handler, mock_client):
        """execute_tool logs successful write operations."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")

        with (
            patch("lm_mcp.server.get_tool_handler", return_value=mock_handler),
            patch("lm_mcp.server.get_client", return_value=mock_client),
            patch("lm_mcp.server.log_write_operation") as mock_log,
        ):
            from lm_mcp.server import execute_tool

            await execute_tool("create_device", {"name": "test"})

        mock_log.assert_called_once_with("create_device", {"name": "test"}, success=True)

    @pytest.mark.asyncio
    async def test_records_session_when_enabled(self, monkeypatch, mock_handler, mock_client):
        """execute_tool records results in session when session is enabled."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_SESSION_ENABLED", "true")

        mock_session = MagicMock()

        with (
            patch("lm_mcp.server.get_tool_handler", return_value=mock_handler),
            patch("lm_mcp.server.get_client", return_value=mock_client),
            patch("lm_mcp.server.get_session", return_value=mock_session),
        ):
            from lm_mcp.server import execute_tool

            await execute_tool("get_devices", {"limit": 10})

        mock_session.record_result.assert_called_once_with(
            "get_devices", {"limit": 10}, {"id": 1}, success=True
        )

    @pytest.mark.asyncio
    async def test_skips_session_for_session_tools(self, monkeypatch, mock_handler):
        """execute_tool does not record session tools in session history."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_SESSION_ENABLED", "true")

        mock_session = MagicMock()

        with (
            patch("lm_mcp.server.get_tool_handler", return_value=mock_handler),
            patch("lm_mcp.server.get_session", return_value=mock_session),
        ):
            from lm_mcp.server import execute_tool

            await execute_tool("get_session_context", {})

        mock_session.record_result.assert_not_called()

    @pytest.mark.asyncio
    async def test_handler_value_error_returns_error_text(self, monkeypatch, mock_client):
        """execute_tool catches ValueError and returns error message."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")

        failing_handler = AsyncMock(side_effect=ValueError("bad input"))

        with (
            patch("lm_mcp.server.get_tool_handler", return_value=failing_handler),
            patch("lm_mcp.server.get_client", return_value=mock_client),
        ):
            from lm_mcp.server import execute_tool

            result = await execute_tool("get_devices", {"limit": -1})

        assert "bad input" in result[0].text

    @pytest.mark.parametrize(
        ("exc", "arguments"),
        [
            (TypeError("get_devices() got an unexpected keyword argument 'foo'"), {"foo": 1}),
            (ValueError("bad input"), {"limit": -1}),
        ],
    )
    async def test_handler_exception_is_logged_with_traceback(
        self, monkeypatch, mock_client, caplog, exc, arguments
    ):
        """A handler that raises leaves one record with exc_info and an ErrorContent result."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")

        failing_handler = AsyncMock(side_effect=exc)

        with (
            patch("lm_mcp.server.get_tool_handler", return_value=failing_handler),
            patch("lm_mcp.server.get_client", return_value=mock_client),
            caplog.at_level(logging.ERROR, logger="lm_mcp.server"),
        ):
            from lm_mcp.server import execute_tool

            result = await execute_tool("get_devices", arguments)

        assert is_error_result(result)
        assert str(exc) in result[0].text
        records = [r for r in caplog.records if r.name == "lm_mcp.server"]
        assert len(records) == 1
        assert records[0].exc_info is not None
        assert records[0].exc_info[0] is type(exc)
        assert "get_devices" in records[0].getMessage()


class TestCallToolDelegatesToExecuteTool:
    """Tests that the MCP call_tool handler delegates to execute_tool."""

    @pytest.mark.asyncio
    async def test_call_tool_uses_execute_tool(self, monkeypatch):
        """The MCP call_tool handler delegates to execute_tool."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")

        expected = [TextContent(type="text", text="delegated")]

        with patch("lm_mcp.server.execute_tool", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = expected
            from lm_mcp.server import call_tool

            result = await call_tool("get_devices", {"limit": 10})

        mock_exec.assert_called_once_with("get_devices", {"limit": 10})
        assert result == expected


class TestPortalToolGating:
    """Portal tools are dispatchable only in multi-portal mode."""

    @pytest.mark.asyncio
    async def test_execute_tool_rejects_portal_tools_in_single_portal_mode(self, monkeypatch):
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.delenv("LM_MULTI_PORTAL", raising=False)

        from lm_mcp.server import execute_tool

        for name, args in (("use_portal", {"customer": "x"}), ("list_portals", {})):
            result = await execute_tool(name, args)
            assert result[0].text.startswith("Error:")
            assert "multi-portal" in result[0].text


class TestMultiPortalDispatch:
    """execute_tool behavior in multi-portal mode before and around portal selection."""

    def _multi_env(self, monkeypatch, tmp_path):
        p = tmp_path / "portals.json"
        p.write_text(json.dumps({"acme": {"portal": "acme.example.com", "bearer_token": "t"}}))
        monkeypatch.setenv("LM_MULTI_PORTAL", "true")
        monkeypatch.setenv("LM_PORTALS_FILE", str(p))
        monkeypatch.delenv("LM_PORTAL", raising=False)
        monkeypatch.delenv("LM_BEARER_TOKEN", raising=False)

    @pytest.mark.asyncio
    async def test_execute_tool_allows_portal_tools_despite_categories(
        self, monkeypatch, tmp_path, reset_portals
    ):
        self._multi_env(monkeypatch, tmp_path)
        monkeypatch.setenv("LM_MCP_CATEGORIES", "read")

        from lm_mcp.server import execute_tool

        result = await execute_tool("current_portal", {})
        data = json.loads(result[0].text)
        assert "active" in data

    @pytest.mark.asyncio
    async def test_search_tools_works_before_use_portal(self, monkeypatch, tmp_path, reset_portals):
        self._multi_env(monkeypatch, tmp_path)

        from lm_mcp.server import execute_tool

        result = await execute_tool("search_tools", {"query": "device"})
        text = result[0].text
        assert "No portal selected" not in text
        assert "device" in text

    @pytest.mark.asyncio
    async def test_get_reference_works_before_use_portal(
        self, monkeypatch, tmp_path, reset_portals
    ):
        self._multi_env(monkeypatch, tmp_path)

        from lm_mcp.server import execute_tool

        result = await execute_tool("get_reference", {"list": True})
        assert "No portal selected" not in result[0].text

    @pytest.mark.asyncio
    async def test_get_workflow_works_before_use_portal(self, monkeypatch, tmp_path, reset_portals):
        self._multi_env(monkeypatch, tmp_path)

        from lm_mcp.server import execute_tool

        result = await execute_tool("get_workflow", {"list": True})
        assert "No portal selected" not in result[0].text

    @pytest.mark.asyncio
    async def test_terraform_tools_unsupported_in_multi_portal(
        self, monkeypatch, tmp_path, reset_portals
    ):
        self._multi_env(monkeypatch, tmp_path)

        from lm_mcp.server import _set_tf_runner, execute_tool

        _set_tf_runner(MagicMock())
        try:
            result = await execute_tool("terraform_init", {})
            assert "not supported in multi-portal mode" in result[0].text
        finally:
            _set_tf_runner(None)

    @pytest.mark.asyncio
    async def test_use_portal_recorded_in_session_history(
        self, monkeypatch, tmp_path, reset_portals
    ):
        self._multi_env(monkeypatch, tmp_path)

        from lm_mcp.server import execute_tool
        from lm_mcp.session import get_session, reset_session

        reset_session()
        try:
            await execute_tool("use_portal", {"customer": "acme"})
            history = get_session().history
            assert history and history[-1].tool_name == "use_portal"
        finally:
            reset_session()


DEVICE_URL = "https://test.logicmonitor.com/santaba/rest/device/devices/7"

# Field types copied from a live GET /device/devices read (2026-10-20); the error
# envelope copies the live 404 body shape with the 403 status.
DEVICE_7 = {
    "id": 7,
    "name": "10.0.0.7",
    "displayName": "web-07",
    "deviceType": 0,
    "currentCollectorId": 3,
    "hostGroupIds": "2,14",
    "hostStatus": "normal",
}
FORBIDDEN = {"errorMessage": "Permission denied", "errorCode": 1403, "errorDetail": None}


@pytest.fixture
def write_portal(monkeypatch, reset_portals):
    """Single-portal env with writes on and a real client bound the way stdio binds it."""
    monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
    monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
    monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "true")
    monkeypatch.delenv("LM_MULTI_PORTAL", raising=False)
    monkeypatch.delenv("LM_SESSION_ENABLED", raising=False)

    from lm_mcp.auth import create_auth_provider
    from lm_mcp.client import LogicMonitorClient
    from lm_mcp.config import get_config
    from lm_mcp.server import _set_client

    config = get_config()
    _set_client(
        LogicMonitorClient(
            base_url=config.base_url,
            auth=create_auth_provider(config),
            timeout=config.timeout,
            api_version=config.api_version,
            max_retries=config.max_retries,
            ingest_url=config.ingest_url,
        )
    )


def _audit_lines(caplog) -> list[tuple[int, str]]:
    return [(r.levelno, r.getMessage()) for r in caplog.records if r.name == "lm_mcp.audit"]


class TestWriteOutcomeFromResult:
    """Audit, session and isError derive from the real handler's result (R1.4)."""

    @respx.mock
    async def test_forbidden_delete_audits_failure(self, write_portal, caplog):
        respx.get(DEVICE_URL).mock(return_value=httpx.Response(200, json=DEVICE_7))
        respx.delete(DEVICE_URL).mock(return_value=httpx.Response(403, json=FORBIDDEN))
        from lm_mcp.server import execute_tool

        with caplog.at_level(logging.INFO, logger="lm_mcp.audit"):
            result = await execute_tool("delete_device", {"device_id": 7})

        assert isinstance(result[0], ErrorContent)
        assert result[0].text.startswith("Error: Permission denied")
        assert _audit_lines(caplog) == [
            (logging.WARNING, "Write operation failed: delete_device args={'device_id': 7}")
        ]

    @respx.mock
    async def test_write_disabled_refusal_audits_failure(self, write_portal, monkeypatch, caplog):
        monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "false")
        from lm_mcp.config import reset_config
        from lm_mcp.server import execute_tool

        reset_config()
        with caplog.at_level(logging.INFO, logger="lm_mcp.audit"):
            result = await execute_tool("delete_device", {"device_id": 7})

        assert isinstance(result[0], ErrorContent)
        assert result[0].text.startswith("Error: Write operations are disabled")
        assert not respx.calls
        assert _audit_lines(caplog) == [
            (logging.WARNING, "Write operation failed: delete_device args={'device_id': 7}")
        ]

    @respx.mock
    async def test_collector_debug_refusal_audits_failure(self, write_portal, caplog):
        """A collector_debug request the tool refuses is a failed write, before any call."""
        from lm_mcp.server import execute_tool

        with caplog.at_level(logging.INFO, logger="lm_mcp.audit"):
            result = await execute_tool(
                "collector_debug",
                {"command": "ping", "device_id": 7, "args": {"host": "169.254.169.254"}},
            )

        assert isinstance(result[0], ErrorContent)
        assert not respx.calls
        lines = _audit_lines(caplog)
        assert [level for level, _ in lines] == [logging.WARNING]
        assert lines[0][1].startswith("Write operation failed: collector_debug")

    @respx.mock
    async def test_collector_debug_portal_refusal_audits_failure(self, write_portal, caplog):
        """A debug POST the portal refuses keeps its JSON body but is audited as a failure."""
        respx.post("https://test.logicmonitor.com/santaba/rest/debug").mock(
            return_value=httpx.Response(403, json=FORBIDDEN)
        )
        from lm_mcp.server import execute_tool

        with caplog.at_level(logging.INFO, logger="lm_mcp.audit"):
            result = await execute_tool("collector_debug", {"command": "uptime", "collector_id": 9})

        assert isinstance(result[0], ErrorContent)
        assert result[0].text.startswith("Error: uptime: refused: ")
        assert json.loads(result[0].text.split("\nDetails: ", 1)[1])["status"] == "refused"
        lines = _audit_lines(caplog)
        assert [level for level, _ in lines] == [logging.WARNING]
        assert lines[0][1].startswith("Write operation failed: collector_debug")

    @respx.mock
    async def test_collector_debug_answer_audits_success(self, write_portal, caplog, monkeypatch):
        from lm_mcp.tools import collector_debug as cd

        monkeypatch.setattr(cd, "POLL_SECONDS", 0.01)
        respx.post("https://test.logicmonitor.com/santaba/rest/debug").mock(
            return_value=httpx.Response(200, json={"sessionId": "s1"})
        )
        respx.get("https://test.logicmonitor.com/santaba/rest/debug/s1").mock(
            return_value=httpx.Response(200, json={"output": "uptime=1h"})
        )
        from lm_mcp.server import execute_tool

        with caplog.at_level(logging.INFO, logger="lm_mcp.audit"):
            result = await execute_tool("collector_debug", {"command": "uptime", "collector_id": 9})

        assert not is_error_result(result)
        assert json.loads(result[0].text)["status"] == "answered"
        lines = _audit_lines(caplog)
        assert [level for level, _ in lines] == [logging.INFO]
        assert lines[0][1].startswith("Write operation: collector_debug")

    @respx.mock
    async def test_successful_delete_audits_success(self, write_portal, caplog):
        respx.get(DEVICE_URL).mock(return_value=httpx.Response(200, json=DEVICE_7))
        respx.delete(DEVICE_URL).mock(return_value=httpx.Response(200, json={}))
        from lm_mcp.server import execute_tool

        with caplog.at_level(logging.INFO, logger="lm_mcp.audit"):
            result = await execute_tool("delete_device", {"device_id": 7})

        assert not is_error_result(result)
        assert json.loads(result[0].text)["success"] is True
        assert _audit_lines(caplog) == [
            (logging.INFO, "Write operation: delete_device args={'device_id': 7}")
        ]

    async def test_write_raising_before_handler_audits_failure(self, write_portal, caplog):
        """No client bound: get_client raises and the except path audits the write as failed."""
        from lm_mcp.server import _set_client, execute_tool

        _set_client(None)
        with caplog.at_level(logging.INFO, logger="lm_mcp.audit"):
            result = await execute_tool("delete_device", {"device_id": 7})

        assert result[0].text == "Error executing delete_device: Client not initialized"
        assert _audit_lines(caplog) == [
            (logging.WARNING, "Write operation failed: delete_device args={'device_id': 7}")
        ]

    async def test_write_value_error_audits_failure(self, write_portal, caplog):
        """An unknown write-prefixed tool raises ValueError in lookup; it audits as failed."""
        from lm_mcp.server import execute_tool

        with caplog.at_level(logging.INFO, logger="lm_mcp.audit"):
            result = await execute_tool("delete_no_such_resource", {"id": 7})

        assert is_error_result(result)
        assert result[0].text.startswith("Error: ")
        assert _audit_lines(caplog) == [
            (logging.WARNING, "Write operation failed: delete_no_such_resource args={'id': 7}")
        ]

    @respx.mock
    async def test_forbidden_delete_recorded_as_failure_in_session(self, write_portal, monkeypatch):
        monkeypatch.setenv("LM_SESSION_ENABLED", "true")
        respx.get(DEVICE_URL).mock(return_value=httpx.Response(200, json=DEVICE_7))
        respx.delete(DEVICE_URL).mock(return_value=httpx.Response(403, json=FORBIDDEN))
        from lm_mcp.config import reset_config
        from lm_mcp.server import execute_tool
        from lm_mcp.session import get_session, reset_session

        reset_config()
        reset_session()
        try:
            await execute_tool("delete_device", {"device_id": 7})
            entry = get_session().history[-1]
            assert entry.tool_name == "delete_device"
            assert entry.success is False
        finally:
            reset_session()

    @pytest.mark.parametrize(
        ("content", "expected"),
        [
            (TextContent(type="text", text="plain text, not JSON"), True),
            (ErrorContent(type="text", text='{"error": true, "message": "x"}'), False),
        ],
        ids=["plain-text-success", "json-text-error"],
    )
    async def test_session_outcome_follows_result_type_not_json(
        self, write_portal, monkeypatch, content, expected
    ):
        """Session success comes from the result type, whether or not the text parses."""
        monkeypatch.setenv("LM_SESSION_ENABLED", "true")
        from lm_mcp.config import reset_config
        from lm_mcp.server import execute_tool
        from lm_mcp.session import get_session, reset_session

        reset_config()
        reset_session()
        try:
            with patch(
                "lm_mcp.server.get_tool_handler", return_value=AsyncMock(return_value=[content])
            ):
                await execute_tool("get_devices", {})
            assert get_session().history[-1].success is expected
        finally:
            reset_session()

    @respx.mock
    async def test_call_tool_marks_failure_is_error(self, write_portal):
        respx.get(DEVICE_URL).mock(return_value=httpx.Response(200, json=DEVICE_7))
        respx.delete(DEVICE_URL).mock(return_value=httpx.Response(403, json=FORBIDDEN))
        from lm_mcp.server import call_tool

        result = await call_tool("delete_device", {"device_id": 7})

        assert isinstance(result, CallToolResult)
        assert result.isError is True
        assert result.content[0].text.startswith("Error: Permission denied")

    @respx.mock
    async def test_call_tool_success_is_plain_content(self, write_portal):
        respx.get(DEVICE_URL).mock(return_value=httpx.Response(200, json=DEVICE_7))
        respx.delete(DEVICE_URL).mock(return_value=httpx.Response(200, json={}))
        from lm_mcp.server import call_tool

        result = await call_tool("delete_device", {"device_id": 7})

        assert isinstance(result, list)
        assert json.loads(result[0].text)["success"] is True

    @respx.mock
    async def test_sdk_request_handler_reports_is_error(self, write_portal):
        """The registered MCP CallToolRequest handler carries isError to the wire result."""
        respx.get(DEVICE_URL).mock(return_value=httpx.Response(200, json=DEVICE_7))
        respx.delete(DEVICE_URL).mock(return_value=httpx.Response(403, json=FORBIDDEN))
        from lm_mcp.server import server

        handler = server.request_handlers[CallToolRequest]
        response = await handler(
            CallToolRequest(
                method="tools/call",
                params=CallToolRequestParams(name="delete_device", arguments={"device_id": 7}),
            )
        )

        wire = response.model_dump(by_alias=True, exclude_none=True)
        assert wire["isError"] is True
        assert wire["content"][0]["text"].startswith("Error: Permission denied")

    def test_mcp_floor_admits_only_call_tool_result_passthrough(self):
        """The mcp requirement excludes every release that cannot pass a CallToolResult.

        call_tool returns CallToolResult(isError=True) for an error. mcp 1.19.0 is the first
        lowlevel server that passes one through; 1.18.0 and earlier list() it, fail
        validation, and send a pydantic message in place of the tool's error text.
        """
        from packaging.requirements import Requirement
        from packaging.version import Version

        pyproject = Path(__file__).parent.parent / "pyproject.toml"
        dependencies = tomllib.loads(pyproject.read_text())["project"]["dependencies"]
        mcp = next(r for r in map(Requirement, dependencies) if r.name == "mcp")

        assert Version("1.18.0") not in mcp.specifier
        assert Version("1.19.0") in mcp.specifier
