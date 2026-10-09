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
    async def test_get_api_tokens_without_admin_lists_all(self, client):
        """Omitting admin_id lists every token (the registry never exposed admin_id)."""
        from lm_mcp.tools.api_tokens import get_api_tokens

        respx.get("https://test.logicmonitor.com/santaba/rest/setting/admins/apitokens").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": 7,
                            "accessId": "AbCdEfGhIjKlMnOpQrSt",
                            "adminId": 3,
                            "status": 2,
                            "type": "LMv1",
                        }
                    ],
                    "total": 1,
                },
            )
        )
        data = json.loads((await get_api_tokens(client))[0].text)
        assert data["api_tokens"][0]["access_id"] == "AbCdEfGhIjKlMnOpQrSt"
        assert data["api_tokens"][0]["type"] == "LMv1"

    @respx.mock
    async def test_get_api_token_without_admin_looks_up(self, client):
        from lm_mcp.tools.api_tokens import get_api_token

        respx.get("https://test.logicmonitor.com/santaba/rest/setting/admins/apitokens").mock(
            return_value=httpx.Response(
                200, json={"items": [{"id": 7, "accessId": "AbCdEfGhIjKlMnOpQrSt", "adminId": 3}]}
            )
        )
        data = json.loads((await get_api_token(client, token_id=7))[0].text)
        assert data["admin_id"] == 3

    @respx.mock
    async def test_get_api_token_without_admin_not_found(self, client):
        from lm_mcp.tools.api_tokens import get_api_token

        respx.get("https://test.logicmonitor.com/santaba/rest/setting/admins/apitokens").mock(
            return_value=httpx.Response(200, json={"items": []})
        )
        text = (await get_api_token(client, token_id=99))[0].text
        assert "not found" in text


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
