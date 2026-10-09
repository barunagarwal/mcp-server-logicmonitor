# Description: Tests for admin MCP tools (Dashboard Groups, API Tokens, Access Groups, OIDs).
# Description: Covers CRUD operations and error handling for administrative resources.

import json

import httpx
import pytest
import respx

from lm_mcp.auth.bearer import BearerAuth
from lm_mcp.client import LogicMonitorClient


@pytest.fixture
def auth():
    return BearerAuth("test-token")


@pytest.fixture
def client(auth):
    return LogicMonitorClient(
        base_url="https://test.logicmonitor.com/santaba/rest",
        auth=auth,
        timeout=30,
        api_version=3,
    )


class TestDashboardGroups:
    @respx.mock
    async def test_get_dashboard_groups_returns_list(self, client):
        from lm_mcp.tools.dashboard_groups import get_dashboard_groups

        respx.get("https://test.logicmonitor.com/santaba/rest/dashboard/groups").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": 1,
                            "name": "Production",
                            "description": "Production dashboards",
                            "parentId": 0,
                            "fullPath": "Production",
                            "numOfDashboards": 10,
                            "numOfDirectDashboards": 5,
                            "numOfDirectSubGroups": 2,
                        }
                    ],
                    "total": 1,
                },
            )
        )

        result = await get_dashboard_groups(client)
        data = json.loads(result[0].text)
        assert data["dashboard_groups"][0]["name"] == "Production"

    @respx.mock
    async def test_get_dashboard_group_returns_details(self, client):
        from lm_mcp.tools.dashboard_groups import get_dashboard_group

        respx.get("https://test.logicmonitor.com/santaba/rest/dashboard/groups/1").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 1,
                    "name": "Production",
                    "description": "Production dashboards",
                    "parentId": 0,
                    "fullPath": "Production",
                    "numOfDashboards": 10,
                    "widgetTokens": [{"name": "token1", "value": "value1"}],
                },
            )
        )

        result = await get_dashboard_group(client, group_id=1)
        data = json.loads(result[0].text)
        assert data["name"] == "Production"


class TestApiTokens:
    @respx.mock
    async def test_get_api_tokens_returns_list(self, client):
        from lm_mcp.tools.api_tokens import get_api_tokens

        respx.get("https://test.logicmonitor.com/santaba/rest/setting/admins/1/apitokens").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": 100,
                            "adminId": 1,
                            "adminName": "admin",
                            "note": "CI/CD token",
                            "status": 2,
                            "createdOn": 1700000000,
                            "lastUsedOn": 1700100000,
                            "roles": [{"name": "administrator"}],
                        }
                    ],
                    "total": 1,
                },
            )
        )

        result = await get_api_tokens(client, admin_id=1)
        data = json.loads(result[0].text)
        assert data["api_tokens"][0]["note"] == "CI/CD token"

    @respx.mock
    async def test_get_api_token_returns_details(self, client):
        from lm_mcp.tools.api_tokens import get_api_token

        respx.get("https://test.logicmonitor.com/santaba/rest/setting/admins/1/apitokens/100").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 100,
                    "adminId": 1,
                    "adminName": "admin",
                    "note": "CI/CD token",
                    "status": 2,
                    "roles": [{"id": 1, "name": "administrator"}],
                },
            )
        )

        result = await get_api_token(client, admin_id=1, token_id=100)
        data = json.loads(result[0].text)
        assert data["note"] == "CI/CD token"

    @respx.mock
    async def test_get_api_tokens_without_admin_lists_portal_wide(self, client):
        """admin_id is optional; omitted, tokens are listed across the portal."""
        from lm_mcp.tools.api_tokens import get_api_tokens

        route = respx.get(
            "https://test.logicmonitor.com/santaba/rest/setting/admins/apitokens"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": 100,
                            "adminId": 1,
                            "adminName": "admin",
                            "note": "CI/CD token",
                            "status": 2,
                            "roles": [{"name": "administrator"}],
                        },
                        {
                            "id": 101,
                            "adminId": 7,
                            "adminName": "svc-backup",
                            "note": "backup job",
                            "status": 2,
                            "roles": [{"name": "readonly"}],
                        },
                    ],
                    "total": 2,
                },
            )
        )

        result = await get_api_tokens(client, limit=25)
        data = json.loads(result[0].text)
        assert route.called
        assert route.calls.last.request.url.params["size"] == "25"
        assert [t["admin_id"] for t in data["api_tokens"]] == [1, 7]
        assert data["total"] == 2

    @respx.mock
    async def test_get_api_token_without_admin_fetches_by_id(self, client):
        """Omitted admin_id, the token is fetched by id through the portal-wide filter."""
        from lm_mcp.tools.api_tokens import get_api_token

        route = respx.get(
            "https://test.logicmonitor.com/santaba/rest/setting/admins/apitokens"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": 100,
                            "adminId": 1,
                            "adminName": "admin",
                            "note": "CI/CD token",
                            "status": 2,
                            "roles": [{"id": 1, "name": "administrator"}],
                        }
                    ],
                    "total": 1,
                },
            )
        )

        result = await get_api_token(client, token_id=100)
        data = json.loads(result[0].text)
        assert route.calls.last.request.url.params["filter"] == "id:100"
        assert data["id"] == 100
        assert data["admin_id"] == 1
        assert data["roles"] == [{"id": 1, "name": "administrator"}]

    @respx.mock
    async def test_get_api_token_without_admin_reports_missing_id(self, client):
        """An id the portal-wide filter does not match is a not-found error, not empty data."""
        from lm_mcp.tools.api_tokens import get_api_token

        respx.get("https://test.logicmonitor.com/santaba/rest/setting/admins/apitokens").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        result = await get_api_token(client, token_id=999)
        assert result[0].text.startswith("Error: API token 999 not found")

    @respx.mock
    async def test_get_api_tokens_returns_access_id_and_type(self, client):
        """access_id is what get_api_token_audit matches on, so the listing carries it."""
        from lm_mcp.tools.api_tokens import get_api_tokens

        respx.get("https://test.logicmonitor.com/santaba/rest/setting/admins/apitokens").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {"id": 7, "accessId": "AbCdEfGhIjKlMnOpQrSt", "adminId": 3, "type": "LMv1"}
                    ],
                    "total": 1,
                },
            )
        )

        token = json.loads((await get_api_tokens(client))[0].text)["api_tokens"][0]
        assert token["access_id"] == "AbCdEfGhIjKlMnOpQrSt"
        assert token["type"] == "LMv1"

    @respx.mock
    async def test_get_api_token_returns_access_id_and_type(self, client):
        from lm_mcp.tools.api_tokens import get_api_token

        respx.get("https://test.logicmonitor.com/santaba/rest/setting/admins/apitokens").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": 7,
                            "accessId": "AbCdEfGhIjKlMnOpQrSt",
                            "adminId": 3,
                            "type": "Bearer",
                        }
                    ],
                    "total": 1,
                },
            )
        )

        token = json.loads((await get_api_token(client, token_id=7))[0].text)
        assert token["access_id"] == "AbCdEfGhIjKlMnOpQrSt"
        assert token["type"] == "Bearer"

    @respx.mock
    async def test_get_api_token_without_admin_rejects_a_different_id(self, client):
        """A lookup that returns some other token is not found, not that token's data."""
        from lm_mcp.tools.api_tokens import get_api_token

        respx.get("https://test.logicmonitor.com/santaba/rest/setting/admins/apitokens").mock(
            return_value=httpx.Response(
                200, json={"items": [{"id": 8, "adminId": 3, "note": "other"}], "total": 1}
            )
        )

        result = await get_api_token(client, token_id=7)
        assert result[0].text.startswith("Error: API token 7 not found")

    @respx.mock
    async def test_get_api_tokens_tolerates_null_roles(self, client):
        from lm_mcp.tools.api_tokens import get_api_tokens

        respx.get("https://test.logicmonitor.com/santaba/rest/setting/admins/apitokens").mock(
            return_value=httpx.Response(
                200, json={"items": [{"id": 7, "adminId": 3, "roles": None}], "total": 1}
            )
        )

        token = json.loads((await get_api_tokens(client))[0].text)["api_tokens"][0]
        assert token["roles"] == []


class TestAccessGroups:
    @respx.mock
    async def test_get_access_groups_returns_list(self, client):
        from lm_mcp.tools.access_groups import get_access_groups

        respx.get("https://test.logicmonitor.com/santaba/rest/setting/accessgroup").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": 1,
                            "name": "US Operations",
                            "description": "US team access",
                            "tenantId": 0,
                        }
                    ],
                    "total": 1,
                },
            )
        )

        result = await get_access_groups(client)
        data = json.loads(result[0].text)
        assert data["access_groups"][0]["name"] == "US Operations"

    @respx.mock
    async def test_get_access_group_returns_details(self, client):
        from lm_mcp.tools.access_groups import get_access_group

        respx.get("https://test.logicmonitor.com/santaba/rest/setting/accessgroup/1").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 1,
                    "name": "US Operations",
                    "description": "US team access",
                    "tenantId": 0,
                },
            )
        )

        result = await get_access_group(client, group_id=1)
        data = json.loads(result[0].text)
        assert data["name"] == "US Operations"


class TestOids:
    @respx.mock
    async def test_get_oids_returns_list(self, client):
        from lm_mcp.tools.oids import get_oids

        respx.get("https://test.logicmonitor.com/santaba/rest/setting/oids").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": 1,
                            "oid": "1.3.6.1.2.1.1.1",
                            "name": "sysDescr",
                            "category": "System",
                            "description": "System description",
                            "datapointType": "string",
                        }
                    ],
                    "total": 1,
                },
            )
        )

        result = await get_oids(client)
        data = json.loads(result[0].text)
        assert data["oids"][0]["name"] == "sysDescr"

    @respx.mock
    async def test_get_oid_returns_details(self, client):
        from lm_mcp.tools.oids import get_oid

        respx.get("https://test.logicmonitor.com/santaba/rest/setting/oids/1").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 1,
                    "oid": "1.3.6.1.2.1.1.1",
                    "name": "sysDescr",
                    "category": "System",
                    "description": "System description",
                    "datapointType": "string",
                    "datapointDescription": "A textual description of the entity",
                },
            )
        )

        result = await get_oid(client, oid_id=1)
        data = json.loads(result[0].text)
        assert data["oid"] == "1.3.6.1.2.1.1.1"
