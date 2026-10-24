# Description: Configuration for Terraform CLI integration.
# Description: Loads workspace settings from environment variables with TF_ prefix.

from __future__ import annotations

from pydantic_settings import BaseSettings

from lm_mcp.config_warnings import log_unusable_config

_cached_terraform_config: TerraformConfig | None = None


def get_terraform_config() -> TerraformConfig | None:
    """Get the cached TerraformConfig singleton.

    Returns None if TF_WORKSPACE_DIR is not configured. This allows the server
    to start without Terraform -- terraform tools are simply excluded.
    """
    global _cached_terraform_config
    if _cached_terraform_config is None:
        try:
            _cached_terraform_config = TerraformConfig()
        except Exception as exc:
            log_unusable_config("Terraform", TerraformConfig, exc, gate="TF_WORKSPACE_DIR")
            return None
    return _cached_terraform_config


def reset_terraform_config() -> None:
    """Clear the cached config. Used in tests to reset state."""
    global _cached_terraform_config
    _cached_terraform_config = None


class TerraformConfig(BaseSettings):
    """Configuration for Terraform CLI integration.

    Requires a workspace directory where Terraform workspaces are managed.
    Each workspace name maps to a subdirectory under workspace_dir.
    When TF_WORKSPACE_DIR is absent, get_terraform_config() returns None and
    terraform tools are excluded from the server.
    """

    workspace_dir: str  # TF_WORKSPACE_DIR (required -- the gate)
    terraform_binary: str = "terraform"  # TF_TERRAFORM_BINARY
    timeout: int = 300  # TF_TIMEOUT (seconds, terraform ops can be slow)
    auto_approve_enabled: bool = False  # TF_AUTO_APPROVE_ENABLED

    model_config = {"env_prefix": "TF_"}
