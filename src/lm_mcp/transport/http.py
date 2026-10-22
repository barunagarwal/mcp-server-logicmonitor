# Description: HTTP transport implementation for MCP server.
# Description: Uses Starlette and Uvicorn for streamable HTTP mode.

from __future__ import annotations

import asyncio
import json
import logging
import secrets
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from starlette.applications import Starlette
    from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

# Probe and info routes stay reachable without a token so orchestration works
# out of the box: their bodies carry no LM data, only component status. (Probes
# *can* send headers -- Kubernetes httpGet takes httpHeaders and curl takes -H --
# so an operator who wants them gated can front them with a proxy.) Only /health
# reaches the LM API, and only for a caller that passes the bearer check (or on a
# server with no token configured) when LM_HEALTH_CHECK_CONNECTIVITY is enabled.
_OPEN_PATHS = frozenset({"/", "/health", "/healthz", "/readyz"})


def _is_open_path(path: str) -> bool:
    """Match the probe allowlist, tolerating a trailing slash.

    Starlette redirects /healthz/ to /healthz, but that redirect never runs when
    auth rejects the request first, so a probe written with a trailing slash
    would start failing the moment a token is configured. Only exact members and
    their trailing-slash forms match; everything else stays gated.
    """
    return path in _OPEN_PATHS or path.rstrip("/") in _OPEN_PATHS


def _bearer_matches(headers: Iterable[tuple[bytes, bytes]], token: bytes) -> bool:
    """Return True when the ASGI headers carry ``Authorization: Bearer <token>``.

    Shared by the auth middleware and the /health connectivity gate so both
    accept exactly the same credentials.
    """
    provided = b""
    for name, value in headers:
        if name == b"authorization":
            provided = value
            break

    # RFC 7235 defines auth-scheme as case-insensitive. Only the credentials
    # are secret, so only they get the constant-time comparison; a missing or
    # malformed header degrades to comparing against empty bytes.
    scheme, _, credentials = provided.partition(b" ")
    return scheme.lower() == b"bearer" and secrets.compare_digest(credentials, token)


class BearerAuthMiddleware:
    """Require a bearer token on every route outside _OPEN_PATHS.

    Installed only when LM_HTTP_AUTH_TOKEN is configured. The allowlist is
    deliberate: any route added later is authenticated by default rather than
    silently exposed. Written as raw ASGI so this module keeps its runtime
    imports free of starlette, matching the rest of the transport.
    """

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self._token = token.encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or _is_open_path(scope["path"]):
            await self.app(scope, receive, send)
            return

        if _bearer_matches(scope.get("headers", []), self._token):
            await self.app(scope, receive, send)
            return

        body = json.dumps({"error": "Unauthorized"}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"www-authenticate", b"Bearer"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def create_asgi_app() -> Starlette:
    """Create the ASGI application with MCP and health endpoints.

    Returns:
        Starlette application configured with routes and middleware.
    """
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.middleware.cors import CORSMiddleware
    from starlette.requests import Request
    from starlette.responses import JSONResponse, Response
    from starlette.routing import Route

    from lm_mcp.config import get_config

    config = get_config()

    async def health(request: Request) -> Response:
        """Detailed health check endpoint.

        Adds the LM API connectivity check when LM_HEALTH_CHECK_CONNECTIVITY is on
        and the caller could also reach /mcp: no inbound token is configured, or the
        request carries it. /health is an open path, so anonymous callers get the
        local checks only and cannot spend the portal's API quota.
        """
        from lm_mcp.health import run_health_checks

        include_connectivity = config.health_check_connectivity and (
            not config.http_auth_token
            or _bearer_matches(request.scope["headers"], config.http_auth_token.encode())
        )
        result = await run_health_checks(include_connectivity=include_connectivity)
        status_code = 200 if result.status == "healthy" else 503
        return JSONResponse(result.to_dict(), status_code=status_code)

    async def healthz(request: Request) -> Response:
        """Kubernetes liveness probe endpoint."""
        from lm_mcp.health import run_health_checks

        result = await run_health_checks(include_connectivity=False)
        if result.status == "unhealthy":
            return Response(content="unhealthy", status_code=503)
        return Response(content="ok", status_code=200)

    async def readyz(request: Request) -> Response:
        """Kubernetes readiness probe endpoint.

        Never calls the LM API: probes are unauthenticated and frequent, and a
        connectivity failure grades ``warn``, which could not change this response.
        """
        from lm_mcp.health import run_health_checks

        result = await run_health_checks(include_connectivity=False)
        if result.status == "unhealthy":
            return Response(content="not ready", status_code=503)
        return Response(content="ready", status_code=200)

    def rpc_error(code: int, message: str, req_id: object, status_code: int = 400) -> Response:
        """Build a JSON-RPC 2.0 error response."""
        return JSONResponse(
            {"jsonrpc": "2.0", "error": {"code": code, "message": message}, "id": req_id},
            status_code=status_code,
        )

    async def mcp_endpoint(request: Request) -> Response:
        """MCP JSON-RPC endpoint for tool calls.

        Delegates tool execution to the shared execute_tool middleware,
        ensuring consistent behavior (filtering, validation, audit logging,
        session recording) across stdio and HTTP transports. tools/call
        arguments are checked against the tool's input schema first, so a
        malformed call never reaches a handler.
        """
        import jsonschema

        from lm_mcp.registry import AWX_TOOLS, TF_TOOLS, TOOLS, WATSONX_TOOLS
        from lm_mcp.server import (
            _awx_client,
            _filter_tools,
            _tf_runner,
            _watsonx_client,
            execute_tool,
        )

        try:
            body = await request.json()
        except json.JSONDecodeError:
            return rpc_error(-32700, "Parse error", None)

        req_id = None
        try:
            if not isinstance(body, dict):
                return rpc_error(-32600, "Invalid Request", None)

            method = body.get("method")
            params = body.get("params", {})
            req_id = body.get("id")
            if not isinstance(params, dict):
                return rpc_error(-32602, "Invalid params: params must be an object", req_id)

            # The tools this server can dispatch, before operator filters.
            all_tools = list(TOOLS)
            if _awx_client is not None:
                all_tools.extend(AWX_TOOLS)
            if _watsonx_client is not None:
                all_tools.extend(WATSONX_TOOLS)
            if _tf_runner is not None:
                all_tools.extend(TF_TOOLS)

            if method == "tools/list":
                filtered = _filter_tools(all_tools, config)
                result = [{"name": t.name, "description": t.description} for t in filtered]
                return JSONResponse({"jsonrpc": "2.0", "result": result, "id": req_id})

            elif method == "tools/call":
                tool_name = params.get("name")
                arguments = params.get("arguments", {})

                if not tool_name:
                    return rpc_error(-32602, "Missing tool name", req_id)

                # A name outside the manifest goes to execute_tool, which owns the
                # unknown-tool and integration-not-configured refusals.
                tool = next((t for t in all_tools if t.name == tool_name), None)
                if tool is not None:
                    try:
                        jsonschema.validate(arguments, tool.inputSchema)
                    except jsonschema.ValidationError as e:
                        message = f"Invalid arguments for {tool_name}: {e.message}"
                        location = "/".join(str(part) for part in e.absolute_path)
                        if location:
                            message += f" (at {location})"
                        return rpc_error(-32602, message, req_id)

                result = await execute_tool(tool_name, arguments)

                # Extract text content from result
                if result and len(result) > 0:
                    text = result[0].text
                    try:
                        content = json.loads(text)
                    except json.JSONDecodeError:
                        content = text
                else:
                    content = None

                return JSONResponse({"jsonrpc": "2.0", "result": content, "id": req_id})

            elif method == "resources/list":
                from lm_mcp.resources import RESOURCES

                result = [{"uri": str(r.uri), "name": r.name} for r in RESOURCES]
                return JSONResponse({"jsonrpc": "2.0", "result": result, "id": req_id})

            elif method == "prompts/list":
                from lm_mcp.prompts import PROMPTS

                result = [{"name": p.name, "description": p.description} for p in PROMPTS]
                return JSONResponse({"jsonrpc": "2.0", "result": result, "id": req_id})

            else:
                return rpc_error(-32601, f"Method not found: {method}", req_id)

        # Exception text can carry internal state (URLs, credentials in a DSN), so
        # the caller gets a fixed message and the traceback goes to the log.
        except ValueError:
            logger.exception("Invalid params in MCP request")
            return rpc_error(-32602, "Invalid params", req_id)
        except Exception:
            logger.exception("Error handling MCP request")
            return rpc_error(-32603, "Internal error", req_id, status_code=500)

    # Analysis store (shared across requests within the ASGI app)
    from lm_mcp.analysis import AnalysisStore, run_analysis, validate_workflow

    analysis_store = AnalysisStore(ttl_minutes=60)
    # Hold references to background tasks to prevent garbage collection (RUF006)
    _background_tasks: set[asyncio.Task] = set()  # type: ignore[type-arg]

    async def post_analyze(request: Request) -> Response:
        """Start an analysis workflow.

        Accepts JSON body with 'workflow' and 'arguments' fields.
        Returns 202 with analysis_id for async polling.
        """
        try:
            body = await request.json()
        except (json.JSONDecodeError, Exception):
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        workflow = body.get("workflow")
        if not workflow:
            return JSONResponse({"error": "Missing 'workflow' field"}, status_code=400)

        try:
            validate_workflow(workflow)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)

        arguments = body.get("arguments", {})
        req = analysis_store.create(workflow, arguments)

        # Run analysis in background
        task = asyncio.create_task(run_analysis(analysis_store, req.id))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

        return JSONResponse(
            {"analysis_id": req.id, "status": "pending"},
            status_code=202,
        )

    async def get_analysis(request: Request) -> Response:
        """Poll analysis status and results.

        Returns the current state of an analysis request.
        """
        analysis_id = request.path_params["analysis_id"]
        req = analysis_store.get(analysis_id)

        if req is None:
            return JSONResponse({"error": "Analysis not found"}, status_code=404)

        return JSONResponse(req.to_dict())

    async def webhook_alert(request: Request) -> Response:
        """Receive LM alert webhook and trigger RCA workflow.

        Accepts alert payload and starts an automatic RCA analysis.
        """
        try:
            body = await request.json()
        except (json.JSONDecodeError, Exception):
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        # Extract alert context for RCA
        device_id = body.get("deviceId")
        alert_id = body.get("alertId")
        arguments = {
            "hours_back": 4,
        }
        if device_id:
            arguments["device_id"] = device_id
        if alert_id:
            arguments["alert_id"] = alert_id

        req = analysis_store.create("rca_workflow", arguments)
        task = asyncio.create_task(run_analysis(analysis_store, req.id))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

        return JSONResponse(
            {"analysis_id": req.id, "status": "pending"},
            status_code=202,
        )

    async def root(request: Request) -> Response:
        """Root endpoint with server info."""
        from lm_mcp import __version__

        return JSONResponse(
            {
                "name": "LogicMonitor MCP Server",
                "version": __version__,
                "transport": "http",
                "endpoints": {
                    "mcp": "/mcp",
                    "health": "/health",
                    "healthz": "/healthz",
                    "readyz": "/readyz",
                    "analyze": "/api/v1/analyze",
                    "analysis": "/api/v1/analysis/{id}",
                    "webhook_alert": "/api/v1/webhooks/alert",
                },
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

    routes = [
        Route("/", root, methods=["GET"]),
        Route("/mcp", mcp_endpoint, methods=["POST"]),
        Route("/health", health, methods=["GET"]),
        Route("/healthz", healthz, methods=["GET"]),
        Route("/readyz", readyz, methods=["GET"]),
        Route("/api/v1/analyze", post_analyze, methods=["POST"]),
        Route("/api/v1/analysis/{analysis_id}", get_analysis, methods=["GET"]),
        Route("/api/v1/webhooks/alert", webhook_alert, methods=["POST"]),
    ]

    # Configure CORS middleware. Order matters: the first entry is outermost,
    # so CORS answers preflights before auth runs -- browsers cannot attach a
    # token to a preflight, and 401s still get CORS headers so JS can read them.
    cors_origins = config.cors_origins_list
    middleware = []
    if cors_origins:
        middleware.append(
            Middleware(
                CORSMiddleware,
                allow_origins=cors_origins,
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
            )
        )

    if config.http_auth_token:
        middleware.append(Middleware(BearerAuthMiddleware, token=config.http_auth_token))
    else:
        logger.warning(
            "Inbound HTTP authentication is disabled; /mcp and /api/v1/* accept "
            "unauthenticated requests. Set LM_HTTP_AUTH_TOKEN to require a bearer token."
        )

    return Starlette(routes=routes, middleware=middleware)


async def create_http_server() -> None:
    """Create and run the HTTP server.

    Initializes the LogicMonitor client and starts Uvicorn.
    """
    import uvicorn

    from lm_mcp.auth import create_auth_provider
    from lm_mcp.client import LogicMonitorClient
    from lm_mcp.config import get_config
    from lm_mcp.server import _set_awx_client, _set_client, _set_tf_runner, _set_watsonx_client
    from lm_mcp.session import get_session

    # Load config. Multi-portal mode is stdio-only and is rejected at config
    # construction, so the HTTP transport always binds a fixed client at startup.
    config = get_config()
    auth = create_auth_provider(config)
    client = LogicMonitorClient(
        base_url=config.base_url,
        auth=auth,
        timeout=config.timeout,
        api_version=config.api_version,
        max_retries=config.max_retries,
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
            logger.warning(
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
                logger.warning(
                    "torch/transformers not installed; HuggingFace fallback disabled. "
                    "Install with: uv add 'lm-mcp[huggingface]'"
                )

    # Initialize Terraform runner if configured
    tf_runner = None
    from lm_mcp.terraform_config import get_terraform_config

    tf_config = get_terraform_config()
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

    # Create ASGI app
    app = create_asgi_app()

    # Configure Uvicorn (with optional TLS)
    ssl_kwargs: dict = {}
    if config.http_ssl_certfile:
        ssl_kwargs["ssl_certfile"] = config.http_ssl_certfile
    if config.http_ssl_keyfile:
        ssl_kwargs["ssl_keyfile"] = config.http_ssl_keyfile
    if config.http_ssl_keyfile_password:
        ssl_kwargs["ssl_keyfile_password"] = config.http_ssl_keyfile_password

    uvicorn_config = uvicorn.Config(
        app,
        host=config.http_host,
        port=config.http_port,
        log_level="info",
        **ssl_kwargs,
    )

    server = uvicorn.Server(uvicorn_config)

    scheme = "https" if config.http_ssl_certfile else "http"
    logger.info(f"Starting {scheme} server on {config.http_host}:{config.http_port}")

    try:
        await server.serve()
    finally:
        if tf_runner is not None:
            await tf_runner.close()
        if watsonx_client is not None:
            await watsonx_client.close()
        if awx_client is not None:
            await awx_client.close()
        if client is not None:
            await client.close()
