# Description: Tests for scripts/check_release_tag.py, the release workflow's metadata gate.
# Description: Runs the script on tmp_path copies of the repo's version files and changelog.

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "scripts" / "check_release_tag.py"
# Every file the script reads, relative to the repo root.
RELEASE_FILES = ("pyproject.toml", "server.json", "src/lm_mcp/__init__.py", "CHANGELOG.md")


@pytest.fixture
def release_root(tmp_path: Path) -> Path:
    """A copy of the repo's release metadata, at the repo's current version."""
    for name in RELEASE_FILES:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / name, target)
    return tmp_path


def _version(root: Path) -> str:
    with (root / "pyproject.toml").open("rb") as f:
        return tomllib.load(f)["project"]["version"]


def _run(tag: str, root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), tag, str(root)],
        capture_output=True,
        text=True,
        check=False,
    )


def _rewrite(path: Path, pattern: str, replacement: str) -> None:
    text = path.read_text()
    new, count = re.subn(pattern, replacement, text, count=1, flags=re.M)
    assert count == 1, f"{pattern!r} not found in {path}"
    path.write_text(new)


class TestCheckReleaseTag:
    """R2.2 (b) and (c): the tag version matches every version field and the changelog."""

    def test_matching_metadata_passes(self, release_root: Path) -> None:
        result = _run(f"v{_version(release_root)}", release_root)
        assert result.returncode == 0, result.stderr
        assert result.stderr == ""

    def test_tag_that_matches_no_file_fails(self, release_root: Path) -> None:
        result = _run("v0.0.0-gatecheck", release_root)
        assert result.returncode != 0
        assert "pyproject.toml" in result.stderr

    def test_pyproject_mismatch_names_pyproject(self, release_root: Path) -> None:
        version = _version(release_root)
        _rewrite(release_root / "pyproject.toml", r'^version = ".*"$', 'version = "0.0.1"')
        result = _run(f"v{version}", release_root)
        assert result.returncode != 0
        assert "pyproject.toml" in result.stderr
        assert "server.json" not in result.stderr

    @pytest.mark.parametrize("field", ["top-level", "package"])
    def test_server_json_mismatch_names_server_json(self, release_root: Path, field: str) -> None:
        version = _version(release_root)
        path = release_root / "server.json"
        data = json.loads(path.read_text())
        if field == "top-level":
            data["version"] = "0.0.1"
        else:
            data["packages"][0]["version"] = "0.0.1"
        path.write_text(json.dumps(data, indent=2))
        result = _run(f"v{version}", release_root)
        assert result.returncode != 0
        assert "server.json" in result.stderr
        assert "pyproject.toml" not in result.stderr

    def test_init_version_mismatch_names_init(self, release_root: Path) -> None:
        version = _version(release_root)
        _rewrite(
            release_root / "src/lm_mcp/__init__.py",
            r'^__version__ = ".*"$',
            '__version__ = "0.0.1"',
        )
        result = _run(f"v{version}", release_root)
        assert result.returncode != 0
        assert "src/lm_mcp/__init__.py" in result.stderr

    def test_missing_changelog_section_fails(self, release_root: Path) -> None:
        version = _version(release_root)
        _rewrite(
            release_root / "CHANGELOG.md",
            rf"^## \[{re.escape(version)}\].*$",
            "## [0.0.1] - 2000-01-01",
        )
        result = _run(f"v{version}", release_root)
        assert result.returncode != 0
        assert "CHANGELOG.md" in result.stderr

    def test_empty_changelog_section_fails(self, release_root: Path) -> None:
        version = _version(release_root)
        path = release_root / "CHANGELOG.md"
        text = path.read_text()
        heading = re.search(rf"^## \[{re.escape(version)}\].*$", text, re.M)
        assert heading is not None
        following = re.search(r"^## \[", text[heading.end() :], re.M)
        end = heading.end() + following.start() if following else len(text)
        # A section with a subheading and prose but no list entry is still empty.
        path.write_text(text[: heading.end()] + "\n\nNotes.\n\n### Fixed\n\n" + text[end:])
        result = _run(f"v{version}", release_root)
        assert result.returncode != 0
        assert "CHANGELOG.md" in result.stderr
