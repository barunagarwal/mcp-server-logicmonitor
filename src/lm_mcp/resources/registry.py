# Description: MCP resource registry for LogicMonitor schema resources.
# Description: Provides resource definitions and content retrieval functions.

from __future__ import annotations

import json

from mcp.types import Resource
from pydantic import AnyUrl

from lm_mcp.resources.enums import get_enum_content
from lm_mcp.resources.filters import get_filter_content
from lm_mcp.resources.guides import get_guide_content
from lm_mcp.resources.schemas import get_schema_content

# MCP Resource definitions for LogicMonitor API schemas
RESOURCES: list[Resource] = [
    # Schema resources - API object field definitions
    Resource(
        uri=AnyUrl("lm://schema/alerts"),
        name="Alert Schema",
        description="LogicMonitor alert object fields, types, and descriptions",
        mimeType="application/json",
    ),
    Resource(
        uri=AnyUrl("lm://schema/devices"),
        name="Device Schema",
        description="LogicMonitor device object fields, types, and descriptions",
        mimeType="application/json",
    ),
    Resource(
        uri=AnyUrl("lm://schema/sdts"),
        name="SDT Schema",
        description="LogicMonitor SDT (Scheduled Downtime) object fields",
        mimeType="application/json",
    ),
    Resource(
        uri=AnyUrl("lm://schema/dashboards"),
        name="Dashboard Schema",
        description="LogicMonitor dashboard object fields",
        mimeType="application/json",
    ),
    Resource(
        uri=AnyUrl("lm://schema/collectors"),
        name="Collector Schema",
        description="LogicMonitor collector object fields",
        mimeType="application/json",
    ),
    Resource(
        uri=AnyUrl("lm://schema/escalations"),
        name="Escalation Chain Schema",
        description="LogicMonitor escalation chain object fields",
        mimeType="application/json",
    ),
    Resource(
        uri=AnyUrl("lm://schema/reports"),
        name="Report Schema",
        description="LogicMonitor report object fields",
        mimeType="application/json",
    ),
    Resource(
        uri=AnyUrl("lm://schema/websites"),
        name="Website Schema",
        description="LogicMonitor website check object fields",
        mimeType="application/json",
    ),
    Resource(
        uri=AnyUrl("lm://schema/datasources"),
        name="DataSource Schema",
        description="LogicMonitor DataSource definition fields",
        mimeType="application/json",
    ),
    Resource(
        uri=AnyUrl("lm://schema/users"),
        name="User Schema",
        description="LogicMonitor user object fields",
        mimeType="application/json",
    ),
    Resource(
        uri=AnyUrl("lm://schema/audit"),
        name="Audit Log Schema",
        description="LogicMonitor audit log entry fields",
        mimeType="application/json",
    ),
    # Enum resources - valid values for specific fields
    Resource(
        uri=AnyUrl("lm://enums/severity"),
        name="Alert Severity Values",
        description="Valid severity levels: critical(4), error(3), warning(2), info(1)",
        mimeType="application/json",
    ),
    Resource(
        uri=AnyUrl("lm://enums/device-status"),
        name="Device Status Values",
        description="Valid device status values: normal(0), dead(1), etc.",
        mimeType="application/json",
    ),
    Resource(
        uri=AnyUrl("lm://enums/sdt-type"),
        name="SDT Type Values",
        description="Valid SDT types: DeviceSDT, DeviceGroupSDT, etc.",
        mimeType="application/json",
    ),
    Resource(
        uri=AnyUrl("lm://enums/alert-cleared"),
        name="Alert Cleared Status",
        description="Alert cleared status values: true, false",
        mimeType="application/json",
    ),
    Resource(
        uri=AnyUrl("lm://enums/alert-acked"),
        name="Alert Acknowledged Status",
        description="Alert acknowledgment status values: true, false",
        mimeType="application/json",
    ),
    Resource(
        uri=AnyUrl("lm://enums/collector-build"),
        name="Collector Build Types",
        description="Collector build version types: EA, GD, MGD",
        mimeType="application/json",
    ),
    # Filter resources - how to filter API queries
    Resource(
        uri=AnyUrl("lm://filters/alerts"),
        name="Alert Filter Fields",
        description="Filter fields and operators for alert queries",
        mimeType="application/json",
    ),
    Resource(
        uri=AnyUrl("lm://filters/devices"),
        name="Device Filter Fields",
        description="Filter fields and operators for device queries",
        mimeType="application/json",
    ),
    Resource(
        uri=AnyUrl("lm://filters/sdts"),
        name="SDT Filter Fields",
        description="Filter fields and operators for SDT queries",
        mimeType="application/json",
    ),
    Resource(
        uri=AnyUrl("lm://syntax/operators"),
        name="Filter Operators",
        description="LogicMonitor API filter operators: :, ~, >, <, !:, !~, >:, <:",
        mimeType="application/json",
    ),
    # Guide resources - help AI agents pick tools and construct queries
    Resource(
        uri=AnyUrl("lm://guide/tool-categories"),
        name="Tool Categories",
        description="All LogicMonitor MCP tools organized by domain category",
        mimeType="application/json",
    ),
    Resource(
        uri=AnyUrl("lm://guide/examples"),
        name="Common Query Examples",
        description="Common filter patterns and query examples for LogicMonitor API",
        mimeType="application/json",
    ),
    Resource(
        uri=AnyUrl("lm://guide/mcp-orchestration"),
        name="MCP Server Orchestration Guide",
        description="Patterns for combining LogicMonitor with other MCP servers",
        mimeType="application/json",
    ),
    Resource(
        uri=AnyUrl("lm://guide/best-practices"),
        name="Best Practices Guide",
        description=(
            "Scenario-based best practices for alert noise, device health, "
            "availability, and remediation"
        ),
        mimeType="application/json",
    ),
    Resource(
        uri=AnyUrl("lm://guide/example-responses"),
        name="Example Tool Responses",
        description=("Realistic example output from key tools to help understand response formats"),
        mimeType="application/json",
    ),
]


def get_resource_content(uri: str) -> str:
    """Get the content for a resource by its URI.

    Args:
        uri: The resource URI (e.g., 'lm://schema/alerts').

    Returns:
        JSON string containing the resource content.

    Raises:
        ValueError: If the URI is not recognized.
    """
    # Parse URI to determine resource type and name
    if not uri.startswith("lm://"):
        raise ValueError(f"Invalid resource URI: {uri}")

    path = uri[5:]  # Remove 'lm://' prefix
    parts = path.split("/", 1)

    if len(parts) != 2:
        raise ValueError(f"Invalid resource path: {path}")

    resource_type, resource_name = parts

    content: dict | None = None

    if resource_type == "schema":
        content = get_schema_content(resource_name)
    elif resource_type == "enums":
        content = get_enum_content(resource_name)
    elif resource_type == "filters":
        content = get_filter_content(resource_name)
    elif resource_type == "syntax":
        if resource_name == "operators":
            content = get_filter_content("operators")
    elif resource_type == "guide":
        content = get_guide_content(resource_name)

    if content is None:
        raise ValueError(f"Resource not found: {uri}")

    return json.dumps(content, indent=2)


def get_resource_by_uri(uri: str) -> Resource | None:
    """Find a resource definition by its URI.

    Args:
        uri: The resource URI to find.

    Returns:
        Resource object if found, None otherwise.
    """
    for resource in RESOURCES:
        if str(resource.uri) == uri:
            return resource
    return None


def list_resource_uris() -> list[str]:
    """Get a list of all available resource URIs.

    Returns:
        List of resource URI strings.
    """
    return [str(resource.uri) for resource in RESOURCES]
