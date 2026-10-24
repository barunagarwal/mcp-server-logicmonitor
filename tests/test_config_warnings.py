# Description: Tests that unusable optional-integration configuration is logged, not dropped.
# Description: Covers the watsonx, HuggingFace and Terraform loaders and the unconfigured silence.

from __future__ import annotations

import logging
import sys
import types

import pytest

from lm_mcp.awx_config import get_awx_config, reset_awx_config
from lm_mcp.hf_config import get_hf_config, reset_hf_config
from lm_mcp.ibm_config import get_watsonx_config, reset_watsonx_config
from lm_mcp.terraform_config import get_terraform_config, reset_terraform_config

_LOADERS = {
    "awx": (get_awx_config, reset_awx_config),
    "watsonx": (get_watsonx_config, reset_watsonx_config),
    "huggingface": (get_hf_config, reset_hf_config),
    "terraform": (get_terraform_config, reset_terraform_config),
}


@pytest.fixture(autouse=True)
def _clean_integration_env(monkeypatch):
    """No integration variable from the developer's shell leaks into a case."""
    import os

    for name in list(os.environ):
        if name.startswith(("AWX_", "WATSONX_", "HF_", "TF_")):
            monkeypatch.delenv(name)
    for _get, reset in _LOADERS.values():
        reset()
    yield
    for _get, reset in _LOADERS.values():
        reset()


def _warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]


@pytest.mark.parametrize(
    ("loader", "env", "named"),
    [
        (
            "watsonx",
            {"WATSONX_API_KEY": "key-0123", "WATSONX_PROJECT_ID": "p1", "WATSONX_TIMEOUT": "soon"},
            "WATSONX_TIMEOUT",
        ),
        ("terraform", {"TF_WORKSPACE_DIR": "/srv/tf", "TF_TIMEOUT": "soon"}, "TF_TIMEOUT"),
    ],
)
def test_unusable_value_is_logged_by_name(loader, env, named, monkeypatch, caplog):
    """R4.5: a configured integration with an unreadable value logs the variable and is off."""
    get, _reset = _LOADERS[loader]
    for name, value in env.items():
        monkeypatch.setenv(name, value)

    with caplog.at_level(logging.WARNING, logger="lm_mcp"):
        assert get() is None

    (message,) = _warnings(caplog)
    assert named in message
    assert "soon" not in message
    assert "key-0123" not in message


def test_huggingface_settings_failure_is_logged(monkeypatch, caplog):
    """R4.5: the HuggingFace loader logs a settings failure with its traceback.

    Every HuggingFaceConfig field is a string with a default, so no HF_ value
    fails validation; the failure here comes from the settings class itself.
    """
    import lm_mcp.hf_config as hf_config

    class BrokenSettings(hf_config.HuggingFaceConfig):
        def __init__(self) -> None:
            raise RuntimeError("settings source failed")

    monkeypatch.setitem(sys.modules, "torch", types.ModuleType("torch"))
    monkeypatch.setattr(hf_config, "HuggingFaceConfig", BrokenSettings)

    with caplog.at_level(logging.WARNING, logger="lm_mcp"):
        assert get_hf_config() is None

    (record,) = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert "HF_" in record.getMessage()
    assert "settings source failed" in record.getMessage()
    assert record.exc_info is not None


@pytest.mark.parametrize(
    ("loader", "unrelated"),
    [
        ("awx", {}),
        ("watsonx", {}),
        ("terraform", {"TF_LOG": "DEBUG", "TF_VAR_region": "us-east-1"}),
    ],
)
def test_unconfigured_integration_is_silent(loader, unrelated, monkeypatch, caplog):
    """R4.5: an integration whose gate variable is unset returns None and logs nothing.

    Terraform's own TF_ variables share the prefix and must not read as configuration.
    """
    get, _reset = _LOADERS[loader]
    for name, value in unrelated.items():
        monkeypatch.setenv(name, value)

    with caplog.at_level(logging.DEBUG, logger="lm_mcp"):
        assert get() is None

    assert _warnings(caplog) == []
