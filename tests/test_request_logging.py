# Description: Tests for request logging and debug mode.
# Description: Verifies log level config and debug/warning mode behavior.

import logging

import pytest


class TestLogLevelConfig:
    """Tests for LM_LOG_LEVEL configuration."""

    def test_default_log_level_is_warning(self, monkeypatch):
        """Default log_level is 'warning'."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test_token_value")

        from lm_mcp.config import LMConfig

        config = LMConfig()
        assert config.log_level == "warning"

    def test_log_level_accepts_debug(self, monkeypatch):
        """log_level accepts 'debug' value."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test_token_value")
        monkeypatch.setenv("LM_LOG_LEVEL", "debug")

        from lm_mcp.config import LMConfig

        config = LMConfig()
        assert config.log_level == "debug"

    def test_log_level_accepts_info(self, monkeypatch):
        """log_level accepts 'info' value."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test_token_value")
        monkeypatch.setenv("LM_LOG_LEVEL", "info")

        from lm_mcp.config import LMConfig

        config = LMConfig()
        assert config.log_level == "info"

    def test_log_level_rejects_invalid(self, monkeypatch):
        """log_level rejects invalid values."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test_token_value")
        monkeypatch.setenv("LM_LOG_LEVEL", "verbose")

        from lm_mcp.config import LMConfig

        with pytest.raises(ValueError):
            LMConfig()


class TestDebugModeLogging:
    """Tests for debug mode log output integration."""

    def test_debug_mode_produces_request_log(self, caplog):
        """Debug mode produces log for API request details."""
        from lm_mcp.logging import log_api_request

        with caplog.at_level(logging.DEBUG, logger="lm_mcp.client"):
            log_api_request("GET", "/alert/alerts", {"size": 50})

        assert "GET /alert/alerts" in caplog.text

    def test_warning_mode_suppresses_request_log(self, caplog):
        """Warning mode suppresses debug-level request logs."""
        from lm_mcp.logging import log_api_request

        with caplog.at_level(logging.WARNING, logger="lm_mcp.client"):
            log_api_request("GET", "/alert/alerts", {"size": 50})

        assert caplog.text == ""


class TestConfigureLogging:
    """configure_logging routes records to stderr at LM_LOG_LEVEL (R3.7)."""

    @pytest.fixture
    def restore_root(self):
        """Put the root logger back as it was: level, and no server stderr handler."""
        from lm_mcp.logging import STDERR_HANDLER_NAME

        root = logging.getLogger()
        level = root.level
        yield
        for handler in list(root.handlers):
            if handler.get_name() == STDERR_HANDLER_NAME:
                root.removeHandler(handler)
        root.setLevel(level)

    def _config(self, monkeypatch, level):
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test_token_value")
        monkeypatch.setenv("LM_LOG_LEVEL", level)

        from lm_mcp.config import LMConfig

        return LMConfig()

    def test_info_level_puts_the_audit_line_on_stderr(self, monkeypatch, capsys, restore_root):
        """At info an INFO audit record reaches the stderr handler with level and logger name."""
        from lm_mcp.logging import configure_logging, log_write_operation

        configure_logging(self._config(monkeypatch, "info"))
        log_write_operation("create_device", {"name": "web-01"}, success=True)

        err = capsys.readouterr().err
        assert "Write operation: create_device" in err
        assert "INFO" in err
        assert "lm_mcp.audit" in err

    def test_warning_level_drops_the_info_audit_line(self, monkeypatch, capsys, restore_root):
        """At warning the INFO audit record is not emitted, while a failed write still is."""
        from lm_mcp.logging import configure_logging, log_write_operation

        configure_logging(self._config(monkeypatch, "warning"))
        log_write_operation("create_device", {"name": "web-01"}, success=True)
        assert "Write operation" not in capsys.readouterr().err

        log_write_operation("delete_device", {"device_id": 7}, success=False)
        err = capsys.readouterr().err
        assert "Write operation failed: delete_device" in err
        assert "WARNING" in err

    def test_nothing_is_written_to_stdout(self, monkeypatch, capsys, restore_root):
        """stdout is the stdio JSON-RPC channel, so log records never go there."""
        from lm_mcp.logging import configure_logging, log_write_operation

        configure_logging(self._config(monkeypatch, "info"))
        log_write_operation("create_device", {"name": "web-01"}, success=True)

        captured = capsys.readouterr()
        assert captured.out == ""
        assert "create_device" in captured.err

    def test_configure_logging_is_idempotent(self, monkeypatch, capsys, restore_root):
        """A second call installs no second handler, so a record is written once."""
        from lm_mcp.logging import STDERR_HANDLER_NAME, configure_logging, log_write_operation

        first = configure_logging(self._config(monkeypatch, "info"))
        second = configure_logging(self._config(monkeypatch, "info"))

        root = logging.getLogger()
        assert second is first
        assert [h.get_name() for h in root.handlers].count(STDERR_HANDLER_NAME) == 1
        log_write_operation("create_device", {"name": "web-01"}, success=True)
        assert capsys.readouterr().err.count("Write operation: create_device") == 1

    async def test_run_server_configures_logging_first(self, monkeypatch, restore_root):
        """run_server installs the handler at the configured level before the runner starts."""
        from lm_mcp import transport
        from lm_mcp.logging import STDERR_HANDLER_NAME

        self._config(monkeypatch, "info")
        seen: dict = {}

        async def fake_runner():
            root = logging.getLogger()
            seen["level"] = root.level
            seen["handlers"] = [h.get_name() for h in root.handlers]

        monkeypatch.setattr(transport, "get_transport_runner", lambda config: fake_runner)

        from lm_mcp.server import run_server

        await run_server()

        assert seen["level"] == logging.INFO
        assert STDERR_HANDLER_NAME in seen["handlers"]
