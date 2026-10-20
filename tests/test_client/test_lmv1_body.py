# Description: Tests that LMv1 signs the exact body bytes the client puts on the wire.
# Description: Recomputes each signature from the request a respx-faked portal receives.

import base64
import hashlib
import hmac

import pytest
import respx
from httpx import Request, Response

from lm_mcp.auth import create_auth_provider
from lm_mcp.client import LogicMonitorClient
from lm_mcp.config import LMConfig

BASE_URL = "https://test.logicmonitor.com/santaba/rest"
INGEST_URL = "https://test.logicmonitor.com"
ACCESS_ID = "test-access-id"
ACCESS_KEY = "test-access-key"


@pytest.fixture
def lmv1_client(monkeypatch):
    """A client built from LM_ACCESS_ID and LM_ACCESS_KEY the way the transports build it."""
    monkeypatch.delenv("LM_BEARER_TOKEN", raising=False)
    monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
    monkeypatch.setenv("LM_ACCESS_ID", ACCESS_ID)
    monkeypatch.setenv("LM_ACCESS_KEY", ACCESS_KEY)
    config = LMConfig()
    return LogicMonitorClient(
        base_url=config.base_url,
        auth=create_auth_provider(config),
        max_retries=0,
        ingest_url=INGEST_URL,
    )


def _assert_signed_over_wire_body(request: Request, resource_path: str) -> None:
    """Recompute the LMv1 signature over the received body and compare to the header."""
    scheme, _, credentials = request.headers["Authorization"].partition(" ")
    access_id, signature, timestamp = credentials.split(":")
    assert scheme == "LMv1"
    assert access_id == ACCESS_ID

    wire_body = request.content.decode("utf-8")
    message = f"{request.method}{timestamp}{wire_body}{resource_path}"
    hex_digest = hmac.new(
        ACCESS_KEY.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    expected = base64.b64encode(hex_digest.encode("utf-8")).decode("utf-8")
    assert signature == expected, f"signature does not cover wire body {wire_body!r}"


class TestLMv1SignsWireBody:
    """R1.1: the signed string and the transmitted body are the same bytes for every verb."""

    @respx.mock
    async def test_post_signs_wire_body(self, lmv1_client):
        """POST with a populated dict signs exactly the bytes it sends."""
        route = respx.post(f"{BASE_URL}/sdt/sdts").mock(return_value=Response(200, json={"id": 1}))

        async with lmv1_client as client:
            await client.post("/sdt/sdts", json_body={"a": 1, "b": "x"})

        request = route.calls.last.request
        assert request.content == b'{"a":1,"b":"x"}'
        assert request.headers["Content-Type"] == "application/json"
        _assert_signed_over_wire_body(request, "/sdt/sdts")

    @respx.mock
    async def test_patch_non_ascii_signs_wire_body(self, lmv1_client):
        """PATCH with a non-ASCII value signs and sends the same UTF-8 bytes."""
        route = respx.patch(f"{BASE_URL}/device/devices/5").mock(
            return_value=Response(200, json={"id": 5})
        )

        async with lmv1_client as client:
            await client.patch("/device/devices/5", json_body={"description": "ü"})

        request = route.calls.last.request
        assert request.content == '{"description":"ü"}'.encode()
        _assert_signed_over_wire_body(request, "/device/devices/5")

    @respx.mock
    async def test_put_empty_dict_signs_wire_body(self, lmv1_client):
        """PUT with an empty dict sends and signs ``{}``."""
        route = respx.put(f"{BASE_URL}/device/groups/7").mock(
            return_value=Response(200, json={"id": 7})
        )

        async with lmv1_client as client:
            await client.put("/device/groups/7", json_body={})

        request = route.calls.last.request
        assert request.content == b"{}"
        _assert_signed_over_wire_body(request, "/device/groups/7")

    @respx.mock
    async def test_bodiless_get_signs_empty_string(self, lmv1_client):
        """GET sends no body and signs the empty string."""
        route = respx.get(f"{BASE_URL}/alert/alerts").mock(
            return_value=Response(200, json={"items": []})
        )

        async with lmv1_client as client:
            await client.get("/alert/alerts")

        request = route.calls.last.request
        assert request.content == b""
        _assert_signed_over_wire_body(request, "/alert/alerts")

    @respx.mock
    async def test_ingest_post_signs_wire_body(self, lmv1_client):
        """ingest_post signs exactly the bytes it sends to the ingestion host."""
        route = respx.post(f"{INGEST_URL}/rest/log/ingest").mock(
            return_value=Response(202, json={"success": True})
        )

        async with lmv1_client as client:
            await client.ingest_post("/rest/log/ingest", json_body=[{"msg": "ü", "n": 2}])

        request = route.calls.last.request
        assert request.content == '[{"msg":"ü","n":2}]'.encode()
        _assert_signed_over_wire_body(request, "/rest/log/ingest")
