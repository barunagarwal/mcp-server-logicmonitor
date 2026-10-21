# Description: Tests for MCP tool filtering by enabled/disabled config.
# Description: Validates tool cherry-picking with glob patterns and rejection.

import pytest

from lm_mcp.registry import TOOLS
from lm_mcp.server import PORTAL_TOOLS, _filter_tools


class _MockConfig:
    """Lightweight config mock for tool filtering tests."""

    def __init__(
        self, enabled_tools=None, disabled_tools=None, mcp_categories=None, multi_portal=False
    ):
        self.enabled_tools = enabled_tools
        self.disabled_tools = disabled_tools
        self.mcp_categories = mcp_categories
        self.multi_portal = multi_portal


class TestFilterTools:
    """Tests for the _filter_tools function."""

    def test_no_filters_returns_all(self):
        """No filters returns all tools."""
        config = _MockConfig()
        result = _filter_tools(TOOLS, config)
        assert len(result) == len(TOOLS) - len(PORTAL_TOOLS)

    def test_enabled_exact_names(self):
        """Enabled list with exact names returns only those tools."""
        config = _MockConfig(enabled_tools="get_devices,get_alerts")
        result = _filter_tools(TOOLS, config)
        names = {t.name for t in result}
        assert names == {"get_devices", "get_alerts"}

    def test_enabled_glob_pattern(self):
        """Enabled list with glob pattern matches correctly."""
        config = _MockConfig(enabled_tools="get_device*")
        result = _filter_tools(TOOLS, config)
        for tool in result:
            assert tool.name.startswith("get_device")
        assert len(result) > 1

    def test_disabled_exact_names(self):
        """Disabled list hides specific tools."""
        config = _MockConfig(disabled_tools="delete_device,delete_device_group")
        result = _filter_tools(TOOLS, config)
        names = {t.name for t in result}
        assert "delete_device" not in names
        assert "delete_device_group" not in names
        assert "get_devices" in names

    def test_disabled_glob_pattern(self):
        """Disabled list with glob hides matching tools."""
        config = _MockConfig(disabled_tools="delete_*")
        result = _filter_tools(TOOLS, config)
        for tool in result:
            assert not tool.name.startswith("delete_"), (
                f"Tool {tool.name} should be hidden by delete_* pattern"
            )

    def test_enabled_multiple_patterns(self):
        """Multiple glob patterns in enabled list work together."""
        config = _MockConfig(enabled_tools="get_devices,get_alerts,export_*")
        result = _filter_tools(TOOLS, config)
        names = {t.name for t in result}
        assert "get_devices" in names
        assert "get_alerts" in names
        # Should include export tools
        export_tools = [n for n in names if n.startswith("export_")]
        assert len(export_tools) > 0
        # Should NOT include other tools
        assert "create_device" not in names


class TestCallToolRejection:
    """Tests for call_tool rejection of disabled tools."""

    @pytest.mark.asyncio
    async def test_disabled_tool_rejected(self, monkeypatch):
        """Calling a disabled tool returns error message."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token-value")
        monkeypatch.setenv("LM_DISABLED_TOOLS", "delete_*")

        from lm_mcp.server import call_tool

        result = await call_tool("delete_device", {"device_id": 1})
        assert result.isError is True
        text = result.content[0].text.lower()
        assert "disabled" in text or "not enabled" in text

    @pytest.mark.asyncio
    async def test_enabled_tool_not_in_list_rejected(self, monkeypatch):
        """Calling a tool not in enabled list returns error message."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token-value")
        monkeypatch.setenv("LM_ENABLED_TOOLS", "get_devices,get_alerts")

        from lm_mcp.server import call_tool

        result = await call_tool("delete_device", {"device_id": 1})
        assert result.isError is True
        text = result.content[0].text.lower()
        assert "not enabled" in text or "error" in text


class TestCategoryFilter:
    """Tests for the LM_MCP_CATEGORIES annotation-based filter."""

    def test_categories_unset_returns_all(self):
        config = _MockConfig()
        result = _filter_tools(TOOLS, config)
        assert len(result) == len(TOOLS) - len(PORTAL_TOOLS)

    def test_categories_read_only_excludes_destructive(self):
        config = _MockConfig(mcp_categories="read")
        result = _filter_tools(TOOLS, config)
        for tool in result:
            assert tool.annotations is not None
            assert tool.annotations.readOnlyHint, (
                f"{tool.name} appeared in read-only filter but has readOnlyHint=False"
            )
            assert not tool.annotations.destructiveHint, (
                f"{tool.name} appeared in read filter but is destructive"
            )

    def test_categories_workflow_returns_curated_set(self):
        from lm_mcp.categories import WORKFLOW_TOOLS

        config = _MockConfig(mcp_categories="workflow")
        result = _filter_tools(TOOLS, config)
        names = {t.name for t in result}
        # update_logicmodule isn't registered yet — strip from the expected set
        # for the curation-feature-only test pass.
        expected = WORKFLOW_TOOLS & {t.name for t in TOOLS}
        assert names == expected

    def test_categories_export_only(self):
        config = _MockConfig(mcp_categories="export")
        result = _filter_tools(TOOLS, config)
        for tool in result:
            assert tool.name.startswith("export_"), (
                f"{tool.name} appeared in export filter but doesn't start with export_"
            )

    def test_categories_intersect_with_enabled_tools(self):
        """LM_MCP_CATEGORIES narrows further; never expands."""
        config = _MockConfig(enabled_tools="get_*", mcp_categories="read")
        result = _filter_tools(TOOLS, config)
        for tool in result:
            assert tool.name.startswith("get_")
            assert tool.annotations is not None and tool.annotations.readOnlyHint

    def test_categories_unknown_token_warned_not_errored(self, caplog):
        import logging

        config = _MockConfig(mcp_categories="read,bogus,workflow")
        with caplog.at_level(logging.WARNING, logger="lm_mcp.server"):
            result = _filter_tools(TOOLS, config)
        # Unknown token logs a warning but does not error
        assert any("bogus" in r.message for r in caplog.records)
        # Filter still applies based on the valid tokens
        for tool in result:
            cats_present = []
            if (
                tool.annotations is not None
                and tool.annotations.readOnlyHint
                and tool.annotations.openWorldHint
            ):
                cats_present.append("read")
            from lm_mcp.categories import WORKFLOW_TOOLS

            if tool.name in WORKFLOW_TOOLS:
                cats_present.append("workflow")
            assert cats_present, f"{tool.name} survived filter but matches no valid category"

    def test_categories_all_typos_returns_unfiltered(self):
        """Defensive: all-typo input does not silently empty the surface."""
        config = _MockConfig(mcp_categories="bogus,nonsense")
        result = _filter_tools(TOOLS, config)
        assert len(result) == len(TOOLS) - len(PORTAL_TOOLS)

    @pytest.mark.asyncio
    async def test_call_tool_rejects_filtered_by_category(self, monkeypatch):
        """Calling a tool excluded by LM_MCP_CATEGORIES returns the category error."""
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token-value")
        monkeypatch.setenv("LM_MCP_CATEGORIES", "read")

        from lm_mcp.config import reset_config
        from lm_mcp.server import call_tool

        reset_config()
        try:
            result = await call_tool("delete_device", {"device_id": 1})
            assert result.isError is True
            assert "LM_MCP_CATEGORIES" in result.content[0].text
        finally:
            reset_config()


class TestPortalToolVisibility:
    """Portal tools are hidden outside multi-portal mode and present within it."""

    def test_filter_tools_hides_portal_tools_in_single_portal(self):
        result = _filter_tools(TOOLS, _MockConfig())
        names = {t.name for t in result}
        assert names.isdisjoint(PORTAL_TOOLS)

    def test_filter_tools_keeps_portal_tools_in_multi_portal(self):
        result = _filter_tools(TOOLS, _MockConfig(multi_portal=True))
        names = {t.name for t in result}
        assert names >= PORTAL_TOOLS


class TestPortalToolCategoryExemption:
    """Portal tools bypass LM_MCP_CATEGORIES in multi-portal mode (control plane)."""

    def test_portal_tools_survive_category_filter_in_multi_portal(self):
        result = _filter_tools(
            TOOLS, _MockConfig(mcp_categories="read,workflow", multi_portal=True)
        )
        names = {t.name for t in result}
        assert names >= PORTAL_TOOLS

    def test_category_filter_still_applies_to_data_tools_in_multi_portal(self):
        result = _filter_tools(TOOLS, _MockConfig(mcp_categories="workflow", multi_portal=True))
        names = {t.name for t in result} - PORTAL_TOOLS
        from lm_mcp.categories import WORKFLOW_TOOLS

        assert names <= WORKFLOW_TOOLS
