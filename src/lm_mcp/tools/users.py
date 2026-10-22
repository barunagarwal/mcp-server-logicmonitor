# Description: User and role management tools for LogicMonitor MCP server.
# Description: Provides user/role query, create, update, and delete functions.

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp.types import TextContent

from lm_mcp.tools import (
    WILDCARD_STRIP_NOTE,
    format_response,
    handle_error,
    paginated_response,
    quote_filter_value,
    require_write_permission,
    sanitize_filter_value,
)

if TYPE_CHECKING:
    from lm_mcp.client import LogicMonitorClient


async def get_users(
    client: LogicMonitorClient,
    name_filter: str | None = None,
    filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[TextContent]:
    """List users from LogicMonitor.

    Args:
        client: LogicMonitor API client.
        name_filter: Filter by username (supports wildcards).
        filter: Raw filter expression for advanced queries (overrides name_filter).
            Supports LogicMonitor filter syntax with operators:
            : (equal), !: (not equal), > < >: <: (comparisons),
            ~ (contains), !~ (not contains).
            Examples: "username~admin,status:active"
        limit: Maximum number of users to return.
        offset: Number of results to skip for pagination.

    Returns:
        List of TextContent with user data or error.
    """
    try:
        params: dict = {"size": limit, "offset": offset}
        wildcards_stripped = False

        # If raw filter is provided, use it directly (power user mode)
        if filter:
            params["filter"] = filter
        elif name_filter:
            clean_name, was_modified = sanitize_filter_value(name_filter)
            wildcards_stripped = wildcards_stripped or was_modified
            params["filter"] = f"username~{quote_filter_value(clean_name)}"

        result = await client.get("/setting/admins", params=params)

        users = []
        for item in result.get("items", []):
            users.append(
                {
                    "id": item.get("id"),
                    "username": item.get("username"),
                    "email": item.get("email"),
                    "first_name": item.get("firstName"),
                    "last_name": item.get("lastName"),
                    "status": item.get("status"),
                    "roles": [r.get("name") for r in item.get("roles", [])],
                    "two_fa_enabled": item.get("twoFAEnabled"),
                    "api_only": item.get("apionly"),
                }
            )

        response = {
            **paginated_response(users, result, offset),
            "users": users,
        }
        if wildcards_stripped:
            response["note"] = WILDCARD_STRIP_NOTE
        return format_response(response)
    except Exception as e:
        return handle_error(e)


async def get_user(
    client: LogicMonitorClient,
    user_id: int,
) -> list[TextContent]:
    """Get detailed information about a specific user.

    Args:
        client: LogicMonitor API client.
        user_id: User ID.

    Returns:
        List of TextContent with user details or error.
    """
    try:
        result = await client.get(f"/setting/admins/{user_id}")

        user = {
            "id": result.get("id"),
            "username": result.get("username"),
            "email": result.get("email"),
            "first_name": result.get("firstName"),
            "last_name": result.get("lastName"),
            "status": result.get("status"),
            "roles": [{"id": r.get("id"), "name": r.get("name")} for r in result.get("roles", [])],
            "two_fa_enabled": result.get("twoFAEnabled"),
            "api_only": result.get("apionly"),
            "phone": result.get("phone"),
            "sms_email": result.get("smsEmail"),
            "note": result.get("note"),
            "created_by": result.get("createdBy"),
            "last_login_on": result.get("lastLoginOn"),
        }

        return format_response(user)
    except Exception as e:
        return handle_error(e)


async def get_roles(
    client: LogicMonitorClient,
    name_filter: str | None = None,
    filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[TextContent]:
    """List roles from LogicMonitor.

    Args:
        client: LogicMonitor API client.
        name_filter: Filter by role name (supports wildcards).
        filter: Raw filter expression for advanced queries (overrides name_filter).
            Supports LogicMonitor filter syntax with operators:
            : (equal), !: (not equal), > < >: <: (comparisons),
            ~ (contains), !~ (not contains).
            Examples: "name~admin,twoFARequired:true"
        limit: Maximum number of roles to return.
        offset: Number of results to skip for pagination.

    Returns:
        List of TextContent with role data or error.
    """
    try:
        params: dict = {"size": limit, "offset": offset}
        wildcards_stripped = False

        # If raw filter is provided, use it directly (power user mode)
        if filter:
            params["filter"] = filter
        elif name_filter:
            clean_name, was_modified = sanitize_filter_value(name_filter)
            wildcards_stripped = wildcards_stripped or was_modified
            params["filter"] = f"name~{quote_filter_value(clean_name)}"

        result = await client.get("/setting/roles", params=params)

        roles = []
        for item in result.get("items", []):
            roles.append(
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "description": item.get("description"),
                    "requires_eula": item.get("requireEULA"),
                    "two_fa_required": item.get("twoFARequired"),
                    "associated_user_count": item.get("associatedUserCount"),
                }
            )

        response = {
            "total": result.get("total", 0),
            "count": len(roles),
            "roles": roles,
        }
        if wildcards_stripped:
            response["note"] = WILDCARD_STRIP_NOTE
        return format_response(response)
    except Exception as e:
        return handle_error(e)


async def get_role(
    client: LogicMonitorClient,
    role_id: int,
) -> list[TextContent]:
    """Get detailed information about a specific role.

    Args:
        client: LogicMonitor API client.
        role_id: Role ID.

    Returns:
        List of TextContent with role details or error.
    """
    try:
        result = await client.get(f"/setting/roles/{role_id}")

        role = {
            "id": result.get("id"),
            "name": result.get("name"),
            "description": result.get("description"),
            "requires_eula": result.get("requireEULA"),
            "two_fa_required": result.get("twoFARequired"),
            "custom_help_label": result.get("customHelpLabel"),
            "custom_help_url": result.get("customHelpURL"),
            "privileges": result.get("privileges", []),
        }

        return format_response(role)
    except Exception as e:
        return handle_error(e)


@require_write_permission
async def create_user(
    client: LogicMonitorClient,
    username: str,
    email: str,
    first_name: str,
    last_name: str,
    roles: list[int],
    password: str | None = None,
    phone: str | None = None,
    sms_email: str | None = None,
    note: str | None = None,
    api_only: bool = False,
    two_fa_enabled: bool = False,
) -> list[TextContent]:
    """Create a new user in LogicMonitor.

    Args:
        client: LogicMonitor API client.
        username: Login username (typically email address).
        email: User email address.
        first_name: First name.
        last_name: Last name.
        roles: List of role IDs to assign.
        password: Initial password (omit for SSO-only users).
        phone: Phone number.
        sms_email: SMS email address for notifications.
        note: Admin note about the user.
        api_only: Whether user is API-only (no portal access).
        two_fa_enabled: Whether to require two-factor authentication.

    Returns:
        List of TextContent with created user info or error.
    """
    try:
        body: dict = {
            "username": username,
            "email": email,
            "firstName": first_name,
            "lastName": last_name,
            "roles": [{"id": rid} for rid in roles],
            "apionly": api_only,
            "twoFAEnabled": two_fa_enabled,
        }

        if password is not None:
            body["password"] = password
        if phone is not None:
            body["phone"] = phone
        if sms_email is not None:
            body["smsEmail"] = sms_email
        if note is not None:
            body["note"] = note

        result = await client.post("/setting/admins", json_body=body)

        return format_response(
            {
                "success": True,
                "message": f"User '{username}' created",
                "user_id": result.get("id"),
                "result": result,
            }
        )
    except Exception as e:
        return handle_error(e)


@require_write_permission
async def update_user(
    client: LogicMonitorClient,
    user_id: int,
    email: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    roles: list[int] | None = None,
    phone: str | None = None,
    sms_email: str | None = None,
    note: str | None = None,
    api_only: bool | None = None,
    two_fa_enabled: bool | None = None,
) -> list[TextContent]:
    """Update an existing user in LogicMonitor.

    Args:
        client: LogicMonitor API client.
        user_id: User ID to update.
        email: New email address.
        first_name: New first name.
        last_name: New last name.
        roles: New list of role IDs to assign (replaces existing).
        phone: New phone number.
        sms_email: New SMS email address.
        note: New admin note.
        api_only: Whether user is API-only.
        two_fa_enabled: Whether to require two-factor authentication.

    Returns:
        List of TextContent with updated user info or error.
    """
    try:
        body: dict = {}

        if email is not None:
            body["email"] = email
        if first_name is not None:
            body["firstName"] = first_name
        if last_name is not None:
            body["lastName"] = last_name
        if roles is not None:
            body["roles"] = [{"id": rid} for rid in roles]
        if phone is not None:
            body["phone"] = phone
        if sms_email is not None:
            body["smsEmail"] = sms_email
        if note is not None:
            body["note"] = note
        if api_only is not None:
            body["apionly"] = api_only
        if two_fa_enabled is not None:
            body["twoFAEnabled"] = two_fa_enabled

        if not body:
            return format_response(
                {
                    "error": True,
                    "code": "NO_CHANGES",
                    "message": "No updates provided",
                }
            )

        result = await client.patch(f"/setting/admins/{user_id}", json_body=body)

        return format_response(
            {
                "success": True,
                "message": f"User {user_id} updated",
                "result": result,
            }
        )
    except Exception as e:
        return handle_error(e)


@require_write_permission
async def delete_user(
    client: LogicMonitorClient,
    user_id: int,
) -> list[TextContent]:
    """Delete a user from LogicMonitor.

    WARNING: This permanently removes the user account.

    Args:
        client: LogicMonitor API client.
        user_id: User ID to delete.

    Returns:
        List of TextContent with deletion confirmation or error.
    """
    try:
        user = await client.get(f"/setting/admins/{user_id}")
        username = user.get("username", f"ID:{user_id}")

        await client.delete(f"/setting/admins/{user_id}")

        return format_response(
            {
                "success": True,
                "message": f"User '{username}' deleted",
                "user_id": user_id,
            }
        )
    except Exception as e:
        return handle_error(e)
