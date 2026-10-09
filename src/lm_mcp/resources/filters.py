# Description: Filter field definitions and syntax documentation.
# Description: Provides filter operators and field references for LogicMonitor API queries.

from __future__ import annotations

# Filter operators supported by LogicMonitor API
FILTER_OPERATORS = {
    "name": "operators",
    "description": "LogicMonitor API filter operators and their usage",
    "operators": {
        ":": {
            "name": "equals",
            "description": "Exact match comparison",
            "examples": ["severity:4", 'hostStatus:"normal"', "cleared:false"],
            "supports_types": ["string", "integer", "boolean"],
        },
        "!:": {
            "name": "not_equals",
            "description": "Not equal comparison",
            "examples": ['hostStatus!:"normal"', "severity!:1"],
            "supports_types": ["string", "integer", "boolean"],
        },
        "~": {
            "name": "contains",
            "description": "Substring match (case-insensitive). No wildcards needed — "
            "the ~ operator automatically matches any substring.",
            "examples": ["displayName~prod", "monitorObjectName~server"],
            "supports_types": ["string"],
        },
        "!~": {
            "name": "not_contains",
            "description": "Does not contain substring",
            "examples": ["displayName!~test", "name!~backup"],
            "supports_types": ["string"],
        },
        ">": {
            "name": "greater_than",
            "description": "Greater than (exclusive)",
            "examples": ["severity>2", "startEpoch>1704067200000"],
            "supports_types": ["integer"],
        },
        "<": {
            "name": "less_than",
            "description": "Less than (exclusive)",
            "examples": ["severity<4", "endEpoch<1704153600000"],
            "supports_types": ["integer"],
        },
        ">:": {
            "name": "greater_or_equal",
            "description": "Greater than or equal to",
            "examples": ["severity>:2", "createdOn>:1704067200"],
            "supports_types": ["integer"],
        },
        "<:": {
            "name": "less_or_equal",
            "description": "Less than or equal to",
            "examples": ["severity<:3", "updatedOn<:1704153600"],
            "supports_types": ["integer"],
        },
    },
    "combining_filters": {
        "description": "Multiple filters are combined with comma (AND logic)",
        "examples": [
            "severity:4,cleared:false (critical AND active)",
            'hostStatus:"normal",displayName~"prod" (normal AND name contains prod)',
            "startEpoch>:1704067200000,severity>:3 (recent AND error+critical)",
        ],
    },
}

# Alert-specific filter fields
ALERT_FILTERS = {
    "name": "alerts",
    "description": "Filter fields available for alert queries",
    "api_endpoint": "/alert/alerts",
    "fields": {
        "severity": {
            "type": "integer",
            "description": "Alert severity (1=info, 2=warning, 3=error, 4=critical)",
            "operators": [":", "!:", ">", "<", ">:", "<:"],
            "examples": ["severity:4", "severity>:3"],
        },
        "cleared": {
            "type": "boolean",
            "description": "Whether alert is cleared",
            "operators": [":"],
            "examples": ["cleared:false", "cleared:true"],
        },
        "acked": {
            "type": "boolean",
            "description": "Whether alert is acknowledged",
            "operators": [":"],
            "examples": ["acked:false", "acked:true"],
        },
        "sdted": {
            "type": "boolean",
            "description": "Whether resource is in SDT",
            "operators": [":"],
            "examples": ["sdted:false"],
        },
        "startEpoch": {
            "type": "integer",
            "description": "Alert start time (epoch ms)",
            "operators": [">", "<", ">:", "<:"],
            "examples": ["startEpoch>:1704067200000"],
        },
        "endEpoch": {
            "type": "integer",
            "description": "Alert end time (epoch ms)",
            "operators": [">", "<", ">:", "<:"],
            "examples": ["endEpoch<:1704153600000"],
        },
        "monitorObjectName": {
            "type": "string",
            "description": "Device display name",
            "operators": [":", "~", "!:", "!~"],
            "examples": ["monitorObjectName~server-01"],
        },
        "dataPointName": {
            "type": "string",
            "description": "Datapoint name",
            "operators": [":", "~"],
            "examples": ["dataPointName~CPU"],
        },
        "instanceName": {
            "type": "string",
            "description": "Instance name",
            "operators": [":", "~"],
            "examples": ["instanceName~eth0"],
        },
        "resourceTemplateName": {
            "type": "string",
            "description": "DataSource name",
            "operators": [":", "~"],
            "examples": ["resourceTemplateName~WinCPU"],
        },
        "rule": {
            "type": "string",
            "description": "Alert rule name",
            "operators": [":", "~"],
            "examples": ["rule~Critical"],
        },
        "ackedBy": {
            "type": "string",
            "description": "User who acknowledged",
            "operators": [":", "~"],
            "examples": ["ackedBy~admin"],
        },
        "hostGroupIds": {
            "type": "string",
            "description": "Device group IDs (comma-separated internally). "
            "Use ~ operator to match devices belonging to a group.",
            "operators": ["~"],
            "examples": ["hostGroupIds~1234"],
        },
        "monitorObjectId": {
            "type": "integer",
            "description": "Device/resource ID",
            "operators": [":"],
            "examples": ["monitorObjectId:9269"],
        },
        "monitorObjectGroups": {
            "type": "string",
            "description": "Device group full path. Use | for multiple groups, "
            "append * for subgroups.",
            "operators": [":", "~"],
            "examples": [
                'monitorObjectGroups:"Kubernetes Cluster: rm-aks-cluster/*"',
                'monitorObjectGroups:"Devices by Type/Linux Servers"',
            ],
        },
    },
    "common_queries": [
        {
            "description": "Active critical alerts",
            "filter": "severity:4,cleared:false",
        },
        {
            "description": "Unacknowledged errors and above",
            "filter": "severity>:3,acked:false,cleared:false",
        },
        {
            "description": "Alerts for specific device",
            "filter": "monitorObjectName~server-01,cleared:false",
        },
        {
            "description": "CPU-related alerts",
            "filter": "dataPointName~CPU,cleared:false",
        },
        {
            "description": "Alerts for devices in a group (e.g., K8s cluster)",
            "filter": "hostGroupIds~1977,cleared:false",
        },
    ],
}

# Device-specific filter fields
DEVICE_FILTERS = {
    "name": "devices",
    "description": "Filter fields available for device queries",
    "api_endpoint": "/device/devices",
    "fields": {
        "id": {
            "type": "integer",
            "description": "Device ID",
            "operators": [":", "!:"],
            "examples": ["id:123"],
        },
        "displayName": {
            "type": "string",
            "description": "Device display name",
            "operators": [":", "~", "!:", "!~"],
            "examples": ["displayName~prod", "displayName:server-01"],
        },
        "name": {
            "type": "string",
            "description": "Device system name",
            "operators": [":", "~", "!:", "!~"],
            "examples": ["name~192.168"],
        },
        "hostStatus": {
            "type": "string",
            "description": (
                "Device status as a quoted word: normal, dead, dead-collector, unmonitored, "
                "disabled. Numeric codes match nothing"
            ),
            "operators": [":", "!:"],
            "examples": ['hostStatus:"dead"', 'hostStatus!:"normal"'],
        },
        "hostGroupIds": {
            "type": "string",
            "description": "Device group membership",
            "operators": ["~"],
            "examples": ["hostGroupIds~5"],
        },
        "preferredCollectorId": {
            "type": "integer",
            "description": "Collector ID",
            "operators": [":", "!:"],
            "examples": ["preferredCollectorId:10"],
        },
        "deviceType": {
            "type": "integer",
            "description": "Device type (0=regular, 2=AWS, etc.)",
            "operators": [":", "!:"],
            "examples": ["deviceType:0", "deviceType:2"],
        },
        "disableAlerting": {
            "type": "boolean",
            "description": "Alerting disabled flag",
            "operators": [":"],
            "examples": ["disableAlerting:false"],
        },
    },
    "common_queries": [
        {
            "description": "All normal devices",
            "filter": 'hostStatus:"normal"',
        },
        {
            "description": "Dead or problematic devices",
            "filter": 'hostStatus!:"normal"',
        },
        {
            "description": "Production devices by name",
            "filter": 'displayName~"prod",hostStatus:"normal"',
        },
        {
            "description": "Devices in specific group",
            "filter": "hostGroupIds~5",
        },
    ],
}

# SDT-specific filter fields
SDT_FILTERS = {
    "name": "sdts",
    "description": "Filter fields available for SDT queries",
    "api_endpoint": "/sdt/sdts",
    "fields": {
        "type": {
            "type": "string",
            "description": "SDT type (DeviceSDT, DeviceGroupSDT, etc.)",
            "operators": [":"],
            "examples": ["type:DeviceSDT", "type:CollectorSDT"],
        },
        "deviceId": {
            "type": "integer",
            "description": "Device ID for device SDTs",
            "operators": [":", "!:"],
            "examples": ["deviceId:123"],
        },
        "deviceGroupId": {
            "type": "integer",
            "description": "Device group ID for group SDTs",
            "operators": [":", "!:"],
            "examples": ["deviceGroupId:5"],
        },
        "admin": {
            "type": "string",
            "description": "SDT creator username",
            "operators": [":", "~"],
            "examples": ["admin~john"],
        },
        "startDateTime": {
            "type": "integer",
            "description": "SDT start time (epoch ms)",
            "operators": [">", "<", ">:", "<:"],
            "examples": ["startDateTime>:1704067200000"],
        },
        "endDateTime": {
            "type": "integer",
            "description": "SDT end time (epoch ms)",
            "operators": [">", "<", ">:", "<:"],
            "examples": ["endDateTime<:1704153600000"],
        },
        "isEffective": {
            "type": "boolean",
            "description": "Whether SDT is currently active",
            "operators": [":"],
            "examples": ["isEffective:true"],
        },
    },
    "common_queries": [
        {
            "description": "All device SDTs",
            "filter": "type:DeviceSDT",
        },
        {
            "description": "Active SDTs",
            "filter": "isEffective:true",
        },
        {
            "description": "SDTs created by specific user",
            "filter": "admin~john",
        },
    ],
}

# All filter definitions
ALL_FILTERS = {
    "operators": FILTER_OPERATORS,
    "alerts": ALERT_FILTERS,
    "devices": DEVICE_FILTERS,
    "sdts": SDT_FILTERS,
}


def get_filter_content(filter_name: str) -> dict | None:
    """Get filter definition by name.

    Args:
        filter_name: The filter identifier (e.g., 'alerts', 'devices', 'operators').

    Returns:
        Filter definition dict or None if not found.
    """
    return ALL_FILTERS.get(filter_name)
