# Description: Configuration for HuggingFace local Granite model fallback.
# Description: Loads model settings from environment variables with HF_ prefix.

from __future__ import annotations

from pydantic_settings import BaseSettings

from lm_mcp.config_warnings import log_unusable_config

_cached_hf_config: HuggingFaceConfig | None = None


def get_hf_config() -> HuggingFaceConfig | None:
    """Get the cached HuggingFaceConfig singleton.

    Returns None if torch is not installed (the natural gate). Installing
    lm-mcp[huggingface] provides torch. When torch is absent, HuggingFace
    tools are silently excluded and the server falls back to statistical methods.
    """
    global _cached_hf_config
    if _cached_hf_config is None:
        try:
            import torch  # noqa: F401 -- presence check only
        except ImportError:
            return None
        try:
            _cached_hf_config = HuggingFaceConfig()
        except Exception as exc:
            log_unusable_config("HuggingFace fallback", HuggingFaceConfig, exc, gate=None)
            return None
    return _cached_hf_config


def reset_hf_config() -> None:
    """Clear the cached config. Used in tests to reset state."""
    global _cached_hf_config
    _cached_hf_config = None


class HuggingFaceConfig(BaseSettings):
    """Configuration for local Granite model inference via HuggingFace.

    All fields have defaults so the config always constructs if torch is
    installed. The gate is torch availability, not env var presence.
    Used as a fallback when watsonx.ai API credentials are not configured.
    """

    ttm_model: str = "ibm-granite/granite-timeseries-ttm-r2"  # HF_TTM_MODEL
    llm_model: str = "ibm-granite/granite-3.3-2b-instruct"  # HF_LLM_MODEL
    device: str = "auto"  # HF_DEVICE (cpu, cuda, mps, auto)
    cache_dir: str | None = None  # HF_CACHE_DIR

    model_config = {"env_prefix": "HF_"}
