# Description: Tool registry for LogicMonitor MCP server.
# Description: Defines all MCP tools with schemas and handlers.

from __future__ import annotations

from typing import Any

from mcp.types import Tool, ToolAnnotations

# Annotation presets for tool categorization
_READ_ONLY = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True
)
_WRITE = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True
)
_DELETE = ToolAnnotations(
    readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=True
)
_EXPORT = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True
)
_IMPORT = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True
)
_SESSION_READ = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
)
_SESSION_WRITE = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False
)

# Shape of LM ids passed as strings (SDT and ops note ids carry letters and
# underscores), so a client refuses path characters before the call is made.
_LM_STRING_ID_PATTERN = "^[A-Za-z0-9_-]+$"

# Tool definitions organized by category
TOOLS: list[Tool] = []

# Devices
TOOLS.extend(
    [
        Tool(
            name="get_devices",
            description="List devices (resources) from LogicMonitor with optional filtering",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "group_id": {"type": "integer", "description": "Filter by device group ID"},
                    "name_filter": {
                        "type": "string",
                        "description": "Filter by display name (substring match)",
                    },
                    "hostname_filter": {
                        "type": "string",
                        "description": "Filter by hostname or IP address (substring match)",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["normal", "dead", "dead-collector", "unmonitored", "disabled"],
                        "description": "Filter by device status",
                    },
                    "filter": {
                        "type": "string",
                        "description": "Raw filter expression (overrides other filters). "
                        "Syntax: field:value, field~value. String values must be quoted: "
                        'displayName~"server". Custom property queries use dot-notation: '
                        'customProperties.name:"env",customProperties.value:"prod"',
                    },
                    "limit": {
                        "type": "integer",
                        "default": 50,
                        "description": "Max results (max 1000)",
                    },
                    "offset": {"type": "integer", "default": 0, "description": "Pagination offset"},
                },
            },
        ),
        Tool(
            name="get_device",
            description="Get detailed information about a specific device (resource)",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "integer", "description": "Device ID"},
                },
                "required": ["device_id"],
            },
        ),
        Tool(
            name="get_device_groups",
            description="List device/resource groups from LogicMonitor",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "parent_id": {"type": "integer", "description": "Filter by parent group ID"},
                    "name_filter": {
                        "type": "string",
                        "description": "Filter by group name (substring match)",
                    },
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                },
            },
        ),
        Tool(
            name="get_device_group",
            description=(
                "Get detailed information about a specific device/resource group,"
                " including appliesTo expression and parent ID"
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "group_id": {"type": "integer", "description": "Device group ID"},
                },
                "required": ["group_id"],
            },
        ),
        Tool(
            name="create_device",
            description="Create a new device/resource (requires write permission)",
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Device hostname or IP address"},
                    "display_name": {"type": "string", "description": "Display name"},
                    "preferred_collector_id": {"type": "integer", "description": "Collector ID"},
                    "host_group_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Group IDs",
                    },
                    "description": {"type": "string", "description": "Device description"},
                    "custom_properties": {"type": "object", "description": "Custom properties"},
                },
                "required": ["name", "display_name", "preferred_collector_id"],
            },
        ),
        Tool(
            name="update_device",
            description="Update an existing device/resource (requires write permission). "
            "Custom properties are merged with existing properties (not replaced).",
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "integer", "description": "Device ID to update"},
                    "display_name": {"type": "string", "description": "New display name"},
                    "description": {"type": "string", "description": "New description"},
                    "host_group_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "New group IDs",
                    },
                    "preferred_collector_id": {
                        "type": "integer",
                        "description": "New collector ID",
                    },
                    "disable_alerting": {"type": "boolean", "description": "Disable alerting"},
                    "custom_properties": {"type": "object", "description": "Custom properties"},
                },
                "required": ["device_id"],
            },
        ),
        Tool(
            name="delete_device",
            description=(
                "Delete a device/resource (requires write permission). Soft delete by default."
            ),
            annotations=_DELETE,
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "integer", "description": "Device ID to delete"},
                    "delete_hard": {
                        "type": "boolean",
                        "default": False,
                        "description": "Permanently delete",
                    },
                },
                "required": ["device_id"],
            },
        ),
        Tool(
            name="recover_device",
            description=(
                "Recover a soft-deleted device/resource (requires write permission)."
                " Only works within the recovery window."
            ),
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "integer", "description": "Device ID to recover"},
                },
                "required": ["device_id"],
            },
        ),
        Tool(
            name="bulk_delete_devices",
            description=(
                "Delete multiple devices/resources in one operation"
                " (max 100, requires write permission). Soft delete by default."
            ),
            annotations=_DELETE,
            inputSchema={
                "type": "object",
                "properties": {
                    "device_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Device IDs to delete (max 100)",
                    },
                    "delete_hard": {
                        "type": "boolean",
                        "default": False,
                        "description": "Permanently delete (default: soft delete)",
                    },
                },
                "required": ["device_ids"],
            },
        ),
        Tool(
            name="create_device_group",
            description="Create a new device/resource group (requires write permission)",
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Group name"},
                    "parent_id": {
                        "type": "integer",
                        "default": 1,
                        "description": "Parent group ID (1=root)",
                    },
                    "description": {"type": "string", "description": "Group description"},
                    "applies_to": {
                        "type": "string",
                        "description": "AppliesTo expression for dynamic membership",
                    },
                    "custom_properties": {"type": "object", "description": "Custom properties"},
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="update_device_group",
            description=(
                "Update a device/resource group (requires write permission)."
                " Custom properties are merged with existing."
            ),
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "group_id": {"type": "integer", "description": "Device group ID to update"},
                    "name": {"type": "string", "description": "New group name"},
                    "description": {"type": "string", "description": "New group description"},
                    "applies_to": {
                        "type": "string",
                        "description": "New AppliesTo expression for dynamic membership",
                    },
                    "parent_id": {
                        "type": "integer",
                        "description": "New parent group ID (moves the group)",
                    },
                    "disable_alerting": {
                        "type": "boolean",
                        "description": "Disable alerting for all devices in this group",
                    },
                    "custom_properties": {
                        "type": "object",
                        "description": "Custom properties to set/update (merged with existing)",
                    },
                },
                "required": ["group_id"],
            },
        ),
        Tool(
            name="delete_device_group",
            description="Delete a device/resource group (requires write permission). Shows impact.",
            annotations=_DELETE,
            inputSchema={
                "type": "object",
                "properties": {
                    "group_id": {"type": "integer", "description": "Group ID to delete"},
                    "delete_children": {
                        "type": "boolean",
                        "default": False,
                        "description": "Delete child devices/groups",
                    },
                    "delete_hard": {
                        "type": "boolean",
                        "default": False,
                        "description": "Permanently delete",
                    },
                },
                "required": ["group_id"],
            },
        ),
    ]
)

# Alerts
TOOLS.extend(
    [
        Tool(
            name="get_alerts",
            description=(
                "Get alerts from LogicMonitor with optional filtering"
                "\n\nFor Kubernetes clusters, use group_id (from "
                "get_device_groups) instead of device — the device name "
                "filter does not work reliably for K8s resources."
                "\n\nCommon mistakes: startEpoch/endEpoch use SECONDS not "
                "milliseconds. String filter values need double quotes "
                '(e.g., monitorObjectName:"hostname").'
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "severity": {
                        "type": "string",
                        "enum": ["critical", "error", "warning", "info"],
                        "description": "Filter by severity",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["active", "acknowledged"],
                        "description": "Filter by status",
                    },
                    "cleared": {"type": "boolean", "description": "Filter by cleared status"},
                    "acked": {"type": "boolean", "description": "Filter by acknowledged status"},
                    "sdted": {"type": "boolean", "description": "Filter by SDT status"},
                    "start_epoch": {
                        "type": "integer",
                        "description": "Filter alerts started after this epoch timestamp",
                    },
                    "end_epoch": {
                        "type": "integer",
                        "description": "Filter alerts started before this epoch timestamp",
                    },
                    "datapoint": {
                        "type": "string",
                        "description": "Filter by datapoint name (substring match)",
                    },
                    "instance": {
                        "type": "string",
                        "description": "Filter by instance name (substring match)",
                    },
                    "datasource": {
                        "type": "string",
                        "description": "Filter by datasource/template name (substring match)",
                    },
                    "device": {
                        "type": "string",
                        "description": "Filter by device name (substring match)",
                    },
                    "group_id": {
                        "type": "integer",
                        "description": "Filter by device group ID (matches all devices)",
                    },
                    "device_id": {
                        "type": "integer",
                        "description": "Filter by device/resource ID",
                    },
                    "filter": {
                        "type": "string",
                        "description": "Raw filter expression (overrides other filters). "
                        "Example: severity:4,cleared:false",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 50,
                        "description": "Max results (max 1000)",
                    },
                    "offset": {"type": "integer", "default": 0, "description": "Pagination offset"},
                },
            },
        ),
        Tool(
            name="get_alert_details",
            description="Get detailed information about a specific alert",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "alert_id": {
                        "type": "string",
                        "description": "Alert ID (with or without LMA prefix)",
                    },
                    "include_message": {
                        "type": "boolean",
                        "default": False,
                        "description": "Include the full alert message body (needMessage)",
                    },
                },
                "required": ["alert_id"],
            },
        ),
        Tool(
            name="acknowledge_alert",
            description=(
                "Acknowledge an alert (requires write permission)"
                "\n\nCommon mistakes: alert_id works with or without "
                "the LMA prefix."
            ),
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "alert_id": {
                        "type": "string",
                        "description": "Alert ID (with or without LMA prefix)",
                    },
                    "note": {"type": "string", "description": "Optional acknowledgment note"},
                },
                "required": ["alert_id"],
            },
        ),
        Tool(
            name="add_alert_note",
            description="Add a note to an alert without acknowledging (requires write permission)",
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "alert_id": {
                        "type": "string",
                        "description": "Alert ID (with or without LMA prefix)",
                    },
                    "note": {"type": "string", "description": "Note text to add"},
                },
                "required": ["alert_id", "note"],
            },
        ),
        Tool(
            name="bulk_acknowledge_alerts",
            description="Acknowledge multiple alerts at once (max 100, requires write permission)",
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "alert_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Alert IDs (max 100)",
                    },
                    "note": {"type": "string", "description": "Optional acknowledgment note"},
                },
                "required": ["alert_ids"],
            },
        ),
    ]
)

# SDTs (Scheduled Downtime)
TOOLS.extend(
    [
        Tool(
            name="list_sdts",
            description="List scheduled downtimes from LogicMonitor",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {
                        "type": "integer",
                        "description": "Filter by device ID",
                    },
                    "device_group_id": {
                        "type": "integer",
                        "description": "Filter by device group ID",
                    },
                    "sdt_type": {
                        "type": "string",
                        "enum": ["DeviceSDT", "DeviceGroupSDT", "DeviceDataSourceSDT"],
                        "description": "Filter by SDT type",
                    },
                    "admin": {
                        "type": "string",
                        "description": "Filter by admin username (substring match)",
                    },
                    "filter": {
                        "type": "string",
                        "description": "Raw filter expression (overrides other filters). "
                        "Example: type:DeviceSDT,admin~john",
                    },
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                },
            },
        ),
        Tool(
            name="create_sdt",
            description=(
                "Create a scheduled downtime (requires write permission)"
                "\n\nCommon mistakes: duration_minutes is MINUTES not "
                "hours/seconds. DeviceSDT needs device_id, "
                "DeviceGroupSDT needs device_group_id. "
                "DeviceDataSourceSDT needs device_id + datasource_id. "
                "Cloud resources (collector_id=-2) may not support DeviceSDT; "
                "use DeviceGroupSDT on their parent group instead."
            ),
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "sdt_type": {
                        "type": "string",
                        "enum": [
                            "DeviceSDT",
                            "DeviceGroupSDT",
                            "DeviceDataSourceSDT",
                            "DeviceDataSourceInstanceSDT",
                            "DeviceDataSourceInstanceGroupSDT",
                            "DeviceBatchJobSDT",
                            "DeviceClusterAlertDefSDT",
                            "DeviceEventSourceSDT",
                            "ServiceSDT",
                            "ServiceGroupSDT",
                            "WebsiteSDT",
                            "WebsiteGroupSDT",
                            "CollectorSDT",
                        ],
                        "description": "SDT type",
                    },
                    "device_id": {
                        "type": "integer",
                        "description": "Device ID (for Device* SDT types)",
                    },
                    "device_group_id": {
                        "type": "integer",
                        "description": "Device group ID (for DeviceGroupSDT)",
                    },
                    "datasource_id": {
                        "type": "integer",
                        "description": "Datasource ID (for DeviceDataSourceSDT)",
                    },
                    "duration_minutes": {
                        "type": "integer",
                        "default": 60,
                        "description": "Duration in minutes",
                    },
                    "comment": {"type": "string", "description": "SDT comment"},
                },
                "required": ["sdt_type"],
            },
        ),
        Tool(
            name="delete_sdt",
            description="Delete a scheduled downtime (requires write permission)",
            annotations=_DELETE,
            inputSchema={
                "type": "object",
                "properties": {
                    "sdt_id": {
                        "type": "string",
                        "pattern": _LM_STRING_ID_PATTERN,
                        "description": "SDT ID to delete",
                    },
                },
                "required": ["sdt_id"],
            },
        ),
        Tool(
            name="update_sdt",
            description=(
                "Update a scheduled downtime (requires write permission)."
                " Uses fetch-modify-PUT to preserve unmodified fields."
            ),
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "sdt_id": {
                        "type": "string",
                        "pattern": _LM_STRING_ID_PATTERN,
                        "description": "SDT ID to update",
                    },
                    "end_date_time": {
                        "type": "integer",
                        "description": "New end time in epoch milliseconds",
                    },
                    "start_date_time": {
                        "type": "integer",
                        "description": "New start time in epoch milliseconds",
                    },
                    "comment": {"type": "string", "description": "New SDT comment"},
                },
                "required": ["sdt_id"],
            },
        ),
        Tool(
            name="bulk_create_device_sdt",
            description=(
                "Create SDT for multiple devices/resources (max 100, requires write permission)"
            ),
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "device_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Device IDs (max 100)",
                    },
                    "duration_minutes": {
                        "type": "integer",
                        "default": 60,
                        "description": "Duration (max 7 days)",
                    },
                    "comment": {"type": "string", "description": "SDT comment"},
                },
                "required": ["device_ids"],
            },
        ),
        Tool(
            name="bulk_delete_sdt",
            description="Delete multiple SDTs at once (max 100, requires write permission)",
            annotations=_DELETE,
            inputSchema={
                "type": "object",
                "properties": {
                    "sdt_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "SDT IDs (max 100)",
                    },
                },
                "required": ["sdt_ids"],
            },
        ),
        Tool(
            name="get_active_sdts",
            description="Get currently active SDTs",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "integer", "description": "Filter by device ID"},
                    "device_group_id": {"type": "integer", "description": "Filter by group ID"},
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                },
            },
        ),
        Tool(
            name="get_upcoming_sdts",
            description="Get SDTs scheduled to start within a time window",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "hours_ahead": {
                        "type": "integer",
                        "default": 24,
                        "description": "Hours ahead to look",
                    },
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                },
            },
        ),
    ]
)

# Collectors
TOOLS.extend(
    [
        Tool(
            name="get_collectors",
            description="List collectors from LogicMonitor",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "hostname_filter": {
                        "type": "string",
                        "description": "Filter by hostname (substring match)",
                    },
                    "collector_group_id": {
                        "type": "integer",
                        "description": "Filter by collector group ID",
                    },
                    "filter": {
                        "type": "string",
                        "description": "Raw filter expression (overrides other filters). "
                        "Example: hostname~prod,collectorGroupId:1",
                    },
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                    "offset": {"type": "integer", "default": 0, "description": "Pagination offset"},
                },
            },
        ),
        Tool(
            name="get_collector",
            description="Get detailed information about a specific collector",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "collector_id": {"type": "integer", "description": "Collector ID"},
                },
                "required": ["collector_id"],
            },
        ),
        Tool(
            name="get_collector_groups",
            description="List collector groups",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "name_filter": {
                        "type": "string",
                        "description": "Filter by name (substring)",
                    },
                    "filter": {
                        "type": "string",
                        "description": "Raw filter expression (overrides name_filter). "
                        "Example: name~prod,autoBalance:true",
                    },
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                    "offset": {"type": "integer", "default": 0, "description": "Pagination offset"},
                },
            },
        ),
        Tool(
            name="get_collector_group",
            description="Get details about a specific collector group",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "group_id": {"type": "integer", "description": "Collector group ID"},
                },
                "required": ["group_id"],
            },
        ),
        Tool(
            name="update_collector",
            description=(
                "Update a collector (requires write permission)."
                " Change group, description, failback, or escalation chain."
            ),
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "collector_id": {"type": "integer", "description": "Collector ID to update"},
                    "description": {"type": "string", "description": "New description"},
                    "collector_group_id": {
                        "type": "integer",
                        "description": "New collector group ID",
                    },
                    "enable_failback": {
                        "type": "boolean",
                        "description": "Enable automatic failback",
                    },
                    "escalation_chain_id": {
                        "type": "integer",
                        "description": "Escalation chain ID for collector down alerts",
                    },
                },
                "required": ["collector_id"],
            },
        ),
        Tool(
            name="delete_collector",
            description=(
                "Delete a collector (requires write permission)."
                " Blocks if devices are still assigned."
            ),
            annotations=_DELETE,
            inputSchema={
                "type": "object",
                "properties": {
                    "collector_id": {"type": "integer", "description": "Collector ID to delete"},
                },
                "required": ["collector_id"],
            },
        ),
        Tool(
            name="create_collector_group",
            description="Create a collector group (requires write permission)",
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Group name"},
                    "description": {"type": "string", "description": "Description"},
                    "auto_balance": {
                        "type": "boolean",
                        "description": "Enable auto-balancing",
                    },
                    "auto_balance_strategy": {
                        "type": "string",
                        "description": "Auto-balance strategy (e.g., roundRobin)",
                    },
                    "custom_properties": {
                        "type": "object",
                        "description": "Custom properties as key-value pairs",
                    },
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="update_collector_group",
            description="Update a collector group (requires write permission)",
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "group_id": {
                        "type": "integer",
                        "description": "Collector group ID to update",
                    },
                    "name": {"type": "string", "description": "New group name"},
                    "description": {"type": "string", "description": "New description"},
                    "auto_balance": {
                        "type": "boolean",
                        "description": "Enable/disable auto-balancing",
                    },
                    "auto_balance_strategy": {
                        "type": "string",
                        "description": "New auto-balance strategy",
                    },
                    "custom_properties": {
                        "type": "object",
                        "description": "Custom properties to merge",
                    },
                },
                "required": ["group_id"],
            },
        ),
        Tool(
            name="delete_collector_group",
            description=(
                "Delete a collector group (requires write permission)."
                " Blocks if collectors are still assigned."
            ),
            annotations=_DELETE,
            inputSchema={
                "type": "object",
                "properties": {
                    "group_id": {
                        "type": "integer",
                        "description": "Collector group ID to delete",
                    },
                },
                "required": ["group_id"],
            },
        ),
    ]
)

# Metrics and Data
TOOLS.extend(
    [
        Tool(
            name="get_device_datasources",
            description=(
                "Get datasources applied to a device (resource)"
                "\n\nCommon mistakes: Returns device-datasource associations "
                "not definitions. The ID returned here is device_datasource_id "
                "for use with get_device_data."
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "integer", "description": "Device ID"},
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                },
                "required": ["device_id"],
            },
        ),
        Tool(
            name="get_device_instances",
            description="Get instances of a datasource on a device (resource)",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "integer", "description": "Device ID"},
                    "device_datasource_id": {
                        "type": "integer",
                        "description": "Device-DataSource ID (from get_device_datasources)",
                    },
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                },
                "required": ["device_id", "device_datasource_id"],
            },
        ),
        Tool(
            name="add_device_instance",
            description=(
                "Add a monitored instance to a datasource on a device"
                " (requires write permission)."
                " Used for datasources without Active Discovery"
                " (e.g. ServiceStatus)."
            ),
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "integer", "description": "Device ID"},
                    "device_datasource_id": {
                        "type": "integer",
                        "description": "Device-DataSource ID (from get_device_datasources)",
                    },
                    "display_name": {
                        "type": "string",
                        "description": "Display name for the instance",
                    },
                    "wild_value": {
                        "type": "string",
                        "description": (
                            "Wildcard value used by the datasource"
                            " to query this instance"
                            " (e.g. 'nginx.service' for"
                            " ServiceStatus, a port number"
                            " for Port-)"
                        ),
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional instance description",
                    },
                },
                "required": ["device_id", "device_datasource_id", "display_name", "wild_value"],
            },
        ),
        Tool(
            name="update_device_instance",
            description="Update a monitored instance on a device (requires write permission)",
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "integer", "description": "Device ID"},
                    "device_datasource_id": {
                        "type": "integer",
                        "description": "Device-DataSource ID",
                    },
                    "instance_id": {"type": "integer", "description": "Instance ID to update"},
                    "display_name": {"type": "string", "description": "New display name"},
                    "description": {"type": "string", "description": "New description"},
                    "stop_monitoring": {
                        "type": "boolean",
                        "description": "Stop or resume monitoring for this instance",
                    },
                    "disable_alerting": {
                        "type": "boolean",
                        "description": "Disable or enable alerting for this instance",
                    },
                },
                "required": ["device_id", "device_datasource_id", "instance_id"],
            },
        ),
        Tool(
            name="delete_device_instance",
            description=(
                "Delete a monitored instance from a datasource"
                " on a device (requires write permission)"
            ),
            annotations=_DELETE,
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "integer", "description": "Device ID"},
                    "device_datasource_id": {
                        "type": "integer",
                        "description": "Device-DataSource ID",
                    },
                    "instance_id": {"type": "integer", "description": "Instance ID to delete"},
                },
                "required": ["device_id", "device_datasource_id", "instance_id"],
            },
        ),
        Tool(
            name="get_device_data",
            description=(
                "Get metric data for a device/resource datasource instance"
                "\n\nCommon mistakes: Returns most recent data unless "
                "period/start/end specified. Requires device_datasource_id "
                "(from get_device_datasources) not the datasource definition ID."
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "integer", "description": "Device ID"},
                    "device_datasource_id": {
                        "type": "integer",
                        "description": "Device-DataSource ID (from get_device_datasources)",
                    },
                    "instance_id": {"type": "integer", "description": "Instance ID"},
                    "datapoints": {
                        "type": "string",
                        "description": "Comma-separated datapoint names (optional, all if omitted)",
                    },
                    "start_time": {
                        "type": "integer",
                        "description": "Start time in epoch seconds (optional)",
                    },
                    "end_time": {
                        "type": "integer",
                        "description": "End time in epoch seconds (optional)",
                    },
                },
                "required": ["device_id", "device_datasource_id", "instance_id"],
            },
        ),
        Tool(
            name="get_graph_data",
            description="Get graph image data for visualization",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "integer", "description": "Device ID"},
                    "device_datasource_id": {
                        "type": "integer",
                        "description": "Device-DataSource ID (from get_device_datasources)",
                    },
                    "instance_id": {"type": "integer", "description": "Instance ID"},
                    "graph_id": {"type": "integer", "description": "Graph ID"},
                    "start_time": {
                        "type": "integer",
                        "description": "Start time in epoch seconds (optional)",
                    },
                    "end_time": {
                        "type": "integer",
                        "description": "End time in epoch seconds (optional)",
                    },
                },
                "required": ["device_id", "device_datasource_id", "instance_id", "graph_id"],
            },
        ),
    ]
)

# Dashboards
TOOLS.extend(
    [
        Tool(
            name="get_dashboards",
            description="List dashboards from LogicMonitor",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "name_filter": {"type": "string", "description": "Filter by name (substring)"},
                    "group_id": {"type": "integer", "description": "Filter by group ID"},
                    "filter": {
                        "type": "string",
                        "description": "Raw filter expression (overrides other filters). "
                        "Example: name~prod,owner:admin",
                    },
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                    "offset": {"type": "integer", "default": 0, "description": "Pagination offset"},
                },
            },
        ),
        Tool(
            name="get_dashboard",
            description="Get detailed information about a specific dashboard",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "dashboard_id": {"type": "integer", "description": "Dashboard ID"},
                },
                "required": ["dashboard_id"],
            },
        ),
        Tool(
            name="get_dashboard_widgets",
            description="Get widgets configured on a dashboard",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "dashboard_id": {"type": "integer", "description": "Dashboard ID"},
                },
                "required": ["dashboard_id"],
            },
        ),
        Tool(
            name="get_widget",
            description="Get details about a specific widget",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "dashboard_id": {"type": "integer", "description": "Dashboard ID"},
                    "widget_id": {"type": "integer", "description": "Widget ID"},
                },
                "required": ["dashboard_id", "widget_id"],
            },
        ),
        Tool(
            name="create_dashboard",
            description="Create a dashboard, optionally from template (requires write permission)",
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Dashboard name"},
                    "group_id": {
                        "type": "integer",
                        "default": 1,
                        "description": "Dashboard group ID",
                    },
                    "description": {"type": "string", "description": "Dashboard description"},
                    "sharable": {
                        "type": "boolean",
                        "default": True,
                        "description": "Make dashboard sharable",
                    },
                    "widget_tokens": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Widget token overrides "
                        '(e.g., [{"name": "##host##", "value": "server1"}])',
                    },
                    "template": {
                        "type": "object",
                        "description": "Full dashboard definition to clone from "
                        "(from export_dashboard). Name is overridden, id is stripped.",
                    },
                    "template_path": {
                        "type": "string",
                        "description": "Path to a local JSON file holding the dashboard "
                        "definition or an export_dashboard envelope; loaded by reference so "
                        "a large export stays out of context. Ignored if template is set.",
                    },
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="update_dashboard",
            description="Update an existing dashboard (requires write permission)",
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "dashboard_id": {"type": "integer", "description": "Dashboard ID to update"},
                    "name": {"type": "string", "description": "New name"},
                    "description": {"type": "string", "description": "New description"},
                    "group_id": {"type": "integer", "description": "New group ID"},
                    "sharable": {"type": "boolean", "description": "Make dashboard sharable"},
                },
                "required": ["dashboard_id"],
            },
        ),
        Tool(
            name="delete_dashboard",
            description="Delete a dashboard (requires write permission)",
            annotations=_DELETE,
            inputSchema={
                "type": "object",
                "properties": {
                    "dashboard_id": {"type": "integer", "description": "Dashboard ID to delete"},
                },
                "required": ["dashboard_id"],
            },
        ),
        Tool(
            name="add_widget",
            description="Add a widget to a dashboard (requires write permission). "
            "For text widgets: use 'content' (not 'html') as the config key. "
            "For bigNumber widgets: dataPoints need 'name' field, include "
            "'bigNumberItems' array, colorThresholds use 'relation'/'threshold', "
            "aggregateFunction is lowercase (e.g., 'average'). "
            "For cgraph widgets: deviceDisplayName/deviceGroupFullPath/instanceName "
            "must be GlobMatchToggle objects {'value': '...', 'isGlob': true}, "
            "dataPoints need 'display' object, graphInfo needs 'aggregate': false "
            "when using topX. "
            "For deviceSLA widgets: required config fields are 'groupName' "
            "(not deviceGroupFullPath), 'deviceName', 'dataSourceFullName', "
            "'metric', 'threshold'. Also required: 'daysInWeek' (e.g., "
            "'1,2,3,4,5,6,7'), 'periodInOneDay' (e.g., '0:00-23:59'), "
            "'displayType' (0=availability, 1=timeline), 'calculationMethod' "
            "(0=percent, 1=actual), 'unmonitoredTimeAlertStatus' (0=ignore, "
            "1=warning, 2=error, 3=critical).",
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "dashboard_id": {"type": "integer", "description": "Dashboard ID"},
                    "name": {"type": "string", "description": "Widget name"},
                    "widget_type": {
                        "type": "string",
                        "description": "Widget type (cgraph, sgraph, bigNumber, text, "
                        "html, alert, noc, gauge, pieChart, table, etc.)",
                    },
                    "column_index": {
                        "type": "integer",
                        "description": "Start column, 1-12. Omit to let the portal "
                        "auto-place the widget below existing widgets.",
                    },
                    "row": {
                        "type": "integer",
                        "description": "Start row. Omit to append below existing widgets.",
                    },
                    "row_span": {
                        "type": "integer",
                        "description": "Height in rows (default 1 when a position is set).",
                    },
                    "col_span": {
                        "type": "integer",
                        "description": "Width in columns, 1-12 (default 6 when a position is set).",
                    },
                    "description": {"type": "string", "description": "Widget description"},
                    "config": {
                        "type": "object",
                        "description": "Widget configuration (type-specific). "
                        "Merged into the request payload.",
                    },
                },
                "required": ["dashboard_id", "name", "widget_type"],
            },
        ),
        Tool(
            name="update_widget",
            description="Update a widget (requires write permission)",
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "dashboard_id": {"type": "integer", "description": "Dashboard ID"},
                    "widget_id": {"type": "integer", "description": "Widget ID"},
                    "name": {"type": "string", "description": "New name"},
                    "description": {"type": "string", "description": "New description"},
                    "column_index": {"type": "integer", "description": "New start column (1-12)"},
                    "row": {"type": "integer", "description": "New start row"},
                    "row_span": {"type": "integer", "description": "New height in rows"},
                    "col_span": {"type": "integer", "description": "New width in columns (1-12)"},
                    "config": {"type": "object", "description": "New configuration"},
                },
                "required": ["dashboard_id", "widget_id"],
            },
        ),
        Tool(
            name="delete_widget",
            description="Delete a widget from a dashboard (requires write permission)",
            annotations=_DELETE,
            inputSchema={
                "type": "object",
                "properties": {
                    "dashboard_id": {"type": "integer", "description": "Dashboard ID"},
                    "widget_id": {"type": "integer", "description": "Widget ID to delete"},
                },
                "required": ["dashboard_id", "widget_id"],
            },
        ),
    ]
)

# Dashboard Groups
TOOLS.extend(
    [
        Tool(
            name="get_dashboard_groups",
            description="List dashboard groups",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                },
            },
        ),
        Tool(
            name="get_dashboard_group",
            description="Get details about a specific dashboard group",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "group_id": {"type": "integer", "description": "Dashboard group ID"},
                },
                "required": ["group_id"],
            },
        ),
        Tool(
            name="create_dashboard_group",
            description="Create a dashboard group in LogicMonitor (requires write permission)",
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name of the dashboard group"},
                    "parent_id": {
                        "type": "integer",
                        "description": "Parent group ID (optional)",
                    },
                    "description": {"type": "string", "description": "Optional description"},
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="delete_dashboard_group",
            description="Delete a dashboard group from LogicMonitor (requires write permission)",
            annotations=_DELETE,
            inputSchema={
                "type": "object",
                "properties": {
                    "group_id": {
                        "type": "integer",
                        "description": "Dashboard group ID to delete",
                    },
                },
                "required": ["group_id"],
            },
        ),
        Tool(
            name="update_dashboard_group",
            description="Update a dashboard group (requires write permission)",
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "group_id": {
                        "type": "integer",
                        "description": "Dashboard group ID to update",
                    },
                    "name": {"type": "string", "description": "New group name"},
                    "description": {"type": "string", "description": "New description"},
                    "parent_id": {
                        "type": "integer",
                        "description": "New parent group ID",
                    },
                },
                "required": ["group_id"],
            },
        ),
    ]
)

# Websites
TOOLS.extend(
    [
        Tool(
            name="get_websites",
            description="List websites from LogicMonitor",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "name_filter": {"type": "string", "description": "Filter by name (substring)"},
                    "group_id": {"type": "integer", "description": "Filter by website group ID"},
                    "filter": {
                        "type": "string",
                        "description": "Raw filter expression (overrides other filters). "
                        "Example: name~prod,type:webcheck",
                    },
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                    "offset": {"type": "integer", "default": 0, "description": "Pagination offset"},
                },
            },
        ),
        Tool(
            name="get_website",
            description="Get detailed information about a specific website",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "website_id": {"type": "integer", "description": "Website ID"},
                },
                "required": ["website_id"],
            },
        ),
        Tool(
            name="get_website_groups",
            description="List website groups",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "parent_id": {"type": "integer", "description": "Filter by parent group ID"},
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                },
            },
        ),
        Tool(
            name="get_website_data",
            description="Get synthetic check data for a website",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "website_id": {"type": "integer", "description": "Website ID"},
                    "checkpoint_id": {"type": "integer", "description": "Checkpoint ID"},
                    "start_time": {
                        "type": "integer",
                        "description": "Start time in epoch seconds (optional)",
                    },
                    "end_time": {
                        "type": "integer",
                        "description": "End time in epoch seconds (optional)",
                    },
                },
                "required": ["website_id", "checkpoint_id"],
            },
        ),
        Tool(
            name="create_website",
            description="Create a website check in LogicMonitor (requires write permission)",
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name of the website check"},
                    "website_type": {
                        "type": "string",
                        "enum": ["webcheck", "pingcheck"],
                        "description": "Type of check",
                    },
                    "domain": {"type": "string", "description": "Domain or host to check"},
                    "description": {"type": "string", "description": "Optional description"},
                    "group_id": {"type": "integer", "description": "Website group ID"},
                    "polling_interval": {
                        "type": "integer",
                        "default": 5,
                        "description": "Check interval in minutes",
                    },
                    "is_internal": {
                        "type": "boolean",
                        "default": False,
                        "description": "Whether this is an internal website",
                    },
                },
                "required": ["name", "website_type", "domain"],
            },
        ),
        Tool(
            name="update_website",
            description="Update a website check in LogicMonitor (requires write permission)",
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "website_id": {"type": "integer", "description": "Website ID to update"},
                    "name": {"type": "string", "description": "Updated name"},
                    "description": {"type": "string", "description": "Updated description"},
                    "polling_interval": {
                        "type": "integer",
                        "description": "Updated polling interval in minutes",
                    },
                    "is_internal": {
                        "type": "boolean",
                        "description": "Updated internal website flag",
                    },
                    "disable_alerting": {
                        "type": "boolean",
                        "description": "Whether to disable alerting",
                    },
                },
                "required": ["website_id"],
            },
        ),
        Tool(
            name="delete_website",
            description="Delete a website check from LogicMonitor (requires write permission)",
            annotations=_DELETE,
            inputSchema={
                "type": "object",
                "properties": {
                    "website_id": {"type": "integer", "description": "Website ID to delete"},
                },
                "required": ["website_id"],
            },
        ),
        Tool(
            name="create_website_group",
            description="Create a website group in LogicMonitor (requires write permission)",
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name of the website group"},
                    "parent_id": {"type": "integer", "description": "Parent group ID (optional)"},
                    "description": {"type": "string", "description": "Optional description"},
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="delete_website_group",
            description="Delete a website group from LogicMonitor (requires write permission)",
            annotations=_DELETE,
            inputSchema={
                "type": "object",
                "properties": {
                    "group_id": {"type": "integer", "description": "Group ID to delete"},
                },
                "required": ["group_id"],
            },
        ),
    ]
)

# Reports
TOOLS.extend(
    [
        Tool(
            name="get_reports",
            description="List reports from LogicMonitor",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "name_filter": {"type": "string", "description": "Filter by name (substring)"},
                    "group_id": {"type": "integer", "description": "Filter by group ID"},
                    "report_type": {"type": "string", "description": "Filter by type"},
                    "filter": {
                        "type": "string",
                        "description": "Raw filter expression (overrides other filters). "
                        "Example: name~monthly,type~Alert",
                    },
                    "include_nextgen": {
                        "type": "boolean",
                        "default": False,
                        "description": "Include NextGen reports",
                    },
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                    "offset": {"type": "integer", "default": 0, "description": "Pagination offset"},
                },
            },
        ),
        Tool(
            name="get_report",
            description="Get detailed information about a specific report",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "report_id": {"type": "integer", "description": "Report ID"},
                },
                "required": ["report_id"],
            },
        ),
        Tool(
            name="get_report_groups",
            description="List report groups",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "name_filter": {"type": "string", "description": "Filter by name (substring)"},
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                },
            },
        ),
        Tool(
            name="get_scheduled_reports",
            description="Get reports with schedules configured",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "enabled_only": {
                        "type": "boolean",
                        "default": False,
                        "description": "Only enabled schedules",
                    },
                    "include_nextgen": {
                        "type": "boolean",
                        "default": False,
                        "description": "Include NextGen reports",
                    },
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                },
            },
        ),
        Tool(
            name="run_report",
            description="Run/execute a report (requires write permission)",
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "report_id": {"type": "integer", "description": "Report ID to run"},
                    "notify_email": {
                        "type": "string",
                        "description": "Email to notify when complete",
                    },
                },
                "required": ["report_id"],
            },
        ),
        Tool(
            name="get_report_execution",
            description=(
                "Poll the status of a report generation task started by run_report "
                "(returns status and result URL when finished)"
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "report_id": {"type": "integer", "description": "Report ID"},
                    "task_id": {
                        "type": "integer",
                        "description": "Task ID returned by run_report",
                    },
                },
                "required": ["report_id", "task_id"],
            },
        ),
        Tool(
            name="create_report",
            description="Create a new report (requires write permission)",
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Report name"},
                    "report_type": {"type": "string", "description": "Report type"},
                    "group_id": {"type": "integer", "default": 1, "description": "Report group ID"},
                    "description": {"type": "string", "description": "Report description"},
                    "format": {"type": "string", "default": "PDF", "description": "Output format"},
                    "schedule_cron": {
                        "type": "string",
                        "description": "Cron expression to schedule generation "
                        "(omit for on-demand only)",
                    },
                    "schedule_timezone": {
                        "type": "string",
                        "description": "Schedule timezone (e.g. America/Los_Angeles)",
                    },
                },
                "required": ["name", "report_type"],
            },
        ),
        Tool(
            name="update_report_schedule",
            description="Update a report's schedule (requires write permission)",
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "report_id": {"type": "integer", "description": "Report ID to update"},
                    "enabled": {
                        "type": "boolean",
                        "description": "Pass false to clear (disable) the schedule",
                    },
                    "cron": {"type": "string", "description": "Cron expression, e.g. 0 8 * * 1"},
                    "timezone": {
                        "type": "string",
                        "description": "Schedule timezone -> scheduleTimezone",
                    },
                },
                "required": ["report_id"],
            },
        ),
        Tool(
            name="delete_report",
            description="Delete a report (requires write permission)",
            annotations=_DELETE,
            inputSchema={
                "type": "object",
                "properties": {
                    "report_id": {"type": "integer", "description": "Report ID to delete"},
                },
                "required": ["report_id"],
            },
        ),
    ]
)

# Escalation Chains
TOOLS.extend(
    [
        Tool(
            name="get_escalation_chains",
            description="List escalation chains",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                },
            },
        ),
        Tool(
            name="get_escalation_chain",
            description="Get details about a specific escalation chain",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "chain_id": {"type": "integer", "description": "Escalation chain ID"},
                },
                "required": ["chain_id"],
            },
        ),
        Tool(
            name="get_recipient_groups",
            description="List recipient groups",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "name_filter": {
                        "type": "string",
                        "description": "Filter by group name (supports wildcards)",
                    },
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                    "detail": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "When true, fetch each group's full recipient list via an extra"
                            " GET per group. Off by default to avoid N+1 API calls."
                        ),
                    },
                },
            },
        ),
        Tool(
            name="get_recipient_group",
            description="Get details about a specific recipient group",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "group_id": {"type": "integer", "description": "Recipient group ID"},
                },
                "required": ["group_id"],
            },
        ),
        Tool(
            name="create_escalation_chain",
            description="Create an escalation chain (requires write permission)",
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name of the escalation chain"},
                    "description": {"type": "string", "description": "Optional description"},
                    "enable_throttling": {
                        "type": "boolean",
                        "default": False,
                        "description": "Enable alert throttling",
                    },
                    "throttling_period": {
                        "type": "integer",
                        "description": "Throttling period in minutes",
                    },
                    "throttling_alerts": {
                        "type": "integer",
                        "description": "Number of alerts before throttling",
                    },
                    "destinations": {
                        "type": "array",
                        "description": (
                            "List of Chain objects. Each Chain has type ('single' or"
                            " 'timebased'), optional period object (null for 'single'),"
                            " and stages (list of stage arrays; each stage is a list of"
                            " Recipient objects). To route to an LM Integration, use a"
                            " Recipient with type='admin', addr=<username>, and"
                            " method=<integration display name>. Lowercase 'admin'."
                            " Shorthand {type: 'integration', integration_name: ...,"
                            " admin: ...} is rewritten to the canonical admin+method"
                            " form before the request hits the API."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "enum": ["single", "timebased"],
                                },
                                "period": {"type": ["object", "null"]},
                                "stages": {
                                    "type": "array",
                                    "description": (
                                        "List of stage arrays; each stage is a list"
                                        " of Recipient objects {type, addr, method,"
                                        " contact}."
                                    ),
                                    "items": {
                                        "type": "array",
                                        "items": {"type": "object"},
                                    },
                                },
                            },
                            "required": ["type", "stages"],
                        },
                        "examples": [
                            [
                                {
                                    "type": "single",
                                    "period": None,
                                    "stages": [
                                        [
                                            {
                                                "type": "admin",
                                                "addr": "rmatuszewski",
                                                "method": ("Azure Sentinel Pipeline (POC)"),
                                            }
                                        ]
                                    ],
                                }
                            ]
                        ],
                    },
                    "cc_destinations": {
                        "type": "array",
                        "description": (
                            "CC Recipient list. Each entry is a Recipient {type, addr,"
                            " method, contact}. Applied to every stage."
                        ),
                        "items": {"type": "object"},
                    },
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="update_escalation_chain",
            description="Update an escalation chain (requires write permission)",
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "chain_id": {"type": "integer", "description": "Escalation chain ID"},
                    "name": {"type": "string", "description": "Updated name"},
                    "description": {"type": "string", "description": "Updated description"},
                    "enable_throttling": {
                        "type": "boolean",
                        "description": "Updated throttling setting",
                    },
                    "throttling_period": {
                        "type": "integer",
                        "description": "Updated throttling period in minutes",
                    },
                    "throttling_alerts": {
                        "type": "integer",
                        "description": "Updated number of alerts before throttling",
                    },
                    "destinations": {
                        "type": "array",
                        "description": (
                            "Updated list of Chain objects. Same shape as on create:"
                            " {type, period, stages}. See create_escalation_chain for"
                            " the full Recipient shape and integration-routing form."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "enum": ["single", "timebased"],
                                },
                                "period": {"type": ["object", "null"]},
                                "stages": {
                                    "type": "array",
                                    "items": {
                                        "type": "array",
                                        "items": {"type": "object"},
                                    },
                                },
                            },
                            "required": ["type", "stages"],
                        },
                    },
                    "cc_destinations": {
                        "type": "array",
                        "description": "Updated CC Recipient list.",
                        "items": {"type": "object"},
                    },
                },
                "required": ["chain_id"],
            },
        ),
        Tool(
            name="delete_escalation_chain",
            description="Delete an escalation chain (requires write permission)",
            annotations=_DELETE,
            inputSchema={
                "type": "object",
                "properties": {
                    "chain_id": {"type": "integer", "description": "Escalation chain ID"},
                },
                "required": ["chain_id"],
            },
        ),
        Tool(
            name="create_recipient_group",
            description="Create a recipient group (requires write permission)",
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": (
                            "Name of the recipient group. Sent as groupName to the LM v3 API."
                        ),
                    },
                    "description": {"type": "string", "description": "Optional description"},
                    "recipients": {
                        "type": "array",
                        "description": (
                            "Optional initial recipients. Each entry is a Recipient"
                            " {type, method, addr, contact}. ``type`` and ``method``"
                            " are required by the LM API."
                        ),
                        "items": {"type": "object"},
                        "examples": [
                            [
                                {
                                    "type": "admin",
                                    "method": "email",
                                    "addr": "oncall@example.com",
                                }
                            ]
                        ],
                    },
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="update_recipient_group",
            description="Update a recipient group (requires write permission)",
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "group_id": {"type": "integer", "description": "Recipient group ID"},
                    "name": {
                        "type": "string",
                        "description": ("Updated name. Sent as groupName to the LM v3 API."),
                    },
                    "description": {"type": "string", "description": "Updated description"},
                    "recipients": {
                        "type": "array",
                        "description": (
                            "Replacement recipient list. When provided, LM replaces"
                            " the group's current recipient set with this list."
                        ),
                        "items": {"type": "object"},
                    },
                },
                "required": ["group_id"],
            },
        ),
        Tool(
            name="delete_recipient_group",
            description="Delete a recipient group (requires write permission)",
            annotations=_DELETE,
            inputSchema={
                "type": "object",
                "properties": {
                    "group_id": {"type": "integer", "description": "Recipient group ID"},
                },
                "required": ["group_id"],
            },
        ),
    ]
)

# Integrations (Custom HTTP Delivery)
TOOLS.extend(
    [
        Tool(
            name="get_integrations",
            description=(
                "List LogicMonitor integrations (Custom HTTP Delivery, Slack,"
                " PagerDuty, etc.). Returns a short summary per integration."
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "name_filter": {
                        "type": "string",
                        "description": "Filter by integration name (supports wildcards).",
                    },
                    "type_filter": {
                        "type": "string",
                        "description": (
                            "Exact-match filter on the integration type, e.g."
                            " 'http' for Custom HTTP Delivery, 'slack-2',"
                            " 'pagerduty'. Wildcards are not supported for"
                            " type."
                        ),
                    },
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                },
            },
        ),
        Tool(
            name="get_integration",
            description=(
                "Get a specific integration's full definition. Field set"
                " depends on integration type; password/OAuth secret"
                " fields are masked."
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "integration_id": {
                        "type": "integer",
                        "description": "Integration ID",
                    },
                },
                "required": ["integration_id"],
            },
        ),
        Tool(
            name="create_http_integration",
            description=(
                "Create a Custom HTTP Delivery integration (type=http)."
                " Required fields: name, url. Use extra_fields for"
                " OAuth, actionNotes*, updateData*, or the 'extra' UI"
                " metadata blob. (requires write permission)"
            ),
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Integration display name"},
                    "url": {
                        "type": "string",
                        "description": "Webhook URL for the active alert lifecycle",
                    },
                    "description": {"type": "string", "description": "Optional description"},
                    "http_method": {
                        "type": "string",
                        "default": "post",
                        "description": "HTTP verb for active alert posts",
                    },
                    "headers": {
                        "type": ["object", "array"],
                        "description": (
                            "Headers for active alerts. Accepts a plain"
                            " {name: value} dict or a list of {HeaderName:"
                            " value} single-key dicts (LM's native form)."
                        ),
                        "examples": [
                            {"Authorization": "Bearer ...", "Content-Type": "application/json"}
                        ],
                    },
                    "alert_body": {
                        "type": "string",
                        "description": (
                            "Payload template. Supports LM ##TOKEN## substitutions"
                            " such as ##ALERTID##, ##LEVEL##, ##HOST##."
                        ),
                    },
                    "alert_body_format": {
                        "type": "string",
                        "default": "json",
                        "description": "Payload format (json or form).",
                    },
                    "alert_data_type": {
                        "type": "string",
                        "description": "LM alert data type, typically 'raw' or 'formatted'.",
                    },
                    "username": {"type": "string", "description": "Basic-auth username"},
                    "password": {"type": "string", "description": "Basic-auth password"},
                    "enabled_lifecycles": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Subset of ['active', 'ack', 'clear', 'update',"
                            " 'actionNotes', 'updateData']. Defaults to the"
                            " four core lifecycles."
                        ),
                    },
                    "ack_url": {"type": "string", "description": "Override URL for ack"},
                    "ack_method": {"type": "string", "description": "Override HTTP verb for ack"},
                    "ack_body": {"type": "string", "description": "Override payload for ack"},
                    "ack_headers": {
                        "type": ["object", "array"],
                        "description": "Override headers for ack (same shape as headers).",
                    },
                    "clear_url": {"type": "string", "description": "Override URL for clear"},
                    "clear_method": {"type": "string"},
                    "clear_body": {"type": "string"},
                    "clear_headers": {"type": ["object", "array"]},
                    "update_url": {"type": "string", "description": "Override URL for update"},
                    "update_method": {"type": "string"},
                    "update_body": {"type": "string"},
                    "update_headers": {"type": ["object", "array"]},
                    "extra_fields": {
                        "type": "object",
                        "description": (
                            "Raw LM integration fields merged last. Use for"
                            " OAuth credentials (oAuthClientId, etc.),"
                            " updateData*, actionNotes*, and the 'extra'"
                            " UI metadata string."
                        ),
                    },
                },
                "required": ["name", "url"],
            },
        ),
        Tool(
            name="update_http_integration",
            description=(
                "Update a Custom HTTP Delivery integration via PATCH. Only"
                " fields explicitly provided are sent; omitted fields keep"
                " their current server values. (requires write permission)"
            ),
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "integration_id": {
                        "type": "integer",
                        "description": "Integration ID",
                    },
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "url": {"type": "string"},
                    "http_method": {"type": "string"},
                    "headers": {"type": ["object", "array"]},
                    "alert_body": {"type": "string"},
                    "alert_body_format": {"type": "string"},
                    "alert_data_type": {"type": "string"},
                    "username": {"type": "string"},
                    "password": {"type": "string"},
                    "enabled_lifecycles": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "ack_url": {"type": "string"},
                    "ack_method": {"type": "string"},
                    "ack_body": {"type": "string"},
                    "ack_headers": {"type": ["object", "array"]},
                    "clear_url": {"type": "string"},
                    "clear_method": {"type": "string"},
                    "clear_body": {"type": "string"},
                    "clear_headers": {"type": ["object", "array"]},
                    "update_url": {"type": "string"},
                    "update_method": {"type": "string"},
                    "update_body": {"type": "string"},
                    "update_headers": {"type": ["object", "array"]},
                    "extra_fields": {"type": "object"},
                },
                "required": ["integration_id"],
            },
        ),
        Tool(
            name="delete_integration",
            description=(
                "Delete an integration by ID. Works for any integration"
                " type (http, slack-2, pagerduty, etc.). (requires write"
                " permission)"
            ),
            annotations=_DELETE,
            inputSchema={
                "type": "object",
                "properties": {
                    "integration_id": {
                        "type": "integer",
                        "description": "Integration ID",
                    },
                },
                "required": ["integration_id"],
            },
        ),
    ]
)

# Alert Rules
TOOLS.extend(
    [
        Tool(
            name="get_alert_rules",
            description="List alert rules",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                },
            },
        ),
        Tool(
            name="get_alert_rule",
            description="Get details about a specific alert rule",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "rule_id": {"type": "integer", "description": "Alert rule ID"},
                },
                "required": ["rule_id"],
            },
        ),
        Tool(
            name="create_alert_rule",
            description="Create an alert rule in LogicMonitor (requires write permission)",
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name of the alert rule"},
                    "priority": {
                        "type": "integer",
                        "description": "Priority level (lower = higher priority)",
                    },
                    "escalation_chain_id": {
                        "type": "integer",
                        "description": "Escalation chain ID for the rule",
                    },
                    "level_str": {
                        "type": "string",
                        "enum": ["Critical", "Error", "Warning", "All"],
                        "description": "Alert level filter",
                    },
                    "devices": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of device patterns to match",
                    },
                    "device_groups": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of device group patterns to match",
                    },
                    "datasource": {"type": "string", "description": "DataSource pattern to match"},
                    "datapoint": {"type": "string", "description": "DataPoint pattern to match"},
                    "instance": {"type": "string", "description": "Instance pattern to match"},
                    "suppress_alert_clear": {
                        "type": "boolean",
                        "default": False,
                        "description": "Suppress alert clear notifications",
                    },
                    "suppress_alert_ack_sdt": {
                        "type": "boolean",
                        "default": False,
                        "description": "Suppress ack/SDT notifications",
                    },
                },
                "required": ["name", "priority", "escalation_chain_id"],
            },
        ),
        Tool(
            name="update_alert_rule",
            description="Update an alert rule in LogicMonitor (requires write permission)",
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "rule_id": {"type": "integer", "description": "Alert rule ID to update"},
                    "name": {"type": "string", "description": "Updated name"},
                    "priority": {"type": "integer", "description": "Updated priority level"},
                    "escalation_chain_id": {
                        "type": "integer",
                        "description": "Updated escalation chain ID",
                    },
                    "level_str": {"type": "string", "description": "Updated alert level filter"},
                    "suppress_alert_clear": {
                        "type": "boolean",
                        "description": "Updated suppress alert clear setting",
                    },
                    "suppress_alert_ack_sdt": {
                        "type": "boolean",
                        "description": "Updated suppress ack/SDT setting",
                    },
                },
                "required": ["rule_id"],
            },
        ),
        Tool(
            name="delete_alert_rule",
            description="Delete an alert rule from LogicMonitor (requires write permission)",
            annotations=_DELETE,
            inputSchema={
                "type": "object",
                "properties": {
                    "rule_id": {"type": "integer", "description": "Alert rule ID to delete"},
                },
                "required": ["rule_id"],
            },
        ),
    ]
)

# Users and Roles
TOOLS.extend(
    [
        Tool(
            name="get_users",
            description="List users from LogicMonitor",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "name_filter": {
                        "type": "string",
                        "description": "Filter by username (substring match)",
                    },
                    "filter": {
                        "type": "string",
                        "description": "Raw filter expression (overrides name_filter). "
                        "Example: username~admin,status:active",
                    },
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                    "offset": {"type": "integer", "default": 0, "description": "Pagination offset"},
                },
            },
        ),
        Tool(
            name="get_user",
            description="Get details about a specific user",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "integer", "description": "User ID"},
                },
                "required": ["user_id"],
            },
        ),
        Tool(
            name="get_roles",
            description="List roles",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "name_filter": {
                        "type": "string",
                        "description": "Filter by role name (substring match)",
                    },
                    "filter": {
                        "type": "string",
                        "description": "Raw filter expression (overrides name_filter). "
                        "Example: name~admin,twoFARequired:true",
                    },
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                    "offset": {"type": "integer", "default": 0, "description": "Pagination offset"},
                },
            },
        ),
        Tool(
            name="get_role",
            description="Get details about a specific role",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "role_id": {"type": "integer", "description": "Role ID"},
                },
                "required": ["role_id"],
            },
        ),
        Tool(
            name="create_user",
            description="Create a user in LogicMonitor (requires write permission)",
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "username": {"type": "string", "description": "Login username"},
                    "email": {"type": "string", "description": "Email address"},
                    "first_name": {"type": "string", "description": "First name"},
                    "last_name": {"type": "string", "description": "Last name"},
                    "roles": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Role IDs to assign",
                    },
                    "password": {"type": "string", "description": "Initial password"},
                    "phone": {"type": "string", "description": "Phone number"},
                    "sms_email": {"type": "string", "description": "SMS email"},
                    "note": {"type": "string", "description": "Admin note"},
                    "api_only": {
                        "type": "boolean",
                        "default": False,
                        "description": "API-only user (no portal access)",
                    },
                    "two_fa_enabled": {
                        "type": "boolean",
                        "default": False,
                        "description": "Require two-factor auth",
                    },
                },
                "required": ["username", "email", "first_name", "last_name", "roles"],
            },
        ),
        Tool(
            name="update_user",
            description="Update a user in LogicMonitor (requires write permission)",
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "integer", "description": "User ID to update"},
                    "email": {"type": "string", "description": "New email"},
                    "first_name": {"type": "string", "description": "New first name"},
                    "last_name": {"type": "string", "description": "New last name"},
                    "roles": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "New role IDs (replaces existing)",
                    },
                    "phone": {"type": "string", "description": "New phone number"},
                    "sms_email": {"type": "string", "description": "New SMS email"},
                    "note": {"type": "string", "description": "New admin note"},
                    "api_only": {"type": "boolean", "description": "API-only flag"},
                    "two_fa_enabled": {"type": "boolean", "description": "Two-factor flag"},
                },
                "required": ["user_id"],
            },
        ),
        Tool(
            name="delete_user",
            description="Delete a user from LogicMonitor (requires write permission)",
            annotations=_DELETE,
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "integer", "description": "User ID to delete"},
                },
                "required": ["user_id"],
            },
        ),
    ]
)

# Access Groups
TOOLS.extend(
    [
        Tool(
            name="get_access_groups",
            description="List access groups",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                },
            },
        ),
        Tool(
            name="get_access_group",
            description="Get details about a specific access group",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "group_id": {"type": "integer", "description": "Access group ID"},
                },
                "required": ["group_id"],
            },
        ),
    ]
)

# API Tokens
TOOLS.extend(
    [
        Tool(
            name="get_api_tokens",
            description="List API tokens",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "admin_id": {
                        "type": "integer",
                        "description": "User ID whose tokens to list (omit for all tokens)",
                    },
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                },
            },
        ),
        Tool(
            name="get_api_token",
            description="Get details about a specific API token",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "token_id": {"type": "integer", "description": "API token ID"},
                    "admin_id": {
                        "type": "integer",
                        "description": "Owning user ID (optional; looked up when omitted)",
                    },
                },
                "required": ["token_id"],
            },
        ),
    ]
)

# Resources and Properties
TOOLS.extend(
    [
        Tool(
            name="get_device_properties",
            description="Get all properties of a device (resource)",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "integer", "description": "Device ID"},
                    "name_filter": {
                        "type": "string",
                        "description": "Filter by property name (substring match)",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 100,
                        "description": "Max results",
                    },
                },
                "required": ["device_id"],
            },
        ),
        Tool(
            name="get_device_property",
            description="Get a specific property of a device (resource)",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "integer", "description": "Device ID"},
                    "property_name": {"type": "string", "description": "Property name"},
                },
                "required": ["device_id", "property_name"],
            },
        ),
        Tool(
            name="update_device_property",
            description="Update or create a device/resource property (requires write permission)",
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "integer", "description": "Device ID"},
                    "property_name": {"type": "string", "description": "Property name"},
                    "property_value": {"type": "string", "description": "Property value"},
                },
                "required": ["device_id", "property_name", "property_value"],
            },
        ),
    ]
)

# Datasources
TOOLS.extend(
    [
        Tool(
            name="get_datasources",
            description="List datasources from LogicMonitor",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "name_filter": {"type": "string", "description": "Filter by name (substring)"},
                    "applies_to_filter": {
                        "type": "string",
                        "description": "Filter by appliesTo expression",
                    },
                    "filter": {
                        "type": "string",
                        "description": "Raw filter expression (overrides other filters). "
                        "Example: name~CPU,group:Core",
                    },
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                    "offset": {"type": "integer", "default": 0, "description": "Pagination offset"},
                },
            },
        ),
        Tool(
            name="get_datasource",
            description="Get details about a specific datasource",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "datasource_id": {"type": "integer", "description": "Datasource ID"},
                },
                "required": ["datasource_id"],
            },
        ),
        Tool(
            name="create_datasource",
            description="Create a DataSource via REST API from a full definition dict "
            "(requires write permission). Accepts REST API format (same as "
            "export_datasource output). Use for round-tripping exports or building "
            "definitions from scratch. For LM Exchange format, use import_datasource. "
            "Script DataSource datapoints require appropriate type values.",
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "definition": {
                        "type": "object",
                        "description": "Full DataSource definition in REST API format",
                    },
                    "overwrite": {
                        "type": "boolean",
                        "default": False,
                        "description": "If true, delete existing DataSource with same name "
                        "before creating",
                    },
                },
                "required": ["definition"],
            },
        ),
        Tool(
            name="update_datasource",
            description=(
                "RAW UPDATE -- full-replace semantics. Any field omitted from "
                "`definition` is BLANKED on the server. Two prior production incidents "
                "wiped Groovy scripts via this tool. PREFER update_logicmodule"
                "(type='datasource', id, changes, mode='preview') for partial updates "
                "with diff preview. Requires confirm=true to proceed."
            ),
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "datasource_id": {
                        "type": "integer",
                        "description": "DataSource ID to update",
                    },
                    "definition": {
                        "type": "object",
                        "description": "FULL DataSource definition with all fields (will replace)",
                    },
                    "confirm": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "Must be true to proceed. Defaults to false to prevent "
                            "accidental field-blanking. Use update_logicmodule for safe "
                            "partial updates."
                        ),
                    },
                },
                "required": ["datasource_id", "definition"],
            },
        ),
        Tool(
            name="delete_datasource",
            description="Delete a DataSource definition "
            "(requires write permission). Existing collected data is retained.",
            annotations=_DELETE,
            inputSchema={
                "type": "object",
                "properties": {
                    "datasource_id": {
                        "type": "integer",
                        "description": "DataSource ID to delete",
                    },
                },
                "required": ["datasource_id"],
            },
        ),
    ]
)

# ConfigSources, EventSources, PropertySources, TopologySources, LogSources
TOOLS.extend(
    [
        Tool(
            name="get_configsources",
            description="List ConfigSources",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "name_filter": {"type": "string", "description": "Filter by name (substring)"},
                    "applies_to_filter": {
                        "type": "string",
                        "description": "Filter by appliesTo expression",
                    },
                    "filter": {
                        "type": "string",
                        "description": "Raw filter expression (overrides other filters). "
                        "Example: name~Cisco,technology:snmp",
                    },
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                    "offset": {"type": "integer", "default": 0, "description": "Pagination offset"},
                },
            },
        ),
        Tool(
            name="get_configsource",
            description="Get details about a specific ConfigSource",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "configsource_id": {"type": "integer", "description": "ConfigSource ID"},
                },
                "required": ["configsource_id"],
            },
        ),
        Tool(
            name="get_configsource_update_reasons",
            description="Get update history and audit trail for a ConfigSource",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "configsource_id": {"type": "integer", "description": "ConfigSource ID"},
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                    "offset": {"type": "integer", "default": 0, "description": "Pagination offset"},
                },
                "required": ["configsource_id"],
            },
        ),
        Tool(
            name="get_device_config",
            description="List config versions collected for a device instance",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "integer", "description": "Device ID"},
                    "device_datasource_id": {
                        "type": "integer",
                        "description": "Device-DataSource ID for the ConfigSource",
                    },
                    "instance_id": {
                        "type": "integer",
                        "description": "Instance ID (e.g. Running-Config)",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 10,
                        "description": "Max config versions to return",
                    },
                    "offset": {"type": "integer", "default": 0, "description": "Pagination offset"},
                },
                "required": ["device_id", "device_datasource_id", "instance_id"],
            },
        ),
        Tool(
            name="get_device_config_version",
            description="Get a specific config version with full content and diffs",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "integer", "description": "Device ID"},
                    "device_datasource_id": {
                        "type": "integer",
                        "description": "Device-DataSource ID for the ConfigSource",
                    },
                    "instance_id": {"type": "integer", "description": "Instance ID"},
                    "config_id": {
                        "type": "string",
                        "description": "Config version ID (from get_device_config)",
                    },
                    "start_epoch": {
                        "type": "integer",
                        "default": 0,
                        "description": "Epoch to compare against. "
                        "Use 0 to compare with previous version.",
                    },
                },
                "required": ["device_id", "device_datasource_id", "instance_id", "config_id"],
            },
        ),
        Tool(
            name="collect_device_config",
            description="Trigger an on-demand config collection for a device instance",
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "integer", "description": "Device ID"},
                    "device_datasource_id": {
                        "type": "integer",
                        "description": "Device-DataSource ID for the ConfigSource",
                    },
                    "instance_id": {"type": "integer", "description": "Instance ID"},
                },
                "required": ["device_id", "device_datasource_id", "instance_id"],
            },
        ),
        Tool(
            name="get_eventsources",
            description="List EventSources",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "name_filter": {"type": "string", "description": "Filter by name (substring)"},
                    "applies_to_filter": {
                        "type": "string",
                        "description": "Filter by appliesTo expression",
                    },
                    "filter": {
                        "type": "string",
                        "description": "Raw filter expression (overrides other filters). "
                        "Example: name~Windows,group:Events",
                    },
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                    "offset": {"type": "integer", "default": 0, "description": "Pagination offset"},
                },
            },
        ),
        Tool(
            name="get_eventsource",
            description="Get details about a specific EventSource",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "eventsource_id": {"type": "integer", "description": "EventSource ID"},
                },
                "required": ["eventsource_id"],
            },
        ),
        Tool(
            name="get_device_eventsources",
            description=(
                "Get EventSources applied to a device (resource)."
                " Returns device-level EventSource associations."
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "integer", "description": "Device ID"},
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                },
                "required": ["device_id"],
            },
        ),
        Tool(
            name="update_device_eventsource",
            description=(
                "Update a device-level EventSource association"
                " (requires write permission). Use to enable or disable"
                " alerting for an EventSource on a specific device."
            ),
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "integer", "description": "Device ID"},
                    "device_eventsource_id": {
                        "type": "integer",
                        "description": (
                            "Device-EventSource association ID (from get_device_eventsources)"
                        ),
                    },
                    "disable_alerting": {
                        "type": "boolean",
                        "description": "Set true to disable alerting, false to enable",
                    },
                },
                "required": ["device_id", "device_eventsource_id"],
            },
        ),
        Tool(
            name="get_propertysources",
            description="List PropertySources",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "name_filter": {"type": "string", "description": "Filter by name (substring)"},
                    "applies_to_filter": {
                        "type": "string",
                        "description": "Filter by appliesTo expression",
                    },
                    "filter": {
                        "type": "string",
                        "description": "Raw filter expression (overrides other filters). "
                        "Example: name~Linux,technology:script",
                    },
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                    "offset": {"type": "integer", "default": 0, "description": "Pagination offset"},
                },
            },
        ),
        Tool(
            name="get_propertysource",
            description="Get details about a specific PropertySource",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "propertysource_id": {"type": "integer", "description": "PropertySource ID"},
                },
                "required": ["propertysource_id"],
            },
        ),
        Tool(
            name="get_topologysources",
            description="List TopologySources",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "name_filter": {"type": "string", "description": "Filter by name (substring)"},
                    "applies_to_filter": {
                        "type": "string",
                        "description": "Filter by appliesTo expression",
                    },
                    "filter": {
                        "type": "string",
                        "description": "Raw filter expression (overrides other filters). "
                        "Example: name~Network,technology:snmp",
                    },
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                    "offset": {"type": "integer", "default": 0, "description": "Pagination offset"},
                },
            },
        ),
        Tool(
            name="get_topologysource",
            description="Get details about a specific TopologySource",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "topologysource_id": {"type": "integer", "description": "TopologySource ID"},
                },
                "required": ["topologysource_id"],
            },
        ),
        Tool(
            name="get_logsources",
            description="List LogSources",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "name_filter": {"type": "string", "description": "Filter by name (substring)"},
                    "applies_to_filter": {
                        "type": "string",
                        "description": "Filter by appliesTo expression",
                    },
                    "filter": {
                        "type": "string",
                        "description": "Raw filter expression (overrides other filters). "
                        "Example: name~syslog,logType:EventLog",
                    },
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                    "offset": {"type": "integer", "default": 0, "description": "Pagination offset"},
                },
            },
        ),
        Tool(
            name="get_logsource",
            description="Get details about a specific LogSource",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "logsource_id": {"type": "integer", "description": "LogSource ID"},
                },
                "required": ["logsource_id"],
            },
        ),
        Tool(
            name="get_device_logsources",
            description="Get LogSources applied to a device (resource)",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "integer", "description": "Device ID"},
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                },
                "required": ["device_id"],
            },
        ),
    ]
)

# Network Scans
TOOLS.extend(
    [
        Tool(
            name="get_netscans",
            description="List network scans",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                },
            },
        ),
        Tool(
            name="get_netscan",
            description="Get details about a specific network scan",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "netscan_id": {"type": "integer", "description": "Netscan ID"},
                },
                "required": ["netscan_id"],
            },
        ),
        Tool(
            name="run_netscan",
            description="Execute a network scan (requires write permission)",
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "netscan_id": {"type": "integer", "description": "Netscan ID to run"},
                },
                "required": ["netscan_id"],
            },
        ),
    ]
)

# OIDs
TOOLS.extend(
    [
        Tool(
            name="get_oids",
            description="List OID definitions",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "oid_filter": {"type": "string", "description": "Filter by OID (substring)"},
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                },
            },
        ),
        Tool(
            name="get_oid",
            description="Get details about a specific OID",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "oid_id": {"type": "integer", "description": "OID ID"},
                },
                "required": ["oid_id"],
            },
        ),
    ]
)

# Services
TOOLS.extend(
    [
        Tool(
            name="get_services",
            description=(
                "List Service Insight business services (deviceType 6 devices, "
                "including APM trace services)"
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "name_filter": {
                        "type": "string",
                        "description": "Filter by service name (substring match)",
                    },
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                },
            },
        ),
        Tool(
            name="get_service",
            description="Get details about a specific Service Insight service",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "service_id": {
                        "type": "integer",
                        "description": "Service device ID (deviceType 6)",
                    },
                },
                "required": ["service_id"],
            },
        ),
        Tool(
            name="get_service_groups",
            description="List Service Insight service groups (BizService device groups)",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "name_filter": {
                        "type": "string",
                        "description": "Filter by group name (substring match)",
                    },
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                },
            },
        ),
    ]
)

# Ops Notes
TOOLS.extend(
    [
        Tool(
            name="get_ops_notes",
            description="List ops notes",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                },
            },
        ),
        Tool(
            name="get_ops_note",
            description="Get details about a specific ops note",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "note_id": {"type": "integer", "description": "Ops note ID"},
                },
                "required": ["note_id"],
            },
        ),
        Tool(
            name="add_ops_note",
            description="Add an ops note (requires write permission)",
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "note": {"type": "string", "description": "Note text"},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags"},
                    "device_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Device IDs to scope the note to",
                    },
                    "group_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Device group IDs to scope the note to",
                    },
                },
                "required": ["note"],
            },
        ),
        Tool(
            name="update_ops_note",
            description="Update an ops note (requires write permission)",
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "note_id": {
                        "type": "string",
                        "pattern": _LM_STRING_ID_PATTERN,
                        "description": "Ops note ID to update",
                    },
                    "note": {"type": "string", "description": "New note text"},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "New tags (replaces existing)",
                    },
                    "device_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "New device IDs to scope the note to",
                    },
                    "group_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "New device group IDs to scope the note to",
                    },
                },
                "required": ["note_id"],
            },
        ),
        Tool(
            name="delete_ops_note",
            description="Delete an ops note (requires write permission)",
            annotations=_DELETE,
            inputSchema={
                "type": "object",
                "properties": {
                    "note_id": {
                        "type": "string",
                        "pattern": _LM_STRING_ID_PATTERN,
                        "description": "Ops note ID to delete",
                    },
                },
                "required": ["note_id"],
            },
        ),
    ]
)

# Audit Logs
TOOLS.extend(
    [
        Tool(
            name="get_audit_logs",
            description="Get audit logs from LogicMonitor",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "username": {"type": "string", "description": "Filter by username"},
                    "action": {"type": "string", "description": "Filter by action type"},
                    "resource_type": {
                        "type": "string",
                        "description": "Filter by resource type",
                    },
                    "start_time": {
                        "type": "integer",
                        "description": "Start time in epoch seconds (optional)",
                    },
                    "end_time": {
                        "type": "integer",
                        "description": "End time in epoch seconds (optional)",
                    },
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                    "offset": {"type": "integer", "default": 0, "description": "Pagination offset"},
                },
            },
        ),
        Tool(
            name="get_api_token_audit",
            description="Get API token usage audit logs",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "token_id": {
                        "type": "integer",
                        "description": "Filter by API token ID",
                    },
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                },
            },
        ),
        Tool(
            name="get_login_audit",
            description="Get login/authentication audit logs",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "username": {"type": "string", "description": "Filter by username"},
                    "success_only": {
                        "type": "boolean",
                        "default": False,
                        "description": "Only successful logins",
                    },
                    "failed_only": {
                        "type": "boolean",
                        "default": False,
                        "description": "Only failed logins",
                    },
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                },
            },
        ),
        Tool(
            name="get_change_audit",
            description="Get configuration change audit logs",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "resource_type": {"type": "string", "description": "Filter by resource type"},
                    "change_type": {"type": "string", "description": "Filter by change type"},
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                },
            },
        ),
    ]
)

# Topology
TOOLS.extend(
    [
        Tool(
            name="get_topology_map",
            description="Get network topology map data",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "device_group_id": {
                        "type": "integer",
                        "description": "Filter by device group ID",
                    },
                    "include_connections": {
                        "type": "boolean",
                        "default": True,
                        "description": "Include connection data",
                    },
                    "limit": {"type": "integer", "default": 100, "description": "Max results"},
                },
            },
        ),
        Tool(
            name="get_device_neighbors",
            description="Get neighboring devices/resources based on topology",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "integer", "description": "Device ID"},
                    "depth": {
                        "type": "integer",
                        "default": 1,
                        "description": "Depth of neighbor search",
                    },
                },
                "required": ["device_id"],
            },
        ),
        Tool(
            name="get_device_interfaces",
            description="Get network interfaces for a device (resource)",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "integer", "description": "Device ID"},
                },
                "required": ["device_id"],
            },
        ),
        Tool(
            name="get_network_flows",
            description="Get network flow data (NetFlow/sFlow)",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "integer", "description": "Device ID"},
                    "source_ip": {"type": "string", "description": "Filter by source IP"},
                    "dest_ip": {"type": "string", "description": "Filter by destination IP"},
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                },
            },
        ),
        Tool(
            name="get_device_connections",
            description="Get device/resource relationships and connections",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "integer", "description": "Device ID"},
                },
                "required": ["device_id"],
            },
        ),
    ]
)

# Batch Jobs
TOOLS.extend(
    [
        Tool(
            name="get_batchjobs",
            description="List batch jobs",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                },
            },
        ),
        Tool(
            name="get_batchjob",
            description="Get details about a specific batch job",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "batchjob_id": {"type": "integer", "description": "Batch job ID"},
                },
                "required": ["batchjob_id"],
            },
        ),
        Tool(
            name="get_device_batchjobs",
            description=(
                "List BatchJob datasources applied to a device (resource); per-run "
                "output lives in instance data via get_device_data"
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "integer", "description": "Device ID"},
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                },
                "required": ["device_id"],
            },
        ),
        Tool(
            name="get_scheduled_downtime_jobs",
            description="Get batch jobs related to SDT automation",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                },
            },
        ),
    ]
)

# Cost/Cloud
TOOLS.extend(
    [
        Tool(
            name="get_cost_recommendations",
            description=(
                "Get cost optimization recommendations. Category filter takes the "
                "category description string from get_cost_recommendation_categories"
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": (
                            'Category description string (e.g. "Idle AWS EC2 instances")'
                        ),
                    },
                    "status": {
                        "type": "string",
                        "description": "Filter by recommendation status (e.g. active)",
                    },
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                    "offset": {
                        "type": "integer",
                        "default": 0,
                        "description": "Results to skip for pagination",
                    },
                },
            },
        ),
        Tool(
            name="get_idle_resources",
            description=(
                "Get idle/underutilized cloud resources (resolved from idle-type "
                "cost recommendation categories)"
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "provider": {
                        "type": "string",
                        "description": "Narrow to one cloud provider (aws, azure, gcp)",
                    },
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                },
            },
        ),
        Tool(
            name="get_cost_recommendation_categories",
            description="Get cost recommendation categories with counts and savings",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="get_cost_recommendation",
            description="Get a specific cost recommendation by ID (v224 API)",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "recommendation_id": {
                        "type": "integer",
                        "description": "ID of the recommendation to retrieve",
                    },
                },
                "required": ["recommendation_id"],
            },
        ),
    ]
)

# OTLP Metrics (native OTLP ingest, PromQL query surface; feature-flag gated)
TOOLS.extend(
    [
        Tool(
            name="get_otlp_metric_names",
            description=(
                "[PREVIEW] List metric names ingested via native OpenTelemetry (OTLP). "
                "Requires the OTLP Metrics feature flag; returns a friendly notice "
                "when unavailable"
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "contains": {
                        "type": "string",
                        "description": "Substring filter on metric names (wildcards unsupported)",
                    },
                    "start": {
                        "type": "integer",
                        "description": "Window start, unix epoch seconds",
                    },
                    "end": {
                        "type": "integer",
                        "description": "Window end, unix epoch seconds",
                    },
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                },
            },
        ),
        Tool(
            name="get_otlp_metric_labels",
            description=(
                "[PREVIEW] List label names on native OTLP metrics, optionally "
                "narrowed to one metric"
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "metric": {
                        "type": "string",
                        "description": "Narrow to labels present on this metric name",
                    },
                    "label_name": {
                        "type": "string",
                        "description": "Substring filter on label names",
                    },
                    "start": {
                        "type": "integer",
                        "description": "Window start, unix epoch seconds",
                    },
                    "end": {
                        "type": "integer",
                        "description": "Window end, unix epoch seconds",
                    },
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                },
            },
        ),
        Tool(
            name="get_otlp_label_values",
            description=(
                "[PREVIEW] List values observed for one native OTLP metric label "
                "(e.g. all service_name values)"
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": (
                            "Label name to list values for, e.g. service_name; discover "
                            "names with get_otlp_metric_labels"
                        ),
                    },
                    "metric": {
                        "type": "string",
                        "description": "Narrow to values present on this metric name",
                    },
                    "start": {
                        "type": "integer",
                        "description": "Window start, unix epoch seconds",
                    },
                    "end": {
                        "type": "integer",
                        "description": "Window end, unix epoch seconds",
                    },
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                },
                "required": ["key"],
            },
        ),
        Tool(
            name="query_otlp_metrics",
            description=(
                "[PREVIEW] Run a PromQL range query against native OTLP metrics. "
                "Returns a time-series matrix"
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "PromQL expression. Examples: container_memory_usage_bytes "
                            "(raw series), avg(container_cpu_usage_seconds_total) "
                            "(aggregate), rate(container_network_receive_bytes_total[5m]) "
                            '(per-second rate), nginx_up{service_name="api"} (label '
                            "matcher). Discover names and labels with "
                            "get_otlp_metric_names / get_otlp_metric_labels"
                        ),
                    },
                    "start": {
                        "type": "integer",
                        "description": (
                            "Window start, unix epoch seconds. Keep windows under ~30 "
                            "days; very wide windows fail in the metrics backend"
                        ),
                    },
                    "end": {
                        "type": "integer",
                        "description": "Window end, unix epoch seconds",
                    },
                    "step": {
                        "type": "string",
                        "description": (
                            "Resolution step, e.g. '30s', '5m', '1h'; use larger steps "
                            "for wider windows"
                        ),
                    },
                },
                "required": ["query", "start", "end"],
            },
        ),
    ]
)

# Imports/Exports
TOOLS.extend(
    [
        Tool(
            name="export_datasource",
            description="Export a datasource definition (REST API format). "
            "Output can be used with create_datasource or update_datasource.",
            annotations=_EXPORT,
            inputSchema={
                "type": "object",
                "properties": {
                    "datasource_id": {"type": "integer", "description": "Datasource ID"},
                },
                "required": ["datasource_id"],
            },
        ),
        Tool(
            name="export_dashboard",
            description="Export a dashboard definition",
            annotations=_EXPORT,
            inputSchema={
                "type": "object",
                "properties": {
                    "dashboard_id": {"type": "integer", "description": "Dashboard ID"},
                },
                "required": ["dashboard_id"],
            },
        ),
        Tool(
            name="export_alert_rule",
            description="Export an alert rule definition",
            annotations=_EXPORT,
            inputSchema={
                "type": "object",
                "properties": {
                    "alert_rule_id": {"type": "integer", "description": "Alert rule ID"},
                },
                "required": ["alert_rule_id"],
            },
        ),
        Tool(
            name="export_escalation_chain",
            description="Export an escalation chain definition",
            annotations=_EXPORT,
            inputSchema={
                "type": "object",
                "properties": {
                    "escalation_chain_id": {
                        "type": "integer",
                        "description": "Escalation chain ID",
                    },
                },
                "required": ["escalation_chain_id"],
            },
        ),
        Tool(
            name="export_configsource",
            description="Export a ConfigSource definition (REST API format). "
            "Output can be used with create_configsource or update_configsource.",
            annotations=_EXPORT,
            inputSchema={
                "type": "object",
                "properties": {
                    "configsource_id": {"type": "integer", "description": "ConfigSource ID"},
                },
                "required": ["configsource_id"],
            },
        ),
        Tool(
            name="export_eventsource",
            description="Export an EventSource definition (REST API format). "
            "Output can be used with create_eventsource or update_eventsource.",
            annotations=_EXPORT,
            inputSchema={
                "type": "object",
                "properties": {
                    "eventsource_id": {"type": "integer", "description": "EventSource ID"},
                },
                "required": ["eventsource_id"],
            },
        ),
        Tool(
            name="export_propertysource",
            description="Export a PropertySource definition (REST API format). "
            "Output can be used with create_propertysource or update_propertysource.",
            annotations=_EXPORT,
            inputSchema={
                "type": "object",
                "properties": {
                    "propertysource_id": {"type": "integer", "description": "PropertySource ID"},
                },
                "required": ["propertysource_id"],
            },
        ),
        Tool(
            name="export_logsource",
            description="Export a LogSource definition (REST API format). "
            "Output can be used with create_logsource or update_logsource.",
            annotations=_EXPORT,
            inputSchema={
                "type": "object",
                "properties": {
                    "logsource_id": {"type": "integer", "description": "LogSource ID"},
                },
                "required": ["logsource_id"],
            },
        ),
        Tool(
            name="export_diagnosticsource",
            description="Export a DiagnosticSource definition (REST API format). "
            "Output can be used with create_diagnosticsource or update_diagnosticsource.",
            annotations=_EXPORT,
            inputSchema={
                "type": "object",
                "properties": {
                    "diagnosticsource_id": {
                        "type": "integer",
                        "description": "DiagnosticSource ID",
                    },
                },
                "required": ["diagnosticsource_id"],
            },
        ),
        Tool(
            name="export_remediationsource",
            description="Export a RemediationSource definition (REST API format). "
            "Output can be used with create_remediationsource or "
            "update_remediationsource.",
            annotations=_EXPORT,
            inputSchema={
                "type": "object",
                "properties": {
                    "remediationsource_id": {
                        "type": "integer",
                        "description": "RemediationSource ID",
                    },
                },
                "required": ["remediationsource_id"],
            },
        ),
        Tool(
            name="import_datasource",
            description="Import a DataSource from LM Exchange JSON format via "
            "multipart upload (requires write permission). This expects LM Exchange "
            "format, not REST API format. For REST API format definitions "
            "(e.g., from export_datasource), use create_datasource instead.",
            annotations=_IMPORT,
            inputSchema={
                "type": "object",
                "properties": {
                    "definition": {
                        "type": "object",
                        "description": "DataSource JSON definition in LM Exchange format",
                    },
                    "handle_conflict": {
                        "type": "string",
                        "description": "How to handle naming conflicts with existing modules",
                    },
                    "fields_to_preserve": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Fields to preserve from existing module when overwriting",
                    },
                },
                "required": ["definition"],
            },
        ),
        Tool(
            name="create_configsource",
            description="Create a ConfigSource via REST API from a full definition dict "
            "(requires write permission). Accepts REST API format (same as "
            "export_configsource output). For LM Exchange format, use import_configsource.",
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "definition": {
                        "type": "object",
                        "description": "Full ConfigSource definition in REST API format",
                    },
                    "overwrite": {
                        "type": "boolean",
                        "default": False,
                        "description": "If true, delete existing ConfigSource "
                        "with same name before creating",
                    },
                },
                "required": ["definition"],
            },
        ),
        Tool(
            name="update_configsource",
            description=(
                "RAW UPDATE -- full-replace semantics. Any field omitted from "
                "`definition` is BLANKED on the server. PREFER update_logicmodule"
                "(type='configsource', id, changes, mode='preview') for partial updates "
                "with diff preview. Requires confirm=true to proceed."
            ),
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "configsource_id": {
                        "type": "integer",
                        "description": "ConfigSource ID to update",
                    },
                    "definition": {
                        "type": "object",
                        "description": (
                            "FULL ConfigSource definition with all fields (will replace)"
                        ),
                    },
                    "confirm": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "Must be true to proceed. Defaults to false to prevent "
                            "accidental field-blanking. Use update_logicmodule for safe "
                            "partial updates."
                        ),
                    },
                },
                "required": ["configsource_id", "definition"],
            },
        ),
        Tool(
            name="delete_configsource",
            description="Delete a ConfigSource definition "
            "(requires write permission). Existing collected data is retained.",
            annotations=_DELETE,
            inputSchema={
                "type": "object",
                "properties": {
                    "configsource_id": {
                        "type": "integer",
                        "description": "ConfigSource ID to delete",
                    },
                },
                "required": ["configsource_id"],
            },
        ),
        Tool(
            name="create_eventsource",
            description="Create an EventSource via REST API from a full definition dict "
            "(requires write permission). Accepts REST API format (same as "
            "export_eventsource output). For LM Exchange format, use import_eventsource.",
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "definition": {
                        "type": "object",
                        "description": "Full EventSource definition in REST API format",
                    },
                    "overwrite": {
                        "type": "boolean",
                        "default": False,
                        "description": "If true, delete existing EventSource "
                        "with same name before creating",
                    },
                },
                "required": ["definition"],
            },
        ),
        Tool(
            name="update_eventsource",
            description=(
                "RAW UPDATE -- full-replace semantics. Any field omitted from "
                "`definition` is BLANKED on the server. PREFER update_logicmodule"
                "(type='eventsource', id, changes, mode='preview') for partial updates "
                "with diff preview. Requires confirm=true to proceed."
            ),
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "eventsource_id": {
                        "type": "integer",
                        "description": "EventSource ID to update",
                    },
                    "definition": {
                        "type": "object",
                        "description": "FULL EventSource definition with all fields (will replace)",
                    },
                    "confirm": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "Must be true to proceed. Defaults to false to prevent "
                            "accidental field-blanking. Use update_logicmodule for safe "
                            "partial updates."
                        ),
                    },
                },
                "required": ["eventsource_id", "definition"],
            },
        ),
        Tool(
            name="delete_eventsource",
            description="Delete an EventSource definition "
            "(requires write permission). Existing collected data is retained.",
            annotations=_DELETE,
            inputSchema={
                "type": "object",
                "properties": {
                    "eventsource_id": {
                        "type": "integer",
                        "description": "EventSource ID to delete",
                    },
                },
                "required": ["eventsource_id"],
            },
        ),
        Tool(
            name="import_configsource",
            description="Import a ConfigSource from LM Exchange JSON format via multipart "
            "upload (requires write permission). For REST API format definitions "
            "(e.g., from export_configsource), use create_configsource instead.",
            annotations=_IMPORT,
            inputSchema={
                "type": "object",
                "properties": {
                    "definition": {"type": "object", "description": "ConfigSource JSON definition"},
                    "handle_conflict": {
                        "type": "string",
                        "description": "How to handle naming conflicts with existing modules",
                    },
                    "fields_to_preserve": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Fields to preserve from existing module when overwriting",
                    },
                },
                "required": ["definition"],
            },
        ),
        Tool(
            name="import_eventsource",
            description="Import an EventSource from LM Exchange JSON format via multipart "
            "upload (requires write permission). For REST API format definitions "
            "(e.g., from export_eventsource), use create_eventsource instead.",
            annotations=_IMPORT,
            inputSchema={
                "type": "object",
                "properties": {
                    "definition": {"type": "object", "description": "EventSource JSON definition"},
                    "handle_conflict": {
                        "type": "string",
                        "description": "How to handle naming conflicts with existing modules",
                    },
                    "fields_to_preserve": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Fields to preserve from existing module when overwriting",
                    },
                },
                "required": ["definition"],
            },
        ),
        Tool(
            name="create_propertysource",
            description="Create a PropertySource via REST API from a full definition dict "
            "(requires write permission). Accepts REST API format (same as "
            "export_propertysource output). Use for round-tripping exports or building "
            "definitions from scratch. For LM Exchange format, use import_propertysource.",
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "definition": {
                        "type": "object",
                        "description": "Full PropertySource definition in REST API format",
                    },
                    "overwrite": {
                        "type": "boolean",
                        "default": False,
                        "description": "If true, delete existing PropertySource "
                        "with same name before creating",
                    },
                },
                "required": ["definition"],
            },
        ),
        Tool(
            name="update_propertysource",
            description=(
                "RAW UPDATE -- full-replace semantics. Any field omitted from "
                "`definition` is BLANKED on the server. PREFER update_logicmodule"
                "(type='propertysource', id, changes, mode='preview') for partial updates "
                "with diff preview. Requires confirm=true to proceed."
            ),
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "propertysource_id": {
                        "type": "integer",
                        "description": "PropertySource ID to update",
                    },
                    "definition": {
                        "type": "object",
                        "description": (
                            "FULL PropertySource definition with all fields (will replace)"
                        ),
                    },
                    "confirm": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "Must be true to proceed. Defaults to false to prevent "
                            "accidental field-blanking. Use update_logicmodule for safe "
                            "partial updates."
                        ),
                    },
                },
                "required": ["propertysource_id", "definition"],
            },
        ),
        Tool(
            name="delete_propertysource",
            description="Delete a PropertySource definition "
            "(requires write permission). Existing collected data is retained.",
            annotations=_DELETE,
            inputSchema={
                "type": "object",
                "properties": {
                    "propertysource_id": {
                        "type": "integer",
                        "description": "PropertySource ID to delete",
                    },
                },
                "required": ["propertysource_id"],
            },
        ),
        Tool(
            name="import_propertysource",
            description="Import a PropertySource from LM Exchange JSON format via multipart "
            "upload (requires write permission). For REST API format definitions "
            "(e.g., from export_propertysource), use create_propertysource instead.",
            annotations=_IMPORT,
            inputSchema={
                "type": "object",
                "properties": {
                    "definition": {"type": "object", "description": "PropertySource JSON"},
                    "handle_conflict": {
                        "type": "string",
                        "description": "How to handle naming conflicts with existing modules",
                    },
                    "fields_to_preserve": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Fields to preserve from existing module when overwriting",
                    },
                },
                "required": ["definition"],
            },
        ),
        Tool(
            name="create_logsource",
            description="Create a LogSource via REST API from a full definition dict "
            "(requires write permission). Accepts REST API format (same as "
            "export_logsource output). For LM Exchange format, use import_logsource.",
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "definition": {
                        "type": "object",
                        "description": "Full LogSource definition in REST API format",
                    },
                    "overwrite": {
                        "type": "boolean",
                        "default": False,
                        "description": "If true, delete existing LogSource "
                        "with same name before creating",
                    },
                },
                "required": ["definition"],
            },
        ),
        Tool(
            name="update_logsource",
            description=(
                "RAW UPDATE -- full-replace semantics. Any field omitted from "
                "`definition` is BLANKED on the server. PREFER update_logicmodule"
                "(type='logsource', id, changes, mode='preview') for partial updates "
                "with diff preview. Requires confirm=true to proceed."
            ),
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "logsource_id": {
                        "type": "integer",
                        "description": "LogSource ID to update",
                    },
                    "definition": {
                        "type": "object",
                        "description": "FULL LogSource definition with all fields (will replace)",
                    },
                    "confirm": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "Must be true to proceed. Defaults to false to prevent "
                            "accidental field-blanking. Use update_logicmodule for safe "
                            "partial updates."
                        ),
                    },
                },
                "required": ["logsource_id", "definition"],
            },
        ),
        Tool(
            name="delete_logsource",
            description="Delete a LogSource definition "
            "(requires write permission). Existing collected data is retained.",
            annotations=_DELETE,
            inputSchema={
                "type": "object",
                "properties": {
                    "logsource_id": {
                        "type": "integer",
                        "description": "LogSource ID to delete",
                    },
                },
                "required": ["logsource_id"],
            },
        ),
        Tool(
            name="import_logsource",
            description="Import a LogSource from LM Exchange JSON format via multipart "
            "upload (requires write permission). For REST API format definitions "
            "(e.g., from export_logsource), use create_logsource instead.",
            annotations=_IMPORT,
            inputSchema={
                "type": "object",
                "properties": {
                    "definition": {"type": "object", "description": "LogSource JSON definition"},
                    "handle_conflict": {
                        "type": "string",
                        "description": "How to handle naming conflicts with existing modules",
                    },
                    "fields_to_preserve": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Fields to preserve from existing module when overwriting",
                    },
                },
                "required": ["definition"],
            },
        ),
        Tool(
            name="create_topologysource",
            description="Create a TopologySource via REST API from a full definition dict "
            "(requires write permission). Accepts REST API format. "
            "For LM Exchange format, use import_topologysource.",
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "definition": {
                        "type": "object",
                        "description": "Full TopologySource definition in REST API format",
                    },
                    "overwrite": {
                        "type": "boolean",
                        "default": False,
                        "description": "If true, delete existing TopologySource "
                        "with same name before creating",
                    },
                },
                "required": ["definition"],
            },
        ),
        Tool(
            name="update_topologysource",
            description=(
                "RAW UPDATE -- full-replace semantics. Any field omitted from "
                "`definition` is BLANKED on the server. PREFER update_logicmodule"
                "(type='topologysource', id, changes, mode='preview') for partial updates "
                "with diff preview. Requires confirm=true to proceed."
            ),
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "topologysource_id": {
                        "type": "integer",
                        "description": "TopologySource ID to update",
                    },
                    "definition": {
                        "type": "object",
                        "description": (
                            "FULL TopologySource definition with all fields (will replace)"
                        ),
                    },
                    "confirm": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "Must be true to proceed. Defaults to false to prevent "
                            "accidental field-blanking. Use update_logicmodule for safe "
                            "partial updates."
                        ),
                    },
                },
                "required": ["topologysource_id", "definition"],
            },
        ),
        Tool(
            name="delete_topologysource",
            description="Delete a TopologySource definition "
            "(requires write permission). Existing collected data is retained.",
            annotations=_DELETE,
            inputSchema={
                "type": "object",
                "properties": {
                    "topologysource_id": {
                        "type": "integer",
                        "description": "TopologySource ID to delete",
                    },
                },
                "required": ["topologysource_id"],
            },
        ),
        Tool(
            name="import_topologysource",
            description="Import a TopologySource from LM Exchange JSON format via multipart "
            "upload (requires write permission). For REST API format definitions, "
            "use create_topologysource instead.",
            annotations=_IMPORT,
            inputSchema={
                "type": "object",
                "properties": {
                    "definition": {"type": "object", "description": "TopologySource JSON"},
                    "handle_conflict": {
                        "type": "string",
                        "description": "How to handle naming conflicts with existing modules",
                    },
                    "fields_to_preserve": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Fields to preserve from existing module when overwriting",
                    },
                },
                "required": ["definition"],
            },
        ),
        Tool(
            name="import_diagnosticsource",
            description="Import a DiagnosticSource from LM Exchange JSON format via "
            "multipart upload (requires write permission). For REST API format "
            "definitions (e.g., from export_diagnosticsource), use "
            "create_diagnosticsource instead.",
            annotations=_IMPORT,
            inputSchema={
                "type": "object",
                "properties": {
                    "definition": {
                        "type": "object",
                        "description": "DiagnosticSource JSON definition",
                    },
                    "handle_conflict": {
                        "type": "string",
                        "description": "How to handle naming conflicts with existing modules",
                    },
                    "fields_to_preserve": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Fields to preserve from existing module when overwriting",
                    },
                },
                "required": ["definition"],
            },
        ),
        Tool(
            name="import_jobmonitor",
            description="Import a JobMonitor from JSON (requires write permission)",
            annotations=_IMPORT,
            inputSchema={
                "type": "object",
                "properties": {
                    "definition": {"type": "object", "description": "JobMonitor JSON definition"},
                    "handle_conflict": {
                        "type": "string",
                        "description": "How to handle naming conflicts with existing modules",
                    },
                    "fields_to_preserve": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Fields to preserve from existing module when overwriting",
                    },
                },
                "required": ["definition"],
            },
        ),
        Tool(
            name="import_appliesto_function",
            description="Import an AppliesTo function from JSON (requires write permission)",
            annotations=_IMPORT,
            inputSchema={
                "type": "object",
                "properties": {
                    "definition": {"type": "object", "description": "AppliesTo function JSON"},
                    "handle_conflict": {
                        "type": "string",
                        "description": "How to handle naming conflicts with existing modules",
                    },
                    "fields_to_preserve": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Fields to preserve from existing module when overwriting",
                    },
                },
                "required": ["definition"],
            },
        ),
    ]
)

# Ingestion APIs (require LMv1 authentication)
TOOLS.extend(
    [
        Tool(
            name="ingest_logs",
            description="Ingest log entries into LogicMonitor (requires LMv1 auth)",
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "logs": {
                        "type": "array",
                        "description": "Array of log entries to ingest",
                        "items": {
                            "type": "object",
                            "properties": {
                                "message": {"type": "string", "description": "Log message"},
                                "_lm.resourceId": {
                                    "type": "object",
                                    "description": "Resource mapping (e.g., system.hostname)",
                                },
                                "timestamp": {
                                    "type": "integer",
                                    "description": "Epoch milliseconds (optional)",
                                },
                            },
                            "required": ["message"],
                        },
                    },
                },
                "required": ["logs"],
            },
        ),
        Tool(
            name="push_metrics",
            description="Push custom metrics into LogicMonitor (requires LMv1 auth)",
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "metrics": {
                        "type": "object",
                        "description": "Metric payload with resource mapping and datapoints",
                        "properties": {
                            "resourceIds": {
                                "type": "object",
                                "description": "Resource mapping (e.g., system.hostname)",
                            },
                            "dataSource": {
                                "type": "string",
                                "description": "Datasource name for metrics",
                            },
                            "dataSourceGroup": {
                                "type": "string",
                                "description": "Datasource group name (optional)",
                            },
                            "instances": {
                                "type": "array",
                                "description": "Instance data with datapoints",
                            },
                        },
                        "required": ["resourceIds", "dataSource"],
                    },
                },
                "required": ["metrics"],
            },
        ),
    ]
)

# Correlation and Analysis
TOOLS.extend(
    [
        Tool(
            name="correlate_alerts",
            description=(
                "Correlate alerts by device, datasource, and temporal proximity. "
                "Groups alerts into clusters to identify related issues."
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "hours_back": {
                        "type": "integer",
                        "default": 4,
                        "description": "Hours to look back (default: 4)",
                    },
                    "device": {
                        "type": "string",
                        "description": "Filter by device name (substring match)",
                    },
                    "group_id": {
                        "type": "integer",
                        "description": "Filter by device group ID",
                    },
                    "severity": {
                        "type": "string",
                        "description": "Filter by severity (critical, error, warning, info)",
                        "enum": ["critical", "error", "warning", "info"],
                    },
                    "limit": {
                        "type": "integer",
                        "default": 500,
                        "description": "Max alerts to fetch (default: 500)",
                    },
                },
            },
        ),
        Tool(
            name="get_alert_statistics",
            description=(
                "Aggregate alert counts by severity, device, datasource, and time bucket. "
                "Returns statistical summary over a time window."
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "hours_back": {
                        "type": "integer",
                        "default": 24,
                        "description": "Hours to look back (default: 24)",
                    },
                    "device": {
                        "type": "string",
                        "description": "Filter by device name (substring match)",
                    },
                    "group_id": {
                        "type": "integer",
                        "description": "Filter by device group ID",
                    },
                    "bucket_size_hours": {
                        "type": "integer",
                        "default": 1,
                        "description": "Size of each time bucket in hours (default: 1)",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 1000,
                        "description": "Max alerts to fetch (default: 1000)",
                    },
                },
            },
        ),
        Tool(
            name="get_metric_anomalies",
            description=(
                "Detect metric anomalies using z-score analysis. "
                "Identifies data points deviating significantly from the mean."
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "integer", "description": "Device ID"},
                    "device_datasource_id": {
                        "type": "integer",
                        "description": "Device-DataSource ID (from get_device_datasources)",
                    },
                    "instance_id": {"type": "integer", "description": "Instance ID"},
                    "datapoints": {
                        "type": "string",
                        "description": "Comma-separated datapoint names (optional, all if omitted)",
                    },
                    "hours_back": {
                        "type": "integer",
                        "default": 24,
                        "description": "Hours to look back (default: 24)",
                    },
                    "threshold": {
                        "type": "number",
                        "default": 2.0,
                        "description": "Z-score threshold for anomaly detection (default: 2.0)",
                    },
                    "method": {
                        "type": "string",
                        "enum": ["auto", "zscore", "iqr", "mad"],
                        "default": "auto",
                        "description": (
                            "Anomaly detection method (auto selects based on data distribution)"
                        ),
                    },
                },
                "required": ["device_id", "device_datasource_id", "instance_id"],
            },
        ),
    ]
)

# Baselines
TOOLS.extend(
    [
        Tool(
            name="save_baseline",
            description=(
                "Save a metric baseline from historical data. "
                "Computes mean, min, max, stddev per datapoint and stores "
                "as a session variable for later comparison."
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {
                        "type": "integer",
                        "description": "Device ID",
                    },
                    "device_datasource_id": {
                        "type": "integer",
                        "description": "Device-DataSource ID",
                    },
                    "instance_id": {
                        "type": "integer",
                        "description": "Instance ID",
                    },
                    "baseline_name": {
                        "type": "string",
                        "description": "Name for the stored baseline",
                    },
                    "datapoints": {
                        "type": "string",
                        "description": ("Comma-separated datapoint names (all if omitted)"),
                    },
                    "hours_back": {
                        "type": "integer",
                        "default": 24,
                        "description": "Hours of historical data to use",
                    },
                },
                "required": [
                    "device_id",
                    "device_datasource_id",
                    "instance_id",
                    "baseline_name",
                ],
            },
        ),
        Tool(
            name="compare_to_baseline",
            description=(
                "Compare current metrics against a stored baseline. "
                "Reports deviation percentage and status (normal, elevated, "
                "reduced, anomalous) per datapoint."
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "baseline_name": {
                        "type": "string",
                        "description": "Name of the stored baseline",
                    },
                    "device_id": {
                        "type": "integer",
                        "description": ("Override device ID (uses baseline if omitted)"),
                    },
                    "device_datasource_id": {
                        "type": "integer",
                        "description": ("Override device-datasource ID"),
                    },
                    "instance_id": {
                        "type": "integer",
                        "description": ("Override instance ID"),
                    },
                    "hours_back": {
                        "type": "integer",
                        "default": 1,
                        "description": "Hours of recent data to compare",
                    },
                },
                "required": ["baseline_name"],
            },
        ),
    ]
)

# ML/Statistical Analysis
TOOLS.extend(
    [
        Tool(
            name="forecast_metric",
            description=(
                "Forecast when a metric will breach a threshold using linear "
                "regression. Analyzes historical data to predict trend direction "
                "and estimated breach time."
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {
                        "type": "integer",
                        "description": "Device ID",
                    },
                    "device_datasource_id": {
                        "type": "integer",
                        "description": "Device-DataSource ID",
                    },
                    "instance_id": {
                        "type": "integer",
                        "description": "Instance ID",
                    },
                    "threshold": {
                        "type": "number",
                        "description": "Threshold value that constitutes a breach",
                    },
                    "datapoints": {
                        "type": "string",
                        "description": ("Comma-separated datapoint names (all if omitted)"),
                    },
                    "hours_back": {
                        "type": "integer",
                        "default": 168,
                        "description": "Hours of historical data for regression",
                    },
                    "method": {
                        "type": "string",
                        "enum": ["auto", "linear", "holt_winters", "ttm"],
                        "default": "auto",
                        "description": (
                            "Forecasting method. 'ttm' uses IBM Granite TTM via "
                            "watsonx.ai (requires WATSONX_API_KEY). 'auto' selects "
                            "based on data and watsonx availability."
                        ),
                    },
                },
                "required": [
                    "device_id",
                    "device_datasource_id",
                    "instance_id",
                    "threshold",
                ],
            },
        ),
        Tool(
            name="correlate_metrics",
            description=(
                "Compute Pearson correlation between multiple metric series. "
                "Builds an NxN correlation matrix and highlights strong "
                "correlations (|r| > 0.7). Maximum 10 sources."
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "sources": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "device_id": {"type": "integer"},
                                "device_datasource_id": {"type": "integer"},
                                "instance_id": {"type": "integer"},
                                "datapoint": {"type": "string"},
                            },
                            "required": [
                                "device_id",
                                "device_datasource_id",
                                "instance_id",
                                "datapoint",
                            ],
                        },
                        "description": "List of metric sources to correlate",
                    },
                    "hours_back": {
                        "type": "integer",
                        "default": 24,
                        "description": "Hours of data to analyze",
                    },
                },
                "required": ["sources"],
            },
        ),
        Tool(
            name="detect_change_points",
            description=(
                "Detect regime shifts in metric data using the CUSUM algorithm. "
                "Identifies points where the mean value changes significantly."
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {
                        "type": "integer",
                        "description": "Device ID",
                    },
                    "device_datasource_id": {
                        "type": "integer",
                        "description": "Device-DataSource ID",
                    },
                    "instance_id": {
                        "type": "integer",
                        "description": "Instance ID",
                    },
                    "datapoints": {
                        "type": "string",
                        "description": ("Comma-separated datapoint names (all if omitted)"),
                    },
                    "hours_back": {
                        "type": "integer",
                        "default": 24,
                        "description": "Hours of data to analyze",
                    },
                    "sensitivity": {
                        "type": "number",
                        "default": 1.0,
                        "description": ("Detection sensitivity (lower = more sensitive)"),
                    },
                },
                "required": [
                    "device_id",
                    "device_datasource_id",
                    "instance_id",
                ],
            },
        ),
        Tool(
            name="score_alert_noise",
            description=(
                "Score alert noise level using Shannon entropy and flap detection. "
                "Produces a score from 0 (quiet) to 100 (extremely noisy) with "
                "recommendations for tuning."
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "hours_back": {
                        "type": "integer",
                        "default": 24,
                        "description": "Hours to look back",
                    },
                    "device": {
                        "type": "string",
                        "description": "Optional device name filter",
                    },
                    "group_id": {
                        "type": "integer",
                        "description": "Optional device group ID filter",
                    },
                },
            },
        ),
        Tool(
            name="detect_seasonality",
            description=(
                "Detect periodic patterns in metric data using autocorrelation. "
                "Identifies dominant periods (1h, 4h, 12h, 24h, 168h) and "
                "peak activity hours."
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {
                        "type": "integer",
                        "description": "Device ID",
                    },
                    "device_datasource_id": {
                        "type": "integer",
                        "description": "Device-DataSource ID",
                    },
                    "instance_id": {
                        "type": "integer",
                        "description": "Instance ID",
                    },
                    "datapoints": {
                        "type": "string",
                        "description": ("Comma-separated datapoint names (all if omitted)"),
                    },
                    "hours_back": {
                        "type": "integer",
                        "default": 168,
                        "description": "Hours of data to analyze (default 1 week)",
                    },
                },
                "required": [
                    "device_id",
                    "device_datasource_id",
                    "instance_id",
                ],
            },
        ),
        Tool(
            name="calculate_availability",
            description=(
                "Calculate availability percentage from alert history. "
                "Computes SLA-style uptime metrics, MTTR, and per-device "
                "breakdown from cleared and active alerts."
                "\n\nCommon mistakes: hours_back defaults to 720 (30 days). "
                "Narrow scope with device_id/group_id for performance."
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {
                        "type": "integer",
                        "description": "Optional device ID filter",
                    },
                    "group_id": {
                        "type": "integer",
                        "description": (
                            "Optional device group ID filter; not with device_id or device_name"
                        ),
                    },
                    "hours_back": {
                        "type": "integer",
                        "default": 720,
                        "description": "Hours to look back (default 30 days)",
                    },
                    "severity_threshold": {
                        "type": "string",
                        "default": "error",
                        "description": (
                            "Minimum severity for downtime (critical, error, warning, info)"
                        ),
                    },
                },
            },
        ),
        Tool(
            name="analyze_blast_radius",
            description=(
                "Analyze the blast radius of a device failure using topology "
                "data. Traverses neighbors to identify downstream impact and "
                "scores overall blast radius (0-100)."
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {
                        "type": "integer",
                        "description": "Device ID to analyze",
                    },
                    "depth": {
                        "type": "integer",
                        "default": 2,
                        "description": "Max traversal depth (1-3)",
                    },
                },
                "required": ["device_id"],
            },
        ),
        Tool(
            name="correlate_changes",
            description=(
                "Cross-reference alert spikes with audit/change logs. "
                "Identifies changes that may have triggered alert increases "
                "using configurable correlation windows."
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "hours_back": {
                        "type": "integer",
                        "default": 24,
                        "description": "Hours to look back",
                    },
                    "correlation_window_minutes": {
                        "type": "integer",
                        "default": 30,
                        "description": ("Minutes after a change to look for alert spikes"),
                    },
                },
            },
        ),
        Tool(
            name="score_device_health",
            description=(
                "Score health of a specific device-datasource instance using "
                "z-score analysis. For full device health reports across all "
                "datasources, use the health_check composite tool instead."
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {
                        "type": "integer",
                        "description": "Device ID",
                    },
                    "device_datasource_id": {
                        "type": "integer",
                        "description": "Device-DataSource ID",
                    },
                    "instance_id": {
                        "type": "integer",
                        "description": "Instance ID",
                    },
                    "datapoints": {
                        "type": "string",
                        "description": ("Comma-separated datapoint names (all if omitted)"),
                    },
                    "hours_back": {
                        "type": "integer",
                        "default": 4,
                        "description": "Hours of historical data for baseline",
                    },
                    "weights": {
                        "type": "object",
                        "description": ("Optional dict of datapoint_name -> weight"),
                    },
                },
                "required": [
                    "device_id",
                    "device_datasource_id",
                    "instance_id",
                ],
            },
        ),
        Tool(
            name="calculate_error_budget",
            description=(
                "Calculate SLO error budget consumption and projected "
                "exhaustion date. Computes remaining budget, burn rate, "
                "and status (healthy/warning/critical/exhausted) based "
                "on actual availability vs target SLO."
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {
                        "type": "integer",
                        "description": "Filter to a specific device",
                    },
                    "group_id": {
                        "type": "integer",
                        "description": "Filter to a device group; not with device_id",
                    },
                    "target_slo": {
                        "type": "number",
                        "default": 99.9,
                        "description": "Target SLO percentage (default: 99.9)",
                    },
                    "period_days": {
                        "type": "integer",
                        "default": 30,
                        "description": "SLO measurement period in days (default: 30)",
                    },
                },
            },
        ),
        Tool(
            name="classify_trend",
            description=(
                "Classify metric trends as stable, increasing, decreasing, "
                "cyclic, or volatile. Uses linear regression slope, coefficient "
                "of variation, and autocorrelation."
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {
                        "type": "integer",
                        "description": "Device ID",
                    },
                    "device_datasource_id": {
                        "type": "integer",
                        "description": "Device-DataSource ID",
                    },
                    "instance_id": {
                        "type": "integer",
                        "description": "Instance ID",
                    },
                    "datapoints": {
                        "type": "string",
                        "description": ("Comma-separated datapoint names (all if omitted)"),
                    },
                    "hours_back": {
                        "type": "integer",
                        "default": 24,
                        "description": "Hours of data to analyze",
                    },
                },
                "required": [
                    "device_id",
                    "device_datasource_id",
                    "instance_id",
                ],
            },
        ),
    ]
)

# Session Management
TOOLS.extend(
    [
        Tool(
            name="get_session_context",
            description="Get current session context (last results, variables, history)",
            annotations=_SESSION_READ,
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="set_session_variable",
            description="Set a user-defined session variable for use across tool calls",
            annotations=_SESSION_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Variable name"},
                    "value": {
                        "description": "Variable value (string, number, boolean, array, or object)",
                    },
                },
                "required": ["name", "value"],
            },
        ),
        Tool(
            name="get_session_variable",
            description="Get a user-defined session variable",
            annotations=_SESSION_READ,
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Variable name to retrieve"},
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="delete_session_variable",
            description="Delete a user-defined session variable",
            annotations=_SESSION_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Variable name to delete"},
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="clear_session_context",
            description="Clear all session context (last results, variables, and history)",
            annotations=_SESSION_WRITE,
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="list_session_history",
            description="List recent tool call history",
            annotations=_SESSION_READ,
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "default": 10,
                        "description": "Maximum entries to return (max 50)",
                    },
                },
            },
        ),
    ]
)

# Traces / APM
TOOLS.extend(
    [
        Tool(
            name="get_trace_services",
            description=(
                "List APM trace services (deviceType:6). "
                "Entry point for discovering traced services."
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "namespace": {
                        "type": "string",
                        "description": "Filter by service name (substring match)",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 50,
                        "description": "Max results",
                    },
                },
            },
        ),
        Tool(
            name="get_trace_service",
            description="Get detailed information about a specific APM trace service",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "service_id": {
                        "type": "integer",
                        "description": "APM service device ID",
                    },
                },
                "required": ["service_id"],
            },
        ),
        Tool(
            name="get_trace_service_alerts",
            description="Get alerts for an APM trace service",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "service_id": {
                        "type": "integer",
                        "description": "APM service device ID",
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["critical", "error", "warning", "info"],
                        "description": "Filter by alert severity",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 50,
                        "description": "Max results",
                    },
                },
                "required": ["service_id"],
            },
        ),
        Tool(
            name="get_trace_service_datasources",
            description=(
                "List datasources applied to an APM service "
                "(e.g. LogicMonitor_APM_Services, _Operations)"
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "service_id": {
                        "type": "integer",
                        "description": "APM service device ID",
                    },
                    "name_filter": {
                        "type": "string",
                        "description": "Filter by datasource name (substring match)",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 50,
                        "description": "Max results",
                    },
                },
                "required": ["service_id"],
            },
        ),
        Tool(
            name="get_trace_operations",
            description="List operations (endpoints/routes) for an APM service datasource",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "service_id": {
                        "type": "integer",
                        "description": "APM service device ID",
                    },
                    "device_datasource_id": {
                        "type": "integer",
                        "description": "Device datasource ID (from get_trace_service_datasources)",
                    },
                    "name_filter": {
                        "type": "string",
                        "description": "Filter by operation name (substring match)",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 50,
                        "description": "Max results",
                    },
                },
                "required": ["service_id", "device_datasource_id"],
            },
        ),
        Tool(
            name="get_trace_service_metrics",
            description=(
                "Get APM service-level RED metrics (Duration, ErrorOperationCount, OperationCount)"
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "service_id": {
                        "type": "integer",
                        "description": "APM service device ID",
                    },
                    "device_datasource_id": {
                        "type": "integer",
                        "description": "Device datasource ID",
                    },
                    "instance_id": {
                        "type": "integer",
                        "description": "Instance ID",
                    },
                    "datapoints": {
                        "type": "string",
                        "description": "Comma-separated datapoint names (all if omitted)",
                    },
                    "start_time": {
                        "type": "integer",
                        "description": "Start time in epoch seconds",
                    },
                    "end_time": {
                        "type": "integer",
                        "description": "End time in epoch seconds",
                    },
                },
                "required": ["service_id", "device_datasource_id", "instance_id"],
            },
        ),
        Tool(
            name="get_trace_operation_metrics",
            description=(
                "Get per-operation RED metrics (Duration, ErrorOperationCount, OperationCount)"
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "service_id": {
                        "type": "integer",
                        "description": "APM service device ID",
                    },
                    "device_datasource_id": {
                        "type": "integer",
                        "description": "Device datasource ID",
                    },
                    "instance_id": {
                        "type": "integer",
                        "description": "Operation instance ID",
                    },
                    "datapoints": {
                        "type": "string",
                        "description": "Comma-separated datapoint names (all if omitted)",
                    },
                    "start_time": {
                        "type": "integer",
                        "description": "Start time in epoch seconds",
                    },
                    "end_time": {
                        "type": "integer",
                        "description": "End time in epoch seconds",
                    },
                },
                "required": ["service_id", "device_datasource_id", "instance_id"],
            },
        ),
        Tool(
            name="get_trace_service_properties",
            description=(
                "Get properties for an APM service (OTel attributes, namespace, metadata)"
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "service_id": {
                        "type": "integer",
                        "description": "APM service device ID",
                    },
                    "name_filter": {
                        "type": "string",
                        "description": "Filter by property name (substring match)",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 50,
                        "description": "Max results",
                    },
                },
                "required": ["service_id"],
            },
        ),
    ]
)

# Diagnostic Sources
TOOLS.extend(
    [
        Tool(
            name="get_diagnosticsources",
            description="List DiagnosticSources from LogicMonitor",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "name_filter": {
                        "type": "string",
                        "description": "Filter by source name (substring, server-side)",
                    },
                    "group_filter": {
                        "type": "string",
                        "description": "Filter by group (substring, server-side)",
                    },
                    "filter": {
                        "type": "string",
                        "description": (
                            "Raw LM filter expression (overrides typed filters). "
                            "Operators: : (eq), !: (neq), ~ (contains), !~ (not contains)."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum sources to return (default: 50)",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Results to skip for pagination (default: 0)",
                    },
                },
            },
        ),
        Tool(
            name="get_diagnosticsource",
            description="Get details about a specific DiagnosticSource including datapoints",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "source_id": {
                        "type": "integer",
                        "description": "DiagnosticSource ID",
                    },
                },
                "required": ["source_id"],
            },
        ),
        Tool(
            name="execute_diagnostic",
            description=(
                "Execute a DiagnosticSource script on a target device. Performs "
                "pre-execution checks (collector version, device status, script "
                "review) before triggering manual execution. Poll "
                "get_diagnostic_remediation_results for status and output. "
                "Requires write permission."
            ),
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "host_id": {
                        "type": "integer",
                        "description": "Target device/host ID",
                    },
                    "diagnostic_source_id": {
                        "type": "integer",
                        "description": "DiagnosticSource ID to execute",
                    },
                    "alert_id": {
                        "type": "string",
                        "description": "Optional alert ID to associate with execution",
                    },
                },
                "required": ["host_id", "diagnostic_source_id"],
            },
        ),
        Tool(
            name="create_diagnosticsource",
            description=(
                "Create a DiagnosticSource via REST API from a full definition dict "
                "(requires write permission). Accepts REST API format (same as "
                "export_diagnosticsource output). For LM Exchange format, use "
                "import_diagnosticsource."
            ),
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "definition": {
                        "type": "object",
                        "description": "Full DiagnosticSource definition in REST API format",
                    },
                    "overwrite": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "If true, delete existing DiagnosticSource with same name "
                            "before creating"
                        ),
                    },
                },
                "required": ["definition"],
            },
        ),
        Tool(
            name="update_diagnosticsource",
            description=(
                "RAW UPDATE -- full-replace semantics. Any field omitted from "
                "`definition` is BLANKED on the server, including the script. "
                "PREFER update_logicmodule(type='diagnosticsource', id, changes, "
                "mode='preview') for partial updates with diff preview. Requires "
                "confirm=true to proceed."
            ),
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "diagnosticsource_id": {
                        "type": "integer",
                        "description": "DiagnosticSource ID to update",
                    },
                    "definition": {
                        "type": "object",
                        "description": (
                            "FULL DiagnosticSource definition with all fields (will replace)"
                        ),
                    },
                    "confirm": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "Must be true to proceed. Defaults to false to prevent "
                            "accidental field-blanking. Use update_logicmodule for "
                            "safe partial updates."
                        ),
                    },
                },
                "required": ["diagnosticsource_id", "definition"],
            },
        ),
        Tool(
            name="delete_diagnosticsource",
            description=(
                "Delete a DiagnosticSource definition (requires write permission). "
                "Action chains referencing it lose that stage."
            ),
            annotations=_DELETE,
            inputSchema={
                "type": "object",
                "properties": {
                    "diagnosticsource_id": {
                        "type": "integer",
                        "description": "DiagnosticSource ID to delete",
                    },
                },
                "required": ["diagnosticsource_id"],
            },
        ),
    ]
)

# Remediation Sources
TOOLS.extend(
    [
        Tool(
            name="get_remediationsources",
            description="List RemediationSources from LogicMonitor",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "name_filter": {
                        "type": "string",
                        "description": "Filter by source name (substring, server-side)",
                    },
                    "group_filter": {
                        "type": "string",
                        "description": "Filter by group (substring, server-side)",
                    },
                    "filter": {
                        "type": "string",
                        "description": (
                            "Raw LM filter expression (overrides typed filters). "
                            "Operators: : (eq), !: (neq), ~ (contains), !~ (not contains)."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum sources to return (default: 50)",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Results to skip for pagination (default: 0)",
                    },
                },
            },
        ),
        Tool(
            name="get_remediationsource",
            description=(
                "Get details about a specific RemediationSource including the Groovy script"
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "source_id": {
                        "type": "integer",
                        "description": "RemediationSource ID",
                    },
                },
                "required": ["source_id"],
            },
        ),
        Tool(
            name="execute_remediation",
            description=(
                "Execute a RemediationSource script on a target device. "
                "Performs pre-execution checks (collector version, device status, "
                "script review) before triggering manual execution. "
                "Requires write permission."
            ),
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "host_id": {
                        "type": "integer",
                        "description": "Target device/host ID",
                    },
                    "remediation_source_id": {
                        "type": "integer",
                        "description": "Remediation source ID to execute",
                    },
                    "alert_id": {
                        "type": "string",
                        "description": "Optional alert ID to associate with execution",
                    },
                },
                "required": ["host_id", "remediation_source_id"],
            },
        ),
        Tool(
            name="create_remediationsource",
            description=(
                "Create a RemediationSource via REST API from a full definition dict "
                "(requires write permission). Accepts REST API format (same as "
                "export_remediationsource output). RemediationSources have no LM "
                "Exchange import endpoint."
            ),
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "definition": {
                        "type": "object",
                        "description": "Full RemediationSource definition in REST API format",
                    },
                    "overwrite": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "If true, delete existing RemediationSource with same name "
                            "before creating"
                        ),
                    },
                },
                "required": ["definition"],
            },
        ),
        Tool(
            name="update_remediationsource",
            description=(
                "RAW UPDATE -- full-replace semantics. Any field omitted from "
                "`definition` is BLANKED on the server, including the script. "
                "PREFER update_logicmodule(type='remediationsource', id, changes, "
                "mode='preview') for partial updates with diff preview. Requires "
                "confirm=true to proceed."
            ),
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "remediationsource_id": {
                        "type": "integer",
                        "description": "RemediationSource ID to update",
                    },
                    "definition": {
                        "type": "object",
                        "description": (
                            "FULL RemediationSource definition with all fields (will replace)"
                        ),
                    },
                    "confirm": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "Must be true to proceed. Defaults to false to prevent "
                            "accidental field-blanking. Use update_logicmodule for "
                            "safe partial updates."
                        ),
                    },
                },
                "required": ["remediationsource_id", "definition"],
            },
        ),
        Tool(
            name="delete_remediationsource",
            description=(
                "Delete a RemediationSource definition (requires write permission). "
                "Action chains referencing it lose that stage."
            ),
            annotations=_DELETE,
            inputSchema={
                "type": "object",
                "properties": {
                    "remediationsource_id": {
                        "type": "integer",
                        "description": "RemediationSource ID to delete",
                    },
                },
                "required": ["remediationsource_id"],
            },
        ),
    ]
)

# Automated Diagnostics & Remediation (ADR) composite endpoints
TOOLS.extend(
    [
        Tool(
            name="get_diagnostic_remediation_assignments",
            description=(
                "List the diagnostic and remediation sources assigned to a specific "
                "resource or alert (Automated Diagnostics & Remediation). Unlike "
                "get_diagnosticsources/get_remediationsources, this resolves which "
                "modules actually apply to the target."
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "resource_id": {
                        "type": "integer",
                        "description": "Device/resource ID (provide this or alert_id)",
                    },
                    "alert_id": {
                        "type": "string",
                        "description": "Alert ID (provide this or resource_id)",
                    },
                    "module_type": {
                        "type": "string",
                        "enum": ["diagnosticsource", "remediationsource"],
                        "description": "Restrict to one module type (both if omitted)",
                    },
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                },
            },
        ),
        Tool(
            name="get_diagnostic_remediation_results",
            description=(
                "Get structured execution results for diagnostic and remediation "
                "source runs: status, trigger type, executor, script output, and "
                "timing. Provide exactly one of alert_id or host_id. Time window "
                "params are epoch milliseconds; result timestamps are epoch seconds."
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "alert_id": {
                        "type": "string",
                        "description": "Alert ID (exactly one of alert_id/host_id)",
                    },
                    "host_id": {
                        "type": "integer",
                        "description": "Device/host ID (exactly one of alert_id/host_id)",
                    },
                    "module_type": {
                        "type": "string",
                        "enum": ["diagnostic", "remediation", "both"],
                        "default": "both",
                        "description": "Which module results to return",
                    },
                    "diagnostic_source_id": {
                        "type": "integer",
                        "description": "Filter to one DiagnosticSource by ID",
                    },
                    "diagnostic_source_name": {
                        "type": "string",
                        "description": "Filter to one DiagnosticSource by name",
                    },
                    "remediation_source_id": {
                        "type": "integer",
                        "description": "Filter to one RemediationSource by ID",
                    },
                    "remediation_source_name": {
                        "type": "string",
                        "description": "Filter to one RemediationSource by name",
                    },
                    "start_time_ms": {
                        "type": "integer",
                        "description": "Window start, epoch milliseconds",
                    },
                    "end_time_ms": {
                        "type": "integer",
                        "description": "Window end, epoch milliseconds",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 50,
                        "description": "Max results per page",
                    },
                    "offset": {"type": "integer", "default": 0, "description": "Page offset"},
                    "cursor": {
                        "type": "string",
                        "description": (
                            "Diagnostic-side cursor from a previous response "
                            '(not valid with module_type "both")'
                        ),
                    },
                    "remediation_cursor": {
                        "type": "string",
                        "description": (
                            "Remediation-side cursor from a previous response "
                            '(not valid with module_type "both")'
                        ),
                    },
                },
            },
        ),
    ]
)

# Action Chains (ADR automation)
TOOLS.extend(
    [
        Tool(
            name="get_action_chains",
            description=(
                "List action chains: ordered DiagnosticSource/RemediationSource "
                "stages that action rules trigger on alerts (Automated "
                "Diagnostics & Remediation)"
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "name_filter": {
                        "type": "string",
                        "description": "Filter by chain name (substring, client-side)",
                    },
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                    "offset": {
                        "type": "integer",
                        "default": 0,
                        "description": "Results to skip for pagination",
                    },
                },
            },
        ),
        Tool(
            name="get_action_chain",
            description="Get details about a specific action chain including its stages",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "chain_id": {"type": "integer", "description": "Action chain ID"},
                },
                "required": ["chain_id"],
            },
        ),
        Tool(
            name="create_action_chain",
            description=(
                "Create an action chain from ordered diagnostic/remediation stages "
                "(requires write permission). Each stage references a "
                "DiagnosticSource or RemediationSource by ID."
            ),
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Chain name"},
                    "stages": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {
                                    "type": "integer",
                                    "description": "DiagnosticSource/RemediationSource ID",
                                },
                                "type": {
                                    "type": "string",
                                    "enum": ["diagnosticSource", "remediationSource"],
                                },
                                "name": {
                                    "type": "string",
                                    "description": "Source name (optional)",
                                },
                            },
                            "required": ["id", "type"],
                        },
                        "description": "Ordered stage list",
                    },
                    "description": {"type": "string", "description": "Chain description"},
                },
                "required": ["name", "stages"],
            },
        ),
        Tool(
            name="update_action_chain",
            description=(
                "Update an action chain via PATCH; only provided fields are sent "
                "(requires write permission)"
            ),
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "chain_id": {"type": "integer", "description": "Action chain ID"},
                    "name": {"type": "string", "description": "New chain name"},
                    "stages": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "integer"},
                                "type": {
                                    "type": "string",
                                    "enum": ["diagnosticSource", "remediationSource"],
                                },
                                "name": {"type": "string"},
                            },
                            "required": ["id", "type"],
                        },
                        "description": "Replacement ordered stage list",
                    },
                    "description": {"type": "string", "description": "New description"},
                },
                "required": ["chain_id"],
            },
        ),
        Tool(
            name="delete_action_chain",
            description=(
                "Delete an action chain (requires write permission). Action rules "
                "referencing it stop triggering."
            ),
            annotations=_DELETE,
            inputSchema={
                "type": "object",
                "properties": {
                    "chain_id": {"type": "integer", "description": "Action chain ID"},
                },
                "required": ["chain_id"],
            },
        ),
        Tool(
            name="get_action_rules",
            description=(
                "List action rules: alert conditions (severity, device groups, "
                "datasource matchers) that trigger action chains"
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "name_filter": {
                        "type": "string",
                        "description": "Filter by rule name (substring, client-side)",
                    },
                    "limit": {"type": "integer", "default": 50, "description": "Max results"},
                    "offset": {
                        "type": "integer",
                        "default": 0,
                        "description": "Results to skip for pagination",
                    },
                },
            },
        ),
        Tool(
            name="get_action_rule",
            description="Get details about a specific action rule",
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "rule_id": {"type": "integer", "description": "Action rule ID"},
                },
                "required": ["rule_id"],
            },
        ),
        Tool(
            name="create_action_rule",
            description=(
                "Create an action rule binding an action chain to alert conditions "
                "(requires write permission)"
            ),
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Rule name"},
                    "level": {
                        "type": "string",
                        "description": "Alert severity to match (e.g. Error, Critical)",
                    },
                    "device_groups": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": 'Device group full paths (["*"] for all)',
                    },
                    "action_chain_id": {
                        "type": "integer",
                        "description": "Action chain to trigger",
                    },
                    "devices": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": 'Device display names (["*"] for all)',
                    },
                    "datasource": {"type": "string", "description": "Datasource name matcher"},
                    "instance": {"type": "string", "description": "Instance matcher"},
                    "datapoint": {"type": "string", "description": "Datapoint matcher"},
                    "resource_properties": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "value": {"type": "string"},
                            },
                            "required": ["name", "value"],
                        },
                        "description": "Property matchers",
                    },
                    "enabled": {
                        "type": "boolean",
                        "default": True,
                        "description": "Whether the rule starts enabled",
                    },
                },
                "required": ["name", "level", "device_groups", "action_chain_id"],
            },
        ),
        Tool(
            name="update_action_rule",
            description=(
                "Update an action rule via PATCH; only provided fields are sent "
                "(requires write permission)"
            ),
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "rule_id": {"type": "integer", "description": "Action rule ID"},
                    "name": {"type": "string", "description": "New rule name"},
                    "level": {
                        "type": "string",
                        "description": "Alert severity to match (e.g. Error, Critical)",
                    },
                    "device_groups": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Device group full paths",
                    },
                    "action_chain_id": {
                        "type": "integer",
                        "description": "Action chain to trigger",
                    },
                    "devices": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Device display names",
                    },
                    "datasource": {"type": "string", "description": "Datasource name matcher"},
                    "instance": {"type": "string", "description": "Instance matcher"},
                    "datapoint": {"type": "string", "description": "Datapoint matcher"},
                    "resource_properties": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "value": {"type": "string"},
                            },
                            "required": ["name", "value"],
                        },
                        "description": "Property matchers",
                    },
                    "enabled": {"type": "boolean", "description": "Enable/disable the rule"},
                },
                "required": ["rule_id"],
            },
        ),
        Tool(
            name="delete_action_rule",
            description="Delete an action rule (requires write permission)",
            annotations=_DELETE,
            inputSchema={
                "type": "object",
                "properties": {
                    "rule_id": {"type": "integer", "description": "Action rule ID"},
                },
                "required": ["rule_id"],
            },
        ),
        Tool(
            name="set_action_rule_status",
            description=(
                "Enable or disable an action rule without touching its matchers "
                "(requires write permission)"
            ),
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "rule_id": {"type": "integer", "description": "Action rule ID"},
                    "enabled": {
                        "type": "boolean",
                        "description": "True to enable, False to disable",
                    },
                },
                "required": ["rule_id", "enabled"],
            },
        ),
    ]
)

# Workflows — composite tools and discovery
TOOLS.extend(
    [
        Tool(
            name="triage",
            description=(
                "Composite triage: correlates alerts, clusters by device/time, "
                "scores noise, assesses blast radius, and checks recent changes. "
                "Returns a prioritized incident report."
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "severity": {
                        "type": "string",
                        "enum": ["critical", "error", "warning", "info"],
                        "description": "Filter alerts by severity",
                    },
                    "device": {"type": "string", "description": "Filter by device name"},
                    "group_id": {"type": "integer", "description": "Filter by device group ID"},
                    "hours_back": {
                        "type": "integer",
                        "default": 4,
                        "description": "Hours to look back (default: 4)",
                    },
                    "detail_level": {
                        "type": "string",
                        "enum": ["summary", "full"],
                        "default": "summary",
                        "description": "Output detail level (default: summary)",
                    },
                    "summarize": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "Append plain-English NL summary via IBM Granite "
                            "(requires WATSONX_API_KEY)"
                        ),
                    },
                },
            },
        ),
        Tool(
            name="health_check",
            description=(
                "Composite health check: resolves a device, scores health across "
                "datasources, detects anomalies, checks alerts, and calculates "
                "availability. Returns a single device health report."
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "integer", "description": "Device ID"},
                    "device_name": {
                        "type": "string",
                        "description": "Device display name (used if device_id not provided)",
                    },
                    "detail_level": {
                        "type": "string",
                        "enum": ["summary", "full"],
                        "default": "summary",
                        "description": "Output detail level (default: summary)",
                    },
                    "summarize": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "Append plain-English NL summary via IBM Granite "
                            "(requires WATSONX_API_KEY)"
                        ),
                    },
                },
            },
        ),
        Tool(
            name="capacity_plan",
            description=(
                "Composite capacity planning: forecasts metric breach dates, "
                "classifies trends, detects seasonality and change points. "
                "Returns per-datasource capacity projections."
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "integer", "description": "Device ID"},
                    "device_name": {
                        "type": "string",
                        "description": "Device display name (used if device_id not provided)",
                    },
                    "datasource": {
                        "type": "string",
                        "description": "Filter to a specific datasource name",
                    },
                    "hours_back": {
                        "type": "integer",
                        "default": 168,
                        "description": "Hours of historical data (default: 168 = 1 week)",
                    },
                    "detail_level": {
                        "type": "string",
                        "enum": ["summary", "full"],
                        "default": "summary",
                        "description": "Output detail level (default: summary)",
                    },
                    "summarize": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "Append plain-English NL summary via IBM Granite "
                            "(requires WATSONX_API_KEY)"
                        ),
                    },
                },
            },
        ),
        Tool(
            name="portal_overview",
            description=(
                "Composite portal overview: aggregates alert statistics, collector "
                "health, maintenance windows, noise scores, and dead devices into "
                "a shift-handoff report."
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "hours_back": {
                        "type": "integer",
                        "default": 4,
                        "description": "Hours to look back (default: 4)",
                    },
                    "detail_level": {
                        "type": "string",
                        "enum": ["summary", "full"],
                        "default": "summary",
                        "description": "Output detail level (default: summary)",
                    },
                    "summarize": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "Append plain-English NL summary via IBM Granite "
                            "(requires WATSONX_API_KEY)"
                        ),
                    },
                },
            },
        ),
        Tool(
            name="diagnose",
            description=(
                "Composite diagnosis: given an alert or device, gathers alert "
                "details, device context, correlated alerts, recent changes, "
                "blast radius, and health score. Returns a diagnosis report "
                "with probable root cause and recommendations."
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "alert_id": {
                        "type": "string",
                        "description": "Alert ID to diagnose",
                    },
                    "device_name": {
                        "type": "string",
                        "description": (
                            "Device name to diagnose (finds most recent critical alert)"
                        ),
                    },
                    "detail_level": {
                        "type": "string",
                        "enum": ["summary", "full"],
                        "default": "summary",
                        "description": "Output detail level (default: summary)",
                    },
                    "summarize": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "Append plain-English NL summary via IBM Granite "
                            "(requires WATSONX_API_KEY)"
                        ),
                    },
                },
            },
        ),
        Tool(
            name="search_tools",
            description=(
                "Search available MCP tools by keyword or category. "
                "Use this to discover which tools are available for a task."
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Search keywords (e.g., 'alert', 'device health', 'forecast')"
                        ),
                    },
                    "category": {
                        "type": "string",
                        "description": (
                            "Filter to a specific category (e.g., 'alerts', 'ml_analysis')"
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "default": 10,
                        "description": "Maximum results to return (default: 10)",
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="update_logicmodule",
            description=(
                "Safe partial update for LogicMonitor source types (configsource, "
                "datasource, eventsource, logsource, propertysource, topologysource). "
                "Exports the current full definition, deep-merges your `changes` onto it, "
                "validates required fields, and either returns a dry-run diff (mode='preview', "
                "default) or applies the merged definition (mode='apply'). PREFER this over "
                "the raw update_<type> tools for partial updates -- the raw tools are "
                "full-replace and will blank any field omitted from the payload (two prior "
                "production incidents)."
            ),
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": [
                            "configsource",
                            "datasource",
                            "diagnosticsource",
                            "eventsource",
                            "logsource",
                            "propertysource",
                            "remediationsource",
                            "topologysource",
                        ],
                        "description": "Source type to update",
                    },
                    "id": {"type": "integer", "description": "LogicModule ID"},
                    "changes": {
                        "type": "object",
                        "description": (
                            "Partial update -- only the fields to change. Use `null` as a "
                            "value to explicitly delete a key. Lists replace wholesale."
                        ),
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["preview", "apply"],
                        "default": "preview",
                        "description": (
                            "'preview' returns a dry-run diff without writing (default). "
                            "'apply' writes the merged definition via the underlying "
                            "update_<type> handler."
                        ),
                    },
                },
                "required": ["type", "id", "changes"],
            },
        ),
        Tool(
            name="get_reference",
            description=(
                "Get LogicMonitor reference content (schemas, enums, filter syntax, guides). "
                "Mirrors content from MCP Resources for clients without full Resource support "
                "(Copilot cloud agent, OpenAI Codex, Cline). Categories: schema, enums, "
                "filters, syntax, guide. Pass list=true (or omit both category and name) to "
                "discover all available (category, name) pairs."
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["schema", "enums", "filters", "syntax", "guide"],
                        "description": "Reference category",
                    },
                    "name": {
                        "type": "string",
                        "description": (
                            "Resource name within the category (e.g., 'alerts', 'operators')"
                        ),
                    },
                    "list": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "If true, return the available (category, name) pairs "
                            "instead of content"
                        ),
                    },
                },
            },
        ),
        Tool(
            name="get_workflow",
            description=(
                "Get LogicMonitor workflow guidance text (incident_triage, rca_workflow, "
                "remediate_workflow, etc.). Mirrors MCP Prompt content for clients without "
                "Prompt support. Prefer the composite workflow tools (triage, diagnose, "
                "health_check, capacity_plan, portal_overview) when they exist -- those "
                "execute the procedure. Pass list=true to discover available workflows."
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Workflow name (e.g., 'incident_triage')",
                    },
                    "list": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "If true, return the list of available workflows with their arguments"
                        ),
                    },
                    "arguments": {
                        "type": "object",
                        "description": (
                            "Optional template arguments passed to the workflow text builder"
                        ),
                    },
                },
            },
        ),
    ]
)

# Terraform HCL generator (always available, uses LM client)
TOOLS.extend(
    [
        Tool(
            name="terraform_generate",
            description=(
                "Export an existing LogicMonitor resource as Terraform HCL configuration "
                "using the logicmonitor/logicmonitor provider. Supports device, device_group, "
                "collector, alert_rule, escalation_chain, dashboard, datasource, sdt, website, "
                "role, and report_group resource types."
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "resource_type": {
                        "type": "string",
                        "description": (
                            "LM resource type to export (device, device_group, collector, "
                            "collector_group, alert_rule, escalation_chain, dashboard, "
                            "dashboard_group, datasource, sdt, website, website_group, "
                            "role, report_group)"
                        ),
                    },
                    "resource_id": {
                        "type": "integer",
                        "description": "LogicMonitor resource ID to export",
                    },
                },
                "required": ["resource_type", "resource_id"],
            },
        ),
    ]
)


# Network Intelligence (v3.8.0)
# Interface metrics, NetFlow aggregation, alert burst detection, link flaps,
# power events, enriched collector health, site-outage composite, and coverage audit.
TOOLS.extend(
    [
        Tool(
            name="get_interface_metrics",
            description=(
                "Pull interface-level metrics (in/out bytes, errors, discards, utilization, "
                "status) for a device's interface over a time window. Answers 'how is this "
                "port performing?' Resolves the Interface-family DataSource and the instance "
                "matching the interface name before fetching datapoints."
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "integer", "description": "Device ID"},
                    "interface": {
                        "type": "string",
                        "description": (
                            "Interface name or substring (case-insensitive), e.g. 'Gi0/1', 'eth0'"
                        ),
                    },
                    "metrics": {
                        "type": "string",
                        "description": (
                            "Comma-separated datapoint names. Defaults to RxRate, TxRate, "
                            "ErrorsIn, ErrorsOut, DiscardsIn, DiscardsOut, InterfaceStatus."
                        ),
                    },
                    "hours_back": {
                        "type": "integer",
                        "default": 1,
                        "description": "Hours of history to pull (default: 1)",
                    },
                },
                "required": ["device_id", "interface"],
            },
        ),
        Tool(
            name="get_top_talkers",
            description=(
                "Rank NetFlow flows on an exporter by bandwidth, packets, or flow count. "
                "Group by source IP, destination IP, protocol, application, or "
                "source->destination pair. Answers 'what is consuming my WAN?'"
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "exporter_device_id": {
                        "type": "integer",
                        "description": "NetFlow exporter device ID",
                    },
                    "hours_back": {
                        "type": "integer",
                        "default": 1,
                        "description": "Time window to aggregate (default: 1 hour)",
                    },
                    "n": {
                        "type": "integer",
                        "default": 10,
                        "description": "Number of top entries to return (default: 10)",
                    },
                    "group_by": {
                        "type": "string",
                        "enum": [
                            "src_ip",
                            "dst_ip",
                            "application",
                            "protocol",
                            "src_dst_pair",
                        ],
                        "default": "src_ip",
                        "description": "Aggregation dimension",
                    },
                    "min_bytes": {
                        "type": "integer",
                        "default": 0,
                        "description": "Drop aggregated entries below this byte threshold",
                    },
                },
                "required": ["exporter_device_id"],
            },
        ),
        Tool(
            name="detect_alert_burst",
            description=(
                "Sliding-window detector for mass alert events: N alerts from the same "
                "DataSource across M+ devices within T seconds. Answers 'did a bunch of "
                "stuff break at once?' Used for detecting cascading failures like mass "
                "interface-down events during a site outage."
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "group_id": {
                        "type": "integer",
                        "description": "Scope to a device group",
                    },
                    "device": {
                        "type": "string",
                        "description": "Scope to a device name (substring match)",
                    },
                    "datasource_pattern": {
                        "type": "string",
                        "description": ("Substring match on dataSourceName (case-insensitive)"),
                    },
                    "window_seconds": {
                        "type": "integer",
                        "default": 60,
                        "description": "Sliding window size in seconds",
                    },
                    "min_alerts": {
                        "type": "integer",
                        "default": 10,
                        "description": "Minimum alerts in the window to qualify as burst",
                    },
                    "min_devices": {
                        "type": "integer",
                        "default": 3,
                        "description": "Minimum distinct devices in the window",
                    },
                    "hours_back": {
                        "type": "integer",
                        "default": 1,
                        "description": "Lookback window in hours",
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["critical", "error", "warning", "info"],
                        "description": "Filter by severity",
                    },
                },
            },
        ),
        Tool(
            name="get_link_flaps",
            description=(
                "Identify interfaces with repeated up/down transitions in a time window. "
                "Answers 'which ports are unstable?' Common causes: bad cable, duplex "
                "mismatch, bad SFP, PoE power cycling, WAN instability."
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "group_id": {
                        "type": "integer",
                        "description": "Scope to a device group",
                    },
                    "device": {
                        "type": "string",
                        "description": "Scope to a device name (substring match)",
                    },
                    "hours_back": {
                        "type": "integer",
                        "default": 24,
                        "description": "Lookback window in hours (default: 24)",
                    },
                    "min_transitions": {
                        "type": "integer",
                        "default": 4,
                        "description": "Minimum alert fires to qualify as flapping",
                    },
                    "interface_pattern": {
                        "type": "string",
                        "default": "interface|interfaces|if-|port|ethernet",
                        "description": (
                            "Case-insensitive regex matching interface DataSource names"
                        ),
                    },
                },
            },
        ),
        Tool(
            name="get_collector_health",
            description=(
                "Enriched collector status with time-since-last-contact, downstream device "
                "count, dependent alert count, and optional CollectorDown history. Leading "
                "indicator for site-level events. Prefer this over `get_collectors` when "
                "investigating potential outages."
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "collector_id": {
                        "type": "integer",
                        "description": "Single collector ID. Other scope args are ignored if set.",
                    },
                    "collector_group_id": {
                        "type": "integer",
                        "description": "Restrict to collectors in this group",
                    },
                    "include_history": {
                        "type": "boolean",
                        "default": False,
                        "description": "Include CollectorDown alert history",
                    },
                    "history_days": {
                        "type": "integer",
                        "default": 7,
                        "description": "CollectorDown history lookback in days",
                    },
                },
            },
        ),
        Tool(
            name="get_power_events",
            description=(
                "Filter alerts for UPS/PDU power-event signatures across APC, Liebert, "
                "and Eaton DataSources ('on battery', 'runtime remaining', 'input voltage "
                "lost') over a time window. Returns events matched by DataSource or alert "
                "name substring with counts per pattern."
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "group_id": {
                        "type": "integer",
                        "description": "Scope to a device group",
                    },
                    "device": {
                        "type": "string",
                        "description": "Scope to a device name (substring match)",
                    },
                    "hours_back": {
                        "type": "integer",
                        "default": 2,
                        "description": "Lookback window in hours (default: 2)",
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["critical", "error", "warning", "info"],
                        "description": "Filter by severity",
                    },
                    "patterns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Override default patterns. Default covers UPS, PDU, APC, "
                            "Liebert, Eaton, Battery, PowerSupply, Power_."
                        ),
                    },
                },
            },
        ),
        Tool(
            name="detect_site_outage",
            description=(
                "Composite workflow for site outage detection. Chains CollectorDown "
                "detection, mass-interface-down burst analysis, UPS on-battery events, "
                "and downstream device silence into a single site-outage verdict with "
                "confidence score, scope, and affected device list. Designed to catch the "
                "class of site-outage that generic AIOps correlation misses. Pass a device "
                "group ID representing the site."
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "group_id": {
                        "type": "integer",
                        "description": (
                            "Device group ID representing the site. Devices in this group "
                            "define the analysis scope."
                        ),
                    },
                    "window_seconds": {
                        "type": "integer",
                        "default": 300,
                        "description": "Burst window size in seconds (default: 300)",
                    },
                    "hours_back": {
                        "type": "integer",
                        "default": 1,
                        "description": "Context window for power events in hours",
                    },
                    "detail_level": {
                        "type": "string",
                        "enum": ["summary", "full"],
                        "default": "summary",
                        "description": "Output detail level",
                    },
                },
                "required": ["group_id"],
            },
        ),
        Tool(
            name="audit_network_monitoring_coverage",
            description=(
                "Portal audit that counts UPS/PDU devices onboarded, interface "
                "DataSources applied, SNMP credentials configured, and NetFlow exporters "
                "set up. Returns a prioritized gap list with onboarding recommendations "
                "— turns 'you can't detect X' into 'here's how to enable detection of X.'"
            ),
            annotations=_READ_ONLY,
            inputSchema={
                "type": "object",
                "properties": {
                    "group_id": {
                        "type": "integer",
                        "description": ("Scope the audit to a device group. Omit for portal-wide."),
                    },
                },
            },
        ),
    ]
)


# Ansible Automation Platform tools (conditionally included)
AWX_TOOLS: list[Tool] = [
    # Connection test
    Tool(
        name="test_awx_connection",
        description="Test connectivity to Ansible Automation Platform controller",
        annotations=_READ_ONLY,
        inputSchema={"type": "object", "properties": {}},
    ),
    # Job template tools
    Tool(
        name="get_job_templates",
        description="List job templates from Ansible Automation Platform",
        annotations=_READ_ONLY,
        inputSchema={
            "type": "object",
            "properties": {
                "name_filter": {
                    "type": "string",
                    "description": "Search templates by name",
                },
                "project_id": {
                    "type": "integer",
                    "description": "Filter by project ID",
                },
                "limit": {
                    "type": "integer",
                    "default": 50,
                    "description": "Max results",
                },
            },
        },
    ),
    Tool(
        name="get_job_template",
        description="Get details of a specific job template",
        annotations=_READ_ONLY,
        inputSchema={
            "type": "object",
            "properties": {
                "template_id": {
                    "type": "integer",
                    "description": "The job template ID",
                },
            },
            "required": ["template_id"],
        },
    ),
    # Job execution tools
    Tool(
        name="launch_job",
        description=("Launch an Ansible job template. Requires write permission."),
        annotations=_WRITE,
        inputSchema={
            "type": "object",
            "properties": {
                "template_id": {
                    "type": "integer",
                    "description": "The job template ID to launch",
                },
                "extra_vars": {
                    "type": "object",
                    "description": "Extra variables for the playbook",
                },
                "inventory_id": {
                    "type": "integer",
                    "description": "Override inventory for this run",
                },
                "limit": {
                    "type": "string",
                    "description": "Limit execution to specific hosts (Ansible limit pattern)",
                },
                "check_mode": {
                    "type": "boolean",
                    "default": False,
                    "description": "Run in check/dry-run mode",
                },
            },
            "required": ["template_id"],
        },
    ),
    Tool(
        name="get_job_status",
        description="Get the status of a running or completed job",
        annotations=_READ_ONLY,
        inputSchema={
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "integer",
                    "description": "The job ID to check",
                },
            },
            "required": ["job_id"],
        },
    ),
    Tool(
        name="get_job_output",
        description="Get the stdout output of a job",
        annotations=_READ_ONLY,
        inputSchema={
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "integer",
                    "description": "The job ID to get output from",
                },
            },
            "required": ["job_id"],
        },
    ),
    Tool(
        name="cancel_job",
        description="Cancel a running job. Requires write permission.",
        annotations=_DELETE,
        inputSchema={
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "integer",
                    "description": "The job ID to cancel",
                },
            },
            "required": ["job_id"],
        },
    ),
    Tool(
        name="relaunch_job",
        description="Relaunch a previously run job. Requires write permission.",
        annotations=_WRITE,
        inputSchema={
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "integer",
                    "description": "The original job ID to relaunch",
                },
                "extra_vars": {
                    "type": "object",
                    "description": "Optional override variables",
                },
            },
            "required": ["job_id"],
        },
    ),
    # Inventory tools
    Tool(
        name="get_inventories",
        description="List inventories from Ansible Automation Platform",
        annotations=_READ_ONLY,
        inputSchema={
            "type": "object",
            "properties": {
                "name_filter": {
                    "type": "string",
                    "description": "Search inventories by name",
                },
                "limit": {
                    "type": "integer",
                    "default": 50,
                    "description": "Max results",
                },
            },
        },
    ),
    Tool(
        name="get_inventory_hosts",
        description="List hosts in a specific inventory",
        annotations=_READ_ONLY,
        inputSchema={
            "type": "object",
            "properties": {
                "inventory_id": {
                    "type": "integer",
                    "description": "The inventory ID",
                },
                "limit": {
                    "type": "integer",
                    "default": 50,
                    "description": "Max results",
                },
            },
            "required": ["inventory_id"],
        },
    ),
    # Workflow tools
    Tool(
        name="launch_workflow",
        description=("Launch a workflow job template. Requires write permission."),
        annotations=_WRITE,
        inputSchema={
            "type": "object",
            "properties": {
                "template_id": {
                    "type": "integer",
                    "description": "The workflow template ID to launch",
                },
                "extra_vars": {
                    "type": "object",
                    "description": "Extra variables for the workflow",
                },
                "inventory_id": {
                    "type": "integer",
                    "description": "Override inventory for this run",
                },
                "limit": {
                    "type": "string",
                    "description": "Limit execution to specific hosts",
                },
            },
            "required": ["template_id"],
        },
    ),
    Tool(
        name="get_workflow_status",
        description="Get the status of a workflow job",
        annotations=_READ_ONLY,
        inputSchema={
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "integer",
                    "description": "The workflow job ID",
                },
            },
            "required": ["job_id"],
        },
    ),
    Tool(
        name="get_workflow_templates",
        description="List workflow job templates from Ansible Automation Platform",
        annotations=_READ_ONLY,
        inputSchema={
            "type": "object",
            "properties": {
                "name_filter": {
                    "type": "string",
                    "description": "Search workflow templates by name",
                },
                "limit": {
                    "type": "integer",
                    "default": 50,
                    "description": "Max results",
                },
            },
        },
    ),
    # Admin tools
    Tool(
        name="get_projects",
        description="List projects from Ansible Automation Platform",
        annotations=_READ_ONLY,
        inputSchema={
            "type": "object",
            "properties": {
                "name_filter": {
                    "type": "string",
                    "description": "Search projects by name",
                },
                "limit": {
                    "type": "integer",
                    "default": 50,
                    "description": "Max results",
                },
            },
        },
    ),
    Tool(
        name="get_credentials",
        description="List credentials from Ansible Automation Platform (secrets not exposed)",
        annotations=_READ_ONLY,
        inputSchema={
            "type": "object",
            "properties": {
                "name_filter": {
                    "type": "string",
                    "description": "Search credentials by name",
                },
                "credential_type": {
                    "type": "integer",
                    "description": "Filter by credential type ID",
                },
                "limit": {
                    "type": "integer",
                    "default": 50,
                    "description": "Max results",
                },
            },
        },
    ),
    Tool(
        name="get_organizations",
        description="List organizations from Ansible Automation Platform",
        annotations=_READ_ONLY,
        inputSchema={
            "type": "object",
            "properties": {
                "name_filter": {
                    "type": "string",
                    "description": "Search organizations by name",
                },
                "limit": {
                    "type": "integer",
                    "default": 50,
                    "description": "Max results",
                },
            },
        },
    ),
    Tool(
        name="get_job_events",
        description="Get events from a specific job run",
        annotations=_READ_ONLY,
        inputSchema={
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "integer",
                    "description": "The job ID to get events from",
                },
                "limit": {
                    "type": "integer",
                    "default": 50,
                    "description": "Max results",
                },
            },
            "required": ["job_id"],
        },
    ),
    Tool(
        name="get_hosts",
        description="List hosts from Ansible Automation Platform",
        annotations=_READ_ONLY,
        inputSchema={
            "type": "object",
            "properties": {
                "name_filter": {
                    "type": "string",
                    "description": "Search hosts by name",
                },
                "inventory_id": {
                    "type": "integer",
                    "description": "Filter by inventory ID",
                },
                "limit": {
                    "type": "integer",
                    "default": 50,
                    "description": "Max results",
                },
            },
        },
    ),
]


# IBM watsonx.ai tools — only registered when WATSONX_API_KEY is configured
WATSONX_TOOLS: list[Tool] = [
    Tool(
        name="watsonx_summarize",
        description=(
            "Generate a plain-English summary of structured data using IBM "
            "Granite LLM via watsonx.ai. Takes JSON output from any tool and "
            "produces a concise, shift-handoff-ready analysis summary."
        ),
        annotations=_READ_ONLY,
        inputSchema={
            "type": "object",
            "properties": {
                "data": {
                    "type": "string",
                    "description": "JSON string of structured data to summarize",
                },
                "context": {
                    "type": "string",
                    "default": "",
                    "description": "Context hint (e.g., 'triage report', 'capacity plan')",
                },
                "max_tokens": {
                    "type": "integer",
                    "default": 500,
                    "description": "Maximum tokens in the generated summary",
                },
            },
            "required": ["data"],
        },
    ),
]


# Terraform IaC tools (visible only when TF_WORKSPACE_DIR is set)
TF_TOOLS: list[Tool] = [
    Tool(
        name="terraform_init",
        description=(
            "Initialize a Terraform workspace and download required providers. "
            "Run this before plan, apply, or any other terraform operation. "
            "Requires LM_ENABLE_WRITE_OPERATIONS=true."
        ),
        annotations=_WRITE,
        inputSchema={
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Workspace name (subdirectory of TF_WORKSPACE_DIR)",
                },
                "backend_config": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": (
                        "Optional partial backend configuration as key/value pairs, "
                        'e.g. {"bucket": "state", "key": "prod.tfstate", '
                        '"region": "us-east-1"}. Keys of the local, s3 and azurerm '
                        "backends only; endpoint and proxy overrides are refused, and a "
                        "local path must stay inside the workspace."
                    ),
                },
            },
            "required": ["workspace"],
        },
    ),
    Tool(
        name="terraform_validate",
        description=(
            "Validate Terraform configuration syntax in a workspace. "
            "Returns validation diagnostics as structured JSON."
        ),
        annotations=_READ_ONLY,
        inputSchema={
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Workspace name",
                },
            },
            "required": ["workspace"],
        },
    ),
    Tool(
        name="terraform_plan",
        description=(
            "Preview Terraform changes without applying. Shows what resources "
            "will be created, modified, or destroyed. Returns structured JSON plan. "
            "Requires LM_ENABLE_WRITE_OPERATIONS=true, since providers and data "
            "sources run against live APIs."
        ),
        annotations=_WRITE,
        inputSchema={
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Workspace name",
                },
                "var": {
                    "type": "string",
                    "description": "Variable assignment (key=value)",
                },
                "var_file": {
                    "type": "string",
                    "description": "Path to a .tfvars file inside the workspace (relative to it)",
                },
                "target": {
                    "type": "string",
                    "description": "Target a specific resource address",
                },
            },
            "required": ["workspace"],
        },
    ),
    Tool(
        name="terraform_state_list",
        description=("List all resources currently tracked in Terraform state for a workspace."),
        annotations=_READ_ONLY,
        inputSchema={
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Workspace name",
                },
            },
            "required": ["workspace"],
        },
    ),
    Tool(
        name="terraform_state_show",
        description=(
            "Show detailed Terraform state for a specific resource, "
            "including all attributes and metadata."
        ),
        annotations=_READ_ONLY,
        inputSchema={
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Workspace name",
                },
                "address": {
                    "type": "string",
                    "description": "Resource address (e.g., logicmonitor_device.web01)",
                },
            },
            "required": ["workspace", "address"],
        },
    ),
    Tool(
        name="terraform_output",
        description=("Show Terraform output values defined in the configuration."),
        annotations=_READ_ONLY,
        inputSchema={
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Workspace name",
                },
            },
            "required": ["workspace"],
        },
    ),
    Tool(
        name="terraform_apply",
        description=(
            "Apply Terraform configuration changes. Creates, updates, or destroys "
            "infrastructure as defined in the configuration. Triple-gated: requires "
            "LM_ENABLE_WRITE_OPERATIONS=true, TF_AUTO_APPROVE_ENABLED=true, and "
            "confirm=true parameter."
        ),
        annotations=_WRITE,
        inputSchema={
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Workspace name",
                },
                "var": {
                    "type": "string",
                    "description": "Variable assignment (key=value)",
                },
                "var_file": {
                    "type": "string",
                    "description": "Path to a .tfvars file inside the workspace (relative to it)",
                },
                "target": {
                    "type": "string",
                    "description": "Target a specific resource address",
                },
                "confirm": {
                    "type": "boolean",
                    "default": False,
                    "description": "Must be true to proceed. Safety gate for apply operations.",
                },
            },
            "required": ["workspace"],
        },
    ),
    Tool(
        name="terraform_destroy",
        description=(
            "Destroy all Terraform-managed infrastructure in a workspace. "
            "Triple-gated: requires LM_ENABLE_WRITE_OPERATIONS=true, "
            "TF_AUTO_APPROVE_ENABLED=true, and confirm=true parameter."
        ),
        annotations=_DELETE,
        inputSchema={
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Workspace name",
                },
                "target": {
                    "type": "string",
                    "description": "Target a specific resource address to destroy",
                },
                "confirm": {
                    "type": "boolean",
                    "default": False,
                    "description": "Must be true to proceed. Safety gate for destroy operations.",
                },
            },
            "required": ["workspace"],
        },
    ),
    Tool(
        name="terraform_import",
        description=(
            "Import an existing resource into Terraform state. Maps a real-world "
            "resource (by ID) to a Terraform resource address for state tracking."
        ),
        annotations=_WRITE,
        inputSchema={
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Workspace name",
                },
                "address": {
                    "type": "string",
                    "description": "Terraform resource address (e.g., logicmonitor_device.web01)",
                },
                "resource_id": {
                    "type": "string",
                    "description": "Real-world resource ID to import",
                },
            },
            "required": ["workspace", "address", "resource_id"],
        },
    ),
    Tool(
        name="terraform_write_config",
        description=(
            "Write HCL configuration content to a file in a Terraform workspace. "
            "Use this to create or update .tf files that define infrastructure."
        ),
        annotations=_WRITE,
        inputSchema={
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Workspace name",
                },
                "filename": {
                    "type": "string",
                    "description": "Filename (must end with .tf or .tf.json)",
                },
                "content": {
                    "type": "string",
                    "description": "HCL or JSON content to write to the file",
                },
            },
            "required": ["workspace", "filename", "content"],
        },
    ),
]


# Map tool names to their handler functions
# Multi-portal switching
TOOLS.extend(
    [
        Tool(
            name="list_portals",
            description="List the customer portals available in this multi-portal server.",
            annotations=_SESSION_READ,
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="use_portal",
            description="Switch the active customer portal for subsequent tool calls.",
            annotations=_SESSION_WRITE,
            inputSchema={
                "type": "object",
                "properties": {
                    "customer": {"type": "string", "description": "Portal key from list_portals"}
                },
                "required": ["customer"],
            },
        ),
        Tool(
            name="current_portal",
            description="Show which customer portal is currently active.",
            annotations=_SESSION_READ,
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="reload_portals",
            description=(
                "Re-read the vault so portals added or removed since startup take "
                "effect without restarting the client."
            ),
            annotations=_SESSION_WRITE,
            inputSchema={"type": "object", "properties": {}},
        ),
    ]
)


def get_tool_handler(tool_name: str) -> Any:
    """Get the handler function for a tool.

    Args:
        tool_name: Name of the tool.

    Returns:
        The async handler function for the tool.

    Raises:
        ValueError: If tool not found.
    """
    from lm_mcp.tools import (
        access_groups,
        actions,
        alert_rules,
        alerts,
        ansible,
        api_tokens,
        audit,
        baselines,
        batchjobs,
        collectors,
        configsources,
        correlation,
        cost,
        dashboard_groups,
        dashboards,
        datasources,
        devices,
        diagnostic_remediation,
        diagnosticsources,
        escalations,
        event_correlation,
        eventsources,
        forecasting,
        imports,
        ingestion,
        integrations,
        logsources,
        metrics,
        netscans,
        networking,
        oids,
        ops,
        otlp_metrics,
        propertysources,
        reference,
        remediationsources,
        reports,
        resources,
        scoring,
        sdts,
        services,
        session,
        terraform,
        topology,
        topology_analysis,
        topologysources,
        traces,
        users,
        watsonx,
        websites,
        workflows,
    )
    from lm_mcp.tools import (
        portals as portal_tools,
    )

    handlers = {
        # Multi-portal
        "list_portals": portal_tools.list_portals,
        "use_portal": portal_tools.use_portal,
        "current_portal": portal_tools.current_portal,
        "reload_portals": portal_tools.reload_portals,
        # Devices
        "get_devices": devices.get_devices,
        "get_device": devices.get_device,
        "get_device_groups": devices.get_device_groups,
        "get_device_group": devices.get_device_group,
        "create_device": devices.create_device,
        "update_device": devices.update_device,
        "delete_device": devices.delete_device,
        "recover_device": devices.recover_device,
        "bulk_delete_devices": devices.bulk_delete_devices,
        "create_device_group": devices.create_device_group,
        "update_device_group": devices.update_device_group,
        "delete_device_group": devices.delete_device_group,
        # Alerts
        "get_alerts": alerts.get_alerts,
        "get_alert_details": alerts.get_alert_details,
        "acknowledge_alert": alerts.acknowledge_alert,
        "add_alert_note": alerts.add_alert_note,
        "bulk_acknowledge_alerts": alerts.bulk_acknowledge_alerts,
        # SDTs
        "list_sdts": sdts.list_sdts,
        "create_sdt": sdts.create_sdt,
        "delete_sdt": sdts.delete_sdt,
        "update_sdt": sdts.update_sdt,
        "bulk_create_device_sdt": sdts.bulk_create_device_sdt,
        "bulk_delete_sdt": sdts.bulk_delete_sdt,
        "get_active_sdts": sdts.get_active_sdts,
        "get_upcoming_sdts": sdts.get_upcoming_sdts,
        # Collectors
        "get_collectors": collectors.get_collectors,
        "get_collector": collectors.get_collector,
        "get_collector_groups": collectors.get_collector_groups,
        "get_collector_group": collectors.get_collector_group,
        "update_collector": collectors.update_collector,
        "delete_collector": collectors.delete_collector,
        "create_collector_group": collectors.create_collector_group,
        "update_collector_group": collectors.update_collector_group,
        "delete_collector_group": collectors.delete_collector_group,
        "get_collector_health": collectors.get_collector_health,
        # Network Intelligence (v3.8.0)
        "get_interface_metrics": networking.get_interface_metrics,
        "get_top_talkers": networking.get_top_talkers,
        "detect_alert_burst": networking.detect_alert_burst,
        "get_link_flaps": networking.get_link_flaps,
        "get_power_events": networking.get_power_events,
        # Metrics
        "get_device_datasources": metrics.get_device_datasources,
        "get_device_instances": metrics.get_device_instances,
        "add_device_instance": metrics.add_device_instance,
        "update_device_instance": metrics.update_device_instance,
        "delete_device_instance": metrics.delete_device_instance,
        "get_device_data": metrics.get_device_data,
        "get_graph_data": metrics.get_graph_data,
        # Dashboards
        "get_dashboards": dashboards.get_dashboards,
        "get_dashboard": dashboards.get_dashboard,
        "get_dashboard_widgets": dashboards.get_dashboard_widgets,
        "get_widget": dashboards.get_widget,
        "create_dashboard": dashboards.create_dashboard,
        "update_dashboard": dashboards.update_dashboard,
        "delete_dashboard": dashboards.delete_dashboard,
        "add_widget": dashboards.add_widget,
        "update_widget": dashboards.update_widget,
        "delete_widget": dashboards.delete_widget,
        # Dashboard Groups
        "get_dashboard_groups": dashboard_groups.get_dashboard_groups,
        "get_dashboard_group": dashboard_groups.get_dashboard_group,
        "create_dashboard_group": dashboard_groups.create_dashboard_group,
        "delete_dashboard_group": dashboard_groups.delete_dashboard_group,
        "update_dashboard_group": dashboard_groups.update_dashboard_group,
        # Websites
        "get_websites": websites.get_websites,
        "get_website": websites.get_website,
        "get_website_groups": websites.get_website_groups,
        "get_website_data": websites.get_website_data,
        "create_website": websites.create_website,
        "update_website": websites.update_website,
        "delete_website": websites.delete_website,
        "create_website_group": websites.create_website_group,
        "delete_website_group": websites.delete_website_group,
        # Reports
        "get_reports": reports.get_reports,
        "get_report": reports.get_report,
        "get_report_groups": reports.get_report_groups,
        "get_scheduled_reports": reports.get_scheduled_reports,
        "run_report": reports.run_report,
        "get_report_execution": reports.get_report_execution,
        "create_report": reports.create_report,
        "update_report_schedule": reports.update_report_schedule,
        "delete_report": reports.delete_report,
        # Escalation Chains
        "get_escalation_chains": escalations.get_escalation_chains,
        "get_escalation_chain": escalations.get_escalation_chain,
        "get_recipient_groups": escalations.get_recipient_groups,
        "get_recipient_group": escalations.get_recipient_group,
        "create_escalation_chain": escalations.create_escalation_chain,
        "update_escalation_chain": escalations.update_escalation_chain,
        "delete_escalation_chain": escalations.delete_escalation_chain,
        "create_recipient_group": escalations.create_recipient_group,
        "update_recipient_group": escalations.update_recipient_group,
        "delete_recipient_group": escalations.delete_recipient_group,
        # Integrations
        "get_integrations": integrations.get_integrations,
        "get_integration": integrations.get_integration,
        "create_http_integration": integrations.create_http_integration,
        "update_http_integration": integrations.update_http_integration,
        "delete_integration": integrations.delete_integration,
        # Alert Rules
        "get_alert_rules": alert_rules.get_alert_rules,
        "get_alert_rule": alert_rules.get_alert_rule,
        "create_alert_rule": alert_rules.create_alert_rule,
        "update_alert_rule": alert_rules.update_alert_rule,
        "delete_alert_rule": alert_rules.delete_alert_rule,
        # Diagnostic Sources
        "get_diagnosticsources": diagnosticsources.get_diagnosticsources,
        "get_diagnosticsource": diagnosticsources.get_diagnosticsource,
        "execute_diagnostic": diagnosticsources.execute_diagnostic,
        "create_diagnosticsource": diagnosticsources.create_diagnosticsource,
        "update_diagnosticsource": diagnosticsources.update_diagnosticsource,
        "delete_diagnosticsource": diagnosticsources.delete_diagnosticsource,
        # Remediation Sources
        "get_remediationsources": remediationsources.get_remediationsources,
        "get_remediationsource": remediationsources.get_remediationsource,
        "execute_remediation": remediationsources.execute_remediation,
        "create_remediationsource": remediationsources.create_remediationsource,
        "update_remediationsource": remediationsources.update_remediationsource,
        "delete_remediationsource": remediationsources.delete_remediationsource,
        "get_diagnostic_remediation_assignments": (
            diagnostic_remediation.get_diagnostic_remediation_assignments
        ),
        "get_diagnostic_remediation_results": (
            diagnostic_remediation.get_diagnostic_remediation_results
        ),
        "get_action_chains": actions.get_action_chains,
        "get_action_chain": actions.get_action_chain,
        "create_action_chain": actions.create_action_chain,
        "update_action_chain": actions.update_action_chain,
        "delete_action_chain": actions.delete_action_chain,
        "get_action_rules": actions.get_action_rules,
        "get_action_rule": actions.get_action_rule,
        "create_action_rule": actions.create_action_rule,
        "update_action_rule": actions.update_action_rule,
        "delete_action_rule": actions.delete_action_rule,
        "set_action_rule_status": actions.set_action_rule_status,
        # Users
        "get_users": users.get_users,
        "get_user": users.get_user,
        "get_roles": users.get_roles,
        "get_role": users.get_role,
        "create_user": users.create_user,
        "update_user": users.update_user,
        "delete_user": users.delete_user,
        # Access Groups
        "get_access_groups": access_groups.get_access_groups,
        "get_access_group": access_groups.get_access_group,
        # API Tokens
        "get_api_tokens": api_tokens.get_api_tokens,
        "get_api_token": api_tokens.get_api_token,
        # Resources
        "get_device_properties": resources.get_device_properties,
        "get_device_property": resources.get_device_property,
        "update_device_property": resources.update_device_property,
        # Datasources
        "get_datasources": datasources.get_datasources,
        "get_datasource": datasources.get_datasource,
        "create_datasource": datasources.create_datasource,
        "update_datasource": datasources.update_datasource,
        "delete_datasource": datasources.delete_datasource,
        # ConfigSources
        "get_configsources": configsources.get_configsources,
        "get_configsource": configsources.get_configsource,
        "create_configsource": configsources.create_configsource,
        "update_configsource": configsources.update_configsource,
        "delete_configsource": configsources.delete_configsource,
        "get_configsource_update_reasons": configsources.get_configsource_update_reasons,
        "get_device_config": configsources.get_device_config,
        "get_device_config_version": configsources.get_device_config_version,
        "collect_device_config": configsources.collect_device_config,
        # EventSources
        "get_eventsources": eventsources.get_eventsources,
        "get_eventsource": eventsources.get_eventsource,
        "create_eventsource": eventsources.create_eventsource,
        "update_eventsource": eventsources.update_eventsource,
        "delete_eventsource": eventsources.delete_eventsource,
        "get_device_eventsources": eventsources.get_device_eventsources,
        "update_device_eventsource": eventsources.update_device_eventsource,
        # PropertySources
        "get_propertysources": propertysources.get_propertysources,
        "get_propertysource": propertysources.get_propertysource,
        "create_propertysource": propertysources.create_propertysource,
        "update_propertysource": propertysources.update_propertysource,
        "delete_propertysource": propertysources.delete_propertysource,
        # TopologySources
        "get_topologysources": topologysources.get_topologysources,
        "get_topologysource": topologysources.get_topologysource,
        "create_topologysource": topologysources.create_topologysource,
        "update_topologysource": topologysources.update_topologysource,
        "delete_topologysource": topologysources.delete_topologysource,
        # LogSources
        "get_logsources": logsources.get_logsources,
        "get_logsource": logsources.get_logsource,
        "create_logsource": logsources.create_logsource,
        "update_logsource": logsources.update_logsource,
        "delete_logsource": logsources.delete_logsource,
        "get_device_logsources": logsources.get_device_logsources,
        # Netscans
        "get_netscans": netscans.get_netscans,
        "get_netscan": netscans.get_netscan,
        "run_netscan": netscans.run_netscan,
        # OIDs
        "get_oids": oids.get_oids,
        "get_oid": oids.get_oid,
        # Services
        "get_services": services.get_services,
        "get_service": services.get_service,
        "get_service_groups": services.get_service_groups,
        # Ops Notes
        "get_ops_notes": ops.get_ops_notes,
        "get_ops_note": ops.get_ops_note,
        "add_ops_note": ops.add_ops_note,
        "update_ops_note": ops.update_ops_note,
        "delete_ops_note": ops.delete_ops_note,
        # Audit logs are owned by the audit module.
        "get_audit_logs": audit.get_audit_logs,
        "get_api_token_audit": audit.get_api_token_audit,
        "get_login_audit": audit.get_login_audit,
        "get_change_audit": audit.get_change_audit,
        # Topology
        "get_topology_map": topology.get_topology_map,
        "get_device_neighbors": topology.get_device_neighbors,
        "get_device_interfaces": topology.get_device_interfaces,
        "get_network_flows": topology.get_network_flows,
        "get_device_connections": topology.get_device_connections,
        # Batch Jobs
        "get_batchjobs": batchjobs.get_batchjobs,
        "get_batchjob": batchjobs.get_batchjob,
        "get_device_batchjobs": batchjobs.get_device_batchjobs,
        "get_scheduled_downtime_jobs": batchjobs.get_scheduled_downtime_jobs,
        # Cost
        "get_cost_recommendations": cost.get_cost_recommendations,
        "get_idle_resources": cost.get_idle_resources,
        "get_cost_recommendation_categories": cost.get_cost_recommendation_categories,
        "get_cost_recommendation": cost.get_cost_recommendation,
        # OTLP Metrics
        "get_otlp_metric_names": otlp_metrics.get_otlp_metric_names,
        "get_otlp_metric_labels": otlp_metrics.get_otlp_metric_labels,
        "get_otlp_label_values": otlp_metrics.get_otlp_label_values,
        "query_otlp_metrics": otlp_metrics.query_otlp_metrics,
        # Imports/Exports
        "export_datasource": imports.export_datasource,
        "export_dashboard": imports.export_dashboard,
        "export_alert_rule": imports.export_alert_rule,
        "export_escalation_chain": imports.export_escalation_chain,
        "export_configsource": imports.export_configsource,
        "export_eventsource": imports.export_eventsource,
        "export_propertysource": imports.export_propertysource,
        "export_logsource": imports.export_logsource,
        "export_diagnosticsource": imports.export_diagnosticsource,
        "export_remediationsource": imports.export_remediationsource,
        "import_datasource": imports.import_datasource,
        "import_configsource": imports.import_configsource,
        "import_eventsource": imports.import_eventsource,
        "import_propertysource": imports.import_propertysource,
        "import_logsource": imports.import_logsource,
        "import_topologysource": imports.import_topologysource,
        "import_diagnosticsource": imports.import_diagnosticsource,
        "import_jobmonitor": imports.import_jobmonitor,
        "import_appliesto_function": imports.import_appliesto_function,
        # Ingestion
        "ingest_logs": ingestion.ingest_logs,
        "push_metrics": ingestion.push_metrics,
        # Correlation and Analysis
        "correlate_alerts": correlation.correlate_alerts,
        "get_alert_statistics": correlation.get_alert_statistics,
        "get_metric_anomalies": correlation.get_metric_anomalies,
        # Baselines
        "save_baseline": baselines.save_baseline,
        "compare_to_baseline": baselines.compare_to_baseline,
        # ML/Statistical Analysis
        "forecast_metric": forecasting.forecast_metric,
        "correlate_metrics": correlation.correlate_metrics,
        "detect_change_points": forecasting.detect_change_points,
        "score_alert_noise": scoring.score_alert_noise,
        "detect_seasonality": forecasting.detect_seasonality,
        "classify_trend": forecasting.classify_trend,
        "calculate_availability": scoring.calculate_availability,
        "analyze_blast_radius": topology_analysis.analyze_blast_radius,
        "correlate_changes": event_correlation.correlate_changes,
        "score_device_health": scoring.score_device_health,
        "calculate_error_budget": scoring.calculate_error_budget,
        # Traces / APM
        "get_trace_services": traces.get_trace_services,
        "get_trace_service": traces.get_trace_service,
        "get_trace_service_alerts": traces.get_trace_service_alerts,
        "get_trace_service_datasources": traces.get_trace_service_datasources,
        "get_trace_operations": traces.get_trace_operations,
        "get_trace_service_metrics": traces.get_trace_service_metrics,
        "get_trace_operation_metrics": traces.get_trace_operation_metrics,
        "get_trace_service_properties": traces.get_trace_service_properties,
        # Session
        "get_session_context": session.get_session_context,
        "set_session_variable": session.set_session_variable,
        "get_session_variable": session.get_session_variable,
        "delete_session_variable": session.delete_session_variable,
        "clear_session_context": session.clear_session_context,
        "list_session_history": session.list_session_history,
        # Ansible Automation Platform
        "test_awx_connection": ansible.test_awx_connection,
        "get_job_templates": ansible.get_job_templates,
        "get_job_template": ansible.get_job_template,
        "launch_job": ansible.launch_job,
        "get_job_status": ansible.get_job_status,
        "get_job_output": ansible.get_job_output,
        "cancel_job": ansible.cancel_job,
        "relaunch_job": ansible.relaunch_job,
        "get_inventories": ansible.get_inventories,
        "get_inventory_hosts": ansible.get_inventory_hosts,
        "launch_workflow": ansible.launch_workflow,
        "get_workflow_status": ansible.get_workflow_status,
        "get_workflow_templates": ansible.get_workflow_templates,
        "get_projects": ansible.get_projects,
        "get_credentials": ansible.get_credentials,
        "get_organizations": ansible.get_organizations,
        "get_job_events": ansible.get_job_events,
        "get_hosts": ansible.get_hosts,
        # Workflows
        "triage": workflows.triage,
        "health_check": workflows.health_check,
        "capacity_plan": workflows.capacity_plan,
        "portal_overview": workflows.portal_overview,
        "diagnose": workflows.diagnose,
        "search_tools": workflows.search_tools,
        "update_logicmodule": workflows.update_logicmodule,
        "detect_site_outage": workflows.detect_site_outage,
        "audit_network_monitoring_coverage": workflows.audit_network_monitoring_coverage,
        # Universal reference layer (Resource/Prompt mirrors for non-Claude clients)
        "get_reference": reference.get_reference,
        "get_workflow": reference.get_workflow,
        # IBM watsonx.ai
        "watsonx_summarize": watsonx.watsonx_summarize,
        # Terraform IaC
        "terraform_init": terraform.terraform_init,
        "terraform_validate": terraform.terraform_validate,
        "terraform_plan": terraform.terraform_plan,
        "terraform_state_list": terraform.terraform_state_list,
        "terraform_state_show": terraform.terraform_state_show,
        "terraform_output": terraform.terraform_output,
        "terraform_apply": terraform.terraform_apply,
        "terraform_destroy": terraform.terraform_destroy,
        "terraform_import": terraform.terraform_import_resource,
        "terraform_write_config": terraform.terraform_write_config,
        "terraform_generate": terraform.terraform_generate,
    }

    if tool_name not in handlers:
        raise ValueError(f"Unknown tool: {tool_name}")

    return handlers[tool_name]
