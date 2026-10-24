# Description: Tests for the session context module.
# Description: Validates session state tracking, history, and variable management.


from lm_mcp.session import (
    HistoryEntry,
    SessionContext,
    get_session,
    reset_session,
    set_session,
)


class TestHistoryEntry:
    """Tests for HistoryEntry dataclass."""

    def test_create_history_entry(self):
        """HistoryEntry can be created with required fields."""
        entry = HistoryEntry(
            tool_name="get_devices",
            timestamp="2024-01-01T00:00:00Z",
            arguments={"limit": 10},
            success=True,
        )

        assert entry.tool_name == "get_devices"
        assert entry.timestamp == "2024-01-01T00:00:00Z"
        assert entry.arguments == {"limit": 10}
        assert entry.success is True
        assert entry.result_summary is None

    def test_history_entry_with_summary(self):
        """HistoryEntry can include result summary."""
        entry = HistoryEntry(
            tool_name="get_device",
            timestamp="2024-01-01T00:00:00Z",
            arguments={"device_id": 123},
            success=True,
            result_summary="id=123, name=server01",
        )

        assert entry.result_summary == "id=123, name=server01"


class TestSessionContext:
    """Tests for SessionContext class."""

    def test_create_empty_session(self):
        """SessionContext initializes with empty state."""
        session = SessionContext()

        assert session.last_device is None
        assert session.last_alert is None
        assert session.last_device_list == []
        assert session.variables == {}
        assert session.history == []

    def test_set_and_get_variable(self):
        """Variables can be set and retrieved."""
        session = SessionContext()

        session.set_variable("target_device", 123)
        session.set_variable("filter_string", "name~prod*")

        assert session.get_variable("target_device") == 123
        assert session.get_variable("filter_string") == "name~prod*"
        assert session.get_variable("nonexistent") is None
        assert session.get_variable("nonexistent", "default") == "default"

    def test_delete_variable(self):
        """Variables can be deleted."""
        session = SessionContext()
        session.set_variable("temp", "value")

        assert session.delete_variable("temp") is True
        assert session.get_variable("temp") is None
        assert session.delete_variable("temp") is False

    def test_record_result_adds_history(self):
        """Recording a result adds to history."""
        session = SessionContext()

        session.record_result(
            tool_name="get_devices",
            arguments={"limit": 10},
            result={"items": []},
            success=True,
        )

        assert len(session.history) == 1
        assert session.history[0].tool_name == "get_devices"
        assert session.history[0].success is True

    def test_record_result_stores_device(self):
        """Recording get_device stores the device result."""
        session = SessionContext()

        device_data = {"id": 123, "name": "server01", "displayName": "Server 01"}
        session.record_result(
            tool_name="get_device",
            arguments={"device_id": 123},
            result=device_data,
            success=True,
        )

        assert session.last_device == device_data

    def test_record_result_stores_device_list(self):
        """Recording get_devices stores the device list and first device."""
        session = SessionContext()

        devices = [
            {"id": 1, "name": "server01"},
            {"id": 2, "name": "server02"},
        ]
        session.record_result(
            tool_name="get_devices",
            arguments={"limit": 10},
            result={"items": devices},
            success=True,
        )

        assert session.last_device_list == devices
        assert session.last_device == devices[0]

    def test_record_result_stores_alert(self):
        """Recording get_alert_details stores the alert result."""
        session = SessionContext()

        alert_data = {"id": "LMA123", "severity": 4, "type": "alertAck"}
        session.record_result(
            tool_name="get_alert_details",
            arguments={"alert_id": "LMA123"},
            result=alert_data,
            success=True,
        )

        assert session.last_alert == alert_data

    def test_get_implicit_id(self):
        """Implicit ID can be retrieved from last result."""
        session = SessionContext()

        session.last_device = {"id": 123, "name": "server01"}

        assert session.get_implicit_id("device") == 123
        assert session.get_implicit_id("alert") is None
        assert session.get_implicit_id("nonexistent") is None

    def test_get_implicit_ids_from_list(self):
        """Implicit IDs can be retrieved from last list result."""
        session = SessionContext()

        session.last_device_list = [
            {"id": 1, "name": "server01"},
            {"id": 2, "name": "server02"},
            {"id": 3, "name": "server03"},
        ]

        ids = session.get_implicit_ids("device")
        assert ids == [1, 2, 3]

    def test_history_size_limit(self):
        """History is trimmed when exceeding max size."""
        session = SessionContext()
        session.max_history_size = 5

        for i in range(10):
            session.record_result(
                tool_name=f"tool_{i}",
                arguments={},
                result={},
                success=True,
            )

        assert len(session.history) == 5
        assert session.history[0].tool_name == "tool_5"
        assert session.history[-1].tool_name == "tool_9"

    def test_clear_resets_all_state(self):
        """Clear resets all session state."""
        session = SessionContext()

        session.last_device = {"id": 123}
        session.last_alert = {"id": "LMA123"}
        session.last_device_list = [{"id": 1}]
        session.set_variable("key", "value")
        session.record_result("get_devices", {}, {}, True)

        session.clear()

        assert session.last_device is None
        assert session.last_alert is None
        assert session.last_device_list == []
        assert session.variables == {}
        assert session.history == []

    def test_to_dict_serializes_session(self):
        """Session can be serialized to dictionary."""
        session = SessionContext()
        session.set_variable("filter", "name~prod*")
        # record_result will update last_device
        session.record_result(
            "get_device", {"device_id": 123}, {"id": 123, "name": "server01"}, True
        )

        result = session.to_dict()

        assert "last_results" in result
        assert result["last_results"]["device"] == {"id": 123, "name": "server01"}
        assert result["variables"] == {"filter": "name~prod*"}
        assert "history" in result
        assert result["history_count"] == 1


class TestGlobalSession:
    """Tests for global session management functions."""

    def test_get_session_creates_if_missing(self):
        """get_session creates a new session if none exists."""
        set_session(None)

        session = get_session()

        assert session is not None
        assert isinstance(session, SessionContext)

    def test_get_session_returns_same_instance(self):
        """get_session returns the same instance on subsequent calls."""
        set_session(None)

        session1 = get_session()
        session2 = get_session()

        assert session1 is session2

    def test_reset_session_clears_state(self):
        """reset_session clears the current session state."""
        session = get_session()
        session.set_variable("key", "value")

        reset_session()

        assert session.get_variable("key") is None

    def test_set_session_replaces_global(self):
        """set_session replaces the global session instance."""
        # Get reference to current session
        _ = get_session()
        new_session = SessionContext()
        new_session.set_variable("new", True)

        set_session(new_session)

        current = get_session()
        assert current is new_session
        assert current.get_variable("new") is True


class TestToolResourceMap:
    """R4.6: the resource map names only tools the server registers."""

    def test_every_mapped_tool_is_registered(self):
        """A mapped name no tool carries can never record a result."""
        from lm_mcp.registry import AWX_TOOLS, TF_TOOLS, TOOLS, WATSONX_TOOLS

        registered = {t.name for t in (*TOOLS, *AWX_TOOLS, *WATSONX_TOOLS, *TF_TOOLS)}

        unregistered = [n for n in SessionContext()._tool_resource_map if n not in registered]

        assert unregistered == []


class TestResultSummarization:
    """Tests for result summarization in history."""

    def test_summarize_list_result(self):
        """List results are summarized as item counts."""
        session = SessionContext()

        session.record_result(
            tool_name="get_devices",
            arguments={},
            result={"items": [{"id": 1}, {"id": 2}, {"id": 3}]},
            success=True,
        )

        assert session.history[0].result_summary == "3 items"

    def test_summarize_singular_with_id_and_name(self):
        """Singular results with id and name are summarized."""
        session = SessionContext()

        session.record_result(
            tool_name="get_device",
            arguments={},
            result={"id": 123, "name": "server01"},
            success=True,
        )

        assert session.history[0].result_summary == "id=123, name=server01"

    def test_summarize_singular_with_display_name(self):
        """Singular results with displayName are summarized."""
        session = SessionContext()

        session.record_result(
            tool_name="get_device",
            arguments={},
            result={"id": 123, "displayName": "Server 01"},
            success=True,
        )

        assert session.history[0].result_summary == "id=123, name=Server 01"

    def test_failed_result_no_summary(self):
        """Failed results don't get summarized."""
        session = SessionContext()

        session.record_result(
            tool_name="get_device",
            arguments={},
            result={"error": "Not found"},
            success=False,
        )

        assert session.history[0].result_summary is None
