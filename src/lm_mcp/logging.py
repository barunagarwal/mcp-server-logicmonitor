# Description: Structured logging module for LogicMonitor MCP server.
# Description: Provides helper functions for API request and write audit logging.

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from lm_mcp.config import LMConfig

# Module-level loggers
_client_logger = logging.getLogger("lm_mcp.client")
_audit_logger = logging.getLogger("lm_mcp.audit")

# The one stderr handler configure_logging installs on the root logger.
STDERR_HANDLER_NAME = "lm_mcp.stderr"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

# What an audit line shows in place of a credential-shaped argument value.
REDACTED = "***"
# Split camelCase and acronym boundaries so apiKey and APIKey read as api_key.
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
# A whole credential word (optionally plural) between key separators or ends: the
# generic words, the LogicMonitor credential property words (ssh.pass, snmp.community,
# snmp.auth, snmp.priv) and the cloud compounds written as one word (aws.secretkey).
_CREDENTIAL_WORD = re.compile(
    r"(?:^|_)(?:password|passwd|passphrase|pass|token|secret|key|credential"
    r"|community|auth|priv|extra_vars|apikey|secretkey|accesskey|privatekey|clientsecret)"
    r"s?(?:_|$)"
)
# A key naming an identifier (token_id, api_key_id, device_ids) is not a credential.
_IDENTIFIER_SUFFIX = re.compile(r"(?:^|_)ids?$")
# Name/value pairs whose value is a credential when the paired name is one:
# update_device_property's arguments, and the {name, value} items of LM property lists.
_PAIRED_KEYS = (("property_name", "property_value"), ("name", "value"))


def configure_logging(config: LMConfig) -> logging.Handler:
    """Send the server's log records to stderr at LM_LOG_LEVEL.

    Sets the root logger to the configured level and installs one named
    StreamHandler on stderr; a second call reuses that handler, so the level
    can be re-applied without duplicating output. stdout is never used: under
    the stdio transport it carries the JSON-RPC stream.

    Args:
        config: Server configuration; ``log_level`` is one of debug, info,
            warning, error.

    Returns:
        The stderr handler in place after the call.
    """
    root = logging.getLogger()
    root.setLevel(logging.getLevelNamesMapping()[config.log_level.upper()])
    for existing in root.handlers:
        if existing.get_name() == STDERR_HANDLER_NAME:
            return existing
    handler = logging.StreamHandler(sys.stderr)
    handler.set_name(STDERR_HANDLER_NAME)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root.addHandler(handler)
    return handler


def _normalize_key(key: str) -> str:
    """Lower-case a key with every word boundary written as an underscore."""
    return _CAMEL_BOUNDARY.sub("_", key).replace("-", "_").replace(".", "_").lower()


def is_sensitive_key(key: str) -> bool:
    """Whether an argument key names a credential whose value must not be logged.

    Matches a whole word from ``_CREDENTIAL_WORD`` (the generic words such as
    password, token, secret and key, the LogicMonitor property words pass,
    community, auth and priv, and the one-word compounds such as secretkey,
    singular or plural) at a snake_case, kebab-case, dotted or camelCase
    boundary, case-insensitively, so ``api_key``, ``apiKey``, ``ssh.pass`` and
    ``LM_BEARER_TOKEN`` match while ``keyword`` and ``tokenizer`` do not. A key
    ending in ``id`` or ``ids`` names an identifier, not a credential.

    Args:
        key: The argument key.

    Returns:
        True when the value under the key must be redacted.
    """
    normalized = _normalize_key(key)
    if _IDENTIFIER_SUFFIX.search(normalized):
        return False
    return _CREDENTIAL_WORD.search(normalized) is not None


def redact_arguments(arguments: Any) -> Any:
    """Return a copy of tool arguments with credential-shaped values replaced.

    Walks nested objects and lists. A value under a sensitive key is replaced
    whole, whatever its shape, so an ``extra_vars`` object is hidden entirely.
    An object that pairs a name with a value (``property_name`` with
    ``property_value``, or ``name`` with ``value``) has the value replaced when
    the name is a credential property such as ``ssh.pass``. The input is not
    modified.

    Args:
        arguments: The arguments passed to a tool, or any value inside them.

    Returns:
        The same structure with sensitive values replaced by ``***``.
    """
    if isinstance(arguments, Mapping):
        redacted = {
            key: REDACTED
            if isinstance(key, str) and is_sensitive_key(key)
            else redact_arguments(value)
            for key, value in arguments.items()
        }
        for name_key, value_key in _PAIRED_KEYS:
            name = arguments.get(name_key)
            if value_key in redacted and isinstance(name, str) and is_sensitive_key(name):
                redacted[value_key] = REDACTED
        return redacted
    if isinstance(arguments, list):
        return [redact_arguments(value) for value in arguments]
    return arguments


def log_api_request(
    method: str,
    path: str,
    params: dict | None = None,
) -> None:
    """Log an API request at DEBUG level.

    Uses the lm_mcp.client logger. Only produces output when the logger
    level is set to DEBUG or lower; zero overhead otherwise due to
    isEnabledFor guard.

    Args:
        method: HTTP method.
        path: API resource path.
        params: Query parameters.
    """
    if _client_logger.isEnabledFor(logging.DEBUG):
        _client_logger.debug(
            "%s %s params=%s",
            method,
            path,
            params,
        )


def log_api_response(
    status_code: int,
    elapsed_seconds: float,
    path: str,
) -> None:
    """Log an API response at DEBUG level.

    Args:
        status_code: HTTP response status code.
        elapsed_seconds: Request duration in seconds.
        path: API resource path.
    """
    if _client_logger.isEnabledFor(logging.DEBUG):
        _client_logger.debug(
            "%s %d %.0fms",
            path,
            status_code,
            elapsed_seconds * 1000,
        )


# Prefixes that identify write operations
WRITE_TOOL_PREFIXES = (
    "create_",
    "update_",
    "delete_",
    "acknowledge_",
    "add_",
    "run_",
    "bulk_",
    "import_",
    "ingest_",
    "push_",
    "launch_",
    "cancel_",
    "relaunch_",
    "enable_",
    "disable_",
    "restart_",
    "sync_",
    "execute_",
    "recover_",
    "collect_",
    "set_action_rule",
    "terraform_init",
    "terraform_plan",
    "terraform_apply",
    "terraform_destroy",
    "terraform_import",
    "terraform_write",
    "use_portal",
    "reload_portals",
)


def is_write_tool(tool_name: str) -> bool:
    """Check if a tool name indicates a write operation.

    Args:
        tool_name: MCP tool name to check.

    Returns:
        True if the tool performs write/modify operations.
    """
    return any(tool_name.startswith(prefix) for prefix in WRITE_TOOL_PREFIXES)


def _portal_marker() -> str:
    """Return " portal=<name>" for audit lines in multi-portal mode, else "".

    Looked up lazily so single-portal deployments pay nothing and audit logging
    never depends on portal state being importable.
    """
    try:
        from lm_mcp.config import get_config

        if not get_config().multi_portal:
            return ""
        from lm_mcp import portals

        name = portals.active().get("active")
        return f" portal={name}" if name else ""
    except Exception:
        _audit_logger.debug("could not resolve active portal for audit line", exc_info=True)
        return ""


def log_write_operation(
    tool_name: str,
    arguments: dict,
    success: bool,
) -> None:
    """Log a write operation for audit trail purposes.

    Successful operations are logged at INFO level.
    Failed operations are logged at WARNING level.
    In multi-portal mode each line carries the active portal name.
    Argument values under credential-shaped keys are redacted first
    (see :func:`redact_arguments`).

    Args:
        tool_name: Name of the MCP tool.
        arguments: Arguments passed to the tool.
        success: Whether the operation succeeded.
    """
    shown = redact_arguments(arguments)
    if success:
        _audit_logger.info(
            "Write operation: %s args=%s%s",
            tool_name,
            shown,
            _portal_marker(),
        )
    else:
        _audit_logger.warning(
            "Write operation failed: %s args=%s%s",
            tool_name,
            shown,
            _portal_marker(),
        )
