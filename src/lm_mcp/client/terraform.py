# Description: Terraform CLI subprocess runner for Infrastructure as Code workflows.
# Description: Manages workspace directories and executes terraform commands.

from __future__ import annotations

import asyncio
import logging
import os
import signal
from dataclasses import dataclass
from pathlib import Path

from lm_mcp.exceptions import LMError

logger = logging.getLogger(__name__)

# Variables the subprocess inherits from the server environment, besides TF_*:
# the process basics, plus the proxy and CA settings terraform init needs to reach
# the provider registry from behind an egress proxy or a private CA. Everything
# else, server and cloud credentials included, stays out of terraform's reach;
# provider credentials arrive explicitly through env_extra.
_INHERITED_ENV = frozenset(
    {
        "PATH",
        "HOME",
        "TMPDIR",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "no_proxy",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
    }
)

# Seconds a timed-out terraform gets after SIGINT to finish in-flight provider
# calls, write state and release its lock before it is killed.
_INTERRUPT_GRACE_SECONDS = 30

# Commands that change state, where an interrupted run can leave a held lock and
# resources the state does not record.
_STATE_CHANGING_COMMANDS = frozenset({"apply", "destroy"})


@dataclass
class TerraformResult:
    """Result from a terraform CLI invocation.

    Attributes:
        exit_code: Process exit code (0=success, 1=error, 2=changes pending for plan).
        stdout: Standard output from the terraform process.
        stderr: Standard error from the terraform process.
    """

    exit_code: int
    stdout: str
    stderr: str


class TerraformRunner:
    """Async subprocess wrapper for the Terraform CLI.

    Manages workspace directories under a root directory, executes terraform
    commands with configurable timeouts, and passes credentials via an
    allowlisted subprocess environment (never written to disk).
    """

    def __init__(
        self,
        workspace_dir: str,
        terraform_binary: str = "terraform",
        timeout: int = 300,
        auto_approve_enabled: bool = False,
    ):
        """Initialize the Terraform runner.

        Args:
            workspace_dir: Root directory for Terraform workspaces.
            terraform_binary: Path to the terraform binary.
            timeout: Command timeout in seconds.
            auto_approve_enabled: Whether terraform apply/destroy are allowed.
        """
        self.workspace_dir = Path(workspace_dir).resolve()
        self.terraform_binary = terraform_binary
        self.timeout = timeout
        self.auto_approve_enabled = auto_approve_enabled

    def workspace_path(self, workspace: str) -> Path:
        """Resolve a workspace name to a directory path with traversal guard.

        Args:
            workspace: Workspace name (becomes a subdirectory under workspace_dir).

        Returns:
            Resolved absolute path to the workspace directory.

        Raises:
            ValueError: If the resolved path escapes the workspace root.
        """
        resolved = (self.workspace_dir / workspace).resolve()
        if not resolved.is_relative_to(self.workspace_dir):
            raise ValueError(
                f"Invalid workspace name '{workspace}': resolved path escapes workspace root"
            )
        return resolved

    async def run(
        self,
        args: list[str],
        workspace: str,
        env_extra: dict[str, str] | None = None,
    ) -> TerraformResult:
        """Execute a terraform command in a workspace directory.

        Creates the workspace subdirectory if it does not exist. The subprocess
        inherits only _INHERITED_ENV (process basics, proxy and CA settings) and
        TF_* from the server environment, plus env_extra (typically LM provider
        credentials), never written to disk.

        Args:
            args: Terraform subcommand and flags (e.g., ["plan", "-json"]).
            workspace: Workspace name (subdirectory of workspace_dir).
            env_extra: Additional environment variables for the subprocess.

        Returns:
            TerraformResult with exit code, stdout, and stderr.

        Raises:
            LMError: If the terraform binary is not found or the command times out.
            ValueError: If the workspace name fails path traversal validation.
        """
        ws_path = self.workspace_path(workspace)
        ws_path.mkdir(parents=True, exist_ok=True)

        env = {
            name: value
            for name, value in os.environ.items()
            if name in _INHERITED_ENV or name.startswith("TF_")
        }
        if env_extra:
            env.update(env_extra)

        # Disable interactive prompts and color codes
        env["TF_INPUT"] = "false"
        env["TF_IN_AUTOMATION"] = "true"

        cmd = [self.terraform_binary, *args]
        logger.debug("terraform %s in %s", " ".join(args), ws_path)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(ws_path),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=self.timeout,
            )
        except FileNotFoundError as exc:
            raise LMError(
                message=f"Terraform binary '{self.terraform_binary}' not found",
                code="TERRAFORM_NOT_FOUND",
                suggestion=("Install Terraform: https://developer.hashicorp.com/terraform/install"),
            ) from exc
        except TimeoutError:
            await self._interrupt(proc)
            message = f"Terraform command timed out after {self.timeout}s: {' '.join(args)}"
            suggestion = (
                f"Increase TF_TIMEOUT (current: {self.timeout}s) or simplify the configuration."
            )
            if args and args[0] in _STATE_CHANGING_COMMANDS:
                message += (
                    ". It was interrupted mid-run: the state lock may still be held, and "
                    "resources changed before the interrupt may be missing from state."
                )
                suggestion = (
                    "Run terraform_plan to see what state is missing. If the state is still "
                    "locked, release it with terraform force-unlock <LOCK_ID> once no other "
                    f"run holds it. {suggestion}"
                )
            raise LMError(
                message=message, code="TERRAFORM_TIMEOUT", suggestion=suggestion
            ) from None

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        logger.debug(
            "terraform exit=%d stdout=%d bytes stderr=%d bytes",
            proc.returncode or 0,
            len(stdout),
            len(stderr),
        )

        return TerraformResult(
            exit_code=proc.returncode or 0,
            stdout=stdout,
            stderr=stderr,
        )

    @staticmethod
    async def _interrupt(proc: asyncio.subprocess.Process) -> None:
        """Stop a timed-out terraform: SIGINT, a grace period, then SIGKILL.

        SIGINT is terraform's signal to finish in-flight operations, persist state
        and release its lock; killing it outright skips all three.
        """
        try:
            proc.send_signal(signal.SIGINT)
        except ProcessLookupError:
            logger.debug("terraform exited before it could be interrupted")
            return
        try:
            await asyncio.wait_for(proc.wait(), timeout=_INTERRUPT_GRACE_SECONDS)
            return
        except TimeoutError:
            logger.warning(
                "terraform did not stop within %ss of SIGINT; killing it",
                _INTERRUPT_GRACE_SECONDS,
            )
        try:
            proc.kill()
        except ProcessLookupError:
            logger.debug("terraform exited before it could be killed")
        await proc.wait()

    async def close(self) -> None:
        """Clean up resources. No-op for subprocess runner, matches client interface."""

    async def __aenter__(self) -> TerraformRunner:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()
