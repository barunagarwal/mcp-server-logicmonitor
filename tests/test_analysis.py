# Description: Tests for the analysis store and workflow dispatch.
# Description: Validates AnalysisRequest lifecycle and workflow routing.

from __future__ import annotations

import time

import pytest


class TestAnalysisRequest:
    """Tests for AnalysisRequest dataclass."""

    def test_request_has_required_fields(self):
        """AnalysisRequest has id, workflow, arguments, status, timestamps."""
        from lm_mcp.analysis import AnalysisRequest

        req = AnalysisRequest(
            id="test-123",
            workflow="health_check",
            arguments={},
        )
        assert req.id == "test-123"
        assert req.workflow == "health_check"
        assert req.status == "pending"
        assert req.result is None
        assert req.error is None

    def test_request_default_status_is_pending(self):
        """New requests default to pending status."""
        from lm_mcp.analysis import AnalysisRequest

        req = AnalysisRequest(id="a", workflow="w", arguments={})
        assert req.status == "pending"

    def test_request_to_dict(self):
        """AnalysisRequest serializes to dict."""
        from lm_mcp.analysis import AnalysisRequest

        req = AnalysisRequest(id="test-1", workflow="rca", arguments={"device_id": 42})
        d = req.to_dict()
        assert d["id"] == "test-1"
        assert d["workflow"] == "rca"
        assert d["status"] == "pending"
        assert "created_at" in d


class TestAnalysisStore:
    """Tests for AnalysisStore in-memory storage."""

    def test_create_returns_request(self):
        """create() returns an AnalysisRequest with generated ID."""
        from lm_mcp.analysis import AnalysisStore

        store = AnalysisStore()
        req = store.create("health_check", {})
        assert req.id is not None
        assert req.workflow == "health_check"
        assert req.status == "pending"

    def test_get_returns_stored_request(self):
        """get() retrieves a previously created request."""
        from lm_mcp.analysis import AnalysisStore

        store = AnalysisStore()
        created = store.create("rca", {"device_id": 1})
        fetched = store.get(created.id)
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.workflow == "rca"

    def test_get_returns_none_for_unknown(self):
        """get() returns None for unknown analysis ID."""
        from lm_mcp.analysis import AnalysisStore

        store = AnalysisStore()
        assert store.get("nonexistent") is None

    def test_update_changes_status(self):
        """update() modifies request status and result."""
        from lm_mcp.analysis import AnalysisStore

        store = AnalysisStore()
        req = store.create("test", {})
        store.update(req.id, status="running")
        assert store.get(req.id).status == "running"

    def test_update_sets_result(self):
        """update() stores analysis result."""
        from lm_mcp.analysis import AnalysisStore

        store = AnalysisStore()
        req = store.create("test", {})
        store.update(req.id, status="completed", result={"data": "ok"})
        fetched = store.get(req.id)
        assert fetched.status == "completed"
        assert fetched.result == {"data": "ok"}

    def test_update_sets_error(self):
        """update() stores error message on failure."""
        from lm_mcp.analysis import AnalysisStore

        store = AnalysisStore()
        req = store.create("test", {})
        store.update(req.id, status="failed", error="Something broke")
        fetched = store.get(req.id)
        assert fetched.status == "failed"
        assert fetched.error == "Something broke"

    def test_cleanup_expired_removes_old_entries(self):
        """cleanup_expired() removes finished entries past TTL."""
        from lm_mcp.analysis import AnalysisStore

        store = AnalysisStore(ttl_minutes=0)
        req = store.create("test", {})
        store.update(req.id, status="completed", result={})
        # Force the run's timestamps to the past
        req.created_at = time.time() - 180
        req.completed_at = time.time() - 120
        store.cleanup_expired()
        assert store.get(req.id) is None

    def test_cleanup_keeps_recent_entries(self):
        """cleanup_expired() keeps entries within TTL."""
        from lm_mcp.analysis import AnalysisStore

        store = AnalysisStore(ttl_minutes=60)
        req = store.create("test", {})
        store.cleanup_expired()
        assert store.get(req.id) is not None

    def test_list_recent(self):
        """list_recent() returns entries ordered by creation time."""
        from lm_mcp.analysis import AnalysisStore

        store = AnalysisStore()
        store.create("first", {})
        r2 = store.create("second", {})
        recent = store.list_recent(limit=10)
        assert len(recent) == 2
        assert recent[0].id == r2.id  # Most recent first

    def test_create_evicts_expired_entries(self):
        """R4.6: a create after the TTL drops the expired entries, so the store stays bounded."""
        from lm_mcp.analysis import AnalysisStore

        store = AnalysisStore(ttl_minutes=60)
        old = [store.create("health_check", {}) for _ in range(3)]
        for req in old:
            store.update(req.id, status="completed", result={})
            req.created_at = time.time() - 3700
            req.completed_at = time.time() - 3601

        fresh = store.create("health_check", {})

        assert all(store.get(req.id) is None for req in old)
        assert store.get(fresh.id) is fresh
        assert len(store.list_recent(limit=100)) == 1

    def test_update_evicts_expired_entries(self):
        """R4.6: an update after the TTL drops the expired entries and still applies."""
        from lm_mcp.analysis import AnalysisStore

        store = AnalysisStore(ttl_minutes=60)
        old = store.create("health_check", {})
        current = store.create("health_check", {})
        store.update(old.id, status="failed", error="boom")
        old.created_at = time.time() - 3700
        old.completed_at = time.time() - 3601

        store.update(current.id, status="running")

        assert store.get(old.id) is None
        assert store.get(current.id).status == "running"
        assert len(store.list_recent(limit=100)) == 1

    def test_in_flight_entries_outlive_the_ttl(self):
        """R4.6: a pending or running analysis older than the TTL keeps its entry and result."""
        from lm_mcp.analysis import AnalysisStore

        store = AnalysisStore(ttl_minutes=60)
        queued = store.create("health_check", {})
        running = store.create("health_check", {})
        store.update(running.id, status="running")
        queued.created_at = running.created_at = time.time() - 3601

        store.create("health_check", {})
        store.update(running.id, status="completed", result={"alerts": []})

        assert store.get(queued.id).status == "pending"
        assert store.get(running.id).status == "completed"
        assert store.get(running.id).result == {"alerts": []}

    def test_ttl_counts_from_completion(self):
        """R4.6: a finished analysis stays readable for the TTL after it completed."""
        from lm_mcp.analysis import AnalysisStore

        store = AnalysisStore(ttl_minutes=60)
        req = store.create("health_check", {})
        store.update(req.id, status="completed", result={})
        req.created_at = time.time() - 7200

        store.create("health_check", {})

        assert store.get(req.id) is req


class TestWorkflowDispatch:
    """Tests for workflow routing."""

    def test_valid_workflows_list(self):
        """VALID_WORKFLOWS contains expected workflow names."""
        from lm_mcp.analysis import VALID_WORKFLOWS

        assert "alert_correlation" in VALID_WORKFLOWS
        assert "rca_workflow" in VALID_WORKFLOWS
        assert "top_talkers" in VALID_WORKFLOWS
        assert "health_check" in VALID_WORKFLOWS

    def test_invalid_workflow_raises(self):
        """Unknown workflow raises ValueError."""
        from lm_mcp.analysis import validate_workflow

        with pytest.raises(ValueError, match="Unknown workflow"):
            validate_workflow("nonexistent_workflow")

    def test_valid_workflow_passes(self):
        """Known workflow passes validation."""
        from lm_mcp.analysis import validate_workflow

        validate_workflow("health_check")

    def test_capacity_forecast_in_valid_workflows(self):
        """capacity_forecast is a valid workflow."""
        from lm_mcp.analysis import VALID_WORKFLOWS

        assert "capacity_forecast" in VALID_WORKFLOWS

    def test_device_health_assessment_in_valid_workflows(self):
        """device_health_assessment is a valid workflow."""
        from lm_mcp.analysis import VALID_WORKFLOWS

        assert "device_health_assessment" in VALID_WORKFLOWS

    def test_capacity_forecast_validates(self):
        """capacity_forecast passes validation."""
        from lm_mcp.analysis import validate_workflow

        validate_workflow("capacity_forecast")

    def test_device_health_assessment_validates(self):
        """device_health_assessment passes validation."""
        from lm_mcp.analysis import validate_workflow

        validate_workflow("device_health_assessment")


class TestCapacityForecastWorkflow:
    """Tests for capacity_forecast workflow dispatch."""

    async def test_dispatch_capacity_forecast(self):
        """capacity_forecast dispatches to the correct runner."""
        from lm_mcp.analysis import _dispatch_workflow

        calls = []

        async def mock_execute(tool_name, args):
            calls.append(tool_name)
            from mcp.types import TextContent

            return [TextContent(type="text", text='{"result": "ok"}')]

        result = await _dispatch_workflow(
            "capacity_forecast",
            {
                "device_id": 1,
                "device_datasource_id": 10,
                "instance_id": 100,
                "threshold": 90.0,
            },
            mock_execute,
        )

        assert result["workflow"] == "capacity_forecast"
        assert "forecast" in result
        assert "trend_classification" in result
        assert "forecast_metric" in calls
        assert "classify_trend" in calls


class TestDeviceHealthAssessmentWorkflow:
    """Tests for device_health_assessment workflow dispatch."""

    async def test_dispatch_device_health_assessment(self):
        """device_health_assessment dispatches to the correct runner."""
        from lm_mcp.analysis import _dispatch_workflow

        calls = []

        async def mock_execute(tool_name, args):
            calls.append(tool_name)
            from mcp.types import TextContent

            return [TextContent(type="text", text='{"result": "ok"}')]

        result = await _dispatch_workflow(
            "device_health_assessment",
            {
                "device_id": 1,
                "device_datasource_id": 10,
                "instance_id": 100,
            },
            mock_execute,
        )

        assert result["workflow"] == "device_health_assessment"
        assert "health" in result
        assert "blast_radius" in result
        assert "anomalies" in result
        assert "score_device_health" in calls
        assert "analyze_blast_radius" in calls
        assert "get_metric_anomalies" in calls
