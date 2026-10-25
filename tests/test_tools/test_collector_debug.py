# Description: Tests for the collector_debug tool, its command builder, guards and parser.
# Description: Synthetic replies only, shaped like the collector's text format.
# ruff: noqa: E501  (fixture text and expected command lines are kept on one line to stay readable)

import asyncio
import json
import time

import httpx
import pytest
import respx

from lm_mcp.auth.bearer import BearerAuth
from lm_mcp.client import LogicMonitorClient
from lm_mcp.tools import collector_debug as cd
from lm_mcp.tools.collector_debug import (
    BLOCKED,
    COMMANDS,
    OUTPUT_MAX,
    Target,
    ToolRejectionError,
    build_cmdline,
    check_cmdline,
    collector_debug,
    parse_health_check,
    redact,
)

BASE = "https://test.logicmonitor.com/santaba/rest"
# Built in two parts, so the repository's private-key hook does not read a test as a key.
PEM_BEGIN = "-----BEGIN RSA " + "PRIVATE KEY-----"
PEM_END = "-----END RSA " + "PRIVATE KEY-----"
PGP_BEGIN = "-----BEGIN PGP " + "PRIVATE KEY BLOCK-----"

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
    monkeypatch.setattr(cd, "_READ_FORMS", {})
    cd._POSTS.clear()
    cd._GETS.clear()


def _set_writes(monkeypatch, enabled):
    from importlib import reload

    import lm_mcp.config

    monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
    monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
    monkeypatch.setenv("LM_ENABLE_WRITE_OPERATIONS", "true" if enabled else "false")
    reload(lm_mcp.config)


@pytest.fixture
def writes(monkeypatch):
    _set_writes(monkeypatch, True)


T = Target(collector_id=7, host="10.0.0.5", portal_host="portal-a.example.net")


def assert_linear(work, make, small: int = 50_000, large: int = 200_000) -> None:
    """Four times the input takes about four times as long; a square would take sixteen.

    The best of three runs at each size is compared, the margin is wide for a loaded machine,
    and a small run under 10 ms counts as 10 ms, so timer noise on tiny runs does not decide.
    """

    def best(text: str) -> float:
        times = []
        for _ in range(3):
            started = time.perf_counter()
            work(text)
            times.append(time.perf_counter() - started)
        return min(times)

    fast, slow = best(make(small)), best(make(large))
    assert slow < 5.0, (fast, slow)
    assert slow / max(fast, 0.01) < 8, (fast, slow)


NO_DEVICE = Target(collector_id=7, portal_host="portal-a.example.net")


class TestBuilder:
    @pytest.mark.parametrize(
        "command,args,expected",
        [
            ("uptime", {}, "!uptime"),
            ("health_check", {}, "!shealthcheck func=detail collector=7"),
            ("perf", {}, "!perf type=ds dsFilterColumn=nan"),
            ("perf", {"h": "device-example-*"}, "!perf type=ds dsFilterColumn=nan h=device-example-*"),
            ("perf", {"type": "queue"}, "!perf type=queue"),
            ("getconfig", {"key": "collector.wmi.threadpool"}, "!getconfig collector.wmi.threadpool"),
            ("getconfig", {"key": "collector.snmp.timeout"}, "!getconfig collector.snmp.timeout"),
            ("ping", {"count": 4}, "!ping count=4 10.0.0.5"),
            ("nslookup", {}, "!nslookup 10.0.0.5"),
            ("snmpdiagnose", {}, "!snmpdiagnose 10.0.0.5"),
            ("snmpget", {"oids": [".1.3.6.1.2.1.1.5.0"]}, "!snmpget 10.0.0.5 .1.3.6.1.2.1.1.5.0"),
            ("snmpwalk", {}, "!snmpwalk 10.0.0.5 .1.3.6.1.2.1.1"),
            ("wmi", {}, "!wmi h=10.0.0.5 select * from Win32_Service"),
            ("wmi", {"query": "SELECT Name, State FROM Win32_Service WHERE Name = 'Spooler'"},
             "!wmi h=10.0.0.5 SELECT Name, State FROM Win32_Service WHERE Name = 'Spooler'"),
            ("wmi", {"query": "select * from Win32_Service where State != 'Running'"},
             "!wmi h=10.0.0.5 select * from Win32_Service where State != 'Running'"),
            ("winrm", {"useSSL": "false"}, "!winrm host=10.0.0.5 useSSL=false"),
            ("cim", {"class": "CIM_ComputerSystem"}, "!cim h=10.0.0.5 c=CIM_ComputerSystem"),
            ("http", {"url": "https://10.0.0.5/health"}, "!http https://10.0.0.5/health"),
            ("http", {"url": "http://10.0.0.5:8080/status?verbose=1"}, "!http http://10.0.0.5:8080/status?verbose=1"),
            ("sslcerts", {"port": 443}, "!sslcerts 10.0.0.5 443"),
            ("tlist", {"h": "10.0.0.5"}, "!tlist h=10.0.0.5"),
            ("aplist", {}, "!aplist status=failed"),
            ("splist", {"hostname": "device-example-1"}, "!splist hostname=device-example-1"),
            ("logsurf", {"files": ["wrapper.log", "watchdog.log"]}, "!logsurf level=error n=50 wrapper.log watchdog.log"),
            ("checkserverconnectivity", {}, "!checkserverconnectivity portal-a.example.net"),
            ("reportercache", {}, "!reportercache"), ("avslist", {}, "!avslist"),
            ("firewallstatus", {}, "!firewallstatus"), ("ipaddress", {}, "!ipaddress"),
            ("tasklist", {}, "!tasklist"), ("adlist", {}, "!adlist"), ("nsplist", {}, "!nsplist"),
            ("dxlist", {}, "!dxlist"), ("tplist", {}, "!tplist"), ("macaddress", {}, "!macaddress 10.0.0.5"),
            ("wmi", {"query": "select * from Win32_Process where User = 'svc'"},
             "!wmi h=10.0.0.5 select * from Win32_Process where User = 'svc'"),
            ("snmpwalk", {"oid": ".1.3.6.1.2.1.2"}, "!snmpwalk 10.0.0.5 .1.3.6.1.2.1.2"),
            ("logsurf", {"n": ""}, "!logsurf level=error n=50 wrapper.log"),
            ("logsurf", {"files": ["wrapper.log", "wrapper.log"]}, "!logsurf level=error n=50 wrapper.log"),
            ("http", {"url": "https://10.0.0.5/x?author=a&oauth_state=b&sessions=3&page=2"},
             "!http https://10.0.0.5/x?author=a&oauth_state=b&sessions=3&page=2"),
        ],
    )  # fmt: skip
    def test_composes_the_documented_shape(self, command, args, expected):
        assert build_cmdline(command, args, T) == expected

    @pytest.mark.parametrize(
        "command,args,target,why",
        [
            ("groovy", {}, T, "unknown or disallowed"),
            # Item 2: the target host comes from the device record only.
            ("ping", {}, NO_DEVICE, "device_id is required"),
            ("ping", {"host": "10.0.0.9"}, T, "'host' is not accepted"),
            ("snmpwalk", {"host": "10.0.0.9"}, T, "'host' is not accepted"),
            # Item 4: the portal check is pinned to the configured portal.
            ("checkserverconnectivity", {"host": "attacker.example.net"}, T, "'host' is not accepted"),
            ("checkserverconnectivity", {}, Target(collector_id=7), "portal host is not known"),
            # Item 7: unknown keys are refused per command.
            ("ping", {"bogus": "x", "community": "public"}, T, "ping takes count, type; not bogus, community"),
            ("uptime", {"verbose": True}, T, "uptime takes no arguments; not verbose"),
            ("nslookup", {"extra_hosts": ["other.example.net"]}, T, "not extra_hosts"),
            ("snmpwalk", {"oid": ".1"}, T, "root of the tree"),
            ("snmpwalk", {"oid": "1.3.6.1"}, T, "root of the tree"),
            ("tlist", {}, T, "must be filtered"),
            # Item 3: the URL must name the device, with no credentials.
            ("http", {"url": "10.0.0.5"}, T, "http:// or https://"),
            ("http", {"url": "ftp://10.0.0.5/x"}, T, "http:// or https://"),
            ("http", {"url": "http://169.254.169.254/latest/meta-data/"}, T, "must point at the device itself"),
            ("http", {"url": "https://device-example-2.example.net/"}, T, "must point at the device itself"),
            ("http", {"url": "https://admin:s3cret@10.0.0.5/"}, T, "user information"),
            ("http", {"url": "https://admin@10.0.0.5/"}, T, "user information"),
            ("http", {"url": "https://10.0.0.5/?password=s3cret"}, T, "credential-named parameter 'password'"),
            ("http", {"url": "https://10.0.0.5/x?a=1&apiKey=s3cret"}, T, "credential-named parameter 'apiKey'"),
            ("http", {"url": "https://10.0.0.5/x?access_token=s3cret"}, T, "credential-named parameter"),
            ("http", {"url": "https://10.0.0.5/x?user_name=admin"}, T, "credential-named parameter"),
            ("http", {"url": "https://10.0.0.5:99999/"}, T, "not a valid URL"),
            ("http", {"url": "http:///x"}, T, "must name the device's host"),
            ("http", {"url": "https://10.0.0.5/a b"}, T, "whitespace"),
            ("http", {}, T, "'url' is required"),
            ("sslcerts", {}, T, "'port' is required"),
            # Item 8: one anchored WQL SELECT, never a key=value token.
            ("wmi", {"query": "delete from x"}, T, "one WQL SELECT"),
            ("wmi", {"query": "select a from b; select c from d"}, T, "one WQL SELECT"),
            ("wmi", {"query": "select * from Win32_Service h=evilhost"}, T, "one WQL SELECT"),
            ("wmi", {"query": "select * from Win32_Service where Name = 'x' h=evilhost"}, T, "key=value"),
            ("wmi", {"query": "select * from Win32_Service where Name='x'"}, T, "key=value"),
            ("wmi", {"query": "select * from Win32_Service where Name = `x`"}, T, "character the tool does not allow"),
            # Item 9: getconfig reads only thread-pool and timeout keys.
            ("getconfig", {"key": "proxy.pass"}, T, "thread pool or timeout"),
            ("getconfig", {"key": "collector.wmi.threadpool.x"}, T, "thread pool or timeout"),
            ("getconfig", {"key": "wmi.threadpool"}, T, "thread pool or timeout"),
            ("getconfig", {}, T, "'key' is required"),
            ("logsurf", {"files": ["../secrets.txt"]}, T, "may only name"),
            ("perf", {"type": "cpu", "dsFilterColumn": "nan"}, T, "only to type=ds"),
            ("ping", {"count": 500}, T, "between"),
            ("ping", {"count": True}, T, "whole number"),
            ("snmpwalk", {"oid": "1.03.6.1"}, T, "invalid value"),
            ("snmpwalk", {"oid": ".1.3.6.01"}, T, "invalid value"),
            ("snmpwalk", {"oid": "\u0661.\u0663.\u0666.\u0661"}, T, "invalid value"),
            ("snmpwalk", {"oid": ".1.3.6.1."}, T, "invalid value"),
            ("http", {"url": "http://10.0.0.5/#key=abc"}, T, "fragment"),
            ("http", {"url": "http://10.0.0.5/x;pw=1"}, T, "';' parameters"),
            ("http", {"url": "http://10.0.0.5/x?a=1;pw=x"}, T, "';' parameters"),
            ("http", {"url": "http://10.0.0.5/x?authorization=abc"}, T, "credential-named parameter"),
            ("http", {"url": "http://10.0.0.5/x?authCode=abc"}, T, "credential-named parameter 'authCode'"),
            ("http", {"url": "http://10.0.0.5/a\x00b"}, T, "printable ASCII"),
            ("http", {"url": "http://10.0.0.5/a\x7fb"}, T, "printable ASCII"),
            ("http", {"url": "http://10.0.0.5/?q=\u202e"}, T, "printable ASCII"),
            ("ping", {"count": float("inf")}, T, "whole number"),
            ("sslcerts", {"port": 1.5}, T, "whole number"),
            ("snmpget", {"oids": [f".1.3.6.1.2.1.1.{i}.0" for i in range(11)]}, T, "1 to 10 values"),
            ("snmpdiagnose", {"oids": [f".1.3.6.1.2.1.1.{i}.0" for i in range(6)]}, T, "0 to 5 values"),
            ("http", {"url": "http://10.0.0.5/x?pw=1"}, T, "credential-named parameter 'pw'"),
            ("http", {"url": "http://10.0.0.5/x?jwt=1"}, T, "credential-named parameter 'jwt'"),
            ("http", {"url": "http://10.0.0.5/x?sid=1"}, T, "credential-named parameter 'sid'"),
            ("http", {"url": "http://10.0.0.5/x?bearer=1"}, T, "credential-named parameter 'bearer'"),
            ("http", {"url": "http://10.0.0.5/x?auth=1"}, T, "credential-named parameter 'auth'"),
            ("http", {"url": "http://10.0.0.5/x?accessToken=1"}, T, "credential-named parameter"),
            ("http", {"url": "http://10.0.0.5/" + "a" * 2100}, T, "longer than 2048"),
            ("logsurf", {"files": {"wrapper.log": 1}}, T, "must be a list"),
            # every list item and every enumerated value is checked, so none can add a parameter
            ("snmpget", {"oids": ["h=x"]}, T, "not a valid value for 'oids'"),
            ("snmpdiagnose", {"oids": [".1.3.6.1.2.1.1.5.0", "h=x"]}, T, "not a valid value for 'oids'"),
            ("ping", {"type": "all h=x"}, T, "'type' must be one of"),
            ("perf", {"h": "x h=y"}, T, "'h' has an invalid value"),
        ],
    )  # fmt: skip
    def test_refuses_before_sending(self, command, args, target, why):
        with pytest.raises(ToolRejectionError, match=why):
            build_cmdline(command, args, target)

    @pytest.mark.parametrize(
        "host,url",
        [
            ("device-example-1.example.net", "https://DEVICE-EXAMPLE-1.example.net/health"),
            ("fe80::1", "https://[fe80::1]:8443/health"),
            ("[fe80::1]", "https://[FE80::1]/health"),
            ("DEVICE-EXAMPLE-1.example.net", "https://device-example-1.example.net/health"),
        ],
    )
    def test_url_host_match_ignores_case_and_brackets(self, host, url):
        target = Target(collector_id=7, host=host)
        assert build_cmdline("http", {"url": url}, target) == f"!http {url}"

    def test_url_with_a_trailing_dot_host_is_another_host(self):
        with pytest.raises(ToolRejectionError, match="device itself"):
            build_cmdline("http", {"url": "https://10.0.0.5./"}, T)

    def test_debughistory_is_not_offered(self):
        assert "debughistory" not in COMMANDS

    def test_registry_enum_matches_the_safe_set(self):
        from lm_mcp.registry import TOOLS

        tool = next(t for t in TOOLS if t.name == "collector_debug")
        assert sorted(tool.inputSchema["properties"]["command"]["enum"]) == sorted(COMMANDS)

    def test_registry_documents_every_commands_keys(self):
        """Item 7: each command's argument keys are named in the schema's args text."""
        from lm_mcp.registry import TOOLS

        tool = next(t for t in TOOLS if t.name == "collector_debug")
        import re

        text = tool.inputSchema["properties"]["args"]["description"]
        documented = {}
        for name, keys_text in re.findall(r"(?:^|\. )([a-z_]+): ([^.]+)", text):
            # "type (ds|queue|cpu), dsFilterColumn" -> {"type", "dsFilterColumn"}
            words = re.findall(r"\b([A-Za-z]+)\b(?![^(]*\))", keys_text)
            documented[name] = {w for w in words if w in COMMANDS.get(name, (0, 0, 0, set()))[3]}
        for name, (_g, _dev, _b, keys, _d) in COMMANDS.items():
            assert documented.get(name, set()) == set(keys), (name, documented.get(name), keys)

    def test_registry_lists_it_as_a_write(self):
        """Item 1: annotated as a write, so it lists under the write category."""
        from lm_mcp.categories import categorize
        from lm_mcp.registry import TOOLS

        tool = next(t for t in TOOLS if t.name == "collector_debug")
        assert tool.annotations.readOnlyHint is False
        assert "write" in categorize(tool)
        assert "read" not in categorize(tool)

    def test_no_allowlisted_head_is_blocked(self):
        assert not (cd.ALLOWED_HEADS & BLOCKED)

    @pytest.mark.parametrize(
        "line",
        [
            "!groovy println 1",
            "!restart",
            "!shealthcheck func=detail collector=7\n!restart",
            "!wmi username=x password=y h=10.0.0.5 select * from a",
            "!snmpwalk community=public 10.0.0.5 .1.3.6.1.2.1.1",
            "!http https://10.0.0.5/?password=s3cret",
            "!http https://10.0.0.5/?x=1&token=s3cret",
            "uptime",
            # the transport's own check is an allowlist, with the two fixed forms
            "!debughistory",
            "!getconfig proxy.pass",
            "!shealthcheck func=trigger",
            "!shealthcheck func=detail collector=7 extra",
            " !uptime",
        ],
    )
    def test_final_guard(self, line):
        with pytest.raises(ToolRejectionError):
            check_cmdline(line)


class TestRedaction:
    @pytest.mark.parametrize(
        "text,expected",
        [
            # an unquoted value runs to the line end, or to where the next key= or key: starts
            ("password=abc next", "password=***"),
            ("wmi.pass=my secret pass", "wmi.pass=***"),
            ("wmi.pass=hun,ter2 next", "wmi.pass=***"),
            ("password=hun;ter2", "password=***"),
            ("password=abc, user=x", "password=***, user=x"),
            ("token=x,secret=y;apikey=z", "token=***,secret=***;apikey=***"),
            ("clientSecret=a aws.secretKey=b apiToken=c", "clientSecret=*** aws.secretKey=*** apiToken=***"),
            ("-Dpassword=s3cret -Dwmi.pass=x", "-Dpassword=*** -Dwmi.pass=***"),
            ("accessToken: x dbPassword=y", "accessToken: ***"),
            ("password=x dbPassword=y", "password=*** dbPassword=***"),
            ("password: hunter two", "password: ***"),
            ("password:hunter two", "password:***"),
            ("password = hunter two\nnext", "password = ***\nnext"),
            ("password: abc:def", "password: ***"),
            ("snmp.community: public", "snmp.community: ***"),
            ("ssh.pass: abc", "ssh.pass: ***"),
            ("wmi.pass=hunter2", "wmi.pass=***"),
            ("x dbPassword=y", "x dbPassword=***"),
            ("x-api-key: abc", "x-api-key: ***"),
            ("-Djavax.net.ssl.keyStorePassword=changeit", "-Djavax.net.ssl.keyStorePassword=***"),
            ("a.b.password=x ns:token=y", "a.b.password=*** ns:token=***"),
            ("user=alice state=Running", "user=alice state=Running"),
            # one-case compound keys, as LogicMonitor property names are case-insensitive
            ("wmiPass=x -Dpass=y x_pw=z x-pw=1", "wmiPass=*** -Dpass=*** x_pw=*** x-pw=***"),
            ("<ns:pw>x</ns:pw> SID=S-1-5-21-1", "<ns:pw>***</ns:pw> SID=S-1-5-21-1"),
            ("snmp.authtoken=hunter2", "snmp.authtoken=***"),
            ("SNMP.PRIVTOKEN: x", "SNMP.PRIVTOKEN: ***"),
            ("azure.clientsecret=x DBPASSWORD=y", "azure.clientsecret=*** DBPASSWORD=***"),
            ("snmpcommunity=x adminpassword=y", "snmpcommunity=*** adminpassword=***"),
            # quoted values, with escapes, on one line; an empty one is kept, as it is a finding
            ('authToken="a b c" tail', 'authToken="***" tail'),
            ('{"password": "s3cret"}', '{"password": "***"}'),
            ("'password': 'x'", "'password': '***'"),
            ('"api_key":"k1"', '"api_key":"***"'),
            ('"password":"hun\\"ter2", "x": 1', '"password":"***", "x": 1'),
            ('password="hun', "password=***"),
            ('password="', "password=***"),
            ("password=abc<br>next", "password=***<br>next"),
            ('password="a\nnext"', 'password=***\nnext"'),
            ('"password": ""', '"password": ""'),
            ("wmi.pass= wmi.user=admin", "wmi.pass= wmi.user=admin"),
            # an unquoted value inside a JSON string stops at that string's closing quote
            ('{"detail": "proxy pass: none", "status": "OK"}', '{"detail": "proxy pass: ***", "status": "OK"}'),
            ('{"token":null,"status":"ok"}', '{"token":***,"status":"ok"}'),
            # flags
            ("--password s3cret", "--password ***"),
            ('--password "two words" next', '--password "***" next'),
            ("--password hun ter2", "--password ***"),
            ("--Dpassword hunter2", "--Dpassword ***"),
            # headers and bearer tokens
            ("Authorization: Basic dXNlcjpw", "Authorization: ***"),
            ("Authorization: Bearer abc.def", "Authorization: ***"),
            ("Authorization: abc123", "Authorization: ***"),
            ("Authorization=Basic abc", "Authorization=***"),
            ('{"Authorization": "Bearer abc"}', '{"Authorization": "***"}'),
            ("log: Bearer abc.def ok", "log: Bearer *** ok"),
            # base64 padding never reads as the next key
            ("Authorization: Basic YWRtaW46aHVudGVyMg==", "Authorization: ***"),
            ("Authorization: Bearer abc123=", "Authorization: ***"),
            ("token: abc def==", "token: ***"),
            ("password: correct horse=battery", "password: ***"),
            ("password=abc def== user=x", "password=*** user=x"),
            # markup and JSON punctuation end a value, so the rest still reads true
            ('<add key="Conn" value="Server=x;Password=hunter2"/> <add key="Mode" value="prod"/>',
             '<add key="Conn" value="Server=x;Password=***"/> <add key="Mode" value="prod"/>'),
            ('<label for="password">Password:</label><input name="p">',
             '<label for="password">Password:</label><input name="p">'),
            ('{"token": null, "host": "h"}', '{"token": ***, "host": "h"}'),
            # single-dash flags, and the other words the URL check refuses
            ("keytool -storepass changeit -keypass x", "keytool -storepass *** -keypass ***"),
            ("https://h/x?sig=SECRETSIG&a=1", "https://h/x?sig=***&a=1"),
            ("pw=hunter2 otp=123456", "pw=*** otp=***"),
            ("curl -u admin:hunter2 https://h/ --user ops:s3cret", "curl -u admin:*** https://h/ --user ops:***"),
            # arrays and objects under a secret key, on one line or several
            ('{"snmp.community": ["public", "private", "s3cret"], "a": 1}', '{"snmp.community": ***, "a": 1}'),
            ('"password": [\n  "a",\n  "b"\n],\n"x": 1', '"password": ***,\n"x": 1'),
            ('{"token": {"v": "x", "w": ["y"]}}', '{"token": ***}'),
            ('{"a":{"password":1}}', '{"a":{"password":***}}'),
            # pwd as a key in every form, except a working directory
            ('{"pwd":"hunter2"} pwd: hunter2', '{"pwd":"***"} pwd: ***'),
            ("<pwd>hunter2</pwd>", "<pwd>***</pwd>"),
            ('<add key="pwd" value="x"/>', '<add key="pwd" value="***"/>'),
            ("pwd: ~/work pwd: C:\\Users", "pwd: ~/work pwd: C:\\Users"),
            # name and value as elements (Hadoop, Spring, .NET)
            ("<property><name>x.password</name><value>hunter2</value></property>",
             "<property><name>x.password</name><value>***</value></property>"),
            ("<entry>\n  <key>password</key>\n  <value>s3cret</value>\n</entry>",
             "<entry>\n  <key>password</key>\n  <value>***</value>\n</entry>"),
            ("<name>password</name><value><![CDATA[hunter2]]></value>",
             "<name>password</name><value>***</value>"),
            ("<name>password</name><value><string>hunter2</string></value>",
             "<name>password</name><value>***</value>"),
            ("<property><name>x.user</name><value>admin</value></property>",
             "<property><name>x.user</name><value>admin</value></property>"),
            # without braces, a value field is paired only with a nearby secret name
            ("name: token, value: 1\n" + "x " * 400 + "\nvalue: 2", "name: token, value: ***\n" + "x " * 400 + "\nvalue: 2"),
            # URL authority ends where an authority cannot go on
            ("url=http://10.0.0.5,owner=ops@example.net", "url=http://10.0.0.5,owner=ops@example.net"),
            ('{"url":"http://10.0.0.5","owner":"ops@example.net"}', '{"url":"http://10.0.0.5","owner":"ops@example.net"}'),
            ("https:\\/\\/admin:hunter2@10.0.0.5\\/x", "https:\\/\\/admin:***@10.0.0.5\\/x"),
            # stops at /> and a bearer word inside another word is not a bearer token
            ("<p password=x/>tail", "<p password=***/>tail"),
            ("forebearer note", "forebearer note"),
            # ODBC
            ("Driver=x;Pwd=hunter2;Uid=a", "Driver=x;Pwd=***;Uid=a"),
            ("pwd={hun;ter2};uid=a", "pwd=***;uid=a"),
            ("pwd = x", "pwd = ***"),
            # name/value pairs in one tag or object, in any order, across lines and fields
            ('<property name="wmi.pass" value="hunter2"/>', '<property name="wmi.pass" value="***"/>'),
            ('<property value="hunter2" name="wmi.pass"/>', '<property value="***" name="wmi.pass"/>'),
            ('<property name="password" type="string" value="hunter2"/>', '<property name="password" type="string" value="***"/>'),
            ('{"name": "wmi.pass", "value": "x"}', '{"name": "wmi.pass", "value": "***"}'),
            ('{"name":"wmi.pass","type":"custom","value":"hunter2"}', '{"name":"wmi.pass","type":"custom","value":"***"}'),
            ('{\n "name": "wmi.pass",\n "value": "hunter2"\n}', '{\n "name": "wmi.pass",\n "value": "***"\n}'),
            ('<p name="wmi.pass" value="x"/>next', '<p name="wmi.pass" value="***"/>next'),
            ('<property name="wmi.user" value="admin"/>', '<property name="wmi.user" value="admin"/>'),
            ('{"name": "wmi.pass", "value": ""}', '{"name": "wmi.pass", "value": ""}'),
            # inside one object or tag, the value goes with the name however far apart
            ('{"name":"db.password","description":"' + "d" * 600 + '","value":"hunter2"}',
             '{"name":"db.password","description":"' + "d" * 600 + '","value":"***"}'),
            ('<p name="db.password" note="' + "d" * 600 + '" value="hunter2"/>',
             '<p name="db.password" note="' + "d" * 600 + '" value="***"/>'),
            ('{"name":"' + "a" * 600 + '.password","value":"hunter2"}',
             '{"name":"' + "a" * 600 + '.password","value":"***"}'),
            ("authCode=x auth_code: y", "authCode=*** auth_code: ***"),
            ('name="wmi.pass" value=hunter2', 'name="wmi.pass" value=***'),
            ("key: wmi.pass, value: hunter2", "key: wmi.pass, value: ***"),
            # a value on the next, indented line
            ("password:\n  hunter2", "password:\n  ***"),
            ('{\n "password":\n   "x",\n "a": 1\n}', '{\n "password":\n   "***",\n "a": 1\n}'),
            ("password:\n  user: x", "password:\n  user: x"),
            ("password:\nnext", "password:\nnext"),
            # element content, by tag or by a name/key attribute: children, CDATA, line breaks
            ("<password>p1</password>", "<password>***</password>"),
            ("<snmp.community>c1</snmp.community>", "<snmp.community>***</snmp.community>"),
            ('<Password type="x">hunter2</Password>', '<Password type="x">***</Password>'),
            ('<entry key="wmi.pass">x</entry>', '<entry key="wmi.pass">***</entry>'),
            ('<entry key="wmi.pass"><value>x</value></entry>', '<entry key="wmi.pass">***</entry>'),
            ('<property name="password"><value>x</value></property>', '<property name="password">***</property>'),
            ("<password><![CDATA[x y]]></password>", "<password>***</password>"),
            ("<password>\n hunter2\n</password>", "<password>***</password>"),
            ("<ns:password>x</ns:password>", "<ns:password>***</ns:password>"),
            ("<password></password>", "<password></password>"),
            ('<entry key="wmi.user">admin</entry>', '<entry key="wmi.user">admin</entry>'),
            # URLs: userinfo is masked; a port and path that hold an '@' are left alone
            ("http://admin:s3cret@10.0.0.5/x", "http://admin:***@10.0.0.5/x"),
            ("http://u:p@ss@h/x", "http://u:***@h/x"),
            ("http://u:pa%2Fss@h/x", "http://u:***@h/x"),
            ("https://admin:123456@10.0.0.5/", "https://admin:***@10.0.0.5/"),
            ("https://tok123@10.0.0.5:8443/x@y", "https://***@10.0.0.5:8443/x@y"),
            ("https://admin:s3cret@10.0.0.5/api/users/bob@example.net", "https://admin:***@10.0.0.5/api/users/bob@example.net"),
            ("https://tok123@h/x", "https://***@h/x"),
            ("https://h/x?email=a@example.net", "https://h/x?email=a@example.net"),
            ("https://registry.example.net/@scope/pkg", "https://registry.example.net/@scope/pkg"),
            ("http://10.0.0.1:8080/api/users/admin@example.net", "http://10.0.0.1:8080/api/users/admin@example.net"),
            ("https://[fe80::1]:8443/a/b@c", "https://[fe80::1]:8443/a/b@c"),
            ("https://h/a:b@c", "https://h/a:b@c"),
            # private keys
            (f"{PEM_BEGIN}\nMIIabc\n{PEM_END}\nnext", f"{PEM_BEGIN}***{PEM_END}\nnext"),
            (f"{PGP_BEGIN}\nlQOYBF\n-----END PGP", f"{PGP_BEGIN}***-----END PGP"),
            # other credential words
            ("credential=abc signature=def", "credential=*** signature=***"),
            ("session_id=hunter2 jwt=x", "session_id=*** jwt=***"),
            # not secrets
            ("tokenizer=on passwordless=true superpass=x", "tokenizer=on passwordless=true superpass=x"),
            ("compass=north bypass=1 passes=3 tokens=5", "compass=north bypass=1 passes=3 tokens=5"),
            ("password=\nnext_line", "password=\nnext_line"),
            ("pwd: /usr/local/bin", "pwd: /usr/local/bin"),
        ],
    )  # fmt: skip
    def test_masks_secret_values(self, text, expected):
        assert redact(text) == expected

    @pytest.mark.parametrize(
        "key",
        ["password", "passwd", "pass", "passphrase", "secret", "token", "community", "credential",
         "credentials", "signature", "authorization", "cookie", "bearer", "apikey", "api_key",
         "api-key", "accesskey", "access_key", "access-key", "privatekey", "private_key",
         "private-key", "secretkey", "secret_key", "secret-key", "sessionid", "session_id",
         "session-id", "storepass", "keypass", "authcode", "auth_code", "auth-code", "jwt", "pw",
         "pwd", "sig", "otp"],
    )  # fmt: skip
    def test_each_credential_word_is_masked(self, key):
        """Written out, not read from the code, so dropping a word fails here."""
        assert redact(f"svc.{key}=hunter2") == f"svc.{key}=***"

    def test_long_values_fail_closed(self):
        """A value longer than a pattern reads is masked whole, not left in the clear."""
        long = "z" * 5000
        assert long not in redact(f'{{"name": "api.token", "value": "{long}"}}')
        assert long not in redact(f"<password>{long}</password>")
        assert long not in redact(f"<password>{long}<b>{long}</b></password>")
        assert "z" not in redact(f"<password>{long}")  # no closing tag at all
        assert "z" not in redact('"password": [' + '"z", ' * 2000 + "]")

    def test_values_parsed_from_output_are_masked(self):
        assert cd.redact_values({"a": ["password=x", {"b": "token: y"}], "n": 3}) == {
            "a": ["password=***", {"b": "token: ***"}],
            "n": 3,
        }

    def test_parsed_keys_and_name_value_pairs_are_masked(self):
        data = {
            "proxy.pass": "hunter2",
            "empty_password": "",
            "row": {"name": "wmi.pass", "value": "x"},
        }
        assert cd.redact_values(data) == {
            "proxy.pass": "***",
            "empty_password": "",
            "row": {"name": "wmi.pass", "value": "***"},
        }

    @pytest.mark.parametrize(
        "unit",
        ["-", "a-", "a_", "a=", "a:", "a://", 'x="', 'name="a-', "<a-", "<a ", "--a-", "a=b ",
         "pwd=", "pwd={;", "pwd={ ", "<password><![CDATA[", '<entry key="wmi.pass">', "<password>",
         "password=", 'password="', "password: a ", "Authorization: ", "Bearer ", "http://a:",
         "http://a:1/b@", '{"name": "password", ', '"value": "', PEM_BEGIN,
         "a=\"x\", ", "password: [", '"password": {"a": ', "<name>password</name><value>",
         "name: token, value: ", "curl -u a:", "a://x,", "<pw>"],
    )  # fmt: skip
    def test_hostile_output_is_masked_in_linear_time(self, unit):
        """Output is the device's: masking time must grow with its length, not its square.
        Before the fix, 32k dashes held the event loop for over two minutes."""

        assert_linear(redact, lambda n: (unit * (n // len(unit) + 1))[:n])


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

    def test_results_are_capped(self):
        rows = ",".join(
            f'{{"name": "c{i}", "detail": "{"d" * 1000}", "status": "BAD"}}' for i in range(1000)
        )
        p = parse_health_check(f"=====x=====\n:checkpoints:[{rows}]\n")
        assert len(p["not_ok"]) == cd.PARSE_LIST_MAX and p["not_ok_total"] == 1000
        assert all(len(n["detail"]) <= cd.PARSE_TEXT_MAX for n in p["not_ok"])

    @pytest.mark.parametrize(
        "body",
        ['{"name": "cogs.DSTableByNan", "detail": [{"nanDsi": "5", "dsName": "M"}], "status": "OK"}',
         '{"name": "biz.DataSource.WMI", "detail": "1 of 2 tasks (1.2.3%) returned NaN", "status": "OK"}',
         '{"name": "module.Collector", "detail": {"a": [1, 2]}, "status": "OK"}'],
    )  # fmt: skip
    def test_odd_values_do_not_break_the_parse(self, body):
        p = parse_health_check(f"=====x=====\n:checkpoints:[{body}]\n")
        assert p["checks_parsed"] == 1

    def test_deep_nesting_is_not_followed(self):
        p = parse_health_check("=====x=====\n:checkpoints:" + "[" * 100_000 + "]" * 100_000)
        assert p["checks_parsed"] == 1 and p["not_ok"] == []

    def test_structured_details_are_masked_after_the_parse(self):
        body = '{"name": "module.Collector", "detail": {"proxy.pass": "hunter2"}, "status": "OK"}'
        p = cd.redact_values(parse_health_check(f"=====x=====\n:checkpoints:[{body}]\n"))
        assert "hunter2" not in json.dumps(p) and "proxy.pass" in p["facts"]["module.Collector"]

    def test_a_long_digit_run_in_a_detail_is_parsed_in_linear_time(self):
        def reply(n: int) -> str:
            body = f'{{"name": "biz.DataSource.X", "detail": "{"1" * n} of 2", "status": "OK"}}'
            return f"=====c=====\n:checkpoints:[{body}]\n"

        assert_linear(parse_health_check, reply)

    @pytest.mark.parametrize(
        "unit",
        ["is scheduled at x, finished at y, ", "is scheduled at ", "1", "1 of ", "=====a=====\n",
         "=", ":checkpoints:[", '{"name": "biz.DataSource.X", "detail": "'],
    )  # fmt: skip
    def test_hostile_replies_are_parsed_in_linear_time(self, unit):
        """The reply is the collector's: the parse grows with its length, not faster."""

        assert_linear(
            parse_health_check, lambda n: "=====c=====\n" + (unit * (n // len(unit) + 1))[:n]
        )


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
    """Call the tool and return its body, with _is_error set from the result type.

    A request refused before sending comes back as a validation error ("Error: ...");
    it is read back here as status rejected_by_tool with its detail and suggestion.
    """
    from lm_mcp.tools import is_error_result

    result = await collector_debug(client, **kw)
    text = result[0].text
    if text.startswith("Error: ") and "\nDetails: " in text:
        body = json.loads(text.split("\nDetails: ", 1)[1])
    elif text.startswith("Error: "):
        message, _, suggestion = text[len("Error: ") :].partition("\nSuggestion: ")
        body = {"status": "rejected_by_tool", "detail": message, "suggestion": suggestion}
    else:
        body = json.loads(text)
    body["_is_error"] = is_error_result(result)
    return body


DEVICE = {"id": 42, "name": "10.0.0.42", "currentCollectorId": 7}


@pytest.mark.usefixtures("writes")
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
        seen = mount({"!ping": "Sent: 10, Recv: 10"}, device=DEVICE)
        data = await run(client, command="ping", device_id=42)
        assert seen == ["!ping 10.0.0.42"]
        assert data["collector_id"] == 7 and data["device"]["host_used"] == "10.0.0.42"

    @respx.mock
    async def test_a_caller_host_cannot_override_the_record(self, client):
        """Item 2: host from the record only; a host argument is refused, nothing is sent."""
        seen = mount(device=DEVICE)
        data = await run(client, command="ping", device_id=42, args={"host": "10.0.0.9"})
        assert data["status"] == "rejected_by_tool"
        assert "'host' is not accepted" in data["detail"]
        assert seen == []

    async def test_device_probe_without_device_id_sends_nothing(self, client):
        with respx.mock(assert_all_called=False) as router:
            route = router.route(host="test.logicmonitor.com").mock(httpx.Response(200, json={}))
            data = await run(client, command="ping", collector_id=7)
        assert data["status"] == "rejected_by_tool" and "needs device_id" in data["detail"]
        assert route.call_count == 0

    @respx.mock
    async def test_a_device_record_with_an_odd_name_is_refused(self, client):
        seen = mount(device={"id": 43, "name": "bad host; !restart", "currentCollectorId": 7})
        data = await run(client, command="ping", device_id=43)
        assert data["status"] == "rejected_by_tool" and "plain hostname" in data["detail"]
        assert seen == []

    @respx.mock
    async def test_a_device_name_that_reads_as_an_option_is_refused(self, client):
        seen = mount(device={"id": 45, "name": "-n", "currentCollectorId": 7})
        data = await run(client, command="ping", device_id=45)
        assert data["status"] == "rejected_by_tool" and "plain hostname" in data["detail"]
        assert seen == []

    @pytest.mark.parametrize("args", [{"count": 999}, {"count": float("inf")}])
    async def test_bad_values_are_refused_before_the_device_is_read(self, client, args):
        with respx.mock(assert_all_called=False) as router:
            route = router.route(host="test.logicmonitor.com").mock(httpx.Response(200, json={}))
            data = await run(client, command="ping", device_id=42, args=args)
        assert data["status"] == "rejected_by_tool" and data["_is_error"]
        assert route.call_count == 0

    @pytest.mark.parametrize("args", [{"query": "select * from X h=evil"}])
    async def test_wmi_values_are_refused_before_the_device_is_read(self, client, args):
        with respx.mock(assert_all_called=False) as router:
            route = router.route(host="test.logicmonitor.com").mock(httpx.Response(200, json={}))
            data = await run(client, command="wmi", device_id=42, args=args)
        assert data["status"] == "rejected_by_tool" and data["_is_error"]
        assert route.call_count == 0

    @pytest.mark.parametrize(
        "url", ["https://admin:x@10.0.0.42/", "https://10.0.0.42/?password=x", "ftp://10.0.0.42/"]
    )
    async def test_url_faults_are_refused_before_the_device_is_read(self, client, url):
        with respx.mock(assert_all_called=False) as router:
            route = router.route(host="test.logicmonitor.com").mock(httpx.Response(200, json={}))
            data = await run(client, command="http", device_id=42, args={"url": url})
        assert data["status"] == "rejected_by_tool" and data["_is_error"]
        assert route.call_count == 0

    @respx.mock
    async def test_http_runs_only_against_the_device_record(self, client):
        """Item 3 end to end: the device's own URL runs; another host does not."""
        seen = mount({"!http": "HTTP/1.1 200 OK"}, device=DEVICE)
        ok = await run(
            client, command="http", device_id=42, args={"url": "https://10.0.0.42/health"}
        )
        refused = await run(
            client,
            command="http",
            device_id=42,
            args={"url": "http://169.254.169.254/latest/meta-data/"},
        )
        assert ok["status"] == "answered"
        assert refused["status"] == "rejected_by_tool"
        assert seen == ["!http https://10.0.0.42/health"]

    @respx.mock
    async def test_portal_check_targets_the_configured_portal(self, client):
        """Item 4: the target is the client's own portal host."""
        seen = mount({"!checkserverconnectivity": "PING: Fail, HTTP: OK"})
        data = await run(client, command="checkserverconnectivity", collector_id=7)
        assert seen == ["!checkserverconnectivity test.logicmonitor.com"]
        assert data["status"] == "answered"

    @respx.mock
    async def test_unknown_key_is_refused_with_the_keys_it_takes(self, client):
        """Item 7 through the tool: the reply names the keys the command takes."""
        seen = mount(device=DEVICE)
        data = await run(
            client, command="ping", device_id=42, args={"bogus": "x", "community": "public"}
        )
        assert data["status"] == "rejected_by_tool" and data["_is_error"]
        assert data["suggestion"] == "ping takes count, type"
        assert seen == []

    async def test_args_must_be_an_object(self, client):
        data = await run(client, command="uptime", collector_id=7, args=["x"])
        assert data["status"] == "rejected_by_tool" and "object" in data["detail"]

    @respx.mock
    async def test_output_is_redacted(self, client):
        mount({"!logsurf": "connecting with password=hunter2 to host"})
        data = await run(client, command="logsurf", collector_id=7)
        assert "hunter2" not in json.dumps(data)
        assert "password=***" in data["output"]

    @respx.mock
    async def test_a_probe_cannot_run_on_another_collector(self, client):
        """The record's host means something else in another collector's network."""
        seen = mount(device=DEVICE)
        data = await run(client, command="ping", device_id=42, collector_id=99)
        assert data["status"] == "rejected_by_tool"
        assert "collector that serves the device (7)" in data["detail"]
        assert seen == []

    @respx.mock
    async def test_a_probe_on_the_serving_collector_runs(self, client):
        seen = mount({"!ping": "Sent: 1"}, device=DEVICE)
        data = await run(client, command="ping", device_id=42, collector_id=7)
        assert data["status"] == "answered" and seen == ["!ping 10.0.0.42"]

    @respx.mock
    async def test_a_device_with_no_collector_is_refused(self, client):
        seen = mount(device={"id": 44, "name": "10.0.0.44", "currentCollectorId": None})
        data = await run(client, command="ping", device_id=44, collector_id=7)
        assert data["status"] == "rejected_by_tool" and "names no collector" in data["detail"]
        assert seen == []

    async def test_bad_args_are_refused_before_the_device_is_read(self, client):
        with respx.mock(assert_all_called=False) as router:
            route = router.route(host="test.logicmonitor.com").mock(httpx.Response(200, json={}))
            data = await run(client, command="ping", device_id=42, args={"bogus": 1})
        assert data["status"] == "rejected_by_tool"
        assert route.call_count == 0

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"budget_seconds": float("nan")},
            {"budget_seconds": float("inf")},
            {"max_output_chars": float("nan")},
            {"budget_seconds": "soon"},
        ],
    )
    async def test_non_finite_numbers_are_refused_before_any_call(self, client, kwargs):
        with respx.mock(assert_all_called=False) as router:
            route = router.route(host="test.logicmonitor.com").mock(httpx.Response(200, json={}))
            data = await run(client, command="uptime", collector_id=7, **kwargs)
        assert data["status"] == "rejected_by_tool" and "finite" in data["detail"]
        assert route.call_count == 0

    @respx.mock
    async def test_error_body_and_pending_status_are_redacted(self, client):
        mount(post_error=(400, "bad request: password=hunter2"))
        data = await run(client, command="uptime", collector_id=7)
        assert "hunter2" not in json.dumps(data)

    async def test_a_pending_status_is_redacted(self, client, monkeypatch):
        async def post(*a, **kw):
            return {"sessionId": "s1"}

        async def busy_get(*a, **kw):
            from lm_mcp.exceptions import ValidationError

            raise ValidationError("agent has fetched the task, password=hunter2")

        monkeypatch.setattr(client, "request", post)
        monkeypatch.setattr(client, "get", busy_get)
        data = await run(client, command="uptime", collector_id=7, budget_seconds=2)
        assert data["status"] == "no_reply"
        assert "password=***" in data["detail"] and "hunter2" not in json.dumps(data)

    @respx.mock
    async def test_budget_and_output_are_clamped(self, client):
        mount({"!uptime": "x" * 3000})
        data = await run(
            client, command="uptime", collector_id=7, budget_seconds=1000, max_output_chars=600
        )
        assert data["budget_seconds"] == 60
        assert len(data["output"]) == 600 and data["truncated"] is True
        assert data["output_chars"] == 3000

    @respx.mock
    async def test_bad_api_credentials_are_not_called_a_missing_permission(self, client):
        mount(post_error=(401, "Authentication failed"))
        data = await run(client, command="uptime", collector_id=7)
        assert data["status"] == "error" and "API credentials" in data["detail"]

    @respx.mock
    async def test_usage_reply_is_flagged_as_the_commands_fault(self, client):
        mount({"!sslcerts": "Usage: !sslcerts [timeout=XX] host port"}, device=DEVICE)
        data = await run(client, command="sslcerts", device_id=42, args={"port": 443})
        assert data["status"] == "answered" and "not the device" in data["note"]

    @respx.mock
    async def test_no_reply_inside_the_budget(self, client):
        mount({"!uptime": "slow"})
        data = await run(client, command="uptime", collector_id=7, budget_seconds=2)
        assert data["status"] == "no_reply" and "pending" in data["detail"]
        assert not data["_is_error"]
        assert data["elapsed_ms"] < 3500

    @pytest.mark.parametrize("reply", ["cpu usage: 12%", "<title>Invalid URL</title>"])
    @respx.mock
    async def test_a_device_reply_is_not_read_as_a_usage_banner(self, client, reply):
        mount({"!http": reply}, device=DEVICE)
        data = await run(client, command="http", device_id=42, args={"url": "http://10.0.0.42/"})
        assert data["status"] == "answered" and "note" not in data

    @respx.mock
    async def test_unknown_config_key_is_flagged(self, client):
        mount({"!getconfig": "Configuration key [collector.zzz.threadpool] not found"})
        data = await run(
            client, command="getconfig", collector_id=7, args={"key": "collector.zzz.threadpool"}
        )
        assert data["status"] == "answered" and "agent.conf key" in data["note"]

    @respx.mock
    async def test_still_working_error_keeps_polling(self, client):
        mount({"!ping": "Sent: 4, Recv: 4"}, busy_gets=2, inverted=True, device=DEVICE)
        data = await run(client, command="ping", device_id=42)
        assert data["status"] == "answered" and "Recv: 4" in data["output"]

    @respx.mock
    async def test_still_working_until_the_budget_is_no_reply(self, client):
        mount({"!ping": "Sent: 4, Recv: 4"}, busy_gets=10**6, device=DEVICE)
        data = await run(client, command="ping", device_id=42, budget_seconds=2)
        assert data["status"] == "no_reply", data
        assert "waiting for response" in data["detail"]

    @respx.mock
    async def test_refused_without_debug_permission(self, client):
        mount(post_error=(403, "Permission denied"))
        data = await run(client, command="uptime", collector_id=7)
        assert data["status"] == "refused" and data["_is_error"]

    @respx.mock
    async def test_an_answer_is_not_an_error(self, client):
        mount({"!uptime": "uptime=1h"})
        data = await run(client, command="uptime", collector_id=7)
        assert data["status"] == "answered" and not data["_is_error"]

    @respx.mock
    async def test_unknown_debug_command_is_unsupported(self, client):
        mount(post_error=(400, "Unknown debug command !nsplist"))
        data = await run(client, command="nsplist", collector_id=7)
        assert data["status"] == "unsupported" and data["_is_error"]

    @respx.mock
    async def test_debug_disabled_on_the_collector(self, client):
        mount(post_error=(400, "remote debug is disabled on this collector"))
        data = await run(client, command="uptime", collector_id=7)
        assert data["status"] == "disabled" and data["_is_error"]

    async def test_unknown_command_lists_the_safe_set(self, client):
        data = await run(client, command="restart", collector_id=7)
        assert data["status"] == "rejected_by_tool" and "uptime" in data["suggestion"]

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
        assert data["status"] == "rate_limited" and data["_is_error"]

    @respx.mock
    async def test_own_get_budget(self, client, monkeypatch):
        monkeypatch.setattr(cd, "GET_LIMIT", 0)
        mount({"!uptime": "uptime=1h"})
        data = await run(client, command="uptime", collector_id=7)
        # The command was sent, so it is no answer yet rather than a refusal.
        assert data["status"] == "no_reply" and "GET budget" in data["detail"]
        assert "may still run it" in data["detail"] and not data["_is_error"]

    async def test_no_session_id_is_an_error(self, client, monkeypatch):
        async def post(*a, **kw):
            return {}

        monkeypatch.setattr(client, "request", post)
        data = await run(client, command="uptime", collector_id=7)
        assert data["status"] == "error" and "no session id" in data["detail"]
        assert data["_is_error"]

    @respx.mock
    async def test_output_floor_is_500_characters(self, client):
        mount({"!uptime": "x" * 3000})
        data = await run(client, command="uptime", collector_id=7, max_output_chars=10)
        assert len(data["output"]) == 500 and data["truncated"] is True

    @respx.mock
    async def test_budget_floor_is_two_seconds(self, client):
        mount({"!uptime": "uptime=1h"})
        data = await run(client, command="uptime", collector_id=7, budget_seconds=0)
        assert data["status"] == "answered" and data["budget_seconds"] == 2.0

    @respx.mock
    async def test_masked_output_that_grows_is_still_capped(self, client):
        """Masking can lengthen the text past OUTPUT_MAX; the cap still holds."""
        mount({"!logsurf": "pass=x\n" * (OUTPUT_MAX // 7)})
        data = await run(client, command="logsurf", collector_id=7, max_output_chars=10**9)
        assert data["output_chars"] <= OUTPUT_MAX
        assert len(data["output"]) == OUTPUT_MAX and data["truncated"] is True

    @respx.mock
    async def test_output_is_capped_at_the_maximum(self, client):
        mount({"!uptime": "x" * (OUTPUT_MAX + 500)})
        data = await run(client, command="uptime", collector_id=7, max_output_chars=10**9)
        assert len(data["output"]) == OUTPUT_MAX and data["truncated"] is True
        assert data["output_chars"] == OUTPUT_MAX + 500

    @respx.mock
    async def test_a_masked_value_does_not_break_the_health_check_parse(self, client):
        """The parse reads the raw reply, and only its result is masked."""
        # An unclosed secret element masks to the end of its text, which would break the JSON.
        reply = HEALTH.replace("Free disk is 2 MBytes", "<password>hunter2")
        mount({"!shealthcheck": reply})
        data = await run(client, command="health_check", collector_id=7)
        parsed = data["parsed"]
        assert [m["method"] for m in parsed["methods_by_all_nan_rate"]] == [
            "BATCHSCRIPT",
            "WMI",
            "PING",
        ]
        assert parsed["nan_by_module"] and parsed["facts"]
        disk = next(n for n in parsed["not_ok"] if n["check"] == "basic.Disk")
        assert disk["detail"] == "<password>***"
        assert "hunter2" not in json.dumps(data)

    @respx.mock
    async def test_a_long_health_check_is_parsed_as_far_as_the_cut(self, client):
        mount({"!shealthcheck": HEALTH + "x" * OUTPUT_MAX})
        data = await run(client, command="health_check", collector_id=7)
        assert data["parsed"]["checks_parsed"] == 5 and data["parse_partial"] is True
        mount({"!shealthcheck": "x" * OUTPUT_MAX + HEALTH})
        beyond = await run(client, command="health_check", collector_id=7)
        assert beyond["parsed"]["checks_parsed"] == 0 and beyond["parse_partial"] is True

    @respx.mock
    async def test_a_parse_fault_leaves_the_answer_standing(self, client, monkeypatch):
        def broken(text):
            raise RecursionError

        monkeypatch.setattr(cd, "parse_health_check", broken)
        mount({"!shealthcheck": HEALTH})
        data = await run(client, command="health_check", collector_id=7)
        assert data["status"] == "answered" and not data["_is_error"]
        assert data["parse_error"] == "RecursionError" and data["output"]

    @respx.mock
    async def test_a_device_is_bound_to_its_collector_for_every_command(self, client):
        seen = mount(device=DEVICE)
        data = await run(client, command="uptime", device_id=42, collector_id=99)
        assert data["status"] == "rejected_by_tool"
        assert "collector that serves the device (7)" in data["detail"]
        assert seen == []

    @respx.mock
    async def test_the_error_line_is_one_line(self, client):
        mount(post_error=(500, "agent unreachable\nretry later"))
        result = await collector_debug(client, command="uptime", collector_id=7)
        first, _, rest = result[0].text.partition("\n")
        assert "agent unreachable retry later" in first and rest.startswith("Details: ")

    @respx.mock
    async def test_truncated_follows_what_is_shown_after_masking(self, client):
        """Masking can lengthen or shorten the text; truncated reports what was cut."""
        mount({"!logsurf": "pass=x\n" * 2857})  # 19,999 characters that mask to more
        grown = await run(client, command="logsurf", collector_id=7)
        assert grown["output_chars"] < 20_000 and grown["truncated"] is True
        mount({"!logsurf": "password=" + "y" * 25_000 + "\ntail"})
        cut = await run(client, command="logsurf", collector_id=7)
        # Only the shown 20,000 characters are read and masked, so the tail is not shown.
        assert cut["output"] == "password=***" and cut["truncated"] is True
        mount({"!logsurf": "password=" + "y" * 15_000 + "\ntail"})
        shrunk = await run(client, command="logsurf", collector_id=7)
        assert shrunk["output"] == "password=***\ntail" and shrunk["truncated"] is False

    @pytest.mark.parametrize(
        "kwargs",
        [{"collector_id": "abc"}, {"collector_id": -5}, {"collector_id": 0},
         {"collector_id": True}, {"device_id": "42"}, {"device_id": 4.0}],
    )  # fmt: skip
    async def test_ids_are_checked_before_any_call(self, client, kwargs):
        with respx.mock(assert_all_called=False) as router:
            route = router.route(host="test.logicmonitor.com").mock(httpx.Response(200, json={}))
            data = await run(client, command="ping", **{"device_id": 42, **kwargs})
        assert data["status"] == "rejected_by_tool" and "positive whole number" in data["detail"]
        assert route.call_count == 0

    @respx.mock
    async def test_an_error_line_carries_the_portals_words(self, client):
        mount(post_error=(500, "collector agent is unreachable, password=hunter2"))
        result = await collector_debug(client, command="uptime", collector_id=7)
        first = result[0].text.split("\n", 1)[0]
        assert first.startswith("Error: uptime: error: ")
        assert "unreachable" in first and "hunter2" not in result[0].text

    async def test_a_transport_refusal_is_a_validation_error(self, client, monkeypatch):
        """run_debug's own re-check refuses the line; the tool reports it as a refusal."""

        async def refused(*a, **kw):
            return {"status": "rejected_by_tool", "detail": "not a debug command"}

        monkeypatch.setattr(cd, "run_debug", refused)
        result = await collector_debug(client, command="uptime", collector_id=7)
        assert result[0].text.startswith("Error: uptime: not a debug command")
        assert "Details:" not in result[0].text

    @respx.mock
    async def test_health_check_output_is_capped_at_4000(self, client):
        mount({"!shealthcheck": HEALTH + "x" * 5000})
        data = await run(client, command="health_check", collector_id=7)
        assert len(data["output"]) == 4000 and data["truncated"] is True
        assert data["parsed"]["methods_by_all_nan_rate"]

    @respx.mock
    async def test_a_failure_reads_as_an_error_to_composite_callers(self, client):
        """call_sub_tool raises on a failed status instead of reading it as data."""
        from lm_mcp.tools import call_sub_tool

        mount(post_error=(403, "Permission denied"))
        with pytest.raises(RuntimeError, match="uptime: refused"):
            await call_sub_tool(collector_debug, client, command="uptime", collector_id=7)


class TestRunDebug:
    """run_debug is the transport the assessment tool will share; it guards itself."""

    async def test_a_spent_budget_sends_nothing_and_says_so(self, client):
        with respx.mock(assert_all_called=False) as router:
            route = router.route(host="test.logicmonitor.com").mock(httpx.Response(200, json={}))
            result = await cd.run_debug(client, 7, "!uptime", time.monotonic() - 1)
        assert result["status"] == "error" and "nothing was sent" in result["detail"]
        assert route.call_count == 0

    async def test_it_refuses_an_unchecked_line_without_a_call(self, client):
        with respx.mock(assert_all_called=False) as router:
            route = router.route(host="test.logicmonitor.com").mock(httpx.Response(200, json={}))
            result = await cd.run_debug(client, 7, "!restart", time.monotonic() + 5)
        assert (
            result["status"] == "rejected_by_tool" and "changes the collector" in result["detail"]
        )
        assert route.call_count == 0

    @respx.mock
    async def test_it_cuts_the_output_before_masking(self, client, monkeypatch):
        seen = []
        monkeypatch.setattr(cd, "redact", lambda text: seen.append(len(text)) or text)
        mount({"!uptime": "y" * (OUTPUT_MAX * 3)})
        result = await cd.run_debug(client, 7, "!uptime", time.monotonic() + 5)
        assert result["status"] == "answered"
        assert seen == [OUTPUT_MAX + cd._MASK_MARGIN] and len(result["output"]) == OUTPUT_MAX
        assert result["output_chars"] == OUTPUT_MAX * 3 and result["truncated"] is True

    @pytest.mark.parametrize(
        "secret",
        ["http://bob:hunter2@10.0.0.1/x", '{"name": "db.password", "value": "hunter2"}',
         '<add key="DbPassword" value="hunter2"/>', "mongodb://bob:hunter2@10.0.0.1/db"],
    )  # fmt: skip
    @respx.mock
    async def test_a_secret_the_cut_splits_is_still_masked(self, client, secret):
        """Masking reads past the cut, so a value whose end falls after it is still seen."""
        keep = 1000
        cut_at = secret.index("hunter2") + 3  # the cut lands inside the value
        mount({"!uptime": "x" * (keep - cut_at) + secret + " tail"})
        result = await cd.run_debug(client, 7, "!uptime", time.monotonic() + 5, keep=keep)
        assert "hun" not in result["output"] and len(result["output"]) <= keep


@pytest.mark.usefixtures("writes")
class TestBudget:
    """Item 5: the POST and every poll are held to the time budget."""

    async def test_a_slow_post_is_cut_off_at_the_budget(self, client, monkeypatch):
        async def slow_request(*a, **kw):
            await asyncio.sleep(30)

        monkeypatch.setattr(client, "request", slow_request)
        started = time.monotonic()
        data = await run(client, command="uptime", collector_id=7, budget_seconds=2)
        assert data["status"] == "no_reply"
        assert "did not accept the command" in data["detail"]
        assert time.monotonic() - started < 3

    async def test_a_slow_device_read_is_cut_off_at_the_budget(self, client, monkeypatch):
        async def slow_get(*a, **kw):
            await asyncio.sleep(30)

        monkeypatch.setattr(client, "get", slow_get)
        started = time.monotonic()
        data = await run(client, command="ping", device_id=42, budget_seconds=2)
        assert data["status"] == "error" and data["_is_error"]
        assert "device record" in data["detail"] and "nothing was sent" in data["detail"]
        assert time.monotonic() - started < 3

    async def test_a_slow_poll_is_cut_off_at_the_budget(self, client, monkeypatch):
        async def post(*a, **kw):
            return {"sessionId": "s1"}

        async def slow_get(*a, **kw):
            await asyncio.sleep(30)

        monkeypatch.setattr(client, "request", post)
        monkeypatch.setattr(client, "get", slow_get)
        started = time.monotonic()
        data = await run(client, command="uptime", collector_id=7, budget_seconds=2)
        assert data["status"] == "no_reply"
        assert time.monotonic() - started < 3


class TestWriteGate:
    """Item 1: collector_debug refuses when write operations are off, before any call."""

    async def test_disabled_writes_refuse_before_any_call(self, client, monkeypatch):
        from lm_mcp.registry import get_tool_handler
        from lm_mcp.tools import is_error_result

        _set_writes(monkeypatch, False)
        handler = get_tool_handler("collector_debug")
        with respx.mock(assert_all_called=False) as router:
            route = router.route(host="test.logicmonitor.com").mock(httpx.Response(200, json={}))
            result = await handler(client, command="uptime", collector_id=7)
        assert is_error_result(result)
        assert "Write operations are disabled" in result[0].text
        assert route.call_count == 0

    def test_it_is_audited_as_a_write(self):
        from lm_mcp.logging import is_write_tool

        assert is_write_tool("collector_debug")


class TestWithin:
    async def test_a_spent_budget_refuses_before_calling(self):
        """No call starts once the deadline has passed, and the coroutine is closed."""
        calls = []

        async def call():
            calls.append(1)

        coro = call()
        with pytest.raises(cd._BudgetSpentError):
            await cd._within(time.monotonic() - 1, coro)
        assert calls == []
        assert coro.cr_frame is None  # closed, so no "never awaited" warning


class TestArgumentTypes:
    """Odd argument types are refusals, never unexpected errors."""

    @pytest.mark.parametrize(
        "command,args,why",
        [("snmpget", {"oids": 5}, "'oids' must be a list"),
         ("snmpdiagnose", {"oids": {"a": 1}}, "'oids' must be a list"),
         ("snmpwalk", {"oid": "1.3.6.1." + "9" * 4400}, "invalid value"),
         ("ping", {"count": [1]}, "whole number"),
         ("logsurf", {"files": 5}, "must be a list")],
    )  # fmt: skip
    def test_odd_values_are_refused(self, command, args, why):
        with pytest.raises(ToolRejectionError, match=why):
            build_cmdline(command, args, T)

    @pytest.mark.usefixtures("writes")
    @pytest.mark.parametrize(
        "kwargs",
        [{"command": ["uptime"]}, {"command": "uptime", "budget_seconds": True},
         {"command": "uptime", "max_output_chars": "1e9"}],
    )  # fmt: skip
    async def test_odd_tool_arguments_are_refused(self, client, kwargs):
        with respx.mock(assert_all_called=False) as router:
            route = router.route(host="test.logicmonitor.com").mock(httpx.Response(200, json={}))
            result = await collector_debug(client, collector_id=7, **kwargs)
        assert result[0].text.startswith("Error: ") and "UNEXPECTED" not in result[0].text
        assert route.call_count == 0

    @pytest.mark.parametrize("value,expected", [("7", 7), (7, 7), ("\u00b2", None), (-3, None),
                                                ("1234567890123", None), (True, None)])  # fmt: skip
    def test_counts_are_plain_digits(self, value, expected):
        assert cd._count(value) == expected

    @pytest.mark.parametrize("oid", [".1.3.6.1.2", ".1.3.6.1.2.1", ".1.3.6.1.4", "1.3.6.1.4.1"])
    def test_the_tops_of_the_tree_are_refused(self, oid):
        with pytest.raises(ToolRejectionError, match="walk a subtree"):
            build_cmdline("snmpwalk", {"oid": oid}, T)

    def test_a_wildcard_only_host_filter_is_unfiltered(self):
        with pytest.raises(ToolRejectionError, match="must be filtered"):
            build_cmdline("tlist", {"h": "*"}, T)

    @pytest.mark.parametrize("name", ["cookie", "otp", "accesskey", "authcode", "adminPw", "dbPwd"])
    def test_more_credential_query_names_are_refused(self, name):
        with pytest.raises(ToolRejectionError, match="credential-named parameter"):
            build_cmdline("http", {"url": f"https://10.0.0.5/x?{name}=1"}, T)


@pytest.mark.usefixtures("writes")
class TestTransportState:
    @respx.mock
    async def test_the_read_form_is_learned_per_portal(self, client):
        """Portals differ on whether the read takes collectorId, so each learns its own."""
        mount({"!uptime": "uptime=1h"})  # only the read without collectorId answers
        data = await run(client, command="uptime", collector_id=7)
        assert data["read_form"] == "without"
        assert cd._READ_FORMS == {"test.logicmonitor.com": "without"}

    @respx.mock
    async def test_a_pending_reply_on_one_form_still_tries_the_other(self, client):
        """busy_gets=1: the first read is still pending; the other form is asked at once."""
        mount({"!uptime": "uptime=1h"}, busy_gets=1)
        data = await run(client, command="uptime", collector_id=7)
        assert data["status"] == "answered" and data["api_calls"] == 3


def test_a_builder_type_fault_is_a_refusal(monkeypatch):
    """A builder that trips on a value of the wrong type refuses; it never escapes as an error."""

    def trips(a, t):
        raise TypeError("unsupported operand")

    group, needs, _builder, keys, desc = COMMANDS["uptime"]
    monkeypatch.setitem(COMMANDS, "uptime", (group, needs, trips, keys, desc))
    with pytest.raises(ToolRejectionError, match="wrong type"):
        build_cmdline("uptime", {}, T)


class TestRoundSevenGuards:
    @pytest.mark.parametrize("record_id", [-7, True, 7.0, "1234567890123", "\u00b2", 10**13])
    @respx.mock
    async def test_an_odd_collector_id_on_the_record_is_no_collector(
        self, client, writes, record_id
    ):
        seen = mount(device={"id": 46, "name": "10.0.0.46", "currentCollectorId": record_id})
        data = await run(client, command="ping", device_id=46)
        assert data["status"] == "rejected_by_tool" and "names no collector" in data["detail"]
        assert seen == []

    @respx.mock
    async def test_a_digit_string_collector_id_on_the_record_is_read(self, client, writes):
        seen = mount(
            {"!ping": "Sent: 1"}, device={"id": 47, "name": "10.0.0.47", "currentCollectorId": "7"}
        )
        data = await run(client, command="ping", device_id=47)
        assert data["status"] == "answered" and data["collector_id"] == 7 and seen

    @respx.mock
    async def test_a_learned_read_form_stays_with_its_portal(self, writes):
        """Portal A learns 'without'; portal B, where only 'with' answers, still asks 'with'
        first, so its answer takes one read, not two."""

        def portal(host: str, answering_form: str) -> LogicMonitorClient:
            def handler(request: httpx.Request):
                if request.method == "POST":
                    return httpx.Response(200, json={"sessionId": "s1"})
                with_id = "collectorId" in dict(request.url.params)
                if (answering_form == "with") == with_id:
                    return httpx.Response(200, json={"output": f"uptime from {host}"})
                return httpx.Response(200, json={"output": "cancelled"})

            respx.route(host=host).mock(side_effect=handler)
            return LogicMonitorClient(
                base_url=f"https://{host}/santaba/rest",
                auth=BearerAuth("t"),
                timeout=30,
                api_version=3,
            )

        a = portal("portal-a.example.net", "without")
        b = portal("portal-b.example.net", "with")
        first = await run(a, command="uptime", collector_id=7)
        again = await run(a, command="uptime", collector_id=7)
        other = await run(b, command="uptime", collector_id=7)
        assert first["read_form"] == "without" and first["api_calls"] == 3
        assert again["api_calls"] == 2  # the learned form is asked first on the same portal
        assert other["read_form"] == "with" and other["api_calls"] == 2

    @pytest.mark.parametrize(
        "kwargs,why",
        [({"command": ["uptime"]}, "unknown or disallowed command"),
         ({"command": {"x": 1}}, "unknown or disallowed command"),
         ({"command": "uptime", "budget_seconds": 10**400}, "finite numbers"),
         ({"command": "uptime", "collector_id": 10**13}, "positive whole number")],
    )  # fmt: skip
    async def test_odd_values_are_named_refusals(self, client, writes, kwargs, why):
        args = {"collector_id": 7, **kwargs}
        result = await collector_debug(client, **args)
        assert result[0].text.startswith("Error: ") and why in result[0].text

    def test_a_session_word_with_whitespace_is_still_a_session_word(self):
        assert cd.is_session_word(" pending\n") and not cd.is_session_word("pending work")

    @pytest.mark.parametrize("h", ["*.*", "%", "[*]", "*-*"])
    def test_a_filter_with_no_letter_or_digit_is_unfiltered(self, h):
        with pytest.raises(ToolRejectionError, match="must be filtered"):
            build_cmdline("tlist", {"h": h}, T)

    @pytest.mark.parametrize("oid", ["0", "2", ".1"])
    def test_every_root_arc_is_refused(self, oid):
        with pytest.raises(ToolRejectionError, match="walk a subtree"):
            build_cmdline("snmpwalk", {"oid": oid}, T)

    def test_argument_names_must_be_strings(self):
        with pytest.raises(ToolRejectionError, match="argument names must be strings"):
            build_cmdline("ping", {1: "x"}, T)

    @respx.mock
    async def test_a_command_line_refusal_suggests_no_arguments(self, client, writes):
        seen = mount(device={"id": 48, "name": "d" * 3000, "currentCollectorId": 7})
        data = await run(client, command="ping", device_id=48)
        assert "longer than 2048" in data["detail"] and data["suggestion"] == ""
        assert seen == []

    @respx.mock
    async def test_a_device_record_that_is_not_an_object_is_refused(self, client, writes):
        respx.get(f"{BASE}/device/devices/49").mock(return_value=httpx.Response(200, json=[1, 2]))
        data = await run(client, command="ping", device_id=49)
        assert data["status"] == "rejected_by_tool" and "could not be read" in data["detail"]
