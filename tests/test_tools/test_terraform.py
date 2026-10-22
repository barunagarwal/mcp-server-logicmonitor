# Description: Tests for Terraform tool handlers.
# Description: Verifies all 11 terraform tools with mocked TerraformRunner and LM client.

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from lm_mcp.client.terraform import TerraformResult


@pytest.fixture
def mock_runner():
    """Create a mock TerraformRunner with auto_approve_enabled=True."""
    runner = MagicMock()
    runner.auto_approve_enabled = True
    runner.workspace_path = MagicMock(return_value=MagicMock())
    runner.workspace_path.return_value.mkdir = MagicMock()
    return runner


@pytest.fixture
def mock_runner_locked():
    """Create a mock TerraformRunner with auto_approve_enabled=False."""
    runner = MagicMock()
    runner.auto_approve_enabled = False
    return runner


def _reload_config(monkeypatch, *, writes_enabled: bool = False):
    """Reset and reload config with write operations enabled or disabled."""
    monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
    monkeypatch.setenv("LM_BEARER_TOKEN", "test-token-12345")
    monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", str(writes_enabled).lower())
    from lm_mcp.config import reset_config

    reset_config()


# ---------------------------------------------------------------------------
# terraform_init
# ---------------------------------------------------------------------------


class TestTerraformInit:
    @pytest.mark.asyncio
    async def test_init_success(self, mock_runner, monkeypatch):
        _reload_config(monkeypatch, writes_enabled=True)
        from lm_mcp.tools.terraform import terraform_init

        mock_runner.run = AsyncMock(
            return_value=TerraformResult(exit_code=0, stdout="Initialized.", stderr="")
        )
        result = await terraform_init(mock_runner, workspace="prod")
        data = json.loads(result[0].text)
        assert data["success"] is True
        assert data["workspace"] == "prod"

    @pytest.mark.asyncio
    async def test_init_failure(self, mock_runner, monkeypatch):
        _reload_config(monkeypatch, writes_enabled=True)
        from lm_mcp.tools.terraform import terraform_init

        mock_runner.run = AsyncMock(
            return_value=TerraformResult(exit_code=1, stdout="", stderr="Error: no config")
        )
        result = await terraform_init(mock_runner, workspace="bad")
        data = json.loads(result[0].text)
        assert data["success"] is False

    @pytest.mark.asyncio
    async def test_write_disabled(self, mock_runner, monkeypatch):
        """R3.4: init downloads providers and runs backend code, so writes must be on."""
        _reload_config(monkeypatch, writes_enabled=False)
        from lm_mcp.tools.terraform import terraform_init

        mock_runner.run = AsyncMock()
        result = await terraform_init(mock_runner, workspace="prod")
        assert "write operations are disabled" in result[0].text.lower()
        mock_runner.run.assert_not_called()


# ---------------------------------------------------------------------------
# terraform_validate
# ---------------------------------------------------------------------------


class TestTerraformValidate:
    @pytest.mark.asyncio
    async def test_valid_config(self, mock_runner):
        from lm_mcp.tools.terraform import terraform_validate

        mock_runner.run = AsyncMock(
            return_value=TerraformResult(
                exit_code=0,
                stdout='{"valid": true, "error_count": 0}',
                stderr="",
            )
        )
        result = await terraform_validate(mock_runner, workspace="prod")
        data = json.loads(result[0].text)
        assert data["valid"] is True

    @pytest.mark.asyncio
    async def test_invalid_config(self, mock_runner):
        from lm_mcp.tools.terraform import terraform_validate

        mock_runner.run = AsyncMock(
            return_value=TerraformResult(
                exit_code=1,
                stdout='{"valid": false, "error_count": 1}',
                stderr="Error in config",
            )
        )
        result = await terraform_validate(mock_runner, workspace="bad")
        data = json.loads(result[0].text)
        assert data["valid"] is False


# ---------------------------------------------------------------------------
# terraform_plan
# ---------------------------------------------------------------------------


class TestTerraformPlan:
    @pytest.mark.asyncio
    async def test_no_changes(self, mock_runner, monkeypatch):
        _reload_config(monkeypatch, writes_enabled=True)
        from lm_mcp.tools.terraform import terraform_plan

        mock_runner.run = AsyncMock(return_value=TerraformResult(exit_code=0, stdout="", stderr=""))
        result = await terraform_plan(mock_runner, workspace="prod")
        data = json.loads(result[0].text)
        assert data["status"] == "no_changes"
        assert data["has_changes"] is False

    @pytest.mark.asyncio
    async def test_write_disabled(self, mock_runner, monkeypatch):
        """R3.4: plan evaluates data sources against live APIs, so writes must be on."""
        _reload_config(monkeypatch, writes_enabled=False)
        from lm_mcp.tools.terraform import terraform_plan

        mock_runner.run = AsyncMock()
        result = await terraform_plan(mock_runner, workspace="prod")
        assert "write operations are disabled" in result[0].text.lower()
        mock_runner.run.assert_not_called()

    @pytest.mark.asyncio
    async def test_provider_credentials_passed_explicitly(self, mock_runner, monkeypatch):
        """The LM provider's variables go through env_extra; the bearer token never does."""
        monkeypatch.setenv("LM_PORTAL", "acme.logicmonitor.com")
        monkeypatch.delenv("LM_BEARER_TOKEN", raising=False)
        monkeypatch.setenv("LM_ACCESS_ID", "lmv1-id")
        monkeypatch.setenv("LM_ACCESS_KEY", "lmv1-key")
        monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "true")
        from lm_mcp.config import reset_config

        reset_config()
        from lm_mcp.tools.terraform import terraform_plan

        mock_runner.run = AsyncMock(return_value=TerraformResult(exit_code=0, stdout="", stderr=""))
        await terraform_plan(mock_runner, workspace="prod")

        assert mock_runner.run.call_args.kwargs["env_extra"] == {
            "LM_COMPANY": "acme",
            "TF_VAR_lm_company": "acme",
            "LM_API_ID": "lmv1-id",
            "TF_VAR_lm_api_id": "lmv1-id",
            "LM_API_KEY": "lmv1-key",
            "TF_VAR_lm_api_key": "lmv1-key",
        }

    @pytest.mark.asyncio
    async def test_changes_pending(self, mock_runner, monkeypatch):
        _reload_config(monkeypatch, writes_enabled=True)
        from lm_mcp.tools.terraform import terraform_plan

        plan_line = json.dumps({"type": "planned_change", "change": {"action": "create"}})
        mock_runner.run = AsyncMock(
            return_value=TerraformResult(exit_code=2, stdout=plan_line, stderr="")
        )
        result = await terraform_plan(mock_runner, workspace="prod")
        data = json.loads(result[0].text)
        assert data["status"] == "changes_pending"
        assert data["has_changes"] is True

    @pytest.mark.asyncio
    async def test_plan_error(self, mock_runner, monkeypatch):
        _reload_config(monkeypatch, writes_enabled=True)
        from lm_mcp.tools.terraform import terraform_plan

        mock_runner.run = AsyncMock(
            return_value=TerraformResult(exit_code=1, stdout="", stderr="Error")
        )
        result = await terraform_plan(mock_runner, workspace="prod")
        data = json.loads(result[0].text)
        assert data["status"] == "error"


# ---------------------------------------------------------------------------
# terraform_state_list / terraform_state_show / terraform_output
# ---------------------------------------------------------------------------


class TestTerraformStateList:
    @pytest.mark.asyncio
    async def test_with_resources(self, mock_runner):
        from lm_mcp.tools.terraform import terraform_state_list

        mock_runner.run = AsyncMock(
            return_value=TerraformResult(
                exit_code=0,
                stdout="logicmonitor_device.web01\nlogicmonitor_device.web02\n",
                stderr="",
            )
        )
        result = await terraform_state_list(mock_runner, workspace="prod")
        data = json.loads(result[0].text)
        assert data["resource_count"] == 2
        assert "logicmonitor_device.web01" in data["resources"]

    @pytest.mark.asyncio
    async def test_empty_state(self, mock_runner):
        from lm_mcp.tools.terraform import terraform_state_list

        mock_runner.run = AsyncMock(
            return_value=TerraformResult(exit_code=1, stdout="", stderr="No state file")
        )
        result = await terraform_state_list(mock_runner, workspace="empty")
        assert "error" in result[0].text.lower() or "no state" in result[0].text.lower()


class TestTerraformStateShow:
    @pytest.mark.asyncio
    async def test_valid_address(self, mock_runner):
        from lm_mcp.tools.terraform import terraform_state_show

        resource_json = json.dumps({"type": "logicmonitor_device", "values": {"name": "web01"}})
        mock_runner.run = AsyncMock(
            return_value=TerraformResult(exit_code=0, stdout=resource_json, stderr="")
        )
        result = await terraform_state_show(
            mock_runner, workspace="prod", address="logicmonitor_device.web01"
        )
        data = json.loads(result[0].text)
        assert data["address"] == "logicmonitor_device.web01"
        assert "resource" in data

    @pytest.mark.asyncio
    async def test_not_found(self, mock_runner):
        from lm_mcp.tools.terraform import terraform_state_show

        mock_runner.run = AsyncMock(
            return_value=TerraformResult(exit_code=1, stdout="", stderr="Not found")
        )
        result = await terraform_state_show(
            mock_runner, workspace="prod", address="logicmonitor_device.missing"
        )
        assert "not found" in result[0].text.lower() or "error" in result[0].text.lower()


class TestTerraformOutput:
    @pytest.mark.asyncio
    async def test_with_outputs(self, mock_runner):
        from lm_mcp.tools.terraform import terraform_output

        outputs = json.dumps({"portal_url": {"value": "test.logicmonitor.com"}})
        mock_runner.run = AsyncMock(
            return_value=TerraformResult(exit_code=0, stdout=outputs, stderr="")
        )
        result = await terraform_output(mock_runner, workspace="prod")
        data = json.loads(result[0].text)
        assert "portal_url" in data["outputs"]


# ---------------------------------------------------------------------------
# terraform_apply (triple gate)
# ---------------------------------------------------------------------------


class TestTerraformApply:
    @pytest.mark.asyncio
    async def test_all_gates_pass(self, mock_runner, monkeypatch):
        _reload_config(monkeypatch, writes_enabled=True)
        from lm_mcp.tools.terraform import terraform_apply

        mock_runner.run = AsyncMock(return_value=TerraformResult(exit_code=0, stdout="", stderr=""))
        result = await terraform_apply(mock_runner, workspace="prod", confirm=True)
        data = json.loads(result[0].text)
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_write_disabled(self, mock_runner, monkeypatch):
        _reload_config(monkeypatch, writes_enabled=False)
        from lm_mcp.tools.terraform import terraform_apply

        result = await terraform_apply(mock_runner, workspace="prod", confirm=True)
        assert "write operations are disabled" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_auto_approve_disabled(self, mock_runner_locked, monkeypatch):
        _reload_config(monkeypatch, writes_enabled=True)
        from lm_mcp.tools.terraform import terraform_apply

        result = await terraform_apply(mock_runner_locked, workspace="prod", confirm=True)
        assert "disabled by server configuration" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_confirm_false(self, mock_runner, monkeypatch):
        _reload_config(monkeypatch, writes_enabled=True)
        from lm_mcp.tools.terraform import terraform_apply

        result = await terraform_apply(mock_runner, workspace="prod", confirm=False)
        assert "requires confirm=true" in result[0].text.lower()


# ---------------------------------------------------------------------------
# terraform_destroy (triple gate)
# ---------------------------------------------------------------------------


class TestTerraformDestroy:
    @pytest.mark.asyncio
    async def test_all_gates_pass(self, mock_runner, monkeypatch):
        _reload_config(monkeypatch, writes_enabled=True)
        from lm_mcp.tools.terraform import terraform_destroy

        mock_runner.run = AsyncMock(
            return_value=TerraformResult(exit_code=0, stdout="Destroyed.", stderr="")
        )
        result = await terraform_destroy(mock_runner, workspace="prod", confirm=True)
        data = json.loads(result[0].text)
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_confirm_false(self, mock_runner, monkeypatch):
        _reload_config(monkeypatch, writes_enabled=True)
        from lm_mcp.tools.terraform import terraform_destroy

        result = await terraform_destroy(mock_runner, workspace="prod", confirm=False)
        assert "requires confirm=true" in result[0].text.lower()


# ---------------------------------------------------------------------------
# terraform_import_resource
# ---------------------------------------------------------------------------


class TestTerraformImportResource:
    @pytest.mark.asyncio
    async def test_import_success(self, mock_runner, monkeypatch):
        _reload_config(monkeypatch, writes_enabled=True)
        from lm_mcp.tools.terraform import terraform_import_resource

        mock_runner.run = AsyncMock(
            return_value=TerraformResult(exit_code=0, stdout="Imported.", stderr="")
        )
        result = await terraform_import_resource(
            mock_runner,
            workspace="prod",
            address="logicmonitor_device.web01",
            resource_id="123",
        )
        data = json.loads(result[0].text)
        assert data["success"] is True
        assert data["address"] == "logicmonitor_device.web01"

    @pytest.mark.asyncio
    async def test_write_permission_required(self, mock_runner, monkeypatch):
        _reload_config(monkeypatch, writes_enabled=False)
        from lm_mcp.tools.terraform import terraform_import_resource

        result = await terraform_import_resource(
            mock_runner,
            workspace="prod",
            address="logicmonitor_device.web01",
            resource_id="123",
        )
        assert "write operations are disabled" in result[0].text.lower()


# ---------------------------------------------------------------------------
# terraform_write_config
# ---------------------------------------------------------------------------


class TestTerraformWriteConfig:
    @pytest.mark.asyncio
    async def test_write_success(self, mock_runner, monkeypatch, tmp_path):
        _reload_config(monkeypatch, writes_enabled=True)
        from lm_mcp.tools.terraform import terraform_write_config

        ws_path = tmp_path / "prod"
        mock_runner.workspace_path = MagicMock(return_value=ws_path)
        result = await terraform_write_config(
            mock_runner,
            workspace="prod",
            filename="main.tf",
            content='resource "logicmonitor_device" "test" {}',
        )
        data = json.loads(result[0].text)
        assert data["written"] is True
        assert (ws_path / "main.tf").exists()

    @pytest.mark.asyncio
    async def test_invalid_extension(self, mock_runner, monkeypatch):
        _reload_config(monkeypatch, writes_enabled=True)
        from lm_mcp.tools.terraform import terraform_write_config

        result = await terraform_write_config(
            mock_runner, workspace="prod", filename="config.yaml", content="data"
        )
        assert "must end with .tf" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_path_traversal_rejected(self, mock_runner, monkeypatch):
        _reload_config(monkeypatch, writes_enabled=True)
        from lm_mcp.tools.terraform import terraform_write_config

        result = await terraform_write_config(
            mock_runner, workspace="prod", filename="../etc/main.tf", content="data"
        )
        assert "path separators" in result[0].text.lower()


# ---------------------------------------------------------------------------
# terraform_generate
# ---------------------------------------------------------------------------


class TestTerraformGenerate:
    @pytest.mark.asyncio
    async def test_device_generation(self):
        from lm_mcp.tools.terraform import terraform_generate

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            return_value={
                "id": 42,
                "name": "192.168.1.1",
                "displayName": "web-server-01",
                "preferredCollectorId": 5,
                "hostGroupIds": "1,2",
                "description": "Primary web server",
                "customProperties": [{"name": "env", "value": "prod"}],
            }
        )
        result = await terraform_generate(mock_client, resource_type="device", resource_id=42)
        data = json.loads(result[0].text)
        assert "hcl" in data
        assert "logicmonitor_device" in data["hcl"]
        assert "web_server_01" in data["hcl"]
        assert "192.168.1.1" in data["hcl"]

    @pytest.mark.asyncio
    async def test_device_group_generation(self):
        from lm_mcp.tools.terraform import terraform_generate

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            return_value={
                "id": 10,
                "name": "Production Servers",
                "parentId": 1,
                "description": "All prod servers",
                "appliesTo": 'system.displayname =~ "prod"',
            }
        )
        result = await terraform_generate(mock_client, resource_type="device_group", resource_id=10)
        data = json.loads(result[0].text)
        assert "logicmonitor_device_group" in data["hcl"]
        assert "Production Servers" in data["hcl"]

    @pytest.mark.asyncio
    async def test_unsupported_type(self):
        from lm_mcp.tools.terraform import terraform_generate

        mock_client = AsyncMock()
        result = await terraform_generate(mock_client, resource_type="invalid_type", resource_id=1)
        assert "unsupported resource type" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_alert_rule_with_list_devices(self):
        """alert_rule renderer handles devices/deviceGroups as lists (API format)."""
        from lm_mcp.tools.terraform import terraform_generate

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            return_value={
                "id": 5,
                "name": "Critical CPU Alert",
                "priority": 100,
                "escalatingChainId": 1,
                "levelStr": "critical",
                "devices": ["server-01", "server-02"],
                "deviceGroups": ["Production", "Web Tier"],
                "datasource": "VMware vSphere Host Performance",
            }
        )
        result = await terraform_generate(mock_client, resource_type="alert_rule", resource_id=5)
        data = json.loads(result[0].text)
        assert "logicmonitor_alert_rule" in data["hcl"]
        assert "server-01,server-02" in data["hcl"]
        assert "Production,Web Tier" in data["hcl"]

    @pytest.mark.asyncio
    async def test_escalation_chain_with_destinations(self):
        """escalation_chain renderer includes destination blocks."""
        from lm_mcp.tools.terraform import terraform_generate

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            return_value={
                "id": 3,
                "name": "Ops Team",
                "enableThrottling": True,
                "throttlingPeriod": 10,
                "throttlingAlerts": 30,
                "destinations": [
                    {"type": "single", "addr": "ops@example.com", "method": "email", "period": 15},
                    {"type": "group", "addr": "NOC", "method": "sms", "period": 30},
                ],
            }
        )
        result = await terraform_generate(
            mock_client, resource_type="escalation_chain", resource_id=3
        )
        data = json.loads(result[0].text)
        hcl = data["hcl"]
        assert "destination {" in hcl
        assert "ops@example.com" in hcl
        assert "NOC" in hcl
        assert hcl.count("destination {") == 2

    @pytest.mark.asyncio
    async def test_generic_renderer_for_sdt(self):
        from lm_mcp.tools.terraform import terraform_generate

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            return_value={
                "id": 99,
                "name": "Weekly maintenance",
                "sdtType": "DeviceSDT",
                "deviceId": 42,
            }
        )
        result = await terraform_generate(mock_client, resource_type="sdt", resource_id=99)
        data = json.loads(result[0].text)
        assert "logicmonitor_sdt" in data["hcl"]
        assert "# Generated from LM API" in data["hcl"]


# ---------------------------------------------------------------------------
# var_file and backend_config confinement (R3.4)
# ---------------------------------------------------------------------------


@pytest.fixture
def real_runner(tmp_path):
    """A TerraformRunner on a real workspace root, with run() stubbed."""
    from lm_mcp.client.terraform import TerraformRunner

    runner = TerraformRunner(workspace_dir=str(tmp_path / "root"), auto_approve_enabled=True)
    runner.workspace_path("prod").mkdir(parents=True)
    runner.run = AsyncMock(return_value=TerraformResult(exit_code=0, stdout="", stderr=""))
    return runner


class TestVarFileConfinement:
    @pytest.mark.asyncio
    async def test_plan_traversal_is_refused_before_run(self, real_runner, monkeypatch):
        _reload_config(monkeypatch, writes_enabled=True)
        from lm_mcp.tools.terraform import terraform_plan

        result = await terraform_plan(real_runner, workspace="prod", var_file="../../etc/passwd")

        assert "var_file" in result[0].text
        assert "escapes the workspace" in result[0].text
        real_runner.run.assert_not_called()

    @pytest.mark.asyncio
    async def test_plan_file_inside_workspace_is_passed_through(self, real_runner, monkeypatch):
        _reload_config(monkeypatch, writes_enabled=True)
        from lm_mcp.tools.terraform import terraform_plan

        await terraform_plan(real_runner, workspace="prod", var_file="vars/prod.tfvars")

        args = real_runner.run.call_args.args[0]
        assert args[args.index("-var-file") + 1] == "vars/prod.tfvars"

    @pytest.mark.asyncio
    async def test_symlink_out_of_the_workspace_is_refused(
        self, real_runner, monkeypatch, tmp_path
    ):
        _reload_config(monkeypatch, writes_enabled=True)
        from lm_mcp.tools.terraform import terraform_plan

        outside = tmp_path / "secret.tfvars"
        outside.write_text('token = "x"\n')
        (real_runner.workspace_path("prod") / "link.tfvars").symlink_to(outside)

        result = await terraform_plan(real_runner, workspace="prod", var_file="link.tfvars")

        assert "escapes the workspace" in result[0].text
        real_runner.run.assert_not_called()

    @pytest.mark.asyncio
    async def test_apply_traversal_is_refused_before_run(self, real_runner, monkeypatch):
        _reload_config(monkeypatch, writes_enabled=True)
        from lm_mcp.tools.terraform import terraform_apply

        result = await terraform_apply(
            real_runner, workspace="prod", var_file="/etc/passwd", confirm=True
        )

        assert "escapes the workspace" in result[0].text
        real_runner.run.assert_not_called()


class TestBackendConfigAllowlist:
    @pytest.mark.asyncio
    async def test_unlisted_key_is_refused_and_named(self, real_runner, monkeypatch):
        _reload_config(monkeypatch, writes_enabled=True)
        from lm_mcp.tools.terraform import terraform_init

        result = await terraform_init(
            real_runner,
            workspace="prod",
            backend_config={"path": "x", "address": "http://evil"},
        )

        assert "'address'" in result[0].text
        assert "'path'" not in result[0].text
        real_runner.run.assert_not_called()

    @pytest.mark.asyncio
    async def test_endpoint_override_is_refused(self, real_runner, monkeypatch):
        """A documented s3 key that redirects state traffic is still refused."""
        _reload_config(monkeypatch, writes_enabled=True)
        from lm_mcp.tools.terraform import terraform_init

        result = await terraform_init(
            real_runner,
            workspace="prod",
            backend_config={"bucket": "b", "endpoint": "https://evil.example"},
        )

        assert "'endpoint'" in result[0].text
        real_runner.run.assert_not_called()

    @pytest.mark.asyncio
    async def test_allowed_keys_pass_as_separate_flags(self, real_runner, monkeypatch):
        _reload_config(monkeypatch, writes_enabled=True)
        from lm_mcp.tools.terraform import terraform_init

        await terraform_init(
            real_runner,
            workspace="prod",
            backend_config={"bucket": "state", "key": "lm/prod.tfstate", "region": "us-east-1"},
        )

        args = real_runner.run.call_args.args[0]
        assert args[:2] == ["init", "-no-color"]
        assert args[2:] == [
            "-backend-config",
            "bucket=state",
            "-backend-config",
            "key=lm/prod.tfstate",
            "-backend-config",
            "region=us-east-1",
        ]

    @pytest.mark.asyncio
    async def test_local_state_path_outside_the_workspace_is_refused(
        self, real_runner, monkeypatch
    ):
        """The local backend's path writes state there, so it stays in the workspace."""
        _reload_config(monkeypatch, writes_enabled=True)
        from lm_mcp.tools.terraform import terraform_init

        result = await terraform_init(
            real_runner, workspace="prod", backend_config={"path": "../../../home/x/.bashrc"}
        )

        assert "escapes the workspace" in result[0].text
        real_runner.run.assert_not_called()


# ---------------------------------------------------------------------------
# Path traversal guard (TerraformRunner)
# ---------------------------------------------------------------------------


class TestPathTraversalGuard:
    def test_valid_workspace(self, tmp_path):
        from lm_mcp.client.terraform import TerraformRunner

        runner = TerraformRunner(workspace_dir=str(tmp_path))
        path = runner.workspace_path("prod")
        assert path.is_relative_to(tmp_path)

    def test_traversal_rejected(self, tmp_path):
        from lm_mcp.client.terraform import TerraformRunner

        runner = TerraformRunner(workspace_dir=str(tmp_path))
        with pytest.raises(ValueError, match="escapes workspace root"):
            runner.workspace_path("../../etc/passwd")

    def test_nested_workspace(self, tmp_path):
        from lm_mcp.client.terraform import TerraformRunner

        runner = TerraformRunner(workspace_dir=str(tmp_path))
        path = runner.workspace_path("team/prod")
        assert path.is_relative_to(tmp_path)
