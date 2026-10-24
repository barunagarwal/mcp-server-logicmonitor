# Description: Tests for Ansible Automation Platform configuration loading.
# Description: Verifies pydantic-settings env var handling and optional singleton.


class TestAwxConfig:
    def test_loads_from_env(self, monkeypatch):
        from lm_mcp.awx_config import AwxConfig

        monkeypatch.setenv("AWX_URL", "https://controller.example.com")
        monkeypatch.setenv("AWX_TOKEN", "mytoken123")
        config = AwxConfig()
        assert config.url == "https://controller.example.com"
        assert config.token == "mytoken123"

    def test_defaults(self, monkeypatch):
        from lm_mcp.awx_config import AwxConfig

        monkeypatch.setenv("AWX_URL", "https://controller.example.com")
        monkeypatch.setenv("AWX_TOKEN", "mytoken123")
        config = AwxConfig()
        assert config.verify_ssl is True
        assert config.timeout == 30
        assert config.max_retries == 3

    def test_get_awx_config_returns_none_without_url(self, monkeypatch):
        from lm_mcp.awx_config import get_awx_config, reset_awx_config

        monkeypatch.delenv("AWX_URL", raising=False)
        monkeypatch.delenv("AWX_TOKEN", raising=False)
        reset_awx_config()
        assert get_awx_config() is None

    def test_get_awx_config_returns_config_with_url(self, monkeypatch):
        from lm_mcp.awx_config import get_awx_config, reset_awx_config

        monkeypatch.setenv("AWX_URL", "https://controller.example.com")
        monkeypatch.setenv("AWX_TOKEN", "mytoken123")
        reset_awx_config()
        config = get_awx_config()
        assert config is not None
        assert config.url == "https://controller.example.com"

    def test_get_awx_config_is_cached(self, monkeypatch):
        from lm_mcp.awx_config import get_awx_config, reset_awx_config

        monkeypatch.setenv("AWX_URL", "https://controller.example.com")
        monkeypatch.setenv("AWX_TOKEN", "mytoken123")
        reset_awx_config()
        c1 = get_awx_config()
        c2 = get_awx_config()
        assert c1 is c2

    def test_unusable_verify_ssl_is_logged_by_name(self, monkeypatch, caplog):
        """R4.5: AWX configured with an unreadable AWX_VERIFY_SSL logs it, then returns None."""
        import logging

        from lm_mcp.awx_config import get_awx_config, reset_awx_config

        monkeypatch.setenv("AWX_URL", "https://controller.example.com")
        monkeypatch.setenv("AWX_TOKEN", "mytoken123")
        monkeypatch.setenv("AWX_VERIFY_SSL", "maybe")
        reset_awx_config()

        with caplog.at_level(logging.WARNING, logger="lm_mcp"):
            assert get_awx_config() is None

        (record,) = [r for r in caplog.records if r.levelno == logging.WARNING]
        message = record.getMessage()
        assert "AWX_VERIFY_SSL" in message
        assert "maybe" not in message
        assert "mytoken123" not in message
