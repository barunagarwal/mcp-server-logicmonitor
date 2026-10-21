# Description: Tests for scripts/mypy_ratchet.py, the CI gate on mypy's error count.
# Description: Judges captured mypy output against baseline files, then runs mypy for real.

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "scripts" / "mypy_ratchet.py"


def _load_ratchet() -> ModuleType:
    spec = importlib.util.spec_from_file_location("mypy_ratchet", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ratchet = _load_ratchet()


def _mypy_output(errors: int) -> str:
    """mypy's report shape: one line per error, then the summary line."""
    lines = [
        f'src/lm_mcp/tools/m{i}.py:{i + 1}: error: Argument 1 to "f" has incompatible type '
        f'"str | None"; expected "str"  [arg-type]'
        for i in range(errors)
    ]
    lines.append(f"Found {errors} errors in {errors} files (checked 120 source files)")
    return "\n".join(lines) + "\n"


def _baseline(tmp_path: Path, count: int) -> Path:
    path = tmp_path / "mypy-baseline.txt"
    path.write_text(f"{count}\n")
    return path


class TestJudge:
    """R2.5: the error count may fall or hold, never rise above the checked-in baseline."""

    def test_count_at_baseline_passes(self, tmp_path: Path) -> None:
        code, message = ratchet.judge(_mypy_output(7), _baseline(tmp_path, 7))
        assert code == 0
        assert "7" in message

    def test_count_above_baseline_fails_naming_both(self, tmp_path: Path) -> None:
        code, message = ratchet.judge(_mypy_output(7), _baseline(tmp_path, 6))
        assert code != 0
        assert "7" in message
        assert "6" in message

    def test_count_below_baseline_passes_and_says_lower_it(self, tmp_path: Path) -> None:
        code, message = ratchet.judge(_mypy_output(7), _baseline(tmp_path, 12))
        assert code == 0
        assert "12" in message
        assert "--write" in message

    def test_missing_baseline_is_an_error(self, tmp_path: Path) -> None:
        with pytest.raises(ratchet.RatchetError, match=r"mypy-baseline\.txt"):
            ratchet.judge(_mypy_output(7), tmp_path / "mypy-baseline.txt")

    def test_unreadable_baseline_is_an_error(self, tmp_path: Path) -> None:
        path = tmp_path / "mypy-baseline.txt"
        path.write_text("seven\n")
        with pytest.raises(ratchet.RatchetError, match="seven"):
            ratchet.judge(_mypy_output(7), path)


class TestCountErrors:
    def test_summary_line_is_the_count(self) -> None:
        # The summary wins over the error lines shown, as with mypy's per-file limits.
        output = _mypy_output(2).replace("Found 2 errors", "Found 9 errors")
        assert ratchet.count_errors(output) == 9

    def test_without_a_summary_error_lines_are_counted(self) -> None:
        output = "\n".join(_mypy_output(3).splitlines()[:-1])
        output += "\nsrc/lm_mcp/x.py:1: note: See https://mypy.readthedocs.io\n"
        assert ratchet.count_errors(output) == 3

    def test_success_is_zero(self) -> None:
        assert ratchet.count_errors("Success: no issues found in 120 source files\n") == 0


def _project(tmp_path: Path, errors: int) -> Path:
    """A minimal repo root whose src/lm_mcp holds the given number of mypy errors."""
    package = tmp_path / "src" / "lm_mcp"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    body = "".join(f"value_{i}: int = 'text'\n" for i in range(errors))
    (package / "typed.py").write_text(body)
    # Counts as an error only if the ratchet drops --ignore-missing-imports.
    (package / "deps.py").write_text("import a_dependency_that_is_not_installed  # noqa: F401\n")
    return tmp_path


def _run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


class TestRatchetRunsMypy:
    """End to end: the script runs mypy itself and exits as CI reads it."""

    def test_write_then_hold_then_rise(self, tmp_path: Path) -> None:
        root = _project(tmp_path, 2)
        written = _run(root, "--write")
        assert written.returncode == 0, written.stderr
        assert (root / "mypy-baseline.txt").read_text() == "2\n"
        assert _run(root).returncode == 0
        (root / "src" / "lm_mcp" / "more.py").write_text("extra: str = 1\n")
        risen = _run(root)
        assert risen.returncode == 1
        assert "3" in risen.stderr
        assert "2" in risen.stderr

    def test_missing_baseline_fails(self, tmp_path: Path) -> None:
        result = _run(_project(tmp_path, 1))
        assert result.returncode == 2
        assert "mypy-baseline.txt" in result.stderr

    def test_mypy_that_cannot_run_fails(self, tmp_path: Path) -> None:
        # No src/lm_mcp: mypy exits 2, which is neither a pass nor a count.
        (tmp_path / "mypy-baseline.txt").write_text("0\n")
        result = _run(tmp_path)
        assert result.returncode == 2
        assert "mypy exited 2" in result.stderr
