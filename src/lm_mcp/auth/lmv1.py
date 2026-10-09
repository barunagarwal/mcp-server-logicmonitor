# Description: LMv1 HMAC-SHA256 authentication provider for LogicMonitor API.
# Description: Provides signature-based authentication for ingestion endpoints.

import base64
import hashlib
import hmac
import time

from lm_mcp.auth import AuthProvider
from lm_mcp.exceptions import ConfigurationError


class LMv1Auth(AuthProvider):
    """LMv1 HMAC-SHA256 authentication provider.

    Uses HMAC-SHA256 signatures for request authentication. Required for
    LogicMonitor ingestion APIs (logs, metrics) that don't support Bearer tokens.

    The signature is computed as:
        HMAC-SHA256(access_key, method + timestamp + body + resource_path)

    The Authorization header format is:
        LMv1 access_id:base64(hex(signature)):timestamp
    """

    def __init__(self, access_id: str | None, access_key: str | None):
        """Initialize with LMv1 credentials.

        Args:
            access_id: The LMv1 access ID.
            access_key: The LMv1 access key (secret).

        Raises:
            ConfigurationError: If access_id or access_key is empty or None.
        """
        if not access_id:
            raise ConfigurationError("LMv1 access_id is required")
        if not access_key:
            raise ConfigurationError("LMv1 access_key is required")

        self.access_id = access_id
        self.access_key = access_key

    def get_auth_headers(
        self,
        method: str,
        resource_path: str,
        body: str = "",
    ) -> dict[str, str]:
        """Generate LMv1 authentication header.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE, etc.)
            resource_path: API path (e.g., /santaba/rest/log/ingest)
            body: Request body as string

        Returns:
            Dict with Authorization header containing LMv1 signature.
        """
        timestamp_ms = int(time.time() * 1000)
        signature = self._compute_signature(method, resource_path, body, timestamp_ms)

        return {"Authorization": f"LMv1 {self.access_id}:{signature}:{timestamp_ms}"}

    def _compute_signature(
        self,
        method: str,
        resource_path: str,
        body: str,
        timestamp_ms: int,
    ) -> str:
        """Compute HMAC-SHA256 signature for the request.

        Args:
            method: HTTP method.
            resource_path: API path.
            body: Request body.
            timestamp_ms: Timestamp in milliseconds.

        Returns:
            Base64-encoded hex HMAC-SHA256 signature.
        """
        signature_string = f"{method}{timestamp_ms}{body}{resource_path}"

        # LogicMonitor expects base64 of the HEX digest (not of the raw 32 bytes).
        # Signing the raw digest is rejected with 401 on every REST endpoint.
        hex_digest = hmac.new(
            self.access_key.encode("utf-8"),
            signature_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return base64.b64encode(hex_digest.encode("utf-8")).decode("utf-8")
