# Description: Terraform IaC tools for plan, apply, state, and HCL generation.
# Description: Supports any Terraform provider plus LM-specific resource export.

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

from mcp.types import TextContent

from lm_mcp.exceptions import ValidationError
from lm_mcp.tools import format_response, handle_error, require_write_permission

if TYPE_CHECKING:
    from lm_mcp.client import LogicMonitorClient
    from lm_mcp.client.terraform import TerraformRunner

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _lm_env_vars() -> dict[str, str]:
    """Build LM provider env vars from current config for subprocess.

    Sets both native provider env vars (LM_API_ID, LM_API_KEY, LM_COMPANY)
    and TF_VAR_* equivalents for HCL variable blocks. The native vars are
    what the logicmonitor provider reads directly; TF_VAR_* are for configs
    that use variable blocks for credentials.
    Returns an empty dict if config is unavailable (e.g., in tests).
    """
    try:
        from lm_mcp.config import get_config

        config = get_config()
        env: dict[str, str] = {}
        portal = config.portal if hasattr(config, "portal") else ""
        if portal:
            company = portal.split(".")[0]
            env["LM_COMPANY"] = company
            env["TF_VAR_lm_company"] = company
        if hasattr(config, "access_id") and config.access_id:
            env["LM_API_ID"] = config.access_id
            env["TF_VAR_lm_api_id"] = config.access_id
        if hasattr(config, "access_key") and config.access_key:
            env["LM_API_KEY"] = config.access_key
            env["TF_VAR_lm_api_key"] = config.access_key
        return env
    except Exception:
        logger.warning(
            "terraform: failed to build LM env vars from config; "
            "running without injected LM credentials",
            exc_info=True,
        )
        return {}


# Top-level -backend-config keys terraform_init accepts: the documented keys of the
# local, s3 and azurerm backends, minus those that redirect where state traffic goes
# (endpoint overrides, proxies, metadata, MSI and OIDC URLs) or weaken TLS
# (insecure, custom_ca_bundle). A key outside this set, such as the http backend's
# address, is refused by name.
#   https://developer.hashicorp.com/terraform/language/backend/local
#   https://developer.hashicorp.com/terraform/language/backend/s3
#   https://developer.hashicorp.com/terraform/language/backend/azurerm
_BACKEND_CONFIG_KEYS = frozenset(
    {
        # local
        "path",
        "workspace_dir",
        # s3
        "bucket",
        "key",
        "region",
        "acl",
        "encrypt",
        "kms_key_id",
        "sse_customer_key",
        "workspace_key_prefix",
        "use_lockfile",
        "dynamodb_table",
        "access_key",
        "secret_key",
        "token",
        "profile",
        "shared_config_files",
        "shared_credentials_file",
        "shared_credentials_files",
        "allowed_account_ids",
        "forbidden_account_ids",
        "max_retries",
        "retry_mode",
        "skip_credentials_validation",
        "skip_region_validation",
        "skip_requesting_account_id",
        "skip_metadata_api_check",
        "skip_s3_checksum",
        "sts_region",
        "use_dualstack_endpoint",
        "use_fips_endpoint",
        "use_path_style",
        "force_path_style",
        # azurerm
        "storage_account_name",
        "container_name",
        "snapshot",
        "resource_group_name",
        "subscription_id",
        "tenant_id",
        "lookup_blob_endpoint",
        "use_azuread_auth",
        "sas_token",
        "use_cli",
        "use_msi",
        "use_oidc",
        "use_aks_workload_identity",
        "ado_pipeline_service_connection_id",
        "client_id",
        "client_id_file_path",
        "client_secret",
        "client_secret_file_path",
        "client_certificate",
        "client_certificate_path",
        "client_certificate_password",
        "oidc_request_token",
        "oidc_token",
        "oidc_token_file_path",
    }
)

# Local backend keys that name where state is written, so they stay in the workspace.
_BACKEND_PATH_KEYS = frozenset({"path", "workspace_dir"})


def _confine_to_workspace(runner: TerraformRunner, workspace: str, label: str, path: str) -> str:
    """Return path unchanged if it resolves inside the workspace, else refuse it.

    Resolution follows symlinks, so a link inside the workspace that points out
    of it is refused too.
    """
    root = runner.workspace_path(workspace)
    if not (root / path).resolve().is_relative_to(root):
        raise ValidationError(
            f"{label} '{path}' escapes the workspace directory",
            suggestion=f"Give {label} as a path inside the '{workspace}' workspace.",
        )
    return path


def _backend_config_args(
    runner: TerraformRunner, workspace: str, backend_config: dict[str, str]
) -> list[str]:
    """Build -backend-config flags from allowlisted keys, refusing the rest by name."""
    refused = sorted(k for k in backend_config if k not in _BACKEND_CONFIG_KEYS)
    if refused:
        names = ", ".join(f"'{k}'" for k in refused)
        raise ValidationError(
            f"backend_config key {names} is not allowed",
            suggestion=(
                "Use keys of the local, s3 or azurerm backend; endpoint and proxy "
                "overrides are refused. Declare anything else in the backend block."
            ),
        )
    args: list[str] = []
    for key, value in backend_config.items():
        if key in _BACKEND_PATH_KEYS:
            _confine_to_workspace(runner, workspace, f"backend_config {key}", value)
        args.extend(["-backend-config", f"{key}={value}"])
    return args


def _parse_plan_exit_code(exit_code: int) -> str:
    """Interpret terraform plan -detailed-exitcode values."""
    if exit_code == 0:
        return "no_changes"
    if exit_code == 2:
        return "changes_pending"
    return "error"


def _safe_name(raw: str) -> str:
    """Convert a display name to a valid Terraform resource name.

    Replaces non-alphanumeric characters with underscores and strips
    leading digits so the result is a valid HCL identifier.
    """
    name = re.sub(r"[^a-zA-Z0-9_]", "_", raw).strip("_").lower()
    name = re.sub(r"_+", "_", name)
    if name and name[0].isdigit():
        name = f"r_{name}"
    return name or "resource"


# ---------------------------------------------------------------------------
# Runner tools (receive TerraformRunner); init and plan are write-gated
# ---------------------------------------------------------------------------


@require_write_permission
async def terraform_init(
    runner: TerraformRunner,
    workspace: str,
    backend_config: dict[str, str] | None = None,
) -> list[TextContent]:
    """Initialize a Terraform workspace and download providers.

    Write-gated: init downloads and runs provider plugins and configures the
    state backend.

    Args:
        runner: TerraformRunner instance.
        workspace: Workspace name (subdirectory of TF_WORKSPACE_DIR).
        backend_config: Optional partial backend configuration as key/value pairs,
            limited to local, s3 and azurerm keys.
    """
    try:
        args = ["init", "-no-color"]
        if backend_config:
            args.extend(_backend_config_args(runner, workspace, backend_config))
        result = await runner.run(args, workspace, env_extra=_lm_env_vars())
        return format_response(
            {
                "workspace": workspace,
                "exit_code": result.exit_code,
                "success": result.exit_code == 0,
                "output": result.stdout[-4000:] if result.stdout else "",
                "errors": result.stderr[-2000:] if result.stderr else "",
            }
        )
    except Exception as e:
        return handle_error(e)


async def terraform_validate(
    runner: TerraformRunner,
    workspace: str,
) -> list[TextContent]:
    """Validate Terraform configuration syntax.

    Args:
        runner: TerraformRunner instance.
        workspace: Workspace name.
    """
    try:
        result = await runner.run(
            ["validate", "-json", "-no-color"], workspace, env_extra=_lm_env_vars()
        )
        try:
            parsed = json.loads(result.stdout)
        except json.JSONDecodeError:
            parsed = {"raw_output": result.stdout[-4000:]}
        return format_response(
            {
                "workspace": workspace,
                "valid": result.exit_code == 0,
                "diagnostics": parsed,
                "errors": result.stderr[-2000:] if result.stderr else "",
            }
        )
    except Exception as e:
        return handle_error(e)


@require_write_permission
async def terraform_plan(
    runner: TerraformRunner,
    workspace: str,
    var: str | None = None,
    var_file: str | None = None,
    target: str | None = None,
) -> list[TextContent]:
    """Preview Terraform changes without applying.

    Uses -detailed-exitcode: 0=no changes, 1=error, 2=changes pending.
    Write-gated: plan runs provider plugins and evaluates data sources against
    live APIs.

    Args:
        runner: TerraformRunner instance.
        workspace: Workspace name.
        var: Variable assignment (key=value).
        var_file: Path to a .tfvars file (relative to workspace).
        target: Target a specific resource address.
    """
    try:
        args = ["plan", "-json", "-no-color", "-detailed-exitcode"]
        if var:
            args.extend(["-var", var])
        if var_file:
            args.extend(
                ["-var-file", _confine_to_workspace(runner, workspace, "var_file", var_file)]
            )
        if target:
            args.extend(["-target", target])
        result = await runner.run(args, workspace, env_extra=_lm_env_vars())
        status = _parse_plan_exit_code(result.exit_code)

        # Parse JSON lines from plan output for structured summary
        plan_lines = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if line:
                try:
                    plan_lines.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        return format_response(
            {
                "workspace": workspace,
                "status": status,
                "exit_code": result.exit_code,
                "has_changes": status == "changes_pending",
                "plan_output": plan_lines[-50:],
                "errors": result.stderr[-2000:] if result.stderr and status == "error" else "",
            }
        )
    except Exception as e:
        return handle_error(e)


async def terraform_state_list(
    runner: TerraformRunner,
    workspace: str,
) -> list[TextContent]:
    """List all resources tracked in Terraform state.

    Args:
        runner: TerraformRunner instance.
        workspace: Workspace name.
    """
    try:
        result = await runner.run(["state", "list"], workspace)
        if result.exit_code != 0:
            return format_response(
                {
                    "workspace": workspace,
                    "error": True,
                    "message": result.stderr or "No state file found",
                }
            )
        resources = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        return format_response(
            {
                "workspace": workspace,
                "resource_count": len(resources),
                "resources": resources,
            }
        )
    except Exception as e:
        return handle_error(e)


async def terraform_state_show(
    runner: TerraformRunner,
    workspace: str,
    address: str,
) -> list[TextContent]:
    """Show detailed state for a specific Terraform resource.

    Args:
        runner: TerraformRunner instance.
        workspace: Workspace name.
        address: Resource address (e.g., logicmonitor_device.web01).
    """
    try:
        result = await runner.run(["state", "show", "-json", address], workspace)
        if result.exit_code != 0:
            return format_response(
                {
                    "workspace": workspace,
                    "address": address,
                    "error": True,
                    "message": result.stderr or f"Resource '{address}' not found in state",
                }
            )
        try:
            parsed = json.loads(result.stdout)
        except json.JSONDecodeError:
            parsed = {"raw_output": result.stdout[-4000:]}
        return format_response(
            {
                "workspace": workspace,
                "address": address,
                "resource": parsed,
            }
        )
    except Exception as e:
        return handle_error(e)


async def terraform_output(
    runner: TerraformRunner,
    workspace: str,
) -> list[TextContent]:
    """Show Terraform output values.

    Args:
        runner: TerraformRunner instance.
        workspace: Workspace name.
    """
    try:
        result = await runner.run(["output", "-json"], workspace)
        if result.exit_code != 0:
            return format_response(
                {
                    "workspace": workspace,
                    "outputs": {},
                    "message": result.stderr or "No outputs defined or no state",
                }
            )
        try:
            parsed = json.loads(result.stdout)
        except json.JSONDecodeError:
            parsed = {}
        return format_response(
            {
                "workspace": workspace,
                "outputs": parsed,
            }
        )
    except Exception as e:
        return handle_error(e)


# ---------------------------------------------------------------------------
# Write-gated tools (receive TerraformRunner)
# ---------------------------------------------------------------------------


@require_write_permission
async def terraform_apply(
    runner: TerraformRunner,
    workspace: str,
    var: str | None = None,
    var_file: str | None = None,
    target: str | None = None,
    confirm: bool = False,
) -> list[TextContent]:
    """Apply Terraform configuration changes.

    Triple-gated: requires LM_ENABLE_WRITE_OPERATIONS=true,
    TF_AUTO_APPROVE_ENABLED=true, and confirm=true parameter.

    Args:
        runner: TerraformRunner instance.
        workspace: Workspace name.
        var: Variable assignment (key=value).
        var_file: Path to a .tfvars file (relative to workspace).
        target: Target a specific resource address.
        confirm: Must be True to proceed. Safety gate for destructive operations.
    """
    try:
        if not runner.auto_approve_enabled:
            return format_response(
                {
                    "error": True,
                    "code": "TERRAFORM_APPLY_DISABLED",
                    "message": "Terraform apply is disabled by server configuration",
                    "suggestion": "Set TF_AUTO_APPROVE_ENABLED=true to enable apply operations",
                }
            )
        if not confirm:
            return format_response(
                {
                    "error": True,
                    "code": "CONFIRMATION_REQUIRED",
                    "message": "terraform_apply requires confirm=true parameter",
                    "suggestion": (
                        "Run terraform_plan first to review changes, "
                        "then call terraform_apply with confirm=true"
                    ),
                }
            )

        args = ["apply", "-auto-approve", "-json", "-no-color"]
        if var:
            args.extend(["-var", var])
        if var_file:
            args.extend(
                ["-var-file", _confine_to_workspace(runner, workspace, "var_file", var_file)]
            )
        if target:
            args.extend(["-target", target])
        result = await runner.run(args, workspace, env_extra=_lm_env_vars())

        apply_lines = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if line:
                try:
                    apply_lines.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        return format_response(
            {
                "workspace": workspace,
                "success": result.exit_code == 0,
                "exit_code": result.exit_code,
                "apply_output": apply_lines[-50:],
                "errors": result.stderr[-2000:] if result.stderr and result.exit_code != 0 else "",
            }
        )
    except Exception as e:
        return handle_error(e)


@require_write_permission
async def terraform_destroy(
    runner: TerraformRunner,
    workspace: str,
    target: str | None = None,
    confirm: bool = False,
) -> list[TextContent]:
    """Destroy Terraform-managed infrastructure.

    Triple-gated: requires LM_ENABLE_WRITE_OPERATIONS=true,
    TF_AUTO_APPROVE_ENABLED=true, and confirm=true parameter.

    Args:
        runner: TerraformRunner instance.
        workspace: Workspace name.
        target: Target a specific resource address to destroy.
        confirm: Must be True to proceed. Safety gate for destructive operations.
    """
    try:
        if not runner.auto_approve_enabled:
            return format_response(
                {
                    "error": True,
                    "code": "TERRAFORM_DESTROY_DISABLED",
                    "message": "Terraform destroy is disabled by server configuration",
                    "suggestion": "Set TF_AUTO_APPROVE_ENABLED=true to enable destroy operations",
                }
            )
        if not confirm:
            return format_response(
                {
                    "error": True,
                    "code": "CONFIRMATION_REQUIRED",
                    "message": "terraform_destroy requires confirm=true parameter",
                    "suggestion": (
                        "Run terraform_plan first to review what will be destroyed, "
                        "then call terraform_destroy with confirm=true"
                    ),
                }
            )

        args = ["destroy", "-auto-approve", "-json", "-no-color"]
        if target:
            args.extend(["-target", target])
        result = await runner.run(args, workspace, env_extra=_lm_env_vars())

        return format_response(
            {
                "workspace": workspace,
                "success": result.exit_code == 0,
                "exit_code": result.exit_code,
                "output": result.stdout[-4000:] if result.stdout else "",
                "errors": result.stderr[-2000:] if result.stderr and result.exit_code != 0 else "",
            }
        )
    except Exception as e:
        return handle_error(e)


@require_write_permission
async def terraform_import_resource(
    runner: TerraformRunner,
    workspace: str,
    address: str,
    resource_id: str,
) -> list[TextContent]:
    """Import an existing resource into Terraform state.

    Args:
        runner: TerraformRunner instance.
        workspace: Workspace name.
        address: Terraform resource address (e.g., logicmonitor_device.web01).
        resource_id: The real-world ID of the resource to import.
    """
    try:
        result = await runner.run(
            ["import", "-no-color", address, str(resource_id)],
            workspace,
            env_extra=_lm_env_vars(),
        )
        return format_response(
            {
                "workspace": workspace,
                "address": address,
                "resource_id": resource_id,
                "success": result.exit_code == 0,
                "exit_code": result.exit_code,
                "output": result.stdout[-4000:] if result.stdout else "",
                "errors": result.stderr[-2000:] if result.stderr and result.exit_code != 0 else "",
            }
        )
    except Exception as e:
        return handle_error(e)


@require_write_permission
async def terraform_write_config(
    runner: TerraformRunner,
    workspace: str,
    filename: str,
    content: str,
) -> list[TextContent]:
    """Write HCL configuration to a file in a Terraform workspace.

    Validates the filename ends with .tf or .tf.json and contains no path
    separators to prevent directory traversal.

    Args:
        runner: TerraformRunner instance.
        workspace: Workspace name.
        filename: Filename to write (must end with .tf or .tf.json).
        content: HCL or JSON content to write.
    """
    try:
        # Validate filename
        if "/" in filename or "\\" in filename:
            return format_response(
                {
                    "error": True,
                    "code": "INVALID_FILENAME",
                    "message": "Filename must not contain path separators",
                    "suggestion": "Use a simple filename like 'main.tf' without directory paths",
                }
            )
        if not (filename.endswith(".tf") or filename.endswith(".tf.json")):
            return format_response(
                {
                    "error": True,
                    "code": "INVALID_FILENAME",
                    "message": f"Filename must end with .tf or .tf.json, got '{filename}'",
                    "suggestion": "Use a filename like 'main.tf' or 'config.tf.json'",
                }
            )

        ws_path = runner.workspace_path(workspace)
        ws_path.mkdir(parents=True, exist_ok=True)
        file_path = ws_path / filename
        file_path.write_text(content, encoding="utf-8")

        return format_response(
            {
                "workspace": workspace,
                "filename": filename,
                "written": True,
                "bytes": len(content.encode("utf-8")),
                "path": str(file_path),
            }
        )
    except Exception as e:
        return handle_error(e)


# ---------------------------------------------------------------------------
# terraform_generate — LM-specific (receives LogicMonitorClient)
# ---------------------------------------------------------------------------

# LM API path and Terraform resource type mappings
_RESOURCE_TYPES: dict[str, dict[str, str]] = {
    "device": {"api_path": "/device/devices", "tf_type": "logicmonitor_device"},
    "device_group": {"api_path": "/device/groups", "tf_type": "logicmonitor_device_group"},
    "collector": {
        "api_path": "/setting/collector/collectors",
        "tf_type": "logicmonitor_collector",
    },
    "collector_group": {
        "api_path": "/setting/collector/groups",
        "tf_type": "logicmonitor_collector_group",
    },
    "alert_rule": {"api_path": "/setting/alert/rules", "tf_type": "logicmonitor_alert_rule"},
    "escalation_chain": {
        "api_path": "/setting/alert/chains",
        "tf_type": "logicmonitor_escalation_chain",
    },
    "dashboard": {"api_path": "/dashboard/dashboards", "tf_type": "logicmonitor_dashboard"},
    "dashboard_group": {
        "api_path": "/dashboard/groups",
        "tf_type": "logicmonitor_dashboard_group",
    },
    "datasource": {"api_path": "/setting/datasources", "tf_type": "logicmonitor_datasource"},
    "sdt": {"api_path": "/sdt/sdts", "tf_type": "logicmonitor_sdt"},
    "website": {"api_path": "/website/websites", "tf_type": "logicmonitor_website"},
    "website_group": {"api_path": "/website/groups", "tf_type": "logicmonitor_website_group"},
    "role": {"api_path": "/setting/roles", "tf_type": "logicmonitor_role"},
    "report_group": {"api_path": "/report/groups", "tf_type": "logicmonitor_report_group"},
}


def _render_device(data: dict) -> str:
    """Render a LogicMonitor device as Terraform HCL."""
    name = _safe_name(data.get("displayName", data.get("name", "device")))
    lines = [f'resource "logicmonitor_device" "{name}" {{']
    lines.append(f'  ip_addr              = "{data.get("name", "")}"')
    if data.get("displayName"):
        lines.append(f'  display_name         = "{data["displayName"]}"')
    if data.get("preferredCollectorId"):
        lines.append(f"  preferred_collector_id = {data['preferredCollectorId']}")
    if data.get("hostGroupIds"):
        lines.append(f'  host_group_ids       = "{data["hostGroupIds"]}"')
    if data.get("description"):
        desc = data["description"].replace('"', '\\"')
        lines.append(f'  description          = "{desc}"')
    if data.get("disableAlerting"):
        lines.append("  disable_alerting     = true")
    if data.get("enableNetflow"):
        lines.append("  enable_netflow       = true")
    # Custom properties
    props = data.get("customProperties", [])
    for prop in props:
        lines.append("")
        lines.append("  custom_properties {")
        lines.append(f'    name  = "{prop.get("name", "")}"')
        lines.append(f'    value = "{prop.get("value", "")}"')
        lines.append("  }")
    lines.append("}")
    return "\n".join(lines)


def _render_device_group(data: dict) -> str:
    """Render a LogicMonitor device group as Terraform HCL."""
    name = _safe_name(data.get("name", "group"))
    lines = [f'resource "logicmonitor_device_group" "{name}" {{']
    lines.append(f'  name        = "{data.get("name", "")}"')
    if data.get("parentId"):
        lines.append(f"  parent_id   = {data['parentId']}")
    if data.get("description"):
        desc = data["description"].replace('"', '\\"')
        lines.append(f'  description = "{desc}"')
    if data.get("appliesTo"):
        applies = data["appliesTo"].replace('"', '\\"')
        lines.append(f'  applies_to  = "{applies}"')
    if data.get("disableAlerting"):
        lines.append("  disable_alerting = true")
    if data.get("defaultCollectorId"):
        lines.append(f"  default_collector_id = {data['defaultCollectorId']}")
    props = data.get("customProperties", [])
    for prop in props:
        lines.append("")
        lines.append("  custom_properties {")
        lines.append(f'    name  = "{prop.get("name", "")}"')
        lines.append(f'    value = "{prop.get("value", "")}"')
        lines.append("  }")
    lines.append("}")
    return "\n".join(lines)


def _render_alert_rule(data: dict) -> str:
    """Render a LogicMonitor alert rule as Terraform HCL."""
    name = _safe_name(data.get("name", "alert_rule"))
    lines = [f'resource "logicmonitor_alert_rule" "{name}" {{']
    lines.append(f'  name     = "{data.get("name", "")}"')
    if data.get("priority") is not None:
        lines.append(f"  priority = {data['priority']}")
    if data.get("escalatingChainId"):
        lines.append(f"  escalation_chain_id = {data['escalatingChainId']}")
    if data.get("levelStr"):
        lines.append(f'  level_str = "{data["levelStr"]}"')
    # devices and deviceGroups come from the API as lists, not strings
    if data.get("devices"):
        devs = data["devices"]
        if isinstance(devs, list):
            devs = ",".join(str(d) for d in devs)
        devs = str(devs).replace('"', '\\"')
        lines.append(f'  devices   = "{devs}"')
    if data.get("deviceGroups"):
        groups = data["deviceGroups"]
        if isinstance(groups, list):
            groups = ",".join(str(g) for g in groups)
        groups = str(groups).replace('"', '\\"')
        lines.append(f'  device_groups = "{groups}"')
    if data.get("datasource"):
        lines.append(f'  datasource = "{data["datasource"]}"')
    lines.append("}")
    return "\n".join(lines)


def _render_escalation_chain(data: dict) -> str:
    """Render a LogicMonitor escalation chain as Terraform HCL."""
    name = _safe_name(data.get("name", "chain"))
    lines = [f'resource "logicmonitor_escalation_chain" "{name}" {{']
    lines.append(f'  name = "{data.get("name", "")}"')
    if data.get("enableThrottling"):
        lines.append("  enable_throttling = true")
    if data.get("throttlingPeriod"):
        lines.append(f"  throttling_period = {data['throttlingPeriod']}")
    if data.get("throttlingAlerts"):
        lines.append(f"  throttling_alerts = {data['throttlingAlerts']}")
    # destinations is required by the TF provider
    destinations = data.get("destinations", [])
    if destinations:
        for dest in destinations:
            lines.append("")
            lines.append("  destination {")
            if dest.get("type"):
                lines.append(f'    type   = "{dest["type"]}"')
            if dest.get("addr"):
                addr = str(dest["addr"]).replace('"', '\\"')
                lines.append(f'    addr   = "{addr}"')
            if dest.get("method"):
                lines.append(f'    method = "{dest["method"]}"')
            if dest.get("period") is not None:
                lines.append(f"    period = {dest['period']}")
            if dest.get("stages"):
                stages = dest["stages"]
                if isinstance(stages, list):
                    stages_str = ", ".join(str(s) for s in stages)
                    lines.append(f'    stages = "{stages_str}"')
            lines.append("  }")
    else:
        # Provider requires at least one destination block
        lines.append("")
        lines.append("  # WARNING: no destinations found in API response")
        lines.append("  # Add at least one destination block before applying")
    lines.append("}")
    return "\n".join(lines)


def _render_generic(data: dict, tf_type: str) -> str:
    """Render any LM resource as commented Terraform HCL with raw data.

    Used for resource types without a dedicated renderer.
    """
    name = _safe_name(data.get("displayName", data.get("name", data.get("id", "resource"))))
    if isinstance(name, int):
        name = f"r_{name}"
    lines = ["# Generated from LM API -- review and adjust field names"]
    lines.append(f'resource "{tf_type}" "{name}" {{')
    # Output key fields as comments for manual mapping
    skip_keys = {"id", "createdOn", "updatedOn", "createdBy", "updatedBy"}
    for key, value in data.items():
        if key in skip_keys:
            continue
        if isinstance(value, str):
            escaped = value.replace('"', '\\"')[:200]
            lines.append(f'  # {key} = "{escaped}"')
        elif isinstance(value, bool):
            lines.append(f"  # {key} = {str(value).lower()}")
        elif isinstance(value, int | float):
            lines.append(f"  # {key} = {value}")
    lines.append("}")
    return "\n".join(lines)


# Map resource types to their renderer functions
_RENDERERS: dict[str, object] = {
    "device": _render_device,
    "device_group": _render_device_group,
    "alert_rule": _render_alert_rule,
    "escalation_chain": _render_escalation_chain,
}


async def terraform_generate(
    client: LogicMonitorClient,
    resource_type: str,
    resource_id: int,
) -> list[TextContent]:
    """Export a LogicMonitor resource as Terraform HCL configuration.

    Fetches the resource from the LM API and renders it as HCL using the
    logicmonitor/logicmonitor Terraform provider schema.

    Args:
        client: LogicMonitor API client.
        resource_type: Resource type (device, device_group, alert_rule, etc.).
        resource_id: LM resource ID.
    """
    try:
        if resource_type not in _RESOURCE_TYPES:
            supported = ", ".join(sorted(_RESOURCE_TYPES.keys()))
            return format_response(
                {
                    "error": True,
                    "code": "UNSUPPORTED_RESOURCE_TYPE",
                    "message": f"Unsupported resource type: '{resource_type}'",
                    "supported_types": supported,
                }
            )

        type_info = _RESOURCE_TYPES[resource_type]
        api_path = f"{type_info['api_path']}/{resource_id}"
        data = await client.get(api_path)

        if not data or "id" not in data:
            return format_response(
                {
                    "error": True,
                    "code": "RESOURCE_NOT_FOUND",
                    "message": f"{resource_type} with ID {resource_id} not found",
                }
            )

        renderer = _RENDERERS.get(resource_type)
        hcl = renderer(data) if renderer else _render_generic(data, type_info["tf_type"])

        # Add provider block for convenience
        provider_block = (
            "# LogicMonitor Terraform Provider\n"
            "# Docs: registry.terraform.io/providers/logicmonitor/logicmonitor/latest\n"
            "terraform {\n"
            "  required_providers {\n"
            "    logicmonitor = {\n"
            '      source  = "logicmonitor/logicmonitor"\n'
            "    }\n"
            "  }\n"
            "}\n\n"
            'provider "logicmonitor" {\n'
            "  api_id  = var.lm_api_id\n"
            "  api_key = var.lm_api_key\n"
            "  company = var.lm_company\n"
            "}\n\n"
            'variable "lm_api_id" {\n'
            "  type      = string\n"
            "  sensitive = true\n"
            "}\n\n"
            'variable "lm_api_key" {\n'
            "  type      = string\n"
            "  sensitive = true\n"
            "}\n\n"
            'variable "lm_company" {\n'
            "  type = string\n"
            "}\n"
        )

        full_hcl = f"{provider_block}\n{hcl}\n"

        return format_response(
            {
                "resource_type": resource_type,
                "resource_id": resource_id,
                "terraform_type": type_info["tf_type"],
                "hcl": full_hcl,
            }
        )
    except Exception as e:
        return handle_error(e)
