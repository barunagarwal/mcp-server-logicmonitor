# Description: Guards the hostStatus word form across src/lm_mcp, the resources and the docs.
# Description: The v3 API filters hostStatus on quoted words; numbers match nothing.

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parent.parent

# Every module under src/lm_mcp (tools, resources, prompts) and the operator docs.
GUARDED = sorted(
    {
        *(REPO / "src" / "lm_mcp").rglob("*.py"),
        REPO / "README.md",
        *(REPO / "documentation").rglob("*.md"),
        *(REPO / ".claude" / "skills").rglob("*.md"),
    }
)

HOST_STATUS_WORDS = ("normal", "dead", "dead-collector", "unmonitored", "disabled")

# A numeric filter or comparison: hostStatus:0, hostStatus!:0, hostStatus != 1, hostStatus=1.
NUMERIC = re.compile(r"hostStatus[!:= ]+[0-9]")

# A filter whose value is not a quoted word: the API answers hostStatus:normal with
# HTTP 400 "invalid filter" (live, 2026-10-24).
UNQUOTED = re.compile(r'hostStatus!?:(?!\\?"(?:' + "|".join(HOST_STATUS_WORDS) + r')\\?")')


def _violations(text: str) -> list[str]:
    matches = (*NUMERIC.finditer(text), *UNQUOTED.finditer(text))
    return [text[m.start() : m.end() + 12] for m in matches]


class TestPatterns:
    """R6.1: the guard's patterns catch the forms the API rejects and pass the ones it takes."""

    @pytest.mark.parametrize(
        "text",
        [
            "hostStatus:0",
            "hostStatus!:0",
            "hostStatus:1,displayName~prod",
            "hostStatus != 1",
            "hostStatus=1",
            "displayName~prod,hostStatus:alive",
            "hostStatus:normal",
            'hostStatus:"alive"',
        ],
    )
    def test_rejected_forms(self, text):
        assert _violations(text)

    @pytest.mark.parametrize(
        "text",
        [
            'hostStatus:"normal"',
            'hostStatus!:"normal"',
            'displayName~"prod",hostStatus:"dead-collector"',
            'hostStatus:\\"dead\\"',
            'dev.get("hostStatus")',
            "the raw API item keeps `hostStatus`.",
        ],
    )
    def test_accepted_forms(self, text):
        assert _violations(text) == []


@pytest.mark.parametrize("path", GUARDED, ids=lambda p: str(p.relative_to(REPO)))
def test_guarded_file_uses_host_status_words(path):
    """R6.1: no guarded file filters or compares hostStatus on a number or an unquoted word."""
    assert _violations(path.read_text(encoding="utf-8")) == []


def test_guard_covers_the_files_it_names():
    """R6.1: an empty glob would pass every check vacuously."""
    names = {p.relative_to(REPO).as_posix() for p in GUARDED}
    assert "src/lm_mcp/tools/workflows.py" in names
    assert "src/lm_mcp/tools/devices.py" in names
    assert "src/lm_mcp/resources/schemas.py" in names
    assert "src/lm_mcp/prompts/templates.py" in names
    assert "README.md" in names
    assert any(n.startswith("documentation/") for n in names)
    assert any(n.startswith(".claude/skills/") for n in names)


def _host_status_violations(node: Any, path: str = "") -> list[str]:
    """Every value held under a hostStatus key that is not a status word or a string field."""
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}.{key}"
            if key in ("hostStatus", "host_status"):
                if isinstance(value, dict):
                    if value.get("type", "string") != "string":
                        found.append(f"{here}.type={value['type']!r}")
                    if "example" in value and value["example"] not in HOST_STATUS_WORDS:
                        found.append(f"{here}.example={value['example']!r}")
                elif value not in HOST_STATUS_WORDS:
                    found.append(f"{here}={value!r}")
            found.extend(_host_status_violations(value, here))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            found.extend(_host_status_violations(value, f"{path}[{i}]"))
    return found


def test_violations_walker_catches_structured_numbers():
    """R6.1: a number stored as a value, not written in a filter, is caught too."""
    assert _host_status_violations({"hostStatus": {"type": "integer", "example": 0}}) == [
        ".hostStatus.type='integer'",
        ".hostStatus.example=0",
    ]
    assert _host_status_violations({"devices": [{"host_status": 1}]}) == [
        ".devices[0].host_status=1"
    ]
    assert _host_status_violations({"hostStatus": {"type": "string", "example": "dead"}}) == []


def test_resources_hold_host_status_as_words():
    """R6.1: no resource stores hostStatus as a number, an integer type or a non-word example."""
    from lm_mcp.resources.registry import get_resource_content, list_resource_uris

    uris = list_resource_uris()
    assert uris
    found = {
        uri: v
        for uri in uris
        if (v := _host_status_violations(json.loads(get_resource_content(uri))))
    }
    assert found == {}


def test_device_status_enum_api_values_are_the_words():
    """R6.1: each device-status enum entry's api_value is its own word."""
    from lm_mcp.resources.registry import get_resource_content

    values = json.loads(get_resource_content("lm://enums/device-status"))["values"]
    assert set(values) == set(HOST_STATUS_WORDS)
    assert {name: entry["api_value"] for name, entry in values.items()} == {
        name: name for name in HOST_STATUS_WORDS
    }
