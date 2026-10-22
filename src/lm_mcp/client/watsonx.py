# Description: IBM watsonx.ai API client for Granite model inference.
# Description: Wraps the ibm-watsonx-ai SDK with async support for time series and text generation.

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, NoReturn

from lm_mcp.exceptions import (
    AuthenticationError,
    LMConnectionError,
    LMError,
)

logger = logging.getLogger(__name__)

# Granite model IDs for watsonx.ai inference
TTM_MODEL_ID = "ibm/granite-ttm-512-96-r2"
LLM_MODEL_ID = "ibm/granite-4-h-small"


class WatsonxClient:
    """Async-compatible client for IBM watsonx.ai API.

    The ibm-watsonx-ai SDK is synchronous, so all inference calls run
    in asyncio.to_thread() to avoid blocking the MCP event loop.
    SDK imports happen inside __init__ so the module can be imported
    without the SDK installed.
    """

    def __init__(
        self,
        api_key: str,
        url: str,
        project_id: str,
        timeout: int = 60,
    ):
        try:
            from ibm_watsonx_ai import APIClient, Credentials
        except ImportError as exc:
            raise ImportError(
                "ibm-watsonx-ai is required for watsonx integration. "
                "Install with: uv add 'lm-mcp[ibm]'"
            ) from exc

        self._credentials = Credentials(api_key=api_key, url=url)
        self._api_client = APIClient(credentials=self._credentials, project_id=project_id)
        self._project_id = project_id
        self._timeout = timeout
        self._ts_model: Any = None
        self._llm_model: Any = None

    def _get_ts_model(self) -> Any:
        """Lazy-initialize the time series model."""
        if self._ts_model is None:
            from ibm_watsonx_ai.foundation_models.inference.ts_model_inference import (
                TSModelInference,
            )

            self._ts_model = TSModelInference(
                model_id=TTM_MODEL_ID,
                api_client=self._api_client,
            )
        return self._ts_model

    def _get_llm_model(self) -> Any:
        """Lazy-initialize the language model."""
        if self._llm_model is None:
            from ibm_watsonx_ai.foundation_models import ModelInference

            self._llm_model = ModelInference(
                model_id=LLM_MODEL_ID,
                api_client=self._api_client,
                params={
                    "max_new_tokens": 500,
                    "temperature": 0.3,
                    "top_p": 0.9,
                    "repetition_penalty": 1.1,
                },
            )
        return self._llm_model

    def _run_ttm_forecast(
        self,
        timestamps: list[int],
        values: list[float],
        forecast_periods: int,
    ) -> dict:
        """Synchronous TTM forecast call (runs in thread)."""
        import pandas as pd
        from ibm_watsonx_ai.foundation_models.schema import (
            TSForecastParameters,
        )

        # SDK requires string timestamps, not pandas Timestamps (serialization bug)
        dates = (
            pd.date_range(
                start=pd.to_datetime(timestamps[0], unit="s", utc=True),
                periods=len(timestamps),
                freq=f"{max(1, (timestamps[-1] - timestamps[0]) // max(1, len(timestamps) - 1))}s",
            )
            .strftime("%Y-%m-%dT%H:%M:%SZ")
            .tolist()
        )
        df = pd.DataFrame({"timestamp": dates, "value": values})

        params = TSForecastParameters(
            timestamp_column="timestamp",
            target_columns=["value"],
        )

        result = self._get_ts_model().forecast(data=df, params=params)

        # SDK returns dict: {results: [{value: [...]}], input_data_points, output_data_points}
        forecast_values = result["results"][0]["value"]

        return {
            "forecast_values": forecast_values,
            "forecast_count": len(forecast_values),
            "model": TTM_MODEL_ID,
        }

    def _run_llm_generate(self, prompt: str, max_tokens: int) -> str:
        """Synchronous LLM generation call (runs in thread)."""
        model = self._get_llm_model()
        result = model.generate_text(prompt=prompt)
        return result

    async def forecast_ttm(
        self,
        timestamps: list[int],
        values: list[float],
        forecast_periods: int = 96,
    ) -> dict:
        """Run Granite TTM time-series forecast.

        Args:
            timestamps: Epoch seconds for historical data points.
            values: Metric values corresponding to timestamps.
            forecast_periods: Number of future periods to forecast.

        Returns:
            Dict with forecast_values list and model metadata.
        """
        try:
            return await asyncio.to_thread(
                self._run_ttm_forecast, timestamps, values, forecast_periods
            )
        except ImportError:
            raise
        except Exception as exc:
            _raise_watsonx_error(exc, "TTM forecast")

    async def summarize(
        self,
        data: dict | list | str,
        context: str = "",
        max_tokens: int = 500,
    ) -> str:
        """Generate NL summary of structured data via Granite LLM.

        Args:
            data: Structured data to summarize (dict, list, or string).
            context: Additional context for the summary (e.g., tool name).
            max_tokens: Maximum tokens in the generated summary.

        Returns:
            Plain-English summary string.
        """
        if isinstance(data, (dict, list)):
            data_str = json.dumps(data, indent=2, default=str)
        else:
            data_str = str(data)

        # Truncate large payloads to stay within token limits
        if len(data_str) > 8000:
            data_str = data_str[:8000] + "\n... (truncated)"

        prompt = _build_summary_prompt(data_str, context)

        try:
            return await asyncio.to_thread(self._run_llm_generate, prompt, max_tokens)
        except ImportError:
            raise
        except Exception as exc:
            _raise_watsonx_error(exc, "NL summary")

    async def close(self) -> None:
        """Clean up client resources."""
        self._ts_model = None
        self._llm_model = None

    async def __aenter__(self) -> WatsonxClient:
        """Enter async context manager."""
        return self

    async def __aexit__(self, *args) -> None:
        """Exit async context manager."""
        await self.close()


def _build_summary_prompt(data_str: str, context: str) -> str:
    """Build the LLM prompt for ITOps analysis summaries."""
    context_line = f"Tool: {context}\n" if context else ""
    return (
        "You are an IT operations analyst writing shift handoff notes. "
        "Summarize the following monitoring data in 2-4 concise sentences. "
        "Focus on: what is happening, severity, affected resources, and "
        "recommended next steps. Use plain English, no JSON. Be direct.\n\n"
        f"{context_line}"
        f"Data:\n{data_str}\n\n"
        "Summary:"
    )


def _raise_watsonx_error(exc: Exception, operation: str) -> NoReturn:
    """Map watsonx SDK exceptions to LMError types."""
    exc_str = str(exc)
    exc_type = type(exc).__name__

    if "401" in exc_str or "Unauthorized" in exc_str:
        raise AuthenticationError(
            f"watsonx.ai {operation} failed: {exc_str}",
            suggestion="Check your WATSONX_API_KEY. Generate a new key at "
            "https://cloud.ibm.com/iam/apikeys",
        ) from exc
    elif "connect" in exc_str.lower() or "timeout" in exc_str.lower():
        raise LMConnectionError(f"watsonx.ai unreachable during {operation}: {exc_str}") from exc
    else:
        raise LMError(
            message=f"watsonx.ai {operation} failed: {exc_str}",
            code=f"WATSONX_{exc_type.upper()}",
            suggestion="Check watsonx.ai service status and your project configuration.",
        ) from exc
