# Description: Guards the CI workflow settings that fail silently when an edit drops them.
# Description: Interpreter selection, locked installs, SHA-pinned actions, permissions, concurrency.

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOWS_DIR = Path(__file__).parent.parent / ".github" / "workflows"
WORKFLOWS = sorted(p.name for p in WORKFLOWS_DIR.glob("*.yml"))
# Jobs that run a python-version matrix, by workflow.
MATRIX_JOBS = [("test.yml", "test"), ("release.yml", "gate")]

_USES_RE = re.compile(r"^\s*(?:-\s+)?uses:\s*(\S+)(.*)$", re.M)
_PINNED_RE = re.compile(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}")
_VERSION_COMMENT_RE = re.compile(r"\s+# v\d+(\.\d+)*$")


def _load(name: str) -> dict[str, Any]:
    return yaml.safe_load((WORKFLOWS_DIR / name).read_text())


def _run_lines(workflow: dict[str, Any]) -> list[str]:
    return [
        line
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        for line in step.get("run", "").splitlines()
    ]


def test_both_workflows_are_found() -> None:
    assert {"test.yml", "release.yml"} <= set(WORKFLOWS)


class TestInterpreterAndLock:
    """R2.1: each matrix leg runs the Python it names and installs from uv.lock."""

    @pytest.mark.parametrize(("name", "job"), MATRIX_JOBS)
    def test_matrix_job_sets_uv_python_to_the_leg(self, name: str, job: str) -> None:
        spec = _load(name)["jobs"][job]
        assert spec["strategy"]["matrix"]["python-version"] == ["3.11", "3.12", "3.13"]
        assert spec["env"]["UV_PYTHON"] == "${{ matrix.python-version }}"

    @pytest.mark.parametrize("name", WORKFLOWS)
    def test_every_uv_sync_is_locked(self, name: str) -> None:
        syncs = [line for line in _run_lines(_load(name)) if "uv sync" in line]
        assert syncs, f"{name} runs no uv sync"
        assert all("--locked" in line for line in syncs), syncs


class TestWorkflowHygiene:
    """R2.4: actions pinned by commit, read-only test token, one run per ref."""

    @pytest.mark.parametrize("name", WORKFLOWS)
    def test_every_action_is_pinned_with_a_version_comment(self, name: str) -> None:
        uses = _USES_RE.findall((WORKFLOWS_DIR / name).read_text())
        assert uses, f"{name} uses no actions"
        for ref, trailer in uses:
            assert _PINNED_RE.fullmatch(ref), f"{name}: {ref} is not pinned to a commit SHA"
            assert _VERSION_COMMENT_RE.match(trailer), f"{name}: {ref} lacks a # vX.Y.Z comment"

    def test_test_workflow_token_is_read_only(self) -> None:
        assert _load("test.yml")["permissions"] == {"contents": "read"}

    @pytest.mark.parametrize("name", WORKFLOWS)
    def test_runs_are_grouped_per_ref(self, name: str) -> None:
        group = _load(name)["concurrency"]["group"]
        assert "${{ github.workflow }}" in group
        assert "${{ github.ref }}" in group
