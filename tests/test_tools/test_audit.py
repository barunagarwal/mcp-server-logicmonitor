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
        # action goes to the API; resource_type is the one matched after the fetch
        assert 'description~"Action=Delete"' in _filter(route)
        assert "'Type=SDT' was matched after the fetch" in data["note"]
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
        # One query per portal login wording; none of them is the "Login failed for user"
        # text that Active Discovery quotes from monitored databases.
        from lm_mcp.tools.audit import LOGIN_PATTERNS

        sent = [_filter(route, i) for i in range(len(route.calls))]
        assert sent == [f'description~"{pattern}"' for pattern, _ in LOGIN_PATTERNS]
        assert data["has_more"] is False

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


class TestQueryErrors:
    """Only the two refused-before-sending limits are reported as INVALID_REQUEST."""

    @respx.mock
    @pytest.mark.parametrize(
        "tool", ["get_audit_logs", "get_login_audit", "get_change_audit", "get_api_token_audit"]
    )
    async def test_malformed_body_reaches_handle_error(self, client, caplog, tool):
        """A JSONDecodeError (a ValueError) is logged by handle_error, not reported as a limit."""
        from lm_mcp.tools import audit

        respx.get(URL).mock(
            return_value=httpx.Response(
                200, content=b"<html>not json", headers={"content-type": "application/json"}
            )
        )
        with caplog.at_level("ERROR", logger="lm_mcp.tools"):
            text = (await getattr(audit, tool)(client))[0].text

        assert text.startswith("Error:")
        assert "unhandled error in tool handler" in caplog.text

    async def test_limit_refusal_is_not_logged_as_unhandled(self, client, caplog):
        from lm_mcp.tools.audit import get_audit_logs

        with caplog.at_level("ERROR", logger="lm_mcp.tools"):
            text = (await get_audit_logs(client, offset=9990, limit=50))[0].text

        assert "10000" in text
        assert "unhandled error in tool handler" not in caplog.text


class TestSystemActors:
    """System-actor exclusion is case-sensitive and never hides a user the caller named."""

    @pytest.mark.parametrize(
        ("username", "is_system"),
        [
            ("System:ActiveDiscovery", True),
            ("System::AutoGroupMembership", True),
            ("System.NetScan", True),
            ("LogicMonitor Internal", True),
            ("AZURE auto-delete", True),
            ("system.admin@example.com", False),
            ("System.Admin@example.com", False),
            ("System:user-x@example.com", False),
            ("System: Admin", False),
            ("SYSTEM:ActiveDiscovery", False),
            ("user-a@example.com", False),
        ],
    )
    def test_system_actor_match_is_case_sensitive(self, username, is_system):
        from lm_mcp.tools.audit import SYSTEM_ACTOR

        assert bool(SYSTEM_ACTOR.match(username)) is is_system

    @respx.mock
    async def test_audit_logs_keeps_user_that_looks_like_a_system_prefix(self, client):
        from lm_mcp.tools.audit import get_audit_logs

        respx.get(URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        _row(1, "System:ActiveDiscovery", '"Action=Update"', 3),
                        _row(2, "system.admin@example.com", "Create a dashboard Board-A", 2),
                    ],
                    "total": 2,
                },
            )
        )
        data = json.loads((await get_audit_logs(client, exclude_system=True))[0].text)
        assert [r["username"] for r in data["audit_logs"]] == ["system.admin@example.com"]

    @respx.mock
    async def test_audit_logs_named_system_user_is_not_excluded(self, client):
        from lm_mcp.tools.audit import get_audit_logs

        route = respx.get(URL).mock(
            return_value=httpx.Response(
                200,
                json={"items": [_row(1, "System:ActiveDiscovery", '"Action=Update"', 3)]},
            )
        )
        data = json.loads(
            (await get_audit_logs(client, username="System:ActiveDiscovery", exclude_system=True))[
                0
            ].text
        )
        assert _filter(route) == 'username:"System:ActiveDiscovery"'
        assert [r["id"] for r in data["audit_logs"]] == ["row1"]
        assert "note" not in data

    @respx.mock
    async def test_change_audit_named_system_user_returns_its_changes(self, client):
        from lm_mcp.tools.audit import get_change_audit

        respx.get(URL).mock(
            return_value=httpx.Response(
                200,
                json={"items": [_row(1, "System:ActiveDiscovery", '"Action=Update"', 3)]},
            )
        )
        data = json.loads(
            (await get_change_audit(client, username="System:ActiveDiscovery"))[0].text
        )
        assert [(r["id"], r["change_type"]) for r in data["change_logs"]] == [("row1", "update")]

    @respx.mock
    async def test_change_audit_still_excludes_system_actors_by_default(self, client):
        from lm_mcp.tools.audit import get_change_audit

        respx.get(URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        _row(1, "System:ActiveDiscovery", '"Action=Update"', 3),
                        _row(2, "system.admin@example.com", '"Action=Delete"', 2),
                    ]
                },
            )
        )
        data = json.loads((await get_change_audit(client))[0].text)
        assert [r["id"] for r in data["change_logs"]] == ["row2"]
        assert "total" not in data


class TestApiTokenAuditLookup:
    """token_id lookups check the id, and a caller's access_id is sanitized like other values."""

    @respx.mock
    async def test_token_id_that_does_not_match_is_not_found(self, client):
        from lm_mcp.tools.audit import get_api_token_audit

        respx.get(f"{BASE}/setting/admins/apitokens").mock(
            return_value=httpx.Response(
                200, json={"items": [{"id": 8, "accessId": "ZyXwVuTsRqPoNmLkJiHg"}]}
            )
        )
        logs = respx.get(URL).mock(return_value=httpx.Response(200, json={"items": []}))

        text = (await get_api_token_audit(client, token_id=7))[0].text

        assert "API token 7 not found" in text
        assert not logs.called

    @respx.mock
    async def test_access_id_goes_through_sanitize_filter_value(self, client):
        from lm_mcp.tools.audit import get_api_token_audit

        route = respx.get(URL).mock(return_value=httpx.Response(200, json={"items": []}))

        data = json.loads((await get_api_token_audit(client, access_id="AbCd*EfGh?IjKl"))[0].text)

        assert _filter(route) == 'description~"API token AbCdEfGhIjKl"'
        assert "wildcard" in data["note"].lower()


class TestChangeTypeValidation:
    async def test_unknown_change_type_is_refused_before_any_call(self, client):
        """A typo such as "updated" would otherwise match nothing and read as no changes."""
        from lm_mcp.tools.audit import get_change_audit

        with respx.mock(assert_all_called=False) as mock:
            route = mock.get(URL).mock(return_value=httpx.Response(200, json={"items": []}))
            text = (await get_change_audit(client, change_type="updated"))[0].text

        assert text.startswith("Error: change_type must be one of create, update, delete, import")
        assert not route.called

    @respx.mock
    @pytest.mark.parametrize("change_type", ["create", "UPDATE", " delete ", "import"])
    async def test_known_change_types_are_accepted(self, client, change_type):
        from lm_mcp.tools.audit import get_change_audit

        respx.get(URL).mock(return_value=httpx.Response(200, json={"items": []}))
        data = json.loads((await get_change_audit(client, change_type=change_type))[0].text)
        assert data["change_logs"] == []


class TestPaging:
    """Paging follows the rows the API returned, whatever the filters after the fetch drop."""

    @respx.mock
    async def test_positive_total_with_more_rows_reads_has_more(self, client):
        from lm_mcp.tools.audit import get_audit_logs

        respx.get(URL).mock(
            return_value=httpx.Response(
                200, json={"items": [_row(1, "user-a@example.com", "x", 1)], "total": 100}
            )
        )
        data = json.loads((await get_audit_logs(client, limit=10, offset=0))[0].text)
        assert (data["total"], data["count"], data["offset"]) == (100, 1, 0)
        assert data["has_more"] is True

    @respx.mock
    @pytest.mark.parametrize(("total", "has_more"), [(3, False), (10, True)])
    async def test_dropped_rows_do_not_change_paging(self, client, total, has_more):
        from lm_mcp.tools.audit import get_audit_logs

        respx.get(URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        _row(1, "System:ActiveDiscovery", '"Action=Update"', 3),
                        _row(2, "user-a@example.com", "Create a dashboard Board-A", 2),
                        _row(3, "user-b@example.com", "Create a dashboard Board-B", 1),
                    ],
                    "total": total,
                },
            )
        )
        data = json.loads((await get_audit_logs(client, exclude_system=True, limit=3))[0].text)
        assert data["count"] == 2
        assert data["total"] == total
        assert data["has_more"] is has_more
        assert data["next_offset"] == 3

    @respx.mock
    @pytest.mark.parametrize(
        "body",
        [
            {"items": [_row(i, "user-a@example.com", "x", i) for i in range(3)]},
            {"items": [_row(i, "user-a@example.com", "x", i) for i in range(3)], "total": None},
            {"items": [_row(i, "user-a@example.com", "x", i) for i in range(3)], "total": "5"},
        ],
        ids=["missing", "null", "string"],
    )
    async def test_full_page_without_an_integer_total_reads_has_more(self, client, body):
        from lm_mcp.tools.audit import get_audit_logs

        respx.get(URL).mock(return_value=httpx.Response(200, json=body))
        data = json.loads((await get_audit_logs(client, limit=3))[0].text)
        assert data["has_more"] is True
        assert data["total"] == 4
        assert "lower bound" in data["total_note"]

    @respx.mock
    async def test_short_page_without_a_total_is_complete(self, client):
        from lm_mcp.tools.audit import get_audit_logs

        respx.get(URL).mock(
            return_value=httpx.Response(
                200, json={"items": [_row(1, "user-a@example.com", "x", 1)]}
            )
        )
        data = json.loads((await get_audit_logs(client, limit=3, offset=6))[0].text)
        assert (data["total"], data["has_more"]) == (7, False)

    @respx.mock
    async def test_wildcard_only_username_keeps_system_exclusion(self, client):
        """username="*" sends no username clause, so it names nobody and exclusion stays on."""
        from lm_mcp.tools.audit import get_audit_logs, get_change_audit

        route = respx.get(URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        _row(1, "System:ActiveDiscovery", '"Action=Update"', 2),
                        _row(2, "user-a@example.com", '"Action=Delete"', 1),
                    ],
                    "total": 2,
                },
            )
        )
        logs = json.loads((await get_audit_logs(client, username="*", exclude_system=True))[0].text)
        changes = json.loads((await get_change_audit(client, username="*"))[0].text)

        assert "username" not in _filter(route, 0)
        assert [r["id"] for r in logs["audit_logs"]] == ["row2"]
        assert [r["id"] for r in changes["change_logs"]] == ["row2"]


class TestLoginTruncation:
    @respx.mock
    async def test_a_full_wording_page_reads_has_more(self, client):
        from lm_mcp.tools.audit import get_login_audit

        def responder(request):
            flt = parse_qs(urlparse(str(request.url)).query).get("filter", [""])[0]
            if "signs in via" in flt:
                return httpx.Response(
                    200,
                    json={
                        "items": [
                            _row(i, "user-a@example.com", "user-a signs in via SAML", 10 - i)
                            for i in range(2)
                        ],
                        "total": -3,
                    },
                )
            return httpx.Response(200, json={"items": [], "total": 0})

        respx.get(URL).mock(side_effect=responder)
        data = json.loads((await get_login_audit(client, limit=2))[0].text)
        assert data["count"] == 2
        assert data["has_more"] is True
        assert "narrow" in data["note"]

    @respx.mock
    async def test_merged_wordings_past_limit_read_has_more(self, client):
        from lm_mcp.tools.audit import get_login_audit

        def responder(request):
            flt = parse_qs(urlparse(str(request.url)).query).get("filter", [""])[0]
            # No single wording fills its page; only the merge runs past the limit.
            if "signs in via" in flt:
                rows = [_row(1, "user-a@example.com", "user-a signs in via SAML", 9)]
            elif "signs out" in flt:
                rows = [_row(2, "user-a@example.com", "user-a signs out", 8)]
            elif "2FA Mode" in flt:
                rows = [_row(3, "localuser", "localuser log in. 2FA Mode : None", 7)]
            else:
                rows = []
            return httpx.Response(200, json={"items": rows, "total": len(rows)})

        respx.get(URL).mock(side_effect=responder)
        data = json.loads((await get_login_audit(client, limit=2))[0].text)
        assert [r["id"] for r in data["login_logs"]] == ["row1", "row2"]
        assert data["has_more"] is True


class TestChangeAuditPaging:
    @respx.mock
    async def test_stopping_at_limit_with_rows_left_reads_has_more(self, client):
        from lm_mcp.tools.audit import get_change_audit

        respx.get(URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        _row(1, "user-a@example.com", '"Action=Delete"', 3),
                        _row(2, "user-a@example.com", '"Action=Update"', 2),
                        _row(3, "user-a@example.com", '"Action=Add"', 1),
                    ]
                },
            )
        )
        data = json.loads((await get_change_audit(client, limit=1))[0].text)
        assert [r["id"] for r in data["change_logs"]] == ["row1"]
        assert (data["scanned"], data["has_more"]) == (1, True)

    @respx.mock
    async def test_all_rows_read_and_short_pool_is_complete(self, client):
        from lm_mcp.tools.audit import get_change_audit

        respx.get(URL).mock(
            return_value=httpx.Response(
                200, json={"items": [_row(1, "user-a@example.com", '"Action=Delete"', 3)]}
            )
        )
        data = json.loads((await get_change_audit(client, limit=5))[0].text)
        assert (data["scanned"], data["has_more"]) == (1, False)
        assert "note" not in data

    @respx.mock
    async def test_full_pool_short_of_limit_says_older_changes_exist(self, client):
        from lm_mcp.tools.audit import get_change_audit

        route = respx.get(URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        _row(i, "System:ActiveDiscovery", '"Action=Update"', 300 - i)
                        for i in range(200)
                    ]
                },
            )
        )
        data = json.loads((await get_change_audit(client, limit=5))[0].text)
        assert route.calls[0].request.url.params["size"] == "200"
        assert data["change_logs"] == []
        assert data["has_more"] is True
        assert "Only the newest 200" in data["note"]

    @respx.mock
    async def test_full_pool_holding_every_row_is_complete(self, client):
        """Exactly 200 rows on the portal fill the pool, but nothing older exists."""
        from lm_mcp.tools.audit import get_change_audit

        respx.get(URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        _row(i, "System:ActiveDiscovery", '"Action=Update"', 300 - i)
                        for i in range(200)
                    ],
                    "total": 200,
                },
            )
        )
        data = json.loads((await get_change_audit(client, limit=5))[0].text)
        assert data["has_more"] is False
        assert "note" not in data


class TestApiTokenAuditExactToken:
    @respx.mock
    async def test_rows_of_a_longer_token_with_the_same_prefix_are_dropped(self, client):
        from lm_mcp.tools.audit import get_api_token_audit

        respx.get(URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        _row(1, "svc", "Failed API request: API token AbCdEfGh attempted", 2),
                        _row(2, "svc", "Failed API request: API token AbCdEfGhZZZZ attempted", 1),
                    ],
                    "total": 2,
                },
            )
        )
        data = json.loads((await get_api_token_audit(client, access_id="AbCdEfGh"))[0].text)
        assert [r["id"] for r in data["api_token_logs"]] == ["row1"]
        assert data["count"] == 1
        # Both rows the API returned were read, so nothing is left to page to.
        assert (data["total"], data["has_more"]) == (2, False)
        assert "different token" in data["note"]

    async def test_wildcard_only_access_id_is_refused(self, client):
        from lm_mcp.tools.audit import get_api_token_audit

        with respx.mock(assert_all_called=False) as mock:
            route = mock.get(URL).mock(return_value=httpx.Response(200, json={"items": []}))
            text = (await get_api_token_audit(client, access_id="**"))[0].text

        assert text.startswith("Error: access_id is empty")
        assert not route.called


LONG_USERNAMES = ",".join(f"long-user-example-{i:03d}@subdomain.example.com" for i in range(40))


class TestLimitRefusals:
    """Each tool refuses a request past a ceiling before any call, and does not log it."""

    @pytest.mark.parametrize(
        ("tool", "kwargs", "expect"),
        [
            ("get_audit_logs", {"offset": 9990, "limit": 50}, "10000"),
            ("get_audit_logs", {"username": LONG_USERNAMES}, "HTTP 500"),
            ("get_login_audit", {"username": LONG_USERNAMES}, "HTTP 500"),
            ("get_change_audit", {"username": LONG_USERNAMES}, "HTTP 500"),
            ("get_api_token_audit", {"access_id": "AbCdEfGh", "limit": 10001}, "10000"),
        ],
        ids=["audit-offset", "audit-filter", "login-filter", "change-filter", "token-offset"],
    )
    async def test_refused_before_any_call_and_not_logged(
        self, client, caplog, tool, kwargs, expect
    ):
        from lm_mcp.tools import audit

        with respx.mock(assert_all_called=False) as mock:
            route = mock.get(URL).mock(return_value=httpx.Response(200, json={"items": []}))
            with caplog.at_level("ERROR", logger="lm_mcp.tools"):
                text = (await getattr(audit, tool)(client, **kwargs))[0].text

        assert text.startswith("Error:")
        assert expect in text
        assert not route.called
        assert "unhandled error in tool handler" not in caplog.text


class TestLoginTruncationArms:
    @respx.mock
    @pytest.mark.parametrize(
        ("rows", "total"),
        [(1, -5), (2, 2)],
        ids=["short-page-negative-total", "full-page-exact-total"],
    )
    async def test_each_arm_alone_reads_has_more(self, client, rows, total):
        from lm_mcp.tools.audit import get_login_audit

        def responder(request):
            flt = parse_qs(urlparse(str(request.url)).query).get("filter", [""])[0]
            if "signs in via" in flt:
                items = [
                    _row(i, "user-a@example.com", "user-a signs in via SAML", 9 - i)
                    for i in range(rows)
                ]
                return httpx.Response(200, json={"items": items, "total": total})
            return httpx.Response(200, json={"items": [], "total": 0})

        respx.get(URL).mock(side_effect=responder)
        data = json.loads((await get_login_audit(client, limit=2))[0].text)
        assert data["has_more"] is True
        assert "lower bound" in data["total_note"]

    @respx.mock
    async def test_complete_result_has_no_total_note(self, client):
        from lm_mcp.tools.audit import get_login_audit

        respx.get(URL).mock(return_value=httpx.Response(200, json={"items": [], "total": 0}))
        data = json.loads((await get_login_audit(client, limit=2))[0].text)
        assert data["has_more"] is False
        assert "total_note" not in data

    async def test_success_only_and_failed_only_together_are_refused(self, client):
        from lm_mcp.tools.audit import get_login_audit

        with respx.mock(assert_all_called=False) as mock:
            route = mock.get(URL).mock(return_value=httpx.Response(200, json={"items": []}))
            text = (await get_login_audit(client, success_only=True, failed_only=True))[0].text

        assert text.startswith("Error: success_only and failed_only cannot both be set")
        assert not route.called


class TestChangeClassification:
    @pytest.mark.parametrize(
        ("desc", "expected"),
        [
            ('"Action=Delete"; "Type=Device"', "delete"),
            ('"Action=Add"; "Type=Dashboard"', "create"),
            ('"Action=Import"; "Type=DataSource"', "import"),
            ("Edit the widget W-1 of dashboard Board-C", "update"),
            ("Rename the dashboard Board-C", "update"),
            ('"Action=Enable"; "Type=Collector"', "update"),
            ('"Action=Export"; "Type=Dashboard"', None),
            ('"Action=Login"', None),
            ('"Action=Fetch"; "Type=Report"', None),
            ('"Action=Acknowledge"; "Type=Alert"', None),
            ('"Action=Schedule"; "Type=Report"', None),
        ],
    )
    def test_only_known_verbs_are_changes(self, desc, expected):
        from lm_mcp.tools.audit import _change_type

        assert _change_type(desc) == expected

    @respx.mock
    async def test_change_type_wildcards_are_stripped_then_validated(self, client):
        """As for every string parameter, wildcards are stripped with a note, then validated."""
        from lm_mcp.tools.audit import get_change_audit

        respx.get(URL).mock(
            return_value=httpx.Response(
                200, json={"items": [_row(1, "user-a@example.com", '"Action=Update"', 1)]}
            )
        )
        data = json.loads((await get_change_audit(client, change_type="update*"))[0].text)
        assert [r["change_type"] for r in data["change_logs"]] == ["update"]
        assert "Wildcard" in data["note"]

        refused = (await get_change_audit(client, change_type="updated*"))[0].text
        assert refused.startswith("Error: change_type must be one of")

    @respx.mock
    async def test_short_pool_with_a_negative_total_reads_has_more(self, client):
        from lm_mcp.tools.audit import get_change_audit

        respx.get(URL).mock(
            return_value=httpx.Response(
                200,
                json={"items": [_row(1, "user-a@example.com", '"Action=Delete"', 3)], "total": -5},
            )
        )
        data = json.loads((await get_change_audit(client, limit=5))[0].text)
        assert (data["scanned"], data["has_more"]) == (1, True)


class TestApiTokenAuditResponse:
    @respx.mock
    async def test_reports_no_offset_and_says_how_to_reach_more(self, client):
        from lm_mcp.tools.audit import get_api_token_audit

        respx.get(URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [_row(1, "svc", "Failed API request: API token AbCdEfGh x", 1)],
                    "total": -2,
                },
            )
        )
        data = json.loads((await get_api_token_audit(client, access_id="AbCdEfGh"))[0].text)
        assert "offset" not in data
        assert data["has_more"] is True
        assert "narrow start_time/end_time" in data["note"]

    @respx.mock
    async def test_token_without_an_access_id_is_not_found(self, client):
        from lm_mcp.tools.audit import get_api_token_audit

        respx.get(f"{BASE}/setting/admins/apitokens").mock(
            return_value=httpx.Response(200, json={"items": [{"id": 7, "type": "Bearer"}]})
        )
        logs = respx.get(URL).mock(return_value=httpx.Response(200, json={"items": []}))

        text = (await get_api_token_audit(client, token_id=7))[0].text
        assert "API token 7 not found" in text
        assert not logs.called

    @respx.mock
    async def test_boolean_total_is_not_read_as_a_count(self, client):
        """True is an int in Python; it must not pass as total=1."""
        from lm_mcp.tools.audit import get_audit_logs

        respx.get(URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [_row(i, "user-a@example.com", "x", i) for i in range(2)],
                    "total": True,
                },
            )
        )
        data = json.loads((await get_audit_logs(client, limit=2))[0].text)
        assert (data["total"], data["has_more"]) == (3, True)


class TestRemainingBehaviours:
    @respx.mock
    async def test_sign_out_is_logout_and_rows_are_deduplicated(self, client):
        """A row two wordings both match is returned once; a sign-out reads as logout."""
        from lm_mcp.tools.audit import get_login_audit

        shared = _row(1, "user-a@example.com", "user-a signs in via SAML and signs out", 9)

        def responder(request):
            flt = parse_qs(urlparse(str(request.url)).query).get("filter", [""])[0]
            if "signs in via" in flt:
                return httpx.Response(200, json={"items": [shared], "total": 1})
            if "signs out" in flt:
                rows = [shared, _row(2, "user-a@example.com", "user-a signs out", 8)]
                return httpx.Response(200, json={"items": rows, "total": 2})
            return httpx.Response(200, json={"items": [], "total": 0})

        respx.get(URL).mock(side_effect=responder)
        data = json.loads((await get_login_audit(client))[0].text)
        assert [r["id"] for r in data["login_logs"]] == ["row1", "row2"]
        assert data["login_logs"][1]["status"] == "logout"
        assert data["login_logs"][1]["method"] is None

    @respx.mock
    async def test_change_audit_reports_the_filter_sent(self, client):
        from lm_mcp.tools.audit import get_change_audit

        respx.get(URL).mock(return_value=httpx.Response(200, json={"items": [], "total": 0}))
        data = json.loads(
            (
                await get_change_audit(
                    client, resource_type="dashboard", username="user-a@example.com"
                )
            )[0].text
        )
        assert data["filter"] == 'username:"user-a@example.com",description~"dashboard"'

    def test_two_factor_request_is_not_a_change(self):
        """A leading change verb on a 2FA or API request is not a configuration change."""
        from lm_mcp.tools.audit import _change_type

        assert _change_type("Enable 2FA Request for user-a@example.com") is None
        assert _change_type("Update rejected by API request: path '/device/devices'") is None
        assert _change_type("Enable the collector collector-example-1") == "update"
