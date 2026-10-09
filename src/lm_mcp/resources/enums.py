# Description: Enum value definitions for LogicMonitor API fields.
# Description: Provides valid values for severity, status, and type fields.

from __future__ import annotations

# Alert severity levels (API uses numeric values)
SEVERITY_ENUM = {
    "name": "severity",
    "description": "Alert severity levels for LogicMonitor alerts",
    "values": {
        "critical": {
            "api_value": 4,
            "description": "Critical severity - highest priority alerts",
        },
        "error": {
            "api_value": 3,
            "description": "Error severity - significant issues",
        },
        "warning": {
            "api_value": 2,
            "description": "Warning severity - potential issues",
        },
        "info": {
            "api_value": 1,
            "description": "Info severity - informational alerts",
        },
    },
    "filter_examples": [
        "severity:4 (critical only)",
        "severity>:2 (warning and above)",
        "severity:3,severity:4 (error and critical)",
    ],
}

# Device status values
DEVICE_STATUS_ENUM = {
    "name": "device-status",
    "description": "Device monitoring status values",
    "values": {
        "normal": {
            "api_value": "normal",
            "description": "Device is being monitored normally",
        },
        "dead": {
            "api_value": "dead",
            "description": "Device is not responding",
        },
        "dead-collector": {
            "api_value": "dead-collector",
            "description": "Collector monitoring this device is down",
        },
        "unmonitored": {
            "api_value": "unmonitored",
            "description": "Device exists but is not being monitored",
        },
        "disabled": {
            "api_value": "disabled",
            "description": "Monitoring is disabled for this device",
        },
    },
    "api_field": "hostStatus",
    "filter_examples": [
        'hostStatus:"normal" (normal devices)',
        'hostStatus:"dead" (dead devices)',
        'hostStatus!:"normal" (all non-normal devices)',
    ],
    "note": (
        "The API returns and filters hostStatus as a quoted word. Numeric codes "
        "(0, 1, 2) match nothing, and an unquoted word is rejected."
    ),
}

# SDT (Scheduled Downtime) type values
SDT_TYPE_ENUM = {
    "name": "sdt-type",
    "description": "Scheduled Downtime types for different resource levels",
    "values": {
        "DeviceSDT": {
            "description": "SDT applied to a specific device",
        },
        "DeviceGroupSDT": {
            "description": "SDT applied to a device group",
        },
        "DeviceDataSourceSDT": {
            "description": "SDT applied to a datasource on a device",
        },
        "DeviceDataSourceInstanceSDT": {
            "description": "SDT applied to a specific instance",
        },
        "DeviceDataSourceInstanceGroupSDT": {
            "description": "SDT applied to an instance group",
        },
        "DeviceBatchJobSDT": {
            "description": "SDT applied to a batch job on a device",
        },
        "DeviceClusterAlertDefSDT": {
            "description": "SDT applied to cluster alert definition",
        },
        "DeviceEventSourceSDT": {
            "description": "SDT applied to an event source",
        },
        "ServiceSDT": {
            "description": "SDT applied to a service",
        },
        "ServiceGroupSDT": {
            "description": "SDT applied to a service group",
        },
        "WebsiteSDT": {
            "description": "SDT applied to a website check",
        },
        "WebsiteGroupSDT": {
            "description": "SDT applied to a website group",
        },
        "CollectorSDT": {
            "description": "SDT applied to a collector",
        },
    },
    "api_field": "type",
    "filter_examples": [
        "type:DeviceSDT",
        "type:DeviceGroupSDT",
        "type:CollectorSDT",
    ],
}

# Alert cleared status
ALERT_CLEARED_ENUM = {
    "name": "alert-cleared",
    "description": "Alert cleared status values",
    "values": {
        "true": {"description": "Alert has been cleared/resolved"},
        "false": {"description": "Alert is still active"},
    },
    "api_field": "cleared",
    "filter_examples": [
        "cleared:false (active alerts only)",
        "cleared:true (cleared alerts only)",
    ],
}

# Alert acknowledged status
ALERT_ACKED_ENUM = {
    "name": "alert-acked",
    "description": "Alert acknowledgment status values",
    "values": {
        "true": {"description": "Alert has been acknowledged"},
        "false": {"description": "Alert has not been acknowledged"},
    },
    "api_field": "acked",
    "filter_examples": [
        "acked:false (unacknowledged alerts)",
        "acked:true (acknowledged alerts)",
    ],
}

# Collector build values
COLLECTOR_BUILD_ENUM = {
    "name": "collector-build",
    "description": "Collector build/version status",
    "values": {
        "EA": {"description": "Early Access build"},
        "GD": {"description": "General Deployment build"},
        "MGD": {"description": "Mandatory General Deployment build"},
    },
    "api_field": "build",
}

# All enums for easy iteration
ALL_ENUMS = {
    "severity": SEVERITY_ENUM,
    "device-status": DEVICE_STATUS_ENUM,
    "sdt-type": SDT_TYPE_ENUM,
    "alert-cleared": ALERT_CLEARED_ENUM,
    "alert-acked": ALERT_ACKED_ENUM,
    "collector-build": COLLECTOR_BUILD_ENUM,
}


def get_enum_content(enum_name: str) -> dict | None:
    """Get enum definition by name.

    Args:
        enum_name: The enum identifier (e.g., 'severity', 'device-status').

    Returns:
        Enum definition dict or None if not found.
    """
    return ALL_ENUMS.get(enum_name)
