# Description: Structural validation tests for Claude Code skill files.
# Description: Verifies YAML frontmatter, allowed tools, and registry consistency.

from __future__ import annotations

import re
from pathlib import Path

import pytest

from lm_mcp.registry import AWX_TOOLS, TOOLS

SKILLS_DIR = Path(__file__).resolve().parent.parent / ".claude" / "skills"

# Build a set of all tool names from the registry for cross-referencing
ALL_REGISTRY_TOOLS = {tool.name for tool in TOOLS} | {tool.name for tool in AWX_TOOLS}

# Expected skills (directory names under .claude/skills/)
EXPECTED_SKILLS = [
    "lm-apm",
    "lm-capacity",
    "lm-health",
    "lm-portal",
    "lm-triage",
    "lm-remediate",
    "lm-collector-debug",
]


def _parse_frontmatter(text: str) -> dict:
    """Parse simple YAML frontmatter without external dependencies.

    Handles scalar values and lists (- item lines). Sufficient for
    skill frontmatter which uses name, description, argument-hint,
    and allowed-tools fields.
    """
    result = {}
    current_key = None
    for line in text.split("\n"):
        # List item under current key
        if line.startswith("  - ") and current_key is not None:
            result[current_key].append(line.strip("- ").strip())
            continue
        # Key: value pair
        kv_match = re.match(r"^(\S[\w-]+):\s*(.*)", line)
        if kv_match:
            key = kv_match.group(1)
            value = kv_match.group(2).strip().strip('"').strip("'")
            if value:
                result[key] = value
                current_key = None
            else:
                # Empty value means a list follows
                result[key] = []
                current_key = key
    return result


def _load_skill_frontmatter(skill_dir: Path) -> dict:
    """Parse YAML frontmatter from a SKILL.md file.

    Reads the file and extracts content between the opening and closing
    '---' delimiters.
    """
    skill_file = skill_dir / "SKILL.md"
    text = skill_file.read_text()
    match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    assert match, f"No YAML frontmatter found in {skill_file}"
    return _parse_frontmatter(match.group(1))


def _get_all_skill_dirs() -> list[Path]:
    """Return paths for all expected skill directories."""
    return [SKILLS_DIR / name for name in EXPECTED_SKILLS]


class TestSkillFileStructure:
    """Structural validation for all skill SKILL.md files."""

    @pytest.fixture(autouse=True)
    def _load_skills(self):
        """Load frontmatter for all skills once per test class."""
        self.skills = {}
        for skill_dir in _get_all_skill_dirs():
            skill_file = skill_dir / "SKILL.md"
            if skill_file.exists():
                self.skills[skill_dir.name] = _load_skill_frontmatter(skill_dir)

    def test_all_skills_have_yaml_frontmatter(self):
        """Every expected skill directory has a SKILL.md with YAML frontmatter."""
        for name in EXPECTED_SKILLS:
            assert name in self.skills, f"Skill '{name}' missing or has no frontmatter"

    def test_all_skills_have_name(self):
        """Every skill frontmatter contains a 'name' field."""
        for name, fm in self.skills.items():
            assert "name" in fm, f"Skill '{name}' missing 'name' in frontmatter"

    def test_all_skills_have_description(self):
        """Every skill frontmatter contains a 'description' field."""
        for name, fm in self.skills.items():
            assert "description" in fm, f"Skill '{name}' missing 'description' in frontmatter"

    def test_all_skills_have_allowed_tools(self):
        """Every skill frontmatter contains an 'allowed-tools' list."""
        for name, fm in self.skills.items():
            assert "allowed-tools" in fm, f"Skill '{name}' missing 'allowed-tools' in frontmatter"
            assert isinstance(fm["allowed-tools"], list), (
                f"Skill '{name}' 'allowed-tools' is not a list"
            )
            assert len(fm["allowed-tools"]) > 0, f"Skill '{name}' 'allowed-tools' is empty"

    def test_skill_allowed_tools_exist_in_registry(self):
        """Every tool referenced in skill frontmatter maps to a real registry tool.

        Skill files reference tools as 'mcp__logicmonitor__<tool_name>'.
        This test strips the prefix and checks against TOOLS + AWX_TOOLS.
        """
        prefix = "mcp__logicmonitor__"
        for name, fm in self.skills.items():
            for tool_ref in fm.get("allowed-tools", []):
                assert tool_ref.startswith(prefix), (
                    f"Skill '{name}' tool '{tool_ref}' missing expected prefix"
                )
                tool_name = tool_ref[len(prefix) :]
                assert tool_name in ALL_REGISTRY_TOOLS, (
                    f"Skill '{name}' references tool '{tool_name}' "
                    f"which does not exist in TOOLS or AWX_TOOLS"
                )

    def test_lm_remediate_skill_exists(self):
        """The lm-remediate skill directory and SKILL.md exist."""
        skill_file = SKILLS_DIR / "lm-remediate" / "SKILL.md"
        assert skill_file.exists(), "lm-remediate/SKILL.md does not exist"

    def test_lm_remediate_has_awx_tools(self):
        """lm-remediate skill includes AAP/AWX tools for remediation."""
        fm = self.skills.get("lm-remediate", {})
        tools = fm.get("allowed-tools", [])
        awx_tool_names = [
            "mcp__logicmonitor__test_awx_connection",
            "mcp__logicmonitor__get_job_templates",
            "mcp__logicmonitor__get_job_template",
            "mcp__logicmonitor__launch_job",
            "mcp__logicmonitor__get_job_status",
            "mcp__logicmonitor__get_job_output",
            "mcp__logicmonitor__get_inventories",
            "mcp__logicmonitor__get_inventory_hosts",
        ]
        for expected in awx_tool_names:
            assert expected in tools, f"lm-remediate missing AWX tool '{expected}'"

    def test_lm_remediate_has_lm_diagnostic_tools(self):
        """lm-remediate skill includes LM diagnostic tools."""
        fm = self.skills.get("lm-remediate", {})
        tools = fm.get("allowed-tools", [])
        lm_tool_names = [
            "mcp__logicmonitor__get_alerts",
            "mcp__logicmonitor__get_alert_details",
            "mcp__logicmonitor__get_device",
            "mcp__logicmonitor__get_device_data",
            "mcp__logicmonitor__score_device_health",
            "mcp__logicmonitor__correlate_alerts",
            "mcp__logicmonitor__correlate_changes",
            "mcp__logicmonitor__analyze_blast_radius",
        ]
        for expected in lm_tool_names:
            assert expected in tools, f"lm-remediate missing LM diagnostic tool '{expected}'"
