# Description: Tests for AWX/AAP API client.
# Description: Uses respx to mock HTTP responses for testing.

import pytest
import respx
from httpx import Response

from lm_mcp.client.awx import AwxClient
from lm_mcp.exceptions import (
    AuthenticationError,
    LMConnectionError,
    LMError,
    LMPermissionError,
    NotFoundError,
    RateLimitError,
    ServerError,
)

AWX_BASE = "https://tower.example.com"
AWX_API = f"{AWX_BASE}/api/v2"


@pytest.fixture
def client():
    return AwxClient(
        base_url=AWX_BASE,
        token="test-awx-token",
        timeout=30,
        max_retries=3,
    )


class TestAwxClientInit:
    """Tests for AWX client initialization."""

    def test_stores_config(self):
        """Client stores base_url and token."""
        client = AwxClient(
            base_url=AWX_BASE,
            token="my-token",
            timeout=60,
            max_retries=5,
        )
        assert client.base_url == AWX_API
        assert client.token == "my-token"
        assert client.max_retries == 5

    def test_strips_trailing_slash(self):
        """Client removes trailing slash from base_url."""
        client = AwxClient(
            base_url=f"{AWX_BASE}/",
            token="my-token",
        )
        assert client.base_url == AWX_API

    def test_default_values(self):
        """Client uses sensible defaults."""
        client = AwxClient(
            base_url=AWX_BASE,
            token="my-token",
        )
        assert client.max_retries == 3
        assert client.verify_ssl is True


class TestAwxClientHeaders:
    """Tests for header generation."""

    def test_headers_include_auth(self, client):
        """Headers include Bearer token."""
        headers = client._get_headers()
        assert headers["Authorization"] == "Bearer test-awx-token"

    def test_headers_include_content_type(self, client):
        """Headers include Content-Type."""
        headers = client._get_headers()
        assert headers["Content-Type"] == "application/json"


class TestAwxClientGet:
    """Tests for GET requests."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_success(self, client):
        """Successful GET returns parsed JSON."""
        respx.get(f"{AWX_API}/job_templates/").mock(
            return_value=Response(200, json={"count": 1, "results": [{"id": 1}]})
        )
        result = await client.get("/job_templates/")
        assert result == {"count": 1, "results": [{"id": 1}]}

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_with_params(self, client):
        """GET passes query parameters."""
        route = respx.get(f"{AWX_API}/job_templates/").mock(
            return_value=Response(200, json={"count": 0, "results": []})
        )
        await client.get("/job_templates/", params={"page_size": 10})
        assert route.calls[0].request.url.params["page_size"] == "10"

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_text_response(self, client):
        """GET with format=txt returns raw text."""
        respx.get(f"{AWX_API}/jobs/42/stdout/").mock(
            return_value=Response(200, text="PLAY [all] ***\nok: [host1]")
        )
        result = await client.get("/jobs/42/stdout/", params={"format": "txt"})
        assert result == {"text": "PLAY [all] ***\nok: [host1]"}


class TestAwxClientPost:
    """Tests for POST requests."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_post_success(self, client):
        """Successful POST returns parsed JSON."""
        respx.post(f"{AWX_API}/job_templates/42/launch/").mock(
            return_value=Response(201, json={"job": 99, "status": "pending"})
        )
        result = await client.post(
            "/job_templates/42/launch/", json_body={"extra_vars": {"foo": "bar"}}
        )
        assert result == {"job": 99, "status": "pending"}

    @pytest.mark.asyncio
    @respx.mock
    async def test_post_empty_body(self, client):
        """POST with no body succeeds."""
        respx.post(f"{AWX_API}/jobs/42/cancel/").mock(return_value=Response(202, json={}))
        result = await client.post("/jobs/42/cancel/")
        assert result == {}


class TestAwxClientDelete:
    """Tests for DELETE requests."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_delete_success(self, client):
        """Successful DELETE returns empty dict for 204."""
        respx.delete(f"{AWX_API}/jobs/42/").mock(return_value=Response(204, text=""))
        result = await client.delete("/jobs/42/")
        assert result == {}


class TestAwxClientErrorMapping:
    """Tests for HTTP error code mapping to exceptions."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_401_raises_authentication_error(self, client):
        """401 response raises AuthenticationError."""
        respx.get(f"{AWX_API}/job_templates/").mock(
            return_value=Response(
                401, json={"detail": "Authentication credentials were not provided."}
            )
        )
        with pytest.raises(AuthenticationError):
            await client.get("/job_templates/")

    @pytest.mark.asyncio
    @respx.mock
    async def test_403_raises_permission_error(self, client):
        """403 response raises LMPermissionError."""
        respx.get(f"{AWX_API}/credentials/").mock(
            return_value=Response(
                403, json={"detail": "You do not have permission to perform this action."}
            )
        )
        with pytest.raises(LMPermissionError):
            await client.get("/credentials/")

    @pytest.mark.asyncio
    @respx.mock
    async def test_404_raises_not_found_error(self, client):
        """404 response raises NotFoundError."""
        respx.get(f"{AWX_API}/job_templates/999/").mock(
            return_value=Response(404, json={"detail": "Not found."})
        )
        with pytest.raises(NotFoundError):
            await client.get("/job_templates/999/")

    @pytest.mark.asyncio
    @respx.mock
    async def test_429_raises_rate_limit_error_after_retries(self):
        """429 response raises RateLimitError after retries exhausted."""
        client = AwxClient(
            base_url=AWX_BASE,
            token="test-token",
            max_retries=0,
        )
        respx.get(f"{AWX_API}/job_templates/").mock(
            return_value=Response(429, json={"detail": "Request was throttled."})
        )
        with pytest.raises(RateLimitError):
            await client.get("/job_templates/")

    @pytest.mark.asyncio
    @respx.mock
    async def test_500_raises_server_error_after_retries(self):
        """500 response raises ServerError after retries exhausted."""
        client = AwxClient(
            base_url=AWX_BASE,
            token="test-token",
            max_retries=0,
        )
        respx.get(f"{AWX_API}/ping/").mock(
            return_value=Response(500, json={"detail": "Internal server error"})
        )
        with pytest.raises(ServerError):
            await client.get("/ping/")

    @pytest.mark.asyncio
    @respx.mock
    async def test_400_raises_lm_error(self, client):
        """400 response raises LMError with HTTP code."""
        respx.post(f"{AWX_API}/job_templates/42/launch/").mock(
            return_value=Response(400, json={"extra_vars": ["This field may not be blank."]})
        )
        with pytest.raises(LMError) as exc_info:
            await client.post("/job_templates/42/launch/", json_body={"extra_vars": ""})
        assert exc_info.value.code == "HTTP_400"

    @pytest.mark.asyncio
    @respx.mock
    async def test_409_raises_lm_error(self, client):
        """409 response raises LMError with HTTP code."""
        respx.post(f"{AWX_API}/jobs/42/cancel/").mock(
            return_value=Response(409, json={"detail": "Job already cancelled."})
        )
        with pytest.raises(LMError) as exc_info:
            await client.post("/jobs/42/cancel/")
        assert exc_info.value.code == "HTTP_409"


class TestAwxClientRetry:
    """Tests for retry logic on transient errors."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_retries_on_429(self):
        """Client retries on 429 and succeeds."""
        client = AwxClient(
            base_url=AWX_BASE,
            token="test-token",
            max_retries=2,
        )
        route = respx.get(f"{AWX_API}/job_templates/").mock(
            side_effect=[
                Response(429, json={"detail": "Throttled"}),
                Response(200, json={"count": 1, "results": []}),
            ]
        )
        result = await client.get("/job_templates/")
        assert result == {"count": 1, "results": []}
        assert route.call_count == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_retries_on_500(self):
        """Client retries on 500 and succeeds."""
        client = AwxClient(
            base_url=AWX_BASE,
            token="test-token",
            max_retries=2,
        )
        route = respx.get(f"{AWX_API}/ping/").mock(
            side_effect=[
                Response(500, json={"detail": "Server error"}),
                Response(200, json={"ha": True, "version": "4.5.0"}),
            ]
        )
        result = await client.get("/ping/")
        assert result["version"] == "4.5.0"
        assert route.call_count == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_exhausted_retries_raises(self):
        """Client raises after all retries exhausted."""
        client = AwxClient(
            base_url=AWX_BASE,
            token="test-token",
            max_retries=1,
        )
        respx.get(f"{AWX_API}/job_templates/").mock(
            side_effect=[
                Response(429, json={"detail": "Throttled"}),
                Response(429, json={"detail": "Throttled"}),
            ]
        )
        with pytest.raises(RateLimitError):
            await client.get("/job_templates/")


class TestAwxRetryPolicy:
    """R3.5: AWX follows the LM client's rule; a launch that got a 5xx is not resent."""

    @pytest.fixture
    def waits(self, monkeypatch):
        recorded: list[float] = []

        async def fake_sleep(seconds):
            recorded.append(seconds)

        monkeypatch.setattr("lm_mcp.client.awx.asyncio.sleep", fake_sleep)
        return recorded

    @pytest.mark.asyncio
    @respx.mock
    async def test_launch_502_is_not_retried(self, waits):
        """A 502 on a launch may follow a started job, so the launch is sent once."""
        client = AwxClient(base_url=AWX_BASE, token="test-token", max_retries=2)
        route = respx.post(f"{AWX_API}/job_templates/1/launch/").mock(
            return_value=Response(502, json={"detail": "Bad gateway"})
        )
        with pytest.raises(ServerError):
            await client.post("/job_templates/1/launch/", json_body={})
        assert route.call_count == 1
        assert waits == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_launch_429_is_retried(self, waits):
        """A throttled launch was refused unprocessed, so it is sent again."""
        client = AwxClient(base_url=AWX_BASE, token="test-token", max_retries=2)
        route = respx.post(f"{AWX_API}/job_templates/1/launch/").mock(
            side_effect=[
                Response(429, json={"detail": "Throttled"}),
                Response(201, json={"job": 7}),
            ]
        )
        result = await client.post("/job_templates/1/launch/", json_body={})
        assert result == {"job": 7}
        assert route.call_count == 2

    @pytest.mark.asyncio
    @respx.mock
    @pytest.mark.parametrize(("retry_after", "expected"), [("60", 60), ("600", 120)])
    async def test_retry_after_is_honored_and_capped(self, waits, retry_after, expected):
        """AWX waits as the LM client does: Retry-After lengthens the backoff, up to 120 s."""
        client = AwxClient(base_url=AWX_BASE, token="test-token", max_retries=2)
        respx.get(f"{AWX_API}/job_templates/").mock(
            side_effect=[
                Response(429, headers={"Retry-After": retry_after}, json={"detail": "Throttled"}),
                Response(200, json={"count": 0, "results": []}),
            ]
        )
        await client.get("/job_templates/")
        assert waits == [expected]

    @pytest.mark.asyncio
    @respx.mock
    async def test_read_timeout_is_translated_with_a_message(self, waits):
        """httpx raises ReadTimeout with an empty message; the translation names it."""
        import httpx

        client = AwxClient(base_url=AWX_BASE, token="test-token", max_retries=2)
        route = respx.get(f"{AWX_API}/ping/").mock(side_effect=httpx.ReadTimeout(""))
        with pytest.raises(LMConnectionError) as exc_info:
            await client.get("/ping/")
        assert "timed out" in exc_info.value.message
        assert "/ping/" in exc_info.value.message
        assert route.call_count == 1


class TestAwxClientConnectionError:
    """Tests for connection failure handling."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_connection_error_raises(self, client):
        """Connection failure raises LMConnectionError."""
        import httpx

        respx.get(f"{AWX_API}/ping/").mock(side_effect=httpx.ConnectError("Connection refused"))
        with pytest.raises(LMConnectionError):
            await client.get("/ping/")


class TestAwxClientClose:
    """Tests for client cleanup."""

    @pytest.mark.asyncio
    async def test_close(self, client):
        """Client close does not raise."""
        await client.close()

    @pytest.mark.asyncio
    async def test_async_context_manager(self):
        """Client works as async context manager."""
        async with AwxClient(
            base_url=AWX_BASE,
            token="test-token",
        ) as client:
            assert client.token == "test-token"
