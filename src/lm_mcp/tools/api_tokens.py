# Description: API token tools for LogicMonitor MCP server.
# Description: Provides API token query functions.

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp.types import TextContent

from lm_mcp.tools import format_response, handle_error

if TYPE_CHECKING:
    from lm_mcp.client import LogicMonitorClient


def _token(item: dict, role_ids: bool = False) -> dict:
    return {
        "id": item.get("id"),
        "access_id": item.get("accessId"),
        "admin_id": item.get("adminId"),
        "admin_name": item.get("adminName"),
        "type": item.get("type"),
        "note": item.get("note"),
        "status": item.get("status"),
        "created_on": item.get("createdOn"),
        "last_used_on": item.get("lastUsedOn"),
        "roles": (
            [{"id": r.get("id"), "name": r.get("name")} for r in item.get("roles", []) or []]
            if role_ids
            else [r.get("name") for r in item.get("roles", []) or []]
        ),
    }


async def get_api_tokens(
    client: LogicMonitorClient,
    admin_id: int | None = None,
    limit: int = 50,
) -> list[TextContent]:
    """List API tokens — for one user, or across every user when admin_id is omitted.

    Args:
        client: LogicMonitor API client.
        admin_id: Admin/user ID to list tokens for. Omit to list all tokens in the portal.
        limit: Maximum number of tokens to return.

    Returns:
        List of TextContent with API token data or error.
    """
    try:
        params: dict = {"size": limit}
        path = (
            f"/setting/admins/{admin_id}/apitokens"
            if admin_id is not None
            else "/setting/admins/apitokens"
        )
        result = await client.get(path, params=params)
        tokens = [_token(item) for item in result.get("items", []) or []]

        return format_response(
            {
                "total": result.get("total", 0),
                "count": len(tokens),
                "api_tokens": tokens,
            }
        )
    except Exception as e:
        return handle_error(e)


async def get_api_token(
    client: LogicMonitorClient,
    token_id: int,
    admin_id: int | None = None,
) -> list[TextContent]:
    """Get detailed information about a specific API token.

    Args:
        client: LogicMonitor API client.
        token_id: API token ID.
        admin_id: Owning admin/user ID. Optional — when omitted the token is looked up
            across all users.

    Returns:
        List of TextContent with API token details or error.
    """
    try:
        if admin_id is not None:
            result = await client.get(f"/setting/admins/{admin_id}/apitokens/{token_id}")
        else:
            listing = await client.get(
                "/setting/admins/apitokens", params={"filter": f"id:{int(token_id)}", "size": 1}
            )
            result = (listing.get("items") or [None])[0]
            if not result:
                return format_response(
                    {
                        "error": True,
                        "code": "NOT_FOUND",
                        "message": f"API token {token_id} not found",
                    }
                )
        return format_response(_token(result, role_ids=True))
    except Exception as e:
        return handle_error(e)
