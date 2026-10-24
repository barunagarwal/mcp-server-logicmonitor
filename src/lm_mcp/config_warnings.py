# Description: Logging for optional-integration settings that are set but cannot be used.
# Description: Names the environment variables involved without logging their values.

from __future__ import annotations

import logging
import os

from pydantic import ValidationError
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


def log_unusable_config(
    integration: str,
    settings_cls: type[BaseSettings],
    exc: Exception,
    gate: str | None,
) -> None:
    """Log why an integration's settings did not load, unless it was never configured.

    An unset gate variable means the operator did not configure the integration,
    the normal case, and nothing is logged. Otherwise the failure is logged at
    WARNING: a validation error by variable name and message only, so values such
    as tokens never reach the log; any other error with its traceback.

    Args:
        integration: Name used in the message, such as "AWX".
        settings_cls: The settings class whose construction failed.
        exc: The exception its construction raised.
        gate: The variable whose absence means "not configured", or None when
            the integration has no such variable.
    """
    if gate is not None and not any(name.upper() == gate for name in os.environ):
        return
    prefix = str(settings_cls.model_config.get("env_prefix", ""))
    if isinstance(exc, ValidationError):
        problems = "; ".join(
            f"{prefix}{str(err['loc'][0]).upper() if err['loc'] else ''}: {err['msg']}"
            for err in exc.errors()
        )
        logger.warning("%s is disabled: its configuration is unusable (%s)", integration, problems)
    else:
        logger.warning(
            "%s is disabled: its %s* configuration could not be loaded: %s",
            integration,
            prefix,
            exc,
            exc_info=True,
        )
