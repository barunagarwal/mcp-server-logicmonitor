# Description: Collector debug for investigations: a safe, typed, time-boxed debug command runner.
# Description: Shared debug transport and health-check parser, also used by collector_assessment.

"""Collector debug.

Runs one collector debug command and returns what the collector said. Built for agents (Edwin
AI, Claude, automations) as much as for people, so the guards live here, not in the caller:

- Callers never send free text. They name a command from COMMANDS and pass typed arguments;
  this module builds the command line. Anything that would change the collector, run code on
  its host, write to a device or take a credential is not in COMMANDS, and a final check
  refuses it again at send time.
- No credentials. Protocol probes run on the device's stored properties (snmp.*, wmi.*, cim.*),
  so nothing secret lands in the portal's Audit Log, which keeps debug history as sent.
- One wall-clock budget per call. A command the collector does not pick up in time returns
  no_reply with its elapsed time; nothing hangs.
- Honest states: answered, no_reply, refused, disabled, unsupported, rejected_by_tool,
  rate_limited, error. Never a guessed success.

Transport facts, each observed on live portals:

- POST /debug?collectorId=N with {"cmdline": ...} returns a session id. The collector fetches
  the command on its next check-in, so the result is polled with GET /debug/{sessionId}.
- Whether collectorId belongs on the GET differs between portals (each form has returned
  "cancelled" while the other returned the output). Both forms are asked on the same session
  and the one that answers is remembered for the life of the process.
- Single-word replies such as "cancelled" or "pending" are session statuses, not output.
- Rate limits: POST 200/min, GET 500/min. This module counts its own calls and stops short.

The stored health check (!shealthcheck func=detail) is sectioned text: "=====name=====" blocks,
each with "is scheduled at ..., finished at ..., status N", optional detail, and a
":checkpoints:" JSON array of {name, detail, status}. parse_health_check() turns it into a
compact summary: per-method all-NaN rates, checkpoints not OK, the modules carrying NaN, and
when the check last ran. Checkpoint status alone is misleading (a collector can show every
checkpoint OK with 12% of a method's tasks returning nothing), so the rates lead.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import deque
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from mcp.types import TextContent

from lm_mcp.tools import format_response, handle_error

if TYPE_CHECKING:
    from lm_mcp.client import LogicMonitorClient

logger = logging.getLogger(__name__)

POLL_SECONDS = 1.0
BUDGET_DEFAULT = 15.0
BUDGET_MAX = 60.0
OUTPUT_DEFAULT = 20_000
OUTPUT_MAX = 100_000
RATE_WINDOW = 60.0
POST_LIMIT = 180  # LM allows 200/min; stop short
GET_LIMIT = 450  # LM allows 500/min; stop short

SESSION_WORDS = {
    "cancelled",
    "canceled",
    "pending",
    "queued",
    "scheduled",
    "running",
    "timeout",
    "timedout",
    "expired",
    "unknown",
}

# Second line of defence: never sent, whatever builds the command line.
BLOCKED = {
    "restart", "sbshutdown", "reload", "svc", "upgradeproxy", "register", "keepagentalive",
    "reducelog", "loglevel", "log4jloglevel", "sconfig", "tcancel", "tremove", "groovy", "posh",
    "java", "jcmd", "syswmic", "typeperf", "logman", "cp", "put", "replace", "unzip", "dumpheap",
    "packetcapture", "packetcapture2", "uploadlog", "hostproperty", "wmimethod", "syslogsender",
    "checkcredential", "jdbc", "healthcheckv2", "decryptfilesha", "digest", "etw", "account",
}  # fmt: skip
CREDENTIAL_RE = re.compile(
    r"(^|\s)(password|passwd|pass|authToken|privToken|community|username|user|security)\s*=",
    re.IGNORECASE,
)

_READ_FORM: str | None = None  # "with" | "without", learned per process
_POSTS: deque = deque()
_GETS: deque = deque()


class ToolRejectionError(ValueError):
    """The request was refused by this tool before anything was sent."""


# ---------------------------------------------------------------- argument validation

_HOST_RE = re.compile(r"^[A-Za-z0-9._:\-\[\]%]+$")
_GLOB_RE = re.compile(r"^[A-Za-z0-9._:\-*?\[\]%]+$")
_OID_RE = re.compile(r"^\.?\d+(\.\d+)*$")
_KEY_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")
_CLASS_RE = re.compile(r"^[A-Za-z0-9_]+$")
_ROOT_OIDS = {".1", "1", ".1.3", "1.3", ".1.3.6", "1.3.6", ".1.3.6.1", "1.3.6.1"}
LOG_FILES = ("wrapper.log", "sbproxy.log", "watchdog.log")


def _host(args: dict, key: str = "host") -> str:
    value = str(args.get(key) or "").strip()
    if not value:
        raise ToolRejectionError(f"'{key}' is required")
    if not _HOST_RE.match(value):
        raise ToolRejectionError(f"'{key}' must be a hostname or IP address, without spaces")
    return value


def _opt(args: dict, key: str, allowed: tuple | None = None, pattern: re.Pattern | None = None):
    value = args.get(key)
    if value in (None, ""):
        return None
    text = str(value).strip()
    if allowed is not None and text not in allowed:
        raise ToolRejectionError(f"'{key}' must be one of {', '.join(allowed)}")
    if pattern is not None and not pattern.match(text):
        raise ToolRejectionError(f"'{key}' has an invalid value")
    return text


def _int(args: dict, key: str, lo: int, hi: int, default: int | None = None) -> int | None:
    value = args.get(key, default)
    if value in (None, ""):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError) as e:
        raise ToolRejectionError(f"'{key}' must be a whole number") from e
    if not lo <= number <= hi:
        raise ToolRejectionError(f"'{key}' must be between {lo} and {hi}")
    return number


def _list(args: dict, key: str, pattern: re.Pattern, lo: int, hi: int) -> list[str]:
    raw = args.get(key) or []
    if isinstance(raw, str):
        raw = raw.replace(",", " ").split()
    items = [str(x).strip() for x in raw if str(x).strip()]
    if not lo <= len(items) <= hi:
        raise ToolRejectionError(f"'{key}' takes {lo} to {hi} values")
    for item in items:
        if not pattern.match(item):
            raise ToolRejectionError(f"'{item}' is not a valid value for '{key}'")
    return items


def _join(*parts: Any) -> str:
    return " ".join(str(p) for p in parts if p not in (None, ""))


def _kv(name: str, value: Any) -> str | None:
    return None if value in (None, "") else f"{name}={value}"


# ---------------------------------------------------------------- the safe command set
# name -> (group, needs_device_host, builder(args, collector_id) -> cmdline, description)


def _b_ping(a: dict, _c: int) -> str:
    kind = _opt(a, "type", ("default", "all", "proxy", "sys", "java"))
    return _join("!ping", _kv("type", kind), _kv("count", _int(a, "count", 1, 20)), _host(a))


def _b_snmpwalk(a: dict, _c: int) -> str:
    oid = _opt(a, "oid", pattern=_OID_RE) or ".1.3.6.1.2.1.1"
    if oid in _ROOT_OIDS:
        raise ToolRejectionError("walking from the root of the tree is refused; walk a subtree")
    return _join("!snmpwalk", _kv("timeout", _int(a, "timeout", 1, 120)), _host(a), oid)


def _b_wmi(a: dict, _c: int) -> str:
    query = " ".join(str(a.get("query") or "select * from Win32_Service").split())
    if not re.match(r"^select\s", query, re.IGNORECASE) or ";" in query:
        raise ToolRejectionError("only a single SELECT query is allowed")
    auth = _opt(a, "authType", ("NTLMv2", "Kerberos"))
    return _join("!wmi", f"h={_host(a)}", _kv("authType", auth), query)


def _b_winrm(a: dict, _c: int) -> str:
    return _join(
        "!winrm",
        f"host={_host(a)}",
        _kv("auth", _opt(a, "auth", ("Negotiate", "Kerberos"))),
        _kv("useSSL", _opt(a, "useSSL", ("true", "false"))),
        _kv("certCheck", _opt(a, "certCheck", ("true", "false"))),
        _kv("timeout", _int(a, "timeout", 1, 120)),
    )


def _b_http(a: dict, _c: int) -> str:
    url = str(a.get("url") or "").strip()
    if not re.match(r"^https?://[^\s]+$", url):
        raise ToolRejectionError("'url' must start with http:// or https:// and contain no spaces")
    return _join("!http", _kv("timeout", _int(a, "timeout", 1, 120)), url)


def _b_perf(a: dict, _c: int) -> str:
    kind = _opt(a, "type", ("cpu", "queue", "ds")) or "ds"
    column = _opt(a, "dsFilterColumn", ("nan", "timeout", "queue", "dropped", "avg_exec"))
    if kind != "ds" and column:
        raise ToolRejectionError("'dsFilterColumn' applies only to type=ds")
    if kind == "ds" and not column:
        column = "nan"
    return _join(
        "!perf",
        f"type={kind}",
        _kv("dsFilterColumn", column),
        _kv("ds", _opt(a, "ds", pattern=_GLOB_RE)),
        _kv("h", _opt(a, "h", pattern=_GLOB_RE)),
    )


def _b_tlist(a: dict, _c: int) -> str:
    host = _opt(a, "h", pattern=_GLOB_RE)
    method = _opt(a, "c", pattern=_KEY_RE)
    if not host and not method:
        raise ToolRejectionError(
            "!tlist must be filtered with 'h' (host) or 'c' (method); unfiltered it is huge"
        )
    return _join("!tlist", _kv("c", method), _kv("h", host))


def _b_logsurf(a: dict, _c: int) -> str:
    level = _opt(a, "level", ("all", "trace", "debug", "info", "warn", "error")) or "error"
    count = _int(a, "n", 1, 500, default=50)
    files = a.get("files") or ["wrapper.log"]
    if isinstance(files, str):
        files = files.split()
    for f in files:
        if f not in LOG_FILES:
            raise ToolRejectionError(f"'files' may only name {', '.join(LOG_FILES)}")
    return _join("!logsurf", f"level={level}", f"n={count}", *files)


def _fixed(cmd: str) -> Callable[[dict, int], str]:
    return lambda a, c: cmd


def _b_health(a: dict, c: int) -> str:
    return f"!shealthcheck func=detail collector={c}"


def _b_getconfig(a: dict, _c: int) -> str:
    return _join("!getconfig", _opt(a, "key", pattern=_KEY_RE) or _host({}, "key"))


def _b_portal(a: dict, _c: int) -> str:
    return _join("!checkserverconnectivity", _host(a))


def _b_aplist(a: dict, _c: int) -> str:
    states = ("failed", "done", "waiting", "executing", "duplicate", "unknown")
    status = _opt(a, "status", states) or "failed"
    return _join("!aplist", _kv("h", _opt(a, "h", pattern=_GLOB_RE)), f"status={status}")


def _b_splist(a: dict, _c: int) -> str:
    return _join("!splist", _kv("hostname", _opt(a, "hostname", pattern=_HOST_RE)))


def _b_tplist(a: dict, _c: int) -> str:
    states = ("WAITING", "EXECUTING", "DONE", "FAILED", "EMPTY")
    host = _kv("h", _opt(a, "h", pattern=_GLOB_RE))
    return _join("!tplist", host, _kv("status", _opt(a, "status", states)))


def _b_nslookup(a: dict, _c: int) -> str:
    return _join("!nslookup", _host(a), *_list(a, "extra_hosts", _HOST_RE, 0, 4))


def _b_mac(a: dict, _c: int) -> str:
    return _join("!macaddress", _host(a))


def _b_snmpdiagnose(a: dict, _c: int) -> str:
    return _join("!snmpdiagnose", _host(a), *_list(a, "oids", _OID_RE, 0, 5))


def _b_snmpget(a: dict, _c: int) -> str:
    return _join("!snmpget", _host(a), *_list(a, "oids", _OID_RE, 1, 10))


def _b_cim(a: dict, _c: int) -> str:
    cls = _opt(a, "class", pattern=_CLASS_RE) or _host({}, "class")
    return _join("!cim", f"h={_host(a)}", f"c={cls}")


def _b_sslcerts(a: dict, _c: int) -> str:
    port = _int(a, "port", 1, 65535)
    if port is None:
        raise ToolRejectionError("'port' is required")
    return _join("!sslcerts", _host(a), port)


# name -> (group, needs a device host, builder, what it answers)
COMMANDS: dict[str, tuple[str, bool, Callable[[dict, int], str], str]] = {
    "uptime": ("collector", False, _fixed("!uptime"),
               "Is the debug channel alive? A reply at all is the finding"),
    "health_check": ("collector", False, _b_health,
                     "Stored health check, parsed: per-method all-NaN rates, checkpoints"),
    "perf": ("collector", False, _b_perf,
             "Lost work by method or module: type=ds|queue|cpu, dsFilterColumn, ds, h"),
    "getconfig": ("collector", False, _b_getconfig,
                  "One agent.conf value, e.g. collector.wmi.threadpool"),
    "reportercache": ("collector", False, _fixed("!reportercache"),
                      "Delivery to the platform: the reporter's buffer"),
    "checkserverconnectivity": ("collector", False, _b_portal,
                                "DNS, ping, TCP and HTTP from the collector to the portal host"),
    "avslist": ("collector", False, _fixed("!avslist"), "Anti-virus on the collector host"),
    "firewallstatus": ("collector", False, _fixed("!firewallstatus"), "Collector host firewall"),
    "ipaddress": ("collector", False, _fixed("!ipaddress"), "Collector host addresses"),
    "tasklist": ("collector", False, _fixed("!tasklist"), "Processes on the collector host"),
    "logsurf": ("collector", False, _b_logsurf,
                "Collector logs: level, n, files (wrapper.log, sbproxy.log, watchdog.log)"),
    "debughistory": ("collector", False, _fixed("!debughistory"),
                     "Debug commands recently run on this collector"),
    "adlist": ("tasks", False, _fixed("!adlist"), "Active discovery tasks"),
    "aplist": ("tasks", False, _b_aplist, "Auto-properties tasks, failed by default"),
    "splist": ("tasks", False, _b_splist,
               "PropertySource tasks; the only way to see which one is blocked"),
    "tplist": ("tasks", False, _b_tplist, "TopologySource tasks"),
    "nsplist": ("tasks", False, _fixed("!nsplist"), "NetScan tasks"),
    "dxlist": ("tasks", False, _fixed("!dxlist"), "DiagnosticSource tasks"),
    "tlist": ("tasks", False, _b_tlist, "Collection tasks, filtered by h (host) or c (method)"),
    "ping": ("device", True, _b_ping, "Can the collector reach the device now?"),
    "nslookup": ("device", True, _b_nslookup, "Name resolution from the collector"),
    "macaddress": ("device", True, _b_mac, "MAC address of the device"),
    "snmpdiagnose": ("device", True, _b_snmpdiagnose,
                     "SNMP ladder with the device's registered credentials"),
    "snmpget": ("device", True, _b_snmpget, "SNMP GET with the registered credentials"),
    "snmpwalk": ("device", True, _b_snmpwalk, "Walk one subtree (default system), never the root"),
    "wmi": ("device", True, _b_wmi, "WMI SELECT with stored credentials or the collector account"),
    "winrm": ("device", True, _b_winrm, "WinRM with stored credentials, default Win32_Service"),
    "cim": ("device", True, _b_cim, "WBEM/CIM on 5989 for storage and appliances"),
    "http": ("device", False, _b_http, "HTTP GET; the URL must carry its scheme"),
    "sslcerts": ("device", True, _b_sslcerts, "TLS certificate chain; the port is required"),
}  # fmt: skip


def build_cmdline(command: str, args: dict, collector_id: int) -> str:
    """Compose the command line for a named command, or raise ToolRejectionError."""
    if command not in COMMANDS:
        raise ToolRejectionError(f"unknown or disallowed command '{command}'")
    cmdline = COMMANDS[command][2](args or {}, collector_id)
    check_cmdline(cmdline)
    return cmdline


def check_cmdline(cmdline: str) -> None:
    """Final guard on any command line, however it was built."""
    head = re.match(r"^\s*!([A-Za-z0-9_]+)", cmdline or "")
    if not head:
        raise ToolRejectionError("not a debug command")
    if head.group(1).lower() in BLOCKED:
        raise ToolRejectionError(f"!{head.group(1)} changes the collector, its host or a target")
    if "\n" in cmdline or "\r" in cmdline:
        raise ToolRejectionError("a command line cannot span several lines")
    if CREDENTIAL_RE.search(cmdline):
        raise ToolRejectionError(
            "credentials are never sent; probes use the device's stored properties"
        )


# ---------------------------------------------------------------- transport


def is_session_word(text: str) -> bool:
    t = (text or "").strip()
    return bool(t) and len(t) <= 20 and "\n" not in t and t.lower() in SESSION_WORDS


def _rate_ok(bucket: deque, limit: int) -> bool:
    now = time.monotonic()
    while bucket and now - bucket[0] > RATE_WINDOW:
        bucket.popleft()
    return len(bucket) < limit


_PENDING_ERROR_RE = re.compile(
    r"waiting for response|fetched the task|not (yet )?finished|still running|in progress"
)


def _error_text(e: Exception) -> str:
    return str(getattr(e, "details", "") or getattr(e, "message", "") or e)


def is_pending_error(e: Exception) -> bool:
    """True when a GET /debug/{sid} error only says the collector is still working."""
    text = f"{getattr(e, 'message', '')} {getattr(e, 'details', '') or ''} {e}".lower()
    return bool(_PENDING_ERROR_RE.search(text))


def _classify_error(e: Exception) -> tuple[str, str]:
    name = type(e).__name__
    text = f"{getattr(e, 'message', '')} {getattr(e, 'details', '') or ''} {e}".lower()
    if "ratelimit" in name.lower():
        return "rate_limited", "the portal rate limit was hit; try again shortly"
    if "debug" in text and "disable" in text:
        return (
            "disabled",
            "remote debug is disabled on this collector (debug.disable in agent.conf)",
        )
    if "Permission" in name or "Authentication" in name:
        return "refused", "the calling identity lacks the collector Debug permission"
    if "unknown debug command" in text or "invalid debug command" in text:
        return "unsupported", "this collector build does not support the command"
    return "error", f"{name}"


async def run_debug(
    client: Any, collector_id: int, cmdline: str, deadline: float, counter: list | None = None
) -> dict:
    """Send one checked command and poll for its output until the deadline. Never raises."""
    global _READ_FORM
    started = time.monotonic()
    result: dict = {"cmdline": cmdline, "collector_id": collector_id}

    def done(**kw: Any) -> dict:
        result.update(kw)
        result["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        return result

    try:
        check_cmdline(cmdline)
    except ToolRejectionError as e:
        return done(status="rejected_by_tool", detail=str(e))
    if not _rate_ok(_POSTS, POST_LIMIT):
        return done(status="rate_limited", detail="this server's own POST budget is spent")
    try:
        _POSTS.append(time.monotonic())
        if counter is not None:
            counter[0] += 1
        sub = await client.request(
            "POST", "/debug", params={"collectorId": collector_id}, json_body={"cmdline": cmdline}
        )
        session_id = (sub or {}).get("sessionId") or (sub or {}).get("id")
        if not session_id:
            return done(status="error", detail="the debug API returned no session id")
        forms = [("with", {"collectorId": collector_id}), ("without", None)]
        if _READ_FORM == "without":
            forms.reverse()
        last_status = None
        while time.monotonic() + POLL_SECONDS < deadline:
            await asyncio.sleep(POLL_SECONDS)
            for form, params in forms:
                if not _rate_ok(_GETS, GET_LIMIT):
                    return done(
                        status="rate_limited", detail="this server's own GET budget is spent"
                    )
                _GETS.append(time.monotonic())
                if counter is not None:
                    counter[0] += 1
                try:
                    reply = await client.get(f"/debug/{session_id}", params=params)
                except Exception as e:
                    # A command still running on the collector (ping, a slow walk) can
                    # come back as an API error whose text says the agent is still
                    # working. That is a pending session, not a failure: keep polling.
                    if not is_pending_error(e):
                        raise
                    last_status = _error_text(e)[:200]
                    break
                output = str((reply or {}).get("output") or "")
                if output and not is_session_word(output):
                    _READ_FORM = form
                    return done(status="answered", read_form=form, output=output)
                if output:
                    last_status = output.strip()
        detail = "no answer inside the time budget"
        if last_status:
            detail += f"; last session status '{last_status}'"
        return done(status="no_reply", detail=detail)
    except Exception as e:
        status, detail = _classify_error(e)
        return done(status=status, detail=detail, error_body=_error_text(e)[:4000])


# ---------------------------------------------------------------- health check parsing

_BLOCK_RE = re.compile(r"^=+\$?([^=\n]+?)=+\s*$", re.MULTILINE)
_SCHED_RE = re.compile(r"is scheduled at (.+?), finished at (.+?), status (-?\d+)")
_USAGE_RE = re.compile(
    r"invalid input argument|invalid debug command|usage\s*:|invalid host\.|invalid url"
    r"|configuration key \[[^\]]*\] not found"
)
_NAN_RE = re.compile(r"(\d+) of (\d+) tasks \(([\d.]+)%\)")


def _checkpoints(body: str) -> list[dict]:
    idx = body.find(":checkpoints:")
    if idx < 0:
        return []
    text = body[idx + len(":checkpoints:") :].lstrip()
    if not text.startswith("["):
        return []
    depth, end, in_str, esc = 0, -1, False, False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end < 0:
        return []
    try:
        data = json.loads(text[:end])
    except ValueError:
        return []
    return data if isinstance(data, list) else [data]


def parse_health_check(output: str) -> dict:
    """Summarise a !shealthcheck func=detail reply. Unparsed parts are left out, never guessed."""
    text = output or ""
    marks = list(_BLOCK_RE.finditer(text))
    blocks = []
    for i, m in enumerate(marks):
        body = text[m.end() : marks[i + 1].start() if i + 1 < len(marks) else len(text)]
        blocks.append((m.group(1).strip(), body))

    methods: list[dict[str, Any]] = []
    idle: list[str] = []
    not_ok: list[dict[str, Any]] = []
    nan_modules: list[dict[str, Any]] = []
    facts: dict = {}
    scheduled = []
    for name, body in blocks:
        sched = _SCHED_RE.search(body)
        if sched:
            scheduled.append(sched.group(1).strip())
            if sched.group(3) != "0":
                not_ok.append({"check": name, "detail": f"script status {sched.group(3)}"})
        for cp in _checkpoints(body):
            if not isinstance(cp, dict):
                continue
            cp_name = str(cp.get("name", ""))
            detail = cp.get("detail")
            status = str(cp.get("status", ""))
            if status and status.upper() != "OK":
                not_ok.append({"check": cp_name, "status": status, "detail": detail})
            if cp_name.startswith("biz.DataSource."):
                method = cp_name.split(".", 2)[2]
                match = _NAN_RE.search(str(detail))
                if match:
                    methods.append(
                        {
                            "method": method,
                            "all_nan": int(match.group(1)),
                            "attempts": int(match.group(2)),
                            "all_nan_pct": float(match.group(3)),
                            "checkpoint_status": status,
                        }
                    )
                elif "no tasks" in str(detail).lower():
                    idle.append(method)
            elif cp_name == "cogs.DSTableByNan" and isinstance(detail, list):
                rows = [r for r in detail if isinstance(r, dict) and r.get("nanDsi")]
                rows.sort(key=lambda r: -(r.get("nanDsi") or 0))
                nan_modules = [
                    {
                        "module": r.get("dsName"),
                        "method": r.get("collectorName"),
                        "nan_instances": r.get("nanDsi"),
                        "timeout_instances": r.get("timeoutDsi"),
                        "dropped_instances": r.get("droppedDsi"),
                    }
                    for r in rows[:10]
                ]
            elif cp_name in (
                "basic.Version",
                "basic.Role",
                "biz.InstanceCount",
                "biz.ReportingData",
            ) or cp_name in ("module.Collector", "module.Watchdog"):
                facts[cp_name] = detail

    methods.sort(key=lambda m: -m["all_nan_pct"])
    return {
        "checks_parsed": len(blocks),
        "last_run_started": scheduled[0] if scheduled else None,
        "methods_by_all_nan_rate": methods,
        "idle_methods": idle,
        "not_ok": not_ok,
        "nan_by_module": nan_modules,
        "facts": facts,
        "reading_note": (
            "Rates lead, checkpoint status does not: a method can show OK with a double-digit "
            "share of its tasks returning NaN for every datapoint."
        ),
    }


# ---------------------------------------------------------------- the tool


async def collector_debug(
    client: LogicMonitorClient,
    command: str,
    collector_id: int | None = None,
    device_id: int | None = None,
    args: dict | None = None,
    budget_seconds: float = BUDGET_DEFAULT,
    max_output_chars: int = OUTPUT_DEFAULT,
) -> list[TextContent]:
    """Run one allowlisted collector debug command. See the module docstring."""
    try:
        started = time.monotonic()
        args = dict(args or {})
        calls = [0]
        if command not in COMMANDS:
            return format_response(
                {
                    "status": "rejected_by_tool",
                    "detail": f"unknown or disallowed command '{command}'",
                    "commands": sorted(COMMANDS),
                }
            )
        group, needs_host, _builder, _desc = COMMANDS[command]

        # A device id fills in the host and, when not given, the collector that serves it.
        device_note = None
        if device_id is not None:
            calls[0] += 1
            dev = await client.get(
                f"/device/devices/{int(device_id)}",
                params={"fields": "id,name,displayName,currentCollectorId"},
            )
            if needs_host and not args.get("host"):
                args["host"] = dev.get("name")
            if collector_id is None:
                collector_id = dev.get("currentCollectorId")
            device_note = {"device_id": dev.get("id"), "host_used": args.get("host")}
        if not collector_id:
            return format_response(
                {"status": "rejected_by_tool", "detail": "collector_id (or device_id) is required"}
            )
        collector_id = int(collector_id)

        try:
            cmdline = build_cmdline(command, args, collector_id)
        except ToolRejectionError as e:
            return format_response(
                {"status": "rejected_by_tool", "command": command, "detail": str(e)}
            )

        budget = min(max(float(budget_seconds), 2.0), BUDGET_MAX)
        result = await run_debug(client, collector_id, cmdline, time.monotonic() + budget, calls)
        output = result.pop("output", "")
        cap = min(max(int(max_output_chars), 500), OUTPUT_MAX)
        response: dict = {
            "command": command,
            "group": group,
            **result,
            "budget_seconds": budget,
            "api_calls": calls[0],
        }
        if device_note:
            response["device"] = device_note
        if output:
            response["output_chars"] = len(output)
            response["truncated"] = len(output) > cap
            if command == "health_check":
                response["parsed"] = parse_health_check(output)
                response["output"] = output[: min(cap, 4000)]
                response["truncated"] = len(output) > min(cap, 4000)
            else:
                response["output"] = output[:cap]
            head = output[:300].lower()
            if "configuration key [" in head and "not found" in head:
                response["note"] = (
                    "The collector has no such agent.conf key. Check the key name (keys carry "
                    "their prefix, e.g. collector.wmi.threadpool). This is about the command, "
                    "not the collector."
                )
            elif _USAGE_RE.search(head):
                response["note"] = (
                    "The collector rejected the command syntax and printed its usage. This is "
                    "about the command, not the device."
                )
        response["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        return format_response(response)
    except Exception as e:
        return handle_error(e)
