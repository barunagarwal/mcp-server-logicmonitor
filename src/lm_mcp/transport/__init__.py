# Description: Transport abstraction layer for MCP server.
# Description: Supports stdio (default) and HTTP transports.

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lm_mcp.config import LMConfig

__all__ = ["get_transport_runner", "run_http", "run_stdio"]


async def run_stdio() -> None:
    """Run the MCP server with stdio transport.

    This is the default transport for local AI assistant integration.
    The server communicates via stdin/stdout using JSON-RPC messages.
    """
    from mcp import stdio_server

    from lm_mcp.auth import create_auth_provider
    from lm_mcp.client import LogicMonitorClient
    from lm_mcp.config import get_config
    from lm_mcp.server import (
        _set_awx_client,
        _set_client,
        _set_tf_runner,
        _set_watsonx_client,
        server,
    )
    from lm_mcp.session import get_session

    # Load config. In multi-portal mode client creation is deferred to use_portal.
    config = get_config()
    client = None
    if config.multi_portal:
        from lm_mcp import portals

        portals.load()
    else:
        auth = create_auth_provider(config)
        client = LogicMonitorClient(
            base_url=config.base_url,
            auth=auth,
            timeout=config.timeout,
            api_version=config.api_version,
            max_retries=config.max_retries,
            retry_after_cap=config.retry_after_cap_seconds,
            ingest_url=config.ingest_url,
        )
        _set_client(client)

    # Initialize AWX client if configured
    awx_client = None
    from lm_mcp.awx_config import get_awx_config

    awx_config = get_awx_config()
    if awx_config is not None:
        from lm_mcp.client.awx import AwxClient

        awx_client = AwxClient(
            base_url=awx_config.url,
            token=awx_config.token,
            timeout=awx_config.timeout,
            max_retries=awx_config.max_retries,
            verify_ssl=awx_config.verify_ssl,
        )
        _set_awx_client(awx_client)

    # Initialize watsonx client if configured
    watsonx_client = None
    from lm_mcp.ibm_config import get_watsonx_config

    watsonx_config = get_watsonx_config()
    if watsonx_config is not None:
        try:
            from lm_mcp.client.watsonx import WatsonxClient

            watsonx_client = WatsonxClient(
                api_key=watsonx_config.api_key,
                url=watsonx_config.url,
                project_id=watsonx_config.project_id,
                timeout=watsonx_config.timeout,
            )
            _set_watsonx_client(watsonx_client)
        except ImportError:
            logging.getLogger(__name__).warning(
                "ibm-watsonx-ai not installed; watsonx tools disabled. "
                "Install with: uv add 'lm-mcp[ibm]'"
            )

    # HuggingFace local fallback when watsonx API is not configured
    if watsonx_client is None:
        from lm_mcp.hf_config import get_hf_config

        hf_config = get_hf_config()
        if hf_config is not None:
            try:
                from lm_mcp.client.huggingface import HuggingFaceClient

                watsonx_client = HuggingFaceClient(
                    ttm_model=hf_config.ttm_model,
                    llm_model=hf_config.llm_model,
                    device=hf_config.device,
                    cache_dir=hf_config.cache_dir,
                )
                _set_watsonx_client(watsonx_client)
            except ImportError:
                logging.getLogger(__name__).warning(
                    "torch/transformers not installed; HuggingFace fallback disabled. "
                    "Install with: uv add 'lm-mcp[huggingface]'"
                )

    # Initialize Terraform runner if configured. Skipped in multi-portal mode:
    # the LM Terraform provider needs fixed LM_* credentials, which multi-portal
    # selects at runtime, so the tools would run unauthenticated.
    tf_runner = None
    from lm_mcp.terraform_config import get_terraform_config

    tf_config = get_terraform_config()
    if tf_config is not None and config.multi_portal:
        logging.getLogger(__name__).warning(
            "Terraform tools are disabled in multi-portal mode; "
            "run a single-portal server for Terraform."
        )
        tf_config = None
    if tf_config is not None:
        from lm_mcp.client.terraform import TerraformRunner

        tf_runner = TerraformRunner(
            workspace_dir=tf_config.workspace_dir,
            terraform_binary=tf_config.terraform_binary,
            timeout=tf_config.timeout,
            auto_approve_enabled=tf_config.auto_approve_enabled,
        )
        _set_tf_runner(tf_runner)

    # Initialize session with config settings
    if config.session_enabled:
        session = get_session()
        session.max_history_size = config.session_history_size

    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
    finally:
        if tf_runner is not None:
            await tf_runner.close()
        if watsonx_client is not None:
            await watsonx_client.close()
        if awx_client is not None:
            await awx_client.close()
        if client is not None:
            await client.close()
        from lm_mcp import portals

        await portals.close_all()


async def run_http() -> None:
    """Run the MCP server with HTTP transport.

    This transport is for remote deployments and shared access.
    Requires the 'http' optional dependencies: starlette, uvicorn.
    """
    try:
        from lm_mcp.transport.http import create_http_server
    except ImportError as e:
        raise ImportError(
            "HTTP transport requires additional dependencies. "
            "Install with: pip install lm-mcp[http]"
        ) from e

    await create_http_server()


def get_transport_runner(config: LMConfig) -> Callable[[], Coroutine]:
    """Get the transport runner based on configuration.

    Args:
        config: Server configuration with transport setting.

    Returns:
        Async function to run the server with selected transport.

    Raises:
        ValueError: If transport type is not supported.
    """
    if config.transport == "stdio":
        return run_stdio
    elif config.transport == "http":
        return run_http
    else:
        raise ValueError(f"Unsupported transport: {config.transport}")
