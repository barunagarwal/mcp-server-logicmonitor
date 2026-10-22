# Description: Tests for the shared list pagination response helper and its call sites.
# Description: A negative API total (a lower bound) must read as more results, with a note.

import json

import httpx
import pytest
import respx

from lm_mcp.auth.bearer import BearerAuth
from lm_mcp.client import LogicMonitorClient

BASE_URL = "https://test.logicmonitor.com/santaba/rest"


@pytest.fixture
def client():
    """Create a LogicMonitorClient instance for testing."""
    return LogicMonitorClient(
        base_url=BASE_URL,
        auth=BearerAuth("test-token"),
        timeout=30,
        api_version=3,
    )


class TestPaginatedResponse:
    """R4.2: paginated_response builds total, count, offset and has_more."""

    def test_positive_total_with_more_pages(self):
        from lm_mcp.tools import paginated_response

        response = paginated_response([{}, {}, {}], {"total": 10}, offset=0)

        assert response == {"total": 10, "count": 3, "offset": 0, "has_more": True}

    def test_positive_total_on_last_page(self):
        from lm_mcp.tools import paginated_response

        response = paginated_response([{}, {}, {}], {"total": 10}, offset=7)

        assert response == {"total": 10, "count": 3, "offset": 7, "has_more": False}

    def test_missing_total_reads_as_zero(self):
        from lm_mcp.tools import paginated_response

        response = paginated_response([], {}, offset=0)

        assert response == {"total": 0, "count": 0, "offset": 0, "has_more": False}

    @pytest.mark.parametrize(
        ("api_total", "offset", "expected_total"),
        [
            # The portal's form: -(offset + size + 1) when rows exist past the page.
            (-16, 10, 16),
            # Any negative total is a lower bound, whatever its magnitude.
            (-1, 0, 1),
        ],
    )
    def test_negative_total_means_more_and_carries_a_note(self, api_total, offset, expected_total):
        from lm_mcp.tools import paginated_response

        response = paginated_response([{}] * 5, {"total": api_total}, offset=offset)

        assert response["total"] == expected_total
        assert response["count"] == 5
        assert response["offset"] == offset
        assert response["has_more"] is True
        assert "exact count" in response["total_note"]


# (module, function, endpoint path, extra required arguments)
LIST_TOOLS = [
    ("audit", "get_audit_logs", "/setting/accesslogs", {}),
    ("collectors", "get_collectors", "/setting/collector/collectors", {}),
    ("configsources", "get_configsources", "/setting/configsources", {}),
    (
        "configsources",
        "get_configsource_update_reasons",
        "/setting/configsources/7/updatereasons",
        {"configsource_id": 7},
    ),
    (
        "configsources",
        "get_device_config",
        "/device/devices/1/devicedatasources/2/instances/3/config",
        {"device_id": 1, "device_datasource_id": 2, "instance_id": 3},
    ),
    ("dashboards", "get_dashboards", "/dashboard/dashboards", {}),
    ("datasources", "get_datasources", "/setting/datasources", {}),
    ("eventsources", "get_eventsources", "/setting/eventsources", {}),
    ("logsources", "get_logsources", "/setting/logsources", {}),
    ("propertysources", "get_propertysources", "/setting/propertyrules", {}),
    ("reports", "get_reports", "/report/reports", {}),
    ("topologysources", "get_topologysources", "/setting/topologysources", {}),
    ("users", "get_users", "/setting/admins", {}),
    ("websites", "get_websites", "/website/websites", {}),
    ("alerts", "get_alerts", "/alert/alerts", {}),
    ("devices", "get_devices", "/device/devices", {}),
    ("diagnosticsources", "get_diagnosticsources", "/setting/diagnosticsources", {}),
    ("remediationsources", "get_remediationsources", "/setting/remediationsources", {}),
]


@pytest.mark.parametrize(
    ("module", "function", "path", "kwargs"),
    LIST_TOOLS,
    ids=[f"{m}.{f}" for m, f, _, _ in LIST_TOOLS],
)
@respx.mock
async def test_list_tool_reports_more_on_negative_total(client, module, function, path, kwargs):
    """R4.2: a full page with total -1001 reads as more results, not as the list's end."""
    import importlib

    tool = getattr(importlib.import_module(f"lm_mcp.tools.{module}"), function)
    items = [{"id": i} for i in range(1000)]
    respx.get(f"{BASE_URL}{path}").mock(
        return_value=httpx.Response(200, json={"total": -1001, "items": items})
    )

    result = await tool(client, limit=1000, **kwargs)

    data = json.loads(result[0].text)
    assert data["count"] == 1000
    assert data["total"] == 1001
    assert data["has_more"] is True
    assert "exact count" in data["total_note"]
