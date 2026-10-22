# Description: Invariant that every filter value interpolated in lm_mcp.tools is quoted (R3.6).
# Description: Walks each tool module's f-strings by AST; fails on a raw, unallowlisted value.

"""Filter interpolation invariant.

A LogicMonitor filter clause is ``field<op>value``. A value interpolated raw from a
user string can close its quotes and append clauses (``a"|"b`` becomes two clauses),
so every string value must pass through ``quote_filter_value``. This test walks every
f-string in ``src/lm_mcp/tools/*.py`` whose enclosing statement builds a filter and
whose literal text ends in a filter operator right before an interpolation, and fails
unless the interpolated expression is a ``quote_filter_value(...)`` call or is listed
in ``tests/fixtures/filter_interpolation_allowlist.txt`` as ``module.py: expression``.

The allowlist holds the integer, boolean and constant-map interpolations that cannot
carry a quote, and a value already built from ``quote_filter_value`` output. Run this
file directly to print the current hits in allowlist form.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "src" / "lm_mcp" / "tools"
ALLOWLIST_PATH = REPO_ROOT / "tests" / "fixtures" / "filter_interpolation_allowlist.txt"

# The literal text right before an interpolation ends in an LM filter operator,
# optionally followed by a hand-written opening quote.
_OPERATOR_RE = re.compile(r'(~|!~|:|!:|>:|<:|>|<)"?$')
_QUOTED_CALL_PREFIX = "quote_filter_value("


@dataclass(frozen=True)
class Hit:
    """One interpolated filter value."""

    module: str
    lineno: int
    segment: str
    expr: str

    @property
    def key(self) -> str:
        return f"{self.module}: {self.expr}"

    def __str__(self) -> str:
        return f"{self.module}:{self.lineno}: {self.segment!r} {{{self.expr}}}"


def _enclosing_statement_source(src: str, node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    current = node
    while current in parents and not isinstance(current, ast.stmt):
        current = parents[current]
    return ast.get_source_segment(src, current) or ""


def collect_filter_interpolations(tools_dir: Path = TOOLS_DIR) -> list[Hit]:
    """Return every filter value interpolation in the tool modules, quoted or not."""
    hits: list[Hit] = []
    for path in sorted(tools_dir.glob("*.py")):
        src = path.read_text()
        tree = ast.parse(src, filename=str(path))
        parents: dict[ast.AST, ast.AST] = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parents[child] = parent
        for node in ast.walk(tree):
            if not isinstance(node, ast.JoinedStr):
                continue
            statement = _enclosing_statement_source(src, node, parents)
            if "filter" not in statement.lower():
                continue
            previous = ""
            for part in node.values:
                if isinstance(part, ast.Constant):
                    previous = str(part.value)
                    continue
                if isinstance(part, ast.FormattedValue):
                    if _OPERATOR_RE.search(previous):
                        expr = ast.get_source_segment(src, part.value) or "<unreadable>"
                        hits.append(Hit(path.name, part.lineno, previous, expr))
                    previous = ""
    return hits


def unquoted_hits(hits: list[Hit]) -> list[Hit]:
    """The hits whose expression is not a quote_filter_value call."""
    return [hit for hit in hits if not hit.expr.startswith(_QUOTED_CALL_PREFIX)]


def load_allowlist(path: Path = ALLOWLIST_PATH) -> set[str]:
    """Read the allowlist: one ``module.py: expression`` per line, ``#`` comments allowed."""
    entries: set[str] = set()
    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            entries.add(line)
    return entries


def test_every_filter_value_is_quoted_or_allowlisted() -> None:
    """A filter value interpolated raw from a string is an injection point."""
    allowlist = load_allowlist()
    hits = unquoted_hits(collect_filter_interpolations())
    offenders = [hit for hit in hits if hit.key not in allowlist]
    assert not offenders, (
        "Filter values interpolated without quote_filter_value "
        "(route them through the helper, or allowlist an interpolation that cannot carry "
        "a raw string "
        f"in {ALLOWLIST_PATH.relative_to(REPO_ROOT)}):\n"
        + "\n".join(f"  {hit}" for hit in offenders)
    )


def test_allowlist_names_only_live_interpolations() -> None:
    """Every allowlist entry still matches a hit, so the file cannot drift from the code."""
    live = {hit.key for hit in unquoted_hits(collect_filter_interpolations())}
    stale = sorted(load_allowlist() - live)
    assert not stale, "Allowlist entries that match no interpolation:\n" + "\n".join(
        f"  {entry}" for entry in stale
    )


def test_scan_sees_the_tool_modules() -> None:
    """The scan reads real modules; an empty result would make the invariant vacuous."""
    hits = collect_filter_interpolations()
    assert any(hit.expr.startswith(_QUOTED_CALL_PREFIX) for hit in hits)
    assert any(hit.module == "devices.py" for hit in hits)


if __name__ == "__main__":
    for hit in unquoted_hits(collect_filter_interpolations()):
        print(f"{hit.key}    # line {hit.lineno}, {hit.segment!r}")
