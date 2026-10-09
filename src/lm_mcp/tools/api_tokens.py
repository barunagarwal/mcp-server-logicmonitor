# Description: API token tools for LogicMonitor MCP server.
# Description: Provides API token query functions.

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp.types import TextContent

from lm_mcp.exceptions import NotFoundError
from lm_mcp.tools import format_response, handle_error

if TYPE_CHECKING:
    from lm_mcp.client import LogicMonitorClient


def _token(item: dict, role_ids: bool = False) -> dict:
    """One API token as the tools return it; role_ids keeps each role's id with its name."""
    roles = item.get("roles") or []
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
            [{"id": r.get("id"), "name": r.get("name")} for r in roles]
            if role_ids
            else [r.get("name") for r in roles]
        ),
    }


async def get_api_tokens(
    client: LogicMonitorClient,
    admin_id: int | None = None,
    limit: int = 50,
) -> list[TextContent]:
    """List API tokens for one user/admin, or across the portal when admin_id is omitted.

    Args:
        client: LogicMonitor API client.
        admin_id: Admin/user ID to list tokens for. Omit to list every token in the portal.
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

        tokens = [_token(item) for item in result.get("items") or []]

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
        admin_id: Owning admin/user ID. Omit to look the token up across the portal.

    Returns:
        List of TextContent with API token details or error.
    """
    try:
        if admin_id is not None:
            result = await client.get(f"/setting/admins/{admin_id}/apitokens/{token_id}")
        else:
            listing = await client.get(
                "/setting/admins/apitokens", params={"filter": f"id:{token_id}", "size": 1}
            )
            items = listing.get("items") or []
            # A filter the API does not apply returns other tokens, so the id must match.
            if not items or items[0].get("id") != token_id:
                raise NotFoundError(f"API token {token_id} not found")
            result = items[0]

        return format_response(_token(result, role_ids=True))
    except Exception as e:
        return handle_error(e)
