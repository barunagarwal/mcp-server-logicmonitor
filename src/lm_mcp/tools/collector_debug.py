# Description: Collector debug for investigations: a safe, typed, time-boxed debug command runner.
# Description: Shared debug transport and health-check parser for collector tools.

"""Collector debug.

Runs one collector debug command and returns what the collector said. Built for agents (Edwin
AI, Claude, automations) as much as for people, so the guards live here, not in the caller:

- It is gated as a write. Every allowed command is meant to read, but the call runs it on the
  collector and opens a debug session, so collector_debug needs LM_ENABLE_WRITE_OPERATIONS.
- Callers never send free text. They name a command from COMMANDS and pass that command's
  typed arguments, and any other argument key is refused; this module builds the command line.
  Anything that would change the collector, run code on its host or take a credential is not
  in COMMANDS, and a final allowlist check refuses it again at send time. http sends only a GET
  to the device's own host; a device that acts on a GET (a reboot URL) can still be changed by
  one, so http is a write like the rest.
- The target is never the caller's to choose. Device probes take the host from the device_id
  record (a `host` argument is refused) and run on the collector that record names, since a
  private address means something else inside another collector's network; an http URL must
  name that same host, and checkserverconnectivity targets the portal this client is
  configured for.
- No credentials. Protocol probes run on the device's stored properties (snmp.*, wmi.*, cim.*),
  so nothing secret lands in the portal's Audit Log, which keeps debug history as sent. A URL
  with userinfo or a credential-named query parameter is refused, getconfig reads only
  thread-pool and timeout keys, debughistory is not offered, and output is passed through a
  best-effort redaction of secret values (key=value, key: value, JSON, XML, URL userinfo).
- One wall-clock budget per call, enforced on the device read, the POST and every poll. A
  command the collector does not pick up in time returns no_reply with its elapsed time. The
  output is masked only to a margin past what will be shown, and the masking and the
  health-check parse grow with the length of the text, so a hostile reply cannot hold the
  server either.
- Honest states: answered, no_reply, refused, disabled, unsupported, rate_limited, error, and a
  request refused before sending, which is a validation error. Never a guessed success.

Transport facts, each observed on live portals:

- POST /debug?collectorId=N with {"cmdline": ...} returns a session id. The collector fetches
  the command on its next check-in, so the result is polled with GET /debug/{sessionId}.
- Whether collectorId belongs on the GET differs between portals (each form has returned
  "cancelled" while the other returned the output). Both forms are asked on the same session
  and the one that answers is remembered per portal for the life of the process.
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
import bisect
import contextlib
import json
import logging
import math
import re
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeVar
from urllib.parse import parse_qsl, urlsplit

from mcp.types import TextContent

from lm_mcp.tools import (
    ErrorContent,
    format_response,
    handle_error,
    require_write_permission,
    validation_error,
)

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
# A credential key written as a parameter (key=value) anywhere in the line, not only at a word
# start after whitespace. "User = 'x'" in a WQL comparison is not a parameter and passes.
CREDENTIAL_RE = re.compile(
    r"(?<![A-Za-z0-9])(password|passwd|pass|pwd|authToken|privToken|community|username|user"
    r"|security|secret|token|apikey|api_key)=",
    re.IGNORECASE,
)
MAX_CMDLINE = 2048

# ---------------------------------------------------------------- output redaction
# Best effort, and a second line of defence. The guarantees are elsewhere: no credential is
# ever sent, getconfig reads only thread-pool and timeout keys, and debughistory is not
# offered. Masking catches the common shapes a collector or device prints a secret in; an
# unusual shape can still slip through, and masking errs toward hiding too much rather than
# too little.
#
# Output is hostile input, so every scan either moves forward past what it read or is capped
# at a fixed length: the work grows with the length of the text, never with its square.

# A key names a secret when it ends in one of these words. The short words (pass, pwd, pw)
# count only at the start of the key or after a separator (wmi.pass, x_sid) or a camelCase
# step (wmiPass), so compass, bypass and superpass are not keys; the longer words count at the
# end of any key (dbpassword, snmp.authtoken, CLIENTSECRET).
_SECRET_KEY_WORDS = (
    "password", "passwd", "pass", "passphrase", "secret", "token", "community", "credential",
    "credentials", "signature", "authorization", "cookie", "bearer", "apikey", "api_key",
    "api-key", "accesskey", "access_key", "access-key", "privatekey", "private_key",
    "private-key", "secretkey", "secret_key", "secret-key", "sessionid", "session_id",
    "session-id", "storepass", "keypass", "authcode", "auth_code", "auth-code", "jwt", "pw",
    "pwd", "sig", "otp",
)  # fmt: skip
_SHORT_WORD = 4  # words this long or shorter need a boundary before them
_ASCII_LOWER_OR_DIGIT = frozenset("abcdefghijklmnopqrstuvwxyz0123456789")
_ASCII_UPPER = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
_JVM_FLAG_RE = re.compile(r"^-+D?")


def _is_secret_key(key: str) -> bool:
    """True when a key (wmi.pass, -Ddb.password, clientSecret, snmp.authtoken) names a secret."""
    key = _JVM_FLAG_RE.sub("", key)  # -Dwmi.pass, --password
    low = key.lower()
    for word in _SECRET_KEY_WORDS:
        if not low.endswith(word):
            continue
        start = len(key) - len(word)
        if start == 0 or len(word) > _SHORT_WORD:
            return True
        before, first = key[start - 1], key[start]
        if before in "._:-" or (before in _ASCII_LOWER_OR_DIGIT and first in _ASCII_UPPER):
            return True
    return False


_CAP = 512  # sets how far a <name> element and a bracketed value are read
_MASK_MARGIN = _CAP * 8  # text masked past the cut, so a secret the cut splits is still seen whole
# key=value, key: value, "key": "value", -Dkey=value. The key is one token: word characters,
# dots and dashes, starting where the previous token ended.
_KEYED_RE = re.compile(r"""(?<![\w.-])["']?([\w.-]+)["']?[ \t]*([=:])""")
# --password value, -storepass value
_FLAG_RE = re.compile(r"(?<![\w.-])--?([A-Za-z][\w.-]+)(?=[ \t])")
_SPACES_RE = re.compile(r"[ \t]*")
# A quoted value with backslash escapes, on one line.
_QUOTED_RE = re.compile(r""""(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'""")
# An unquoted value ends at the line end, at markup (<tag, />), at a quote that closes the
# string the key sat in ("detail": "proxy pass: none", "status": ...), or where the next key
# starts. After "key=", the next key is "k=v", "k: " or a -flag; after "key:", the display
# form, only the next "k: ". A "=" that pads base64 (Basic dXNlcjpw==) never starts a key.
_STOPS = r"""[\r\n]|<(?=[A-Za-z/!?])|/>|["'](?=[ \t]*(?:[,;}\]>/\r\n]|\Z))"""
# After "key:", a JSON value also ends where its object or array closes: {"a":{"password":1}}.
_JSON_STOPS = r"""|[}\]](?=[ \t]*(?:[,}\]\r\n]|\Z))"""
_NEXT = r"""(?:[,;&][ \t]*|[ \t])"""
_VALUE_END_RES = {
    "=": re.compile(
        rf"""{_STOPS}|{_NEXT}(?:["']?[\w.:-]+["']?[ \t]*=(?=[^=\s])"""
        r"""|["']?[\w.-]+["']?[ \t]*:(?=[ \t\r\n]|\Z)|--?[A-Za-z])"""
        r"""|[,;&][ \t]*["'][\w.-]+["'][ \t]*:"""
    ),
    ":": re.compile(
        rf"""{_STOPS}{_JSON_STOPS}|{_NEXT}["']?[\w.-]+["']?[ \t]*:(?=[ \t\r\n]|\Z)"""
        r"""|[,;&][ \t]*["'][\w.-]+["'][ \t]*:"""
    ),
}
_KEY_AHEAD_RE = re.compile(r"[\w.-]+[ \t]*=")
# "password:" with its value on the next, indented line (YAML, pretty-printed JSON)
_NEXT_LINE_VALUE_RE = re.compile(r"\r?\n[ \t]+(?=[^\s])")
_KEY_LINE_RE = re.compile(r"""["']?[\w.-]+["']?[ \t]*[=:]|[-#]""")
# Authorization: Bearer xxx is a key; a bare "Bearer xxx" in a log line is caught here.
_BEARER_RE = re.compile(r"(?<![\w-])(bearer[ \t]+)([A-Za-z0-9._~+/=-]+)", re.IGNORECASE)
# A PEM private key block: a BEGIN line naming a PRIVATE KEY, the body, an END line.
_PEM_RE = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY[A-Z ]*-----")
# name="wmi.pass" ... value="x", in either order, anywhere inside one XML tag or one JSON
# object: the text between two of the characters { } < >.
_SEGMENT_RE = re.compile(r"[^{}<>]+")
_NAME_FIELD_RE = re.compile(
    r"""(?<![\w.:-])["']?(?:name|key)["']?\s*[=:]\s*"""
    r"""(?:"([^"]*)"|'([^']*)'|([\w.:-]+))""",
    re.IGNORECASE,
)
_VALUE_FIELD_RE = re.compile(
    r"""((?<![\w.:-])["']?value["']?\s*[=:]\s*)(?:"([^"]*)"|'([^']*)'|([^\s"',;&]+))""",
    re.IGNORECASE,
)
_PAIR_SPAN = 512  # outside braces and tags, how far apart a name and its value field may be
# <password>value</password>, <Password type="x">, <entry key="wmi.pass">value</entry>
_TAG_RE = re.compile(r"<([A-Za-z_][\w.:-]*)((?:\s[^<>]*)?)>")
_TAG_NAME_ATTR_RE = re.compile(
    r"""(?<![\w.:-])(?:name|key)\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.IGNORECASE
)
_LOOSE_TEXT_RE = re.compile(r"[^<]*")  # without a closing tag, the text up to the next tag
# <name>x.password</name><value>hunter2</value>, as Hadoop, Spring and .NET configs write it
_NAMED_VALUE_RE = re.compile(r"\s*<value(?:\s[^<>]*)?>", re.IGNORECASE)
_PATH_RE = re.compile(r"""["']?(?:[~/]|[A-Za-z]:[\\/])""")  # pwd: /usr/local, a directory
# scheme://userinfo@host, and scheme:\/\/ as JSON escapes it
_SCHEME_RE = re.compile(r"(?<![A-Za-z0-9+.-])[A-Za-z][A-Za-z0-9+.-]*:(?://|\\/\\/)")
# The authority ends at / ? # (RFC 3986), at whitespace and at characters an authority never
# holds (quotes, < > \ { } |), and at a comma, where text lists one URL after another.
_AUTHORITY_END_RE = re.compile(r"""[\s/?#"'<>\\{}|,]""")
# curl -u user:password, --user user:password
_USER_FLAG_RE = re.compile(r"(?<![\w.-])(--user|-u)([ \t=]+[^\s:]+:)(\S+)")


def _mask_value(text: str, pos: int, out: list[str], sep: str = "=") -> int:
    """Append the masked value that starts at pos and return where it ends. A quoted value
    keeps its quotes, and an empty one is kept whole: an empty password is itself a finding."""
    quoted = _QUOTED_RE.match(text, pos)
    if quoted:
        q = quoted.group(0)
        out.append(q if len(q) == 2 else f"{q[0]}***{q[0]}")
        return quoted.end()
    if pos >= len(text) or text[pos] in "\r\n" or text.startswith("<", pos):
        return pos
    if text[pos] in "[{":
        close = _bracket_end(text, pos)
        if close is not None:
            out.append("***")
            return close
    out.append("***")
    stop = _VALUE_END_RES[sep].search(text, pos + 1)
    return stop.start() if stop else len(text)


def _bracket_end(text: str, pos: int) -> int | None:
    """The end of the JSON array or object that opens at pos, read up to _CAP*8 characters;
    when it does not close inside that, the rest of the text from pos, so nothing leaks."""
    depth, in_str, esc = 0, False, False
    limit = min(len(text), pos + _CAP * 8)
    for i in range(pos, limit):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
            if depth == 0:
                return i + 1
    return len(text) if limit < len(text) or depth else None


def _mask_keyed(text: str) -> str:
    """key=value and key: value."""
    out, pos = [], 0
    while True:
        m = _KEYED_RE.search(text, pos)
        if not m:
            break
        out.append(text[pos : m.end()])
        pos = m.end()
        if not _is_secret_key(m.group(1)):
            continue
        spaces = _SPACES_RE.match(text, pos)
        start = spaces.end() if spaces else pos
        out.append(text[pos:start])
        if m.group(1).lower() == "pwd" and m.group(2) == ":" and _PATH_RE.match(text, start):
            pos = start  # pwd: /usr/local/bin is a working directory
            continue
        if m.group(2) == "=" and start > pos and _KEY_AHEAD_RE.match(text, start):
            pos = start  # "wmi.pass= wmi.user=x": the password is empty
            continue
        if m.group(2) == ":":
            below = _NEXT_LINE_VALUE_RE.match(text, start)
            if below and not _KEY_LINE_RE.match(text, below.end()):
                out.append(text[start : below.end()])
                start = below.end()
        pos = _mask_value(text, start, out, m.group(2))
    out.append(text[pos:])
    return "".join(out)


def _mask_flags(text: str) -> str:
    """--password value, --password "two words" and -storepass value."""
    out, pos = [], 0
    while True:
        m = _FLAG_RE.search(text, pos)
        if not m:
            break
        out.append(text[pos : m.end()])
        pos = m.end()
        if _is_secret_key(m.group(1)):
            spaces = _SPACES_RE.match(text, pos)
            start = spaces.end() if spaces else pos
            out.append(text[pos:start])
            pos = _mask_value(text, start, out)
    out.append(text[pos:])
    return "".join(out)


def _mask_user_flags(text: str) -> str:
    """curl -u user:password and --user user:password keep the user."""
    return _USER_FLAG_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}***", text)


def _mask_pem(text: str) -> str:
    """The body of a PEM private key, to its END line or, without one, to the end."""
    out, pos = [], 0
    while True:
        m = _PEM_RE.search(text, pos)
        if not m:
            break
        out.append(text[pos : m.end()])
        end = text.find("-----END", m.end())
        end = len(text) if end < 0 else end
        out.append("***")
        pos = end
    out.append(text[pos:])
    return "".join(out)


def _mask_value_field(m: re.Match[str]) -> str:
    if m.group(4) is not None:
        return f"{m.group(1)}***"  # value=hunter2, unquoted
    value = m.group(2) if m.group(2) is not None else m.group(3)
    if not value:
        return m.group(0)
    quote = '"' if m.group(2) is not None else "'"
    return f"{m.group(1)}{quote}***{quote}"


def _mask_segment(m: re.Match[str]) -> str:
    segment = m.group(0)
    secret_at = [
        f.start()
        for f in _NAME_FIELD_RE.finditer(segment)
        if _is_secret_key(f.group(1) or f.group(2) or f.group(3) or "")
    ]
    if not secret_at:
        return segment

    if m.start() > 0 and m.end() < len(m.string):
        # Inside one tag or object: every value field goes with the secret name.
        return _VALUE_FIELD_RE.sub(_mask_value_field, segment)

    def near(v: re.Match[str]) -> str:
        # Outside braces and tags, only a value field close to a secret name field: one
        # "name: token" must not mask every "value:" in the text.
        i = bisect.bisect_left(secret_at, v.start() - _PAIR_SPAN)
        if i < len(secret_at) and secret_at[i] <= v.end() + _PAIR_SPAN:
            return _mask_value_field(v)
        return v.group(0)

    return _VALUE_FIELD_RE.sub(near, segment)


def _mask_pairs(text: str) -> str:
    """Every value field in a tag or object whose name/key field names a secret."""
    return _SEGMENT_RE.sub(_mask_segment, text)


def _mask_content(text: str, pos: int, tag: str, unclosed: dict[str, int], out: list[str]) -> int:
    """Mask an element's content from pos to its closing tag, child elements, CDATA and line
    breaks included; without a closing tag, to the next tag. Each tag is looked for to the end
    of the text at most once from where it is missing, so many unclosed tags cost one scan."""
    close = -1 if unclosed.get(tag, len(text) + 1) <= pos else text.find(f"</{tag}", pos)
    if close < 0:
        unclosed[tag] = pos
        loose = _LOOSE_TEXT_RE.match(text, pos)
        close = loose.end() if loose else pos
    out.append("***" if text[pos:close].strip() else text[pos:close])
    return close


def _mask_elements(text: str) -> str:
    """The content of an element whose tag, or whose name/key attribute, names a secret."""
    out, pos = [], 0
    unclosed: dict[str, int] = {}  # tag -> a position after which it never closes
    while True:
        m = _TAG_RE.search(text, pos)
        if not m:
            break
        out.append(text[pos : m.end()])
        pos = m.end()
        tag, attrs = m.group(1), m.group(2)
        if attrs.rstrip().endswith("/"):
            continue  # <x/> has no content
        if tag.lower() in ("name", "key"):
            # <name>x.password</name><value>hunter2</value>: mask the value element.
            close = text.find(f"</{tag}>", pos, pos + _CAP)
            if close >= 0 and _is_secret_key(text[pos:close].strip()):
                value = _NAMED_VALUE_RE.match(text, close + len(tag) + 3)
                if value:
                    out.append(text[pos : value.end()])
                    pos = _mask_content(text, value.end(), "value", unclosed, out)
            continue
        named = (a or b for a, b in _TAG_NAME_ATTR_RE.findall(attrs))
        if not (_is_secret_key(tag) or any(_is_secret_key(n) for n in named)):
            continue
        pos = _mask_content(text, pos, tag, unclosed, out)
    out.append(text[pos:])
    return "".join(out)


def _mask_userinfo(text: str) -> str:
    """scheme://user:password@host keeps the user; scheme://token@host masks it all."""
    out, pos = [], 0
    while True:
        m = _SCHEME_RE.search(text, pos)
        if not m:
            break
        stop = _AUTHORITY_END_RE.search(text, m.end())
        span_end = stop.start() if stop else len(text)
        at = text.rfind("@", m.end(), span_end)
        out.append(text[pos : m.end()])
        if at < 0:
            pos = m.end()
            continue
        userinfo = text[m.end() : at]
        out.append(f"{userinfo.split(':', 1)[0]}:***" if ":" in userinfo else "***")
        pos = at
    out.append(text[pos:])
    return "".join(out)


def redact(text: str) -> str:
    """Mask the secret values the collector's output shows, keeping their keys. Best effort;
    see the comment above the patterns."""
    out = text or ""
    out = _mask_pem(out)
    out = _mask_keyed(out)
    out = _mask_flags(out)
    out = _mask_user_flags(out)
    out = _BEARER_RE.sub(lambda m: f"{m.group(1)}***", out)
    out = _mask_pairs(out)
    out = _mask_elements(out)
    out = _mask_userinfo(out)
    return out


def redact_values(data: Any) -> Any:
    """Mask a parsed structure: every string, the value under a secret-named key, and the
    value beside a name/key field that names a secret."""
    if isinstance(data, str):
        return redact(data)
    if isinstance(data, list):
        return [redact_values(v) for v in data]
    if not isinstance(data, dict):
        return data
    named = any(
        str(k).lower() in ("name", "key") and isinstance(v, str) and _is_secret_key(v)
        for k, v in data.items()
    )
    masked = {}
    for k, v in data.items():
        secret = _is_secret_key(str(k)) or (named and str(k).lower() == "value")
        masked[k] = "***" if secret and v not in (None, "") else redact_values(v)
    return masked


_READ_FORMS: dict[str, str] = {}  # portal host -> "with" | "without", learned per process
_POSTS: deque = deque()
_GETS: deque = deque()


class ToolRejectionError(ValueError):
    """The request was refused by this tool before anything was sent."""


class CommandLineRejectionError(ToolRejectionError):
    """The composed command line, not one argument, was refused (see check_cmdline)."""


@dataclass(frozen=True)
class Target:
    """Where a command runs and what it may point at, fixed before any argument is read."""

    collector_id: int
    host: str | None = None  # the device record's host, for device probes
    portal_host: str | None = None  # the configured portal, for checkserverconnectivity


# ---------------------------------------------------------------- argument validation

# A letter, digit or "[" first, so a name such as "-n" cannot read as an option.
_HOST_RE = re.compile(r"^[A-Za-z0-9\[][A-Za-z0-9._:\-\[\]%]*$")
_GLOB_RE = re.compile(r"^[A-Za-z0-9._:\-*?\[\]%]+$")
# [0-9], not \d, which also matches other scripts' digits; no leading zeros.
_OID_RE = re.compile(r"^\.?(0|[1-9][0-9]{0,9})(\.(0|[1-9][0-9]{0,9})){0,63}$")
_KEY_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")
_CLASS_RE = re.compile(r"^[A-Za-z0-9_]+$")
# The root and the tops of mgmt, mib-2, private and enterprises: a walk there is the whole device.
_ROOT_OIDS = {(0,), (1,), (2,), (1, 3), (1, 3, 6), (1, 3, 6, 1), (1, 3, 6, 1, 2),
              (1, 3, 6, 1, 2, 1), (1, 3, 6, 1, 4), (1, 3, 6, 1, 4, 1)}  # fmt: skip
LOG_FILES = ("wrapper.log", "sbproxy.log", "watchdog.log")


def _device(t: Target) -> str:
    if not t.host:
        raise ToolRejectionError("device_id is required: the target is the device record's host")
    return t.host


def _required(args: dict, key: str) -> str:
    value = str(args.get(key) or "").strip()
    if not value:
        raise ToolRejectionError(f"'{key}' is required")
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
    value = args.get(key)
    if value is None or value == "":
        value = default
    if value is None:
        return None
    if isinstance(value, bool) or (isinstance(value, float) and not value.is_integer()):
        raise ToolRejectionError(f"'{key}' must be a whole number")
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
    if not isinstance(raw, list):
        raise ToolRejectionError(f"'{key}' must be a list")
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


def _b_ping(a: dict, t: Target) -> str:
    kind = _opt(a, "type", ("default", "all", "proxy", "sys", "java"))
    return _join("!ping", _kv("type", kind), _kv("count", _int(a, "count", 1, 20)), _device(t))


def _b_snmpwalk(a: dict, t: Target) -> str:
    oid = _opt(a, "oid", pattern=_OID_RE) or ".1.3.6.1.2.1.1"
    if tuple(int(part) for part in oid.strip(".").split(".")) in _ROOT_OIDS:
        raise ToolRejectionError(
            "walking from the root of the tree, or the top of mib-2 or enterprises, is "
            "refused; walk a subtree"
        )
    return _join("!snmpwalk", _kv("timeout", _int(a, "timeout", 1, 120)), _device(t), oid)


_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
_WQL_RE = re.compile(
    rf"^SELECT\s+(\*|{_IDENT}(\s*,\s*{_IDENT})*)\s+FROM\s+{_IDENT}(\s+WHERE\s+(?P<where>.+))?$",
    re.IGNORECASE,
)
_WHERE_CHARS_RE = re.compile(r"^[A-Za-z0-9_ '%.,:\\/\-<>=!()]+$")


def _b_wmi(a: dict, t: Target) -> str:
    """One WQL SELECT: SELECT * | cols FROM Class [WHERE ...], with no key=value token.

    The collector reads any key=value token on the line as a parameter of !wmi, so a query
    holding one (h=..., or Name='x' written without spaces) could replace the command's own
    parameters. Comparisons are written with spaces around the operator: Name = 'x'.
    """
    query = " ".join(str(a.get("query") or "select * from Win32_Service").split())
    match = _WQL_RE.match(query)
    if not match:
        raise ToolRejectionError(
            "'query' must be one WQL SELECT: SELECT * | col[, col] FROM Class [WHERE ...]"
        )
    where = match.group("where") or ""
    if where and not _WHERE_CHARS_RE.match(where):
        raise ToolRejectionError("the WHERE clause holds a character the tool does not allow")
    if re.search(r"[A-Za-z0-9_]=", query):
        raise ToolRejectionError(
            "a key=value token in the query would become a !wmi parameter; "
            "write comparisons with spaces, e.g. Name = 'x'"
        )
    auth = _opt(a, "authType", ("NTLMv2", "Kerberos"))
    return _join("!wmi", f"h={_device(t)}", _kv("authType", auth), query)


def _b_winrm(a: dict, t: Target) -> str:
    return _join(
        "!winrm",
        f"host={_device(t)}",
        _kv("auth", _opt(a, "auth", ("Negotiate", "Kerberos"))),
        _kv("useSSL", _opt(a, "useSSL", ("true", "false"))),
        _kv("certCheck", _opt(a, "certCheck", ("true", "false"))),
        _kv("timeout", _int(a, "timeout", 1, 120)),
    )


# Query parameter names that carry a credential. Long words match anywhere in the name
# (accessToken, db_password); short ones match only as a whole word of it (pw, auth, sid), so
# author, oauth_state or sessions stay allowed.
_SECRET_PARAM_ANYWHERE = (
    "password", "passwd", "passphrase", "secret", "token", "apikey", "credential", "signature",
    "bearer", "privatekey", "community", "authorization", "accesskey", "authcode",
)  # fmt: skip
_SECRET_PARAM_WORDS = {
    "pw", "pwd", "pass", "key", "auth", "session", "sessionid", "sid", "sig", "user", "username",
    "login", "jwt", "otp", "cookie",
}  # fmt: skip


def _is_secret_param(name: str) -> bool:
    flat = re.sub(r"[^a-z0-9]", "", name.lower())
    if any(word in flat for word in _SECRET_PARAM_ANYWHERE):
        return True
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    words = {w for w in re.split(r"[^a-z0-9]+", spaced.lower()) if w}
    return bool(words & _SECRET_PARAM_WORDS)


def _bare(host: str) -> str:
    return host.strip("[]").lower()


def _b_http(a: dict, t: Target) -> str:
    """An HTTP(S) GET to the device itself: the URL's host must be the device record's host."""
    device = _device(t)
    url = _required(a, "url")
    if re.search(r"\s", url):
        raise ToolRejectionError("'url' cannot contain whitespace")
    try:
        parts = urlsplit(url)
        _ = parts.port  # raises on a malformed port
    except ValueError as e:
        raise ToolRejectionError("'url' is not a valid URL") from e
    if parts.scheme not in ("http", "https"):
        raise ToolRejectionError("'url' must start with http:// or https://")
    if "#" in url:
        raise ToolRejectionError("'url' cannot carry a fragment (#...)")
    if ";" in parts.path or ";" in parts.query:
        raise ToolRejectionError("'url' cannot carry ';' parameters")
    if "@" in parts.netloc:
        raise ToolRejectionError("'url' cannot carry user information (user:password@)")
    if not parts.hostname:
        raise ToolRejectionError("'url' must name the device's host")
    if _bare(parts.hostname) != _bare(device):
        raise ToolRejectionError(
            f"'url' must point at the device itself ({device}), not another host"
        )
    for name, _value in parse_qsl(parts.query, keep_blank_values=True):
        if _is_secret_param(name):
            raise ToolRejectionError(f"'url' carries a credential-named parameter '{name}'")
    return _join("!http", _kv("timeout", _int(a, "timeout", 1, 120)), url)


def _b_perf(a: dict, _t: Target) -> str:
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


def _b_tlist(a: dict, _t: Target) -> str:
    host = _opt(a, "h", pattern=_GLOB_RE)
    method = _opt(a, "c", pattern=_KEY_RE)
    if (not host or not re.search(r"[A-Za-z0-9]", host)) and not method:
        raise ToolRejectionError(
            "!tlist must be filtered with 'h' (host) or 'c' (method); unfiltered it is huge"
        )
    return _join("!tlist", _kv("c", method), _kv("h", host))


def _b_logsurf(a: dict, _t: Target) -> str:
    level = _opt(a, "level", ("all", "trace", "debug", "info", "warn", "error")) or "error"
    count = _int(a, "n", 1, 500, default=50)
    files = a.get("files") or ["wrapper.log"]
    if isinstance(files, str):
        files = files.split()
    if not isinstance(files, list):
        raise ToolRejectionError(f"'files' must be a list naming {', '.join(LOG_FILES)}")
    for f in files:
        if f not in LOG_FILES:
            raise ToolRejectionError(f"'files' may only name {', '.join(LOG_FILES)}")
    unique = list(dict.fromkeys(files))
    return _join("!logsurf", f"level={level}", f"n={count}", *unique)


def _fixed(cmd: str) -> Callable[[dict, Target], str]:
    return lambda a, t: cmd


def _b_health(a: dict, t: Target) -> str:
    return f"!shealthcheck func=detail collector={t.collector_id}"


# agent.conf keys getconfig may read: the thread pool and timeout of one collection method.
# Nothing else is read, so no other setting, credential or proxy value can be asked for.
_CONFIG_KEY_RE = re.compile(r"^collector\.[a-z][a-z0-9]*\.(threadpool|timeout)$")


def _b_getconfig(a: dict, _t: Target) -> str:
    key = _required(a, "key")
    if not _CONFIG_KEY_RE.match(key):
        raise ToolRejectionError(
            "'key' must be a collection method's thread pool or timeout, "
            "e.g. collector.wmi.threadpool or collector.snmp.timeout"
        )
    return _join("!getconfig", key)


def _b_portal(a: dict, t: Target) -> str:
    if not t.portal_host:
        raise ToolRejectionError("the configured portal host is not known to this client")
    return _join("!checkserverconnectivity", t.portal_host)


def _b_aplist(a: dict, _t: Target) -> str:
    states = ("failed", "done", "waiting", "executing", "duplicate", "unknown")
    status = _opt(a, "status", states) or "failed"
    return _join("!aplist", _kv("h", _opt(a, "h", pattern=_GLOB_RE)), f"status={status}")


def _b_splist(a: dict, _t: Target) -> str:
    return _join("!splist", _kv("hostname", _opt(a, "hostname", pattern=_HOST_RE)))


def _b_tplist(a: dict, _t: Target) -> str:
    states = ("WAITING", "EXECUTING", "DONE", "FAILED", "EMPTY")
    host = _kv("h", _opt(a, "h", pattern=_GLOB_RE))
    return _join("!tplist", host, _kv("status", _opt(a, "status", states)))


def _b_nslookup(a: dict, t: Target) -> str:
    return _join("!nslookup", _device(t))


def _b_mac(a: dict, t: Target) -> str:
    return _join("!macaddress", _device(t))


def _b_snmpdiagnose(a: dict, t: Target) -> str:
    return _join("!snmpdiagnose", _device(t), *_list(a, "oids", _OID_RE, 0, 5))


def _b_snmpget(a: dict, t: Target) -> str:
    return _join("!snmpget", _device(t), *_list(a, "oids", _OID_RE, 1, 10))


def _b_cim(a: dict, t: Target) -> str:
    cls = _opt(a, "class", pattern=_CLASS_RE) or _required(a, "class")
    return _join("!cim", f"h={_device(t)}", f"c={cls}")


def _b_sslcerts(a: dict, t: Target) -> str:
    port = _int(a, "port", 1, 65535)
    if port is None:
        raise ToolRejectionError("'port' is required")
    return _join("!sslcerts", _device(t), port)


# name -> (group, needs a device, builder, argument keys it takes, what it answers)
COMMANDS: dict[str, tuple[str, bool, Callable[[dict, Target], str], frozenset[str], str]] = {
    "uptime": ("collector", False, _fixed("!uptime"), frozenset(),
               "Is the debug channel alive? A reply at all is the finding"),
    "health_check": ("collector", False, _b_health, frozenset(),
                     "Stored health check, parsed: per-method all-NaN rates, checkpoints"),
    "perf": ("collector", False, _b_perf, frozenset({"type", "dsFilterColumn", "ds", "h"}),
             "Lost work by method or module"),
    "getconfig": ("collector", False, _b_getconfig, frozenset({"key"}),
                  "A collection method's thread pool or timeout from agent.conf"),
    "reportercache": ("collector", False, _fixed("!reportercache"), frozenset(),
                      "Delivery to the platform: the reporter's buffer"),
    "checkserverconnectivity": ("collector", False, _b_portal, frozenset(),
                                "DNS, ping, TCP and HTTP from the collector to this portal"),
    "avslist": ("collector", False, _fixed("!avslist"), frozenset(),
                "Anti-virus on the collector host"),
    "firewallstatus": ("collector", False, _fixed("!firewallstatus"), frozenset(),
                       "Collector host firewall"),
    "ipaddress": ("collector", False, _fixed("!ipaddress"), frozenset(),
                  "Collector host addresses"),
    "tasklist": ("collector", False, _fixed("!tasklist"), frozenset(),
                 "Processes on the collector host"),
    "logsurf": ("collector", False, _b_logsurf, frozenset({"level", "n", "files"}),
                "Collector logs: wrapper.log, sbproxy.log, watchdog.log"),
    "adlist": ("tasks", False, _fixed("!adlist"), frozenset(), "Active discovery tasks"),
    "aplist": ("tasks", False, _b_aplist, frozenset({"h", "status"}),
               "Auto-properties tasks, failed by default"),
    "splist": ("tasks", False, _b_splist, frozenset({"hostname"}),
               "PropertySource tasks; the only way to see which one is blocked"),
    "tplist": ("tasks", False, _b_tplist, frozenset({"h", "status"}), "TopologySource tasks"),
    "nsplist": ("tasks", False, _fixed("!nsplist"), frozenset(), "NetScan tasks"),
    "dxlist": ("tasks", False, _fixed("!dxlist"), frozenset(), "DiagnosticSource tasks"),
    "tlist": ("tasks", False, _b_tlist, frozenset({"h", "c"}),
              "Collection tasks, filtered by h (host) or c (method)"),
    "ping": ("device", True, _b_ping, frozenset({"type", "count"}),
             "Can the collector reach the device now?"),
    "nslookup": ("device", True, _b_nslookup, frozenset(), "Name resolution from the collector"),
    "macaddress": ("device", True, _b_mac, frozenset(), "MAC address of the device"),
    "snmpdiagnose": ("device", True, _b_snmpdiagnose, frozenset({"oids"}),
                     "SNMP ladder with the device's registered credentials"),
    "snmpget": ("device", True, _b_snmpget, frozenset({"oids"}),
                "SNMP GET with the registered credentials"),
    "snmpwalk": ("device", True, _b_snmpwalk, frozenset({"oid", "timeout"}),
                 "Walk one subtree (default system), never the root or a top-level tree"),
    "wmi": ("device", True, _b_wmi, frozenset({"query", "authType"}),
            "One WQL SELECT with stored credentials or the collector account"),
    "winrm": ("device", True, _b_winrm, frozenset({"auth", "useSSL", "certCheck", "timeout"}),
              "WinRM with stored credentials, default Win32_Service"),
    "cim": ("device", True, _b_cim, frozenset({"class"}),
            "WBEM/CIM on 5989 for storage and appliances"),
    "http": ("device", True, _b_http, frozenset({"url", "timeout"}),
             "HTTP(S) GET to the device itself; the URL must name the device's host"),
    "sslcerts": ("device", True, _b_sslcerts, frozenset({"port"}),
                 "TLS certificate chain; the port is required"),
}  # fmt: skip


def command_keys(command: str) -> list[str]:
    """The argument keys a command takes, sorted, for documentation and errors."""
    return sorted(COMMANDS[command][3])


def check_args(command: str, args: dict) -> None:
    """Refuse a host argument and any key the command does not take, before any call."""
    if command not in COMMANDS:
        raise ToolRejectionError(f"unknown or disallowed command '{command}'")
    keys = COMMANDS[command][3]
    if any(not isinstance(k, str) for k in args):
        raise ToolRejectionError("argument names must be strings")
    if "host" in args:
        raise ToolRejectionError(
            "'host' is not accepted: device probes take the host from device_id, and "
            "checkserverconnectivity targets the configured portal"
        )
    unknown = sorted(set(args) - keys)
    if unknown:
        takes = ", ".join(sorted(keys)) or "no arguments"
        raise ToolRejectionError(f"{command} takes {takes}; not {', '.join(unknown)}")


def build_cmdline(command: str, args: dict, target: Target) -> str:
    """Compose the command line for a named command, or raise ToolRejectionError."""
    args = args or {}
    check_args(command, args)
    try:
        cmdline = COMMANDS[command][2](args, target)
    except (TypeError, ValueError) as e:
        if isinstance(e, ToolRejectionError):
            raise
        raise ToolRejectionError(f"an argument has a value of the wrong type ({e})") from e
    check_cmdline(cmdline)
    return cmdline


# The command heads the builders produce, and the exact forms of the two that take a key.
ALLOWED_HEADS = frozenset({
    "uptime", "shealthcheck", "perf", "getconfig", "reportercache", "checkserverconnectivity",
    "avslist", "firewallstatus", "ipaddress", "tasklist", "logsurf", "adlist", "aplist", "splist",
    "tplist", "nsplist", "dxlist", "tlist", "ping", "nslookup", "macaddress", "snmpdiagnose",
    "snmpget", "snmpwalk", "wmi", "winrm", "cim", "http", "sslcerts",
})  # fmt: skip
_FIXED_FORMS = {
    "shealthcheck": re.compile(r"^!shealthcheck func=detail collector=[0-9]{1,12}$"),
    "getconfig": re.compile(r"^!getconfig collector\.[a-z][a-z0-9]*\.(threadpool|timeout)$"),
}


def check_cmdline(cmdline: str) -> None:
    """Final guard on any command line, however it was built: an allowlisted head, the exact
    health-check and getconfig forms, printable ASCII, a length cap and no credential. Target
    checks (the device's host, the portal) happen when the builders compose the line."""
    head = re.match(r"^!([A-Za-z0-9_]+)", cmdline or "")
    if not head:
        raise CommandLineRejectionError("not a debug command")
    name = head.group(1).lower()
    if name in BLOCKED:
        raise CommandLineRejectionError(
            f"!{head.group(1)} changes the collector, its host or a target"
        )
    if head.group(1) not in ALLOWED_HEADS:
        raise CommandLineRejectionError(f"!{head.group(1)} is not a command this tool sends")
    form = _FIXED_FORMS.get(name)
    if form and not form.match(cmdline):
        raise CommandLineRejectionError(f"!{name} is sent only in its fixed form")
    if not all(" " <= ch <= "~" for ch in cmdline):  # also refuses a second line
        raise CommandLineRejectionError("a command line takes printable ASCII characters only")
    if len(cmdline) > MAX_CMDLINE:
        raise CommandLineRejectionError(f"the command line is longer than {MAX_CMDLINE} characters")
    if CREDENTIAL_RE.search(cmdline):
        raise CommandLineRejectionError(
            "credentials are never sent; probes use the device's stored properties"
        )


# ---------------------------------------------------------------- transport


def is_session_word(text: str) -> bool:
    t = (text or "").strip()
    return t.lower() in SESSION_WORDS


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
    if "Authentication" in name:
        return "error", "the portal rejected this server's API credentials"
    if "Permission" in name:
        return "refused", "the calling identity lacks the collector Debug permission"
    if "unknown debug command" in text or "invalid debug command" in text:
        return "unsupported", "this collector build does not support the command"
    return "error", f"{name}"


_T = TypeVar("_T")


class _BudgetSpentError(Exception):
    """The time budget ran out before or during a call to the portal."""


async def _within(deadline: float, call: Awaitable[_T]) -> _T:
    """Await one portal call, cut off at the deadline."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        if asyncio.iscoroutine(call):
            call.close()
        raise _BudgetSpentError
    try:
        async with asyncio.timeout(remaining):
            return await call
    except TimeoutError as e:
        raise _BudgetSpentError from e


async def run_debug(
    client: Any,
    collector_id: int,
    cmdline: str,
    deadline: float,
    counter: list | None = None,
    parse: Callable[[str], Any] | None = None,
    keep: int = OUTPUT_MAX,
) -> dict:
    """Send one checked command and poll for its output until the deadline. Never raises.

    The POST and every poll are cut off at the deadline, so a slow portal cannot hold the
    call past its budget. The output is masked to a margin past keep characters (at most
    OUTPUT_MAX) and cut to keep, with output_chars giving the length the collector sent and
    truncated saying whether any of it is not shown. A parse function, when
    given, reads the raw output (cut at OUTPUT_MAX), which masking could break, and its
    result is masked value by value.
    """
    portal = _portal_host(client) or ""
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
    if time.monotonic() >= deadline:
        return done(
            status="error",
            detail="the time budget ran out before the command was sent; nothing was sent",
        )
    try:
        _POSTS.append(time.monotonic())
        if counter is not None:
            counter[0] += 1
        try:
            sub = await _within(
                deadline,
                client.request(
                    "POST",
                    "/debug",
                    params={"collectorId": collector_id},
                    json_body={"cmdline": cmdline},
                ),
            )
        except _BudgetSpentError:
            return done(
                status="no_reply",
                detail=(
                    "the portal did not accept the command inside the time budget; "
                    "the collector may still run it"
                ),
            )
        session_id = (sub or {}).get("sessionId") or (sub or {}).get("id")
        if not session_id:
            return done(status="error", detail="the debug API returned no session id")
        forms = [("with", {"collectorId": collector_id}), ("without", None)]
        if _READ_FORMS.get(portal) == "without":
            forms.reverse()
        last_status = None
        while time.monotonic() + POLL_SECONDS < deadline:
            await asyncio.sleep(POLL_SECONDS)
            for form, params in forms:
                if not _rate_ok(_GETS, GET_LIMIT):
                    # The command was sent, so this is no answer yet, not a refusal.
                    return done(
                        status="no_reply",
                        detail=(
                            "this server's own GET budget is spent; the command was sent and "
                            "the collector may still run it"
                        ),
                    )
                _GETS.append(time.monotonic())
                if counter is not None:
                    counter[0] += 1
                try:
                    reply = await _within(
                        deadline, client.get(f"/debug/{session_id}", params=params)
                    )
                except _BudgetSpentError:
                    break
                except Exception as e:
                    # A command still running on the collector (ping, a slow walk) can
                    # come back as an API error whose text says the agent is still
                    # working. That is a pending session, not a failure: keep polling.
                    if not is_pending_error(e):
                        raise
                    last_status = redact(_error_text(e)[:200])
                    continue
                output = str((reply or {}).get("output") or "")
                if output and not is_session_word(output):
                    _READ_FORMS[portal] = form
                    if parse is not None:
                        # The parse reads the raw reply, which masking could break, cut like
                        # the output; a reply it cannot read leaves the answer standing.
                        try:
                            result["parsed"] = redact_values(parse(output[:OUTPUT_MAX]))
                        except Exception as e:
                            result["parse_error"] = type(e).__name__
                        if len(output) > OUTPUT_MAX:
                            result["parse_partial"] = True
                    # Cut before masking, as the output is the device's and only what is
                    # returned needs the work, but mask a margin past the cut, so a secret
                    # the cut splits is still read whole; then cut the masked text.
                    shown = min(keep, OUTPUT_MAX)
                    masked = redact(output[: shown + _MASK_MARGIN])
                    return done(
                        status="answered",
                        read_form=form,
                        output=masked[:shown],
                        output_chars=len(output),
                        truncated=len(output) > shown or len(masked) > shown,
                    )
                if output:
                    last_status = output.strip()
        detail = "no answer inside the time budget"
        if last_status:
            detail += f"; last session status '{last_status}'"
        return done(status="no_reply", detail=detail)
    except Exception as e:
        status, detail = _classify_error(e)
        return done(status=status, detail=detail, error_body=redact(_error_text(e)[:4000]))


# ---------------------------------------------------------------- health check parsing
# The reply is the collector's, so the parse is held to the same rules as the masking: each
# pattern is bounded or starts where a run starts, nothing is recursed into without a guard,
# and every list and string in the result is capped.

_BLOCK_RE = re.compile(r"^=+\$?([^=\n]+?)=+[ \t]*$", re.MULTILINE)
_SCHED_RE = re.compile(
    r"is scheduled at ([^,\n]{0,80}), finished at ([^,\n]{0,80}), status (-?[0-9]{1,6})"
)
# The collector's own words when it rejects a command line, at the start of a line, so a
# device's "cpu usage: 12%" or an "Invalid URL" page title is not read as one.
_USAGE_RE = re.compile(
    r"^[ \t]*(?:invalid input argument|invalid debug command|usage[ \t]*:|invalid host\."
    r"|invalid url)",
    re.MULTILINE,
)
_NAN_RE = re.compile(r"(?<![0-9])([0-9]{1,9}) of ([0-9]{1,9}) tasks \(([0-9.]{1,12})%\)")
PARSE_LIST_MAX = 25  # entries kept in each list of the parsed result
_ID_MAX = 10**12  # the largest id or count read as one
PARSE_TEXT_MAX = 500  # characters kept of each checkpoint detail


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
    except (ValueError, RecursionError):
        return []
    return data if isinstance(data, list) else [data]


def _detail_text(detail: Any) -> str | None:
    """A checkpoint detail as capped text; structured details are written out as JSON."""
    if detail is None:
        return None
    if isinstance(detail, str):
        text = detail
    else:
        try:
            text = json.dumps(detail, default=str)
        except (ValueError, TypeError, RecursionError):
            text = type(detail).__name__
    return text[:PARSE_TEXT_MAX]


def _count(value: Any) -> int | None:
    """A non-negative whole number from an int or an ASCII digit string, else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 0 <= value <= _ID_MAX else None
    if isinstance(value, str):
        text = value.strip()
        if text.isascii() and text.isdigit() and len(text) <= 12:
            return int(text) if int(text) <= _ID_MAX else None
    return None


def parse_health_check(output: str) -> dict:
    """Summarise a !shealthcheck func=detail reply. Unparsed parts are left out, never guessed."""
    text = output or ""
    marks = list(_BLOCK_RE.finditer(text))
    blocks = []
    for i, m in enumerate(marks):
        body = text[m.end() : marks[i + 1].start() if i + 1 < len(marks) else len(text)]
        blocks.append((m.group(1).strip()[:200], body))

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
            cp_name = str(cp.get("name", ""))[:200]
            detail = cp.get("detail")
            status = str(cp.get("status", ""))[:40]
            if status and status.upper() != "OK":
                not_ok.append({"check": cp_name, "status": status, "detail": _detail_text(detail)})
            if cp_name.startswith("biz.DataSource."):
                method = cp_name.split(".", 2)[2]
                match = _NAN_RE.search(detail) if isinstance(detail, str) else None
                if match:
                    try:
                        pct = float(match.group(3))
                    except ValueError:
                        pct = None
                    if pct is not None:
                        methods.append(
                            {
                                "method": method,
                                "all_nan": int(match.group(1)),
                                "attempts": int(match.group(2)),
                                "all_nan_pct": pct,
                                "checkpoint_status": status,
                            }
                        )
                elif isinstance(detail, str) and "no tasks" in detail.lower():
                    idle.append(method)
            elif cp_name == "cogs.DSTableByNan" and isinstance(detail, list):
                rows = [
                    r for r in detail if isinstance(r, dict) and (_count(r.get("nanDsi")) or 0) > 0
                ]
                rows.sort(key=lambda r: -(_count(r.get("nanDsi")) or 0))
                nan_modules = [
                    {
                        "module": _detail_text(r.get("dsName")),
                        "method": _detail_text(r.get("collectorName")),
                        "nan_instances": _count(r.get("nanDsi")),
                        "timeout_instances": _count(r.get("timeoutDsi")),
                        "dropped_instances": _count(r.get("droppedDsi")),
                    }
                    for r in rows[:10]
                ]
            elif cp_name in (
                "basic.Version",
                "basic.Role",
                "biz.InstanceCount",
                "biz.ReportingData",
                "module.Collector",
                "module.Watchdog",
            ):
                facts[cp_name] = _detail_text(detail)

    methods.sort(key=lambda m: -m["all_nan_pct"])
    return {
        "checks_parsed": len(blocks),
        "last_run_started": scheduled[0] if scheduled else None,
        "methods_by_all_nan_rate": methods[:PARSE_LIST_MAX],
        "idle_methods": idle[:PARSE_LIST_MAX],
        "not_ok": not_ok[:PARSE_LIST_MAX],
        "not_ok_total": len(not_ok),
        "nan_by_module": nan_modules,
        "facts": facts,
        "reading_note": (
            "Rates lead, checkpoint status does not: a method can show OK with a double-digit "
            "share of its tasks returning NaN for every datapoint."
        ),
    }


# ---------------------------------------------------------------- the tool


def _portal_host(client: Any) -> str | None:
    """The host this client is configured for, from its base URL."""
    try:
        return urlsplit(str(getattr(client, "base_url", "") or "")).hostname
    except ValueError:
        return None


# Statuses that mean the command did not run as asked. They are returned as errors, so the
# write audit and the client's isError see a failure; answered and no_reply are results.
FAILED_STATUSES = frozenset({"refused", "disabled", "unsupported", "rate_limited", "error"})


_PLACEHOLDER_HOST = "device.invalid"


def _precheck(command: str, args: dict, collector_id: Any, portal_host: str | None) -> None:
    """Build the command once against a placeholder device, so every argument value is
    checked before any call. The http URL's own host stands in for the device here; the
    real build after the device read compares it with the record."""
    host = _PLACEHOLDER_HOST
    if command == "http":
        with contextlib.suppress(ValueError):
            host = urlsplit(str(args.get("url") or "")).hostname or _PLACEHOLDER_HOST
    build_cmdline(command, args, Target(collector_id=0, host=host, portal_host=portal_host))


def _failed(response: dict) -> list[TextContent]:
    """A command that did not run as asked: an error in the "Error: ..." form callers read,
    with the structured body on a Details line."""
    text = f"Error: {response['command']}: {response['status']}: {response.get('detail', '')}"
    if response.get("error_body"):
        text += f" ({' '.join(str(response['error_body'])[:200].split())})"
    text += f"\nDetails: {json.dumps(response, default=str)}"
    return [ErrorContent(type="text", text=text)]


def _rejected(command: str, detail: str, suggestion: str | None = None) -> list[TextContent]:
    """A request refused before anything was sent: an input-validation error."""
    return validation_error("REJECTED_BY_TOOL", f"{command}: {detail}", suggestion)


def _suggest(command: str, error: ToolRejectionError) -> str | None:
    """The command's argument keys, when the refusal is about an argument."""
    return None if isinstance(error, CommandLineRejectionError) else _takes(command)


def _takes(command: str) -> str:
    keys = command_keys(command)
    return f"{command} takes {', '.join(keys)}" if keys else f"{command} takes no arguments"


@require_write_permission
async def collector_debug(
    client: LogicMonitorClient,
    command: str,
    collector_id: int | None = None,
    device_id: int | None = None,
    args: dict | None = None,
    budget_seconds: float = BUDGET_DEFAULT,
    max_output_chars: int = OUTPUT_DEFAULT,
) -> list[TextContent]:
    """Run one allowlisted collector debug command. See the module docstring.

    Write-gated: the command runs on the collector. Device probes need device_id and take
    their host from the device record; the record also supplies the collector when
    collector_id is not given.
    """
    try:
        started = time.monotonic()
        # Everything the caller passed is checked before any call is made.
        numbers = (budget_seconds, max_output_chars)
        if any(isinstance(n, bool) or not isinstance(n, (int, float)) for n in numbers):
            budget_value = cap_value = math.nan
        else:
            try:
                budget_value, cap_value = float(budget_seconds), float(max_output_chars)
            except OverflowError:
                budget_value = cap_value = math.nan
        if not (math.isfinite(budget_value) and math.isfinite(cap_value)):
            return _rejected(command, "budget_seconds and max_output_chars must be finite numbers")
        for name, value in (("collector_id", collector_id), ("device_id", device_id)):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= _ID_MAX
            ):
                return _rejected(command, f"'{name}' must be a positive whole number")
        budget = min(max(budget_value, 2.0), BUDGET_MAX)
        cap = int(max(cap_value, 500))  # run_debug holds the output to OUTPUT_MAX
        deadline = started + budget
        if args is not None and not isinstance(args, dict):
            return _rejected(command, "'args' must be an object of the command's arguments")
        args = dict(args or {})
        calls = [0]
        if not isinstance(command, str) or command not in COMMANDS:
            return _rejected(
                command,
                f"unknown or disallowed command '{command}'",
                f"Commands: {', '.join(sorted(COMMANDS))}",
            )
        group, needs_device, _builder, _keys, _desc = COMMANDS[command]
        try:
            _precheck(command, args, collector_id, _portal_host(client))
        except ToolRejectionError as e:
            return _rejected(command, str(e), _suggest(command, e))
        if needs_device and device_id is None:
            return _rejected(
                command, f"{command} needs device_id: the target is the device record's host"
            )

        # The device record, not the caller, names the host a probe points at and the
        # collector it runs on: a private address means something else in another network.
        host = None
        device_note = None
        if device_id is not None:
            calls[0] += 1
            try:
                dev = await _within(
                    deadline,
                    client.get(
                        f"/device/devices/{int(device_id)}",
                        params={"fields": "id,name,displayName,currentCollectorId"},
                    ),
                )
            except _BudgetSpentError:
                # Nothing was sent, so this is a failure, not a no_reply.
                return _failed(
                    {
                        "command": command,
                        "status": "error",
                        "detail": (
                            "the device record did not arrive inside the time budget; "
                            "nothing was sent"
                        ),
                        "budget_seconds": budget,
                        "api_calls": calls[0],
                        "elapsed_ms": int((time.monotonic() - started) * 1000),
                    }
                )
            if not isinstance(dev, dict):
                return _rejected(command, "the device record could not be read")
            host = str(dev.get("name") or "").strip() or None
            served_by = _count(dev.get("currentCollectorId")) or None
            if needs_device:
                if not host or not _HOST_RE.match(host):
                    return _rejected(
                        command,
                        "the device record's host is not a plain hostname or IP address",
                    )
                if not served_by:
                    return _rejected(
                        command,
                        "the device record names no collector to run the probe on",
                    )
            if served_by and collector_id is not None and collector_id != served_by:
                # The same rule for every command given a device: it runs where the device is.
                return _rejected(
                    command,
                    f"this runs on the collector that serves the device ({served_by}), "
                    f"not collector {collector_id}",
                )
            if collector_id is None:
                collector_id = served_by
            device_note = {"device_id": dev.get("id"), "host_used": host if needs_device else None}
        if not collector_id:
            return _rejected(command, "collector_id (or device_id) is required")

        target = Target(
            collector_id=int(collector_id),
            host=host if needs_device else None,
            portal_host=_portal_host(client),
        )
        try:
            cmdline = build_cmdline(command, args, target)
        except ToolRejectionError as e:
            return _rejected(command, str(e), _suggest(command, e))

        parse = parse_health_check if command == "health_check" else None
        shown = min(cap, 4000) if command == "health_check" else cap
        result = await run_debug(
            client, target.collector_id, cmdline, deadline, calls, parse, keep=shown
        )
        if result.get("status") == "rejected_by_tool":
            return _rejected(command, str(result.get("detail", "")))
        output = result.pop("output", "")
        total_chars = result.pop("output_chars", len(output))
        parsed = result.pop("parsed", None)
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
            # run_debug cut the masked output to shown and set truncated.
            response["output_chars"] = total_chars
            if parsed is not None:
                response["parsed"] = parsed
            response["output"] = output
            head = output[:300].lower()
            if "configuration key [" in head and "not found" in head:
                response["note"] = (
                    "The collector has no such agent.conf key. Check the method name in the "
                    "key, e.g. collector.wmi.threadpool. This is about the command, not the "
                    "collector."
                )
            elif _USAGE_RE.search(head):
                response["note"] = (
                    "The collector rejected the command syntax and printed its usage. This is "
                    "about the command, not the device."
                )
        response["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        if response.get("status") in FAILED_STATUSES:
            return _failed(response)
        return format_response(response)
    except Exception as e:
        return handle_error(e)
