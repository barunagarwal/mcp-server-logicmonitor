# Description: Tests for the LMConfig configuration module.
# Description: Validates environment loading, credential validation, and URL normalization.

import pytest
from pydantic import ValidationError

from lm_mcp.config import LMConfig


class TestLMConfigBearer:
    """Tests for Bearer token configuration."""

    def test_valid_bearer_config(self, monkeypatch):
        """Valid Bearer config loads successfully from environment."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test_token_123")

        from lm_mcp.config import LMConfig

        config = LMConfig()

        assert config.portal == "test.logicmonitor.com"
        assert config.bearer_token == "test_token_123"
        assert config.api_version == 3
        assert config.timeout == 30

    def test_bearer_missing_token_raises_error(self, monkeypatch):
        """Missing bearer token raises ValidationError when no LMv1 auth."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.delenv("LM_BEARER_TOKEN", raising=False)
        monkeypatch.delenv("LM_ACCESS_ID", raising=False)
        monkeypatch.delenv("LM_ACCESS_KEY", raising=False)

        from lm_mcp.config import LMConfig

        with pytest.raises(ValueError, match="Authentication required"):
            LMConfig()

    def test_bearer_empty_token_raises_error(self, monkeypatch):
        """Empty bearer token raises ValidationError when no LMv1 auth."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "")
        monkeypatch.delenv("LM_ACCESS_ID", raising=False)
        monkeypatch.delenv("LM_ACCESS_KEY", raising=False)

        from lm_mcp.config import LMConfig

        with pytest.raises(ValueError, match="Authentication required"):
            LMConfig()

    def test_credentials_json_populates_lmv1_fields(self, monkeypatch):
        """LMv1 auth can be provided through LM_CREDENTIALS_JSON."""
        monkeypatch.delenv("LM_PORTAL", raising=False)
        monkeypatch.delenv("LM_ACCESS_ID", raising=False)
        monkeypatch.delenv("LM_ACCESS_KEY", raising=False)
        monkeypatch.setenv(
            "LM_CREDENTIALS_JSON",
            '{"access_id":"test_access_id","access_key":"test_access_key","portal_id":"qauat01"}',
        )

        config = LMConfig()

        assert config.portal == "qauat01.logicmonitor.com"
        assert config.access_id == "test_access_id"
        assert config.access_key == "test_access_key"

    def test_credentials_json_invalid_raises_error(self, monkeypatch):
        """Invalid LM_CREDENTIALS_JSON raises a validation error."""
        monkeypatch.delenv("LM_PORTAL", raising=False)
        monkeypatch.setenv("LM_CREDENTIALS_JSON", "not-json")

        with pytest.raises(ValueError, match="credentials_json must be valid JSON"):
            LMConfig()


class TestLMConfigPortalNormalization:
    """Tests for portal URL normalization."""

    def test_portal_strips_https_prefix(self, monkeypatch):
        """Portal URL with https:// prefix is normalized."""
        monkeypatch.setenv("LM_PORTAL", "https://test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test_token")

        from lm_mcp.config import LMConfig

        config = LMConfig()
        assert config.portal == "test.logicmonitor.com"

    def test_portal_strips_http_prefix(self, monkeypatch):
        """Portal URL with http:// prefix is normalized."""
        monkeypatch.setenv("LM_PORTAL", "http://test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test_token")

        from lm_mcp.config import LMConfig

        config = LMConfig()
        assert config.portal == "test.logicmonitor.com"

    def test_portal_strips_trailing_slash(self, monkeypatch):
        """Portal URL with trailing slash is normalized."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com/")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test_token")

        from lm_mcp.config import LMConfig

        config = LMConfig()
        assert config.portal == "test.logicmonitor.com"

    def test_portal_strips_https_and_trailing_slash(self, monkeypatch):
        """Portal URL with https:// and trailing slash is normalized."""
        monkeypatch.setenv("LM_PORTAL", "https://test.logicmonitor.com/")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test_token")

        from lm_mcp.config import LMConfig

        config = LMConfig()
        assert config.portal == "test.logicmonitor.com"


class TestLMConfigBaseUrl:
    """Tests for base_url property."""

    def test_base_url_property(self, monkeypatch):
        """base_url property returns correctly formatted URL."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test_token")

        from lm_mcp.config import LMConfig

        config = LMConfig()
        assert config.base_url == "https://test.logicmonitor.com/santaba/rest"


class TestLMConfigMissingPortal:
    """Tests for missing portal configuration."""

    def test_missing_portal_raises_error(self, monkeypatch):
        """Missing portal raises ValidationError."""
        monkeypatch.delenv("LM_PORTAL", raising=False)
        monkeypatch.setenv("LM_BEARER_TOKEN", "test_token")

        from lm_mcp.config import LMConfig

        with pytest.raises(ValidationError):
            LMConfig()


class TestLMConfigSession:
    """Tests for session configuration options."""

    def test_session_enabled_default(self, monkeypatch):
        """Session is enabled by default."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test_token")

        from lm_mcp.config import LMConfig

        config = LMConfig()
        assert config.session_enabled is True

    def test_session_disabled_from_env(self, monkeypatch):
        """Session can be disabled via environment."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test_token")
        monkeypatch.setenv("LM_SESSION_ENABLED", "false")

        from lm_mcp.config import LMConfig

        config = LMConfig()
        assert config.session_enabled is False

    def test_session_history_size_default(self, monkeypatch):
        """Session history size has default value."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test_token")

        from lm_mcp.config import LMConfig

        config = LMConfig()
        assert config.session_history_size == 50

    def test_session_history_size_from_env(self, monkeypatch):
        """Session history size can be set via environment."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test_token")
        monkeypatch.setenv("LM_SESSION_HISTORY_SIZE", "100")

        from lm_mcp.config import LMConfig

        config = LMConfig()
        assert config.session_history_size == 100

    def test_session_history_size_validation_min(self, monkeypatch):
        """Session history size below minimum (negative) raises error."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test_token")
        monkeypatch.setenv("LM_SESSION_HISTORY_SIZE", "-1")

        from lm_mcp.config import LMConfig

        with pytest.raises(ValueError):
            LMConfig()

    def test_session_history_size_validation_max(self, monkeypatch):
        """Session history size above maximum raises error."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test_token")
        monkeypatch.setenv("LM_SESSION_HISTORY_SIZE", "1001")

        from lm_mcp.config import LMConfig

        with pytest.raises(ValueError):
            LMConfig()


class TestLMConfigValidation:
    """Tests for field validation configuration options."""

    def test_field_validation_default(self, monkeypatch):
        """Field validation defaults to warn."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test_token")

        from lm_mcp.config import LMConfig

        config = LMConfig()
        assert config.field_validation == "warn"

    def test_field_validation_off(self, monkeypatch):
        """Field validation can be turned off."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test_token")
        monkeypatch.setenv("LM_FIELD_VALIDATION", "off")

        from lm_mcp.config import LMConfig

        config = LMConfig()
        assert config.field_validation == "off"

    def test_field_validation_error(self, monkeypatch):
        """Field validation can be set to error mode."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test_token")
        monkeypatch.setenv("LM_FIELD_VALIDATION", "error")

        from lm_mcp.config import LMConfig

        config = LMConfig()
        assert config.field_validation == "error"

    def test_field_validation_invalid_value(self, monkeypatch):
        """Invalid field validation value raises error."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test_token")
        monkeypatch.setenv("LM_FIELD_VALIDATION", "invalid")

        from lm_mcp.config import LMConfig

        with pytest.raises(ValueError):
            LMConfig()


class TestLMConfigHealth:
    """Tests for health check configuration options."""

    def test_health_check_connectivity_default(self, monkeypatch):
        """Health check connectivity is disabled by default."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test_token")

        from lm_mcp.config import LMConfig

        config = LMConfig()
        assert config.health_check_connectivity is False

    def test_health_check_connectivity_enabled(self, monkeypatch):
        """Health check connectivity can be enabled."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test_token")
        monkeypatch.setenv("LM_HEALTH_CHECK_CONNECTIVITY", "true")

        from lm_mcp.config import LMConfig

        config = LMConfig()
        assert config.health_check_connectivity is True


class TestToolFilterConfig:
    """Tests for tool filtering configuration."""

    def test_enabled_tools_accepted(self, monkeypatch):
        """LM_ENABLED_TOOLS config is accepted."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token-value")
        monkeypatch.setenv("LM_ENABLED_TOOLS", "get_devices,get_alerts")

        config = LMConfig()
        assert config.enabled_tools == "get_devices,get_alerts"

    def test_disabled_tools_accepted(self, monkeypatch):
        """LM_DISABLED_TOOLS config is accepted."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token-value")
        monkeypatch.setenv("LM_DISABLED_TOOLS", "delete_*")

        config = LMConfig()
        assert config.disabled_tools == "delete_*"

    def test_mutual_exclusion_error(self, monkeypatch):
        """Setting both enabled and disabled tools raises error."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token-value")
        monkeypatch.setenv("LM_ENABLED_TOOLS", "get_*")
        monkeypatch.setenv("LM_DISABLED_TOOLS", "delete_*")

        with pytest.raises(ValueError, match="Cannot set both"):
            LMConfig()

    def test_defaults_to_none(self, monkeypatch):
        """Tool filters default to None (all tools enabled)."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token-value")

        config = LMConfig()
        assert config.enabled_tools is None
        assert config.disabled_tools is None


class TestLMConfigSSL:
    """Tests for SSL/TLS transport configuration."""

    def test_ssl_fields_default_to_none(self, monkeypatch):
        """SSL fields default to None (no TLS)."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")

        config = LMConfig()
        assert config.http_ssl_certfile is None
        assert config.http_ssl_keyfile is None
        assert config.http_ssl_keyfile_password is None

    def test_ssl_certfile_from_env(self, monkeypatch):
        """SSL cert path loads from environment."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_HTTP_SSL_CERTFILE", "/path/to/cert.pem")

        config = LMConfig()
        assert config.http_ssl_certfile == "/path/to/cert.pem"

    def test_ssl_keyfile_from_env(self, monkeypatch):
        """SSL key path loads from environment."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_HTTP_SSL_KEYFILE", "/path/to/key.pem")

        config = LMConfig()
        assert config.http_ssl_keyfile == "/path/to/key.pem"

    def test_ssl_keyfile_password_from_env(self, monkeypatch):
        """SSL key password loads from environment."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_HTTP_SSL_KEYFILE_PASSWORD", "s3cret")

        config = LMConfig()
        assert config.http_ssl_keyfile_password == "s3cret"
