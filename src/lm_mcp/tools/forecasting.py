# Description: Metric forecasting and trend analysis tools for LogicMonitor.
# Description: Provides forecast_metric, detect_change_points, classify_trend, detect_seasonality.

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from mcp.types import TextContent

from lm_mcp.tools import format_response, handle_error
from lm_mcp.tools.stats_helpers import (
    autocorrelation,
    coefficient_of_variation,
    cusum,
    fetch_metric_series,
    holt_winters,
    linear_regression,
    prediction_interval,
)

if TYPE_CHECKING:
    from lm_mcp.client import LogicMonitorClient

logger = logging.getLogger(__name__)


async def forecast_metric(
    client: LogicMonitorClient,
    device_id: int,
    device_datasource_id: int,
    instance_id: int,
    threshold: float,
    datapoints: str | None = None,
    hours_back: int = 168,
    method: str = "auto",
) -> list[TextContent]:
    """Forecast when a metric will breach a threshold.

    Supports linear regression, Holt-Winters (triple exponential smoothing),
    and IBM Granite TTM via watsonx.ai. Auto mode selects the best available
    method based on data characteristics and watsonx availability.

    Args:
        client: LogicMonitor API client.
        device_id: Device ID.
        device_datasource_id: Device-DataSource ID.
        instance_id: Instance ID.
        threshold: Value that, if exceeded, constitutes a breach.
        datapoints: Comma-separated datapoint names (all if omitted).
        hours_back: Hours of historical data for the regression (default: 168).
        method: Forecasting method - auto, linear, holt_winters, or ttm (default: auto).

    Returns:
        Per-datapoint forecast with slope, breach time, trend direction,
        method_used, and confidence_interval; fallback_reason says why linear
        ran when the selected method could not.
    """
    try:
        series = await fetch_metric_series(
            client,
            device_id,
            device_datasource_id,
            instance_id,
            datapoints=datapoints,
            hours_back=hours_back,
        )

        forecasts = {}
        for dp_name, dp_data in series.items():
            values = dp_data["values"]
            timestamps = dp_data["timestamps"]

            if len(values) < 2:
                forecasts[dp_name] = {
                    "status": "insufficient_data",
                    "sample_count": len(values),
                }
                continue

            # Determine method to use
            method_used, fallback_reason = _select_forecast_method(
                method,
                values,
                timestamps,
                hours_back,
            )

            if fallback_reason is not None:
                forecast_result = _forecast_linear_fallback(
                    values,
                    timestamps,
                    threshold,
                    fallback_reason,
                )
            elif method_used == "ttm":
                forecast_result = await _forecast_ttm(
                    values,
                    timestamps,
                    threshold,
                )
            else:
                # Convert timestamps to hours relative to first
                t0 = timestamps[0]
                x_hours = [(t - t0) / 3600.0 for t in timestamps]

                if method_used == "holt_winters":
                    forecast_result = _forecast_holt_winters(
                        values,
                        timestamps,
                        threshold,
                        t0,
                        x_hours,
                    )
                else:
                    forecast_result = _forecast_linear(
                        values,
                        timestamps,
                        threshold,
                        t0,
                        x_hours,
                    )

            forecasts[dp_name] = forecast_result

        return format_response(
            {
                "device_id": device_id,
                "device_datasource_id": device_datasource_id,
                "instance_id": instance_id,
                "hours_back": hours_back,
                "forecasts": forecasts,
            }
        )
    except Exception as e:
        return handle_error(e)


def _select_forecast_method(
    method: str,
    values: list[float],
    timestamps: list[int],
    hours_back: int,
) -> tuple[str, str | None]:
    """Select the forecasting method based on data characteristics.

    Args:
        method: Requested method (auto, linear, holt_winters, ttm).
        values: Time series values.
        timestamps: Epoch timestamps.
        hours_back: Hours of historical data.

    Returns:
        The method to use ('linear', 'holt_winters', or 'ttm') and, when an
        explicitly requested method cannot run, the reason linear runs instead.
    """
    if method == "linear":
        return "linear", None
    if method == "holt_winters":
        return "holt_winters", None
    if method == "ttm":
        if not _is_watsonx_available():
            return "linear", "TTM requested but watsonx is not configured"
        if len(values) < 512:
            return "linear", f"TTM needs at least 512 points; got {len(values)}"
        return "ttm", None

    # Auto selection: prefer TTM when watsonx is configured and enough data
    if _is_watsonx_available() and len(values) >= 512:
        return "ttm", None

    # Fall through to statistical methods
    if hours_back < 168 or len(values) < 48:
        return "linear", None

    # Check autocorrelation at standard periods to detect seasonality
    if len(timestamps) >= 2:
        avg_interval = (timestamps[-1] - timestamps[0]) / (len(timestamps) - 1)
    else:
        avg_interval = 300

    # Check common periods: 12h, 24h
    best_ac = 0.0
    for period_hours in [12, 24]:
        lag = int(period_hours * 3600 / avg_interval) if avg_interval > 0 else 0
        if 1 <= lag < len(values) // 2:
            ac = abs(autocorrelation(values, lag=lag))
            if ac > best_ac:
                best_ac = ac

    # Require strong seasonality and enough data for 2 full seasons
    min_season_len = 12
    if best_ac > 0.5 and len(values) >= 2 * min_season_len:
        return "holt_winters", None

    return "linear", None


def _is_watsonx_available() -> bool:
    """Check if the watsonx client is configured and available."""
    try:
        from lm_mcp.server import get_watsonx_client

        return get_watsonx_client() is not None
    except Exception:
        return False


async def _forecast_ttm(
    values: list[float],
    timestamps: list[int],
    threshold: float,
) -> dict:
    """Run Granite TTM forecast via watsonx.ai.

    Falls back to linear regression if the watsonx call fails.

    Args:
        values: Historical metric values.
        timestamps: Epoch seconds for each value.
        threshold: Breach threshold.

    Returns:
        Forecast result dict matching the standard forecast format.
    """
    try:
        from lm_mcp.server import get_watsonx_client
        from lm_mcp.tools.watsonx import ttm_forecast_helper

        wx = get_watsonx_client()
        if wx is None:
            return _forecast_linear_fallback(
                values,
                timestamps,
                threshold,
                "TTM requested but watsonx is not configured",
            )

        return await ttm_forecast_helper(
            watsonx_client=wx,
            timestamps=timestamps,
            values=values,
            threshold=threshold,
        )
    except Exception as exc:
        logger.warning(
            "watsonx TTM forecast failed; falling back to linear regression: %s",
            exc,
            exc_info=True,
        )
        return _forecast_linear_fallback(
            values,
            timestamps,
            threshold,
            f"watsonx TTM forecast failed: {exc}",
        )


def _forecast_linear_fallback(
    values: list[float],
    timestamps: list[int],
    threshold: float,
    fallback_reason: str,
) -> dict:
    """Linear regression forecast for when the selected method cannot run."""
    t0 = timestamps[0]
    x_hours = [(t - t0) / 3600.0 for t in timestamps]
    result = _forecast_linear(values, timestamps, threshold, t0, x_hours)
    result["fallback_reason"] = fallback_reason
    return result


def _forecast_linear(
    values: list[float],
    timestamps: list[int],
    threshold: float,
    t0: int,
    x_hours: list[float],
) -> dict:
    """Perform linear regression forecast.

    Args:
        values: Time series values.
        timestamps: Epoch timestamps.
        threshold: Breach threshold.
        t0: First timestamp.
        x_hours: Hours relative to t0.

    Returns:
        Forecast result dict.
    """
    slope, intercept, r_squared = linear_regression(x_hours, values)
    current_value = values[-1]

    # Determine trend direction
    if abs(slope) < 1e-10:
        trend = "stable"
    elif slope > 0:
        trend = "increasing"
    else:
        trend = "decreasing"

    # Calculate breach time
    days_until_breach = None
    predicted_breach_epoch = None

    if slope != 0:
        hours_to_breach = (threshold - intercept) / slope
        current_hours = (timestamps[-1] - t0) / 3600.0
        remaining_hours = hours_to_breach - current_hours

        if remaining_hours > 0:
            days_until_breach = round(remaining_hours / 24.0, 2)
            predicted_breach_epoch = int(timestamps[-1] + remaining_hours * 3600)

    # Compute predicted values for confidence interval
    y_predicted = [slope * xh + intercept for xh in x_hours]
    conf_interval = prediction_interval(values, y_predicted)

    return {
        "current_value": round(current_value, 4),
        "threshold": threshold,
        "trend": trend,
        "slope_per_hour": round(slope, 6),
        "intercept": round(intercept, 4),
        "r_squared": round(r_squared, 4),
        "days_until_breach": days_until_breach,
        "predicted_breach_epoch": predicted_breach_epoch,
        "sample_count": len(values),
        "confidence_interval": conf_interval,
        "method_used": "linear",
    }


def _forecast_holt_winters(
    values: list[float],
    timestamps: list[int],
    threshold: float,
    t0: int,
    x_hours: list[float],
) -> dict:
    """Perform Holt-Winters forecast.

    Args:
        values: Time series values.
        timestamps: Epoch timestamps.
        threshold: Breach threshold.
        t0: First timestamp.
        x_hours: Hours relative to t0.

    Returns:
        Forecast result dict.
    """
    # Determine season length from data interval
    if len(timestamps) >= 2:
        avg_interval = (timestamps[-1] - timestamps[0]) / (len(timestamps) - 1)
    else:
        avg_interval = 300

    # Use 24h as default season; fall back to 12 points minimum
    season_length = max(12, int(86400 / avg_interval)) if avg_interval > 0 else 12

    # Ensure we have enough data for the season length
    if len(values) < 2 * season_length:
        season_length = max(4, len(values) // 2)

    try:
        hw_result = holt_winters(
            values,
            season_length=season_length,
            forecast_periods=24,
        )
    except ValueError as exc:
        logger.warning(
            "Holt-Winters forecast failed; falling back to linear regression: %s",
            exc,
            exc_info=True,
        )
        return _forecast_linear_fallback(
            values,
            timestamps,
            threshold,
            f"Holt-Winters failed: {exc}",
        )

    fitted = hw_result["fitted"]
    forecast_vals = hw_result["forecast"]
    current_value = values[-1]

    # Trend from last fitted values
    recent_slope = (fitted[-1] - fitted[0]) / max(len(fitted) - 1, 1) if len(fitted) >= 2 else 0.0

    if abs(recent_slope) < 1e-10:
        trend = "stable"
    elif recent_slope > 0:
        trend = "increasing"
    else:
        trend = "decreasing"

    # Check if forecast breaches threshold
    days_until_breach = None
    predicted_breach_epoch = None
    last_ts = timestamps[-1]

    if len(timestamps) >= 2:
        interval = (timestamps[-1] - timestamps[0]) / (len(timestamps) - 1)
    else:
        interval = 300

    for i, fv in enumerate(forecast_vals):
        if fv > threshold:
            hours_to_breach = (i + 1) * interval / 3600.0
            days_until_breach = round(hours_to_breach / 24.0, 2)
            predicted_breach_epoch = int(last_ts + (i + 1) * interval)
            break

    # Confidence interval from fitted vs actual
    conf_interval = prediction_interval(values, fitted)

    return {
        "current_value": round(current_value, 4),
        "threshold": threshold,
        "trend": trend,
        "slope_per_hour": round(recent_slope, 6),
        "days_until_breach": days_until_breach,
        "predicted_breach_epoch": predicted_breach_epoch,
        "sample_count": len(values),
        "season_length": season_length,
        "forecast_values": forecast_vals[:24],
        "confidence_interval": conf_interval,
        "method_used": "holt_winters",
    }


async def detect_change_points(
    client: LogicMonitorClient,
    device_id: int,
    device_datasource_id: int,
    instance_id: int,
    datapoints: str | None = None,
    hours_back: int = 24,
    sensitivity: float = 1.0,
) -> list[TextContent]:
    """Detect regime shifts in metric data using the CUSUM algorithm.

    Identifies points where the mean value changes significantly,
    indicating a state change in the monitored resource.

    Args:
        client: LogicMonitor API client.
        device_id: Device ID.
        device_datasource_id: Device-DataSource ID.
        instance_id: Instance ID.
        datapoints: Comma-separated datapoint names (all if omitted).
        hours_back: Hours of data to analyze (default: 24).
        sensitivity: Detection sensitivity (lower = more sensitive, default: 1.0).

    Returns:
        Per-datapoint list of change points with timestamps and direction.
    """
    try:
        series = await fetch_metric_series(
            client,
            device_id,
            device_datasource_id,
            instance_id,
            datapoints=datapoints,
            hours_back=hours_back,
        )

        results = {}
        total_change_points = 0
        for dp_name, dp_data in series.items():
            values = dp_data["values"]
            timestamps = dp_data["timestamps"]

            raw_points = cusum(values, sensitivity=sensitivity)

            # Map indices back to timestamps
            change_points = []
            for cp in raw_points:
                idx = cp["index"]
                ts = timestamps[idx] if idx < len(timestamps) else None
                change_points.append(
                    {
                        "timestamp": ts,
                        "direction": cp["direction"],
                        "magnitude": cp["magnitude"],
                        "index": idx,
                    }
                )

            total_change_points += len(change_points)
            results[dp_name] = {
                "change_point_count": len(change_points),
                "change_points": change_points,
                "sample_count": len(values),
            }

        return format_response(
            {
                "device_id": device_id,
                "device_datasource_id": device_datasource_id,
                "instance_id": instance_id,
                "hours_back": hours_back,
                "sensitivity": sensitivity,
                "total_change_points": total_change_points,
                "datapoints": results,
            }
        )
    except Exception as e:
        return handle_error(e)


async def classify_trend(
    client: LogicMonitorClient,
    device_id: int,
    device_datasource_id: int,
    instance_id: int,
    datapoints: str | None = None,
    hours_back: int = 24,
) -> list[TextContent]:
    """Classify metric trends as stable, increasing, decreasing, cyclic, or volatile.

    Combines linear regression slope, coefficient of variation, and
    autocorrelation to categorize each datapoint's behavior.

    Args:
        client: LogicMonitor API client.
        device_id: Device ID.
        device_datasource_id: Device-DataSource ID.
        instance_id: Instance ID.
        datapoints: Comma-separated datapoint names (all if omitted).
        hours_back: Hours of data to analyze (default: 24).

    Returns:
        Per-datapoint classification with confidence and supporting metrics.
    """
    try:
        series = await fetch_metric_series(
            client,
            device_id,
            device_datasource_id,
            instance_id,
            datapoints=datapoints,
            hours_back=hours_back,
        )

        classifications = {}
        for dp_name, dp_data in series.items():
            values = dp_data["values"]
            timestamps = dp_data["timestamps"]

            if len(values) < 2:
                classifications[dp_name] = {
                    "classification": "insufficient_data",
                    "confidence": 0.0,
                    "sample_count": len(values),
                }
                continue

            # Compute metrics for classification
            cv = coefficient_of_variation(values)

            t0 = timestamps[0] if timestamps else 0
            x_hours = [(t - t0) / 3600.0 for t in timestamps]
            slope, _intercept, r_squared = linear_regression(x_hours, values)

            # Autocorrelation at ~24h lag (use lag that represents 24h)
            # Estimate sample interval from timestamps
            if len(timestamps) >= 2:
                avg_interval = (timestamps[-1] - timestamps[0]) / (len(timestamps) - 1)
                lag_24h = max(1, int(86400 / avg_interval)) if avg_interval > 0 else 1
            else:
                lag_24h = 1
            autocorr = autocorrelation(values, lag=lag_24h)

            # Classification logic
            if cv > 0.5:
                classification = "volatile"
                confidence = min(1.0, cv)
            elif abs(autocorr) > 0.7:
                classification = "cyclic"
                confidence = abs(autocorr)
            elif r_squared > 0.5 and slope > 0:
                classification = "increasing"
                confidence = r_squared
            elif r_squared > 0.5 and slope < 0:
                classification = "decreasing"
                confidence = r_squared
            else:
                classification = "stable"
                confidence = max(0.0, 1.0 - cv)

            classifications[dp_name] = {
                "classification": classification,
                "confidence": round(confidence, 4),
                "slope_per_hour": round(slope, 6),
                "volatility_index": round(cv, 4),
                "autocorrelation_24h": round(autocorr, 4),
                "r_squared": round(r_squared, 4),
                "sample_count": len(values),
            }

        return format_response(
            {
                "device_id": device_id,
                "device_datasource_id": device_datasource_id,
                "instance_id": instance_id,
                "hours_back": hours_back,
                "classifications": classifications,
            }
        )
    except Exception as e:
        return handle_error(e)


async def detect_seasonality(
    client: LogicMonitorClient,
    device_id: int,
    device_datasource_id: int,
    instance_id: int,
    datapoints: str | None = None,
    hours_back: int = 168,
) -> list[TextContent]:
    """Detect periodic patterns in metric data using autocorrelation.

    Computes autocorrelation at standard period lags (1h, 4h, 12h, 24h, 168h)
    to identify seasonal patterns. Also bins values by hour-of-day to find
    peak activity hours.

    Args:
        client: LogicMonitor API client.
        device_id: Device ID.
        device_datasource_id: Device-DataSource ID.
        instance_id: Instance ID.
        datapoints: Comma-separated datapoint names (all if omitted).
        hours_back: Hours of data to analyze (default: 168 = 1 week).

    Returns:
        Per-datapoint seasonality analysis with dominant period and peak hours.
    """
    try:
        series = await fetch_metric_series(
            client,
            device_id,
            device_datasource_id,
            instance_id,
            datapoints=datapoints,
            hours_back=hours_back,
        )

        results = {}
        for dp_name, dp_data in series.items():
            values = dp_data["values"]
            timestamps = dp_data["timestamps"]

            if len(values) < 4:
                results[dp_name] = {
                    "is_seasonal": False,
                    "status": "insufficient_data",
                    "sample_count": len(values),
                }
                continue

            # Estimate sample interval
            if len(timestamps) >= 2:
                avg_interval = (timestamps[-1] - timestamps[0]) / (len(timestamps) - 1)
            else:
                avg_interval = 300  # Default 5-min

            # Standard period lags in hours
            period_hours = [1, 4, 12, 24, 168]
            correlations = {}

            for ph in period_hours:
                lag = int(ph * 3600 / avg_interval) if avg_interval > 0 else 0
                # Skip lags where we have insufficient data
                if lag < 1 or lag >= len(values) // 2:
                    continue
                ac = autocorrelation(values, lag=lag)
                correlations[f"{ph}h"] = round(ac, 4)

            # Find dominant period
            if correlations:
                dominant_period = max(correlations, key=correlations.get)
                max_autocorr = correlations[dominant_period]
                is_seasonal = max_autocorr > 0.5
            else:
                dominant_period = None
                max_autocorr = 0.0
                is_seasonal = False

            # Bin values by hour-of-day to find peak hours
            hourly_bins: dict[int, list[float]] = {}
            for val, ts in zip(values, timestamps, strict=True):
                hour = (ts % 86400) // 3600
                hourly_bins.setdefault(hour, []).append(val)

            peak_hours = []
            if hourly_bins:
                hourly_means = {h: sum(v) / len(v) for h, v in hourly_bins.items()}
                overall_mean = sum(values) / len(values)
                peak_hours = sorted([h for h, m in hourly_means.items() if m > overall_mean])

            results[dp_name] = {
                "is_seasonal": is_seasonal,
                "dominant_period": dominant_period,
                "max_autocorrelation": max_autocorr,
                "correlations": correlations,
                "peak_hours": peak_hours,
                "sample_count": len(values),
            }

        return format_response(
            {
                "device_id": device_id,
                "device_datasource_id": device_datasource_id,
                "instance_id": instance_id,
                "hours_back": hours_back,
                "seasonality": results,
            }
        )
    except Exception as e:
        return handle_error(e)
