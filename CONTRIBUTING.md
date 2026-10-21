# Contributing

Contributions are welcome. Everything lands the same way: fork, branch, pull
request, review, merge.

## Workflow

1. Fork the repository and create a branch from `main`.
2. Make your change, with tests.
3. Open a pull request against `main`.
4. CI runs the suite on Python 3.11, 3.12, and 3.13, plus lint, the mypy
   ratchet, and a build. All checks must pass.
5. The maintainer reviews. `main` is protected: every change needs an approving
   review from the code owner, and direct pushes are rejected.
6. Merges are squash-only, and the branch is deleted afterward.

Nobody needs write access to contribute. If your fork's branch is behind, rebase
on `main` rather than merging it back in.

## Development setup

```bash
uv sync --extra http          # add --extra ibm / --extra huggingface as needed
uv run pre-commit install     # once: runs lint and format on every commit
uv run pytest                 # full suite
uv run ruff check src tests   # lint
uv run ruff format src tests  # format (CI checks this)
uv run python scripts/mypy_ratchet.py   # type check against mypy-baseline.txt
```

mypy runs as a ratchet. `mypy-baseline.txt` holds the current error count, and
CI fails when `uv run python scripts/mypy_ratchet.py` finds more. A change that
fixes type errors should lower the baseline: run
`uv run python scripts/mypy_ratchet.py --write` and commit the file with the fix.

The pre-commit hooks mirror the blocking CI gates (ruff check, ruff format, plus
file hygiene and a private-key guard), so formatting drift fails locally instead
of burning a CI cycle. They deliberately skip pytest, which is too slow for a
commit hook: run it yourself before pushing. Never bypass a failing hook with
`--no-verify`; fix the cause.

Run the server locally over stdio with `uv run lm-mcp-server`, which needs
`LM_PORTAL` and `LM_BEARER_TOKEN` in your environment or a local `.env`.

## Expectations for a pull request

- **Tests ship with the change.** New behavior needs unit coverage; bug fixes
  need a test that fails before the fix.
- **One logical unit per PR.** Unrelated fixes belong in their own PR.
- **Conventional commit titles**, for example `fix(http): ...`, `feat(alerts): ...`,
  `docs(readme): ...`. The PR title becomes the squashed commit subject.
- **Describe the why**, not just the what. Include how you verified the change.
- **No credentials, ever.** Not in code, tests, fixtures, or examples. Push
  protection and secret scanning are enabled and will block them.

## Tool changes

The tool surface is generated and contract-tested. After intentionally adding,
removing, or re-describing a tool:

```bash
uv run python tests/test_tool_contract.py   # regenerate the contract fixture
uv run python tests/test_tools_doc.py       # regenerate documentation/tools.md
```

Commit the regenerated files with your change. `documentation/tools.md` is
generated and must never be hand-edited. A tool also needs an entry in
`TOOL_CATEGORIES` (`src/lm_mcp/resources/guides.py`) or the categorization test
will fail.

Write tools must be decorated with `require_write_permission`: they stay disabled
unless the operator sets `LM_ENABLE_WRITE_OPERATIONS=true`.

## Reporting bugs and vulnerabilities

Open an issue for bugs. For security vulnerabilities, do not open a public
issue: use private vulnerability reporting as described in
[SECURITY.md](SECURITY.md).

## Related documents

- [README.md](README.md) — installation, configuration, client setup
- [MULTIPORTAL.md](MULTIPORTAL.md) — multi-portal mode (stdio only)
- [SECURITY.md](SECURITY.md) — security policy and deployment considerations
- [CHANGELOG.md](CHANGELOG.md) — release history; add an entry under
  `## [Unreleased]` with your change
