# Description: Tests for write operation audit trail logging.
# Description: Verifies that write operations emit audit events and reads do not.

import logging
from typing import ClassVar


class TestWriteToolPrefixDetection:
    """Tests for identifying write tools by prefix."""

    WRITE_PREFIXES = (
        "create_",
        "update_",
        "delete_",
        "acknowledge_",
        "add_",
        "run_",
        "bulk_",
        "import_",
        "ingest_",
        "push_",
    )

    def test_write_tools_match_prefix(self):
        """Known write tools match at least one write prefix."""
        write_tools = [
            "create_device",
            "update_device",
            "delete_device",
            "acknowledge_alert",
            "add_alert_note",
            "run_netscan",
            "bulk_acknowledge_alerts",
            "import_datasource",
            "ingest_logs",
            "push_metrics",
        ]
        for tool in write_tools:
            assert any(tool.startswith(p) for p in self.WRITE_PREFIXES), (
                f"{tool} should match a write prefix"
            )

    def test_read_tools_dont_match_prefix(self):
        """Known read tools do not match any write prefix."""
        read_tools = [
            "get_devices",
            "get_alerts",
            "list_sdts",
            "get_audit_logs",
            "get_session_context",
            "export_datasource",
        ]
        for tool in read_tools:
            assert not any(tool.startswith(p) for p in self.WRITE_PREFIXES), (
                f"{tool} should not match a write prefix"
            )

    def test_recover_and_collect_are_write_tools(self):
        """recover_device and collect_device_config are detected as write tools.

        Both mutate the portal but lacked a write prefix, so they executed without an
        audit-log entry until recover_/collect_ were added to WRITE_TOOL_PREFIXES.
        """
        from lm_mcp.logging import is_write_tool

        assert is_write_tool("recover_device")
        assert is_write_tool("collect_device_config")

    def test_write_gated_terraform_tools_are_audited(self):
        """terraform_init and terraform_plan are write-gated, so they are audited too."""
        from lm_mcp.logging import is_write_tool

        assert is_write_tool("terraform_init")
        assert is_write_tool("terraform_plan")
        assert not is_write_tool("terraform_validate")


class TestAwxWriteToolPrefixes:
    """Tests for AWX write tool prefix detection."""

    AWX_WRITE_TOOLS: ClassVar[list[str]] = [
        "launch_job",
        "cancel_job",
        "relaunch_job",
        "launch_workflow",
    ]

    def test_awx_write_tools_match_prefix(self):
        """AWX write tools match write prefixes in WRITE_TOOL_PREFIXES."""
        from lm_mcp.logging import is_write_tool

        for tool in self.AWX_WRITE_TOOLS:
            assert is_write_tool(tool), f"{tool} should be detected as a write tool"


class TestWriteAuditLogging:
    """Tests for write audit trail integration in server.py."""

    def test_log_write_operation_emits_info(self, caplog):
        """log_write_operation emits INFO-level log."""
        from lm_mcp.logging import log_write_operation

        with caplog.at_level(logging.INFO, logger="lm_mcp.audit"):
            log_write_operation("create_device", {"name": "test"}, success=True)

        assert "create_device" in caplog.text

    def test_log_write_operation_failure_emits_warning(self, caplog):
        """log_write_operation emits WARNING-level log on failure."""
        from lm_mcp.logging import log_write_operation

        with caplog.at_level(logging.WARNING, logger="lm_mcp.audit"):
            log_write_operation("delete_device", {"device_id": 1}, success=False)

        assert "delete_device" in caplog.text
        assert "failed" in caplog.text.lower()


class TestPortalAuditVisibility:
    """Portal switches are auditable and audit lines carry portal identity."""

    def test_use_portal_and_reload_portals_are_write_tools(self):
        from lm_mcp.logging import is_write_tool

        assert is_write_tool("use_portal")
        assert is_write_tool("reload_portals")
        assert not is_write_tool("list_portals")
        assert not is_write_tool("current_portal")

    def test_audit_line_includes_active_portal_in_multi_portal(
        self, monkeypatch, tmp_path, reset_portals, caplog
    ):
        import json

        from lm_mcp import portals
        from lm_mcp.logging import log_write_operation

        p = tmp_path / "portals.json"
        p.write_text(json.dumps({"acme": {"portal": "acme.example.com", "bearer_token": "t"}}))
        monkeypatch.setenv("LM_MULTI_PORTAL", "true")
        monkeypatch.setenv("LM_PORTALS_FILE", str(p))
        monkeypatch.delenv("LM_PORTAL", raising=False)
        monkeypatch.delenv("LM_BEARER_TOKEN", raising=False)
        portals.activate("acme")

        with caplog.at_level(logging.INFO, logger="lm_mcp.audit"):
            log_write_operation("create_device", {}, success=True)
        assert any("portal=acme" in r.getMessage() for r in caplog.records)

    def test_audit_line_has_no_portal_marker_in_single_portal(self, monkeypatch, caplog):
        from lm_mcp.logging import log_write_operation

        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        monkeypatch.delenv("LM_MULTI_PORTAL", raising=False)

        with caplog.at_level(logging.INFO, logger="lm_mcp.audit"):
            log_write_operation("create_device", {}, success=True)
        assert not any("portal=" in r.getMessage() for r in caplog.records)
