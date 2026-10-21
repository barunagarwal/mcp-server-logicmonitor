# Description: LogicMonitor MCP Server package.
# Description: Provides MCP tools for interacting with LogicMonitor REST API v3.

from lm_mcp.config import LMConfig, get_config, reset_config
from lm_mcp.exceptions import (
    AuthenticationError,
    ConfigurationError,
    LMConnectionError,
    LMError,
    LMPermissionError,
    NotFoundError,
    RateLimitError,
    ServerError,
)

__version__ = "4.2.1"

__all__ = [
    "AuthenticationError",
    "ConfigurationError",
    "LMConfig",
    "LMConnectionError",
    "LMError",
    "LMPermissionError",
    "NotFoundError",
    "RateLimitError",
    "ServerError",
    "__version__",
    "get_config",
    "reset_config",
]
