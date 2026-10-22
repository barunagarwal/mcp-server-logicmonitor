# Description: Custom exception classes for LogicMonitor MCP Server.
# Description: Provides structured error handling with codes and suggestions for API operations.


class LMError(Exception):
    """Base exception for LogicMonitor MCP errors.

    All LM-specific exceptions inherit from this class, providing
    consistent error handling with codes and optional suggestions.
    ``details`` carries the raw server message when ``message`` has been
    rewritten into a user-facing hint (e.g., by the Jackson translator
    in the client), so debugging context is not lost.
    """

    def __init__(
        self,
        message: str,
        code: str = "LM_ERROR",
        suggestion: str | None = None,
        details: str | None = None,
    ):
        self.message = message
        self.code = code
        self.suggestion = suggestion
        self.details = details
        super().__init__(message)

    def to_dict(self) -> dict:
        """Return error as dict for tool responses."""
        result = {
            "error": True,
            "code": self.code,
            "message": self.message,
        }
        if self.suggestion:
            result["suggestion"] = self.suggestion
        if self.details:
            result["details"] = self.details
        return result


class ConfigurationError(LMError):
    """Raised when configuration is invalid or missing."""

    def __init__(self, message: str, suggestion: str | None = None):
        super().__init__(
            message=message,
            code="CONFIG_ERROR",
            suggestion=suggestion
            or "Check your environment variables and .env file configuration.",
        )


class AuthenticationError(LMError):
    """Raised when authentication fails."""

    def __init__(self, message: str, suggestion: str | None = None):
        super().__init__(
            message=message,
            code="AUTH_FAILED",
            suggestion=suggestion
            or "Check your LM_ACCESS_ID/LM_ACCESS_KEY or LM_BEARER_TOKEN credentials.",
        )


class LMPermissionError(LMError):
    """Raised when the API token lacks required permissions."""

    def __init__(self, message: str, suggestion: str | None = None):
        super().__init__(
            message=message,
            code="PERMISSION_DENIED",
            suggestion=suggestion
            or "Your API token may lack required permissions. Contact your LM admin.",
        )


class NotFoundError(LMError):
    """Raised when a requested resource does not exist."""

    def __init__(self, message: str, suggestion: str | None = None):
        super().__init__(
            message=message,
            code="NOT_FOUND",
            suggestion=suggestion
            or "The requested resource does not exist. Verify the ID is correct.",
        )


class ValidationError(LMError):
    """Raised when a request is refused before it is sent because an input is malformed."""

    def __init__(self, message: str, suggestion: str | None = None):
        super().__init__(
            message=message,
            code="VALIDATION_ERROR",
            suggestion=suggestion or "Check the arguments against the tool's input schema.",
        )


class RateLimitError(LMError):
    """Raised when API rate limits are exceeded."""

    def __init__(
        self,
        message: str,
        retry_after: int | None = None,
        suggestion: str | None = None,
    ):
        self.retry_after = retry_after
        default_suggestion = "API rate limit reached."
        if retry_after:
            default_suggestion = f"API rate limit reached. Wait {retry_after} seconds and retry."
        super().__init__(
            message=message,
            code="RATE_LIMITED",
            suggestion=suggestion or default_suggestion,
        )

    def to_dict(self) -> dict:
        """Return error as dict, including retry_after if present."""
        result = super().to_dict()
        if self.retry_after is not None:
            result["retry_after"] = self.retry_after
        return result


class ServerError(LMError):
    """Raised when LogicMonitor API returns a server error."""

    def __init__(self, message: str, suggestion: str | None = None):
        super().__init__(
            message=message,
            code="SERVER_ERROR",
            suggestion=suggestion
            or "LogicMonitor API returned a server error. Try again later or check LM status.",
        )


class LMConnectionError(LMError):
    """Raised when connection to LogicMonitor fails."""

    def __init__(self, message: str, suggestion: str | None = None):
        super().__init__(
            message=message,
            code="CONNECTION_FAILED",
            suggestion=suggestion
            or "Cannot connect to LogicMonitor. Check LM_PORTAL and network access.",
        )
