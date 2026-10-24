# Description: Optional-backend setup shared by the stdio and HTTP transports.
# Description: Builds and registers the AWX, watsonx or HuggingFace, and Terraform clients.

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lm_mcp.client.awx import AwxClient
    from lm_mcp.client.huggingface import HuggingFaceClient
    from lm_mcp.client.terraform import TerraformRunner
    from lm_mcp.client.watsonx import WatsonxClient
    from lm_mcp.config import LMConfig

logger = logging.getLogger(__name__)


@dataclass
class Backends:
    """The optional backends a transport built, closed by that transport at shutdown."""

    awx: AwxClient | None = None
    watsonx: WatsonxClient | HuggingFaceClient | None = None
    terraform: TerraformRunner | None = None

    async def close(self) -> None:
        """Close every backend that was built."""
        if self.terraform is not None:
            await self.terraform.close()
        if self.watsonx is not None:
            await self.watsonx.close()
        if self.awx is not None:
            await self.awx.close()


def bootstrap_backends(config: LMConfig) -> Backends:
    """Build the optional backends that are configured and register them with the server.

    Each backend is absent unless its configuration loads: AWX needs AWX_URL and
    AWX_TOKEN, watsonx needs WATSONX_API_KEY, the HuggingFace fallback stands in
    when watsonx is not configured and torch is installed, and Terraform needs
    TF_WORKSPACE_DIR outside multi-portal mode.

    Args:
        config: The LogicMonitor server configuration.

    Returns:
        The backends built, for the transport to close at shutdown.
    """
    from lm_mcp.server import _set_awx_client, _set_tf_runner, _set_watsonx_client

    backends = Backends()

    from lm_mcp.awx_config import get_awx_config

    awx_config = get_awx_config()
    if awx_config is not None:
        from lm_mcp.client.awx import AwxClient

        backends.awx = AwxClient(
            base_url=awx_config.url,
            token=awx_config.token,
            timeout=awx_config.timeout,
            max_retries=awx_config.max_retries,
            verify_ssl=awx_config.verify_ssl,
        )
        _set_awx_client(backends.awx)

    from lm_mcp.ibm_config import get_watsonx_config

    watsonx_config = get_watsonx_config()
    if watsonx_config is not None:
        try:
            from lm_mcp.client.watsonx import WatsonxClient

            backends.watsonx = WatsonxClient(
                api_key=watsonx_config.api_key,
                url=watsonx_config.url,
                project_id=watsonx_config.project_id,
                timeout=watsonx_config.timeout,
            )
            _set_watsonx_client(backends.watsonx)
        except ImportError:
            logger.warning(
                "ibm-watsonx-ai not installed; watsonx tools disabled. "
                "Install with: uv add 'lm-mcp[ibm]'"
            )
        except Exception:
            # The SDK's APIClient fetches an IAM token on construction, so a bad key
            # or an unreachable IAM endpoint fails here; the LM server serves without it.
            logger.exception(
                "watsonx client construction failed; watsonx tools disabled. "
                "Check WATSONX_API_KEY, WATSONX_URL and WATSONX_PROJECT_ID."
            )

    # HuggingFace local fallback when watsonx API is not configured
    if backends.watsonx is None:
        from lm_mcp.hf_config import get_hf_config

        hf_config = get_hf_config()
        if hf_config is not None:
            try:
                from lm_mcp.client.huggingface import HuggingFaceClient

                backends.watsonx = HuggingFaceClient(
                    ttm_model=hf_config.ttm_model,
                    llm_model=hf_config.llm_model,
                    device=hf_config.device,
                    cache_dir=hf_config.cache_dir,
                )
                _set_watsonx_client(backends.watsonx)
            except ImportError:
                logger.warning(
                    "torch/transformers not installed; HuggingFace fallback disabled. "
                    "Install with: uv add 'lm-mcp[huggingface]'"
                )

    # Skipped in multi-portal mode: the LM Terraform provider needs fixed LM_*
    # credentials, which multi-portal selects at runtime, so the tools would run
    # unauthenticated.
    from lm_mcp.terraform_config import get_terraform_config

    tf_config = get_terraform_config()
    if tf_config is not None and config.multi_portal:
        logger.warning(
            "Terraform tools are disabled in multi-portal mode; "
            "run a single-portal server for Terraform."
        )
        tf_config = None
    if tf_config is not None:
        from lm_mcp.client.terraform import TerraformRunner

        backends.terraform = TerraformRunner(
            workspace_dir=tf_config.workspace_dir,
            terraform_binary=tf_config.terraform_binary,
            timeout=tf_config.timeout,
            auto_approve_enabled=tf_config.auto_approve_enabled,
        )
        _set_tf_runner(backends.terraform)

    return backends
