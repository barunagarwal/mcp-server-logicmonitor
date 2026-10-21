# Description: Run mypy over src/lm_mcp and fail when its error count rises above the baseline.
# Description: The baseline is mypy-baseline.txt at the repo root; --write records the count.

"""mypy ratchet.

Usage: python scripts/mypy_ratchet.py [--write] [--root PATH]

Runs `mypy src/lm_mcp --ignore-missing-imports` from the repo root and compares the
error count with the integer in mypy-baseline.txt. More errors than the baseline
fails; the same count passes; fewer passes and says the baseline can be lowered.
--write records the current count as the new baseline.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

BASELINE_NAME = "mypy-baseline.txt"
MYPY_ARGS = ("src/lm_mcp", "--ignore-missing-imports")

_FOUND_RE = re.compile(r"^Found (\d+) errors? in \d+ files?", re.M)


class RatchetError(Exception):
    """The ratchet cannot judge: mypy failed to run or the baseline is unusable."""


def count_errors(output: str) -> int:
    """The count mypy's `Found N errors` line reports, else the number of error lines."""
    found = _FOUND_RE.search(output)
    if found:
        return int(found.group(1))
    return sum(1 for line in output.splitlines() if ": error:" in line)


def read_baseline(path: Path) -> int:
    try:
        text = path.read_text()
    except FileNotFoundError:
        raise RatchetError(
            f"{path.name} not found; record one with: uv run python scripts/mypy_ratchet.py --write"
        ) from None
    try:
        return int(text.strip())
    except ValueError:
        raise RatchetError(f"{path.name} holds {text.strip()!r}, not an error count") from None


def compare(count: int, baseline: int) -> tuple[int, str]:
    """The exit code and message for a count measured against the baseline."""
    if count > baseline:
        return 1, (
            f"mypy reports {count} errors, above the baseline of {baseline}; "
            "fix the new errors before merging"
        )
    if count < baseline:
        return 0, (
            f"mypy reports {count} errors, below the baseline of {baseline}; lower it with: "
            "uv run python scripts/mypy_ratchet.py --write"
        )
    return 0, f"mypy reports {count} errors, at the baseline"


def judge(output: str, baseline_path: Path) -> tuple[int, str]:
    """The exit code and message for mypy's output measured against the baseline file."""
    return compare(count_errors(output), read_baseline(baseline_path))


def run_mypy(root: Path) -> str:
    result = subprocess.run(
        [sys.executable, "-m", "mypy", *MYPY_ARGS],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    output = result.stdout + result.stderr
    # mypy exits 1 when it finds errors and 2 when it could not check at all.
    if result.returncode not in (0, 1):
        raise RatchetError(f"mypy exited {result.returncode}:\n{output}")
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail when mypy's error count rises.")
    parser.add_argument("--write", action="store_true", help="record the current count")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="the repository root (default: this script's repository)",
    )
    args = parser.parse_args(argv)
    baseline_path = args.root / BASELINE_NAME
    try:
        output = run_mypy(args.root)
        if args.write:
            count = count_errors(output)
            baseline_path.write_text(f"{count}\n")
            print(f"mypy_ratchet: recorded {count} errors in {BASELINE_NAME}")
            return 0
        code, message = judge(output, baseline_path)
    except RatchetError as exc:
        print(f"mypy_ratchet: {exc}", file=sys.stderr)
        return 2
    print(f"mypy_ratchet: {message}", file=sys.stderr if code else sys.stdout)
    return code


if __name__ == "__main__":
    sys.exit(main())
