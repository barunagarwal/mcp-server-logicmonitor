# Description: Builds a real WatsonxClient for tests without reaching IBM Cloud.
# Description: Patches only the SDK's credential and API client classes the constructor calls.

from unittest.mock import MagicMock, patch


def real_watsonx_client():
    """A WatsonxClient built through its constructor with the SDK's client classes patched."""
    from lm_mcp.client.watsonx import WatsonxClient

    with (
        patch("ibm_watsonx_ai.Credentials", return_value=MagicMock()),
        patch("ibm_watsonx_ai.APIClient", return_value=MagicMock()),
    ):
        return WatsonxClient(
            api_key="test-key",
            url="https://us-south.ml.cloud.ibm.com",
            project_id="proj-123",
        )
