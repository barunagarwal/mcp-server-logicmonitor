# Description: Multi-portal registry for the LogicMonitor MCP server.
# Description: Loads per-customer portal credentials from an age-encrypted vault (or a
# plaintext JSON file for testing), builds a LogicMonitor client per customer on demand,
# and tracks the active portal for this process. Lets one server serve many customer
# portals, switched at runtime via the use_portal tool (no per-portal process needed).
from __future__ import annotations

import json
import logging
import subprocess
from typing import Any

logger = logging.getLogger(__name__)

# Process-local state. Under stdio each client (Claude Desktop, Codex) spawns its own
# process, so a single "active" portal per process is safe (one user drives it).
_state: dict[str, Any] = {
    "portals": {},  # name -> record {portal, bearer_token | access_id/access_key, writable}
    "clients": {},  # name -> LogicMonitorClient (lazily built, cached)
    "active": None,  # active portal name
    "active_writable": False,
    "loaded": False,
}


def _require_multi_portal() -> None:
    """Refuse portal-registry access unless multi-portal mode is enabled.

    Guards the single-portal invariant: with LM_MULTI_PORTAL off, the client is
    bound once at startup and no tool call may replace it, even when vault
    environment variables happen to be present.
    """
    from lm_mcp.config import get_config

    if not get_config().multi_portal:
        raise RuntimeError(
            "Multi-portal mode is disabled. Set LM_MULTI_PORTAL=true (and configure "
            "a vault) to use portal tools."
        )


def _load_vault() -> dict[str, dict]:
    """Load the portal map from the age-encrypted vault or a plaintext file.

    The encrypted vault takes precedence: a stale LM_PORTALS_FILE left over from
    testing must not silently serve credentials in place of the production vault.
    """
    from lm_mcp.config import get_config

    cfg = get_config()
    vault_file = getattr(cfg, "vault_file", None)
    age_key = getattr(cfg, "age_key", None)
    if vault_file and age_key:
        if getattr(cfg, "portals_file", None):
            logger.warning(
                "both LM_PORTALS_FILE and the age vault are configured; using the encrypted vault"
            )
        try:
            proc = subprocess.run(
                ["age", "-d", "-i", age_key, vault_file],
                capture_output=True,
                check=True,
                timeout=30,
            )
        except FileNotFoundError as e:
            raise RuntimeError(
                "age binary not found - install age (https://age-encryption.org)"
            ) from e
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or b"").decode(errors="replace").strip()
            raise RuntimeError(f"age decryption failed: {stderr}") from e
        except subprocess.TimeoutExpired as e:
            raise RuntimeError("age decryption timed out after 30s") from e
        return json.loads(proc.stdout)
    if getattr(cfg, "portals_file", None):
        with open(cfg.portals_file) as f:
            return json.load(f)
    raise RuntimeError("Multi-portal mode needs LM_PORTALS_FILE, or LM_VAULT_FILE + LM_AGE_KEY.")


def _normalize_records(portals_map: dict[str, dict]) -> dict[str, dict]:
    """Canonicalize each record's portal host; warn and keep raw on invalid values.

    Warn-and-keep so one typo cannot brick the whole vault: the bad record only
    fails when someone tries to activate it (_build_client validates strictly).
    """
    from lm_mcp.config import normalize_portal_host

    out: dict[str, dict] = {}
    for name, rec in portals_map.items():
        rec = dict(rec or {})
        portal = rec.get("portal")
        if portal:
            try:
                rec["portal"] = normalize_portal_host(str(portal))
            except ValueError:
                logger.warning(
                    "portal record '%s' has an invalid hostname %r; keeping as-is", name, portal
                )
        out[name] = rec
    return out


def _parse_vault() -> dict[str, dict]:
    """Load, validate, and normalize the vault without touching module state."""
    portals_map = _load_vault()
    if not isinstance(portals_map, dict) or not portals_map:
        raise RuntimeError("Portal vault must be a non-empty JSON object of name -> record.")
    return _normalize_records(portals_map)


def load() -> None:
    """Parse the vault once (idempotent) into the in-memory portal map.

    Never discards live clients; refreshing from disk is reload()'s job, which
    closes the clients it replaces.
    """
    _require_multi_portal()
    if _state["loaded"]:
        return
    _state["portals"] = _parse_vault()
    _state["loaded"] = True


def names() -> list[dict]:
    """Return portal metadata (never secrets): name, portal host, auth type, writable."""
    load()
    out = []
    for name, rec in sorted(_state["portals"].items()):
        rec = rec or {}
        auth = "bearer" if rec.get("bearer_token") else ("lmv1" if rec.get("access_id") else "none")
        out.append(
            {
                "name": name,
                "portal": rec.get("portal", ""),
                "auth": auth,
                "writable": bool(rec.get("writable", False)),
                "active": name == _state["active"],
            }
        )
    return out


def _build_client(rec: dict):
    from lm_mcp.auth.bearer import BearerAuth
    from lm_mcp.auth.lmv1 import LMv1Auth
    from lm_mcp.client import LogicMonitorClient
    from lm_mcp.config import get_config, normalize_portal_host

    cfg = get_config()
    portal = rec.get("portal")
    if not portal:
        raise ValueError("portal record is missing the 'portal' hostname")
    portal = normalize_portal_host(str(portal))
    if rec.get("bearer_token"):
        auth = BearerAuth(rec["bearer_token"])
    elif rec.get("access_id") and rec.get("access_key"):
        auth = LMv1Auth(rec["access_id"], rec["access_key"])
    else:
        raise ValueError("portal record needs bearer_token or access_id + access_key")
    return LogicMonitorClient(
        base_url=f"https://{portal}/santaba/rest",
        auth=auth,
        timeout=cfg.timeout,
        api_version=cfg.api_version,
        max_retries=cfg.max_retries,
        retry_after_cap=cfg.retry_after_cap_seconds,
        ingest_url=f"https://{portal}",
    )


def activate(customer: str) -> dict:
    """Make `customer` the active portal for subsequent tool calls."""
    load()
    if customer not in _state["portals"]:
        raise ValueError(
            f"portal '{customer}' not found. Available: {', '.join(sorted(_state['portals']))}"
        )
    rec = _state["portals"][customer] or {}
    client = _state["clients"].get(customer)
    if client is None:
        client = _build_client(rec)
        _state["clients"][customer] = client

    from lm_mcp.server import _set_client

    _set_client(client)
    _state["active"] = customer
    _state["active_writable"] = bool(rec.get("writable", False))
    return {
        "active": customer,
        "portal": rec.get("portal", ""),
        "writable": _state["active_writable"],
    }


async def reload() -> dict:
    """Re-read the vault from disk so added/removed portals take effect without a restart.

    Atomic: the new map is parsed and the surviving active portal's replacement
    client is built before any state is swapped, so a failure at any point leaves
    the old registry, active portal, and installed client fully intact. Replaced
    clients are closed after the swap.
    """
    _require_multi_portal()
    new_portals = _parse_vault()

    prev_active = _state["active"]
    keep_active = prev_active is not None and prev_active in new_portals
    new_client = None
    if keep_active:
        # Build before swapping: a broken record for the active portal aborts
        # the reload without degrading the running server.
        new_client = _build_client(new_portals[prev_active] or {})

    old_clients = list(_state["clients"].values())
    _state["portals"] = new_portals
    _state["clients"] = {}
    _state["loaded"] = True

    from lm_mcp.server import _set_client

    if keep_active:
        _state["clients"][prev_active] = new_client
        _set_client(new_client)
        _state["active"] = prev_active
        _state["active_writable"] = bool((new_portals[prev_active] or {}).get("writable", False))
    else:
        if prev_active:
            _set_client(None)
        _state["active"] = None
        _state["active_writable"] = False

    for client in old_clients:
        try:
            await client.close()
        except Exception:
            logger.debug("error closing a replaced portal client", exc_info=True)

    return {
        "reloaded": True,
        "count": len(_state["portals"]),
        "active": _state["active"],
        "portals": names(),
    }


def active() -> dict:
    """Return the currently active portal (or nulls if none selected yet)."""
    name = _state["active"]
    portal = (_state["portals"].get(name) or {}).get("portal") if name else None
    return {"active": name, "portal": portal, "writable": _state["active_writable"]}


def has_active() -> bool:
    return _state["active"] is not None


def is_active_writable() -> bool:
    return bool(_state["active_writable"])


async def close_all() -> None:
    """Close every cached client (called on shutdown)."""
    for client in _state["clients"].values():
        try:
            await client.close()
        except Exception:
            logger.debug("error closing a portal client", exc_info=True)
    _state["clients"] = {}

    # Never leave the process-global client pointing at a closed instance.
    from lm_mcp.server import _set_client

    _set_client(None)
