# Description: Schema definitions for LogicMonitor API objects.
# Description: Provides field names, types, and descriptions for alerts, devices, and SDTs.

from __future__ import annotations

# Alert schema - fields available on LogicMonitor alert objects
ALERT_SCHEMA = {
    "name": "alerts",
    "description": "LogicMonitor alert object schema",
    "api_endpoint": "/alert/alerts",
    "fields": {
        "id": {
            "type": "string",
            "description": "Alert ID with LMA prefix (e.g., LMA12345)",
            "filterable": True,
            "example": "LMA12345",
        },
        "severity": {
            "type": "integer",
            "description": "Alert severity level: 1=info, 2=warning, 3=error, 4=critical",
            "filterable": True,
            "enum_ref": "severity",
            "example": 4,
        },
        "cleared": {
            "type": "boolean",
            "description": "Whether the alert has been cleared/resolved",
            "filterable": True,
            "example": False,
        },
        "acked": {
            "type": "boolean",
            "description": "Whether the alert has been acknowledged",
            "filterable": True,
            "example": False,
        },
        "sdted": {
            "type": "boolean",
            "description": "Whether the resource is in scheduled downtime",
            "filterable": True,
            "example": False,
        },
        "startEpoch": {
            "type": "integer",
            "description": "Alert start time in epoch milliseconds",
            "filterable": True,
            "operators": [">", "<", ">:", "<:"],
            "example": 1704067200000,
        },
        "endEpoch": {
            "type": "integer",
            "description": "Alert end time in epoch milliseconds (0 if not cleared)",
            "filterable": True,
            "operators": [">", "<", ">:", "<:"],
        },
        "monitorObjectName": {
            "type": "string",
            "description": "Display name of the device generating the alert",
            "filterable": True,
            "operators": [":", "~", "!:", "!~"],
            "example": "server-01.example.com",
        },
        "monitorObjectId": {
            "type": "integer",
            "description": "ID of the device generating the alert",
            "filterable": True,
        },
        "monitorObjectType": {
            "type": "string",
            "description": "Type of monitored object (device, website, etc.)",
            "filterable": True,
        },
        "dataPointName": {
            "type": "string",
            "description": "Name of the datapoint that triggered the alert",
            "filterable": True,
            "operators": [":", "~"],
            "example": "CPUBusyPercent",
        },
        "dataPointId": {
            "type": "integer",
            "description": "ID of the datapoint",
            "filterable": True,
        },
        "instanceName": {
            "type": "string",
            "description": "Name of the datasource instance",
            "filterable": True,
            "operators": [":", "~"],
            "example": "CPU",
        },
        "instanceId": {
            "type": "integer",
            "description": "ID of the datasource instance",
            "filterable": True,
        },
        "resourceTemplateName": {
            "type": "string",
            "description": "Name of the DataSource that generated the alert",
            "filterable": True,
            "operators": [":", "~"],
            "example": "WinCPU",
        },
        "resourceTemplateId": {
            "type": "integer",
            "description": "ID of the DataSource",
            "filterable": True,
        },
        "threshold": {
            "type": "string",
            "description": "Threshold value that was exceeded",
            "filterable": False,
        },
        "value": {
            "type": "string",
            "description": "Current value that triggered the alert",
            "filterable": False,
        },
        "rule": {
            "type": "string",
            "description": "Name of the alert rule that matched",
            "filterable": True,
            "operators": [":", "~"],
        },
        "ruleId": {
            "type": "integer",
            "description": "ID of the alert rule",
            "filterable": True,
        },
        "chain": {
            "type": "string",
            "description": "Name of the escalation chain",
            "filterable": True,
        },
        "chainId": {
            "type": "integer",
            "description": "ID of the escalation chain",
            "filterable": True,
        },
        "ackedBy": {
            "type": "string",
            "description": "Username who acknowledged the alert",
            "filterable": True,
            "operators": [":", "~"],
        },
        "ackedEpoch": {
            "type": "integer",
            "description": "Time when alert was acknowledged (epoch ms)",
            "filterable": True,
        },
    },
}

# Device schema - fields available on LogicMonitor device objects
DEVICE_SCHEMA = {
    "name": "devices",
    "description": "LogicMonitor device object schema",
    "api_endpoint": "/device/devices",
    "fields": {
        "id": {
            "type": "integer",
            "description": "Unique device identifier",
            "filterable": True,
            "example": 123,
        },
        "name": {
            "type": "string",
            "description": "Device system name (often hostname or IP)",
            "filterable": True,
            "operators": [":", "~", "!:", "!~"],
            "example": "192.168.1.100",
        },
        "displayName": {
            "type": "string",
            "description": "Human-friendly display name",
            "filterable": True,
            "operators": [":", "~", "!:", "!~"],
            "example": "Production Web Server 01",
        },
        "hostStatus": {
            "type": "string",
            "description": "Device status word - see enum device-status for values",
            "filterable": True,
            "enum_ref": "device-status",
            "example": "normal",
        },
        "hostGroupIds": {
            "type": "string",
            "description": "Comma-separated list of device group IDs",
            "filterable": True,
            "operators": ["~"],
            "example": "1,5,12",
        },
        "preferredCollectorId": {
            "type": "integer",
            "description": "ID of the collector monitoring this device",
            "filterable": True,
        },
        "preferredCollectorGroupId": {
            "type": "integer",
            "description": "ID of the collector group",
            "filterable": True,
        },
        "deviceType": {
            "type": "integer",
            "description": "Device type: 0=regular, 2=AWS, 4=Azure, 6=GCP",
            "filterable": True,
        },
        "enableNetflow": {
            "type": "boolean",
            "description": "Whether NetFlow monitoring is enabled",
            "filterable": True,
        },
        "disableAlerting": {
            "type": "boolean",
            "description": "Whether alerting is disabled for this device",
            "filterable": True,
        },
        "createdOn": {
            "type": "integer",
            "description": "Device creation time (epoch seconds)",
            "filterable": True,
            "operators": [">", "<", ">:", "<:"],
        },
        "updatedOn": {
            "type": "integer",
            "description": "Last update time (epoch seconds)",
            "filterable": True,
            "operators": [">", "<", ">:", "<:"],
        },
        "currentCollectorId": {
            "type": "integer",
            "description": "ID of collector currently monitoring device",
            "filterable": True,
        },
        "description": {
            "type": "string",
            "description": "Device description",
            "filterable": True,
            "operators": [":", "~"],
        },
        "link": {
            "type": "string",
            "description": "External link associated with device",
            "filterable": False,
        },
    },
}

# SDT (Scheduled Downtime) schema
SDT_SCHEMA = {
    "name": "sdts",
    "description": "LogicMonitor Scheduled Downtime (SDT) object schema",
    "api_endpoint": "/sdt/sdts",
    "fields": {
        "id": {
            "type": "string",
            "description": "SDT ID in format TYPE_NUMBER (e.g., D_123)",
            "filterable": True,
            "example": "D_123",
        },
        "type": {
            "type": "string",
            "description": "SDT type indicating what resource is in downtime",
            "filterable": True,
            "enum_ref": "sdt-type",
            "example": "DeviceSDT",
        },
        "sdtType": {
            "type": "string",
            "description": "Schedule type: oneTime, daily, weekly, monthly",
            "filterable": True,
            "example": "oneTime",
        },
        "startDateTime": {
            "type": "integer",
            "description": "SDT start time in epoch milliseconds",
            "filterable": True,
            "operators": [">", "<", ">:", "<:"],
        },
        "endDateTime": {
            "type": "integer",
            "description": "SDT end time in epoch milliseconds",
            "filterable": True,
            "operators": [">", "<", ">:", "<:"],
        },
        "duration": {
            "type": "integer",
            "description": "SDT duration in minutes",
            "filterable": True,
        },
        "deviceId": {
            "type": "integer",
            "description": "Device ID (for DeviceSDT type)",
            "filterable": True,
        },
        "deviceGroupId": {
            "type": "integer",
            "description": "Device group ID (for DeviceGroupSDT type)",
            "filterable": True,
        },
        "deviceDisplayName": {
            "type": "string",
            "description": "Display name of the device in SDT",
            "filterable": True,
            "operators": [":", "~"],
        },
        "admin": {
            "type": "string",
            "description": "Username who created the SDT",
            "filterable": True,
            "operators": [":", "~"],
        },
        "comment": {
            "type": "string",
            "description": "SDT comment/reason",
            "filterable": True,
            "operators": [":", "~"],
        },
        "isEffective": {
            "type": "boolean",
            "description": "Whether SDT is currently active",
            "filterable": True,
        },
        "weekDay": {
            "type": "string",
            "description": "Day of week for recurring SDT",
            "filterable": True,
            "example": "Monday",
        },
        "monthDay": {
            "type": "integer",
            "description": "Day of month for recurring SDT",
            "filterable": True,
        },
        "hour": {
            "type": "integer",
            "description": "Start hour for recurring SDT (0-23)",
            "filterable": True,
        },
        "minute": {
            "type": "integer",
            "description": "Start minute for recurring SDT (0-59)",
            "filterable": True,
        },
    },
}

# Dashboard schema
DASHBOARD_SCHEMA = {
    "name": "dashboards",
    "description": "LogicMonitor dashboard object schema",
    "api_endpoint": "/dashboard/dashboards",
    "fields": {
        "id": {
            "type": "integer",
            "description": "Unique dashboard identifier",
            "filterable": True,
        },
        "name": {
            "type": "string",
            "description": "Dashboard name",
            "filterable": True,
            "operators": [":", "~", "!:", "!~"],
        },
        "groupId": {
            "type": "integer",
            "description": "Dashboard group ID",
            "filterable": True,
        },
        "groupName": {
            "type": "string",
            "description": "Dashboard group name",
            "filterable": True,
            "operators": [":", "~"],
        },
        "description": {
            "type": "string",
            "description": "Dashboard description",
            "filterable": True,
            "operators": [":", "~"],
        },
        "sharable": {
            "type": "boolean",
            "description": "Whether dashboard can be shared",
            "filterable": True,
        },
        "owner": {
            "type": "string",
            "description": "Dashboard owner username",
            "filterable": True,
            "operators": [":", "~"],
        },
    },
}

# Collector schema
COLLECTOR_SCHEMA = {
    "name": "collectors",
    "description": "LogicMonitor collector object schema",
    "api_endpoint": "/setting/collector/collectors",
    "fields": {
        "id": {
            "type": "integer",
            "description": "Unique collector identifier",
            "filterable": True,
        },
        "hostname": {
            "type": "string",
            "description": "Collector hostname",
            "filterable": True,
            "operators": [":", "~", "!:", "!~"],
        },
        "description": {
            "type": "string",
            "description": "Collector description",
            "filterable": True,
            "operators": [":", "~"],
        },
        "collectorGroupId": {
            "type": "integer",
            "description": "Collector group ID",
            "filterable": True,
        },
        "collectorGroupName": {
            "type": "string",
            "description": "Collector group name",
            "filterable": True,
            "operators": [":", "~"],
        },
        "status": {
            "type": "integer",
            "description": "Collector status code",
            "filterable": True,
        },
        "build": {
            "type": "string",
            "description": "Collector build version",
            "filterable": True,
        },
        "platform": {
            "type": "string",
            "description": "Collector platform (linux, windows)",
            "filterable": True,
        },
        "isDown": {
            "type": "boolean",
            "description": "Whether collector is down",
            "filterable": True,
        },
    },
}

# Escalation chain schema
ESCALATION_SCHEMA = {
    "name": "escalations",
    "description": "LogicMonitor escalation chain object schema",
    "api_endpoint": "/setting/alert/chains",
    "fields": {
        "id": {
            "type": "integer",
            "description": "Unique escalation chain identifier",
            "filterable": True,
        },
        "name": {
            "type": "string",
            "description": "Escalation chain name",
            "filterable": True,
            "operators": [":", "~", "!:", "!~"],
        },
        "description": {
            "type": "string",
            "description": "Escalation chain description",
            "filterable": True,
            "operators": [":", "~"],
        },
        "enableThrottling": {
            "type": "boolean",
            "description": "Whether alert throttling is enabled",
            "filterable": True,
        },
        "throttlingPeriod": {
            "type": "integer",
            "description": "Throttling period in minutes",
            "filterable": False,
        },
        "throttlingAlerts": {
            "type": "integer",
            "description": "Number of alerts before throttling activates",
            "filterable": False,
        },
        "inAlerting": {
            "type": "boolean",
            "description": "Whether chain is actively used in alerting",
            "filterable": True,
        },
    },
}

# Report schema
REPORT_SCHEMA = {
    "name": "reports",
    "description": "LogicMonitor report object schema",
    "api_endpoint": "/report/reports",
    "fields": {
        "id": {
            "type": "integer",
            "description": "Unique report identifier",
            "filterable": True,
        },
        "name": {
            "type": "string",
            "description": "Report name",
            "filterable": True,
            "operators": [":", "~", "!:", "!~"],
        },
        "type": {
            "type": "string",
            "description": "Report type (Alert, Host inventory, etc.)",
            "filterable": True,
            "operators": [":", "~"],
        },
        "groupId": {
            "type": "integer",
            "description": "Report group ID",
            "filterable": True,
        },
        "format": {
            "type": "string",
            "description": "Output format (PDF, CSV, HTML)",
            "filterable": True,
        },
        "description": {
            "type": "string",
            "description": "Report description",
            "filterable": True,
            "operators": [":", "~"],
        },
        "lastGenerateOn": {
            "type": "integer",
            "description": "Last generation timestamp (epoch seconds)",
            "filterable": True,
            "operators": [">", "<", ">:", "<:"],
        },
    },
}

# Website schema
WEBSITE_SCHEMA = {
    "name": "websites",
    "description": "LogicMonitor website check object schema",
    "api_endpoint": "/website/websites",
    "fields": {
        "id": {
            "type": "integer",
            "description": "Unique website check identifier",
            "filterable": True,
        },
        "name": {
            "type": "string",
            "description": "Website check name",
            "filterable": True,
            "operators": [":", "~", "!:", "!~"],
        },
        "type": {
            "type": "string",
            "description": "Check type (webcheck, pingcheck)",
            "filterable": True,
        },
        "domain": {
            "type": "string",
            "description": "Domain or host being monitored",
            "filterable": True,
            "operators": [":", "~"],
        },
        "status": {
            "type": "string",
            "description": "Website status (alive, dead)",
            "filterable": True,
        },
        "pollingInterval": {
            "type": "integer",
            "description": "Check interval in minutes",
            "filterable": True,
        },
        "groupId": {
            "type": "integer",
            "description": "Website group ID",
            "filterable": True,
        },
        "isInternal": {
            "type": "boolean",
            "description": "Whether monitored via internal collector",
            "filterable": True,
        },
        "disableAlerting": {
            "type": "boolean",
            "description": "Whether alerting is disabled",
            "filterable": True,
        },
    },
}

# DataSource schema
DATASOURCE_SCHEMA = {
    "name": "datasources",
    "description": "LogicMonitor DataSource definition schema",
    "api_endpoint": "/setting/datasources",
    "fields": {
        "id": {
            "type": "integer",
            "description": "Unique DataSource identifier",
            "filterable": True,
        },
        "name": {
            "type": "string",
            "description": "DataSource internal name",
            "filterable": True,
            "operators": [":", "~", "!:", "!~"],
        },
        "displayName": {
            "type": "string",
            "description": "DataSource display name",
            "filterable": True,
            "operators": [":", "~"],
        },
        "appliesTo": {
            "type": "string",
            "description": "AppliesTo expression controlling which devices get this DataSource",
            "filterable": True,
            "operators": ["~"],
        },
        "collectMethod": {
            "type": "string",
            "description": "Collection method (snmp, script, jdbc, etc.)",
            "filterable": True,
        },
        "group": {
            "type": "string",
            "description": "DataSource group name",
            "filterable": True,
            "operators": [":", "~"],
        },
        "technology": {
            "type": "string",
            "description": "Technology category",
            "filterable": True,
        },
        "hasMultiInstances": {
            "type": "boolean",
            "description": "Whether DataSource supports multiple instances",
            "filterable": True,
        },
    },
}

# User schema
USER_SCHEMA = {
    "name": "users",
    "description": "LogicMonitor user object schema",
    "api_endpoint": "/setting/admins",
    "fields": {
        "id": {
            "type": "integer",
            "description": "Unique user identifier",
            "filterable": True,
        },
        "username": {
            "type": "string",
            "description": "Login username",
            "filterable": True,
            "operators": [":", "~", "!:", "!~"],
        },
        "email": {
            "type": "string",
            "description": "User email address",
            "filterable": True,
            "operators": [":", "~"],
        },
        "status": {
            "type": "string",
            "description": "Account status (active, suspended)",
            "filterable": True,
        },
        "firstName": {
            "type": "string",
            "description": "User first name",
            "filterable": True,
            "operators": [":", "~"],
        },
        "lastName": {
            "type": "string",
            "description": "User last name",
            "filterable": True,
            "operators": [":", "~"],
        },
        "roles": {
            "type": "array",
            "description": "Assigned role IDs and names",
            "filterable": False,
        },
        "twoFAEnabled": {
            "type": "boolean",
            "description": "Whether two-factor authentication is enabled",
            "filterable": True,
        },
    },
}

# Audit log schema
AUDIT_SCHEMA = {
    "name": "audit",
    "description": "LogicMonitor audit log entry schema",
    "api_endpoint": "/setting/accesslogs",
    "fields": {
        "id": {
            "type": "integer",
            "description": "Unique audit log entry ID",
            "filterable": True,
        },
        "username": {
            "type": "string",
            "description": "Username who performed the action",
            "filterable": True,
            "operators": [":", "~"],
        },
        "ip": {
            "type": "string",
            "description": "Source IP address",
            "filterable": True,
            "operators": [":", "~"],
        },
        "happenedOn": {
            "type": "string",
            "description": "Action type (login, create, update, delete, etc.)",
            "filterable": True,
            "operators": [":"],
        },
        "happenedOnLocal": {
            "type": "integer",
            "description": "Timestamp of the action (epoch seconds)",
            "filterable": True,
            "operators": [">", "<", ">:", "<:"],
        },
        "description": {
            "type": "string",
            "description": "Human-readable description of the action",
            "filterable": True,
            "operators": ["~"],
        },
        "sessionId": {
            "type": "string",
            "description": "Session identifier",
            "filterable": False,
        },
    },
}

# All schemas for easy iteration
ALL_SCHEMAS = {
    "alerts": ALERT_SCHEMA,
    "devices": DEVICE_SCHEMA,
    "sdts": SDT_SCHEMA,
    "dashboards": DASHBOARD_SCHEMA,
    "collectors": COLLECTOR_SCHEMA,
    "escalations": ESCALATION_SCHEMA,
    "reports": REPORT_SCHEMA,
    "websites": WEBSITE_SCHEMA,
    "datasources": DATASOURCE_SCHEMA,
    "users": USER_SCHEMA,
    "audit": AUDIT_SCHEMA,
}


def get_schema_content(schema_name: str) -> dict | None:
    """Get schema definition by name.

    Args:
        schema_name: The schema identifier (e.g., 'alerts', 'devices').

    Returns:
        Schema definition dict or None if not found.
    """
    return ALL_SCHEMAS.get(schema_name)
