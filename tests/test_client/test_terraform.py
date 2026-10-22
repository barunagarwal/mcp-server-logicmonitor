# Description: Tests for the Terraform subprocess runner's environment handling.
# Description: Runs a real child process that reports the environment it received.

import json
import os
import sys
import time

import pytest

from lm_mcp.client.terraform import TerraformRunner
from lm_mcp.exceptions import LMError

# Stands in for the terraform binary: prints the environment the runner passed.
_PRINT_ENV = ["-c", "import json, os; print(json.dumps(dict(os.environ)))"]

_SERVER_SECRETS = {
    "LM_BEARER_TOKEN": "lm-bearer-secret",
    "AWX_TOKEN": "awx-secret",
    "WATSONX_API_KEY": "watsonx-secret",
    "LM_HTTP_AUTH_TOKEN": "inbound-secret",
    "DATABASE_URL": "postgres://user:pw@db/x",
}


async def _child_env(tmp_path, env_extra=None) -> dict[str, str]:
    runner = TerraformRunner(workspace_dir=str(tmp_path), terraform_binary=sys.executable)
    result = await runner.run(_PRINT_ENV, "ws", env_extra=env_extra)
    assert result.exit_code == 0, result.stderr
    return json.loads(result.stdout)


class TestRunnerEnvironment:
    """R3.4: the Terraform subprocess gets an allowlisted environment, not os.environ."""

    @pytest.mark.asyncio
    async def test_server_secrets_do_not_reach_the_subprocess(self, tmp_path, monkeypatch):
        """Credentials in the server's environment are not inherited by terraform."""
        for name, value in _SERVER_SECRETS.items():
            monkeypatch.setenv(name, value)

        env = await _child_env(tmp_path)

        leaked = sorted(set(_SERVER_SECRETS) & set(env))
        assert leaked == []

    @pytest.mark.asyncio
    async def test_allowlisted_variables_pass_through(self, tmp_path, monkeypatch):
        """PATH, HOME, TMPDIR and TF_* from the server env reach the subprocess."""
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        monkeypatch.setenv("TF_VAR_region", "us-east-1")
        monkeypatch.setenv("TF_LOG", "INFO")

        env = await _child_env(tmp_path)

        assert env["PATH"]
        assert env["HOME"] == str(tmp_path)
        assert env["TMPDIR"] == str(tmp_path)
        assert env["TF_VAR_region"] == "us-east-1"
        assert env["TF_LOG"] == "INFO"
        assert env["TF_INPUT"] == "false"
        assert env["TF_IN_AUTOMATION"] == "true"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "name",
        [
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "NO_PROXY",
            "http_proxy",
            "https_proxy",
            "no_proxy",
            "SSL_CERT_FILE",
            "SSL_CERT_DIR",
        ],
    )
    async def test_proxy_and_ca_settings_pass_through(self, tmp_path, monkeypatch, name):
        """terraform init reaches the registry through the operator's proxy and CA."""
        monkeypatch.setenv(name, "proxy-or-ca-value")

        env = await _child_env(tmp_path)

        assert env[name] == "proxy-or-ca-value"

    @pytest.mark.asyncio
    async def test_cloud_credentials_stay_out(self, tmp_path, monkeypatch):
        """Cloud credentials in the server env are not inherited; backends get them otherwise."""
        for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "ARM_CLIENT_SECRET"):
            monkeypatch.setenv(name, "cloud-secret")

        env = await _child_env(tmp_path)

        assert not {"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "ARM_CLIENT_SECRET"} & set(env)

    @pytest.mark.asyncio
    async def test_env_extra_reaches_the_subprocess(self, tmp_path, monkeypatch):
        """Provider variables the caller passes in env_extra are set explicitly."""
        monkeypatch.setenv("LM_BEARER_TOKEN", "lm-bearer-secret")
        extra = {
            "LM_API_ID": "id",
            "LM_API_KEY": "key",
            "LM_COMPANY": "acme",
            "TF_VAR_lm_api_id": "id",
        }

        env = await _child_env(tmp_path, env_extra=extra)

        for name, value in extra.items():
            assert env[name] == value
        assert "LM_BEARER_TOKEN" not in env


# Stand-ins for a terraform that outlives the timeout. Each writes its pid to the
# workspace (its cwd); the first stops on SIGINT, the second ignores it.
_STOPS_ON_SIGINT = """
import os, pathlib, signal, sys, time
pathlib.Path("pid").write_text(str(os.getpid()))
def stop(*_):
    pathlib.Path("interrupted").write_text("yes")
    sys.exit(130)
signal.signal(signal.SIGINT, stop)
time.sleep(20)
"""

_IGNORES_SIGINT = """
import os, pathlib, signal, time
pathlib.Path("pid").write_text(str(os.getpid()))
signal.signal(signal.SIGINT, signal.SIG_IGN)
time.sleep(20)
"""


def _fake_terraform(tmp_path, body: str) -> str:
    script = tmp_path / "terraform"
    script.write_text(f"#!{sys.executable}\n{body}")
    script.chmod(0o755)
    return str(script)


def _slow_runner(tmp_path, body: str) -> TerraformRunner:
    return TerraformRunner(
        workspace_dir=str(tmp_path / "root"),
        terraform_binary=_fake_terraform(tmp_path, body),
        timeout=1,
    )


class TestRunnerTimeout:
    """R3.4: a timed-out command is interrupted, given a grace period, then killed."""

    @pytest.mark.asyncio
    async def test_timeout_sends_sigint_first(self, tmp_path):
        """terraform gets SIGINT, its signal to release locks and stop cleanly."""
        runner = _slow_runner(tmp_path, _STOPS_ON_SIGINT)

        with pytest.raises(LMError) as exc_info:
            await runner.run(["plan"], "ws")

        assert exc_info.value.code == "TERRAFORM_TIMEOUT"
        assert (runner.workspace_path("ws") / "interrupted").exists()

    @pytest.mark.asyncio
    async def test_process_ignoring_sigint_is_killed_after_the_grace_period(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr("lm_mcp.client.terraform._INTERRUPT_GRACE_SECONDS", 0.5)
        runner = _slow_runner(tmp_path, _IGNORES_SIGINT)

        started = time.monotonic()
        with pytest.raises(LMError):
            await runner.run(["plan"], "ws")
        elapsed = time.monotonic() - started

        assert elapsed < 10
        pid = int((runner.workspace_path("ws") / "pid").read_text())
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("command", ["apply", "destroy"])
    async def test_state_changing_timeout_names_lock_and_orphan_risk(self, tmp_path, command):
        runner = _slow_runner(tmp_path, _STOPS_ON_SIGINT)

        with pytest.raises(LMError) as exc_info:
            await runner.run([command, "-auto-approve"], "ws")

        text = f"{exc_info.value.message} {exc_info.value.suggestion}"
        assert "force-unlock" in text
        assert "missing from state" in text

    @pytest.mark.asyncio
    async def test_read_only_timeout_has_no_state_warning(self, tmp_path):
        runner = _slow_runner(tmp_path, _STOPS_ON_SIGINT)

        with pytest.raises(LMError) as exc_info:
            await runner.run(["plan"], "ws")

        text = f"{exc_info.value.message} {exc_info.value.suggestion}"
        assert "force-unlock" not in text
