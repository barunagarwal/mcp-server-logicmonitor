# Description: Configuration for Ansible Automation Platform integration.
# Description: Loads AAP credentials from environment variables with AWX_ prefix.

from __future__ import annotations

from pydantic_settings import BaseSettings

from lm_mcp.config_warnings import log_unusable_config

_cached_awx_config: AwxConfig | None = None


def get_awx_config() -> AwxConfig | None:
    """Get the cached AwxConfig singleton.

    Returns None if AWX_URL is not configured. This allows the server
    to start without AAP credentials — ansible tools are simply excluded.
    """
    global _cached_awx_config
    if _cached_awx_config is None:
        try:
            _cached_awx_config = AwxConfig()
        except Exception as exc:
            log_unusable_config("AWX", AwxConfig, exc, gate="AWX_URL")
            return None
    return _cached_awx_config


def reset_awx_config() -> None:
    """Clear the cached config. Used in tests to reset state."""
    global _cached_awx_config
    _cached_awx_config = None


class AwxConfig(BaseSettings):
    """Configuration for Ansible Automation Platform API integration.

    Compatible with AWX, Ansible Tower, and Red Hat Automation Controller.
    All fields are required unless AWX_URL is absent, in which case
    get_awx_config() returns None and ansible tools are excluded.
    """

    url: str  # AWX_URL
    token: str  # AWX_TOKEN
    verify_ssl: bool = True  # AWX_VERIFY_SSL
    timeout: int = 30  # AWX_TIMEOUT
    max_retries: int = 3  # AWX_MAX_RETRIES

    model_config = {"env_prefix": "AWX_"}
