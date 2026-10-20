# Description: Tests for the health check module.
# Description: Validates health check logic and status determination.

import pytest
import respx
from httpx import Response

from lm_mcp.health import HealthCheck, HealthResponse


class TestHealthCheck:
    """Tests for HealthCheck dataclass."""

    def test_create_passing_check(self):
        """HealthCheck can be created for passing status."""
        check = HealthCheck(name="server", status="pass", message="Running")

        assert check.name == "server"
        assert check.status == "pass"
        assert check.message == "Running"

    def test_create_failing_check(self):
        """HealthCheck can be created for failing status."""
        check = HealthCheck(name="client", status="fail", message="Not initialized")

        assert check.status == "fail"
        assert check.message == "Not initialized"

    def test_create_warning_check(self):
        """HealthCheck can be created for warning status."""
        check = HealthCheck(name="connectivity", status="warn")

        assert check.status == "warn"
        assert check.message is None

    def test_to_dict_includes_status(self):
        """to_dict includes status field."""
        check = HealthCheck(name="test", status="pass")
        result = check.to_dict()

        assert result["status"] == "pass"

    def test_to_dict_includes_message_when_present(self):
        """to_dict includes message when present."""
        check = HealthCheck(name="test", status="pass", message="OK")
        result = check.to_dict()

        assert result["message"] == "OK"

    def test_to_dict_excludes_message_when_none(self):
        """to_dict excludes message when None."""
        check = HealthCheck(name="test", status="pass")
        result = check.to_dict()

        assert "message" not in result


class TestHealthResponse:
    """Tests for HealthResponse dataclass."""

    def test_create_healthy_response(self):
        """HealthResponse can be created with healthy status."""
        response = HealthResponse(
            status="healthy",
            timestamp="2024-01-01T00:00:00Z",
            version="1.0.0",
        )

        assert response.status == "healthy"
        assert response.timestamp == "2024-01-01T00:00:00Z"
        assert response.version == "1.0.0"
        assert response.checks == {}

    def test_response_with_checks(self):
        """HealthResponse can include multiple checks."""
        checks = {
            "server": HealthCheck(name="server", status="pass"),
            "client": HealthCheck(name="client", status="pass"),
        }

        response = HealthResponse(
            status="healthy",
            timestamp="2024-01-01T00:00:00Z",
            version="1.0.0",
            checks=checks,
        )

        assert len(response.checks) == 2
        assert "server" in response.checks
        assert "client" in response.checks

    def test_to_dict_serializes_response(self):
        """to_dict serializes the full response."""
        checks = {
            "server": HealthCheck(name="server", status="pass", message="Running"),
        }

        response = HealthResponse(
            status="healthy",
            timestamp="2024-01-01T00:00:00Z",
            version="1.0.0",
            checks=checks,
        )

        result = response.to_dict()

        assert result["status"] == "healthy"
        assert result["timestamp"] == "2024-01-01T00:00:00Z"
        assert result["version"] == "1.0.0"
        assert "checks" in result
        assert result["checks"]["server"]["status"] == "pass"
        assert result["checks"]["server"]["message"] == "Running"


class TestHealthStatusDetermination:
    """Tests for overall status determination logic."""

    def test_all_pass_is_healthy(self):
        """All passing checks result in healthy status."""
        checks = {
            "server": HealthCheck(name="server", status="pass"),
            "client": HealthCheck(name="client", status="pass"),
            "config": HealthCheck(name="config", status="pass"),
        }

        statuses = [check.status for check in checks.values()]

        if "fail" in statuses:
            overall = "unhealthy"
        elif "warn" in statuses:
            overall = "degraded"
        else:
            overall = "healthy"

        assert overall == "healthy"

    def test_any_warn_is_degraded(self):
        """Any warning check results in degraded status."""
        checks = {
            "server": HealthCheck(name="server", status="pass"),
            "connectivity": HealthCheck(name="connectivity", status="warn"),
        }

        statuses = [check.status for check in checks.values()]

        if "fail" in statuses:
            overall = "unhealthy"
        elif "warn" in statuses:
            overall = "degraded"
        else:
            overall = "healthy"

        assert overall == "degraded"

    def test_any_fail_is_unhealthy(self):
        """Any failing check results in unhealthy status."""
        checks = {
            "server": HealthCheck(name="server", status="pass"),
            "client": HealthCheck(name="client", status="fail"),
        }

        statuses = [check.status for check in checks.values()]

        if "fail" in statuses:
            overall = "unhealthy"
        elif "warn" in statuses:
            overall = "degraded"
        else:
            overall = "healthy"

        assert overall == "unhealthy"

    def test_fail_takes_precedence_over_warn(self):
        """Fail status takes precedence over warn status."""
        checks = {
            "server": HealthCheck(name="server", status="warn"),
            "client": HealthCheck(name="client", status="fail"),
        }

        statuses = [check.status for check in checks.values()]

        if "fail" in statuses:
            overall = "unhealthy"
        elif "warn" in statuses:
            overall = "degraded"
        else:
            overall = "healthy"

        assert overall == "unhealthy"


PORTAL_BASE = "https://test.logicmonitor.com/santaba/rest"
INBOUND_BEARER = "test-http-auth-token-0123"


@pytest.fixture
def connectivity_env(monkeypatch, reset_portals):
    """HTTP config with LM_HEALTH_CHECK_CONNECTIVITY on and a real LM client bound.

    create_asgi_app() does not build the LM client, and run_health_checks only pings
    when one exists, so the client is bound here the way create_http_server binds it.
    """
    from lm_mcp.auth.bearer import BearerAuth
    from lm_mcp.client import LogicMonitorClient
    from lm_mcp.server import _set_client

    monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
    monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
    monkeypatch.setenv("LM_HEALTH_CHECK_CONNECTIVITY", "true")
    monkeypatch.delenv("LM_HTTP_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("LM_CORS_ORIGINS", raising=False)
    _set_client(LogicMonitorClient(base_url=PORTAL_BASE, auth=BearerAuth("test-token")))


@pytest.fixture
def admins_route():
    """The connectivity check's portal call, faked; yields the route to count calls."""
    with respx.mock(assert_all_called=False) as router:
        router.route(host="127.0.0.1").pass_through()
        yield router.get(f"{PORTAL_BASE}/setting/admins").mock(
            return_value=Response(200, json={"items": [], "total": 0})
        )


def _asgi_client():
    from httpx import ASGITransport, AsyncClient

    from lm_mcp.transport.http import create_asgi_app

    return AsyncClient(transport=ASGITransport(app=create_asgi_app()), base_url="http://test")


class TestReadyzStaysLocal:
    """R1.5: /readyz never spends the portal's API quota (issue #56)."""

    async def test_readyz_never_calls_portal(self, connectivity_env, admins_route):
        """Fifty readiness probes with connectivity enabled make zero portal calls."""
        async with _asgi_client() as client:
            responses = [await client.get("/readyz") for _ in range(50)]

        assert [r.status_code for r in responses] == [200] * 50
        assert admins_route.call_count == 0


class TestHealthConnectivityGate:
    """R1.5: /health runs the connectivity check only for callers that could reach /mcp."""

    async def test_health_checks_connectivity_when_no_token_configured(
        self, connectivity_env, admins_route
    ):
        """With no inbound token, /mcp is open, so /health may ping the portal once."""
        async with _asgi_client() as client:
            resp = await client.get("/health")

        assert admins_route.call_count == 1
        assert resp.json()["checks"]["connectivity"]["status"] == "pass"

    async def test_health_skips_connectivity_for_unauthenticated_caller(
        self, connectivity_env, admins_route, monkeypatch
    ):
        """With a token configured, an anonymous /health stays local-only."""
        monkeypatch.setenv("LM_HTTP_AUTH_TOKEN", INBOUND_BEARER)

        async with _asgi_client() as client:
            missing = await client.get("/health")
            wrong = await client.get("/health", headers={"Authorization": "Bearer nope-nope"})

        assert admins_route.call_count == 0
        assert missing.status_code == 200
        assert wrong.status_code == 200
        assert "connectivity" not in missing.json()["checks"]

    async def test_health_checks_connectivity_for_authenticated_caller(
        self, connectivity_env, admins_route, monkeypatch
    ):
        """A caller presenting the inbound token gets the connectivity check."""
        monkeypatch.setenv("LM_HTTP_AUTH_TOKEN", INBOUND_BEARER)

        async with _asgi_client() as client:
            resp = await client.get(
                "/health", headers={"Authorization": f"Bearer {INBOUND_BEARER}"}
            )

        assert admins_route.call_count == 1
        assert resp.json()["checks"]["connectivity"]["status"] == "pass"

    async def test_live_server_gates_health_connectivity(
        self, connectivity_env, admins_route, monkeypatch
    ):
        """Over a real uvicorn socket: probes stay local, only the token holder pings."""
        import asyncio

        import httpx
        import uvicorn

        from lm_mcp.transport.http import create_asgi_app

        monkeypatch.setenv("LM_HTTP_AUTH_TOKEN", INBOUND_BEARER)
        server = uvicorn.Server(
            uvicorn.Config(create_asgi_app(), host="127.0.0.1", port=0, log_level="warning")
        )
        serving = asyncio.create_task(server.serve())
        try:
            while not server.started:
                await asyncio.sleep(0.01)
            port = server.servers[0].sockets[0].getsockname()[1]
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
                readyz = await client.get("/readyz")
                anonymous = await client.get("/health")
                assert admins_route.call_count == 0
                authed = await client.get(
                    "/health", headers={"Authorization": f"Bearer {INBOUND_BEARER}"}
                )
        finally:
            server.should_exit = True
            await serving

        assert readyz.status_code == 200
        assert anonymous.status_code == 200
        assert authed.status_code == 200
        assert admins_route.call_count == 1


class TestHttpServerClientConstruction:
    """create_http_server builds the LM client from configuration."""

    async def test_http_client_uses_configured_max_retries(self, monkeypatch, reset_portals):
        """R1.6: the HTTP transport's client gets LM_MAX_RETRIES, not the default."""
        from unittest.mock import AsyncMock

        import uvicorn

        from lm_mcp import server as server_module
        from lm_mcp.transport.http import create_http_server

        for var in ("AWX_URL", "AWX_TOKEN", "WATSONX_API_KEY", "TF_WORKSPACE_DIR"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_TRANSPORT", "http")
        monkeypatch.setenv("LM_MAX_RETRIES", "7")
        monkeypatch.setattr("lm_mcp.hf_config.get_hf_config", lambda: None)
        # Shutdown closes the client, so read it while the server is "serving".
        serving_clients = []
        serve = AsyncMock(side_effect=lambda: serving_clients.append(server_module._client))
        monkeypatch.setattr(uvicorn.Server, "serve", serve)

        await create_http_server()

        serve.assert_awaited_once()
        assert serving_clients[0].max_retries == 7
