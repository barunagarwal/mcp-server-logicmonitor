# Description: Tests for the HTTP /mcp JSON-RPC endpoint's request validation.
# Description: Covers schema-checked tools/call arguments, body shape, and generic error text.

import json
import logging
from unittest.mock import AsyncMock, patch

import pytest
import respx
from httpx import ASGITransport, AsyncClient, Response
from mcp.types import TextContent


@pytest.fixture
def _env(monkeypatch):
    """Configure a single-portal server with no inbound auth or tool filters."""
    monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
    monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
    for name in (
        "LM_HTTP_AUTH_TOKEN",
        "LM_ENABLED_TOOLS",
        "LM_DISABLED_TOOLS",
        "LM_MCP_CATEGORIES",
    ):
        monkeypatch.delenv(name, raising=False)


async def _post(body):
    """POST a raw JSON body to /mcp on a freshly built ASGI app."""
    from lm_mcp.transport.http import create_asgi_app

    transport = ASGITransport(app=create_asgi_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(
            "/mcp", content=json.dumps(body), headers={"Content-Type": "application/json"}
        )


def _call(name, arguments):
    """Build a tools/call JSON-RPC request."""
    return {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
        "id": 7,
    }


@pytest.mark.usefixtures("_env")
class TestToolsCallArgumentValidation:
    """R3.2: tools/call arguments are checked against the tool's schema before dispatch."""

    @pytest.mark.asyncio
    async def test_missing_required_argument_is_refused_before_dispatch(self):
        """A missing required property returns -32602 naming it; execute_tool never runs."""
        with patch("lm_mcp.server.execute_tool", new_callable=AsyncMock) as mock_exec:
            resp = await _post(_call("get_device", {}))

        mock_exec.assert_not_called()
        assert resp.status_code == 400
        data = resp.json()
        assert data["id"] == 7
        assert data["error"]["code"] == -32602
        assert "device_id" in data["error"]["message"]

    @pytest.mark.asyncio
    async def test_wrong_type_is_refused_before_dispatch(self):
        """A string where the schema wants an integer returns -32602 naming the property."""
        with patch("lm_mcp.server.execute_tool", new_callable=AsyncMock) as mock_exec:
            resp = await _post(_call("get_devices", {"limit": "ten"}))

        mock_exec.assert_not_called()
        assert resp.status_code == 400
        data = resp.json()
        assert data["error"]["code"] == -32602
        assert "limit" in data["error"]["message"]

    @pytest.mark.asyncio
    async def test_non_object_arguments_are_refused_before_dispatch(self):
        """arguments that are not an object fail the schema's type check."""
        with patch("lm_mcp.server.execute_tool", new_callable=AsyncMock) as mock_exec:
            resp = await _post(_call("get_devices", [5]))

        mock_exec.assert_not_called()
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == -32602

    @pytest.mark.asyncio
    async def test_valid_call_reaches_execute_tool_with_its_arguments(self):
        """A call that satisfies the schema is dispatched unchanged."""
        mock_result = [TextContent(type="text", text=json.dumps({"id": 42}))]
        with patch(
            "lm_mcp.server.execute_tool", new_callable=AsyncMock, return_value=mock_result
        ) as mock_exec:
            resp = await _post(_call("get_devices", {"limit": 5, "name_filter": "web"}))

        mock_exec.assert_called_once_with("get_devices", {"limit": 5, "name_filter": "web"})
        assert resp.status_code == 200
        assert resp.json()["result"] == {"id": 42}

    @pytest.mark.asyncio
    async def test_unknown_tool_is_left_to_execute_tool(self):
        """A name outside the manifest skips schema lookup; execute_tool owns the refusal."""
        resp = await _post(_call("no_such_tool", {}))

        assert resp.status_code == 200
        assert "Unknown tool: no_such_tool" in json.dumps(resp.json()["result"])

    @pytest.mark.asyncio
    @respx.mock
    async def test_valid_call_runs_through_the_real_client(self):
        """A valid get_device call reaches the portal through the real client and handler."""
        from lm_mcp.auth.bearer import BearerAuth
        from lm_mcp.client import LogicMonitorClient
        from lm_mcp.server import _set_client

        route = respx.get("https://test.logicmonitor.com/santaba/rest/device/devices/7").mock(
            return_value=Response(200, json={"id": 7, "displayName": "web-7"})
        )
        client = LogicMonitorClient(
            base_url="https://test.logicmonitor.com/santaba/rest", auth=BearerAuth("test-token")
        )
        _set_client(client)
        try:
            resp = await _post(_call("get_device", {"device_id": 7}))
        finally:
            _set_client(None)
            await client.close()

        assert route.called
        assert resp.status_code == 200
        assert "web-7" in json.dumps(resp.json()["result"])


@pytest.mark.usefixtures("_env")
class TestRequestShape:
    """R3.2: a body that is not a JSON-RPC request object is a client error, not a 500."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("body", [[_call("get_devices", {})], "tools/list", 5, None])
    async def test_non_object_body_is_a_400_jsonrpc_error(self, body):
        """An array (batch), string, number or null body returns -32600 with HTTP 400."""
        resp = await _post(body)

        assert resp.status_code == 400
        data = resp.json()
        assert data["jsonrpc"] == "2.0"
        assert data["error"]["code"] == -32600
        assert data["id"] is None

    @pytest.mark.asyncio
    async def test_non_object_params_is_a_400_jsonrpc_error(self):
        """params that are not an object return -32602 with HTTP 400."""
        resp = await _post({"jsonrpc": "2.0", "method": "tools/call", "params": [1], "id": 3})

        assert resp.status_code == 400
        data = resp.json()
        assert data["error"]["code"] == -32602
        assert data["id"] == 3


@pytest.mark.usefixtures("_env")
class TestInternalErrorText:
    """R3.2: dispatch failures return a fixed message and log the traceback."""

    @pytest.mark.asyncio
    async def test_unexpected_exception_returns_generic_message(self, caplog):
        """An exception inside dispatch is logged with its traceback, never echoed."""
        with (
            caplog.at_level(logging.ERROR, logger="lm_mcp.transport.http"),
            patch(
                "lm_mcp.server.execute_tool",
                new_callable=AsyncMock,
                side_effect=RuntimeError("pool dsn=postgres://admin:hunter2@db"),
            ),
        ):
            resp = await _post(_call("get_devices", {}))

        assert resp.status_code == 500
        data = resp.json()
        assert data["error"]["code"] == -32603
        assert data["error"]["message"] == "Internal error"
        assert "hunter2" not in resp.text
        records = [r for r in caplog.records if r.name == "lm_mcp.transport.http"]
        assert records and records[-1].exc_info is not None
        assert "hunter2" in caplog.text

    @pytest.mark.asyncio
    async def test_value_error_returns_generic_message(self, caplog):
        """A ValueError inside dispatch is -32602 with a fixed message and a logged traceback."""
        with (
            caplog.at_level(logging.ERROR, logger="lm_mcp.transport.http"),
            patch(
                "lm_mcp.server.execute_tool",
                new_callable=AsyncMock,
                side_effect=ValueError("internal state id=91f2"),
            ),
        ):
            resp = await _post(_call("get_devices", {}))

        assert resp.status_code == 400
        data = resp.json()
        assert data["error"]["code"] == -32602
        assert data["error"]["message"] == "Invalid params"
        assert "91f2" not in resp.text
        records = [r for r in caplog.records if r.name == "lm_mcp.transport.http"]
        assert records and records[-1].exc_info is not None
