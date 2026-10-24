# Description: IBM watsonx.ai tool helpers and standalone MCP tools.
# Description: Provides TTM forecasting, NL summary generation, and the watsonx_summarize tool.

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from mcp.types import TextContent

from lm_mcp.tools import format_response, handle_error

if TYPE_CHECKING:
    from lm_mcp.client.watsonx import WatsonxClient


async def watsonx_summarize(
    client: WatsonxClient,
    data: str,
    context: str = "",
    max_tokens: int = 500,
) -> list[TextContent]:
    """Generate a plain-English summary of structured data using IBM Granite.

    Takes JSON data from any MCP tool output and produces a concise,
    shift-handoff-ready summary via watsonx.ai Granite LLM.

    Args:
        client: WatsonxClient instance.
        data: JSON string of structured data to summarize.
        context: Context hint for the summary (e.g., "triage report").
        max_tokens: Maximum tokens in the generated summary.

    Returns:
        MCP TextContent with the summary.
    """
    try:
        parsed = json.loads(data) if isinstance(data, str) else data
        summary = await client.summarize(parsed, context=context, max_tokens=max_tokens)
        return format_response({"summary": summary, "model": client.llm_model_id})
    except Exception as e:
        return handle_error(e)


async def ttm_forecast_helper(
    watsonx_client: WatsonxClient,
    timestamps: list[int],
    values: list[float],
    threshold: float,
    forecast_periods: int = 96,
) -> dict:
    """Run Granite TTM forecast and format result for forecast_metric().

    This is an internal helper, not a registered MCP tool. It is called
    by forecasting.py when method="ttm" and watsonx is configured.

    Args:
        watsonx_client: WatsonxClient instance.
        timestamps: Epoch seconds for historical data.
        values: Metric values corresponding to timestamps.
        threshold: Alert threshold to check breach against.
        forecast_periods: Number of future periods to predict.

    Returns:
        Dict matching the forecast_metric response structure.
    """
    result = await watsonx_client.forecast_ttm(
        timestamps=timestamps,
        values=values,
        forecast_periods=forecast_periods,
    )

    forecast_values = result.get("forecast_values", [])
    current_value = values[-1] if values else 0.0

    # Check if any forecasted value breaches the threshold
    breach_detected = any(v >= threshold for v in forecast_values)
    max_forecast = max(forecast_values) if forecast_values else current_value

    # Estimate days until breach from forecast values
    days_until_breach = None
    if breach_detected and timestamps:
        interval = _estimate_interval(timestamps)
        for i, v in enumerate(forecast_values):
            if v >= threshold:
                days_until_breach = round((i * interval) / 86400, 1)
                break

    return {
        "current_value": current_value,
        "threshold": threshold,
        "breach_detected": breach_detected,
        "max_forecast": max_forecast,
        "days_until_breach": days_until_breach,
        "forecast_values": forecast_values[:24],
        "forecast_count": len(forecast_values),
        "method_used": "ttm",
        "model": result.get("model", "ibm/granite-ttm-512-96-r2"),
    }


async def nl_summarize_helper(
    watsonx_client: WatsonxClient,
    report_data: dict,
    workflow_name: str,
) -> str:
    """Generate NL summary of a workflow tool report.

    This is an internal helper, not a registered MCP tool. It is called
    by workflow tools when summarize=True and watsonx is configured.

    Args:
        watsonx_client: WatsonxClient instance.
        report_data: The structured report dict from a workflow tool.
        workflow_name: Name of the workflow (triage, diagnose, etc.).

    Returns:
        Plain-English summary string.
    """
    return await watsonx_client.summarize(
        data=report_data,
        context=f"{workflow_name} report",
    )


def _estimate_interval(timestamps: list[int]) -> int:
    """Estimate the data collection interval from timestamps in seconds."""
    if len(timestamps) < 2:
        return 300
    diffs = [timestamps[i + 1] - timestamps[i] for i in range(min(10, len(timestamps) - 1))]
    return max(1, int(sum(diffs) / len(diffs)))
