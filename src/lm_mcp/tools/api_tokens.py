# Description: API token tools for LogicMonitor MCP server.
# Description: Provides API token query functions.

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp.types import TextContent

from lm_mcp.exceptions import NotFoundError
from lm_mcp.tools import format_response, handle_error

if TYPE_CHECKING:
    from lm_mcp.client import LogicMonitorClient


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

        tokens = []
        for item in result.get("items", []):
            tokens.append(
                {
                    "id": item.get("id"),
                    "admin_id": item.get("adminId"),
                    "admin_name": item.get("adminName"),
                    "note": item.get("note"),
                    "status": item.get("status"),
                    "created_on": item.get("createdOn"),
                    "last_used_on": item.get("lastUsedOn"),
                    "roles": [r.get("name") for r in item.get("roles", [])],
                }
            )

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
            if not items:
                raise NotFoundError(f"API token {token_id} not found")
            result = items[0]

        token = {
            "id": result.get("id"),
            "admin_id": result.get("adminId"),
            "admin_name": result.get("adminName"),
            "note": result.get("note"),
            "status": result.get("status"),
            "created_on": result.get("createdOn"),
            "last_used_on": result.get("lastUsedOn"),
            "roles": [{"id": r.get("id"), "name": r.get("name")} for r in result.get("roles", [])],
        }

        return format_response(token)
    except Exception as e:
        return handle_error(e)
