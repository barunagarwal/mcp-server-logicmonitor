# Description: Tests for filter value sanitization utility.
# Description: Validates wildcard stripping, note injection, and clean input passthrough.

import json

import httpx
import pytest
import respx

from lm_mcp.auth.bearer import BearerAuth
from lm_mcp.client import LogicMonitorClient
from lm_mcp.tools import quote_filter_value, sanitize_filter_value


@pytest.fixture
def auth():
    """Create a BearerAuth instance for testing."""
    return BearerAuth("test-token")


@pytest.fixture
def client(auth):
    """Create a LogicMonitorClient instance for testing."""
    return LogicMonitorClient(
        base_url="https://test.logicmonitor.com/santaba/rest",
        auth=auth,
        timeout=30,
        api_version=3,
    )


@pytest.fixture
def enable_writes(monkeypatch):
    """Enable write operations for testing."""
    monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
    monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
    monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "true")

    from importlib import reload

    import lm_mcp.config

    reload(lm_mcp.config)


class TestSanitizeFilterValue:
    """Tests for the sanitize_filter_value utility function."""

    def test_strips_trailing_wildcard(self):
        """Trailing * is removed from filter value."""
        cleaned, was_modified = sanitize_filter_value("prod*")
        assert cleaned == "prod"
        assert was_modified is True

    def test_strips_leading_wildcard(self):
        """Leading * is removed from filter value."""
        cleaned, was_modified = sanitize_filter_value("*prod")
        assert cleaned == "prod"
        assert was_modified is True

    def test_strips_multiple_wildcards(self):
        """Multiple * characters are removed."""
        cleaned, was_modified = sanitize_filter_value("*prod*server*")
        assert cleaned == "prodserver"
        assert was_modified is True

    def test_strips_question_mark_wildcard(self):
        """? wildcard characters are removed."""
        cleaned, was_modified = sanitize_filter_value("prod?server")
        assert cleaned == "prodserver"
        assert was_modified is True

    def test_strips_mixed_wildcards(self):
        """Both * and ? wildcards are removed."""
        cleaned, was_modified = sanitize_filter_value("prod*serv?r")
        assert cleaned == "prodservr"
        assert was_modified is True

    def test_clean_value_unchanged(self):
        """Values without wildcards pass through unchanged."""
        cleaned, was_modified = sanitize_filter_value("production")
        assert cleaned == "production"
        assert was_modified is False

    def test_none_returns_none(self):
        """None input returns None and not modified."""
        cleaned, was_modified = sanitize_filter_value(None)
        assert cleaned is None
        assert was_modified is False

    def test_empty_string_returns_empty(self):
        """Empty string passes through unchanged."""
        cleaned, was_modified = sanitize_filter_value("")
        assert cleaned == ""
        assert was_modified is False

    def test_only_wildcards_returns_empty(self):
        """String of only wildcards becomes empty string."""
        cleaned, was_modified = sanitize_filter_value("***")
        assert cleaned == ""
        assert was_modified is True

    def test_preserves_other_special_chars(self):
        """Non-wildcard special characters are preserved."""
        cleaned, was_modified = sanitize_filter_value("prod-server_01.example")
        assert cleaned == "prod-server_01.example"
        assert was_modified is False


class TestWildcardNoteInResponse:
    """Tests that wildcard stripping produces a note in tool responses."""

    @respx.mock
    async def test_wildcard_stripped_includes_note(self, client):
        """Response includes note when wildcards are stripped from name_filter."""
        from lm_mcp.tools.devices import get_devices

        route = respx.get("https://test.logicmonitor.com/santaba/rest/device/devices").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        result = await get_devices(client, name_filter="prod*")

        data = json.loads(result[0].text)
        assert "note" in data
        assert "wildcard" in data["note"].lower() or "Wildcard" in data["note"]
        # Verify the actual filter sent to API has no wildcard
        params = dict(route.calls[0].request.url.params)
        assert params["filter"] == 'displayName~"prod"'

    @respx.mock
    async def test_clean_input_no_note(self, client):
        """Response does NOT include note when input has no wildcards."""
        from lm_mcp.tools.devices import get_devices

        respx.get("https://test.logicmonitor.com/santaba/rest/device/devices").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        result = await get_devices(client, name_filter="prod")

        data = json.loads(result[0].text)
        assert "note" not in data

    @respx.mock
    async def test_datasources_wildcard_note(self, client):
        """DataSource filter also strips wildcards and includes note."""
        from lm_mcp.tools.datasources import get_datasources

        route = respx.get("https://test.logicmonitor.com/santaba/rest/setting/datasources").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        result = await get_datasources(client, name_filter="CPU*")

        data = json.loads(result[0].text)
        assert "note" in data
        params = dict(route.calls[0].request.url.params)
        assert params["filter"] == 'name~"CPU"'

    @respx.mock
    async def test_alerts_device_wildcard_note(self, client):
        """Alert device filter strips wildcards and includes note."""
        from lm_mcp.tools.alerts import get_alerts

        route = respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        result = await get_alerts(client, device="server*")

        data = json.loads(result[0].text)
        assert "note" in data
        params = dict(route.calls[0].request.url.params)
        assert params["filter"] == 'monitorObjectName~"server"'

    @respx.mock
    async def test_collectors_wildcard_note(self, client):
        """Collector hostname filter strips wildcards and includes note."""
        from lm_mcp.tools.collectors import get_collectors

        route = respx.get(
            "https://test.logicmonitor.com/santaba/rest/setting/collector/collectors"
        ).mock(return_value=httpx.Response(200, json={"items": [], "total": 0}))

        result = await get_collectors(client, hostname_filter="coll*")

        data = json.loads(result[0].text)
        assert "note" in data
        params = dict(route.calls[0].request.url.params)
        assert params["filter"] == 'hostname~"coll"'


class TestCorrelationSanitization:
    """Tests that correlation and scoring tools sanitize device filter values."""

    @respx.mock
    async def test_correlate_alerts_strips_wildcard(self, client):
        """correlate_alerts strips wildcards from device parameter."""
        from lm_mcp.tools.correlation import _build_alert_filter

        result = await _build_alert_filter(client, hours_back=4, device="server*")

        assert 'monitorObjectName~"server"' in result
        assert "*" not in result

    @respx.mock
    async def test_score_alert_noise_strips_wildcard(self, client):
        """score_alert_noise strips wildcards from device parameter."""
        from lm_mcp.tools.scoring import score_alert_noise

        route = respx.get("https://test.logicmonitor.com/santaba/rest/alert/alerts").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        await score_alert_noise(client, device="prod*")

        params = dict(route.calls[0].request.url.params)
        assert 'monitorObjectName~"prod"' in params["filter"]
        assert "*" not in params["filter"]


class TestFilterValueSentToApi:
    """Tests that the actual filter value sent to the LM API is correct."""

    @respx.mock
    async def test_devices_name_filter_value(self, client):
        """get_devices sends displayName~{value} as filter to API."""
        from lm_mcp.tools.devices import get_devices

        route = respx.get("https://test.logicmonitor.com/santaba/rest/device/devices").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        await get_devices(client, name_filter="production")

        params = dict(route.calls[0].request.url.params)
        assert params["filter"] == 'displayName~"production"'

    @respx.mock
    async def test_device_groups_name_filter_value(self, client):
        """get_device_groups sends name~{value} as filter to API."""
        from lm_mcp.tools.devices import get_device_groups

        route = respx.get("https://test.logicmonitor.com/santaba/rest/device/groups").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        await get_device_groups(client, name_filter="Production")

        params = dict(route.calls[0].request.url.params)
        assert params["filter"] == 'name~"Production"'

    @respx.mock
    async def test_logsources_name_filter_value(self, client):
        """get_logsources sends name~{value} as filter to API."""
        from lm_mcp.tools.logsources import get_logsources

        route = respx.get("https://test.logicmonitor.com/santaba/rest/setting/logsources").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        await get_logsources(client, name_filter="syslog")

        params = dict(route.calls[0].request.url.params)
        assert params["filter"] == 'name~"syslog"'

    @respx.mock
    async def test_dashboards_name_filter_value(self, client):
        """get_dashboards sends name~{value} as filter to API."""
        from lm_mcp.tools.dashboards import get_dashboards

        route = respx.get("https://test.logicmonitor.com/santaba/rest/dashboard/dashboards").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        await get_dashboards(client, name_filter="overview")

        params = dict(route.calls[0].request.url.params)
        assert params["filter"] == 'name~"overview"'

    @respx.mock
    async def test_websites_name_filter_value(self, client):
        """get_websites sends name~{value} as filter to API."""
        from lm_mcp.tools.websites import get_websites

        route = respx.get("https://test.logicmonitor.com/santaba/rest/website/websites").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        await get_websites(client, name_filter="portal")

        params = dict(route.calls[0].request.url.params)
        assert params["filter"] == 'name~"portal"'


class TestQuoteFilterValue:
    """quote_filter_value yields exactly one quoted clause whatever the value holds (R3.6)."""

    def test_plain_value_is_wrapped(self):
        """A value without special characters is wrapped in double quotes."""
        assert quote_filter_value("prod") == '"prod"'

    def test_embedded_quotes_are_escaped(self):
        """Quotes inside the value are escaped so they cannot close the clause."""
        assert quote_filter_value('a"|"b') == '"a\\"|\\"b"'

    def test_backslash_is_escaped(self):
        """A backslash is doubled so it cannot neutralize the escape of a quote."""
        assert quote_filter_value("a\\b") == '"a\\\\b"'

    def test_backslash_before_quote_keeps_the_quote_escaped(self):
        """Backslashes are escaped before quotes; the other order leaves the quote live."""
        expected = '"' + "a" + "\\\\" + '\\"' + "b" + '"'
        assert quote_filter_value('a\\"b') == expected


class TestFilterValueWithQuotesSendsOneClause:
    """A value shaped like an injected OR clause reaches the API as one clause (R3.6)."""

    @respx.mock
    async def test_devices_name_filter_with_quotes_sends_one_clause(self, client):
        """get_devices sends exactly one displayName clause for a value holding quotes."""
        from lm_mcp.tools.devices import get_devices

        route = respx.get("https://test.logicmonitor.com/santaba/rest/device/devices").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )

        await get_devices(client, name_filter='a"|"b')

        params = dict(route.calls[0].request.url.params)
        assert params["filter"] == 'displayName~"a\\"|\\"b"'
        assert params["filter"].count("displayName") == 1

    @respx.mock
    async def test_create_datasource_overwrite_lookup_quotes_the_name(self, client, enable_writes):
        """The overwrite lookup by name goes through quote_filter_value."""
        from lm_mcp.tools.datasources import create_datasource

        lookup = respx.get("https://test.logicmonitor.com/santaba/rest/setting/datasources").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0})
        )
        respx.post("https://test.logicmonitor.com/santaba/rest/setting/datasources").mock(
            return_value=httpx.Response(200, json={"id": 7, "name": 'a"|"b'})
        )

        definition = {"name": 'a"|"b', "collectMethod": "script"}
        await create_datasource(client, definition, overwrite=True)

        params = dict(lookup.calls[0].request.url.params)
        assert params["filter"] == 'name:"a\\"|\\"b"'
