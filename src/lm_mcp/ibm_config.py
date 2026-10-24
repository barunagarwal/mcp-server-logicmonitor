# Description: Configuration for IBM watsonx.ai and Concert integrations.
# Description: Loads credentials from environment variables with WATSONX_ and CONCERT_ prefixes.

from __future__ import annotations

from pydantic_settings import BaseSettings

from lm_mcp.config_warnings import log_unusable_config

_cached_watsonx_config: WatsonxConfig | None = None


def get_watsonx_config() -> WatsonxConfig | None:
    """Get the cached WatsonxConfig singleton.

    Returns None if WATSONX_API_KEY is not configured. This allows the server
    to start without IBM credentials -- watsonx tools are simply excluded.
    """
    global _cached_watsonx_config
    if _cached_watsonx_config is None:
        try:
            _cached_watsonx_config = WatsonxConfig()
        except Exception as exc:
            log_unusable_config("watsonx", WatsonxConfig, exc, gate="WATSONX_API_KEY")
            return None
    return _cached_watsonx_config


def reset_watsonx_config() -> None:
    """Clear the cached config. Used in tests to reset state."""
    global _cached_watsonx_config
    _cached_watsonx_config = None


class WatsonxConfig(BaseSettings):
    """Configuration for IBM watsonx.ai API integration.

    Requires an IBM Cloud API key, watsonx.ai project ID, and region URL.
    When WATSONX_API_KEY is absent, get_watsonx_config() returns None and
    watsonx tools are excluded from the server.
    """

    api_key: str  # WATSONX_API_KEY
    url: str = "https://us-south.ml.cloud.ibm.com"  # WATSONX_URL
    project_id: str  # WATSONX_PROJECT_ID
    timeout: int = 60  # WATSONX_TIMEOUT

    model_config = {"env_prefix": "WATSONX_"}
