# Description: Tests for Audit log MCP tools.
# Description: Validates audit log access functions against the verified API filter behaviour.

import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx

from lm_mcp.auth.bearer import BearerAuth
from lm_mcp.client import LogicMonitorClient

BASE = "https://test.logicmonitor.com/santaba/rest"
URL = f"{BASE}/setting/accesslogs"


@pytest.fixture
def auth():
    """Create a BearerAuth instance for testing."""
    return BearerAuth("test-token")


@pytest.fixture
def client(auth):
    """Create a LogicMonitorClient instance for testing."""
    return LogicMonitorClient(base_url=BASE, auth=auth, timeout=30, api_version=3)


def _row(i, username, desc, t):
    """A synthetic audit row in the shape /setting/accesslogs returns."""
    return {
        "id": f"row{i}",
        "username": username,
        "ip": "192.0.2.10",
        "happenedOn": t,
        "happenedOnLocal": "2026-10-01 10:00:00 UTC",
        "description": desc,
        "sessionId": None,
    }


def _filter(route, n=-1):
    """The filter query parameter of the n-th recorded call."""
    return parse_qs(urlparse(str(route.calls[n].request.url)).query).get("filter", [""])[0]


class TestGetAuditLogs:
    """Tests for get_audit_logs tool."""

    @respx.mock
    async def test_returns_list_with_epoch_timestamp(self, client):
        from lm_mcp.tools.audit import get_audit_logs

        respx.get(URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        _row(
                            1,
                            "user-a@example.com",
                            "user-a@example.com signs in via SAML",
                            1700000100,
                        ),
                        _row(2, "user-a@example.com", "Edit the dashboard Board-A", 1700000000),
                    ],
                    "total": 2,
                },
            )
        )
        data = json.loads((await get_audit_logs(client))[0].text)
        assert data["count"] == 2
        assert data["audit_logs"][0]["happened_on"] == 1700000100
        assert data["audit_logs"][0]["timestamp"] == "2026-10-01 10:00:00 UTC"
        assert data["has_more"] is False

    @respx.mock
    async def test_time_window_filters_on_happened_on(self, client):
        """start/end must filter happenedOn (epoch); happenedOnLocal filters are ignored by LM."""
        from lm_mcp.tools.audit import get_audit_logs

        route = respx.get(URL).mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )
        await get_audit_logs(client, start_time=1700000000, end_time=1700003600)
        flt = _filter(route)
        assert "happenedOn>:1700000000" in flt
        assert "happenedOn<:1700003600" in flt
        assert "happenedOnLocal" not in flt

    @respx.mock
    async def test_username_list_becomes_or_list(self, client):
        from lm_mcp.tools.audit import get_audit_logs

        route = respx.get(URL).mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )
        await get_audit_logs(client, username="user-a@example.com, user-b@example.com")
        assert _filter(route) == 'username:"user-a@example.com"|"user-b@example.com"'

    @respx.mock
    async def test_action_is_a_description_match(self, client):
        from lm_mcp.tools.audit import get_audit_logs

        route = respx.get(URL).mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )
        await get_audit_logs(client, action="Action=Delete")
        flt = _filter(route)
        assert flt == 'description~"Action=Delete"'
        assert "happenedOn:" not in flt

    @respx.mock
    async def test_second_text_filter_applied_after_fetch(self, client):
        from lm_mcp.tools.audit import get_audit_logs

        route = respx.get(URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        _row(
                            1, "u", '"Action=Delete"; "Type=Device"; "Device=device-example-1"', 2
                        ),
                        _row(2, "u", '"Action=Delete"; "Type=SDT"; "Description= Delete SDT"', 1),
                    ],
                    "total": 2,
                },
            )
        )
        data = json.loads(
            (await get_audit_logs(client, action="Action=Delete", resource_type="Type=SDT"))[0].text
        )
        assert _filter(route).count("description~") == 1
        assert [r["id"] for r in data["audit_logs"]] == ["row2"]

    @respx.mock
    async def test_never_sends_negative_operators(self, client):
        from lm_mcp.tools.audit import get_audit_logs

        route = respx.get(URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        _row(1, "System:ActiveDiscovery", '"Action=Update"; "Type=Instance"', 3),
                        _row(2, "System::AutoGroupMembership", " host(id=1,name =x) add to G", 2),
                        _row(3, "user-a@example.com", "Create a dashboard Board-B", 1),
                    ],
                    "total": -4,
                },
            )
        )
        data = json.loads((await get_audit_logs(client, exclude_system=True, limit=3))[0].text)
        flt = _filter(route)
        assert "!" not in flt
        assert [r["username"] for r in data["audit_logs"]] == ["user-a@example.com"]
        assert "system" in data["note"]
        # negative total means more rows exist
        assert data["has_more"] is True
        assert data["next_offset"] == 3

    async def test_offset_beyond_ceiling_is_refused(self, client):
        from lm_mcp.tools.audit import get_audit_logs

        text = (await get_audit_logs(client, offset=9990, limit=50))[0].text
        assert text.startswith("Error:")
        assert "10000" in text

    async def test_overlong_filter_is_refused(self, client):
        from lm_mcp.tools.audit import get_audit_logs

        names = ",".join(f"long-user-example-{i:03d}@subdomain.example.com" for i in range(40))
        text = (await get_audit_logs(client, username=names))[0].text
        assert text.startswith("Error:")
        assert "HTTP 500" in text


class TestGetLoginAudit:
    """Tests for get_login_audit tool."""

    @respx.mock
    async def test_queries_login_wordings_and_ignores_discovery_noise(self, client):
        from lm_mcp.tools.audit import get_login_audit

        def responder(request):
            flt = parse_qs(urlparse(str(request.url)).query).get("filter", [""])[0]
            if "signs in via" in flt:
                return httpx.Response(
                    200,
                    json={
                        "items": [
                            _row(
                                1, "user-a@example.com", "user-a@example.com signs in via SAML", 30
                            )
                        ]
                    },
                )
            if "could not log into the system" in flt:
                return httpx.Response(
                    200,
                    json={
                        "items": [
                            _row(
                                2,
                                "localuser",
                                "localuser could not log into the system - "
                                "Two Factor Authentication failed",
                                20,
                            )
                        ]
                    },
                )
            if "2FA Mode" in flt:
                return httpx.Response(
                    200,
                    json={"items": [_row(3, "localuser", "localuser log in. 2FA Mode : None", 10)]},
                )
            return httpx.Response(200, json={"items": []})

        route = respx.get(URL).mock(side_effect=responder)
        data = json.loads((await get_login_audit(client))[0].text)
        assert [r["status"] for r in data["login_logs"]] == ["success", "failed", "success"]
        assert data["login_logs"][0]["method"] == "SAML"
        assert data["login_logs"][1]["method"] == "2FA"
        assert data["login_logs"][2]["method"] == "Local"
        assert all(
            "Login failed for user" not in _filter(route, i) for i in range(len(route.calls))
        )

    @respx.mock
    async def test_failed_only_queries_failure_wordings_only(self, client):
        from lm_mcp.tools.audit import get_login_audit

        route = respx.get(URL).mock(return_value=httpx.Response(200, json={"items": []}))
        await get_login_audit(client, failed_only=True, username="localuser")
        filters = [_filter(route, i) for i in range(len(route.calls))]
        assert len(filters) == 2
        assert all('username:"localuser"' in f for f in filters)
        assert all("signs in" not in f for f in filters)


class TestGetChangeAudit:
    """Tests for get_change_audit tool."""

    @respx.mock
    async def test_classifies_and_filters_changes(self, client):
        from lm_mcp.tools.audit import get_change_audit

        respx.get(URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        _row(1, "System:ActiveDiscovery", '"Action=Update"; "Type=Instance"', 9),
                        _row(2, "user-a@example.com", "user-a@example.com signs in via SAML", 8),
                        _row(
                            3,
                            "user-a@example.com",
                            '"Action=Delete"; "Type=Device"; "Device=device-example-2 (5)"',
                            7,
                        ),
                        _row(4, "user-a@example.com", "Create a dashboard Board-C", 6),
                        _row(
                            5,
                            "user-a@example.com",
                            "Note (ACK) added to (LMD1) by (user-a@example.com).",
                            5,
                        ),
                        _row(
                            6, "user-b@example.com", "Edit the widget W-1 of dashboard Board-C", 4
                        ),
                    ]
                },
            )
        )
        data = json.loads((await get_change_audit(client))[0].text)
        assert [(r["id"], r["change_type"]) for r in data["change_logs"]] == [
            ("row3", "delete"),
            ("row4", "create"),
            ("row6", "update"),
        ]
        deletes = json.loads((await get_change_audit(client, change_type="delete"))[0].text)
        assert [r["id"] for r in deletes["change_logs"]] == ["row3"]


class TestGetApiTokenAudit:
    """Tests for get_api_token_audit tool."""

    @respx.mock
    async def test_token_id_resolves_to_access_id(self, client):
        from lm_mcp.tools.audit import get_api_token_audit

        respx.get(f"{BASE}/setting/admins/apitokens").mock(
            return_value=httpx.Response(
                200, json={"items": [{"id": 7, "accessId": "AbCdEfGhIjKlMnOpQrSt"}]}
            )
        )
        route = respx.get(URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        _row(
                            1,
                            "AbCdEfGhIjKlMnOpQrSt",
                            "Failed API request: API token AbCdEfGhIjKlMnOpQrSt attempted to "
                            "access path '/santaba/rest/device/devices' with Method: GET. "
                            "Similar case has occurred 12 times "
                            "(Not shown in audit log one by one)",
                            2,
                        ),
                        _row(
                            2,
                            "svc-api",
                            '"Action=Delete"; "Type=Device"; "Device=device-example-3 (9)"; '
                            '"Description= via API token AbCdEfGhIjKlMnOpQrSt"',
                            1,
                        ),
                    ]
                },
            )
        )
        data = json.loads((await get_api_token_audit(client, token_id=7))[0].text)
        assert _filter(route) == 'description~"API token AbCdEfGhIjKlMnOpQrSt"'
        first, second = data["api_token_logs"]
        assert first["kind"] == "rejected" and first["attempts"] == 12
        assert first["path"] == "/santaba/rest/device/devices" and first["method"] == "GET"
        assert second["kind"] == "change via token"
        assert second["access_id"] == "AbCdEfGhIjKlMnOpQrSt"
