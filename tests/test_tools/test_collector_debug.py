# Description: Tests for the collector_debug tool, its command builder, guards and parser.
# Description: Synthetic replies only, shaped like the collector's text format.
# ruff: noqa: E501  (fixture text and expected command lines are kept on one line to stay readable)

import json

import httpx
import pytest
import respx

from lm_mcp.auth.bearer import BearerAuth
from lm_mcp.client import LogicMonitorClient
from lm_mcp.tools import collector_debug as cd
from lm_mcp.tools.collector_debug import (
    BLOCKED,
    COMMANDS,
    ToolRejectionError,
    build_cmdline,
    check_cmdline,
    collector_debug,
    parse_health_check,
)

BASE = "https://test.logicmonitor.com/santaba/rest"

HEALTH = """
==========================$Internal Collector Status==========================
is scheduled at Mon Jan 05 10:00:00 UTC 2026, finished at Mon Jan 05 10:00:01 UTC 2026, status 0
summary:
detail:
:checkpoints:[
  {"name": "module.Collector", "detail": "The collector is alive.", "status": "OK"},
  {"name": "module.Watchdog", "detail": "The collector watchdog is alive.", "status": "OK"}
]

==========================Agent_Check0002_DataCollectorPerformanceCheck.groovy==========================
is scheduled at Mon Jan 05 10:00:02 UTC 2026, finished at Mon Jan 05 10:00:03 UTC 2026, status 0
summary:
detail:
:checkpoints:[
  {"name": "biz.DataSource.BATCHSCRIPT", "detail": "60 of 500 tasks (12.00%) returned NaN for all datapoints.", "status": "OK"},
  {"name": "biz.DataSource.WMI", "detail": "10 of 400 tasks (2.50%) returned NaN for all datapoints.", "status": "OK"},
  {"name": "biz.DataSource.SNMP", "detail": "No tasks", "status": "OK"},
  {"name": "biz.DataSource.PING", "detail": "0 of 100 tasks (0.00%) returned NaN for all datapoints.", "status": "OK"}
]

==========================Agent_Check0012_DiskUsageCheck.groovy==========================
is scheduled at Mon Jan 05 10:00:04 UTC 2026, finished at Mon Jan 05 10:00:05 UTC 2026, status 1
summary:
detail: synthetic
:checkpoints:[{"name": "basic.Disk", "detail": "Free disk is 2 MBytes", "status": "WARN"}]

==========================Agent_Check0033_CollectorWorkLoad.groovy==========================
is scheduled at Mon Jan 05 10:00:06 UTC 2026, finished at Mon Jan 05 10:00:07 UTC 2026, status 0
summary:
detail: synthetic
:checkpoints:[
  {"name": "biz.InstanceCount", "detail": "The collector has 900 instances", "status": "OK"},
  {"name": "basic.Version", "detail": "Collector #7 version is 39200 and size Medium", "status": "OK"}
]

==========================Agent_Check0041_CogsPerformanceCheck.groovy==========================
is scheduled at Mon Jan 05 10:00:08 UTC 2026, finished at Mon Jan 05 10:00:09 UTC 2026, status 0
summary:
detail:
:checkpoints:[
  {"name": "cogs.DSTableByNan", "detail": [
    {"nanDsi": 3, "dsName": "Example_Module_B", "timeoutDsi": 0, "droppedDsi": 0, "collectorName": "wmi"},
    {"nanDsi": 40, "dsName": "Example_Module_A", "timeoutDsi": 2, "droppedDsi": 0, "collectorName": "batchscript"},
    {"nanDsi": 0, "dsName": "Example_Module_C", "timeoutDsi": 0, "droppedDsi": 0, "collectorName": "ping"}
  ], "status": "OK"}
]
"""


@pytest.fixture
def client():
    return LogicMonitorClient(
        base_url=BASE, auth=BearerAuth("test-token"), timeout=30, api_version=3
    )


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(cd, "POLL_SECONDS", 0.01)
    cd._POSTS.clear()
    cd._GETS.clear()


class TestBuilder:
    @pytest.mark.parametrize(
        "command,args,expected",
        [
            ("uptime", {}, "!uptime"),
            ("health_check", {}, "!shealthcheck func=detail collector=7"),
            ("perf", {}, "!perf type=ds dsFilterColumn=nan"),
            ("perf", {"h": "device-example-*"}, "!perf type=ds dsFilterColumn=nan h=device-example-*"),
            ("perf", {"type": "queue"}, "!perf type=queue"),
            ("getconfig", {"key": "wmi.threadpool"}, "!getconfig wmi.threadpool"),
            ("ping", {"host": "10.0.0.5", "count": 4}, "!ping count=4 10.0.0.5"),
            ("nslookup", {"host": "device-example-1", "extra_hosts": ["device-example-1.example.net"]},
             "!nslookup device-example-1 device-example-1.example.net"),
            ("snmpdiagnose", {"host": "10.0.0.5"}, "!snmpdiagnose 10.0.0.5"),
            ("snmpget", {"host": "10.0.0.5", "oids": [".1.3.6.1.2.1.1.5.0"]}, "!snmpget 10.0.0.5 .1.3.6.1.2.1.1.5.0"),
            ("snmpwalk", {"host": "10.0.0.5"}, "!snmpwalk 10.0.0.5 .1.3.6.1.2.1.1"),
            ("wmi", {"host": "10.0.0.5"}, "!wmi h=10.0.0.5 select * from Win32_Service"),
            ("winrm", {"host": "10.0.0.5", "useSSL": "false"}, "!winrm host=10.0.0.5 useSSL=false"),
            ("cim", {"host": "10.0.0.5", "class": "CIM_ComputerSystem"}, "!cim h=10.0.0.5 c=CIM_ComputerSystem"),
            ("http", {"url": "https://device-example-1.example.net/health"}, "!http https://device-example-1.example.net/health"),
            ("sslcerts", {"host": "10.0.0.5", "port": 443}, "!sslcerts 10.0.0.5 443"),
            ("tlist", {"h": "10.0.0.5"}, "!tlist h=10.0.0.5"),
            ("aplist", {}, "!aplist status=failed"),
            ("splist", {"hostname": "device-example-1"}, "!splist hostname=device-example-1"),
            ("logsurf", {"files": ["wrapper.log", "watchdog.log"]}, "!logsurf level=error n=50 wrapper.log watchdog.log"),
            ("checkserverconnectivity", {"host": "portal-a.example.net"}, "!checkserverconnectivity portal-a.example.net"),
        ],
    )  # fmt: skip
    def test_composes_the_documented_shape(self, command, args, expected):
        assert build_cmdline(command, args, 7) == expected

    @pytest.mark.parametrize(
        "command,args,why",
        [
            ("groovy", {}, "unknown or disallowed"),
            ("ping", {}, "'host' is required"),
            ("ping", {"host": "10.0.0.5; !restart"}, "hostname or IP"),
            ("ping", {"host": "10.0.0.5 !restart"}, "hostname or IP"),
            ("snmpwalk", {"host": "10.0.0.5", "oid": ".1"}, "root of the tree"),
            ("snmpwalk", {"host": "10.0.0.5", "oid": "1.3.6.1"}, "root of the tree"),
            ("tlist", {}, "must be filtered"),
            ("http", {"url": "device-example-1"}, "http:// or https://"),
            ("sslcerts", {"host": "10.0.0.5"}, "'port' is required"),
            ("wmi", {"host": "10.0.0.5", "query": "delete from x"}, "SELECT"),
            ("wmi", {"host": "10.0.0.5", "query": "select a from b; select c from d"}, "SELECT"),
            ("logsurf", {"files": ["../secrets.txt"]}, "may only name"),
            ("perf", {"type": "cpu", "dsFilterColumn": "nan"}, "only to type=ds"),
            ("ping", {"host": "10.0.0.5", "count": 500}, "between"),
        ],
    )
    def test_refuses_before_sending(self, command, args, why):
        with pytest.raises(ToolRejectionError, match=why):
            build_cmdline(command, args, 7)

    def test_registry_enum_matches_the_safe_set(self):
        from lm_mcp.registry import TOOLS

        tool = next(t for t in TOOLS if t.name == "collector_debug")
        assert sorted(tool.inputSchema["properties"]["command"]["enum"]) == sorted(COMMANDS)

    def test_no_allowlisted_command_is_blocked(self):
        for name in COMMANDS:
            assert name not in BLOCKED

    @pytest.mark.parametrize(
        "line",
        [
            "!groovy println 1",
            "!restart",
            "!shealthcheck func=detail collector=7\n!restart",
            "!wmi username=x password=y h=10.0.0.5 select * from a",
            "!snmpwalk community=public 10.0.0.5 .1.3.6.1.2.1.1",
            "uptime",
        ],
    )
    def test_final_guard(self, line):
        with pytest.raises(ToolRejectionError):
            check_cmdline(line)


class TestParser:
    def test_rates_lead_and_are_sorted(self):
        p = parse_health_check(HEALTH)
        assert [m["method"] for m in p["methods_by_all_nan_rate"]] == ["BATCHSCRIPT", "WMI", "PING"]
        top = p["methods_by_all_nan_rate"][0]
        assert (top["all_nan"], top["attempts"], top["all_nan_pct"]) == (60, 500, 12.0)
        assert top["checkpoint_status"] == "OK"
        assert p["idle_methods"] == ["SNMP"]

    def test_not_ok_includes_warn_checkpoints_and_failed_scripts(self):
        p = parse_health_check(HEALTH)
        checks = {(n["check"], n.get("status")) for n in p["not_ok"]}
        assert ("basic.Disk", "WARN") in checks
        assert any("script status 1" in str(n.get("detail")) for n in p["not_ok"])

    def test_modules_by_nan_and_facts(self):
        p = parse_health_check(HEALTH)
        assert [m["module"] for m in p["nan_by_module"]] == ["Example_Module_A", "Example_Module_B"]
        assert p["facts"]["biz.InstanceCount"] == "The collector has 900 instances"
        assert p["last_run_started"].startswith("Mon Jan 05 10:00:00")
        assert p["checks_parsed"] == 5

    def test_truncated_reply_does_not_break_the_parse(self):
        p = parse_health_check(HEALTH[: len(HEALTH) - 120])
        assert p["methods_by_all_nan_rate"]
        assert p["nan_by_module"] == []

    def test_empty_reply(self):
        assert parse_health_check("")["checks_parsed"] == 0


def mount(replies=None, post_error=None, inverted=False, device=None, busy_gets=0):
    """Synthetic debug API. replies maps a command prefix to its output, or 'slow'.

    busy_gets: the first N reads fail with the portal's still-working error.
    """
    seen = []
    gets = [0]

    def handler(request: httpx.Request):
        path = request.url.path.replace("/santaba/rest", "")
        params = dict(request.url.params)
        if request.method == "POST" and path == "/debug":
            body = json.loads(request.content)
            seen.append(body["cmdline"])
            if post_error:
                return httpx.Response(post_error[0], json={"errorMessage": post_error[1]})
            return httpx.Response(200, json={"sessionId": "s1"})
        if path == "/debug/s1":
            gets[0] += 1
            if gets[0] <= busy_gets:
                return httpx.Response(
                    400, json={"errorMessage": "agent has fetched the task, waiting for response"}
                )
            line = seen[-1]
            out = next((v for k, v in (replies or {}).items() if line.startswith(k)), "ok")
            if out == "slow":
                return httpx.Response(200, json={"output": "pending"})
            with_id = "collectorId" in params
            if with_id != inverted:
                return httpx.Response(200, json={"output": "cancelled"})
            return httpx.Response(200, json={"output": out})
        if path.startswith("/device/devices/") and device:
            return httpx.Response(200, json=device)
        return httpx.Response(404, json={"errorMessage": "unmocked"})

    respx.route(host="test.logicmonitor.com").mock(side_effect=handler)
    return seen


async def run(client, **kw):
    return json.loads((await collector_debug(client, **kw))[0].text)


class TestTool:
    @respx.mock
    async def test_answers_and_parses_the_health_check(self, client):
        seen = mount({"!shealthcheck": HEALTH})
        data = await run(client, command="health_check", collector_id=7)
        assert data["status"] == "answered"
        assert seen == ["!shealthcheck func=detail collector=7"]
        assert data["cmdline"] == seen[0]
        assert data["parsed"]["methods_by_all_nan_rate"][0]["method"] == "BATCHSCRIPT"
        assert data["output_chars"] == len(HEALTH)
        assert data["read_form"] in ("with", "without")

    @respx.mock
    async def test_either_get_form_can_be_the_one_that_answers(self, client):
        mount({"!uptime": "uptime=1h 2m"}, inverted=True)
        data = await run(client, command="uptime", collector_id=7)
        assert data["status"] == "answered" and "uptime=1h" in data["output"]

    @respx.mock
    async def test_device_id_fills_host_and_collector(self, client):
        seen = mount(
            {"!ping": "Sent: 10, Recv: 10"},
            device={"id": 42, "name": "10.0.0.42", "currentCollectorId": 7},
        )
        data = await run(client, command="ping", device_id=42)
        assert seen == ["!ping 10.0.0.42"]
        assert data["collector_id"] == 7 and data["device"]["host_used"] == "10.0.0.42"

    @respx.mock
    async def test_usage_reply_is_flagged_as_the_commands_fault(self, client):
        mount({"!sslcerts": "Usage: !sslcerts [timeout=XX] host port"})
        data = await run(
            client, command="sslcerts", collector_id=7, args={"host": "10.0.0.5", "port": 443}
        )
        assert data["status"] == "answered" and "not the device" in data["note"]

    @respx.mock
    async def test_no_reply_inside_the_budget(self, client):
        mount({"!uptime": "slow"})
        data = await run(client, command="uptime", collector_id=7, budget_seconds=2)
        assert data["status"] == "no_reply" and "pending" in data["detail"]
        assert data["elapsed_ms"] < 3500

    @respx.mock
    async def test_unknown_config_key_is_flagged(self, client):
        mount({"!getconfig": "Configuration key [wmi.threadpool] not found in setting"})
        data = await run(
            client, command="getconfig", collector_id=7, args={"key": "wmi.threadpool"}
        )
        assert data["status"] == "answered" and "agent.conf key" in data["note"]

    @respx.mock
    async def test_still_working_error_keeps_polling(self, client):
        mount({"!ping": "Sent: 4, Recv: 4"}, busy_gets=2, inverted=True)
        data = await run(client, command="ping", collector_id=7, args={"host": "10.0.0.9"})
        assert data["status"] == "answered" and "Recv: 4" in data["output"]

    @respx.mock
    async def test_still_working_until_the_budget_is_no_reply(self, client):
        mount({"!ping": "Sent: 4, Recv: 4"}, busy_gets=10**6)
        data = await run(
            client, command="ping", collector_id=7, args={"host": "10.0.0.9"}, budget_seconds=2
        )
        assert data["status"] == "no_reply", data
        assert "waiting for response" in data["detail"]

    @respx.mock
    async def test_refused_without_debug_permission(self, client):
        mount(post_error=(403, "Permission denied"))
        data = await run(client, command="uptime", collector_id=7)
        assert data["status"] == "refused"

    @respx.mock
    async def test_unknown_debug_command_is_unsupported(self, client):
        mount(post_error=(400, "Unknown debug command !nsplist"))
        data = await run(client, command="nsplist", collector_id=7)
        assert data["status"] == "unsupported"

    @respx.mock
    async def test_debug_disabled_on_the_collector(self, client):
        mount(post_error=(400, "remote debug is disabled on this collector"))
        data = await run(client, command="uptime", collector_id=7)
        assert data["status"] == "disabled"

    async def test_unknown_command_lists_the_safe_set(self, client):
        data = await run(client, command="restart", collector_id=7)
        assert data["status"] == "rejected_by_tool" and "uptime" in data["commands"]

    async def test_collector_is_required(self, client):
        data = await run(client, command="uptime")
        assert data["status"] == "rejected_by_tool"

    async def test_rejection_sends_nothing(self, client):
        with respx.mock(assert_all_called=False) as router:
            route = router.route(host="test.logicmonitor.com").mock(httpx.Response(200, json={}))
            data = await run(client, command="tlist", collector_id=7, args={})
            assert data["status"] == "rejected_by_tool"
            assert route.call_count == 0

    @respx.mock
    async def test_own_rate_budget(self, client, monkeypatch):
        monkeypatch.setattr(cd, "POST_LIMIT", 0)
        mount()
        data = await run(client, command="uptime", collector_id=7)
        assert data["status"] == "rate_limited"
