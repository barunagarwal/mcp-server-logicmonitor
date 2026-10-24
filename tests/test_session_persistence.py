# Description: Tests for session persistence layer.
# Description: Validates file-backed variable storage and loading.

from __future__ import annotations

import json
import os
import tempfile

import pytest

from lm_mcp.session import (
    get_session,
    reset_session,
    set_session,
)


@pytest.fixture(autouse=True)
def _clean_session():
    """Reset session state before and after each test."""
    from lm_mcp.session import set_persistence_path

    set_persistence_path(None)
    reset_session()
    yield
    set_persistence_path(None)
    reset_session()


class TestPersistencePath:
    """Tests for persistence path configuration."""

    def test_set_persistence_path_none_is_noop(self):
        """Setting path to None disables persistence (default behavior)."""
        from lm_mcp.session import get_persistence_path, set_persistence_path

        set_persistence_path(None)
        assert get_persistence_path() is None

    def test_set_persistence_path_configures_path(self):
        """Setting a path enables file-backed persistence."""
        from lm_mcp.session import get_persistence_path, set_persistence_path

        set_persistence_path("/tmp/test_session.json")
        assert get_persistence_path() == "/tmp/test_session.json"


class TestSaveVariables:
    """Tests for saving session variables to file."""

    def test_variables_saved_on_set(self):
        """Setting a variable writes to the persistence file."""
        from lm_mcp.session import set_persistence_path

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name

        try:
            set_persistence_path(path)
            session = get_session()
            session.set_variable("test_key", "test_value")

            with open(path) as f:
                data = json.load(f)
            assert data["test_key"] == "test_value"
        finally:
            os.unlink(path)

    def test_saved_file_is_valid_json(self):
        """Persistence file contains valid JSON."""
        from lm_mcp.session import set_persistence_path

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name

        try:
            set_persistence_path(path)
            session = get_session()
            session.set_variable("key1", {"nested": [1, 2, 3]})

            with open(path) as f:
                data = json.load(f)
            assert data["key1"]["nested"] == [1, 2, 3]
        finally:
            os.unlink(path)

    def test_save_empty_variables(self):
        """Clearing variables writes empty dict to file."""
        from lm_mcp.session import set_persistence_path

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name

        try:
            set_persistence_path(path)
            session = get_session()
            session.set_variable("key", "val")
            session.clear()

            with open(path) as f:
                data = json.load(f)
            assert data == {}
        finally:
            os.unlink(path)

    def test_delete_variable_updates_file(self):
        """Deleting a variable updates the persistence file."""
        from lm_mcp.session import set_persistence_path

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name

        try:
            set_persistence_path(path)
            session = get_session()
            session.set_variable("a", 1)
            session.set_variable("b", 2)
            session.delete_variable("a")

            with open(path) as f:
                data = json.load(f)
            assert "a" not in data
            assert data["b"] == 2
        finally:
            os.unlink(path)

    def test_no_save_when_persistence_disabled(self):
        """Variables are not saved to file when persistence is disabled."""
        from lm_mcp.session import set_persistence_path

        set_persistence_path(None)
        session = get_session()
        session.set_variable("key", "val")
        # No file created, no error raised


class TestLoadVariables:
    """Tests for loading session variables from file."""

    def test_variables_loaded_on_session_init(self):
        """Variables are loaded from file when session is created."""
        from lm_mcp.session import set_persistence_path

        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            json.dump({"loaded_key": "loaded_value"}, f)
            path = f.name

        try:
            set_persistence_path(path)
            # Force new session creation
            set_session(None)
            session = get_session()
            assert session.get_variable("loaded_key") == "loaded_value"
        finally:
            os.unlink(path)

    def test_missing_file_handled_gracefully(self):
        """Missing persistence file does not cause error."""
        from lm_mcp.session import set_persistence_path

        set_persistence_path("/tmp/nonexistent_session_file_12345.json")
        set_session(None)
        session = get_session()
        assert session.variables == {}

    def test_corrupt_file_handled_gracefully(self):
        """Corrupt JSON file does not cause error."""
        from lm_mcp.session import set_persistence_path

        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            f.write("not valid json {{{")
            path = f.name

        try:
            set_persistence_path(path)
            set_session(None)
            session = get_session()
            assert session.variables == {}
        finally:
            os.unlink(path)

    def test_loaded_variables_accessible(self):
        """Loaded variables can be retrieved via get_variable."""
        from lm_mcp.session import set_persistence_path

        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            json.dump({"count": 42, "name": "test"}, f)
            path = f.name

        try:
            set_persistence_path(path)
            set_session(None)
            session = get_session()
            assert session.get_variable("count") == 42
            assert session.get_variable("name") == "test"
        finally:
            os.unlink(path)


class TestPersistenceIntegration:
    """Integration tests for persistence round-trip."""

    def test_set_variable_survives_session_reset(self):
        """Variables set in one session are available after reset."""
        from lm_mcp.session import set_persistence_path

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name

        try:
            set_persistence_path(path)
            session = get_session()
            session.set_variable("persist_me", "hello")

            # Simulate server restart: clear in-memory session
            set_session(None)
            new_session = get_session()
            assert new_session.get_variable("persist_me") == "hello"
        finally:
            os.unlink(path)

    @pytest.fixture
    def _no_backends(self, monkeypatch):
        """Leave every optional backend unconfigured so bootstrap builds none."""
        from lm_mcp.terraform_config import reset_terraform_config

        for var in ("AWX_URL", "AWX_TOKEN", "WATSONX_API_KEY", "TF_WORKSPACE_DIR"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setattr("lm_mcp.hf_config.get_hf_config", lambda: None)
        monkeypatch.setenv("LM_PORTAL", "test.logicmonitor.com")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test-token")
        reset_terraform_config()
        yield
        reset_terraform_config()

    @pytest.mark.usefixtures("_no_backends")
    async def test_transport_bootstrap_wires_the_configured_path(self, monkeypatch, tmp_path):
        """R4.6: startup with LM_SESSION_PERSIST_PATH set persists a variable set via the server."""
        from lm_mcp.config import get_config
        from lm_mcp.server import execute_tool
        from lm_mcp.session import get_persistence_path
        from lm_mcp.transport.bootstrap import bootstrap_backends

        path = tmp_path / "session.json"
        monkeypatch.setenv("LM_SESSION_PERSIST_PATH", str(path))

        backends = bootstrap_backends(get_config())
        try:
            result = await execute_tool(
                "set_session_variable", {"name": "region", "value": "us-west"}
            )
        finally:
            await backends.close()

        assert not getattr(result[0], "isError", False)
        assert get_persistence_path() == str(path)
        assert json.loads(path.read_text()) == {"region": "us-west"}

    @pytest.mark.usefixtures("_no_backends")
    async def test_transport_bootstrap_loads_variables_from_a_previous_run(
        self, monkeypatch, tmp_path
    ):
        """R4.6: a restarted server reads back the variables the last run persisted."""
        from lm_mcp.config import get_config
        from lm_mcp.transport.bootstrap import bootstrap_backends

        path = tmp_path / "session.json"
        path.write_text(json.dumps({"region": "us-west"}))
        monkeypatch.setenv("LM_SESSION_PERSIST_PATH", str(path))
        set_session(None)

        backends = bootstrap_backends(get_config())
        await backends.close()

        assert get_session().get_variable("region") == "us-west"

    def test_persistence_disabled_by_default(self):
        """Without configuring a path, no persistence occurs."""
        session = get_session()
        session.set_variable("ephemeral", True)
        # No file operations, no errors
        assert session.get_variable("ephemeral") is True
