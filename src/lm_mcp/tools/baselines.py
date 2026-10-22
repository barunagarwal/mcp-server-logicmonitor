# Description: Baseline metric comparison tools for session-based analysis.
# Description: Save metric baselines and compare current data against stored baselines.

from __future__ import annotations

import statistics
import time

from mcp.types import TextContent

from lm_mcp.client import LogicMonitorClient
from lm_mcp.exceptions import LMError
from lm_mcp.session import get_session
from lm_mcp.tools import format_response, handle_error


async def save_baseline(
    client: LogicMonitorClient,
    device_id: int,
    device_datasource_id: int,
    instance_id: int,
    baseline_name: str,
    datapoints: str | None = None,
    hours_back: int = 24,
) -> list[TextContent]:
    """Save a metric baseline from historical data.

    Fetches metric data and computes per-datapoint statistics
    (mean, min, max, stddev, sample_count). Stores the baseline
    as a session variable for later comparison.

    Args:
        client: LogicMonitor API client.
        device_id: Device ID.
        device_datasource_id: Device-DataSource ID.
        instance_id: Instance ID.
        baseline_name: Name for the stored baseline.
        datapoints: Comma-separated datapoint names (all if omitted).
        hours_back: Hours of historical data to use.

    Returns:
        Confirmation with baseline summary.
    """
    try:
        now = int(time.time())
        start = now - (hours_back * 3600)

        params: dict = {"start": str(start), "end": str(now)}
        if datapoints:
            params["datapoints"] = datapoints

        path = (
            f"/device/devices/{device_id}"
            f"/devicedatasources/{device_datasource_id}"
            f"/instances/{instance_id}/data"
        )
        resp = await client.get(path, params=params)

        if isinstance(resp, dict) and "errorMessage" in resp:
            # A 200 whose body carries errorMessage without errorCode slips past the
            # client's check; surface it as an API error, not an unhandled crash.
            raise LMError(message=str(resp["errorMessage"]), code="API_ERROR")

        dp_names = resp.get("datapoints", resp.get("dataPoints", []))
        value_rows = resp.get("values", [])

        baseline_data: dict = {}
        for dp_idx, dp_name in enumerate(dp_names):
            raw_values = [
                row[dp_idx] for row in value_rows if dp_idx < len(row) and row[dp_idx] != "No Data"
            ]
            nums = [v for v in raw_values if v is not None]
            if not nums:
                baseline_data[dp_name] = {
                    "mean": None,
                    "min": None,
                    "max": None,
                    "stddev": None,
                    "sample_count": 0,
                }
                continue

            mean = statistics.mean(nums)
            stddev = statistics.stdev(nums) if len(nums) > 1 else 0.0

            baseline_data[dp_name] = {
                "mean": mean,
                "min": min(nums),
                "max": max(nums),
                "stddev": stddev,
                "sample_count": len(nums),
            }

        # Store in session
        session = get_session()
        stored = {
            "device_id": device_id,
            "device_datasource_id": device_datasource_id,
            "instance_id": instance_id,
            "datapoints": baseline_data,
            "hours_back": hours_back,
            "created_at": now,
        }
        session.set_variable(f"baseline_{baseline_name}", stored)

        return format_response(
            {
                "success": True,
                "baseline_name": baseline_name,
                "datapoints": baseline_data,
                "hours_back": hours_back,
                "device_id": device_id,
            }
        )

    except Exception as e:
        return handle_error(e)


async def compare_to_baseline(
    client: LogicMonitorClient,
    baseline_name: str,
    device_id: int | None = None,
    device_datasource_id: int | None = None,
    instance_id: int | None = None,
    hours_back: int = 1,
) -> list[TextContent]:
    """Compare current metrics against a stored baseline.

    Fetches recent metric data and compares against the stored
    baseline statistics. Reports deviation percentage and status
    (normal, elevated, reduced, anomalous) for each datapoint.

    Args:
        client: LogicMonitor API client.
        baseline_name: Name of the stored baseline.
        device_id: Override device ID (uses baseline if omitted).
        device_datasource_id: Override device-datasource ID.
        instance_id: Override instance ID.
        hours_back: Hours of recent data to compare.

    Returns:
        Comparison report with deviation status per datapoint.
    """
    try:
        session = get_session()
        baseline = session.get_variable(f"baseline_{baseline_name}")

        if baseline is None:
            return format_response(
                {
                    "error": True,
                    "message": (
                        f"Baseline '{baseline_name}' not found. "
                        "Use save_baseline to create one first."
                    ),
                }
            )

        # Use baseline IDs unless explicitly overridden
        d_id = device_id if device_id is not None else baseline["device_id"]
        dds_id = (
            device_datasource_id
            if device_datasource_id is not None
            else baseline["device_datasource_id"]
        )
        i_id = instance_id if instance_id is not None else baseline["instance_id"]

        now = int(time.time())
        start = now - (hours_back * 3600)

        path = f"/device/devices/{d_id}/devicedatasources/{dds_id}/instances/{i_id}/data"
        resp = await client.get(
            path,
            params={
                "start": str(start),
                "end": str(now),
            },
        )

        if isinstance(resp, dict) and "errorMessage" in resp:
            # A 200 whose body carries errorMessage without errorCode slips past the
            # client's check; surface it as an API error, not an unhandled crash.
            raise LMError(message=str(resp["errorMessage"]), code="API_ERROR")

        dp_names = resp.get("datapoints", resp.get("dataPoints", []))
        value_rows = resp.get("values", [])
        baseline_dps = baseline.get("datapoints", {})

        comparisons: dict = {}
        for dp_idx, dp_name in enumerate(dp_names):
            if dp_name not in baseline_dps:
                continue

            bl = baseline_dps[dp_name]
            bl_mean = bl.get("mean")
            if bl_mean is None:
                continue

            raw_values = [
                row[dp_idx] for row in value_rows if dp_idx < len(row) and row[dp_idx] != "No Data"
            ]
            nums = [v for v in raw_values if v is not None]
            if not nums:
                comparisons[dp_name] = {
                    "status": "no_data",
                    "baseline_mean": bl_mean,
                    "current_mean": None,
                    "deviation_percent": None,
                }
                continue

            current_mean = statistics.mean(nums)

            # Calculate deviation as percentage of baseline mean
            if bl_mean != 0:
                deviation_pct = abs((current_mean - bl_mean) / bl_mean) * 100
            else:
                deviation_pct = 0.0 if current_mean == 0 else float("inf")

            # Classify deviation
            if deviation_pct <= 20:
                status = "normal"
            elif deviation_pct <= 50:
                status = "elevated" if current_mean > bl_mean else "reduced"
            else:
                status = "anomalous"

            comparisons[dp_name] = {
                "status": status,
                "baseline_mean": bl_mean,
                "current_mean": round(current_mean, 4),
                "deviation_percent": round(deviation_pct, 2),
            }

        return format_response(
            {
                "baseline_name": baseline_name,
                "comparisons": comparisons,
                "hours_compared": hours_back,
            }
        )

    except Exception as e:
        return handle_error(e)
