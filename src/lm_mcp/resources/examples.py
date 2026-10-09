# Description: Example response data for key LogicMonitor MCP tools.
# Description: Provides realistic compact examples to help LLMs understand output formats.

from __future__ import annotations

EXAMPLE_RESPONSES: dict = {
    "name": "example-responses",
    "description": (
        "Example output from key LogicMonitor MCP tools to help understand response formats"
    ),
    "examples": {
        "get_alerts": {
            "description": "Active alerts with severity, device, and datasource context",
            "example": {
                "total": 3,
                "count": 3,
                "alerts": [
                    {
                        "id": "LMA12345",
                        "severity": 4,
                        "severity_name": "critical",
                        "monitor_object_name": "prod-web-01.example.com",
                        "resource_template_name": "LinuxCPU",
                        "datapoint_name": "CPUBusyPercent",
                        "alert_value": "98.5",
                        "threshold": "> 95",
                        "start_epoch": 1710288000,
                        "acked": False,
                        "cleared": False,
                    },
                    {
                        "id": "LMA12346",
                        "severity": 3,
                        "severity_name": "error",
                        "monitor_object_name": "prod-db-01.example.com",
                        "resource_template_name": "MySQLStatus",
                        "datapoint_name": "SlowQueries",
                        "alert_value": "45",
                        "threshold": "> 20",
                        "start_epoch": 1710287400,
                        "acked": False,
                        "cleared": False,
                    },
                    {
                        "id": "LMA12347",
                        "severity": 2,
                        "severity_name": "warning",
                        "monitor_object_name": "prod-web-02.example.com",
                        "resource_template_name": "LinuxDisk",
                        "datapoint_name": "UsedPercent",
                        "alert_value": "82.3",
                        "threshold": "> 80",
                        "start_epoch": 1710286800,
                        "acked": True,
                        "cleared": False,
                    },
                ],
            },
        },
        "get_devices": {
            "description": "Device list with status, groups, and collector info",
            "example": {
                "total": 2,
                "count": 2,
                "devices": [
                    {
                        "id": 101,
                        "display_name": "prod-web-01.example.com",
                        "host_name": "10.0.1.10",
                        "host_status": "normal",
                        "status_name": "normal",
                        "device_type": 0,
                        "host_group_ids": "1,5,12",
                        "preferred_collector_id": 10,
                    },
                    {
                        "id": 102,
                        "display_name": "prod-db-01.example.com",
                        "host_name": "10.0.1.20",
                        "host_status": "normal",
                        "status_name": "normal",
                        "device_type": 0,
                        "host_group_ids": "1,6,12",
                        "preferred_collector_id": 10,
                    },
                ],
            },
        },
        "get_device_data": {
            "description": "Raw metric data with timestamps and datapoint values",
            "example": {
                "device_id": 101,
                "device_datasource_id": 5001,
                "instance_id": 3001,
                "datapoints": ["CPUBusyPercent", "CPUIdlePercent"],
                "values": [
                    [85.2, 14.8],
                    [72.1, 27.9],
                    [91.5, 8.5],
                ],
                "time": [1710288000, 1710287700, 1710287400],
            },
        },
        "score_device_health": {
            "description": "Composite health score with per-datapoint z-scores",
            "example": {
                "device_id": 101,
                "health_score": 62,
                "status": "degraded",
                "contributing_factors": [
                    {
                        "datapoint": "CPUBusyPercent",
                        "latest_value": 91.5,
                        "mean": 45.2,
                        "stddev": 15.3,
                        "z_score": 3.03,
                        "weight": 1.0,
                        "weighted_impact": 3.03,
                    },
                    {
                        "datapoint": "MemUsedPercent",
                        "latest_value": 72.1,
                        "mean": 65.8,
                        "stddev": 8.2,
                        "z_score": 0.77,
                        "weight": 1.0,
                        "weighted_impact": 0.77,
                    },
                ],
                "anomaly_count": 1,
            },
        },
        "calculate_availability": {
            "description": "SLA-style availability with per-device breakdown",
            "example": {
                "availability_percent": 99.82,
                "total_downtime_minutes": 129.6,
                "total_uptime_minutes": 43070.4,
                "mttr_minutes": 43.2,
                "incident_count": 3,
                "longest_incident_minutes": 65.0,
                "by_device": {
                    "prod-web-01.example.com": {
                        "availability_percent": 99.82,
                        "downtime_minutes": 129.6,
                        "incident_count": 3,
                    },
                },
                "hours_back": 720,
                "severity_threshold": "error",
            },
        },
        "correlate_alerts": {
            "description": "Alert clusters grouped by device, datasource, and time",
            "example": {
                "total_alerts": 8,
                "cluster_count": 3,
                "time_window_hours": 4,
                "clusters": [
                    {
                        "type": "device",
                        "key": "prod-web-01.example.com",
                        "count": 4,
                        "alert_ids": [
                            "LMA12345",
                            "LMA12348",
                            "LMA12349",
                            "LMA12350",
                        ],
                        "first_alert_time": 1710286800,
                        "last_alert_time": 1710288000,
                    },
                    {
                        "type": "datasource",
                        "key": "LinuxCPU",
                        "count": 3,
                        "devices": [
                            "prod-web-01.example.com",
                            "prod-web-02.example.com",
                        ],
                        "alert_ids": ["LMA12345", "LMA12348", "LMA12351"],
                        "first_alert_time": 1710287400,
                        "last_alert_time": 1710288000,
                    },
                    {
                        "type": "temporal",
                        "key": "window_1710287400",
                        "count": 3,
                        "alert_ids": ["LMA12345", "LMA12346", "LMA12348"],
                        "first_alert_time": 1710287400,
                        "last_alert_time": 1710287600,
                    },
                ],
            },
        },
        "forecast_metric": {
            "description": "Per-datapoint trend forecast with breach prediction",
            "example": {
                "device_id": 101,
                "device_datasource_id": 5001,
                "instance_id": 3001,
                "hours_back": 168,
                "method_used": "linear",
                "forecasts": {
                    "UsedPercent": {
                        "current_value": 72.3,
                        "threshold": 90.0,
                        "trend": "increasing",
                        "slope_per_hour": 0.015,
                        "r_squared": 0.87,
                        "days_until_breach": 49.2,
                        "predicted_breach_epoch": 1714536000,
                        "sample_count": 2016,
                    },
                },
            },
        },
    },
}


def get_example_responses() -> dict:
    """Get all example response data.

    Returns:
        Dict containing example responses for key tools.
    """
    return EXAMPLE_RESPONSES
