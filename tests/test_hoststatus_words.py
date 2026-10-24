# Description: Guards the hostStatus word form in the code and docs main owns.
# Description: The v3 API filters hostStatus on quoted words; numbers match nothing.

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# The dead-device counter and the operator docs. The resources, prompts and device
# filter elsewhere under src/lm_mcp are not in this list.
GUARDED = sorted(
    [
        REPO / "src" / "lm_mcp" / "tools" / "workflows.py",
        REPO / "README.md",
        *(REPO / "documentation").rglob("*.md"),
        *(REPO / ".claude" / "skills").rglob("*.md"),
    ]
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
    assert "README.md" in names
    assert any(n.startswith("documentation/") for n in names)
    assert any(n.startswith(".claude/skills/") for n in names)
