# Description: HuggingFace local Granite model client for TTM forecasting and NL summaries.
# Description: Drop-in fallback for WatsonxClient when watsonx.ai API is not configured.

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, NoReturn

from lm_mcp.exceptions import LMConnectionError, LMError

logger = logging.getLogger(__name__)


class HuggingFaceClient:
    """Local Granite model inference via HuggingFace transformers.

    Implements the same async interface as WatsonxClient (forecast_ttm and
    summarize) so it can be assigned to _watsonx_client via duck typing.
    Models are lazy-loaded on first call to avoid blocking server startup.
    All inference runs in asyncio.to_thread() to keep the MCP event loop free.
    Heavy imports (torch, transformers, tsfm_public) happen inside methods,
    not at module level, so this module can be imported without them installed.
    """

    def __init__(
        self,
        ttm_model: str = "ibm-granite/granite-timeseries-ttm-r2",
        llm_model: str = "ibm-granite/granite-3.3-2b-instruct",
        device: str = "auto",
        cache_dir: str | None = None,
    ):
        self._ttm_model_name = ttm_model
        self._llm_model_name = llm_model
        self._device = device
        self._cache_dir = cache_dir
        self._ttm_model: Any = None
        self._llm_pipeline: Any = None

    @property
    def llm_model_id(self) -> str:
        """The local language model that writes summaries."""
        return self._llm_model_name

    def _get_ttm_model(self) -> Any:
        """Lazy-load the TTM time series model."""
        if self._ttm_model is None:
            logger.info("Loading TTM model: %s (first call, may download)", self._ttm_model_name)
            from tsfm_public import TinyTimeMixerForPrediction

            kwargs: dict[str, Any] = {}
            if self._cache_dir:
                kwargs["cache_dir"] = self._cache_dir
            self._ttm_model = TinyTimeMixerForPrediction.from_pretrained(
                self._ttm_model_name, **kwargs
            )
        return self._ttm_model

    def _get_llm_pipeline(self) -> Any:
        """Lazy-load the LLM text generation pipeline."""
        if self._llm_pipeline is None:
            logger.info("Loading LLM pipeline: %s (first call, may download)", self._llm_model_name)
            from transformers import pipeline as hf_pipeline

            kwargs: dict[str, Any] = {"model": self._llm_model_name}
            if self._device != "auto":
                kwargs["device"] = self._device
            else:
                kwargs["device_map"] = "auto"
            if self._cache_dir:
                kwargs["model_kwargs"] = {"cache_dir": self._cache_dir}
            self._llm_pipeline = hf_pipeline("text-generation", **kwargs)
        return self._llm_pipeline

    def _run_ttm_forecast(
        self,
        timestamps: list[int],
        values: list[float],
        forecast_periods: int,
    ) -> dict:
        """Synchronous TTM forecast (runs in thread)."""
        import torch

        model = self._get_ttm_model()

        # TTM expects shape (batch, context_length, channels)
        # Use last 512 values (model context window)
        input_values = values[-512:]
        input_tensor = torch.tensor([input_values], dtype=torch.float32).unsqueeze(-1)

        with torch.no_grad():
            output = model(input_tensor)

        # Output: prediction_outputs shape (batch, forecast_length, channels)
        forecast_values = output.prediction_outputs[0, :forecast_periods, 0].tolist()

        return {
            "forecast_values": forecast_values,
            "forecast_count": len(forecast_values),
            "model": self._ttm_model_name,
        }

    def _run_llm_generate(self, prompt: str, max_tokens: int) -> str:
        """Synchronous LLM text generation (runs in thread)."""
        pipe = self._get_llm_pipeline()
        result = pipe(
            prompt,
            max_new_tokens=max_tokens,
            temperature=0.3,
            top_p=0.9,
            repetition_penalty=1.1,
            return_full_text=False,
        )
        return result[0]["generated_text"].strip()

    async def forecast_ttm(
        self,
        timestamps: list[int],
        values: list[float],
        forecast_periods: int = 96,
    ) -> dict:
        """Run Granite TTM time-series forecast locally.

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
            _raise_hf_error(exc, "TTM forecast")

    async def summarize(
        self,
        data: dict | list | str,
        context: str = "",
        max_tokens: int = 500,
    ) -> str:
        """Generate NL summary of structured data via local Granite LLM.

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

        # Truncate large payloads to stay within model context
        if len(data_str) > 8000:
            data_str = data_str[:8000] + "\n... (truncated)"

        prompt = _build_summary_prompt(data_str, context)

        try:
            return await asyncio.to_thread(self._run_llm_generate, prompt, max_tokens)
        except ImportError:
            raise
        except Exception as exc:
            _raise_hf_error(exc, "NL summary")

    async def close(self) -> None:
        """Free model memory."""
        self._ttm_model = None
        self._llm_pipeline = None

    async def __aenter__(self) -> HuggingFaceClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()


def _build_summary_prompt(data_str: str, context: str) -> str:
    """Build the LLM prompt for ITOps analysis summaries.

    Uses the same prompt template as WatsonxClient for consistent output.
    """
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


def _raise_hf_error(exc: Exception, operation: str) -> NoReturn:
    """Map HuggingFace errors to LMError types."""
    exc_str = str(exc)
    exc_type = type(exc).__name__

    if "connect" in exc_str.lower() or "download" in exc_str.lower():
        raise LMConnectionError(
            f"HuggingFace model download failed during {operation}: {exc_str}",
            suggestion="Check network connectivity and model name. "
            "Models are downloaded on first use from huggingface.co.",
        ) from exc
    else:
        raise LMError(
            message=f"HuggingFace {operation} failed: {exc_str}",
            code=f"HF_{exc_type.upper()}",
            suggestion="Check model compatibility and available memory.",
        ) from exc
