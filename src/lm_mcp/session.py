# Description: Session context module for tracking operation results across tool calls.
# Description: Enables conversational workflows like "update the device" without re-specifying IDs.

import contextlib
import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class HistoryEntry:
    """A single entry in the tool call history."""

    tool_name: str
    timestamp: str
    arguments: dict[str, Any]
    success: bool
    result_summary: str | None = None


@dataclass
class SessionContext:
    """Per-session state for tracking operation results.

    Enables conversational workflows by storing:
    - Last results by resource type for implicit ID resolution
    - User-defined variables for cross-tool state
    - Recent tool call history for context

    Thread Safety:
        This implementation is NOT thread-safe. Each session should have
        its own SessionContext instance.
    """

    # Last results by resource type (singular)
    last_device: dict[str, Any] | None = None
    last_alert: dict[str, Any] | None = None
    last_sdt: dict[str, Any] | None = None
    last_collector: dict[str, Any] | None = None
    last_dashboard: dict[str, Any] | None = None
    last_website: dict[str, Any] | None = None
    last_user: dict[str, Any] | None = None
    last_device_group: dict[str, Any] | None = None
    last_website_group: dict[str, Any] | None = None
    last_collector_group: dict[str, Any] | None = None
    last_escalation_chain: dict[str, Any] | None = None
    last_alert_rule: dict[str, Any] | None = None
    last_report: dict[str, Any] | None = None

    # Last results by resource type (list)
    last_device_list: list[dict[str, Any]] = field(default_factory=list)
    last_alert_list: list[dict[str, Any]] = field(default_factory=list)
    last_sdt_list: list[dict[str, Any]] = field(default_factory=list)
    last_collector_list: list[dict[str, Any]] = field(default_factory=list)
    last_dashboard_list: list[dict[str, Any]] = field(default_factory=list)
    last_website_list: list[dict[str, Any]] = field(default_factory=list)
    last_user_list: list[dict[str, Any]] = field(default_factory=list)
    last_device_group_list: list[dict[str, Any]] = field(default_factory=list)
    last_website_group_list: list[dict[str, Any]] = field(default_factory=list)
    last_collector_group_list: list[dict[str, Any]] = field(default_factory=list)

    # User-defined variables
    variables: dict[str, Any] = field(default_factory=dict)

    # Tool call history (circular buffer)
    history: list[HistoryEntry] = field(default_factory=list)
    max_history_size: int = 50

    # Mapping from tool name patterns to resource types
    _tool_resource_map: dict[str, str] = field(
        default_factory=lambda: {
            "get_device": "device",
            "get_devices": "device_list",
            "create_device": "device",
            "update_device": "device",
            "get_alerts": "alert_list",
            "get_alert_details": "alert",
            "acknowledge_alert": "alert",
            "list_sdts": "sdt_list",
            "create_sdt": "sdt",
            "get_collector": "collector",
            "get_collectors": "collector_list",
            "get_dashboard": "dashboard",
            "get_dashboards": "dashboard_list",
            "create_dashboard": "dashboard",
            "update_dashboard": "dashboard",
            "get_website": "website",
            "get_websites": "website_list",
            "create_website": "website",
            "update_website": "website",
            "get_user": "user",
            "get_users": "user_list",
            "get_device_group": "device_group",
            "get_device_groups": "device_group_list",
            "create_device_group": "device_group",
            "get_website_groups": "website_group_list",
            "create_website_group": "website_group",
            "get_collector_group": "collector_group",
            "get_collector_groups": "collector_group_list",
            "get_escalation_chain": "escalation_chain",
            "get_escalation_chains": "escalation_chain_list",
            "create_escalation_chain": "escalation_chain",
            "get_alert_rule": "alert_rule",
            "get_alert_rules": "alert_rule_list",
            "create_alert_rule": "alert_rule",
            "get_report": "report",
            "get_reports": "report_list",
        }
    )

    def record_result(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        result: Any,
        success: bool = True,
    ) -> None:
        """Record a tool result for future reference.

        Args:
            tool_name: Name of the tool that was called
            arguments: Arguments passed to the tool
            result: The result returned by the tool
            success: Whether the tool call succeeded
        """
        # Add to history
        summary = self._summarize_result(result) if success else None
        entry = HistoryEntry(
            tool_name=tool_name,
            timestamp=datetime.now(UTC).isoformat(),
            arguments=arguments,
            success=success,
            result_summary=summary,
        )
        self.history.append(entry)

        # Trim history if needed
        if len(self.history) > self.max_history_size:
            self.history = self.history[-self.max_history_size :]

        # Update last result if successful and we know the resource type
        if success and tool_name in self._tool_resource_map:
            resource_type = self._tool_resource_map[tool_name]
            self._store_result(resource_type, result)

    def _store_result(self, resource_type: str, result: Any) -> None:
        """Store result in the appropriate last_* attribute."""
        if not isinstance(result, dict):
            return

        # Handle list results
        if resource_type.endswith("_list"):
            items = result.get("items", result.get("data", []))
            if isinstance(items, list):
                attr_name = f"last_{resource_type}"
                if hasattr(self, attr_name):
                    setattr(self, attr_name, items)
                    # Also store first item as singular
                    singular_type = resource_type[:-5]  # Remove "_list"
                    if items:
                        singular_attr = f"last_{singular_type}"
                        if hasattr(self, singular_attr):
                            setattr(self, singular_attr, items[0])
        else:
            # Handle singular results
            # Look for the item in common result structures
            item = result.get("item", result.get("data", result))
            if isinstance(item, dict):
                attr_name = f"last_{resource_type}"
                if hasattr(self, attr_name):
                    setattr(self, attr_name, item)

    def _summarize_result(self, result: Any) -> str | None:
        """Create a brief summary of a result for history display."""
        if not isinstance(result, dict):
            return None

        # Count items if it's a list result
        items = result.get("items", result.get("data"))
        if isinstance(items, list):
            return f"{len(items)} items"

        # Get ID and name for singular results
        item = result.get("item", result.get("data", result))
        if isinstance(item, dict):
            item_id = item.get("id")
            name = item.get("name", item.get("displayName", item.get("alertId")))
            if item_id and name:
                return f"id={item_id}, name={name}"
            elif item_id:
                return f"id={item_id}"
            elif name:
                return f"name={name}"

        return None

    def get_implicit_id(self, resource_type: str) -> int | str | None:
        """Get implicit ID from last operation of given type.

        Args:
            resource_type: Resource type (e.g., "device", "alert")

        Returns:
            The ID from the last operation of that type, or None if not available
        """
        attr_name = f"last_{resource_type}"
        if not hasattr(self, attr_name):
            return None

        last_result = getattr(self, attr_name)
        if not isinstance(last_result, dict):
            return None

        return last_result.get("id")

    def get_implicit_ids(self, resource_type: str) -> list[int | str]:
        """Get implicit IDs from last list operation of given type.

        Args:
            resource_type: Resource type (e.g., "device", "alert")

        Returns:
            List of IDs from the last list operation, or empty list if not available
        """
        attr_name = f"last_{resource_type}_list"
        if not hasattr(self, attr_name):
            return []

        last_list = getattr(self, attr_name)
        if not isinstance(last_list, list):
            return []

        return [item.get("id") for item in last_list if isinstance(item, dict) and item.get("id")]

    def set_variable(self, name: str, value: Any) -> None:
        """Set a user-defined variable.

        Args:
            name: Variable name
            value: Variable value (must be JSON-serializable)
        """
        self.variables[name] = value
        _save_variables(self)

    def get_variable(self, name: str, default: Any = None) -> Any:
        """Get a user-defined variable.

        Args:
            name: Variable name
            default: Default value if variable not found

        Returns:
            Variable value or default
        """
        return self.variables.get(name, default)

    def delete_variable(self, name: str) -> bool:
        """Delete a user-defined variable.

        Args:
            name: Variable name

        Returns:
            True if variable was deleted, False if it didn't exist
        """
        if name in self.variables:
            del self.variables[name]
            _save_variables(self)
            return True
        return False

    def clear(self) -> None:
        """Reset all session state."""
        # Clear singular results
        self.last_device = None
        self.last_alert = None
        self.last_sdt = None
        self.last_collector = None
        self.last_dashboard = None
        self.last_website = None
        self.last_user = None
        self.last_device_group = None
        self.last_website_group = None
        self.last_collector_group = None
        self.last_escalation_chain = None
        self.last_alert_rule = None
        self.last_report = None

        # Clear list results
        self.last_device_list = []
        self.last_alert_list = []
        self.last_sdt_list = []
        self.last_collector_list = []
        self.last_dashboard_list = []
        self.last_website_list = []
        self.last_user_list = []
        self.last_device_group_list = []
        self.last_website_group_list = []
        self.last_collector_group_list = []

        # Clear variables and history
        self.variables = {}
        self.history = []
        _save_variables(self)

    def to_dict(self) -> dict[str, Any]:
        """Convert session context to dictionary for serialization.

        Returns:
            Dictionary representation of session state
        """
        return {
            "last_results": {
                "device": self.last_device,
                "device_list": self.last_device_list[:5] if self.last_device_list else None,
                "alert": self.last_alert,
                "alert_list": self.last_alert_list[:5] if self.last_alert_list else None,
                "sdt": self.last_sdt,
                "sdt_list": self.last_sdt_list[:5] if self.last_sdt_list else None,
                "collector": self.last_collector,
                "dashboard": self.last_dashboard,
                "website": self.last_website,
                "user": self.last_user,
                "device_group": self.last_device_group,
                "website_group": self.last_website_group,
                "collector_group": self.last_collector_group,
                "escalation_chain": self.last_escalation_chain,
                "alert_rule": self.last_alert_rule,
                "report": self.last_report,
            },
            "variables": self.variables,
            "history": [
                {
                    "tool": e.tool_name,
                    "timestamp": e.timestamp,
                    "success": e.success,
                    "summary": e.result_summary,
                }
                for e in self.history[-10:]  # Last 10 entries only
            ],
            "history_count": len(self.history),
        }


# Global session context instance for stdio mode
_session: SessionContext | None = None

# File-backed persistence path (None = in-memory only)
_persistence_path: str | None = None


def set_persistence_path(path: str | None) -> None:
    """Configure file-backed persistence for session variables.

    Args:
        path: File path for JSON storage, or None to disable.
    """
    global _persistence_path
    _persistence_path = path


def get_persistence_path() -> str | None:
    """Get the configured persistence file path.

    Returns:
        The persistence path, or None if disabled.
    """
    return _persistence_path


def _save_variables(session: SessionContext) -> None:
    """Write session variables to persistence file (atomic).

    Uses write-to-temp + os.replace() for crash safety.
    No-op when persistence is disabled.
    """
    if _persistence_path is None:
        return

    try:
        dir_name = os.path.dirname(_persistence_path) or "."
        fd, tmp_path = tempfile.mkstemp(suffix=".tmp", dir=dir_name)
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(session.variables, f)
            os.replace(tmp_path, _persistence_path)
        except BaseException:
            # Clean up temp file on any failure
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise
    except Exception:
        logger.warning(
            "Failed to save session variables to %s",
            _persistence_path,
            exc_info=True,
        )


def _load_variables(session: SessionContext) -> None:
    """Load session variables from persistence file.

    Handles missing files and corrupt JSON gracefully.
    No-op when persistence is disabled.
    """
    if _persistence_path is None:
        return

    try:
        with open(_persistence_path) as f:
            data = json.load(f)
        if isinstance(data, dict):
            session.variables = data
    except FileNotFoundError:
        pass
    except (json.JSONDecodeError, OSError):
        logger.warning(
            "Failed to load session variables from %s",
            _persistence_path,
            exc_info=True,
        )


def get_session() -> SessionContext:
    """Get the global session context, creating it if needed.

    On first creation, loads persisted variables from file if configured.

    Returns:
        The global SessionContext instance
    """
    global _session
    if _session is None:
        _session = SessionContext()
        _load_variables(_session)
    return _session


def reset_session() -> None:
    """Reset the global session context."""
    global _session
    if _session is not None:
        _session.clear()


def set_session(session: SessionContext | None) -> None:
    """Set the global session context.

    Args:
        session: SessionContext instance to use, or None to clear.
    """
    global _session
    _session = session
