# Description: Tests for MCP resource registry.
# Description: Verifies resource listing and content retrieval functions.

from __future__ import annotations

import json

import pytest

from lm_mcp.resources import RESOURCES, get_resource_content
from lm_mcp.resources.registry import get_resource_by_uri, list_resource_uris


class TestResourcesRegistry:
    """Tests for the RESOURCES list and registry functions."""

    def test_resources_list_not_empty(self):
        """RESOURCES list contains resource definitions."""
        assert len(RESOURCES) > 0

    def test_resources_have_required_fields(self):
        """Each resource has uri, name, and description."""
        for resource in RESOURCES:
            assert resource.uri is not None
            assert resource.name is not None
            assert resource.description is not None

    def test_resources_uris_are_unique(self):
        """All resource URIs are unique."""
        uris = [str(r.uri) for r in RESOURCES]
        assert len(uris) == len(set(uris))

    def test_resources_uris_follow_scheme(self):
        """All resource URIs use the lm:// scheme."""
        for resource in RESOURCES:
            assert str(resource.uri).startswith("lm://")

    def test_list_resource_uris_returns_all(self):
        """list_resource_uris returns all registered URIs."""
        uris = list_resource_uris()
        assert len(uris) == len(RESOURCES)
        for resource in RESOURCES:
            assert str(resource.uri) in uris

    def test_get_resource_by_uri_found(self):
        """get_resource_by_uri returns resource for valid URI."""
        resource = get_resource_by_uri("lm://schema/alerts")
        assert resource is not None
        assert str(resource.uri) == "lm://schema/alerts"
        assert resource.name == "Alert Schema"

    def test_get_resource_by_uri_not_found(self):
        """get_resource_by_uri returns None for invalid URI."""
        resource = get_resource_by_uri("lm://invalid/resource")
        assert resource is None


class TestGetResourceContent:
    """Tests for get_resource_content function."""

    def test_get_schema_alerts(self):
        """get_resource_content returns alert schema JSON."""
        content = get_resource_content("lm://schema/alerts")
        data = json.loads(content)
        assert data["name"] == "alerts"
        assert "fields" in data
        assert "severity" in data["fields"]
        assert "cleared" in data["fields"]

    def test_get_schema_devices(self):
        """get_resource_content returns device schema JSON."""
        content = get_resource_content("lm://schema/devices")
        data = json.loads(content)
        assert data["name"] == "devices"
        assert "fields" in data
        assert "displayName" in data["fields"]
        assert "hostStatus" in data["fields"]

    def test_get_schema_sdts(self):
        """get_resource_content returns SDT schema JSON."""
        content = get_resource_content("lm://schema/sdts")
        data = json.loads(content)
        assert data["name"] == "sdts"
        assert "fields" in data
        assert "type" in data["fields"]
        assert "startDateTime" in data["fields"]

    def test_get_enum_severity(self):
        """get_resource_content returns severity enum JSON."""
        content = get_resource_content("lm://enums/severity")
        data = json.loads(content)
        assert data["name"] == "severity"
        assert "values" in data
        assert "critical" in data["values"]
        assert data["values"]["critical"]["api_value"] == 4

    def test_get_enum_device_status(self):
        """get_resource_content returns device-status enum JSON."""
        content = get_resource_content("lm://enums/device-status")
        data = json.loads(content)
        assert data["name"] == "device-status"
        assert "values" in data
        assert "normal" in data["values"]
        assert data["values"]["normal"]["api_value"] == "normal"

    def test_get_enum_sdt_type(self):
        """get_resource_content returns sdt-type enum JSON."""
        content = get_resource_content("lm://enums/sdt-type")
        data = json.loads(content)
        assert data["name"] == "sdt-type"
        assert "values" in data
        assert "DeviceSDT" in data["values"]
        assert "DeviceGroupSDT" in data["values"]

    def test_get_filters_alerts(self):
        """get_resource_content returns alert filters JSON."""
        content = get_resource_content("lm://filters/alerts")
        data = json.loads(content)
        assert data["name"] == "alerts"
        assert "fields" in data
        assert "severity" in data["fields"]
        assert "common_queries" in data

    def test_get_filters_devices(self):
        """get_resource_content returns device filters JSON."""
        content = get_resource_content("lm://filters/devices")
        data = json.loads(content)
        assert data["name"] == "devices"
        assert "fields" in data
        assert "displayName" in data["fields"]

    def test_get_syntax_operators(self):
        """get_resource_content returns filter operators JSON."""
        content = get_resource_content("lm://syntax/operators")
        data = json.loads(content)
        assert "operators" in data
        assert ":" in data["operators"]
        assert "~" in data["operators"]
        assert ">:" in data["operators"]

    def test_invalid_uri_scheme(self):
        """get_resource_content raises ValueError for invalid scheme."""
        with pytest.raises(ValueError, match="Invalid resource URI"):
            get_resource_content("https://invalid/uri")

    def test_invalid_uri_path(self):
        """get_resource_content raises ValueError for invalid path."""
        with pytest.raises(ValueError, match="Invalid resource path"):
            get_resource_content("lm://invalid")

    def test_unknown_resource(self):
        """get_resource_content raises ValueError for unknown resource."""
        with pytest.raises(ValueError, match="Resource not found"):
            get_resource_content("lm://schema/unknown")


class TestResourceContentStructure:
    """Tests verifying resource content structure and completeness."""

    def test_all_schema_resources_loadable(self):
        """All schema resources return valid JSON."""
        schema_uris = [str(r.uri) for r in RESOURCES if "/schema/" in str(r.uri)]
        for uri in schema_uris:
            content = get_resource_content(uri)
            data = json.loads(content)
            assert "name" in data
            assert "fields" in data

    def test_all_enum_resources_loadable(self):
        """All enum resources return valid JSON."""
        enum_uris = [str(r.uri) for r in RESOURCES if "/enums/" in str(r.uri)]
        for uri in enum_uris:
            content = get_resource_content(uri)
            data = json.loads(content)
            assert "name" in data
            assert "values" in data

    def test_all_filter_resources_loadable(self):
        """All filter resources return valid JSON."""
        filter_uris = [str(r.uri) for r in RESOURCES if "/filters/" in str(r.uri)]
        for uri in filter_uris:
            content = get_resource_content(uri)
            data = json.loads(content)
            assert "name" in data
            assert "fields" in data

    def test_schema_fields_have_types(self):
        """Schema field definitions include type information."""
        content = get_resource_content("lm://schema/alerts")
        data = json.loads(content)
        for field_name, field_def in data["fields"].items():
            assert "type" in field_def, f"Field {field_name} missing type"
            assert "description" in field_def, f"Field {field_name} missing description"

    def test_filter_fields_have_operators(self):
        """Filter field definitions include supported operators."""
        content = get_resource_content("lm://filters/alerts")
        data = json.loads(content)
        for field_name, field_def in data["fields"].items():
            assert "operators" in field_def, f"Field {field_name} missing operators"
            assert len(field_def["operators"]) > 0


class TestNewSchemas:
    """Tests for the 6 new schema resources added in v1.3.0."""

    def test_escalation_schema_exists(self):
        """Escalation schema is retrievable."""
        content = get_resource_content("lm://schema/escalations")
        data = json.loads(content)
        assert data["name"] == "escalations"
        assert "fields" in data
        assert "name" in data["fields"]
        assert "enableThrottling" in data["fields"]

    def test_report_schema_exists(self):
        """Report schema is retrievable."""
        content = get_resource_content("lm://schema/reports")
        data = json.loads(content)
        assert data["name"] == "reports"
        assert "fields" in data
        assert "type" in data["fields"]
        assert "format" in data["fields"]

    def test_website_schema_exists(self):
        """Website schema is retrievable."""
        content = get_resource_content("lm://schema/websites")
        data = json.loads(content)
        assert data["name"] == "websites"
        assert "fields" in data
        assert "domain" in data["fields"]
        assert "pollingInterval" in data["fields"]

    def test_datasource_schema_exists(self):
        """DataSource schema is retrievable."""
        content = get_resource_content("lm://schema/datasources")
        data = json.loads(content)
        assert data["name"] == "datasources"
        assert "fields" in data
        assert "appliesTo" in data["fields"]
        assert "collectMethod" in data["fields"]

    def test_user_schema_exists(self):
        """User schema is retrievable."""
        content = get_resource_content("lm://schema/users")
        data = json.loads(content)
        assert data["name"] == "users"
        assert "fields" in data
        assert "username" in data["fields"]
        assert "email" in data["fields"]

    def test_audit_schema_exists(self):
        """Audit schema is retrievable."""
        content = get_resource_content("lm://schema/audit")
        data = json.loads(content)
        assert data["name"] == "audit"
        assert "fields" in data
        assert "username" in data["fields"]
        assert "happenedOn" in data["fields"]

    def test_all_11_schemas_in_registry(self):
        """All 11 schemas are registered as resources."""
        schema_uris = [str(r.uri) for r in RESOURCES if "/schema/" in str(r.uri)]
        assert len(schema_uris) == 11


class TestGuideResources:
    """Tests for guide resources (tool categories and examples)."""

    def test_tool_categories_resource_exists(self):
        """Tool categories guide resource is registered."""
        from lm_mcp.resources.registry import get_resource_by_uri

        resource = get_resource_by_uri("lm://guide/tool-categories")
        assert resource is not None

    def test_tool_categories_content(self):
        """Tool categories content has categories with tools."""
        content = get_resource_content("lm://guide/tool-categories")
        data = json.loads(content)
        assert data["name"] == "tool-categories"
        assert "categories" in data
        assert len(data["categories"]) > 10

    def test_tool_categories_covers_all_registered_tools(self):
        """Tool categories index accounts for all registered tools."""
        from lm_mcp.registry import AWX_TOOLS, TF_TOOLS, TOOLS, WATSONX_TOOLS

        content = get_resource_content("lm://guide/tool-categories")
        data = json.loads(content)

        # Collect all tools mentioned in categories
        categorized_tools = set()
        for category in data["categories"].values():
            categorized_tools.update(category["tools"])

        # Collect all registered tool names (LM + AWX + TF + WX)
        registered_tools = (
            {t.name for t in TOOLS}
            | {t.name for t in AWX_TOOLS}
            | {t.name for t in TF_TOOLS}
            | {t.name for t in WATSONX_TOOLS}
        )

        # Every registered tool should be in some category
        missing = registered_tools - categorized_tools
        assert not missing, f"Tools not in any category: {missing}"

        # Every categorized tool should be a real tool
        extra = categorized_tools - registered_tools
        assert not extra, f"Categorized tools not in registry: {extra}"

    def test_examples_resource_exists(self):
        """Common query examples resource is registered."""
        from lm_mcp.resources.registry import get_resource_by_uri

        resource = get_resource_by_uri("lm://guide/examples")
        assert resource is not None

    def test_examples_content(self):
        """Examples content has examples and filter syntax."""
        content = get_resource_content("lm://guide/examples")
        data = json.loads(content)
        assert data["name"] == "examples"
        assert "examples" in data
        assert len(data["examples"]) >= 10
        assert "filter_syntax" in data

    def test_examples_have_descriptions(self):
        """Each example has description, tool, and notes."""
        content = get_resource_content("lm://guide/examples")
        data = json.loads(content)
        for example in data["examples"]:
            assert "description" in example, f"Example missing description: {example}"
            assert "tool" in example, f"Example missing tool: {example}"
            assert "notes" in example, f"Example missing notes: {example}"

    def test_guide_unknown_returns_not_found(self):
        """Unknown guide raises ValueError."""
        with pytest.raises(ValueError, match="Resource not found"):
            get_resource_content("lm://guide/nonexistent")

    def test_all_guide_resources_loadable(self):
        """All guide resources return valid JSON."""
        guide_uris = [str(r.uri) for r in RESOURCES if "/guide/" in str(r.uri)]
        assert len(guide_uris) == 5
        for uri in guide_uris:
            content = get_resource_content(uri)
            data = json.loads(content)
            assert isinstance(data, dict)


class TestOrchestrationGuide:
    """Tests for the MCP orchestration guide resource."""

    def test_orchestration_guide_resource_exists(self):
        """Orchestration guide resource is registered."""
        from lm_mcp.resources.registry import get_resource_by_uri

        resource = get_resource_by_uri("lm://guide/mcp-orchestration")
        assert resource is not None
        assert resource.name == "MCP Server Orchestration Guide"

    def test_orchestration_guide_content_is_valid_json(self):
        """Orchestration guide returns valid JSON with required keys."""
        content = get_resource_content("lm://guide/mcp-orchestration")
        data = json.loads(content)
        assert data["name"] == "mcp-orchestration"
        assert "scenarios" in data
        assert "best_practices" in data
        assert "configuration_example" in data

    def test_orchestration_guide_has_scenarios(self):
        """Guide includes multi-server workflow scenarios."""
        content = get_resource_content("lm://guide/mcp-orchestration")
        data = json.loads(content)
        assert len(data["scenarios"]) >= 3

    def test_orchestration_guide_scenarios_have_steps(self):
        """Each scenario has name, description, and steps with server/tool."""
        content = get_resource_content("lm://guide/mcp-orchestration")
        data = json.loads(content)
        for scenario in data["scenarios"]:
            assert "name" in scenario, "Scenario missing name"
            assert "description" in scenario, "Scenario missing description"
            assert "steps" in scenario, "Scenario missing steps"
            for step in scenario["steps"]:
                assert "server" in step, "Step missing server"
                assert "tool" in step, "Step missing tool"

    def test_orchestration_guide_has_best_practices(self):
        """Guide includes best practices list."""
        content = get_resource_content("lm://guide/mcp-orchestration")
        data = json.loads(content)
        assert len(data["best_practices"]) >= 3

    def test_orchestration_guide_has_config_example(self):
        """Guide includes MCP client configuration example."""
        content = get_resource_content("lm://guide/mcp-orchestration")
        data = json.loads(content)
        config = data["configuration_example"]
        assert "mcpServers" in config
        assert "logicmonitor" in config["mcpServers"]

    def test_orchestration_guide_total_resource_count(self):
        """Total resource count is 26 after adding example-responses guide."""
        assert len(RESOURCES) == 26


class TestBestPracticesResource:
    """Tests for best practices guide resource."""

    def test_best_practices_resource_resolves(self):
        """lm://guide/best-practices returns content."""
        content = get_resource_content("lm://guide/best-practices")
        data = json.loads(content)
        assert isinstance(data, dict)
        assert len(data) > 0

    def test_best_practices_structure(self):
        """Each scenario has condition, recommended_actions, anti_patterns."""
        content = get_resource_content("lm://guide/best-practices")
        data = json.loads(content)
        for scenario_name, scenario in data.items():
            assert "condition" in scenario, f"{scenario_name} missing condition"
            assert "recommended_actions" in scenario, f"{scenario_name} missing recommended_actions"
            assert "anti_patterns" in scenario, f"{scenario_name} missing anti_patterns"
            assert isinstance(scenario["recommended_actions"], list)
            assert isinstance(scenario["anti_patterns"], list)
            for rec in scenario["recommended_actions"]:
                assert "action" in rec
                assert "how" in rec
                assert "priority" in rec

    def test_best_practices_scenarios_present(self):
        """All expected scenarios are present."""
        content = get_resource_content("lm://guide/best-practices")
        data = json.loads(content)
        expected = [
            "high_alert_noise",
            "device_health_low",
            "availability_low",
            "remediation_execution",
            "genai_monitoring",
        ]
        for scenario in expected:
            assert scenario in data, f"Missing scenario: {scenario}"

    def test_best_practices_resource_in_list(self):
        """Best practices resource URI appears in resource listing."""
        uris = list_resource_uris()
        assert "lm://guide/best-practices" in uris
