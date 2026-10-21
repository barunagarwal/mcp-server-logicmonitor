# Description: Verify a release tag against the package version fields and the changelog.
# Description: The release workflow's gate runs it; it exits nonzero naming each mismatch.

"""Check that a release tag matches the release metadata.

Usage: python scripts/check_release_tag.py <tag> <repo root>

The tag is the pushed ref name, such as v4.2.1. The version it names (the tag without
its leading "v") must equal pyproject.toml's [project].version, both version fields in
server.json and lm_mcp.__version__, and CHANGELOG.md must have a "## [<version>]"
section holding at least one list entry.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
import tomllib
from pathlib import Path


def _pyproject_version(root: Path) -> object:
    with (root / "pyproject.toml").open("rb") as f:
        return tomllib.load(f).get("project", {}).get("version")


def _server_json_versions(root: Path) -> list[tuple[str, object]]:
    data = json.loads((root / "server.json").read_text())
    fields: list[tuple[str, object]] = [("version", data.get("version"))]
    for index, package in enumerate(data.get("packages", [])):
        fields.append((f"packages[{index}].version", package.get("version")))
    return fields


def _init_version(root: Path) -> object:
    tree = ast.parse((root / "src" / "lm_mcp" / "__init__.py").read_text())
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "__version__" for t in node.targets)
            and isinstance(node.value, ast.Constant)
        ):
            return node.value.value
    return None


def _changelog_has_entry(root: Path, version: str) -> bool:
    heading = f"## [{version}]"
    in_section = False
    for line in (root / "CHANGELOG.md").read_text().splitlines():
        if line.startswith("## "):
            if in_section:
                return False
            in_section = line.startswith(heading)
        elif in_section and line.lstrip().startswith(("- ", "* ")):
            return True
    return False


def check(tag: str, root: Path) -> list[str]:
    """Return one line per mismatch between the tag and the release metadata."""
    version = tag.removeprefix("v")
    found: list[tuple[str, object]] = [
        ("pyproject.toml [project].version", _pyproject_version(root))
    ]
    found += [(f"server.json {field}", value) for field, value in _server_json_versions(root)]
    found.append(("src/lm_mcp/__init__.py __version__", _init_version(root)))
    problems = [
        f"{where} is {value!r}, tag {tag} names {version!r}"
        for where, value in found
        if value != version
    ]
    if not _changelog_has_entry(root, version):
        problems.append(f"CHANGELOG.md has no '## [{version}]' section with an entry")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check a release tag against the metadata.")
    parser.add_argument("tag", help="the release tag, such as v4.2.1")
    parser.add_argument("root", type=Path, help="the repository root")
    args = parser.parse_args(argv)
    problems = check(args.tag, args.root)
    for problem in problems:
        print(f"check_release_tag: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"check_release_tag: {args.tag} matches the version fields and CHANGELOG.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
