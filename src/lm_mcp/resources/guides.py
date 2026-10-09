# Description: Guide resources for LogicMonitor MCP server.
# Description: Provides tool category index and common query examples for AI agents.

from __future__ import annotations

# All LogicMonitor MCP tools organized by domain category.
# Helps AI agents pick the right tool from a large set.
TOOL_CATEGORIES = {
    "name": "tool-categories",
    "description": "All LogicMonitor MCP tools organized by domain",
    "categories": {
        "workflows": {
            "description": "Composite workflow tools -- recommended starting point",
            "tools": [
                "triage",
                "health_check",
                "capacity_plan",
                "portal_overview",
                "diagnose",
                "update_logicmodule",
                "detect_site_outage",
                "audit_network_monitoring_coverage",
            ],
        },
        "universal_reference": {
            "description": (
                "Resource/Prompt mirrors exposed as Tools for clients without those primitives"
            ),
            "tools": ["get_reference", "get_workflow"],
        },
        "discovery": {
            "description": "Tool search and discovery",
            "tools": ["search_tools"],
        },
        "devices": {
            "description": "Device/resource management",
            "tools": [
                "get_devices",
                "get_device",
                "get_device_groups",
                "get_device_group",
                "create_device",
                "update_device",
                "delete_device",
                "recover_device",
                "bulk_delete_devices",
                "create_device_group",
                "update_device_group",
                "delete_device_group",
                "get_device_properties",
                "get_device_property",
                "update_device_property",
            ],
        },
        "alerts": {
            "description": "Alert monitoring and management",
            "tools": [
                "get_alerts",
                "get_alert_details",
                "acknowledge_alert",
                "add_alert_note",
                "bulk_acknowledge_alerts",
            ],
        },
        "alert_rules": {
            "description": "Alert rule configuration",
            "tools": [
                "get_alert_rules",
                "get_alert_rule",
                "create_alert_rule",
                "update_alert_rule",
                "delete_alert_rule",
            ],
        },
        "sdts": {
            "description": "Scheduled downtime management",
            "tools": [
                "list_sdts",
                "create_sdt",
                "update_sdt",
                "delete_sdt",
                "bulk_create_device_sdt",
                "bulk_delete_sdt",
                "get_active_sdts",
                "get_upcoming_sdts",
            ],
        },
        "collectors": {
            "description": "Collector status and management",
            "tools": [
                "get_collectors",
                "get_collector",
                "get_collector_groups",
                "get_collector_group",
                "update_collector",
                "delete_collector",
                "create_collector_group",
                "update_collector_group",
                "delete_collector_group",
                "get_collector_health",
                "assess_collector_health",
                "collector_debug",
            ],
        },
        "networking": {
            "description": (
                "Network intelligence primitives: interface metrics, NetFlow top "
                "talkers, alert burst detection, link flap identification, power "
                "event filtering (UPS/PDU)"
            ),
            "tools": [
                "get_interface_metrics",
                "get_top_talkers",
                "detect_alert_burst",
                "get_link_flaps",
                "get_power_events",
            ],
        },
        "datasources": {
            "description": "DataSource and instance monitoring",
            "tools": [
                "get_device_datasources",
                "get_device_instances",
                "add_device_instance",
                "update_device_instance",
                "delete_device_instance",
                "get_device_data",
                "get_graph_data",
                "get_datasources",
                "get_datasource",
                "create_datasource",
                "update_datasource",
                "delete_datasource",
            ],
        },
        "dashboards": {
            "description": "Dashboard and widget management",
            "tools": [
                "get_dashboards",
                "get_dashboard",
                "get_dashboard_widgets",
                "get_widget",
                "create_dashboard",
                "update_dashboard",
                "delete_dashboard",
                "add_widget",
                "update_widget",
                "delete_widget",
                "get_dashboard_groups",
                "get_dashboard_group",
                "create_dashboard_group",
                "update_dashboard_group",
                "delete_dashboard_group",
            ],
        },
        "websites": {
            "description": "Website monitoring",
            "tools": [
                "get_websites",
                "get_website",
                "get_website_groups",
                "get_website_data",
                "create_website",
                "update_website",
                "delete_website",
                "create_website_group",
                "delete_website_group",
            ],
        },
        "reports": {
            "description": "Report management and execution",
            "tools": [
                "get_reports",
                "get_report",
                "get_report_groups",
                "get_scheduled_reports",
                "run_report",
                "get_report_execution",
                "create_report",
                "update_report_schedule",
                "delete_report",
            ],
        },
        "escalations": {
            "description": "Escalation chain and recipient management",
            "tools": [
                "get_escalation_chains",
                "get_escalation_chain",
                "get_recipient_groups",
                "get_recipient_group",
                "create_escalation_chain",
                "update_escalation_chain",
                "delete_escalation_chain",
                "create_recipient_group",
                "update_recipient_group",
                "delete_recipient_group",
            ],
        },
        "integrations": {
            "description": (
                "Alert delivery integrations (Custom HTTP Delivery / webhooks)."
                " CRUD on /setting/integrations. Pair with escalation chains"
                " and alert rules to route alerts to Azure Sentinel, PagerDuty,"
                " ServiceNow, etc."
            ),
            "tools": [
                "get_integrations",
                "get_integration",
                "create_http_integration",
                "update_http_integration",
                "delete_integration",
            ],
        },
        "users": {
            "description": "User, role, and access management",
            "tools": [
                "get_users",
                "get_user",
                "create_user",
                "update_user",
                "delete_user",
                "get_roles",
                "get_role",
                "get_access_groups",
                "get_access_group",
                "get_api_tokens",
                "get_api_token",
            ],
        },
        "topology": {
            "description": "Network topology and connectivity",
            "tools": [
                "get_topology_map",
                "get_device_neighbors",
                "get_device_interfaces",
                "get_network_flows",
                "get_device_connections",
            ],
        },
        "audit": {
            "description": "Audit logs and activity tracking",
            "tools": [
                "get_audit_logs",
                "get_api_token_audit",
                "get_login_audit",
                "get_change_audit",
            ],
        },
        "cost": {
            "description": "Cloud cost analysis and optimization",
            "tools": [
                "get_cost_recommendations",
                "get_idle_resources",
                "get_cost_recommendation_categories",
                "get_cost_recommendation",
            ],
        },
        "logimodules": {
            "description": "LogicModule definitions (ConfigSource, EventSource, etc.)",
            "tools": [
                "get_configsources",
                "get_configsource",
                "create_configsource",
                "update_configsource",
                "delete_configsource",
                "get_configsource_update_reasons",
                "get_device_config",
                "get_device_config_version",
                "collect_device_config",
                "get_eventsources",
                "get_eventsource",
                "create_eventsource",
                "update_eventsource",
                "delete_eventsource",
                "get_device_eventsources",
                "update_device_eventsource",
                "get_propertysources",
                "get_propertysource",
                "create_propertysource",
                "update_propertysource",
                "delete_propertysource",
                "get_topologysources",
                "get_topologysource",
                "create_topologysource",
                "update_topologysource",
                "delete_topologysource",
                "get_logsources",
                "get_logsource",
                "create_logsource",
                "update_logsource",
                "delete_logsource",
                "get_device_logsources",
            ],
        },
        "netscans": {
            "description": "Network scan management",
            "tools": [
                "get_netscans",
                "get_netscan",
                "run_netscan",
            ],
        },
        "ops": {
            "description": "Operations notes, OIDs, and services",
            "tools": [
                "get_oids",
                "get_oid",
                "get_services",
                "get_service",
                "get_service_groups",
                "get_ops_notes",
                "get_ops_note",
                "add_ops_note",
                "update_ops_note",
                "delete_ops_note",
            ],
        },
        "batchjobs": {
            "description": "Batch job monitoring",
            "tools": [
                "get_batchjobs",
                "get_batchjob",
                "get_device_batchjobs",
                "get_scheduled_downtime_jobs",
            ],
        },
        "exports": {
            "description": "Export LogicModule definitions as JSON",
            "tools": [
                "export_datasource",
                "export_dashboard",
                "export_alert_rule",
                "export_escalation_chain",
                "export_configsource",
                "export_eventsource",
                "export_propertysource",
                "export_logsource",
                "export_diagnosticsource",
                "export_remediationsource",
            ],
        },
        "imports": {
            "description": "Import LogicModule definitions from JSON",
            "tools": [
                "import_datasource",
                "import_configsource",
                "import_eventsource",
                "import_propertysource",
                "import_logsource",
                "import_topologysource",
                "import_diagnosticsource",
                "import_jobmonitor",
                "import_appliesto_function",
            ],
        },
        "ingestion": {
            "description": "Push custom logs and metrics",
            "tools": [
                "ingest_logs",
                "push_metrics",
            ],
        },
        "otlp_metrics": {
            "description": (
                "Native OTLP metrics: PromQL range queries and metric/label "
                "discovery (feature-flag gated, [PREVIEW])"
            ),
            "tools": [
                "get_otlp_metric_names",
                "get_otlp_metric_labels",
                "get_otlp_label_values",
                "query_otlp_metrics",
            ],
        },
        "correlation": {
            "description": "Alert correlation and metric anomaly detection",
            "tools": [
                "correlate_alerts",
                "get_alert_statistics",
                "get_metric_anomalies",
            ],
        },
        "traces": {
            "description": "APM trace service discovery, metrics, and properties",
            "tools": [
                "get_trace_services",
                "get_trace_service",
                "get_trace_service_alerts",
                "get_trace_service_datasources",
                "get_trace_operations",
                "get_trace_service_metrics",
                "get_trace_operation_metrics",
                "get_trace_service_properties",
            ],
        },
        "ml_analysis": {
            "description": "ML/statistical analysis and forecasting",
            "tools": [
                "forecast_metric",
                "correlate_metrics",
                "detect_change_points",
                "score_alert_noise",
                "detect_seasonality",
                "calculate_availability",
                "analyze_blast_radius",
                "correlate_changes",
                "classify_trend",
                "score_device_health",
                "calculate_error_budget",
            ],
        },
        "session": {
            "description": "Session context, variable management, and baselines",
            "tools": [
                "get_session_context",
                "set_session_variable",
                "get_session_variable",
                "delete_session_variable",
                "clear_session_context",
                "list_session_history",
                "save_baseline",
                "compare_to_baseline",
            ],
        },
        "portals": {
            "description": "Multi-portal switching: one server, many customer portals",
            "tools": [
                "list_portals",
                "use_portal",
                "current_portal",
                "reload_portals",
            ],
        },
        "ansible": {
            "description": "Ansible Automation Platform for observability-driven remediation",
            "tools": [
                "test_awx_connection",
                "get_job_templates",
                "get_job_template",
                "launch_job",
                "get_job_status",
                "get_job_output",
                "cancel_job",
                "relaunch_job",
                "get_inventories",
                "get_inventory_hosts",
                "launch_workflow",
                "get_workflow_status",
                "get_workflow_templates",
                "get_projects",
                "get_credentials",
                "get_organizations",
                "get_job_events",
                "get_hosts",
            ],
        },
        "terraform": {
            "description": "Terraform Infrastructure as Code management for any provider",
            "tools": [
                "terraform_init",
                "terraform_validate",
                "terraform_plan",
                "terraform_state_list",
                "terraform_state_show",
                "terraform_output",
                "terraform_apply",
                "terraform_destroy",
                "terraform_import",
                "terraform_write_config",
                "terraform_generate",
            ],
        },
        "remediation": {
            "description": ("Diagnostic sources, remediation sources, and remediation execution."),
            "tools": [
                "get_diagnosticsources",
                "get_diagnosticsource",
                "get_remediationsources",
                "get_remediationsource",
                "get_diagnostic_remediation_assignments",
                "get_diagnostic_remediation_results",
                "execute_remediation",
                "execute_diagnostic",
                "create_diagnosticsource",
                "update_diagnosticsource",
                "delete_diagnosticsource",
                "create_remediationsource",
                "update_remediationsource",
                "delete_remediationsource",
            ],
        },
        "actions": {
            "description": (
                "ADR automation: action chains (ordered diagnostic/remediation "
                "stages) and the rules that bind them to alerts."
            ),
            "tools": [
                "get_action_chains",
                "get_action_chain",
                "create_action_chain",
                "update_action_chain",
                "delete_action_chain",
                "get_action_rules",
                "get_action_rule",
                "create_action_rule",
                "update_action_rule",
                "delete_action_rule",
                "set_action_rule_status",
            ],
        },
        "watsonx": {
            "description": "IBM watsonx.ai summarization and forecasting",
            "tools": [
                "watsonx_summarize",
            ],
        },
    },
}

# Common filter patterns and query examples.
# Helps AI agents construct correct API filters.
COMMON_QUERY_EXAMPLES = {
    "name": "examples",
    "description": "Common LogicMonitor API filter patterns and query examples",
    "examples": [
        {
            "description": "Find active critical alerts",
            "tool": "get_alerts",
            "filter": "severity:4,cleared:false",
            "notes": "Severity 4 = critical. Boolean values do not need quotes.",
        },
        {
            "description": "Find dead devices",
            "tool": "get_devices",
            "filter": "hostStatus:1",
            "notes": "hostStatus 1 = dead. Use get_devices with status='dead'.",
        },
        {
            "description": "Find alerts for a specific device by name",
            "tool": "get_alerts",
            "filter": 'monitorObjectName:"server-01.example.com"',
            "notes": "String values MUST be double-quoted in filters.",
        },
        {
            "description": "Find devices by display name substring",
            "tool": "get_devices",
            "filter": 'displayName~"production"',
            "notes": "The ~ operator performs substring matching. No wildcards needed.",
        },
        {
            "description": "Find unacknowledged error alerts",
            "tool": "get_alerts",
            "filter": "severity:3,acked:false,cleared:false",
            "notes": "Severity 3 = error. Combine multiple filters with commas.",
        },
        {
            "description": "Find alerts started in last hour",
            "tool": "get_alerts",
            "filter": "startEpoch>:{epoch_ms}",
            "notes": "Replace {epoch_ms} with epoch milliseconds. Use >: for greater-or-equal.",
        },
        {
            "description": "Find devices in a specific group",
            "tool": "get_devices",
            "filter": "hostGroupIds~5",
            "notes": "Use ~ for contains since hostGroupIds is a comma-separated list.",
        },
        {
            "description": "Find active SDTs for a device",
            "tool": "get_active_sdts",
            "args": {"device_id": 123},
            "notes": "get_active_sdts already filters to currently active SDTs.",
        },
        {
            "description": "Find collectors by hostname",
            "tool": "get_collectors",
            "filter": 'hostname~"prod-collector"',
            "notes": "Use hostname_filter parameter for substring matching.",
        },
        {
            "description": "Find websites by name",
            "tool": "get_websites",
            "filter": 'name~"api-health"',
            "notes": "Use name_filter parameter for substring matching.",
        },
        {
            "description": "Find dashboards by owner",
            "tool": "get_dashboards",
            "filter": 'owner:"admin"',
            "notes": "Exact match with : operator. String values need quotes.",
        },
        {
            "description": "Get failed login attempts",
            "tool": "get_login_audit",
            "args": {"failed_only": True},
            "notes": "Use failed_only=True for security review.",
        },
        {
            "description": "Get idle cloud resources",
            "tool": "get_idle_resources",
            "args": {"provider": "aws"},
            "notes": "Narrow by cloud provider for targeted cost review.",
        },
        {
            "description": "Check device neighbors for topology context",
            "tool": "get_device_neighbors",
            "args": {"device_id": 123, "depth": 2},
            "notes": "Depth 1-3 controls how many hops to traverse.",
        },
    ],
    "filter_syntax": {
        "operators": {
            ":": "Exact match (equal)",
            "!:": "Not equal",
            "~": "Contains (substring match)",
            "!~": "Not contains",
            ">": "Greater than",
            "<": "Less than",
            ">:": "Greater than or equal",
            "<:": "Less than or equal",
        },
        "rules": [
            "String values MUST be wrapped in double quotes",
            "Numeric and boolean values work without quotes",
            "Combine filters with commas (logical AND)",
            "The ~ operator performs substring matching; wildcards (* ?) are stripped",
        ],
    },
}


# MCP multi-server orchestration patterns and workflows.
# Guides AI agents on combining LogicMonitor with other MCP servers.
MCP_ORCHESTRATION_GUIDE: dict = {
    "name": "mcp-orchestration",
    "description": (
        "Patterns for combining the LogicMonitor MCP server with other "
        "MCP servers to build multi-system workflows."
    ),
    "scenarios": [
        {
            "name": "Incident to Ticket",
            "description": (
                "Detect alert clusters in LogicMonitor, create incidents "
                "in PagerDuty, and file follow-up tickets in Jira."
            ),
            "steps": [
                {
                    "server": "logicmonitor",
                    "tool": "correlate_alerts",
                    "description": "Identify alert clusters by device and time",
                },
                {
                    "server": "logicmonitor",
                    "tool": "get_alert_statistics",
                    "description": "Get severity distribution and top talkers",
                },
                {
                    "server": "pagerduty",
                    "tool": "create_incident",
                    "description": "Create PagerDuty incident with alert summary",
                },
                {
                    "server": "jira",
                    "tool": "create_issue",
                    "description": "File Jira ticket with root cause notes",
                },
            ],
        },
        {
            "name": "Full RCA Workflow",
            "description": (
                "Correlate alerts, map topology, check CMDB for "
                "dependencies, and compile root cause report."
            ),
            "steps": [
                {
                    "server": "logicmonitor",
                    "tool": "correlate_alerts",
                    "description": "Find correlated alert clusters",
                },
                {
                    "server": "logicmonitor",
                    "tool": "get_device_neighbors",
                    "description": "Map network topology around affected devices",
                },
                {
                    "server": "servicenow",
                    "tool": "get_ci_dependencies",
                    "description": "Query CMDB for upstream dependencies",
                },
                {
                    "server": "logicmonitor",
                    "tool": "get_metric_anomalies",
                    "description": "Detect metric anomalies on root cause device",
                },
            ],
        },
        {
            "name": "Change Correlation",
            "description": (
                "Cross-reference LogicMonitor alerts with recent deployments "
                "from CI/CD tools to identify change-induced incidents."
            ),
            "steps": [
                {
                    "server": "logicmonitor",
                    "tool": "get_alerts",
                    "description": "Retrieve recent alerts in the time window",
                },
                {
                    "server": "github",
                    "tool": "list_deployments",
                    "description": "Get recent deployments from GitHub",
                },
                {
                    "server": "logicmonitor",
                    "tool": "get_change_audit",
                    "description": "Check for LM config changes in same window",
                },
                {
                    "server": "slack",
                    "tool": "post_message",
                    "description": "Notify team channel with correlation findings",
                },
            ],
        },
    ],
    "configuration_example": {
        "mcpServers": {
            "logicmonitor": {
                "command": "uvx",
                "args": ["mcp-server-logicmonitor"],
                "env": {
                    "LM_PORTAL": "your-portal.logicmonitor.com",
                    "LM_BEARER_TOKEN": "your-token",
                },
            },
            "pagerduty": {
                "command": "uvx",
                "args": ["mcp-server-pagerduty"],
                "env": {"PD_API_KEY": "your-key"},
            },
            "jira": {
                "command": "uvx",
                "args": ["mcp-server-jira"],
                "env": {
                    "JIRA_URL": "https://your-org.atlassian.net",
                    "JIRA_TOKEN": "your-token",
                },
            },
        },
    },
    "best_practices": [
        (
            "Start with LogicMonitor for context: always gather alert and "
            "device data before calling external systems."
        ),
        (
            "Pass structured data between servers: use JSON results from one "
            "tool as input arguments to the next."
        ),
        (
            "Handle failures gracefully: if an external MCP server is "
            "unavailable, continue the workflow with available data."
        ),
        (
            "Use session variables to store intermediate results: save "
            "baselines, correlation IDs, and ticket references for later steps."
        ),
        (
            "Scope operations narrowly: filter alerts by time window and "
            "severity before passing to external systems to reduce noise."
        ),
    ],
}


def get_guide_content(guide_name: str) -> dict | None:
    """Get guide content by name.

    Args:
        guide_name: The guide identifier.

    Returns:
        Guide content dict or None if not found.
    """
    from lm_mcp.resources.best_practices import get_best_practices
    from lm_mcp.resources.examples import get_example_responses

    guides: dict[str, dict] = {
        "tool-categories": TOOL_CATEGORIES,
        "examples": COMMON_QUERY_EXAMPLES,
        "mcp-orchestration": MCP_ORCHESTRATION_GUIDE,
        "best-practices": get_best_practices(),
        "example-responses": get_example_responses(),
    }
    return guides.get(guide_name)
