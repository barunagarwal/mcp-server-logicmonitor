# Description: Tests for watsonx tool helpers and standalone watsonx_summarize tool.
# Description: Mocks WatsonxClient to validate tool output format and error handling.

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.watsonx_sdk import real_watsonx_client


class TestWatsonxSummarizeTool:
    """Tests for the watsonx_summarize standalone MCP tool."""

    @pytest.mark.asyncio
    async def test_returns_formatted_response(self):
        """watsonx_summarize returns TextContent with the summary and the watsonx model id."""
        from lm_mcp.client.watsonx import LLM_MODEL_ID
        from lm_mcp.tools.watsonx import watsonx_summarize

        client = real_watsonx_client()
        with patch("ibm_watsonx_ai.foundation_models.ModelInference", autospec=True) as model_cls:
            model_cls.return_value.generate_text.return_value = (
                "Portal is healthy. No action needed."
            )
            result = await watsonx_summarize(
                client,
                data='{"noise_score": 12}',
                context="portal overview",
            )

        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["summary"] == "Portal is healthy. No action needed."
        assert data["model"] == LLM_MODEL_ID

    @pytest.mark.asyncio
    async def test_huggingface_fallback_reports_its_own_model(self):
        """R4.5: a summary the HuggingFace fallback wrote names the local model, not IBM's."""
        from lm_mcp.client.huggingface import HuggingFaceClient
        from lm_mcp.tools.watsonx import watsonx_summarize

        client = HuggingFaceClient(llm_model="ibm-granite/granite-3.3-2b-instruct")
        client._llm_pipeline = MagicMock(return_value=[{"generated_text": "All quiet."}])

        result = await watsonx_summarize(client, data='{"alerts": []}')

        data = json.loads(result[0].text)
        assert data["summary"] == "All quiet."
        assert data["model"] == "ibm-granite/granite-3.3-2b-instruct"

    @pytest.mark.asyncio
    async def test_handles_error_gracefully(self):
        """watsonx_summarize returns error response on failure."""
        from lm_mcp.tools.watsonx import watsonx_summarize

        mock_client = AsyncMock()
        mock_client.summarize = AsyncMock(side_effect=RuntimeError("API down"))

        result = await watsonx_summarize(mock_client, data='{"alerts": []}')

        assert len(result) == 1
        assert "error" in result[0].text.lower() or "API down" in result[0].text

    @pytest.mark.asyncio
    async def test_parses_json_string_input(self):
        """watsonx_summarize parses JSON string data before sending to client."""
        from lm_mcp.tools.watsonx import watsonx_summarize

        mock_client = AsyncMock()
        mock_client.summarize = AsyncMock(return_value="Summary text.")

        await watsonx_summarize(mock_client, data='{"key": "value"}')

        call_args = mock_client.summarize.call_args
        assert isinstance(call_args[1].get("data") or call_args[0][0], dict)


class TestTtmForecastHelper:
    """Tests for the ttm_forecast_helper internal function."""

    @pytest.mark.asyncio
    async def test_returns_forecast_structure(self):
        """ttm_forecast_helper returns dict with expected fields."""
        from lm_mcp.tools.watsonx import ttm_forecast_helper

        mock_client = AsyncMock()
        mock_client.forecast_ttm = AsyncMock(
            return_value={
                "forecast_values": [50.0, 55.0, 60.0, 65.0],
                "forecast_count": 4,
                "model": "ibm/granite-ttm-512-96-r2",
            }
        )

        result = await ttm_forecast_helper(
            watsonx_client=mock_client,
            timestamps=[1000, 1300, 1600, 1900],
            values=[40.0, 42.0, 44.0, 46.0],
            threshold=90.0,
        )

        assert result["method_used"] == "ttm"
        assert result["current_value"] == 46.0
        assert result["threshold"] == 90.0
        assert result["breach_detected"] is False
        assert "forecast_values" in result

    @pytest.mark.asyncio
    async def test_detects_breach(self):
        """ttm_forecast_helper sets breach_detected when forecast exceeds threshold."""
        from lm_mcp.tools.watsonx import ttm_forecast_helper

        mock_client = AsyncMock()
        mock_client.forecast_ttm = AsyncMock(
            return_value={
                "forecast_values": [85.0, 88.0, 92.0, 95.0],
                "forecast_count": 4,
                "model": "ibm/granite-ttm-512-96-r2",
            }
        )

        result = await ttm_forecast_helper(
            watsonx_client=mock_client,
            timestamps=[1000, 1300, 1600, 1900],
            values=[80.0, 82.0, 84.0, 86.0],
            threshold=90.0,
        )

        assert result["breach_detected"] is True
        assert result["days_until_breach"] is not None
        assert result["max_forecast"] == 95.0

    @pytest.mark.asyncio
    async def test_handles_empty_values(self):
        """ttm_forecast_helper handles empty input gracefully."""
        from lm_mcp.tools.watsonx import ttm_forecast_helper

        mock_client = AsyncMock()
        mock_client.forecast_ttm = AsyncMock(
            return_value={
                "forecast_values": [],
                "forecast_count": 0,
                "model": "ibm/granite-ttm-512-96-r2",
            }
        )

        result = await ttm_forecast_helper(
            watsonx_client=mock_client,
            timestamps=[],
            values=[],
            threshold=90.0,
        )

        assert result["breach_detected"] is False
        assert result["current_value"] == 0.0


class TestNlSummarizeHelper:
    """Tests for the nl_summarize_helper internal function."""

    @pytest.mark.asyncio
    async def test_calls_client_with_context(self):
        """nl_summarize_helper passes workflow name as context."""
        from lm_mcp.tools.watsonx import nl_summarize_helper

        mock_client = AsyncMock()
        mock_client.summarize = AsyncMock(return_value="Triage summary.")

        result = await nl_summarize_helper(
            watsonx_client=mock_client,
            report_data={"noise_score": 42},
            workflow_name="triage",
        )

        assert result == "Triage summary."
        mock_client.summarize.assert_called_once()
        call_kwargs = mock_client.summarize.call_args[1]
        assert call_kwargs["context"] == "triage report"


class TestEstimateInterval:
    """Tests for the _estimate_interval helper."""

    def test_estimates_from_timestamps(self):
        from lm_mcp.tools.watsonx import _estimate_interval

        timestamps = [1000, 1300, 1600, 1900, 2200]
        assert _estimate_interval(timestamps) == 300

    def test_single_timestamp_returns_default(self):
        from lm_mcp.tools.watsonx import _estimate_interval

        assert _estimate_interval([1000]) == 300

    def test_empty_returns_default(self):
        from lm_mcp.tools.watsonx import _estimate_interval

        assert _estimate_interval([]) == 300
