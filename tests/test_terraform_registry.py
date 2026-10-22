# Description: Registry tests for Terraform tool definitions.
# Description: Verifies tool count, annotations, handler coverage, and naming conventions.

from __future__ import annotations

from lm_mcp.registry import TF_TOOLS, TOOLS, get_tool_handler


class TestTerraformToolRegistry:
    """Verify TF_TOOLS list integrity and handler wiring."""

    def test_tf_tools_count(self):
        """TF_TOOLS contains exactly 10 tools (terraform_generate is in TOOLS)."""
        assert len(TF_TOOLS) == 10

    def test_tf_tools_have_names(self):
        """All TF tools have non-empty names."""
        for tool in TF_TOOLS:
            assert tool.name, f"Tool missing name: {tool}"

    def test_tf_tools_have_descriptions(self):
        """All TF tools have non-empty descriptions."""
        for tool in TF_TOOLS:
            assert tool.description, f"Tool '{tool.name}' missing description"

    def test_tf_tools_have_schemas(self):
        """All TF tools have input schemas."""
        for tool in TF_TOOLS:
            assert tool.inputSchema, f"Tool '{tool.name}' missing inputSchema"

    def test_tf_tools_have_annotations(self):
        """All TF tools have annotations."""
        for tool in TF_TOOLS:
            assert tool.annotations is not None, f"Tool '{tool.name}' missing annotations"

    def test_tf_tool_names_are_unique(self):
        """No duplicate names within TF_TOOLS."""
        names = [t.name for t in TF_TOOLS]
        assert len(names) == len(set(names))

    def test_no_overlap_with_lm_tools(self):
        """TF tool names do not collide with main TOOLS."""
        tf_names = {t.name for t in TF_TOOLS}
        lm_names = {t.name for t in TOOLS}
        overlap = tf_names & lm_names
        assert not overlap, f"Name collision: {overlap}"

    def test_terraform_generate_in_tools(self):
        """terraform_generate is registered in TOOLS (not TF_TOOLS)."""
        tool_names = {t.name for t in TOOLS}
        assert "terraform_generate" in tool_names

    def test_terraform_generate_not_in_tf_tools(self):
        """terraform_generate is not duplicated in TF_TOOLS."""
        tf_names = {t.name for t in TF_TOOLS}
        assert "terraform_generate" not in tf_names

    def test_read_tools_marked_readonly(self):
        """Read-only TF tools have readOnlyHint=True."""
        read_tools = {
            "terraform_validate",
            "terraform_state_list",
            "terraform_state_show",
            "terraform_output",
        }
        for tool in TF_TOOLS:
            if tool.name in read_tools:
                assert tool.annotations.readOnlyHint is True, (
                    f"Tool '{tool.name}' should be read-only"
                )

    def test_write_tools_not_readonly(self):
        """Write TF tools have readOnlyHint=False."""
        write_tools = {
            "terraform_init",
            "terraform_plan",
            "terraform_apply",
            "terraform_destroy",
            "terraform_import",
            "terraform_write_config",
        }
        for tool in TF_TOOLS:
            if tool.name in write_tools:
                assert tool.annotations.readOnlyHint is False, (
                    f"Tool '{tool.name}' should not be read-only"
                )

    def test_destroy_marked_destructive(self):
        """terraform_destroy has destructiveHint=True."""
        destroy = next(t for t in TF_TOOLS if t.name == "terraform_destroy")
        assert destroy.annotations.destructiveHint is True

    def test_all_tf_tools_have_handlers(self):
        """Every TF tool has a registered handler."""
        all_tools = list(TF_TOOLS) + [t for t in TOOLS if t.name == "terraform_generate"]
        for tool in all_tools:
            handler = get_tool_handler(tool.name)
            assert callable(handler), f"Tool '{tool.name}' has no handler"
