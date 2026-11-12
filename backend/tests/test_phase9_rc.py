"""Phase 9 Release Candidate Tests: Hardening, Diagnostics, Reconnect, Restart Persistence, and Privacy Log Export."""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, MagicMock
import pytest
from fastapi.testclient import TestClient

from app.action_router.capabilities import CapabilityRegistry
from app.action_router.executor import ActionExecutor
from app.config import (
    PrivacySafeLogExporter,
    SystemDiagnosticsService,
    sanitize_user_paths,
)
from app.database.persistence import DatabaseManager
from app.integrations.fl_studio.adapter import ConnectionStatus, FLStudioAdapter
from app.main import app
from app.project_memory import ProjectMemoryManager, TaskSummaryRecord
from app.schemas.actions import (
    ActionDefinition,
    ActionLifecycleState,
    ActionRiskLevel,
    ActionType,
)


class TestSystemDiagnosticsAndPackaging:
    def test_diagnostics_and_secret_hygiene(self):
        service = SystemDiagnosticsService()
        report = service.run_diagnostics(probe_live_fl=False)

        by_name = {c.name: c for c in report.checks}
        assert by_name["python_and_os"].ready is True
        assert by_name["hcu_gui_automation"].ready is True
        assert by_name["desktop_companion_binary"].ready is True
        assert by_name["secret_hygiene"].ready is True
        assert by_name["secret_hygiene"].status == "CLEAN"
        assert report.overall_ready is True
        assert len(report.project_backup_guidance) >= 3

        # When FL Studio is not probed live, remediation instructions are still clear
        if not by_name["fl_studio_mcp"].ready:
            assert "loopMIDI" in by_name["fl_studio_mcp"].remediation


class TestReconnectAndHonestOfflineFailure:
    @pytest.mark.asyncio
    async def test_never_claims_success_when_fl_studio_unavailable(self, tmp_path):
        """When FL Studio is unreachable, real FL_MCP actions must fail honestly, never fake success."""
        db = DatabaseManager(db_path=str(tmp_path / "offline.db"))
        offline_fl = MagicMock(spec=FLStudioAdapter)
        offline_fl.check_health.return_value = ConnectionStatus(
            connected=False,
            fl_studio_alive=False,
            error="FL Studio daemon unreachable",
        )
        offline_fl.connect.return_value = ConnectionStatus(
            connected=False,
            fl_studio_alive=False,
            error="FL Studio daemon unreachable",
        )
        executor = ActionExecutor(db=db, fl_adapter=offline_fl)

        action = ActionDefinition(
            task_id="task_offline_test",
            action_type=ActionType.SET_TEMPO,
            description="Attempt tempo change while FL Studio is offline",
            parameters={"bpm": 128.0},
            execution_route="FL_MCP",
            risk_level=ActionRiskLevel.LOW,
            max_retries=0,
        )

        result = await executor.execute_action(action, prefer_mock=False)
        assert result.status != ActionLifecycleState.SUCCEEDED
        assert result.verified is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_reconnect_behavior_recovers_cleanly(self):
        """Capability discovery marks FL_MCP inactive when disconnected and active again on reconnect."""
        registry = CapabilityRegistry()
        mock_adapter = MagicMock()

        # 1. Simulate FL Studio disconnected
        mock_adapter.async_check_health = AsyncMock(
            return_value=ConnectionStatus(
                connected=False,
                fl_studio_alive=False,
                error="Connection refused",
            )
        )
        route_offline = await registry.discover_fl_capabilities(mock_adapter)
        assert route_offline.is_active is False

        # 2. Simulate FL Studio reconnected
        mock_adapter.async_check_health = AsyncMock(
            return_value=ConnectionStatus(
                connected=True,
                fl_studio_alive=True,
            )
        )
        route_online = await registry.discover_fl_capabilities(mock_adapter)
        assert route_online.is_active is True
        assert ActionType.SET_TEMPO in route_online.supported_actions


class TestRestartAndInterruptedTaskPersistence:
    def test_interrupted_tasks_and_app_restart_persistence(self, tmp_path):
        db_file = str(tmp_path / "restart_persist.db")
        mem_file = str(tmp_path / "restart_memory.json")

        # Session 1: before app restart
        db1 = DatabaseManager(db_path=db_file)
        mem1 = ProjectMemoryManager(storage_path=mem_file)

        act_ok = ActionDefinition(
            action_id="act_rc_ok",
            task_id="task_rc_1",
            action_type=ActionType.SET_TEMPO,
            parameters={"bpm": 126.0},
            status=ActionLifecycleState.SUCCEEDED,
            verified=True,
        )
        act_cancelled = ActionDefinition(
            action_id="act_rc_cancel",
            task_id="task_rc_1",
            action_type=ActionType.SET_STEP_GRID,
            parameters={"channel": 0, "steps": [0, 4, 8, 12]},
            status=ActionLifecycleState.CANCELLED,
            verified=False,
        )
        db1.save_action(act_ok)
        db1.save_action(act_cancelled)

        mem1.record_task_summary(
            TaskSummaryRecord(
                task_id="task_rc_1",
                plan_id="plan_rc_1",
                prompt="Interrupted session test",
                parsed_intent={"genre": "melodic_techno"},
                actions_planned=2,
                actions_succeeded=1,
                actions_verified=1,
                actions_failed=0,
                actions_awaiting_approval=0,
                completed_steps=["Set tempo to 126 BPM"],
                remaining_limitations=["Interrupted by user stop on step 2"],
            )
        )

        # Session 2: simulate application restart by creating new instances on the same files
        db2 = DatabaseManager(db_path=db_file)
        mem2 = ProjectMemoryManager(storage_path=mem_file)

        recovered_actions = db2.list_actions_for_task("task_rc_1")
        assert len(recovered_actions) == 2
        statuses = {a.action_id: a.status.value for a in recovered_actions}
        assert statuses["act_rc_ok"] == ActionLifecycleState.SUCCEEDED.value
        assert statuses["act_rc_cancel"] == ActionLifecycleState.CANCELLED.value

        recovered_summaries = mem2.get_recent_summaries()
        assert len(recovered_summaries) == 1
        assert recovered_summaries[0].task_id == "task_rc_1"
        assert "Interrupted by user stop" in recovered_summaries[0].remaining_limitations[0]


class TestPrivacySafeCrashAndLogExport:
    def test_privacy_safe_crash_report_and_log_export(self, tmp_path):
        try:
            raise RuntimeError(
                r"Failed reading C:\Users\emoca\Documents\MyProject.flp with key sk-proj999888777666555"
            )
        except RuntimeError as exc:
            crash = PrivacySafeLogExporter.format_crash_report(
                exc,
                context_note=r"User path C:\Users\emoca\Desktop and Bearer super_secret_token_123",
            )

        assert "emoca" not in crash["message"]
        assert r"C:\Users\[USER]" in crash["message"]
        assert "sk-proj999888777666555" not in crash["message"]
        assert "[REDACTED_SECRET]" in crash["message"]
        assert "super_secret_token_123" not in crash["context"]

        export_file = str(tmp_path / "exported_logs.json")
        diag = SystemDiagnosticsService().run_diagnostics(probe_live_fl=False)
        out_path = PrivacySafeLogExporter.export_sanitized_logs(
            export_file,
            diagnostics=diag,
            extra_logs=[
                r"Loaded sample from C:\Users\emoca\Samples\kick.wav",
                "Auth header: Bearer my_private_token_abcdef123",
            ],
        )
        assert os.path.isfile(out_path)
        with open(out_path, "r", encoding="utf-8") as f:
            raw_text = f.read()

        assert "my_private_token_abcdef123" not in raw_text
        assert "emoca" not in raw_text
        parsed = json.loads(raw_text)
        assert parsed["diagnostics"]["overall_ready"] is True

    def test_diagnostics_and_log_export_api_endpoints(self, tmp_path):
        client = TestClient(app)
        resp = client.get("/api/diagnostics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["overall_ready"] is True
        check_names = {c["name"] for c in data["checks"]}
        assert "secret_hygiene" in check_names
        assert "desktop_companion_binary" in check_names

        export_target = str(tmp_path / "api_log_bundle.json")
        exp_resp = client.post("/api/logs/export", json={"output_path": export_target})
        assert exp_resp.status_code == 200
        assert exp_resp.json()["exported"] is True
        assert os.path.isfile(export_target)
