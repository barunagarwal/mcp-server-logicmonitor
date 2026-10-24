# Description: Tests for HTTP analysis endpoints.
# Description: Validates POST /api/v1/analyze, GET /api/v1/analysis/{id}, and webhook.

from __future__ import annotations

import pytest


@pytest.fixture
def _set_env(monkeypatch):
    """Set required environment variables for HTTP app creation."""
    monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
    monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")


class TestPostAnalyze:
    """Tests for POST /api/v1/analyze endpoint."""

    @pytest.mark.asyncio
    async def test_submit_valid_workflow(self, _set_env):
        """POST /api/v1/analyze returns 202 with analysis_id for valid workflow."""
        from httpx import ASGITransport, AsyncClient

        from lm_mcp.transport.http import create_asgi_app

        app = create_asgi_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://localhost") as client:
            resp = await client.post(
                "/api/v1/analyze",
                json={"workflow": "health_check", "arguments": {}},
            )

        assert resp.status_code == 202
        data = resp.json()
        assert "analysis_id" in data
        assert data["status"] == "pending"

    @pytest.mark.asyncio
    async def test_submit_invalid_workflow(self, _set_env):
        """POST /api/v1/analyze returns 400 for unknown workflow."""
        from httpx import ASGITransport, AsyncClient

        from lm_mcp.transport.http import create_asgi_app

        app = create_asgi_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://localhost") as client:
            resp = await client.post(
                "/api/v1/analyze",
                json={"workflow": "nonexistent", "arguments": {}},
            )

        assert resp.status_code == 400
        assert "error" in resp.json()

    @pytest.mark.asyncio
    async def test_submit_missing_body(self, _set_env):
        """POST /api/v1/analyze returns 400 for missing/invalid body."""
        from httpx import ASGITransport, AsyncClient

        from lm_mcp.transport.http import create_asgi_app

        app = create_asgi_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://localhost") as client:
            resp = await client.post(
                "/api/v1/analyze",
                content=b"not json",
                headers={"content-type": "application/json"},
            )

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_submit_missing_workflow_field(self, _set_env):
        """POST /api/v1/analyze returns 400 when workflow field is missing."""
        from httpx import ASGITransport, AsyncClient

        from lm_mcp.transport.http import create_asgi_app

        app = create_asgi_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://localhost") as client:
            resp = await client.post(
                "/api/v1/analyze",
                json={"arguments": {}},
            )

        assert resp.status_code == 400


class TestAnalysisConcurrency:
    """R4.6: LM_ANALYSIS_MAX_CONCURRENCY bounds the workflows running at once; the rest queue."""

    @pytest.fixture
    def gated_tools(self, monkeypatch):
        """Replace execute_tool with one that holds every call until the gate opens."""
        import asyncio

        from mcp.types import TextContent

        state = {"in_flight": 0, "peak": 0, "gate": asyncio.Event()}

        async def fake_execute_tool(name: str, arguments: dict) -> list[TextContent]:
            state["in_flight"] += 1
            state["peak"] = max(state["peak"], state["in_flight"])
            try:
                await state["gate"].wait()
            finally:
                state["in_flight"] -= 1
            return [TextContent(type="text", text="{}")]

        monkeypatch.setattr("lm_mcp.server.execute_tool", fake_execute_tool)
        return state

    @staticmethod
    async def _settle() -> None:
        import asyncio

        for _ in range(50):
            await asyncio.sleep(0)

    async def test_limit_bounds_running_workflows_and_queues_the_rest(
        self, _set_env, monkeypatch, gated_tools
    ):
        """With a limit of 2, three submissions run two workflows; a fourth is accepted, waits."""
        from httpx import ASGITransport, AsyncClient

        from lm_mcp.transport.http import create_asgi_app

        monkeypatch.setenv("LM_ANALYSIS_MAX_CONCURRENCY", "2")
        app = create_asgi_app()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://localhost"
        ) as client:

            async def submit() -> str:
                resp = await client.post(
                    "/api/v1/analyze", json={"workflow": "health_check", "arguments": {}}
                )
                assert resp.status_code == 202
                return resp.json()["analysis_id"]

            async def statuses(ids: list[str]) -> list[str]:
                return [
                    (await client.get(f"/api/v1/analysis/{aid}")).json()["status"] for aid in ids
                ]

            ids = [await submit() for _ in range(3)]
            await self._settle()

            assert gated_tools["in_flight"] == 2
            assert sorted(await statuses(ids)) == ["pending", "running", "running"]

            ids.append(await submit())
            await self._settle()

            assert gated_tools["in_flight"] == 2
            assert (await statuses(ids))[3] == "pending"

            gated_tools["gate"].set()
            for _ in range(20):
                await self._settle()
                if all(s == "completed" for s in await statuses(ids)):
                    break

            assert await statuses(ids) == ["completed"] * 4

        assert gated_tools["peak"] == 2


class TestGetAnalysis:
    """Tests for GET /api/v1/analysis/{id} endpoint."""

    @pytest.mark.asyncio
    async def test_get_pending_analysis(self, _set_env):
        """GET /api/v1/analysis/{id} returns pending status for new analysis."""
        from httpx import ASGITransport, AsyncClient

        from lm_mcp.transport.http import create_asgi_app

        app = create_asgi_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://localhost") as client:
            # Create an analysis first
            post_resp = await client.post(
                "/api/v1/analyze",
                json={"workflow": "health_check", "arguments": {}},
            )
            analysis_id = post_resp.json()["analysis_id"]

            # Poll for status
            get_resp = await client.get(f"/api/v1/analysis/{analysis_id}")

        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["id"] == analysis_id
        assert data["status"] in ("pending", "running", "completed", "failed")

    @pytest.mark.asyncio
    async def test_get_nonexistent_analysis(self, _set_env):
        """GET /api/v1/analysis/{id} returns 404 for unknown ID."""
        from httpx import ASGITransport, AsyncClient

        from lm_mcp.transport.http import create_asgi_app

        app = create_asgi_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://localhost") as client:
            resp = await client.get("/api/v1/analysis/nonexistent-id")

        assert resp.status_code == 404


class TestWebhookAlert:
    """Tests for POST /api/v1/webhooks/alert endpoint."""

    @pytest.mark.asyncio
    async def test_valid_alert_webhook(self, _set_env):
        """POST /api/v1/webhooks/alert returns 202 with analysis_id."""
        from httpx import ASGITransport, AsyncClient

        from lm_mcp.transport.http import create_asgi_app

        app = create_asgi_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://localhost") as client:
            resp = await client.post(
                "/api/v1/webhooks/alert",
                json={
                    "alertId": "LMA123",
                    "severity": "critical",
                    "deviceId": 42,
                },
            )

        assert resp.status_code == 202
        data = resp.json()
        assert "analysis_id" in data

    @pytest.mark.asyncio
    async def test_invalid_webhook_body(self, _set_env):
        """POST /api/v1/webhooks/alert returns 400 for invalid body."""
        from httpx import ASGITransport, AsyncClient

        from lm_mcp.transport.http import create_asgi_app

        app = create_asgi_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://localhost") as client:
            resp = await client.post(
                "/api/v1/webhooks/alert",
                content=b"not json",
                headers={"content-type": "application/json"},
            )

        assert resp.status_code == 400


class TestRootEndpoint:
    """Tests for root endpoint including new API paths."""

    @pytest.mark.asyncio
    async def test_root_includes_analysis_endpoints(self, _set_env):
        """Root endpoint lists analysis API paths."""
        from httpx import ASGITransport, AsyncClient

        from lm_mcp.transport.http import create_asgi_app

        app = create_asgi_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://localhost") as client:
            resp = await client.get("/")

        data = resp.json()
        endpoints = data["endpoints"]
        assert "analyze" in endpoints
        assert "analysis" in endpoints
        assert "webhook_alert" in endpoints
