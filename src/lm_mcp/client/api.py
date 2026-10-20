# Description: LogicMonitor API client for making authenticated requests.
# Description: Handles HTTP communication, error mapping, and response parsing.

import asyncio
import contextlib
import json
import random
import re
import time

import httpx

from lm_mcp.auth import AuthProvider
from lm_mcp.exceptions import (
    AuthenticationError,
    LMConnectionError,
    LMError,
    LMPermissionError,
    NotFoundError,
    RateLimitError,
    ServerError,
)
from lm_mcp.logging import log_api_request, log_api_response

# Jackson-aware translations for common LogicMonitor 4xx error shapes.
# LM's v3 API frequently returns raw Jackson deserialization errors that
# name Java POJO internals (e.g. ``RestEscalatingChainV3$Period``). This
# table rewrites the worst offenders into actionable hints while keeping
# the raw server message under ``LMError.details`` for debugging.
#
# Each entry is ``(pattern, translated_message_or_None, suggestion)``.
# When ``translated_message_or_None`` is None, the raw message is kept
# but the suggestion is still attached. ``{match1}`` / ``{match2}`` in
# the translated message or suggestion are replaced by regex capture
# groups (1-indexed).
_LM_ERROR_PATTERNS: list[tuple[re.Pattern[str], str | None, str]] = [
    (
        re.compile(r"Cannot construct instance of `[^`]*\$Period`", re.IGNORECASE),
        "destinations[].period must be null or a Period object",
        (
            "Set period to null for 'single' chains. For 'timebased' chains, "
            "pass an object like {hour1: 9, hour2: 17, minute1: 0, minute2: 0, "
            "weekDays: [1,2,3,4,5]}."
        ),
    ),
    (
        re.compile(
            r"Cannot deserialize value of type `[^`]*ArrayList<[^`]*Recipient[^`]*>` from Object",
            re.IGNORECASE,
        ),
        "destinations[].stages expects a list of Recipient objects, not a wrapper object",
        (
            "stages is a list of lists. Shape: stages: [[{type: 'admin', "
            "addr: '<username>', method: '<integration display name>'}, ...]]."
        ),
    ),
    (
        re.compile(r"invalid recipient for stage \d+", re.IGNORECASE),
        None,
        (
            "Escalation recipients use lowercase type='admin' with "
            "method=<integration display name>. 'INTEGRATION' is not a valid "
            "type. Use the integration-shorthand form "
            "{type: 'integration', integration_name: ..., admin: ...} -- the "
            "MCP server rewrites it to the canonical admin+method form."
        ),
    ),
    (
        re.compile(r"admin<(\d+)> is not found", re.IGNORECASE),
        "admin user id {match1} not found",
        (
            "addr must be the admin's username string, not the integer id. "
            "Use get_users to look up the username for this id."
        ),
    ),
    (
        re.compile(r"invalid method <\w+> for type ARBITRARY", re.IGNORECASE),
        None,
        (
            "Recipients with type='ARBITRARY' can only use method='email'. "
            "To reach an integration, use type='admin' with "
            "method=<integration display name>."
        ),
    ),
]


def _translate_lm_error(raw_message: str) -> tuple[str | None, str | None]:
    """Match a raw LM error message against known Jackson/validation patterns.

    Returns ``(translated_message_or_None, suggestion_or_None)``. When no
    pattern matches, both values are None and callers should fall back to
    the raw message and the generic suggestion. When a pattern matches but
    its translated message is None, the caller should keep the raw message
    and attach only the suggestion.
    """
    if not raw_message:
        return None, None
    for pattern, translated, suggestion in _LM_ERROR_PATTERNS:
        match = pattern.search(raw_message)
        if match:
            resolved_message = translated
            resolved_suggestion = suggestion
            if resolved_message is not None:
                for idx, group in enumerate(match.groups(), start=1):
                    resolved_message = resolved_message.replace(f"{{match{idx}}}", group or "")
            for idx, group in enumerate(match.groups(), start=1):
                resolved_suggestion = resolved_suggestion.replace(f"{{match{idx}}}", group or "")
            return resolved_message, resolved_suggestion
    return None, None


def _serialize_json_body(json_body: list | dict | None) -> str:
    """Serialize a JSON request body once, as the string to sign and to send.

    LMv1 HMAC signs the body string verbatim, so the client sends the UTF-8
    bytes of this exact string instead of letting httpx serialize the body a
    second time with its own separators. ``None`` means no body and signs as
    ``""``; an empty dict still serializes to ``"{}"``.
    """
    if json_body is None:
        return ""
    return json.dumps(json_body, separators=(",", ":"), ensure_ascii=False)


class LogicMonitorClient:
    """Async HTTP client for LogicMonitor REST API.

    Handles authentication, request building, error mapping, and retry logic.
    Use as async context manager for proper resource cleanup.
    """

    def __init__(
        self,
        base_url: str,
        auth: AuthProvider,
        timeout: int = 30,
        api_version: int = 3,
        max_retries: int = 3,
        ingest_url: str | None = None,
    ):
        """Initialize the client.

        Args:
            base_url: LogicMonitor API base URL (e.g., https://company.logicmonitor.com/santaba/rest)
            auth: Authentication provider for generating auth headers.
            timeout: Request timeout in seconds.
            api_version: LogicMonitor API version.
            max_retries: Maximum retry attempts for rate-limited requests.
            ingest_url: Base URL for ingestion APIs (e.g., https://company.logicmonitor.com).
        """
        self.base_url = base_url.rstrip("/")
        self.auth = auth
        self.api_version = api_version
        self.max_retries = max_retries
        self._client = httpx.AsyncClient(timeout=timeout)
        self.ingest_url = ingest_url.rstrip("/") if ingest_url else None

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

    async def __aenter__(self) -> "LogicMonitorClient":
        """Enter async context manager."""
        return self

    async def __aexit__(self, *args) -> None:
        """Exit async context manager and close client."""
        await self.close()

    def _get_headers(self, method: str, path: str, body: str = "") -> dict[str, str]:
        """Build request headers including auth.

        Args:
            method: HTTP method.
            path: API resource path.
            body: Request body string for signature calculation.

        Returns:
            Dict of headers for the request.
        """
        headers = {
            "Content-Type": "application/json",
            "X-Version": str(self.api_version),
        }
        headers.update(self.auth.get_auth_headers(method, path, body))
        return headers

    def _parse_error_response(self, response: httpx.Response) -> tuple[str, int | None]:
        """Parse error message and retry-after from response.

        Args:
            response: The HTTP response to parse.

        Returns:
            Tuple of (error message, retry_after value or None).
        """
        try:
            error_data = response.json()
            message = error_data.get("errorMessage", response.text)
        except (json.JSONDecodeError, ValueError):
            message = response.text

        retry_after = None
        if "Retry-After" in response.headers:
            with contextlib.suppress(ValueError):
                retry_after = int(response.headers["Retry-After"])

        return message, retry_after

    def _check_response_body_errors(self, data: dict) -> None:
        """Check for API errors returned inside HTTP 200 response bodies.

        Some LM API endpoints return HTTP 200 but include error details
        in the JSON body (errorMessage + errorCode). This method detects
        that pattern and raises LMError so callers see the failure.

        Args:
            data: Parsed JSON response body.

        Raises:
            LMError: If response body contains both errorMessage and errorCode.
        """
        if not isinstance(data, dict):
            return
        error_message = data.get("errorMessage")
        error_code = data.get("errorCode")
        if error_message and error_code is not None:
            raise LMError(
                message=str(error_message),
                code=f"API_ERROR_{error_code}",
            )

    def _raise_for_status(
        self, response: httpx.Response, message: str, retry_after: int | None
    ) -> None:
        """Raise appropriate exception for error responses.

        For 4xx responses, the raw server message is passed through the
        Jackson-aware translator (see :func:`_translate_lm_error`). When a
        pattern matches, the raised :class:`LMError` carries the
        translated message, a targeted suggestion, and the original raw
        text under ``details`` for debugging.

        Args:
            response: The HTTP response to check.
            message: Parsed error message.
            retry_after: Retry-After header value if present.

        Raises:
            AuthenticationError: For 401 responses.
            LMPermissionError: For 403 responses.
            NotFoundError: For 404 responses.
            RateLimitError: For 429 responses.
            ServerError: For 5xx responses.
        """
        status = response.status_code

        if status == 401:
            raise AuthenticationError(message)
        elif status == 403:
            raise LMPermissionError(message)
        elif status == 404:
            raise NotFoundError(message)
        elif status == 429:
            raise RateLimitError(message, retry_after=retry_after)
        elif status >= 500:
            raise ServerError(message)
        elif 400 <= status < 500:
            translated, translated_suggestion = _translate_lm_error(message)
            user_message = translated if translated is not None else message
            suggestion = translated_suggestion or (
                f"The API returned HTTP {status}. Check the request parameters and body format."
            )
            details = message if translated is not None or translated_suggestion else None
            raise LMError(
                message=user_message,
                code=f"HTTP_{status}",
                suggestion=suggestion,
                details=details,
            )

    async def request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        json_body: dict | None = None,
    ) -> dict:
        """Make an authenticated request to the LogicMonitor API with retry.

        Implements exponential backoff for rate-limited (429) responses.

        Args:
            method: HTTP method (GET, POST, PUT, PATCH, DELETE).
            path: API resource path (e.g., /alert/alerts).
            params: Query parameters.
            json_body: JSON body for POST/PUT/PATCH requests.

        Returns:
            Parsed JSON response as dict.

        Raises:
            LMConnectionError: If connection fails.
            AuthenticationError: For 401 responses.
            LMPermissionError: For 403 responses.
            NotFoundError: For 404 responses.
            RateLimitError: For 429 responses after retries exhausted.
            ServerError: For 5xx responses.
        """
        url = f"{self.base_url}{path}"
        # ``json_body`` is checked against None rather than truthiness so that an
        # empty dict ``{}`` still serializes to ``"{}"`` and matches the body
        # httpx puts on the wire. LMv1 HMAC signs the body string verbatim, so
        # a ``""`` vs ``"{}"`` mismatch produces 401 on LMv1 portals.
        body_str = _serialize_json_body(json_body)
        content = body_str.encode("utf-8") if json_body is not None else None
        headers = self._get_headers(method, path, body_str)

        log_api_request(method, path, params)

        last_retry_after: int | None = None
        last_message = "Rate limited"

        for attempt in range(self.max_retries + 1):
            request_start = time.monotonic()
            try:
                response = await self._client.request(
                    method=method,
                    url=url,
                    params=params,
                    content=content,
                    headers=headers,
                )
            except httpx.ConnectError as e:
                raise LMConnectionError(f"Failed to connect to {self.base_url}: {e}") from e

            # Retry on rate limit (429) or server errors (5xx)
            if response.status_code == 429 or response.status_code >= 500:
                message, retry_after = self._parse_error_response(response)
                last_message = message
                last_retry_after = retry_after

                if attempt < self.max_retries:
                    # Exponential backoff with jitter to prevent thundering herd
                    base_backoff = 2**attempt
                    jitter = random.uniform(0, 0.5 * base_backoff)
                    wait_time = base_backoff + jitter
                    if retry_after is not None:
                        wait_time = min(retry_after, wait_time)
                    await asyncio.sleep(wait_time)
                    continue

            if response.status_code >= 400:
                message, retry_after = self._parse_error_response(response)
                self._raise_for_status(response, message, retry_after)

            elapsed = time.monotonic() - request_start
            log_api_response(response.status_code, elapsed, path)
            data = response.json()
            self._check_response_body_errors(data)
            return data

        raise RateLimitError(last_message, retry_after=last_retry_after)

    async def get(self, path: str, params: dict | None = None) -> dict:
        """Make a GET request.

        Args:
            path: API resource path.
            params: Query parameters.

        Returns:
            Parsed JSON response.
        """
        return await self.request("GET", path, params=params)

    async def post(self, path: str, json_body: dict | None = None) -> dict:
        """Make a POST request.

        Args:
            path: API resource path.
            json_body: JSON body.

        Returns:
            Parsed JSON response.
        """
        return await self.request("POST", path, json_body=json_body)

    async def post_multipart(
        self, path: str, definition: dict | str, params: dict | None = None
    ) -> dict:
        """Make a multipart/form-data POST request for LogicModule imports.

        The LM import endpoints require multipart file upload rather than JSON body.
        The definition is serialized to JSON and uploaded as a file part named 'file'.
        Content-Type is not set explicitly so httpx auto-generates the multipart boundary.

        Args:
            path: API resource path (e.g., /setting/datasources/importjson).
            definition: LogicModule definition dict to import.
            params: Optional query parameters (e.g., handleConflict).

        Returns:
            Parsed JSON response as dict.

        Raises:
            LMConnectionError: If connection fails.
            AuthenticationError: For 401 responses.
            LMPermissionError: For 403 responses.
            NotFoundError: For 404 responses.
            RateLimitError: For 429 responses after retries exhausted.
            ServerError: For 5xx responses.
            LMError: For other 4xx responses.
        """
        url = f"{self.base_url}{path}"
        # Handle string definitions to prevent double-serialization
        json_str = definition if isinstance(definition, str) else json.dumps(definition)

        # Build headers without Content-Type (httpx sets multipart boundary)
        headers = {
            "X-Version": str(self.api_version),
        }
        # Use empty body string for auth signature (multipart bodies aren't signed)
        headers.update(self.auth.get_auth_headers("POST", path, ""))

        files = {"file": ("import.json", json_str, "application/json")}

        log_api_request("POST", path, None)

        last_retry_after: int | None = None
        last_message = "Rate limited"

        for attempt in range(self.max_retries + 1):
            request_start = time.monotonic()
            try:
                response = await self._client.request(
                    method="POST",
                    url=url,
                    files=files,
                    headers=headers,
                    params=params,
                )
            except httpx.ConnectError as e:
                raise LMConnectionError(f"Failed to connect to {self.base_url}: {e}") from e

            # Retry on rate limit (429) or server errors (5xx)
            if response.status_code == 429 or response.status_code >= 500:
                message, retry_after = self._parse_error_response(response)
                last_message = message
                last_retry_after = retry_after

                if attempt < self.max_retries:
                    base_backoff = 2**attempt
                    jitter = random.uniform(0, 0.5 * base_backoff)
                    wait_time = base_backoff + jitter
                    if retry_after is not None:
                        wait_time = min(retry_after, wait_time)
                    await asyncio.sleep(wait_time)
                    continue

            if response.status_code >= 400:
                message, retry_after = self._parse_error_response(response)
                self._raise_for_status(response, message, retry_after)

            elapsed = time.monotonic() - request_start
            log_api_response(response.status_code, elapsed, path)
            data = response.json()
            self._check_response_body_errors(data)
            return data

        raise RateLimitError(last_message, retry_after=last_retry_after)

    async def put(self, path: str, json_body: dict | None = None) -> dict:
        """Make a PUT request.

        Args:
            path: API resource path.
            json_body: JSON body.

        Returns:
            Parsed JSON response.
        """
        return await self.request("PUT", path, json_body=json_body)

    async def patch(self, path: str, json_body: dict | None = None) -> dict:
        """Make a PATCH request.

        Args:
            path: API resource path.
            json_body: JSON body.

        Returns:
            Parsed JSON response.
        """
        return await self.request("PATCH", path, json_body=json_body)

    async def delete(self, path: str, params: dict | None = None) -> dict:
        """Make a DELETE request.

        Args:
            path: API resource path.
            params: Query parameters.

        Returns:
            Parsed JSON response.
        """
        return await self.request("DELETE", path, params=params)

    async def ingest_post(
        self,
        path: str,
        json_body: list | dict | None = None,
    ) -> dict:
        """Make a POST request to ingestion API.

        Uses the ingest_url base instead of the standard base_url.
        Ingestion APIs use paths like /rest/log/ingest.

        Args:
            path: Ingestion API path (e.g., /rest/log/ingest).
            json_body: JSON body (list of log entries or metric payload).

        Returns:
            Parsed JSON response.

        Raises:
            ConfigurationError: If ingest_url is not configured.
        """
        from lm_mcp.exceptions import ConfigurationError

        if not self.ingest_url:
            raise ConfigurationError(
                "Ingestion URL not configured. Set ingest_url when creating client."
            )

        url = f"{self.ingest_url}{path}"
        # See note on ``request()`` -- empty body must serialize as ``"{}"`` so
        # the LMv1 HMAC signature matches what httpx actually transmits.
        body_str = _serialize_json_body(json_body)
        content = body_str.encode("utf-8") if json_body is not None else None

        # Build headers with auth for the ingest path
        headers = {
            "Content-Type": "application/json",
        }
        headers.update(self.auth.get_auth_headers("POST", path, body_str))

        last_retry_after: int | None = None
        last_message = "Rate limited"

        for attempt in range(self.max_retries + 1):
            try:
                response = await self._client.request(
                    method="POST",
                    url=url,
                    content=content,
                    headers=headers,
                )
            except httpx.ConnectError as e:
                raise LMConnectionError(f"Failed to connect to {self.ingest_url}: {e}") from e

            # Retry on rate limit (429) or server errors (5xx)
            if response.status_code == 429 or response.status_code >= 500:
                message, retry_after = self._parse_error_response(response)
                last_message = message
                last_retry_after = retry_after

                if attempt < self.max_retries:
                    base_backoff = 2**attempt
                    jitter = random.uniform(0, 0.5 * base_backoff)
                    wait_time = base_backoff + jitter
                    if retry_after is not None:
                        wait_time = min(retry_after, wait_time)
                    await asyncio.sleep(wait_time)
                    continue

            # Handle 202 Accepted (success for ingestion)
            if response.status_code == 202:
                try:
                    data = response.json()
                except (json.JSONDecodeError, ValueError):
                    return {"success": True, "message": "Accepted"}
                # A 202 can still carry per-record rejection details in the body;
                # surface them instead of reporting blanket success (silent data loss).
                self._check_response_body_errors(data)
                if isinstance(data, dict) and data.get("success") is False:
                    raise LMError(
                        message=str(
                            data.get("message")
                            or data.get("errorMessage")
                            or "Ingestion reported failure in a 202 response"
                        ),
                        code="INGEST_PARTIAL_FAILURE",
                    )
                return data

            if response.status_code >= 400:
                message, retry_after = self._parse_error_response(response)
                self._raise_for_status(response, message, retry_after)

            return response.json()

        raise RateLimitError(last_message, retry_after=last_retry_after)
