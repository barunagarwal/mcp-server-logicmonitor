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


class TestMultiPortalTransport:
    """Multi-portal mode is stdio-only; the HTTP transport shares one process."""

    def _vault(self, tmp_path):
        p = tmp_path / "portals.json"
        p.write_text('{"acme": {"portal": "acme.example.com", "bearer_token": "t"}}')
        return str(p)

    def test_multi_portal_rejects_http_transport(self, monkeypatch, tmp_path):
        """Multi-portal + HTTP transport must fail fast at config construction."""
        monkeypatch.setenv("LM_MULTI_PORTAL", "true")
        monkeypatch.setenv("LM_PORTALS_FILE", self._vault(tmp_path))
        monkeypatch.setenv("LM_TRANSPORT", "http")
        monkeypatch.delenv("LM_PORTAL", raising=False)
        monkeypatch.delenv("LM_BEARER_TOKEN", raising=False)

        with pytest.raises(ValidationError, match="stdio"):
            LMConfig()

    def test_multi_portal_allows_stdio_transport(self, monkeypatch, tmp_path):
        """Multi-portal with the default stdio transport constructs fine."""
        monkeypatch.setenv("LM_MULTI_PORTAL", "true")
        monkeypatch.setenv("LM_PORTALS_FILE", self._vault(tmp_path))
        monkeypatch.delenv("LM_TRANSPORT", raising=False)
        monkeypatch.delenv("LM_PORTAL", raising=False)
        monkeypatch.delenv("LM_BEARER_TOKEN", raising=False)

        config = LMConfig()
        assert config.multi_portal is True
        assert config.transport == "stdio"


class TestMultiPortalConfig:
    """Multi-portal config fail-fast and path expansion."""

    def _clear_vault_env(self, monkeypatch):
        for var in (
            "LM_PORTALS_FILE",
            "LM_VAULT_FILE",
            "LM_AGE_KEY",
            "LM_PORTAL",
            "LM_BEARER_TOKEN",
            "LM_TRANSPORT",
        ):
            monkeypatch.delenv(var, raising=False)

    def test_multi_portal_requires_vault_source(self, monkeypatch):
        self._clear_vault_env(monkeypatch)
        monkeypatch.setenv("LM_MULTI_PORTAL", "true")
        with pytest.raises(ValidationError, match="LM_VAULT_FILE"):
            LMConfig()

    def test_multi_portal_accepts_portals_file(self, monkeypatch, tmp_path):
        self._clear_vault_env(monkeypatch)
        p = tmp_path / "portals.json"
        p.write_text("{}")
        monkeypatch.setenv("LM_MULTI_PORTAL", "true")
        monkeypatch.setenv("LM_PORTALS_FILE", str(p))
        assert LMConfig().multi_portal is True

    def test_multi_portal_vault_pair_required_together(self, monkeypatch, tmp_path):
        self._clear_vault_env(monkeypatch)
        monkeypatch.setenv("LM_MULTI_PORTAL", "true")
        monkeypatch.setenv("LM_VAULT_FILE", str(tmp_path / "secrets.age"))
        with pytest.raises(ValidationError, match="LM_AGE_KEY"):
            LMConfig()

    def test_multi_portal_paths_expand_tilde(self, monkeypatch):
        from pathlib import Path

        self._clear_vault_env(monkeypatch)
        monkeypatch.setenv("LM_MULTI_PORTAL", "true")
        monkeypatch.setenv("LM_PORTALS_FILE", "~/p.json")
        config = LMConfig()
        assert config.portals_file == str(Path.home() / "p.json")

    def test_ingest_url_raises_without_portal(self, monkeypatch, tmp_path):
        self._clear_vault_env(monkeypatch)
        p = tmp_path / "portals.json"
        p.write_text("{}")
        monkeypatch.setenv("LM_MULTI_PORTAL", "true")
        monkeypatch.setenv("LM_PORTALS_FILE", str(p))
        config = LMConfig()
        with pytest.raises(ValueError, match="portal"):
            _ = config.ingest_url


class TestHttpUnauthenticatedBind:
    """R3.3: the HTTP transport refuses an unauthenticated non-loopback bind."""

    @pytest.fixture(autouse=True)
    def _http_env(self, monkeypatch):
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        for var in ("LM_HTTP_AUTH_TOKEN", "LM_HTTP_ALLOW_UNAUTHENTICATED", "LM_HTTP_HOST"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("LM_TRANSPORT", "http")

    def test_allow_unauthenticated_defaults_to_false(self, monkeypatch):
        """LM_HTTP_ALLOW_UNAUTHENTICATED is a bool that defaults to False."""
        monkeypatch.setenv("LM_HTTP_HOST", "127.0.0.1")
        assert LMConfig().http_allow_unauthenticated is False

    @pytest.mark.parametrize(("raw", "expected"), [("true", True), ("1", True), ("false", False)])
    def test_allow_unauthenticated_parses_as_bool(self, monkeypatch, raw, expected):
        """The override reads the usual boolean spellings."""
        monkeypatch.setenv("LM_HTTP_HOST", "127.0.0.1")
        monkeypatch.setenv("LM_HTTP_ALLOW_UNAUTHENTICATED", raw)
        assert LMConfig().http_allow_unauthenticated is expected

    @pytest.mark.parametrize("host", ["0.0.0.0", "::", "10.1.2.3", "mcp.internal"])
    def test_non_loopback_bind_without_token_is_refused(self, monkeypatch, host):
        """A non-loopback bind with no token and no override fails with one line naming both."""
        monkeypatch.setenv("LM_HTTP_HOST", host)
        with pytest.raises(ValidationError) as exc:
            LMConfig()
        message = exc.value.errors()[0]["msg"]
        assert "\n" not in message
        assert "LM_HTTP_AUTH_TOKEN" in message
        assert "LM_HTTP_ALLOW_UNAUTHENTICATED" in message

    def test_empty_token_counts_as_unset(self, monkeypatch):
        """Compose passes ${LM_HTTP_AUTH_TOKEN:-}, an empty string; it does not satisfy the bind."""
        monkeypatch.setenv("LM_HTTP_HOST", "0.0.0.0")
        monkeypatch.setenv("LM_HTTP_AUTH_TOKEN", "")
        with pytest.raises(ValidationError, match="LM_HTTP_ALLOW_UNAUTHENTICATED"):
            LMConfig()

    @pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost", "LOCALHOST"])
    def test_loopback_bind_without_token_is_allowed(self, monkeypatch, host):
        """Loopback binds need no token."""
        monkeypatch.setenv("LM_HTTP_HOST", host)
        assert LMConfig().http_auth_token is None

    def test_non_loopback_bind_with_token_is_allowed(self, monkeypatch):
        """A token satisfies a non-loopback bind."""
        monkeypatch.setenv("LM_HTTP_HOST", "0.0.0.0")
        monkeypatch.setenv("LM_HTTP_AUTH_TOKEN", "a" * 16)
        assert LMConfig().http_host == "0.0.0.0"

    def test_non_loopback_bind_with_override_is_allowed(self, monkeypatch):
        """The explicit override admits an unauthenticated non-loopback bind."""
        monkeypatch.setenv("LM_HTTP_HOST", "0.0.0.0")
        monkeypatch.setenv("LM_HTTP_ALLOW_UNAUTHENTICATED", "true")
        assert LMConfig().http_allow_unauthenticated is True

    def test_stdio_transport_ignores_the_bind(self, monkeypatch):
        """stdio never binds, so the default 0.0.0.0 host with no token constructs."""
        monkeypatch.setenv("LM_TRANSPORT", "stdio")
        config = LMConfig()
        assert config.http_host == "0.0.0.0"
        assert config.http_auth_token is None
