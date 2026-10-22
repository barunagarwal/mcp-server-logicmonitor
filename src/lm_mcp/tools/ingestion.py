# Description: Log and metric ingestion tools for LogicMonitor MCP server.
# Description: Provides ingest_logs and push_metrics using LMv1 HMAC authentication.

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp.types import TextContent

from lm_mcp.tools import (
    format_response,
    handle_error,
    require_write_permission,
    validation_error,
)

if TYPE_CHECKING:
    from lm_mcp.client import LogicMonitorClient


@require_write_permission
async def ingest_logs(
    client: LogicMonitorClient,
    logs: list[dict],
) -> list[TextContent]:
    """Ingest log entries into LogicMonitor.

    Sends log entries to the LogicMonitor log ingestion API. Each log entry
    should contain a message and resource mapping information.

    Args:
        client: LogicMonitor API client with LMv1 authentication.
        logs: List of log entries. Each entry should have:
            - message: The log message text
            - _lm.resourceId: Resource mapping (e.g., {"system.hostname": "server1"})
            - Optional: timestamp (epoch ms), other metadata

    Returns:
        List containing TextContent with ingestion result.

    Example log entry:
        {
            "message": "Application started successfully",
            "_lm.resourceId": {"system.hostname": "webserver1"},
            "timestamp": 1609459200000
        }
    """
    try:
        if not logs:
            return validation_error(
                "VALIDATION_ERROR",
                "logs list cannot be empty",
                suggestion="Pass at least one log entry with message + _lm.resourceId.",
            )

        result = await client.ingest_post("/rest/log/ingest", json_body=logs)
        return format_response(result)
    except Exception as e:
        return handle_error(e)


@require_write_permission
async def push_metrics(
    client: LogicMonitorClient,
    metrics: dict,
) -> list[TextContent]:
    """Push custom metrics into LogicMonitor.

    Sends metric data to the LogicMonitor v2 metric ingestion API.
    Metrics are associated with resources and organized by datasource.

    Args:
        client: LogicMonitor API client with LMv1 authentication.
        metrics: Metric payload containing:
            - resourceIds: Resource mapping (e.g., {"system.hostname": "server1"})
            - dataSource: Name of the datasource for these metrics
            - dataSourceGroup: Optional datasource group name
            - instances: List of instance data with datapoints

    Returns:
        List containing TextContent with ingestion result.

    Example metrics payload:
        {
            "resourceIds": {"system.hostname": "server1"},
            "dataSource": "CustomAppMetrics",
            "dataSourceGroup": "MyApplications",
            "instances": [
                {
                    "instanceName": "main",
                    "dataPoints": [
                        {"dataPointName": "requests", "values": [100, 150, 200]}
                    ]
                }
            ]
        }
    """
    try:
        if not metrics:
            return validation_error(
                "VALIDATION_ERROR",
                "metrics payload cannot be empty",
                suggestion="Provide resourceIds, dataSource, and instances at minimum.",
            )

        if "resourceIds" not in metrics:
            return validation_error(
                "VALIDATION_ERROR",
                "metrics.resourceIds is required",
                suggestion='Add resourceIds, e.g. {"system.hostname": "server1"}.',
            )
        if "dataSource" not in metrics:
            return validation_error(
                "VALIDATION_ERROR",
                "metrics.dataSource is required",
                suggestion="Add a dataSource name string.",
            )

        result = await client.ingest_post(
            "/rest/metric/ingest", json_body=metrics, params={"create": "true"}
        )
        return format_response(result)
    except Exception as e:
        return handle_error(e)
