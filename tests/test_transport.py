# Description: Tests for the transport abstraction module.
# Description: Validates transport runner selection and configuration.

import logging
import sys
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from lm_mcp.transport import get_transport_runner, run_http, run_stdio


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

    async def test_single_portal_client_uses_configured_max_retries(self, monkeypatch):
        """R1.6: the single-portal client is built with LM_MAX_RETRIES, not the default."""
        from lm_mcp import server as server_module

        monkeypatch.setenv("LM_MAX_RETRIES", "7")
        # Shutdown nulls the global client, so read it while the loop is serving.
        serving_clients = []
        self.serve.side_effect = lambda *args: serving_clients.append(server_module._client)

        await run_stdio()

        self.serve.assert_awaited_once()
        assert serving_clients[0] is not None
        assert serving_clients[0].max_retries == 7
