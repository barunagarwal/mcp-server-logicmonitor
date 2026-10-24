# Description: Tests for the transport abstraction module.
# Description: Validates transport runner selection and configuration.

import logging
import sys
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from lm_mcp.transport import get_transport_runner, run_http, run_stdio
from tests.live_uvicorn import free_port, live_uvicorn


class TestTransportModule:
    """Tests for transport module imports and exports."""

    def test_run_stdio_is_callable(self):
        """run_stdio function is importable and callable."""
        assert callable(run_stdio)

    def test_run_http_is_callable(self):
        """run_http function is importable and callable."""
        assert callable(run_http)

    def test_get_transport_runner_is_callable(self):
        """get_transport_runner function is importable and callable."""
        assert callable(get_transport_runner)


class TestGetTransportRunner:
    """Tests for transport runner selection."""

    def test_stdio_transport_returns_run_stdio(self, monkeypatch):
        """stdio transport returns run_stdio function."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_TRANSPORT", "stdio")

        from lm_mcp.config import LMConfig

        config = LMConfig()
        runner = get_transport_runner(config)

        assert runner is run_stdio

    def test_http_transport_returns_run_http(self, monkeypatch):
        """http transport returns run_http function."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_TRANSPORT", "http")
        monkeypatch.setenv("LM_HTTP_HOST", "127.0.0.1")

        from lm_mcp.config import LMConfig

        config = LMConfig()
        runner = get_transport_runner(config)

        assert runner is run_http

    def test_invalid_transport_raises_error(self, monkeypatch):
        """Invalid transport type raises ValueError."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_TRANSPORT", "invalid")

        from lm_mcp.config import LMConfig

        # LMConfig validation should catch invalid transport
        with pytest.raises(ValidationError):
            LMConfig()

    def test_default_transport_is_stdio(self, monkeypatch):
        """Default transport is stdio when not specified."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.delenv("LM_TRANSPORT", raising=False)

        from lm_mcp.config import LMConfig

        config = LMConfig()

        assert config.transport == "stdio"


class TestTransportConfig:
    """Tests for transport-related configuration."""

    def test_http_host_default(self, monkeypatch):
        """Default HTTP host is 0.0.0.0."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")

        from lm_mcp.config import LMConfig

        config = LMConfig()

        assert config.http_host == "0.0.0.0"

    def test_http_host_from_env(self, monkeypatch):
        """HTTP host can be set from environment."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_HTTP_HOST", "127.0.0.1")

        from lm_mcp.config import LMConfig

        config = LMConfig()

        assert config.http_host == "127.0.0.1"

    def test_http_port_default(self, monkeypatch):
        """Default HTTP port is 8080."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")

        from lm_mcp.config import LMConfig

        config = LMConfig()

        assert config.http_port == 8080

    def test_http_port_from_env(self, monkeypatch):
        """HTTP port can be set from environment."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_HTTP_PORT", "9000")

        from lm_mcp.config import LMConfig

        config = LMConfig()

        assert config.http_port == 9000

    def test_http_port_validation_min(self, monkeypatch):
        """HTTP port below minimum raises error."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_HTTP_PORT", "0")

        from lm_mcp.config import LMConfig

        with pytest.raises(ValueError):
            LMConfig()

    def test_http_port_validation_max(self, monkeypatch):
        """HTTP port above maximum raises error."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_HTTP_PORT", "70000")

        from lm_mcp.config import LMConfig

        with pytest.raises(ValueError):
            LMConfig()

    def test_cors_origins_default(self, monkeypatch):
        """Default CORS origins is wildcard."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")

        from lm_mcp.config import LMConfig

        config = LMConfig()

        assert config.cors_origins == ""

    def test_cors_origins_from_env(self, monkeypatch):
        """CORS origins can be set from environment."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_CORS_ORIGINS", "https://example.com,https://other.com")

        from lm_mcp.config import LMConfig

        config = LMConfig()

        assert config.cors_origins == "https://example.com,https://other.com"

    def test_cors_origins_list_property(self, monkeypatch):
        """cors_origins_list property parses comma-separated origins."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_CORS_ORIGINS", "https://a.com,https://b.com")

        from lm_mcp.config import LMConfig

        config = LMConfig()
        origins = config.cors_origins_list

        assert origins == ["https://a.com", "https://b.com"]

    def test_cors_origins_list_wildcard(self, monkeypatch):
        """cors_origins_list returns wildcard as single-item list."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_CORS_ORIGINS", "*")

        from lm_mcp.config import LMConfig

        config = LMConfig()
        origins = config.cors_origins_list

        assert origins == ["*"]


def _fake_stdio_server():
    """Stand-in for mcp.stdio_server that yields placeholder streams."""

    @asynccontextmanager
    async def _cm():
        yield (None, None)

    return _cm


class TestRunStdioStartup:
    """R1.2: run_stdio setup reaches the serve loop in every optional-integration branch.

    The serve loop and the stdio streams are faked; everything before them runs
    for real, including client construction and the optional-integration probes.
    """

    @pytest.fixture(autouse=True)
    def _isolate(self, monkeypatch, reset_portals):
        from lm_mcp import server as server_module
        from lm_mcp.hf_config import reset_hf_config
        from lm_mcp.terraform_config import reset_terraform_config

        for var in (
            "LM_MULTI_PORTAL",
            "LM_PORTALS_FILE",
            "LM_VAULT_FILE",
            "LM_AGE_KEY",
            "LM_MAX_RETRIES",
            "AWX_URL",
            "AWX_TOKEN",
            "WATSONX_API_KEY",
            "WATSONX_URL",
            "WATSONX_PROJECT_ID",
            "TF_WORKSPACE_DIR",
        ):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        reset_hf_config()
        reset_terraform_config()

        self.serve = AsyncMock()
        monkeypatch.setattr(server_module.server, "run", self.serve)
        monkeypatch.setattr("mcp.stdio_server", _fake_stdio_server())
        monkeypatch.setattr("lm_mcp.hf_config.get_hf_config", lambda: None)
        yield
        reset_hf_config()
        reset_terraform_config()

    async def test_multi_portal_with_terraform_reaches_serve_loop(
        self, monkeypatch, tmp_path, caplog
    ):
        """Multi-portal plus TF_WORKSPACE_DIR logs the Terraform-disabled warning and serves."""
        portals_file = tmp_path / "portals.json"
        portals_file.write_text('{"acme": {"portal": "acme.example.com", "bearer_token": "t"}}')
        monkeypatch.setenv("LM_MULTI_PORTAL", "true")
        monkeypatch.setenv("LM_PORTALS_FILE", str(portals_file))
        monkeypatch.delenv("LM_PORTAL")
        monkeypatch.delenv("LM_BEARER_TOKEN")
        monkeypatch.setenv("TF_WORKSPACE_DIR", str(tmp_path))

        with caplog.at_level(logging.WARNING, logger="lm_mcp.transport"):
            await run_stdio()

        self.serve.assert_awaited_once()
        assert any(
            "Terraform tools are disabled in multi-portal mode" in r.getMessage()
            for r in caplog.records
        )

    async def test_watsonx_import_error_logs_and_reaches_serve_loop(self, monkeypatch, caplog):
        """A configured watsonx without its extra logs a warning and still serves."""
        monkeypatch.setenv("WATSONX_API_KEY", "test-key")
        monkeypatch.setenv("WATSONX_URL", "https://us-south.ml.cloud.ibm.com")
        monkeypatch.setenv("WATSONX_PROJECT_ID", "test-project")
        monkeypatch.setitem(sys.modules, "lm_mcp.client.watsonx", None)

        with caplog.at_level(logging.WARNING, logger="lm_mcp.transport"):
            await run_stdio()

        self.serve.assert_awaited_once()
        assert any("ibm-watsonx-ai not installed" in r.getMessage() for r in caplog.records)

    async def test_huggingface_import_error_logs_and_reaches_serve_loop(self, monkeypatch, caplog):
        """A HuggingFace config without torch/transformers logs a warning and still serves."""
        from lm_mcp.hf_config import HuggingFaceConfig

        monkeypatch.setattr("lm_mcp.hf_config.get_hf_config", lambda: HuggingFaceConfig())
        monkeypatch.setitem(sys.modules, "lm_mcp.client.huggingface", None)

        with caplog.at_level(logging.WARNING, logger="lm_mcp.transport"):
            await run_stdio()

        self.serve.assert_awaited_once()
        assert any("HuggingFace fallback disabled" in r.getMessage() for r in caplog.records)

    async def test_watsonx_construction_failure_logs_and_reaches_serve_loop(
        self, monkeypatch, caplog
    ):
        """R4.5: a watsonx SDK constructor failure is logged, leaves watsonx unset, and serves.

        The SDK's APIClient fetches an IAM token on construction, so a bad key or
        an unreachable IAM endpoint fails there with WMLClientError.
        """
        from unittest.mock import MagicMock

        from ibm_watsonx_ai.wml_client_error import WMLClientError

        from lm_mcp import server as server_module

        monkeypatch.setenv("WATSONX_API_KEY", "test-key")
        monkeypatch.setenv("WATSONX_PROJECT_ID", "test-project")
        monkeypatch.setattr("ibm_watsonx_ai.Credentials", MagicMock())
        monkeypatch.setattr(
            "ibm_watsonx_ai.APIClient",
            MagicMock(side_effect=WMLClientError("Error getting IAM Token.")),
        )
        serving_watsonx = []
        self.serve.side_effect = lambda *args: serving_watsonx.append(server_module._watsonx_client)

        with caplog.at_level(logging.WARNING, logger="lm_mcp.transport"):
            await run_stdio()

        self.serve.assert_awaited_once()
        assert serving_watsonx == [None]
        (record,) = [r for r in caplog.records if "watsonx" in r.getMessage()]
        assert record.levelno == logging.ERROR
        assert record.exc_info is not None
        assert "Error getting IAM Token." in str(record.exc_info[1])

    async def test_single_portal_client_uses_configured_max_retries(self, monkeypatch):
        """R1.6, R3.5: the client gets LM_MAX_RETRIES and LM_RETRY_AFTER_CAP_SECONDS."""
        from lm_mcp import server as server_module

        monkeypatch.setenv("LM_MAX_RETRIES", "7")
        monkeypatch.setenv("LM_RETRY_AFTER_CAP_SECONDS", "45")
        # Shutdown nulls the global client, so read it while the loop is serving.
        serving_clients = []
        self.serve.side_effect = lambda *args: serving_clients.append(server_module._client)

        await run_stdio()

        self.serve.assert_awaited_once()
        assert serving_clients[0] is not None
        assert serving_clients[0].max_retries == 7
        assert serving_clients[0].retry_after_cap == 45


async def _stdio_tool_names(serve: AsyncMock) -> list[str]:
    """Run stdio setup and return the tool names list_tools gives while it serves."""
    from lm_mcp.server import list_tools

    names: list[str] = []

    async def capture(*_args):
        names.extend(t.name for t in await list_tools())

    serve.side_effect = capture
    await run_stdio()
    return names


async def _http_tool_names(monkeypatch) -> list[str]:
    """Start the HTTP server on loopback and return the tool names tools/list gives."""
    import httpx

    from lm_mcp.transport.http import create_http_server

    live = live_uvicorn(monkeypatch)
    async with (
        live(create_http_server()) as port,
        httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client,
    ):
        resp = await client.post("/mcp", json={"jsonrpc": "2.0", "method": "tools/list", "id": 1})
    return [tool["name"] for tool in resp.json()["result"]]


def _clear_backend_globals() -> None:
    from lm_mcp.server import _set_awx_client, _set_tf_runner, _set_watsonx_client

    _set_awx_client(None)
    _set_watsonx_client(None)
    _set_tf_runner(None)


class TestOneBootstrapForBothTransports:
    """R4.7: both transports build backends through one function and list the same tools.

    The stdio serve loop and streams are faked; the HTTP server runs on a real
    loopback socket. Backend construction runs for real, with the watsonx SDK's
    client classes patched.
    """

    @pytest.fixture(autouse=True)
    def _isolate(self, monkeypatch, reset_portals):
        from lm_mcp import server as server_module
        from lm_mcp.hf_config import reset_hf_config
        from lm_mcp.terraform_config import reset_terraform_config

        for var in (
            "LM_MULTI_PORTAL",
            "LM_PORTALS_FILE",
            "LM_ENABLED_TOOLS",
            "LM_DISABLED_TOOLS",
            "LM_MCP_CATEGORIES",
            "LM_HTTP_AUTH_TOKEN",
            "LM_HTTP_ALLOW_UNAUTHENTICATED",
            "AWX_URL",
            "AWX_TOKEN",
            "WATSONX_API_KEY",
            "WATSONX_URL",
            "WATSONX_PROJECT_ID",
            "TF_WORKSPACE_DIR",
        ):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_HTTP_HOST", "127.0.0.1")
        monkeypatch.setenv("LM_HTTP_PORT", str(free_port("127.0.0.1")))
        reset_hf_config()
        reset_terraform_config()

        self.serve = AsyncMock()
        monkeypatch.setattr(server_module.server, "run", self.serve)
        monkeypatch.setattr("mcp.stdio_server", _fake_stdio_server())
        monkeypatch.setattr("lm_mcp.hf_config.get_hf_config", lambda: None)
        yield
        reset_hf_config()
        reset_terraform_config()

    def _configure_every_backend(self, monkeypatch, tmp_path) -> None:
        from unittest.mock import MagicMock

        monkeypatch.setenv("AWX_URL", "https://awx.example.com")
        monkeypatch.setenv("AWX_TOKEN", "awx-token")
        monkeypatch.setenv("WATSONX_API_KEY", "test-key")
        monkeypatch.setenv("WATSONX_PROJECT_ID", "test-project")
        monkeypatch.setenv("TF_WORKSPACE_DIR", str(tmp_path))
        monkeypatch.setattr("ibm_watsonx_ai.Credentials", MagicMock())
        monkeypatch.setattr("ibm_watsonx_ai.APIClient", MagicMock())

    async def test_configured_backends_list_the_same_tools(self, monkeypatch, tmp_path):
        """AWX, watsonx and Terraform configured: stdio and HTTP name the same tools."""
        from lm_mcp.registry import AWX_TOOLS, TF_TOOLS, WATSONX_TOOLS

        self._configure_every_backend(monkeypatch, tmp_path)

        stdio_names = await _stdio_tool_names(self.serve)
        _clear_backend_globals()
        http_names = await _http_tool_names(monkeypatch)

        assert stdio_names == http_names
        backend_names = {t.name for t in (*AWX_TOOLS, *WATSONX_TOOLS, *TF_TOOLS)}
        assert backend_names <= set(stdio_names)

    async def test_no_backends_list_the_filtered_core_tools(self, monkeypatch):
        """With no backend configured both transports list exactly the filtered TOOLS."""
        from lm_mcp.config import get_config
        from lm_mcp.registry import TOOLS
        from lm_mcp.server import _filter_tools

        expected = [t.name for t in _filter_tools(list(TOOLS), get_config())]

        assert await _stdio_tool_names(self.serve) == expected
        _clear_backend_globals()
        assert await _http_tool_names(monkeypatch) == expected

    async def test_each_transport_calls_bootstrap_backends_once(self, monkeypatch, tmp_path):
        """bootstrap_backends is the one function both transports build backends with."""
        from unittest.mock import patch

        from lm_mcp.transport import bootstrap

        self._configure_every_backend(monkeypatch, tmp_path)

        with patch.object(
            bootstrap, "bootstrap_backends", wraps=bootstrap.bootstrap_backends
        ) as spy:
            await _stdio_tool_names(self.serve)
            assert spy.call_count == 1
            _clear_backend_globals()
            await _http_tool_names(monkeypatch)
            assert spy.call_count == 2
