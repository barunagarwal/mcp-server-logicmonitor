# Description: Tests for retry logic.
# Description: Validates exponential backoff behavior on 429 and 5xx responses.

import httpx
import pytest
import respx

from lm_mcp.auth.bearer import BearerAuth
from lm_mcp.client import LogicMonitorClient
from lm_mcp.exceptions import RateLimitError


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Skip backoff waits; Retry-After can now lengthen them to tens of seconds."""

    async def fake_sleep(seconds):
        return None

    monkeypatch.setattr("lm_mcp.client.api.asyncio.sleep", fake_sleep)


@pytest.fixture
def auth():
    """Create a BearerAuth instance for testing."""
    return BearerAuth("test-token")


@pytest.fixture
def client(auth):
    """Create a LogicMonitorClient instance for testing."""
    return LogicMonitorClient(
        base_url="https://test.logicmonitor.com/santaba/rest",
        auth=auth,
        timeout=30,
        api_version=3,
        max_retries=3,
    )


class TestRetryLogic:
    """Tests for retry with exponential backoff."""

    @respx.mock
    async def test_retry_succeeds_on_second_attempt(self, client):
        """Request succeeds after retrying a 429 response."""
        route = respx.get("https://test.logicmonitor.com/santaba/rest/device/devices")
        route.side_effect = [
            httpx.Response(429, headers={"Retry-After": "1"}),
            httpx.Response(200, json={"items": [], "total": 0}),
        ]

        result = await client.get("/device/devices")

        assert result == {"items": [], "total": 0}
        assert route.call_count == 2

    @respx.mock
    async def test_retry_exhausted_raises_rate_limit_error(self, client):
        """RateLimitError is raised when all retries exhausted."""
        route = respx.get("https://test.logicmonitor.com/santaba/rest/device/devices")
        route.mock(
            return_value=httpx.Response(
                429,
                headers={"Retry-After": "1"},
                json={"errorMessage": "Rate limited"},
            )
        )

        with pytest.raises(RateLimitError) as exc_info:
            await client.get("/device/devices")

        assert "Rate limited" in str(exc_info.value)
        assert route.call_count == 4  # Initial + 3 retries

    @respx.mock
    async def test_retry_parses_retry_after_header(self, client):
        """Retry-After header is parsed and stored in exception."""
        route = respx.get("https://test.logicmonitor.com/santaba/rest/device/devices")
        route.mock(
            return_value=httpx.Response(
                429,
                headers={"Retry-After": "30"},
                json={"errorMessage": "Rate limited"},
            )
        )

        with pytest.raises(RateLimitError) as exc_info:
            await client.get("/device/devices")

        assert exc_info.value.retry_after == 30

    @respx.mock
    async def test_5xx_errors_are_retried(self, client):
        """5xx server errors are retried with exponential backoff."""
        route = respx.get("https://test.logicmonitor.com/santaba/rest/device/devices")
        route.mock(return_value=httpx.Response(500, json={"errmsg": "Server error"}))

        from lm_mcp.exceptions import ServerError

        with pytest.raises(ServerError):
            await client.get("/device/devices")

        # Initial request + 3 retries = 4 total calls
        assert route.call_count == 4

    @respx.mock
    async def test_4xx_errors_not_retried(self, client):
        """4xx client errors (except 429) are not retried."""
        route = respx.get("https://test.logicmonitor.com/santaba/rest/device/devices")
        route.mock(return_value=httpx.Response(404, json={"errorMessage": "Not found"}))

        from lm_mcp.exceptions import NotFoundError

        with pytest.raises(NotFoundError):
            await client.get("/device/devices")

        assert route.call_count == 1

    @respx.mock
    async def test_zero_max_retries_no_retry(self, auth):
        """With max_retries=0, no retries are attempted."""
        client = LogicMonitorClient(
            base_url="https://test.logicmonitor.com/santaba/rest",
            auth=auth,
            timeout=30,
            api_version=3,
            max_retries=0,
        )

        route = respx.get("https://test.logicmonitor.com/santaba/rest/device/devices")
        route.mock(
            return_value=httpx.Response(
                429,
                headers={"Retry-After": "1"},
                json={"errorMessage": "Rate limited"},
            )
        )

        with pytest.raises(RateLimitError):
            await client.get("/device/devices")

        assert route.call_count == 1


class TestRetryConfig:
    """Tests for retry configuration."""

    def test_max_retries_config_loaded(self, monkeypatch):
        """max_retries is loaded from config."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_MAX_RETRIES", "5")

        from importlib import reload

        import lm_mcp.config

        reload(lm_mcp.config)
        from lm_mcp.config import LMConfig

        config = LMConfig()
        assert config.max_retries == 5

    def test_max_retries_default_value(self, monkeypatch):
        """max_retries defaults to 3."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")

        from importlib import reload

        import lm_mcp.config

        reload(lm_mcp.config)
        from lm_mcp.config import LMConfig

        config = LMConfig()
        assert config.max_retries == 3

    def test_retry_after_cap_loaded_and_validated(self, monkeypatch):
        """LM_RETRY_AFTER_CAP_SECONDS is read from the environment; negatives are refused."""
        import pydantic

        from lm_mcp.config import LMConfig

        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_RETRY_AFTER_CAP_SECONDS", "30")
        assert LMConfig().retry_after_cap_seconds == 30

        monkeypatch.setenv("LM_RETRY_AFTER_CAP_SECONDS", "-1")
        with pytest.raises(pydantic.ValidationError, match="retry_after_cap_seconds"):
            LMConfig()
