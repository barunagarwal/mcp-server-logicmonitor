# Description: Configuration module for LogicMonitor MCP Server.
# Description: Handles environment variable loading and validation for LM API credentials.

import os
import re
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings


def normalize_portal_host(v: str) -> str:
    """Strip scheme and trailing slashes from a portal hostname and validate it.

    Shared by the LM_PORTAL field validator and the multi-portal vault records,
    so both sources yield the same canonical host form.
    """
    v = str(v)
    if v.startswith("https://"):
        v = v[8:]
    elif v.startswith("http://"):
        v = v[7:]
    v = v.rstrip("/")

    if not v or len(v) < 5:
        raise ValueError("portal must be a valid hostname (e.g., company.logicmonitor.com)")
    if not re.match(r"^[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9\-]+)+$", v):
        raise ValueError(
            f"portal '{v}' is not a valid hostname format (expected: company.logicmonitor.com)"
        )
    return v


# HTTP bind addresses only the local host can reach.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
# HTTP bind addresses that mean "every interface" rather than a name to reach.
_WILDCARD_HOSTS = frozenset({"0.0.0.0", "::", ""})

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
        LM_API_VERSION: API version (default: 3)
        LM_TIMEOUT: Request timeout in seconds (default: 30, range: 5-300)
        LM_ENABLE_WRITE_OPERATIONS: Enable write operations (default: false)
        LM_MAX_RETRIES: Max retry attempts for rate limits (default: 3, range: 0-10)
        LM_TRANSPORT: Transport mode - stdio or http (default: stdio)
        LM_MULTI_PORTAL: Serve many customer portals from one server, selected at
            runtime via use_portal (default: false; stdio-only)
        LM_VAULT_FILE: Path to the age-encrypted portal vault (multi-portal)
        LM_AGE_KEY: Path to the age identity file that decrypts the vault
        LM_PORTALS_FILE: Plaintext JSON portal map (multi-portal, testing only;
            the encrypted vault takes precedence when both are set)
        LM_HTTP_HOST: HTTP server bind address (default: 0.0.0.0). With
            LM_TRANSPORT=http, a non-loopback bind needs LM_HTTP_AUTH_TOKEN or
            LM_HTTP_ALLOW_UNAUTHENTICATED=true, or the server refuses to start.
        LM_HTTP_PORT: HTTP server port (default: 8080)
        LM_CORS_ORIGINS: Comma-separated CORS origins (default: empty, no CORS)
        LM_HTTP_AUTH_TOKEN: Require this bearer token on /mcp and /api/v1/*
            (default: unset, no inbound auth; minimum 16 characters). The health
            endpoints and / stay open for probes. HTTP transport only.
        LM_HTTP_ALLOW_UNAUTHENTICATED: Accept a non-loopback HTTP bind with no
            LM_HTTP_AUTH_TOKEN, for a listener protected some other way such as
            an authenticating proxy (default: false). HTTP transport only.
        LM_HTTP_ALLOWED_HOSTS: Comma-separated Host names the server accepts on
            every route except /healthz and /readyz, besides the loopback names
            and a non-wildcard LM_HTTP_HOST (default: empty). HTTP transport only.
        LM_HTTP_SSL_CERTFILE: TLS certificate path for the HTTP transport
        LM_HTTP_SSL_KEYFILE: TLS private key path for the HTTP transport
        LM_HTTP_SSL_KEYFILE_PASSWORD: Password for an encrypted TLS private key
        LM_SESSION_ENABLED: Enable session context tracking (default: true)
        LM_SESSION_HISTORY_SIZE: Number of tool calls to keep in history (default: 50)
        LM_FIELD_VALIDATION: Field validation mode - off, warn, or error (default: warn)
        LM_ENABLED_TOOLS: Comma-separated tool names or glob patterns to enable (default: all)
        LM_DISABLED_TOOLS: Comma-separated tool names or glob patterns to disable (default: none)
        LM_MCP_CATEGORIES: Comma-separated categories to include (default: all).
            Categories: read, write, delete, export, import, session, workflow.
            Composes by intersection with LM_ENABLED_TOOLS / LM_DISABLED_TOOLS --
            only narrows the surface, never expands.
        LM_HEALTH_CHECK_CONNECTIVITY: Include LM API ping in health checks (default: false)
        LM_LOG_LEVEL: Logging level - debug, info, warning, or error (default: warning)

    Authentication:
        Either bearer_token OR both (access_id AND access_key) must be provided.
        Bearer token is preferred when both are configured.
    """

    # Core settings
    portal: str | None = None
    bearer_token: str | None = None
    access_id: str | None = None
    access_key: str | None = None
    api_version: int = 3
    timeout: int = 30
    enable_write_operations: bool = False
    max_retries: int = 3

    # Multi-portal settings (one server serving many customer portals)
    multi_portal: bool = False
    vault_file: str | None = None
    age_key: str | None = None
    portals_file: str | None = None

    # Transport settings
    transport: Literal["stdio", "http"] = "stdio"
    http_host: str = "0.0.0.0"
    http_port: int = 8080
    cors_origins: str = ""
    http_auth_token: str | None = None
    http_allow_unauthenticated: bool = False
    http_allowed_hosts: str = ""
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
    # Comma-separated: read,write,delete,export,import,session,workflow
    mcp_categories: str | None = None

    # Health check settings
    health_check_connectivity: bool = False

    # Logging settings
    log_level: Literal["debug", "info", "warning", "error"] = "warning"

    model_config = {
        "env_prefix": "LM_",
        # Validation errors must never echo the rejected value: these fields hold
        # credentials, and the error text reaches startup tracebacks, container
        # logs, and the health endpoint's response body.
        "hide_input_in_errors": True,
    }

    @field_validator("portal", mode="before")
    @classmethod
    def normalize_portal(cls, v: str) -> str:
        """Strip protocol prefix and trailing slashes from portal hostname."""
        if v is None:
            return v
        return normalize_portal_host(v)

    @field_validator("portals_file", "vault_file", "age_key", mode="before")
    @classmethod
    def expand_vault_paths(cls, v: str | None) -> str | None:
        """Expand ~ in vault paths; GUI-launched stdio servers get no shell expansion."""
        if v is None:
            return v
        return os.path.expanduser(str(v))

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

    @field_validator("http_auth_token", mode="after")
    @classmethod
    def validate_http_auth_token(cls, v: str | None) -> str | None:
        """Treat an empty value as unset and require real length when set.

        docker-compose passes ${LM_HTTP_AUTH_TOKEN:-}, which arrives as an empty
        string, so empty must mean "no inbound auth" rather than a length error.
        Surrounding whitespace is stripped: a token read from a Kubernetes secret
        file or a .env line often carries a trailing newline, and HTTP parsers
        strip it from header values, so keeping it would 401 every client forever.
        """
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        if len(v) < 16:
            raise ValueError("http_auth_token must be at least 16 characters when set")
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
        if self.multi_portal:
            if self.transport == "http":
                raise ValueError(
                    "LM_MULTI_PORTAL is stdio-only; the HTTP transport shares one "
                    "process across clients. Use LM_TRANSPORT=stdio."
                )
            if not self.portals_file and not (self.vault_file and self.age_key):
                raise ValueError(
                    "Multi-portal mode needs LM_PORTALS_FILE, or LM_VAULT_FILE + LM_AGE_KEY"
                )
            return self

        # Single-portal mode keeps upstream's fail-fast guarantee: a fixed portal is
        # required. (Multi-portal mode selects the portal at runtime via use_portal.)
        if not self.portal:
            raise ValueError(
                "LM_PORTAL is required in single-portal mode "
                "(or set LM_MULTI_PORTAL=true to select portals at runtime)"
            )

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

    @model_validator(mode="after")
    def validate_http_exposure(self) -> "LMConfig":
        """Refuse an HTTP bind that other hosts can reach without authentication.

        stdio never binds, so only the HTTP transport is checked. A bind outside
        _LOOPBACK_HOSTS needs LM_HTTP_AUTH_TOKEN, or LM_HTTP_ALLOW_UNAUTHENTICATED
        set on purpose for a listener protected some other way.
        """
        if (
            self.transport == "http"
            and self.http_host.lower() not in _LOOPBACK_HOSTS
            and not self.http_auth_token
            and not self.http_allow_unauthenticated
        ):
            raise ValueError(
                f"Refusing an unauthenticated HTTP bind on {self.http_host}: set "
                "LM_HTTP_AUTH_TOKEN, bind LM_HTTP_HOST to loopback, or set "
                "LM_HTTP_ALLOW_UNAUTHENTICATED=true to accept the exposure"
            )
        return self

    @property
    def has_lmv1_auth(self) -> bool:
        """Check if LMv1 credentials are configured."""
        return bool(self.access_id and self.access_key)

    @property
    def base_url(self) -> str:
        """Return the base URL for LogicMonitor REST API."""
        if not self.portal:
            raise ValueError("no portal set (multi-portal mode: select a portal via use_portal)")
        return f"https://{self.portal}/santaba/rest"

    @property
    def ingest_url(self) -> str:
        """Return the base URL for LogicMonitor ingestion APIs.

        Ingestion APIs (logs, metrics) use a different path structure
        than the standard REST API.
        """
        if not self.portal:
            raise ValueError("no portal set (multi-portal mode: select a portal via use_portal)")
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

    @property
    def http_host_allowlist(self) -> frozenset[str]:
        """Lowercased Host names answered on every route except /healthz and /readyz.

        The loopback names, LM_HTTP_HOST unless it is a wildcard address (no client
        addresses a server as 0.0.0.0, and some browsers route that name to the
        local host), and each LM_HTTP_ALLOWED_HOSTS entry.
        """
        hosts = set(_LOOPBACK_HOSTS)
        if self.http_host not in _WILDCARD_HOSTS:
            hosts.add(self.http_host.lower())
        hosts.update(h.strip().lower() for h in self.http_allowed_hosts.split(",") if h.strip())
        return frozenset(hosts)
