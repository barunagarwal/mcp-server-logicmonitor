# Description: Tests for LMv1 HMAC-SHA256 authentication provider.
# Description: Validates signature generation and header formatting.

import base64
import hashlib
import hmac
from unittest.mock import patch

import pytest

# Independently computed with LogicMonitor's documented LMv1 recipe:
# base64(hex(HMAC-SHA256("secret_key_456", "GET" + "1609459200000" + "" + "/device/devices")))
REFERENCE_AUTH_HEADER = (
    "LMv1 abc123:"
    "ZWY4MDZjZjlmYjRlNzQwMTBhZjUzZTRkNGVmYWZjNWJmYmQwN2MyNWRiMjJiZDZlM2QzMGQ0ZTFkOGZmYzMwZg=="
    ":1609459200000"
)


class TestLMv1Auth:
    """Tests for LMv1Auth provider."""

    def test_lmv1_auth_inherits_from_auth_provider(self):
        """LMv1Auth implements AuthProvider interface."""
        from lm_mcp.auth import AuthProvider
        from lm_mcp.auth.lmv1 import LMv1Auth

        auth = LMv1Auth("access_id", "access_key")
        assert isinstance(auth, AuthProvider)

    def test_lmv1_auth_stores_credentials(self):
        """LMv1Auth stores access_id and access_key."""
        from lm_mcp.auth.lmv1 import LMv1Auth

        auth = LMv1Auth("my_access_id", "my_access_key")
        assert auth.access_id == "my_access_id"
        assert auth.access_key == "my_access_key"

    def test_lmv1_auth_raises_on_empty_access_id(self):
        """LMv1Auth raises ConfigurationError if access_id is empty."""
        from lm_mcp.auth.lmv1 import LMv1Auth
        from lm_mcp.exceptions import ConfigurationError

        with pytest.raises(ConfigurationError, match="access_id"):
            LMv1Auth("", "access_key")

    def test_lmv1_auth_raises_on_none_access_id(self):
        """LMv1Auth raises ConfigurationError if access_id is None."""
        from lm_mcp.auth.lmv1 import LMv1Auth
        from lm_mcp.exceptions import ConfigurationError

        with pytest.raises(ConfigurationError, match="access_id"):
            LMv1Auth(None, "access_key")

    def test_lmv1_auth_raises_on_empty_access_key(self):
        """LMv1Auth raises ConfigurationError if access_key is empty."""
        from lm_mcp.auth.lmv1 import LMv1Auth
        from lm_mcp.exceptions import ConfigurationError

        with pytest.raises(ConfigurationError, match="access_key"):
            LMv1Auth("access_id", "")

    def test_lmv1_auth_raises_on_none_access_key(self):
        """LMv1Auth raises ConfigurationError if access_key is None."""
        from lm_mcp.auth.lmv1 import LMv1Auth
        from lm_mcp.exceptions import ConfigurationError

        with pytest.raises(ConfigurationError, match="access_key"):
            LMv1Auth("access_id", None)

    def test_get_auth_headers_returns_authorization_header(self):
        """get_auth_headers returns Authorization header with LMv1 prefix."""
        from lm_mcp.auth.lmv1 import LMv1Auth

        auth = LMv1Auth("test_id", "test_key")
        headers = auth.get_auth_headers("GET", "/santaba/rest/alert/alerts")

        assert "Authorization" in headers
        assert headers["Authorization"].startswith("LMv1 test_id:")

    def test_get_auth_headers_includes_timestamp(self):
        """Authorization header includes timestamp in milliseconds."""
        from lm_mcp.auth.lmv1 import LMv1Auth

        auth = LMv1Auth("test_id", "test_key")

        with patch("time.time", return_value=1609459200.0):
            headers = auth.get_auth_headers("GET", "/santaba/rest/alert/alerts")

        # Timestamp should be 1609459200000 (milliseconds)
        assert ":1609459200000" in headers["Authorization"]

    def test_get_auth_headers_format(self):
        """Authorization header follows LMv1 format: LMv1 access_id:signature:timestamp."""
        from lm_mcp.auth.lmv1 import LMv1Auth

        auth = LMv1Auth("my_id", "my_key")

        with patch("time.time", return_value=1609459200.0):
            headers = auth.get_auth_headers("GET", "/santaba/rest/alert/alerts")

        auth_value = headers["Authorization"]
        assert auth_value.startswith("LMv1 my_id:")
        parts = auth_value.replace("LMv1 ", "").split(":")
        assert len(parts) == 3
        assert parts[0] == "my_id"
        assert parts[2] == "1609459200000"

    def test_signature_uses_method_in_string(self):
        """Signature string includes HTTP method."""
        from lm_mcp.auth.lmv1 import LMv1Auth

        auth = LMv1Auth("test_id", "test_key")

        with patch("time.time", return_value=1609459200.0):
            get_headers = auth.get_auth_headers("GET", "/path")
            post_headers = auth.get_auth_headers("POST", "/path")

        # Different methods should produce different signatures
        get_sig = get_headers["Authorization"].split(":")[1]
        post_sig = post_headers["Authorization"].split(":")[1]
        assert get_sig != post_sig

    def test_signature_uses_path_in_string(self):
        """Signature string includes resource path."""
        from lm_mcp.auth.lmv1 import LMv1Auth

        auth = LMv1Auth("test_id", "test_key")

        with patch("time.time", return_value=1609459200.0):
            headers1 = auth.get_auth_headers("GET", "/alert/alerts")
            headers2 = auth.get_auth_headers("GET", "/device/devices")

        # Different paths should produce different signatures
        sig1 = headers1["Authorization"].split(":")[1]
        sig2 = headers2["Authorization"].split(":")[1]
        assert sig1 != sig2

    def test_signature_uses_body_in_string(self):
        """Signature string includes request body."""
        from lm_mcp.auth.lmv1 import LMv1Auth

        auth = LMv1Auth("test_id", "test_key")

        with patch("time.time", return_value=1609459200.0):
            headers1 = auth.get_auth_headers("POST", "/path", "")
            headers2 = auth.get_auth_headers("POST", "/path", '{"key": "value"}')

        # Different bodies should produce different signatures
        sig1 = headers1["Authorization"].split(":")[1]
        sig2 = headers2["Authorization"].split(":")[1]
        assert sig1 != sig2

    def test_signature_is_base64_encoded(self):
        """Signature is valid base64."""
        from lm_mcp.auth.lmv1 import LMv1Auth

        auth = LMv1Auth("test_id", "test_key")
        headers = auth.get_auth_headers("GET", "/path")

        signature = headers["Authorization"].split(":")[1]

        # Should not raise if valid base64
        decoded = base64.b64decode(signature)
        # LM signs the hex digest: 64 lowercase hex chars for SHA256
        assert len(decoded) == 64
        assert all(c in b"0123456789abcdef" for c in decoded)

    def test_signature_calculation_matches_expected(self):
        """Signature matches expected HMAC-SHA256 calculation."""
        from lm_mcp.auth.lmv1 import LMv1Auth

        access_id = "abc123"
        access_key = "secret_key_456"
        method = "GET"
        resource_path = "/santaba/rest/alert/alerts"
        body = ""
        timestamp_ms = 1609459200000

        auth = LMv1Auth(access_id, access_key)

        with patch("time.time", return_value=1609459200.0):
            headers = auth.get_auth_headers(method, resource_path, body)

        # Manually compute expected signature
        # signature_string = method + timestamp + body + resource_path
        sig_string = f"{method}{timestamp_ms}{body}{resource_path}"
        expected_hmac = hmac.new(
            access_key.encode("utf-8"),
            sig_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        expected_signature = base64.b64encode(expected_hmac.encode("utf-8")).decode("utf-8")

        actual_signature = headers["Authorization"].split(":")[1]
        assert actual_signature == expected_signature

    def test_signature_matches_logicmonitor_reference_vector(self):
        """Signature equals a value computed independently with LM's documented recipe."""
        from lm_mcp.auth.lmv1 import LMv1Auth

        auth = LMv1Auth("abc123", "secret_key_456")
        with patch("time.time", return_value=1609459200.0):
            headers = auth.get_auth_headers("GET", "/device/devices", "")

        # base64(hex(HMAC-SHA256(key, "GET1609459200000/device/devices")))
        assert headers["Authorization"] == REFERENCE_AUTH_HEADER

    def test_signature_with_body(self):
        """Signature correctly includes body in calculation."""
        from lm_mcp.auth.lmv1 import LMv1Auth

        access_id = "test_id"
        access_key = "test_key"
        method = "POST"
        resource_path = "/santaba/rest/log/ingest"
        body = '{"message": "test log"}'
        timestamp_ms = 1609459200000

        auth = LMv1Auth(access_id, access_key)

        with patch("time.time", return_value=1609459200.0):
            headers = auth.get_auth_headers(method, resource_path, body)

        # Manually compute expected signature
        sig_string = f"{method}{timestamp_ms}{body}{resource_path}"
        expected_hmac = hmac.new(
            access_key.encode("utf-8"),
            sig_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        expected_signature = base64.b64encode(expected_hmac.encode("utf-8")).decode("utf-8")

        actual_signature = headers["Authorization"].split(":")[1]
        assert actual_signature == expected_signature


class TestLMv1AuthFactory:
    """Tests for LMv1Auth in factory function."""

    def test_factory_creates_lmv1_auth_when_access_id_set(self, monkeypatch):
        """Factory creates LMv1Auth when access_id and access_key are set."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_ACCESS_ID", "my_access_id")
        monkeypatch.setenv("LM_ACCESS_KEY", "my_access_key")
        # Clear bearer token to avoid conflict
        monkeypatch.delenv("LM_BEARER_TOKEN", raising=False)

        from lm_mcp.auth import create_auth_provider
        from lm_mcp.auth.lmv1 import LMv1Auth
        from lm_mcp.config import LMConfig

        config = LMConfig()
        auth = create_auth_provider(config)

        assert isinstance(auth, LMv1Auth)
        assert auth.access_id == "my_access_id"
        assert auth.access_key == "my_access_key"

    def test_factory_prefers_bearer_over_lmv1(self, monkeypatch):
        """Factory prefers Bearer auth when both are configured."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "bearer_token")
        monkeypatch.setenv("LM_ACCESS_ID", "access_id")
        monkeypatch.setenv("LM_ACCESS_KEY", "access_key")

        from lm_mcp.auth import create_auth_provider
        from lm_mcp.auth.bearer import BearerAuth
        from lm_mcp.config import LMConfig

        config = LMConfig()
        auth = create_auth_provider(config)

        assert isinstance(auth, BearerAuth)

    def test_config_raises_when_no_auth_configured(self, monkeypatch):
        """Config raises ValidationError when no auth is configured."""
        from pydantic import ValidationError

        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.delenv("LM_BEARER_TOKEN", raising=False)
        monkeypatch.delenv("LM_ACCESS_ID", raising=False)
        monkeypatch.delenv("LM_ACCESS_KEY", raising=False)

        from lm_mcp.config import LMConfig

        with pytest.raises(ValidationError, match="Authentication required"):
            LMConfig()

    def test_config_raises_when_access_id_without_key(self, monkeypatch):
        """Config raises when access_id is set but access_key is missing."""
        from pydantic import ValidationError

        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.delenv("LM_BEARER_TOKEN", raising=False)
        monkeypatch.setenv("LM_ACCESS_ID", "my_access_id")
        monkeypatch.delenv("LM_ACCESS_KEY", raising=False)

        from lm_mcp.config import LMConfig

        with pytest.raises(ValidationError, match="access_key"):
            LMConfig()

    def test_config_raises_when_access_key_without_id(self, monkeypatch):
        """Config raises when access_key is set but access_id is missing."""
        from pydantic import ValidationError

        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.delenv("LM_BEARER_TOKEN", raising=False)
        monkeypatch.delenv("LM_ACCESS_ID", raising=False)
        monkeypatch.setenv("LM_ACCESS_KEY", "my_access_key")

        from lm_mcp.config import LMConfig

        with pytest.raises(ValidationError, match="access_id"):
            LMConfig()
