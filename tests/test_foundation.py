# Description: Foundation tests verifying all core modules work together.
# Description: Tests package exports, configuration instantiation, and exception handling.

import json
import re
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
# A stated total ("306 tools", "306 structured tools", "**306 Tools**"); smaller numbers
# before "tools" describe subsets, such as a category or a client's cap.
_TOOL_TOTAL_RE = re.compile(r"\b(\d{3})\s+(?:structured\s+)?tools\b", re.IGNORECASE)
_TOOL_BREAKDOWN_RE = re.compile(r"\((\d+) LM \+ (\d+) AAP \+ (\d+) Terraform \+ (\d+) watsonx\)")


def _project_version() -> str:
    return tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())["project"]["version"]


class TestPackageExports:
    """Tests that verify package exports are accessible."""

    def test_version_exported_and_synced(self):
        """Package version is accessible and matches the installed metadata.

        Guards against release bumps that update pyproject.toml but miss
        __init__.py: the two must always agree, so a drifted bump fails here
        instead of shipping a wheel that self-reports the previous version.
        """
        from importlib.metadata import version

        from lm_mcp import __version__

        assert __version__ == version("lm-mcp")

    def test_lm_config_exported(self):
        """LMConfig is exported from package root."""
        from lm_mcp import LMConfig

        assert LMConfig is not None

    def test_all_exceptions_exported(self):
        """All exception classes are exported from package root."""
        from lm_mcp import (
            AuthenticationError,
            ConfigurationError,
            LMConnectionError,
            LMError,
            LMPermissionError,
            NotFoundError,
            RateLimitError,
            ServerError,
        )

        assert LMError is not None
        assert ConfigurationError is not None
        assert AuthenticationError is not None
        assert LMPermissionError is not None
        assert NotFoundError is not None
        assert RateLimitError is not None
        assert ServerError is not None
        assert LMConnectionError is not None


class TestReleaseMetadata:
    """R1.7: the published manifests and the docs agree with the package they describe."""

    def test_server_json_versions_match_pyproject(self):
        """Both server.json version fields carry pyproject.toml's version.

        The MCP registry reads server.json, so a bump that misses it advertises the
        previous release.
        """
        server = json.loads((REPO_ROOT / "server.json").read_text())

        assert server["version"] == _project_version()
        assert [package["version"] for package in server["packages"]] == [_project_version()]

    @pytest.mark.parametrize("doc", ["README.md", "documentation/client-setup.md", "server.json"])
    def test_docs_state_the_registry_tool_count(self, doc):
        """Every total tool count a doc or the registry manifest states is the registry's."""
        from lm_mcp.registry import AWX_TOOLS, TF_TOOLS, TOOLS, WATSONX_TOOLS

        total = len(TOOLS) + len(AWX_TOOLS) + len(WATSONX_TOOLS) + len(TF_TOOLS)
        stated = [int(n) for n in _TOOL_TOTAL_RE.findall((REPO_ROOT / doc).read_text())]

        assert stated, f"{doc} states no tool count"
        assert set(stated) == {total}, f"{doc} states {sorted(set(stated))}, registry has {total}"

    def test_readme_tool_breakdown_matches_the_registry(self):
        """The README's per-integration breakdown matches each registry list."""
        from lm_mcp.registry import AWX_TOOLS, TF_TOOLS, TOOLS, WATSONX_TOOLS

        match = _TOOL_BREAKDOWN_RE.search((REPO_ROOT / "README.md").read_text())

        assert match, "README.md has no (LM + AAP + Terraform + watsonx) tool breakdown"
        counts = (len(TOOLS), len(AWX_TOOLS), len(TF_TOOLS), len(WATSONX_TOOLS))
        assert tuple(int(n) for n in match.groups()) == counts


class TestFoundationIntegration:
    """Integration tests for foundation components."""

    def test_config_instantiation_with_env(self, monkeypatch):
        """LMConfig can be instantiated with mock environment variables."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test_token")

        from lm_mcp import LMConfig

        config = LMConfig()
        assert config.portal == "test.logicmonitor.com"
        assert config.base_url == "https://test.logicmonitor.com/santaba/rest"

    def test_exceptions_can_be_raised_and_converted(self):
        """Exceptions can be raised and converted to dict format."""
        from lm_mcp import AuthenticationError, LMError, RateLimitError

        # Test base error
        base_error = LMError("Base error", code="TEST", suggestion="Fix it")
        assert base_error.to_dict() == {
            "error": True,
            "code": "TEST",
            "message": "Base error",
            "suggestion": "Fix it",
        }

        # Test auth error with defaults
        auth_error = AuthenticationError("Auth failed")
        auth_dict = auth_error.to_dict()
        assert auth_dict["code"] == "AUTH_FAILED"
        assert "suggestion" in auth_dict

        # Test rate limit with retry_after
        rate_error = RateLimitError("Rate limited", retry_after=60)
        rate_dict = rate_error.to_dict()
        assert rate_dict["code"] == "RATE_LIMITED"
        assert rate_dict["retry_after"] == 60

    def test_exception_inheritance(self):
        """All custom exceptions inherit from LMError."""
        from lm_mcp import (
            AuthenticationError,
            ConfigurationError,
            LMConnectionError,
            LMError,
            LMPermissionError,
            NotFoundError,
            RateLimitError,
            ServerError,
        )

        exceptions = [
            ConfigurationError("test"),
            AuthenticationError("test"),
            LMPermissionError("test"),
            NotFoundError("test"),
            RateLimitError("test"),
            ServerError("test"),
            LMConnectionError("test"),
        ]

        for exc in exceptions:
            assert isinstance(exc, LMError), f"{type(exc).__name__} should inherit from LMError"

    def test_config_validation_raises_correct_exception_type(self, monkeypatch):
        """Config validation errors are ValueError not our custom exceptions."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.delenv("LM_BEARER_TOKEN", raising=False)
        monkeypatch.delenv("LM_ACCESS_ID", raising=False)
        monkeypatch.delenv("LM_ACCESS_KEY", raising=False)

        from lm_mcp import LMConfig

        with pytest.raises(ValueError, match="Authentication required"):
            LMConfig()
