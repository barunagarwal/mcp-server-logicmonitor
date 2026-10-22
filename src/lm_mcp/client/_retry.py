# Description: Retry policy and transport-error translation shared by the HTTP clients.
# Description: Decides which responses may be resent and how long to wait between tries.

from __future__ import annotations

import contextlib
import random

import httpx

from lm_mcp.exceptions import LMConnectionError

# Methods safe to resend after a 5xx: repeating them cannot apply a change twice.
IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "PUT", "DELETE"})

# Default ceiling in seconds on a wait a server's Retry-After can impose.
DEFAULT_RETRY_AFTER_CAP = 120

# Failures before any response arrives: timeouts, connect, read and write errors,
# protocol and proxy errors. Each is translated to LMConnectionError and not
# resent: past the connect phase the server may already have acted.
TRANSPORT_ERRORS = (httpx.TransportError,)


def should_retry(method: str, status: int) -> bool:
    """Return whether a response with this status may be retried for this method.

    A 429 means the request was refused unprocessed, so any method is resent.
    A 5xx may come after the server applied the change, so only idempotent
    methods are resent; a POST or PATCH could otherwise create or apply twice.
    """
    if status == 429:
        return True
    return status >= 500 and method.upper() in IDEMPOTENT_METHODS


def retry_after_seconds(response: httpx.Response) -> int | None:
    """Return a response's Retry-After in whole seconds, or None if absent or not a number."""
    if "Retry-After" not in response.headers:
        return None
    with contextlib.suppress(ValueError):
        return int(response.headers["Retry-After"])
    return None


def backoff(attempt: int, retry_after: int | None, cap: int) -> float:
    """Seconds to wait before retry ``attempt + 1``.

    Exponential backoff with jitter spreads out retries from many clients. A
    server's Retry-After can lengthen the wait but never shorten it, and the
    result never exceeds ``cap``.
    """
    base_backoff = 2.0**attempt
    wait = base_backoff + random.uniform(0, 0.5 * base_backoff)
    if retry_after is not None:
        wait = max(retry_after, wait)
    return min(wait, cap)


def transport_error(exc: Exception, service: str, method: str, url: str) -> LMConnectionError:
    """Translate an httpx transport failure into LMConnectionError.

    httpx often raises these with an empty message, so the result always names
    the failure kind, the method and the URL.
    """
    if isinstance(exc, httpx.TimeoutException):
        what = "timed out"
    elif isinstance(exc, httpx.ConnectError):
        what = "could not connect"
    elif isinstance(exc, (httpx.NetworkError, httpx.ProtocolError)):
        what = "lost its connection"
    else:
        what = "failed"
    detail = str(exc) or "no detail from the HTTP library"
    return LMConnectionError(
        f"{service} request {method} {url} {what} ({type(exc).__name__}: {detail})"
    )
