# Description: Configuration module for LogicMonitor MCP Server.
# Description: Handles environment variable loading and validation for LM API credentials.

import json
import re
from typing import Any, Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings

_cached_config: "LMConfig | None" = None


def get_config() -> "LMConfig":
    """Get the cached LMConfig singleton.

    Parses environment variables on first call, returns cached instance
    on subsequent calls. Use reset_config() in tests to clear the cache.

    Returns:
        The LMConfig instance.
    """
    global _cached_config
    if _cached_config is None:
        _cached_config = LMConfig()
    return _cached_config


def reset_config() -> None:
    """Clear the cached config. Used in tests to reset state."""
    global _cached_config
    _cached_config = None


class LMConfig(BaseSettings):
    """Configuration for LogicMonitor MCP Server.

    Loads configuration from environment variables with LM_ prefix.
    Supports both Bearer token and LMv1 HMAC authentication.

    Environment Variables:
        LM_PORTAL: LogicMonitor portal hostname (e.g., company.logicmonitor.com)
        LM_BEARER_TOKEN: API Bearer token for authentication (preferred)
        LM_ACCESS_ID: LMv1 access ID for HMAC authentication
        LM_ACCESS_KEY: LMv1 access key for HMAC authentication
        LM_CREDENTIALS_JSON: JSON object containing bearer_token or
            access_id/access_key and optionally portal or portal_id
        LM_API_VERSION: API version (default: 3)
        LM_TIMEOUT: Request timeout in seconds (default: 30, range: 5-300)
        LM_ENABLE_WRITE_OPERATIONS: Enable write operations (default: false)
        LM_MAX_RETRIES: Max retry attempts for rate limits (default: 3, range: 0-10)
        LM_TRANSPORT: Transport mode - stdio or http (default: stdio)
        LM_HTTP_HOST: HTTP server bind address (default: 0.0.0.0)
        LM_HTTP_PORT: HTTP server port (default: 8080)
        LM_CORS_ORIGINS: Comma-separated CORS origins (default: empty, no CORS)
        LM_SESSION_ENABLED: Enable session context tracking (default: true)
        LM_SESSION_HISTORY_SIZE: Number of tool calls to keep in history (default: 50)
        LM_FIELD_VALIDATION: Field validation mode - off, warn, or error (default: warn)
        LM_ENABLED_TOOLS: Comma-separated tool names or glob patterns to enable (default: all)
        LM_DISABLED_TOOLS: Comma-separated tool names or glob patterns to disable (default: none)
        LM_HEALTH_CHECK_CONNECTIVITY: Include LM API ping in health checks (default: false)
        LM_LOG_LEVEL: Logging level - debug, info, warning, or error (default: warning)

    Authentication:
        Either bearer_token OR both (access_id AND access_key) must be provided.
        Bearer token is preferred when both are configured.
    """

    # Core settings
    portal: str
    bearer_token: str | None = None
    access_id: str | None = None
    access_key: str | None = None
    credentials_json: str | None = None
    api_version: int = 3
    timeout: int = 30
    enable_write_operations: bool = False
    max_retries: int = 3

    # Transport settings
    transport: Literal["stdio", "http"] = "stdio"
    http_host: str = "0.0.0.0"
    http_port: int = 8080
    cors_origins: str = ""
    http_ssl_certfile: str | None = None
    http_ssl_keyfile: str | None = None
    http_ssl_keyfile_password: str | None = None

    # Session settings
    session_enabled: bool = True
    session_history_size: int = 50

    # Validation settings
    field_validation: Literal["off", "warn", "error"] = "warn"

    # Tool filtering
    enabled_tools: str | None = None
    disabled_tools: str | None = None

    # Health check settings
    health_check_connectivity: bool = False

    # Logging settings
    log_level: Literal["debug", "info", "warning", "error"] = "warning"

    model_config = {
        "env_prefix": "LM_",
    }

    @staticmethod
    def _portal_from_credentials(value: Any) -> str | None:
        """Normalize portal identifiers from credential payloads.

        LogicMonitor secret payloads sometimes store only the portal ID
        (for example `qauat01`) instead of the full hostname.
        """
        if value is None:
            return None

        portal = str(value).strip()
        if not portal:
            return None
        if "." not in portal:
            return f"{portal}.logicmonitor.com"
        return portal

    @model_validator(mode="before")
    @classmethod
    def load_credentials_json(cls, data: Any) -> Any:
        """Populate auth fields from LM_CREDENTIALS_JSON when provided."""
        if not isinstance(data, dict):
            return data

        raw = data.get("credentials_json")
        if not raw:
            return data

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("credentials_json must be valid JSON") from exc

        if not isinstance(payload, dict):
            raise ValueError("credentials_json must be a JSON object")

        if not data.get("bearer_token"):
            bearer_token = payload.get("bearer_token") or payload.get("token")
            if bearer_token:
                data["bearer_token"] = str(bearer_token)

        if not data.get("access_id"):
            access_id = payload.get("access_id") or payload.get("accessId")
            if access_id:
                data["access_id"] = str(access_id)

        if not data.get("access_key"):
            access_key = payload.get("access_key") or payload.get("accessKey")
            if access_key:
                data["access_key"] = str(access_key)

        if not data.get("portal"):
            portal = (
                payload.get("portal")
                or payload.get("portal_id")
                or payload.get("portalId")
            )
            normalized = cls._portal_from_credentials(portal)
            if normalized:
                data["portal"] = normalized

        return data

    @field_validator("portal", mode="before")
    @classmethod
    def normalize_portal(cls, v: str) -> str:
        """Strip protocol prefix and trailing slashes from portal hostname."""
        if v is None:
            return v
        v = str(v)
        if v.startswith("https://"):
            v = v[8:]
        elif v.startswith("http://"):
            v = v[7:]
        v = v.rstrip("/")

        # Validate portal hostname format
        if not v or len(v) < 5:
            raise ValueError("portal must be a valid hostname (e.g., company.logicmonitor.com)")
        if not re.match(r"^[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9\-]+)+$", v):
            raise ValueError(
                f"portal '{v}' is not a valid hostname format (expected: company.logicmonitor.com)"
            )
        return v

    @field_validator("timeout", mode="after")
    @classmethod
    def validate_timeout(cls, v: int) -> int:
        """Validate timeout is within acceptable range."""
        if v < 5:
            raise ValueError("timeout must be at least 5 seconds")
        if v > 300:
            raise ValueError("timeout must not exceed 300 seconds (5 minutes)")
        return v

    @field_validator("max_retries", mode="after")
    @classmethod
    def validate_max_retries(cls, v: int) -> int:
        """Validate max_retries is within acceptable range."""
        if v < 0:
            raise ValueError("max_retries must be non-negative")
        if v > 10:
            raise ValueError("max_retries must not exceed 10")
        return v

    @field_validator("http_port", mode="after")
    @classmethod
    def validate_http_port(cls, v: int) -> int:
        """Validate HTTP port is within acceptable range."""
        if v < 1 or v > 65535:
            raise ValueError("http_port must be between 1 and 65535")
        return v

    @field_validator("session_history_size", mode="after")
    @classmethod
    def validate_session_history_size(cls, v: int) -> int:
        """Validate session history size is within acceptable range."""
        if v < 0:
            raise ValueError("session_history_size must be non-negative")
        if v > 1000:
            raise ValueError("session_history_size must not exceed 1000")
        return v

    @model_validator(mode="after")
    def validate_authentication(self) -> "LMConfig":
        """Validate that at least one authentication method is configured.

        Either bearer_token OR both (access_id AND access_key) must be provided.
        """
        has_bearer = bool(self.bearer_token)
        has_lmv1 = bool(self.access_id) or bool(self.access_key)

        if has_bearer:
            if len(self.bearer_token) < 10:
                raise ValueError("bearer_token appears invalid (too short)")
            return self

        if has_lmv1:
            if not self.access_id:
                raise ValueError("access_id is required when using LMv1 authentication")
            if not self.access_key:
                raise ValueError("access_key is required when using LMv1 authentication")
            return self

        raise ValueError(
            "Authentication required: set either LM_BEARER_TOKEN or "
            "both LM_ACCESS_ID and LM_ACCESS_KEY"
        )

    @model_validator(mode="after")
    def validate_tool_filters(self) -> "LMConfig":
        """Validate that enabled_tools and disabled_tools are not both set."""
        if self.enabled_tools and self.disabled_tools:
            raise ValueError(
                "Cannot set both LM_ENABLED_TOOLS and LM_DISABLED_TOOLS. Use one or the other."
            )
        return self

    @property
    def has_lmv1_auth(self) -> bool:
        """Check if LMv1 credentials are configured."""
        return bool(self.access_id and self.access_key)

    @property
    def base_url(self) -> str:
        """Return the base URL for LogicMonitor REST API."""
        return f"https://{self.portal}/santaba/rest"

    @property
    def ingest_url(self) -> str:
        """Return the base URL for LogicMonitor ingestion APIs.

        Ingestion APIs (logs, metrics) use a different path structure
        than the standard REST API.
        """
        return f"https://{self.portal}"

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS origins from comma-separated string to list.

        Returns ["*"] if cors_origins is "*" (allow all).
        Otherwise splits by comma and strips whitespace.
        """
        if self.cors_origins == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
