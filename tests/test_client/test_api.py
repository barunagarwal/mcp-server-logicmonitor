# Description: Tests for LogicMonitor API client.
# Description: Uses respx to mock HTTP responses for testing.

import pytest
import respx
from httpx import Response


class TestLogicMonitorClientInit:
    """Tests for client initialization."""

    def test_client_stores_config(self):
        """Client stores base_url and auth provider."""
        from lm_mcp.auth.bearer import BearerAuth
        from lm_mcp.client import LogicMonitorClient

        auth = BearerAuth("test_token")
        client = LogicMonitorClient(
            base_url="https://test.logicmonitor.com/santaba/rest",
            auth=auth,
            timeout=60,
            api_version=3,
        )

        assert client.base_url == "https://test.logicmonitor.com/santaba/rest"
        assert client.auth == auth
        assert client.api_version == 3

    def test_client_strips_trailing_slash(self):
        """Client removes trailing slash from base_url."""
        from lm_mcp.auth.bearer import BearerAuth
        from lm_mcp.client import LogicMonitorClient

        auth = BearerAuth("test_token")
        client = LogicMonitorClient(
            base_url="https://test.logicmonitor.com/santaba/rest/",
            auth=auth,
        )

        assert client.base_url == "https://test.logicmonitor.com/santaba/rest"


class TestLogicMonitorClientHeaders:
    """Tests for header generation."""

    def test_get_headers_includes_content_type(self):
        """Headers include Content-Type."""
        from lm_mcp.auth.bearer import BearerAuth
        from lm_mcp.client import LogicMonitorClient

        auth = BearerAuth("test_token")
        client = LogicMonitorClient(
            base_url="https://test.logicmonitor.com/santaba/rest",
            auth=auth,
        )

        headers = client._get_headers("GET", "/alert/alerts")
        assert headers["Content-Type"] == "application/json"

    def test_get_headers_includes_api_version(self):
        """Headers include X-Version."""
        from lm_mcp.auth.bearer import BearerAuth
        from lm_mcp.client import LogicMonitorClient

        auth = BearerAuth("test_token")
        client = LogicMonitorClient(
            base_url="https://test.logicmonitor.com/santaba/rest",
            auth=auth,
            api_version=3,
        )

        headers = client._get_headers("GET", "/alert/alerts")
        assert headers["X-Version"] == "3"

    def test_get_headers_includes_auth(self):
        """Headers include Authorization from auth provider."""
        from lm_mcp.auth.bearer import BearerAuth
        from lm_mcp.client import LogicMonitorClient

        auth = BearerAuth("my_token")
        client = LogicMonitorClient(
            base_url="https://test.logicmonitor.com/santaba/rest",
            auth=auth,
        )

        headers = client._get_headers("GET", "/alert/alerts")
        assert headers["Authorization"] == "Bearer my_token"


class TestLogicMonitorClientRequests:
    """Tests for making HTTP requests."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_request_success(self):
        """Successful GET request returns parsed JSON."""
        from lm_mcp.auth.bearer import BearerAuth
        from lm_mcp.client import LogicMonitorClient

        respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=Response(200, json={"items": [{"id": 1}], "total": 1})
        )

        auth = BearerAuth("test_token")
        async with LogicMonitorClient(
            base_url="https://test.logicmonitor.com/santaba/rest",
            auth=auth,
        ) as client:
            result = await client.get("/alert/alerts")

        assert result == {"items": [{"id": 1}], "total": 1}

    @pytest.mark.asyncio
    @respx.mock
    async def test_post_request_success(self):
        """Successful POST request with JSON body."""
        from lm_mcp.auth.bearer import BearerAuth
        from lm_mcp.client import LogicMonitorClient

        respx.post("https://test.logicmonitor.com/santaba/rest/sdt/sdts").mock(
            return_value=Response(200, json={"id": 123, "type": "DeviceSDT"})
        )

        auth = BearerAuth("test_token")
        async with LogicMonitorClient(
            base_url="https://test.logicmonitor.com/santaba/rest",
            auth=auth,
        ) as client:
            result = await client.post("/sdt/sdts", json_body={"type": "DeviceSDT"})

        assert result == {"id": 123, "type": "DeviceSDT"}

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_with_params(self):
        """GET request with query parameters."""
        from lm_mcp.auth.bearer import BearerAuth
        from lm_mcp.client import LogicMonitorClient

        route = respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=Response(200, json={"items": [], "total": 0})
        )

        auth = BearerAuth("test_token")
        async with LogicMonitorClient(
            base_url="https://test.logicmonitor.com/santaba/rest",
            auth=auth,
        ) as client:
            await client.get("/alert/alerts", params={"size": 10, "offset": 0})

        assert route.called
        assert "size=10" in str(route.calls.last.request.url)


class TestLogicMonitorClientErrors:
    """Tests for error handling."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_401_raises_authentication_error(self):
        """401 response raises AuthenticationError."""
        from lm_mcp.auth.bearer import BearerAuth
        from lm_mcp.client import LogicMonitorClient
        from lm_mcp.exceptions import AuthenticationError

        respx.get("https://test.logicmonitor.com/santaba/rest/test").mock(
            return_value=Response(401, json={"errorMessage": "Auth failed"})
        )

        auth = BearerAuth("bad_token")
        async with LogicMonitorClient(
            base_url="https://test.logicmonitor.com/santaba/rest",
            auth=auth,
        ) as client:
            with pytest.raises(AuthenticationError):
                await client.get("/test")

    @pytest.mark.asyncio
    @respx.mock
    async def test_403_raises_permission_error(self):
        """403 response raises LMPermissionError."""
        from lm_mcp.auth.bearer import BearerAuth
        from lm_mcp.client import LogicMonitorClient
        from lm_mcp.exceptions import LMPermissionError

        respx.get("https://test.logicmonitor.com/santaba/rest/test").mock(
            return_value=Response(403, json={"errorMessage": "Forbidden"})
        )

        auth = BearerAuth("test_token")
        async with LogicMonitorClient(
            base_url="https://test.logicmonitor.com/santaba/rest",
            auth=auth,
        ) as client:
            with pytest.raises(LMPermissionError):
                await client.get("/test")

    @pytest.mark.asyncio
    @respx.mock
    async def test_404_raises_not_found_error(self):
        """404 response raises NotFoundError."""
        from lm_mcp.auth.bearer import BearerAuth
        from lm_mcp.client import LogicMonitorClient
        from lm_mcp.exceptions import NotFoundError

        respx.get("https://test.logicmonitor.com/santaba/rest/device/devices/999").mock(
            return_value=Response(404, json={"errorMessage": "Not found"})
        )

        auth = BearerAuth("test_token")
        async with LogicMonitorClient(
            base_url="https://test.logicmonitor.com/santaba/rest",
            auth=auth,
        ) as client:
            with pytest.raises(NotFoundError):
                await client.get("/device/devices/999")

    @pytest.mark.asyncio
    @respx.mock
    async def test_429_raises_rate_limit_error(self):
        """429 response raises RateLimitError."""
        from lm_mcp.auth.bearer import BearerAuth
        from lm_mcp.client import LogicMonitorClient
        from lm_mcp.exceptions import RateLimitError

        respx.get("https://test.logicmonitor.com/santaba/rest/test").mock(
            return_value=Response(
                429,
                json={"errorMessage": "Rate limited"},
                headers={"Retry-After": "60"},
            )
        )

        auth = BearerAuth("test_token")
        async with LogicMonitorClient(
            base_url="https://test.logicmonitor.com/santaba/rest",
            auth=auth,
        ) as client:
            with pytest.raises(RateLimitError) as exc_info:
                await client.get("/test")

        assert exc_info.value.retry_after == 60

    @pytest.mark.asyncio
    @respx.mock
    async def test_500_raises_server_error(self):
        """500 response raises ServerError."""
        from lm_mcp.auth.bearer import BearerAuth
        from lm_mcp.client import LogicMonitorClient
        from lm_mcp.exceptions import ServerError

        respx.get("https://test.logicmonitor.com/santaba/rest/test").mock(
            return_value=Response(500, json={"errorMessage": "Internal error"})
        )

        auth = BearerAuth("test_token")
        async with LogicMonitorClient(
            base_url="https://test.logicmonitor.com/santaba/rest",
            auth=auth,
        ) as client:
            with pytest.raises(ServerError):
                await client.get("/test")

    @pytest.mark.asyncio
    @respx.mock
    async def test_connection_error_raises_lm_connection_error(self):
        """Connection error raises LMConnectionError."""
        import httpx

        from lm_mcp.auth.bearer import BearerAuth
        from lm_mcp.client import LogicMonitorClient
        from lm_mcp.exceptions import LMConnectionError

        respx.get("https://test.logicmonitor.com/santaba/rest/test").mock(
            side_effect=httpx.ConnectError("Connection failed")
        )

        auth = BearerAuth("test_token")
        async with LogicMonitorClient(
            base_url="https://test.logicmonitor.com/santaba/rest",
            auth=auth,
        ) as client:
            with pytest.raises(LMConnectionError):
                await client.get("/test")


class TestUnhandled4xx:
    """Tests for unhandled 4xx status codes (400, 405, 409, 415, etc.)."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_400_raises_lm_error(self):
        """400 Bad Request raises LMError."""
        from lm_mcp.auth.bearer import BearerAuth
        from lm_mcp.client import LogicMonitorClient
        from lm_mcp.exceptions import LMError

        respx.post("https://test.logicmonitor.com/santaba/rest/test").mock(
            return_value=Response(400, json={"errorMessage": "Invalid request body"})
        )

        auth = BearerAuth("test_token")
        async with LogicMonitorClient(
            base_url="https://test.logicmonitor.com/santaba/rest",
            auth=auth,
        ) as client:
            with pytest.raises(LMError, match="Invalid request body") as exc_info:
                await client.post("/test", json_body={"bad": "data"})

        assert exc_info.value.code == "HTTP_400"

    @pytest.mark.asyncio
    @respx.mock
    async def test_409_raises_lm_error(self):
        """409 Conflict raises LMError."""
        from lm_mcp.auth.bearer import BearerAuth
        from lm_mcp.client import LogicMonitorClient
        from lm_mcp.exceptions import LMError

        respx.post("https://test.logicmonitor.com/santaba/rest/test").mock(
            return_value=Response(409, json={"errorMessage": "Resource conflict"})
        )

        auth = BearerAuth("test_token")
        async with LogicMonitorClient(
            base_url="https://test.logicmonitor.com/santaba/rest",
            auth=auth,
        ) as client:
            with pytest.raises(LMError, match="Resource conflict") as exc_info:
                await client.post("/test", json_body={"name": "duplicate"})

        assert exc_info.value.code == "HTTP_409"

    @pytest.mark.asyncio
    @respx.mock
    async def test_415_raises_lm_error(self):
        """415 Unsupported Media Type raises LMError."""
        from lm_mcp.auth.bearer import BearerAuth
        from lm_mcp.client import LogicMonitorClient
        from lm_mcp.exceptions import LMError

        respx.post("https://test.logicmonitor.com/santaba/rest/test").mock(
            return_value=Response(415, json={"errorMessage": "Unsupported media type"})
        )

        auth = BearerAuth("test_token")
        async with LogicMonitorClient(
            base_url="https://test.logicmonitor.com/santaba/rest",
            auth=auth,
        ) as client:
            with pytest.raises(LMError, match="Unsupported media type") as exc_info:
                await client.post("/test", json_body={"data": "test"})

        assert exc_info.value.code == "HTTP_415"

    @pytest.mark.asyncio
    @respx.mock
    async def test_4xx_error_includes_suggestion(self):
        """Unhandled 4xx errors include helpful suggestion text."""
        from lm_mcp.auth.bearer import BearerAuth
        from lm_mcp.client import LogicMonitorClient
        from lm_mcp.exceptions import LMError

        respx.post("https://test.logicmonitor.com/santaba/rest/test").mock(
            return_value=Response(405, json={"errorMessage": "Method not allowed"})
        )

        auth = BearerAuth("test_token")
        async with LogicMonitorClient(
            base_url="https://test.logicmonitor.com/santaba/rest",
            auth=auth,
        ) as client:
            with pytest.raises(LMError) as exc_info:
                await client.post("/test", json_body={})

        assert "HTTP 405" in exc_info.value.suggestion


class TestLogicMonitorClientContextManager:
    """Tests for async context manager."""

    @pytest.mark.asyncio
    async def test_context_manager_closes_client(self):
        """Context manager closes the HTTP client."""
        from lm_mcp.auth.bearer import BearerAuth
        from lm_mcp.client import LogicMonitorClient

        auth = BearerAuth("test_token")

        async with LogicMonitorClient(
            base_url="https://test.logicmonitor.com/santaba/rest",
            auth=auth,
        ) as client:
            assert client._client is not None

        assert client._client.is_closed


class TestPostMultipart:
    """Tests for post_multipart method (multipart/form-data uploads)."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_post_multipart_sends_file_upload(self):
        """post_multipart sends definition as multipart file upload."""
        from lm_mcp.auth.bearer import BearerAuth
        from lm_mcp.client import LogicMonitorClient

        route = respx.post(
            "https://test.logicmonitor.com/santaba/rest/setting/datasources/importjson"
        ).mock(
            return_value=Response(
                200,
                json={"id": 1001, "name": "TestDS"},
            )
        )

        auth = BearerAuth("test_token")
        async with LogicMonitorClient(
            base_url="https://test.logicmonitor.com/santaba/rest",
            auth=auth,
        ) as client:
            result = await client.post_multipart(
                "/setting/datasources/importjson",
                definition={"name": "TestDS", "appliesTo": "isLinux()"},
            )

        assert result == {"id": 1001, "name": "TestDS"}
        assert route.called
        request = route.calls[0].request
        content_type = request.headers.get("content-type", "")
        assert "multipart/form-data" in content_type

    @pytest.mark.asyncio
    @respx.mock
    async def test_post_multipart_does_not_send_json_content_type(self):
        """post_multipart does not set Content-Type to application/json."""
        from lm_mcp.auth.bearer import BearerAuth
        from lm_mcp.client import LogicMonitorClient

        route = respx.post(
            "https://test.logicmonitor.com/santaba/rest/setting/eventsources/importjson"
        ).mock(return_value=Response(200, json={"id": 2001, "name": "TestES"}))

        auth = BearerAuth("test_token")
        async with LogicMonitorClient(
            base_url="https://test.logicmonitor.com/santaba/rest",
            auth=auth,
        ) as client:
            await client.post_multipart(
                "/setting/eventsources/importjson",
                definition={"name": "TestES"},
            )

        request = route.calls[0].request
        content_type = request.headers.get("content-type", "")
        assert "application/json" not in content_type

    @pytest.mark.asyncio
    @respx.mock
    async def test_post_multipart_raises_on_error(self):
        """post_multipart raises appropriate exceptions on error status."""
        from lm_mcp.auth.bearer import BearerAuth
        from lm_mcp.client import LogicMonitorClient
        from lm_mcp.exceptions import LMError

        respx.post(
            "https://test.logicmonitor.com/santaba/rest/setting/datasources/importjson"
        ).mock(return_value=Response(400, json={"errorMessage": "Invalid import format"}))

        auth = BearerAuth("test_token")
        async with LogicMonitorClient(
            base_url="https://test.logicmonitor.com/santaba/rest",
            auth=auth,
        ) as client:
            with pytest.raises(LMError, match="Invalid import format"):
                await client.post_multipart(
                    "/setting/datasources/importjson",
                    definition={"bad": "format"},
                )

    @pytest.mark.asyncio
    @respx.mock
    async def test_post_multipart_includes_auth_header(self):
        """post_multipart includes Authorization header."""
        from lm_mcp.auth.bearer import BearerAuth
        from lm_mcp.client import LogicMonitorClient

        route = respx.post(
            "https://test.logicmonitor.com/santaba/rest/setting/datasources/importjson"
        ).mock(return_value=Response(200, json={"id": 1, "name": "DS"}))

        auth = BearerAuth("test_token")
        async with LogicMonitorClient(
            base_url="https://test.logicmonitor.com/santaba/rest",
            auth=auth,
        ) as client:
            await client.post_multipart(
                "/setting/datasources/importjson",
                definition={"name": "DS"},
            )

        request = route.calls[0].request
        assert "Bearer test_token" in request.headers.get("authorization", "")


class TestResponseBodyErrorDetection:
    """Tests for detecting errors returned inside HTTP 200 response bodies."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_200_with_error_body_raises_lm_error(self):
        """HTTP 200 with errorMessage and errorCode in body raises LMError."""
        from lm_mcp.auth.bearer import BearerAuth
        from lm_mcp.client import LogicMonitorClient
        from lm_mcp.exceptions import LMError

        respx.post("https://test.logicmonitor.com/santaba/rest/test").mock(
            return_value=Response(
                200,
                json={
                    "errorMessage": "Unknown type value: script",
                    "errorCode": 1400,
                },
            )
        )

        auth = BearerAuth("test_token")
        async with LogicMonitorClient(
            base_url="https://test.logicmonitor.com/santaba/rest",
            auth=auth,
        ) as client:
            with pytest.raises(LMError, match="Unknown type value: script") as exc_info:
                await client.post("/test", json_body={"type": "script"})

        assert exc_info.value.code == "API_ERROR_1400"

    @pytest.mark.asyncio
    @respx.mock
    async def test_200_with_valid_body_passes(self):
        """HTTP 200 with normal response body passes through."""
        from lm_mcp.auth.bearer import BearerAuth
        from lm_mcp.client import LogicMonitorClient

        respx.post("https://test.logicmonitor.com/santaba/rest/test").mock(
            return_value=Response(200, json={"id": 1, "name": "TestDS"})
        )

        auth = BearerAuth("test_token")
        async with LogicMonitorClient(
            base_url="https://test.logicmonitor.com/santaba/rest",
            auth=auth,
        ) as client:
            result = await client.post("/test", json_body={"name": "TestDS"})

        assert result == {"id": 1, "name": "TestDS"}

    @pytest.mark.asyncio
    @respx.mock
    async def test_200_with_error_in_multipart_raises_lm_error(self):
        """HTTP 200 with error body via post_multipart raises LMError."""
        from lm_mcp.auth.bearer import BearerAuth
        from lm_mcp.client import LogicMonitorClient
        from lm_mcp.exceptions import LMError

        respx.post(
            "https://test.logicmonitor.com/santaba/rest/setting/datasources/importjson"
        ).mock(
            return_value=Response(
                200,
                json={
                    "errorMessage": "Invalid import definition",
                    "errorCode": 1400,
                },
            )
        )

        auth = BearerAuth("test_token")
        async with LogicMonitorClient(
            base_url="https://test.logicmonitor.com/santaba/rest",
            auth=auth,
        ) as client:
            with pytest.raises(LMError, match="Invalid import definition"):
                await client.post_multipart(
                    "/setting/datasources/importjson",
                    definition={"bad": "data"},
                )

    @pytest.mark.asyncio
    @respx.mock
    async def test_200_with_partial_error_fields_passes(self):
        """HTTP 200 with only errorMessage but no errorCode passes through."""
        from lm_mcp.auth.bearer import BearerAuth
        from lm_mcp.client import LogicMonitorClient

        respx.post("https://test.logicmonitor.com/santaba/rest/test").mock(
            return_value=Response(
                200,
                json={
                    "errorMessage": "Some message",
                    "id": 42,
                },
            )
        )

        auth = BearerAuth("test_token")
        async with LogicMonitorClient(
            base_url="https://test.logicmonitor.com/santaba/rest",
            auth=auth,
        ) as client:
            result = await client.post("/test", json_body={"name": "test"})

        assert result["id"] == 42


class _RecordingAuth:
    """AuthProvider double that records the body string the client signs."""

    def __init__(self) -> None:
        self.captured_body: str | None = None
        self.calls: list[tuple[str, str, str]] = []

    def get_auth_headers(self, method: str, resource_path: str, body: str = "") -> dict[str, str]:
        self.captured_body = body
        self.calls.append((method, resource_path, body))
        return {"Authorization": "LMv1 stub"}


class TestRequestBodyAuthSignature:
    """Regression tests for the LMv1 HMAC empty-body signature drift.

    Background: ``body_str = json.dumps(json_body) if json_body else ""`` treats
    ``{}`` as falsy and signs against ``""`` while httpx still sends ``"{}"``
    over the wire. LMv1 portals reject the resulting signature mismatch with 401.
    The fix uses ``is not None`` so an empty dict still serializes to ``"{}"``.
    """

    @pytest.mark.asyncio
    @respx.mock
    async def test_empty_dict_body_signs_curly_braces(self):
        """POST with json_body={} signs the body string ``{}``, not ``""``."""
        from lm_mcp.client import LogicMonitorClient

        respx.post("https://test.logicmonitor.com/santaba/rest/test/recover").mock(
            return_value=Response(200, json={"ok": True})
        )

        auth = _RecordingAuth()
        async with LogicMonitorClient(
            base_url="https://test.logicmonitor.com/santaba/rest",
            auth=auth,
        ) as client:
            await client.post("/test/recover", json_body={})

        assert auth.captured_body == "{}"

    @pytest.mark.asyncio
    @respx.mock
    async def test_none_body_signs_empty_string(self):
        """GET with no body still signs ``""`` -- regression guard against over-eager fix."""
        from lm_mcp.client import LogicMonitorClient

        respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=Response(200, json={"items": []})
        )

        auth = _RecordingAuth()
        async with LogicMonitorClient(
            base_url="https://test.logicmonitor.com/santaba/rest",
            auth=auth,
        ) as client:
            await client.get("/alert/alerts")

        assert auth.captured_body == ""

    @pytest.mark.asyncio
    @respx.mock
    async def test_populated_body_signs_full_json(self):
        """POST with a populated dict signs the full JSON-serialized body."""
        from lm_mcp.client import LogicMonitorClient

        respx.post("https://test.logicmonitor.com/santaba/rest/sdt/sdts").mock(
            return_value=Response(200, json={"id": 1})
        )

        auth = _RecordingAuth()
        async with LogicMonitorClient(
            base_url="https://test.logicmonitor.com/santaba/rest",
            auth=auth,
        ) as client:
            await client.post("/sdt/sdts", json_body={"type": "DeviceSDT"})

        assert auth.captured_body == '{"type":"DeviceSDT"}'

    @pytest.mark.asyncio
    @respx.mock
    async def test_ingest_post_empty_dict_body_signs_curly_braces(self):
        """ingest_post parallel implementation must apply the same fix."""
        from lm_mcp.client import LogicMonitorClient

        respx.post("https://test.logicmonitor.com/rest/log/ingest").mock(
            return_value=Response(202, json={"success": True})
        )

        auth = _RecordingAuth()
        async with LogicMonitorClient(
            base_url="https://test.logicmonitor.com/santaba/rest",
            auth=auth,
            ingest_url="https://test.logicmonitor.com",
        ) as client:
            await client.ingest_post("/rest/log/ingest", json_body={})

        assert auth.captured_body == "{}"

    @pytest.mark.asyncio
    @respx.mock
    async def test_ingest_post_202_with_success_false_raises(self):
        """A 202 whose body reports success:false is surfaced, not treated as success."""
        from lm_mcp.client import LogicMonitorClient
        from lm_mcp.exceptions import LMError

        respx.post("https://test.logicmonitor.com/rest/log/ingest").mock(
            return_value=Response(202, json={"success": False, "message": "2 records rejected"})
        )

        auth = _RecordingAuth()
        async with LogicMonitorClient(
            base_url="https://test.logicmonitor.com/santaba/rest",
            auth=auth,
            ingest_url="https://test.logicmonitor.com",
        ) as client:
            with pytest.raises(LMError, match="2 records rejected"):
                await client.ingest_post("/rest/log/ingest", json_body={"foo": "bar"})

    @pytest.mark.asyncio
    @respx.mock
    async def test_ingest_post_202_with_error_body_raises(self):
        """A 202 carrying errorMessage+errorCode is surfaced as an error, not success."""
        from lm_mcp.client import LogicMonitorClient
        from lm_mcp.exceptions import LMError

        respx.post("https://test.logicmonitor.com/rest/log/ingest").mock(
            return_value=Response(202, json={"errorMessage": "bad resourceId", "errorCode": 1400})
        )

        auth = _RecordingAuth()
        async with LogicMonitorClient(
            base_url="https://test.logicmonitor.com/santaba/rest",
            auth=auth,
            ingest_url="https://test.logicmonitor.com",
        ) as client:
            with pytest.raises(LMError):
                await client.ingest_post("/rest/log/ingest", json_body={"foo": "bar"})


def _guard_client(auth=None):
    """Build a client with both API and ingest URLs for the path-segment guard tests."""
    from lm_mcp.auth.bearer import BearerAuth
    from lm_mcp.client import LogicMonitorClient

    return LogicMonitorClient(
        base_url="https://test.logicmonitor.com/santaba/rest",
        auth=auth or BearerAuth("test_token"),
        ingest_url="https://test.logicmonitor.com",
    )


class TestPathSegmentGuard:
    """R3.1: a path segment that can escape its resource is refused before any request."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_dot_dot_segment_is_refused_and_nothing_is_sent(self):
        """A traversal segment raises ValidationError naming the segment; no request goes out."""
        from lm_mcp.exceptions import ValidationError

        route = respx.route().mock(return_value=Response(200, json={}))
        async with _guard_client() as client:
            with pytest.raises(ValidationError, match=r"'\.\.'"):
                await client.get("/device/devices/../../setting/admins")

        assert not route.called

    @pytest.mark.asyncio
    @respx.mock
    async def test_delete_with_query_in_id_is_refused(self):
        """A DELETE whose id argument smuggles a query string is refused."""
        from lm_mcp.exceptions import ValidationError

        route = respx.route().mock(return_value=Response(200, json={}))
        async with _guard_client() as client:
            with pytest.raises(ValidationError, match=r"'1\?force=true'"):
                await client.delete("/sdt/sdts/1?force=true")

        assert not route.called

    @pytest.mark.asyncio
    @respx.mock
    @pytest.mark.parametrize("method", ["put", "patch"])
    async def test_put_and_patch_traversal_is_refused(self, method):
        """PUT and PATCH refuse a traversal segment before sending their body."""
        from lm_mcp.exceptions import ValidationError

        route = respx.route().mock(return_value=Response(200, json={}))
        async with _guard_client() as client:
            with pytest.raises(ValidationError, match=r"'\.\.'"):
                await getattr(client, method)(
                    "/device/devices/1/../../setting/admins/1", json_body={"roles": []}
                )

        assert not route.called

    @pytest.mark.asyncio
    @respx.mock
    @pytest.mark.parametrize(
        "segment",
        ["%2e%2e", "%2E%2E", ".%2e", "a%2fb", "a%2Fb", "x%3fy", "x%3Fy", "x%23y", "x#y", "."],
    )
    async def test_encoded_or_reserved_segment_is_refused(self, segment):
        """Percent-encoded dot, slash, ? and #, a raw # and a lone dot are refused."""
        from lm_mcp.exceptions import ValidationError

        route = respx.route().mock(return_value=Response(200, json={}))
        async with _guard_client() as client:
            with pytest.raises(ValidationError):
                await client.get(f"/device/devices/{segment}/properties")

        assert not route.called

    @pytest.mark.asyncio
    @respx.mock
    async def test_ingest_post_traversal_is_refused(self):
        """ingest_post applies the same guard to its ingest path."""
        from lm_mcp.exceptions import ValidationError

        route = respx.route().mock(return_value=Response(202, json={"success": True}))
        async with _guard_client() as client:
            with pytest.raises(ValidationError):
                await client.ingest_post("/rest/../santaba/rest/setting/admins", json_body={})

        assert not route.called

    @pytest.mark.asyncio
    @respx.mock
    async def test_post_multipart_traversal_is_refused(self):
        """post_multipart applies the same guard to its import path."""
        from lm_mcp.exceptions import ValidationError

        route = respx.route().mock(return_value=Response(200, json={}))
        async with _guard_client() as client:
            with pytest.raises(ValidationError):
                await client.post_multipart("/setting/../setting/admins", {"name": "x"})

        assert not route.called

    @pytest.mark.asyncio
    @respx.mock
    async def test_delete_sdt_tool_returns_error_content_and_sends_nothing(
        self, monkeypatch, caplog
    ):
        """delete_sdt with a traversal id returns ErrorContent and makes no request.

        The refusal is an LMError, so handle_error reports it without logging it as an
        unhandled exception with a traceback.
        """
        from lm_mcp.tools import ErrorContent
        from lm_mcp.tools.sdts import delete_sdt

        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "true")
        route = respx.route().mock(return_value=Response(200, json={}))
        async with _guard_client() as client:
            result = await delete_sdt(client, sdt_id="../x")

        assert not route.called
        assert len(result) == 1
        assert isinstance(result[0], ErrorContent)
        assert result[0].text.startswith("Error: ")
        assert "'..'" in result[0].text
        assert "unhandled error in tool handler" not in caplog.text

    @pytest.mark.asyncio
    @respx.mock
    async def test_ordinary_paths_still_reach_the_portal(self):
        """Ids with letters, digits, underscores, hyphens and inner dots pass the guard."""
        route = respx.route().mock(return_value=Response(200, json={"ok": True}))
        async with _guard_client() as client:
            await client.delete("/sdt/sdts/R_123")
            await client.get("/setting/opsnotes/note-1")
            await client.get("/device/devices/42/devicedatasources/7/instances/v1.2")

        assert route.call_count == 3

    @pytest.mark.asyncio
    @respx.mock
    async def test_ingest_post_sends_params_as_query_and_signs_bare_path(self):
        """Query parameters ride in params, so the guarded path carries no ? of its own."""
        route = respx.post("https://test.logicmonitor.com/rest/metric/ingest").mock(
            return_value=Response(202, json={"success": True})
        )
        auth = _RecordingAuth()
        async with _guard_client(auth) as client:
            await client.ingest_post(
                "/rest/metric/ingest", json_body={"a": 1}, params={"create": "true"}
            )

        assert route.called
        assert route.calls[0].request.url.params["create"] == "true"
        assert auth.calls == [("POST", "/rest/metric/ingest", '{"a":1}')]


class TestStringIdSchemaPattern:
    """R3.1: the string-typed id properties declare the id shape, so a client refuses ../x."""

    @pytest.mark.parametrize(
        ("tool_name", "prop"),
        [
            ("delete_sdt", "sdt_id"),
            ("update_sdt", "sdt_id"),
            ("update_ops_note", "note_id"),
            ("delete_ops_note", "note_id"),
        ],
    )
    def test_id_pattern_refuses_traversal_and_admits_lm_ids(self, tool_name, prop):
        """The schema rejects ../x and 1?x=y and accepts SDT_123 and note-1."""
        import jsonschema

        from lm_mcp.registry import TOOLS

        schema = next(t for t in TOOLS if t.name == tool_name).inputSchema
        for bad in ("../x", "1?x=y", "a/b", ""):
            with pytest.raises(jsonschema.ValidationError):
                jsonschema.validate({prop: bad}, schema)
        for good in ("SDT_123", "note-1", "42"):
            jsonschema.validate({prop: good}, schema)
