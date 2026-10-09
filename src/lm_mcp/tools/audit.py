# Description: Audit log tools for LogicMonitor MCP server.
# Description: Provides access to system audit logs and activity tracking.

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from mcp.types import TextContent

from lm_mcp.exceptions import NotFoundError
from lm_mcp.tools import (
    INEXACT_TOTAL_NOTE,
    WILDCARD_STRIP_NOTE,
    format_response,
    handle_error,
    paginated_response,
    quote_filter_value,
    sanitize_filter_value,
    validation_error,
)

if TYPE_CHECKING:
    from lm_mcp.client import LogicMonitorClient

# How /setting/accesslogs filters actually behave, verified against live portals:
#   - happenedOn is the epoch-seconds timestamp; happenedOn>:a,happenedOn<:b is honoured as a
#     range. happenedOnLocal is a display string: a filter on it is silently ignored.
#   - username:"a"|"b" is an exact-match OR list. Negation is NOT supported: username!~ returns
#     nothing and username!: behaves like username:, both with HTTP 200. username~ (contains)
#     returns nothing, and a second username clause is ignored.
#   - description~"text" is a contains match. It does not take an OR list.
#   - A filter longer than roughly 1,000 characters returns HTTP 500.
#   - offset + size above 10,000 returns HTTP 413 ("the query limitation of auditLog is 10000").
#   - total is negative when more rows exist (-N reads "at least N"). Rows come newest first.
#   - sessionId is null in practice.
ACCESSLOGS = "/setting/accesslogs"
OFFSET_CEILING = 10000
FILTER_CHAR_LIMIT = 900

# System and automation actors. They are most of the feed on busy portals (Active Discovery,
# dynamic group membership, AppliesTo, NetScan, cloud auto-delete, ...). The API cannot exclude
# them server-side, so exclude_system drops them after the fetch. The match is case-sensitive
# and a System actor name holds no "@" or space, so a real user such as
# system.admin@example.com or System.Admin@example.com is not mistaken for one.
SYSTEM_ACTOR = re.compile(
    r"^(System(?::{1,2}|\.)[^@\s]+|LogicMonitor Internal|auto-user-suspend"
    r"|(AZURE|AWS|GCP) auto-delete)$"
)

LOGIN_PATTERNS = [
    ("signs in via", "success"),
    ("log in. 2FA Mode", "success"),
    ("logged in through lmsupport", "success"),
    ("could not log into the system", "failed"),
    ("Session timed out for SSO", "failed"),
    ("signs out", "logout"),
]

_KV_ACTION = re.compile(r'"Action=([A-Za-z]+)', re.IGNORECASE)
_LEADING_VERB = re.compile(
    r"^\s*(?:\{[^}]*\}\s*)?(add(?:ed)?|creat(?:e|ed)|clon(?:e|ed)|updat(?:e|ed)|edit(?:ed)?|"
    r"chang(?:e|ed)|modif(?:y|ied)|renam(?:e|ed)|delet(?:e|ed)|remov(?:e|ed)|import(?:ed)?|"
    r"enabl(?:e|ed)|disabl(?:e|ed))\b",
    re.IGNORECASE,
)
_NOT_A_CHANGE = re.compile(
    r"signs in via|log in\. 2FA|logged in through|could not log into|signs out|"
    r"^Note \(|API request:|Session timed out|2FA Request",
    re.IGNORECASE,
)
_TOKEN_IN_DESC = re.compile(r"API token\s+([A-Za-z0-9_\-#*]{4,})", re.IGNORECASE)
_API_PATH = re.compile(r"path\s+'([^']*)'(?:\s+with Method:\s*([A-Z]+))?", re.IGNORECASE)
_SIMILAR = re.compile(r"Similar case has occurred (\d+) times", re.IGNORECASE)


class AuditQueryLimitError(Exception):
    """A request _query refuses before sending: past the offset or filter-length ceiling."""


def _time_clauses(start_time: int | None, end_time: int | None) -> list[str]:
    filters = []
    if start_time:
        filters.append(f"happenedOn>:{int(start_time)}")
    if end_time:
        filters.append(f"happenedOn<:{int(end_time)}")
    return filters


def _username_clause(username: str) -> tuple[str, bool]:
    """Build username:"a"|"b" from one name or a comma-separated list (exact match)."""
    names, stripped = [], False
    for part in username.split(","):
        clean, modified = sanitize_filter_value(part.strip())
        stripped = stripped or modified
        if clean:
            names.append(quote_filter_value(clean))
    return ("username:" + "|".join(names) if names else ""), stripped


def _row(item: dict) -> dict:
    return {
        "id": item.get("id"),
        "username": item.get("username"),
        "ip_address": item.get("ip"),
        "happened_on": item.get("happenedOn"),
        "timestamp": item.get("happenedOnLocal"),
        "description": item.get("description"),
        "session_id": item.get("sessionId"),
    }


async def _query(
    client: LogicMonitorClient, filters: list[str], size: int, offset: int = 0
) -> tuple[list[dict], dict, str]:
    if offset + size > OFFSET_CEILING:
        raise AuditQueryLimitError(
            f"offset + limit must stay within {OFFSET_CEILING} for audit logs "
            "(LogicMonitor returns HTTP 413 beyond it). Narrow the window with "
            "start_time/end_time and page within it instead."
        )
    flt = ",".join(f for f in filters if f)
    if len(flt) > FILTER_CHAR_LIMIT:
        raise AuditQueryLimitError(
            f"filter is {len(flt)} characters; LogicMonitor returns HTTP 500 above about 1,000. "
            "Pass fewer usernames per call."
        )
    params: dict = {"size": size, "offset": offset}
    if flt:
        params["filter"] = flt
    result = await client.get(ACCESSLOGS, params=params)
    items = result.get("items") or []
    total = result.get("total")
    if isinstance(total, bool) or not isinstance(total, int):
        # Read a missing or non-integer total the way the API writes "more exist": a
        # negative lower bound when the page came back full, the exact count otherwise.
        seen = offset + len(items)
        result = {**result, "total": -(seen + 1) if len(items) >= size else seen}
    return items, result, flt


def _contains(item: dict, text: str) -> bool:
    return text.lower() in str(item.get("description") or "").lower()


async def get_audit_logs(
    client: LogicMonitorClient,
    username: str | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    start_time: int | None = None,
    end_time: int | None = None,
    exclude_system: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[TextContent]:
    """Get audit logs from LogicMonitor.

    Args:
        client: LogicMonitor API client.
        username: Exact username, or a comma-separated list of usernames (matched as an OR).
        action: Text the description must contain, e.g. "Action=Delete", "signs in", "SDT".
        resource_type: Text the description must contain, e.g. "dashboard", "Type=Device".
        start_time: Only entries at or after this epoch second (happenedOn).
        end_time: Only entries at or before this epoch second (happenedOn).
        exclude_system: Drop System:* and automation actors after the fetch. Ignored when a
            username filter is sent, so a named system actor can still be queried.
        limit: Maximum number of rows to request (one page).
        offset: Rows to skip; offset + limit must stay within 10,000.

    Returns:
        List of TextContent with audit log data or error.
    """
    try:
        filters, notes, wildcards_stripped = [], [], False
        user_clause = ""
        if username:
            user_clause, stripped = _username_clause(username)
            wildcards_stripped = wildcards_stripped or stripped
            filters.append(user_clause)
        texts = []
        for value in (action, resource_type):
            if value:
                clean, modified = sanitize_filter_value(value)
                wildcards_stripped = wildcards_stripped or modified
                if clean:
                    texts.append(clean)
        # Only one description~ clause is applied server-side; any second one runs here.
        if texts:
            filters.append(f"description~{quote_filter_value(texts[0])}")
        filters.extend(_time_clauses(start_time, end_time))

        items, result, flt = await _query(client, filters, limit, offset)
        fetched = items
        if len(texts) > 1:
            items = [i for i in items if _contains(i, texts[1])]
            notes.append(
                f"'{texts[1]}' was matched after the fetch (one description filter per call)."
            )
        # A named user is queried as asked, system actor or not.
        if exclude_system and not user_clause:
            before = len(items)
            items = [i for i in items if not SYSTEM_ACTOR.match(str(i.get("username") or ""))]
            if before != len(items):
                notes.append(
                    f"{before - len(items)} system/automation rows were dropped from this page; "
                    "the API cannot exclude them server-side, so a page can hold fewer "
                    "than limit rows."
                )

        logs = [_row(i) for i in items]
        # Paging follows the rows the API returned; count is what is left after the
        # filters above, so it can be lower than the page.
        response = {
            **paginated_response(fetched, result, offset),
            "count": len(logs),
            "next_offset": offset + len(fetched),
            "filter": flt or None,
            "audit_logs": logs,
        }
        if wildcards_stripped:
            notes.append(WILDCARD_STRIP_NOTE)
        if notes:
            response["note"] = " ".join(notes)
        return format_response(response)
    except AuditQueryLimitError as e:
        return validation_error("INVALID_REQUEST", str(e))
    except Exception as e:
        return handle_error(e)


async def get_api_token_audit(
    client: LogicMonitorClient,
    token_id: int | None = None,
    access_id: str | None = None,
    start_time: int | None = None,
    end_time: int | None = None,
    limit: int = 50,
) -> list[TextContent]:
    """Get API token usage audit logs: changes made through a token, and rejected calls.

    Args:
        client: LogicMonitor API client.
        token_id: API token ID; resolved to its access ID through /setting/admins/apitokens.
        access_id: API token access ID (takes precedence over token_id).
        start_time: Only entries at or after this epoch second.
        end_time: Only entries at or before this epoch second.
        limit: Maximum number of rows to return.

    Returns:
        List of TextContent with API token audit data or error.
    """
    try:
        wildcards_stripped = False
        if access_id is not None:
            access_id, wildcards_stripped = sanitize_filter_value(access_id)
            if not access_id:
                return validation_error(
                    "INVALID_REQUEST",
                    "access_id is empty once wildcard characters are removed",
                    "Pass the token's full access ID, or use token_id.",
                )
        if not access_id and token_id:
            res = await client.get(
                "/setting/admins/apitokens", params={"filter": f"id:{token_id}", "size": 1}
            )
            found = (res.get("items") or [None])[0]
            # A filter the API does not apply returns other tokens, so the id must match.
            if not found or found.get("id") != token_id or not found.get("accessId"):
                raise NotFoundError(f"API token {token_id} not found")
            access_id = found["accessId"]

        needle = f"API token {access_id}" if access_id else "API token"
        filters = [
            f"description~{quote_filter_value(needle)}",
            *_time_clauses(start_time, end_time),
        ]
        items, result, flt = await _query(client, filters, limit)
        fetched, notes = items, []
        if access_id:
            # description~ is a contains match, so "API token AbCd" also matches the rows of
            # AbCdZZZZ...; keep only rows naming exactly this access ID.
            exact = re.compile(rf"API token {re.escape(access_id)}(?![A-Za-z0-9_\-#*])")
            items = [i for i in items if exact.search(str(i.get("description") or ""))]
            if len(items) != len(fetched):
                notes.append(
                    f"{len(fetched) - len(items)} rows naming a different token that starts "
                    "with this access ID were dropped from this page."
                )

        logs = []
        for item in items:
            desc = str(item.get("description") or "")
            tok = _TOKEN_IN_DESC.search(desc)
            path = _API_PATH.search(desc)
            similar = _SIMILAR.search(desc)
            if desc.lower().startswith("failed api request"):
                kind = "rejected"
            elif desc.lower().startswith("throttled api request"):
                kind = "throttled"
            else:
                kind = "change via token"
            logs.append(
                {
                    **_row(item),
                    "kind": kind,
                    "access_id": tok.group(1) if tok else None,
                    "path": path.group(1) if path else None,
                    "method": (path.group(2) if path else None),
                    "attempts": int(similar.group(1)) if similar else 1,
                }
            )

        # Paging follows the rows the API returned; count is what is left after the
        # exact-token check, so it can be lower than the page.
        page = paginated_response(fetched, result, 0)
        del page["offset"]  # this tool takes no offset; older rows need a narrower window
        response = {
            **page,
            "count": len(logs),
            "filter": flt,
            "api_token_logs": logs,
        }
        if response["has_more"]:
            notes.append("More rows match; narrow start_time/end_time to reach them.")
        if wildcards_stripped:
            notes.append(WILDCARD_STRIP_NOTE)
        if notes:
            response["note"] = " ".join(notes)
        return format_response(response)
    except AuditQueryLimitError as e:
        return validation_error("INVALID_REQUEST", str(e))
    except Exception as e:
        return handle_error(e)


def _login_status(desc: str) -> tuple[str, str | None]:
    low = desc.lower()
    if "could not log into" in low or "session timed out for sso" in low:
        return "failed", ("2FA" if "two factor" in low else "SSO" if "sso" in low else "password")
    if "signs out" in low:
        return "logout", None
    if "logged in through lmsupport" in low:
        return "success", "LM Support"
    m = re.search(r"signs in via\s+(\S+)", desc, re.IGNORECASE)
    if m:
        return "success", m.group(1).rstrip(".").upper()
    m = re.search(r"2FA Mode\s*:\s*(.*)$", desc, re.IGNORECASE)
    if m:
        mode = m.group(1).strip()
        return "success", "Local" + (
            f" + 2FA ({mode})" if mode and mode.lower() not in ("none", "disabled", "off") else ""
        )
    return "unknown", None


async def get_login_audit(
    client: LogicMonitorClient,
    username: str | None = None,
    success_only: bool = False,
    failed_only: bool = False,
    start_time: int | None = None,
    end_time: int | None = None,
    limit: int = 50,
) -> list[TextContent]:
    """Get login/authentication audit logs.

    One description query per known login wording (the API takes no OR on description),
    merged newest first. Active Discovery rows that merely quote "Login failed for user"
    from a monitored database are not portal logins and are not returned.

    Args:
        client: LogicMonitor API client.
        username: Exact username, or a comma-separated list.
        success_only: Only successful logins.
        failed_only: Only failed logins.
        start_time: Only entries at or after this epoch second.
        end_time: Only entries at or before this epoch second.
        limit: Maximum number of logs to return.

    Returns:
        List of TextContent with login audit data or error.
    """
    try:
        if success_only and failed_only:
            return validation_error(
                "INVALID_REQUEST",
                "success_only and failed_only cannot both be set",
                "Set one of them, or neither for every login event.",
            )
        wanted = {"success", "failed", "logout"}
        if success_only:
            wanted = {"success"}
        if failed_only:
            wanted = {"failed"}
        base, wildcards_stripped = [], False
        if username:
            clause, wildcards_stripped = _username_clause(username)
            base.append(clause)
        base.extend(_time_clauses(start_time, end_time))

        seen, merged, page_full = set(), [], False
        for pattern, status in LOGIN_PATTERNS:
            if status not in wanted:
                continue
            items, result, _ = await _query(
                client, [*base, f"description~{quote_filter_value(pattern)}"], limit
            )
            # A full page, or a total past it, means this wording has older rows not read.
            page_full = page_full or len(items) >= limit or abs(result["total"]) > len(items)
            for item in items:
                if item.get("id") in seen:
                    continue
                seen.add(item.get("id"))
                merged.append(item)
        merged.sort(key=lambda i: i.get("happenedOn") or 0, reverse=True)

        logs = []
        for item in merged[:limit]:
            status, method = _login_status(str(item.get("description") or ""))
            logs.append({**_row(item), "status": status, "method": method})

        has_more = page_full or len(merged) > limit
        response: dict[str, Any] = {
            "total": len(logs),
            "count": len(logs),
            "has_more": has_more,
            "login_logs": logs,
        }
        if has_more:
            response["total_note"] = INEXACT_TOTAL_NOTE
        notes = []
        if has_more:
            notes.append(
                f"More login rows exist than the newest {limit} returned; narrow "
                "start_time/end_time or username to reach them."
            )
        if wildcards_stripped:
            notes.append(WILDCARD_STRIP_NOTE)
        if notes:
            response["note"] = " ".join(notes)
        return format_response(response)
    except AuditQueryLimitError as e:
        return validation_error("INVALID_REQUEST", str(e))
    except Exception as e:
        return handle_error(e)


CHANGE_TYPES = ("create", "update", "delete", "import")


def _change_type(desc: str) -> str | None:
    """Classify an audit description as create/update/delete/import, or None if not a change."""
    if _NOT_A_CHANGE.search(desc):
        return None
    m = _KV_ACTION.search(desc) or _LEADING_VERB.search(desc)
    if not m:
        return None
    verb = m.group(1).lower()
    if verb.startswith(("add", "creat", "clon")):
        return "create"
    if verb.startswith(("delet", "remov")):
        return "delete"
    if verb.startswith("import"):
        return "import"
    if verb.startswith(("updat", "edit", "chang", "modif", "renam", "enabl", "disabl")):
        return "update"
    # Export, Login, Fetch, Acknowledge, Schedule, Execute, Test and the like change nothing.
    return None


async def get_change_audit(
    client: LogicMonitorClient,
    resource_type: str | None = None,
    change_type: str | None = None,
    username: str | None = None,
    start_time: int | None = None,
    end_time: int | None = None,
    exclude_system: bool = True,
    limit: int = 50,
) -> list[TextContent]:
    """Get configuration change audit logs (create / update / delete / import).

    The change type is read from the description ("Action=..." or the leading verb); the
    API has no field for it. System actors are excluded by default because Active Discovery
    and dynamic group membership otherwise fill every page.

    Args:
        client: LogicMonitor API client.
        resource_type: Text the description must contain (e.g. "dashboard", "Type=Device").
        change_type: create, update, delete or import.
        username: Exact username, or a comma-separated list.
        start_time: Only entries at or after this epoch second.
        end_time: Only entries at or before this epoch second.
        exclude_system: Drop System:* and automation actors (default True). Ignored when a
            username filter is sent.
        limit: Maximum number of changes to return.

    Returns:
        List of TextContent with change audit data or error.
    """
    try:
        filters, wildcards_stripped = [], False
        user_clause = ""
        if username:
            user_clause, stripped = _username_clause(username)
            wildcards_stripped = wildcards_stripped or stripped
            filters.append(user_clause)
        if resource_type:
            clean, modified = sanitize_filter_value(resource_type)
            wildcards_stripped = wildcards_stripped or modified
            if clean:
                filters.append(f"description~{quote_filter_value(clean)}")
        filters.extend(_time_clauses(start_time, end_time))
        want = None
        if change_type:
            clean, modified = sanitize_filter_value(change_type)
            wildcards_stripped = wildcards_stripped or modified
            want = (clean or "").strip().lower() or None
        if want and want not in CHANGE_TYPES:
            # An unknown type would match nothing and read as "no changes".
            return validation_error(
                "INVALID_REQUEST",
                f"change_type must be one of {', '.join(CHANGE_TYPES)}; got {change_type!r}",
            )

        # A named user is queried as asked, system actor or not.
        drop_system = exclude_system and not user_clause

        # Changes are a small share of the feed, so read a larger pool than requested.
        pool = min(1000, max(limit * 10, 200))
        items, result, flt = await _query(client, filters, pool)

        logs: list[dict[str, Any]] = []
        scanned = 0
        for item in items:
            if len(logs) >= limit:
                break
            scanned += 1
            if drop_system and SYSTEM_ACTOR.match(str(item.get("username") or "")):
                continue
            ct = _change_type(str(item.get("description") or ""))
            if not ct or (want and ct != want):
                continue
            logs.append({**_row(item), "change_type": ct})

        # Rows the API holds past this pool (a negative or larger total) were never read.
        older_rows = abs(result["total"]) > len(items)
        response: dict[str, Any] = {
            "count": len(logs),
            "scanned": scanned,
            "has_more": scanned < len(items) or older_rows,
            "filter": flt or None,
            "change_logs": logs,
        }
        if older_rows and len(logs) < limit:
            response["note"] = (
                f"Only the newest {pool} matching audit rows were scanned. Narrow start_time/"
                "end_time or add resource_type/username to reach older changes."
            )
        if wildcards_stripped:
            response["note"] = (response.get("note", "") + " " + WILDCARD_STRIP_NOTE).strip()
        return format_response(response)
    except AuditQueryLimitError as e:
        return validation_error("INVALID_REQUEST", str(e))
    except Exception as e:
        return handle_error(e)
