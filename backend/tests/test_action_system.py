"""Phase 3 automated tests: Action system, permissions, verification, persistence, and recovery."""

import asyncio
import os
import sys
import tempfile
from pathlib import Path
import pytest
from pydantic import ValidationError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.schemas.actions import (
    ActionDefinition,
    ActionLifecycleState,
    ActionRiskLevel,
    ActionType,
    is_valid_transition,
)
from app.action_router.capabilities import CapabilityRegistry, RouteCapabilities
from app.action_router.permissions import ApprovalManager, classify_risk
from app.action_router.router import ActionRouter
from app.action_router.executor import ActionExecutor
from app.database.persistence import DatabaseManager
from app.verification.engine import VerificationEngine
from app.recovery.manager import CheckpointRecoveryManager


# =========================================================================
# 1. Action Schemas & Allowlist Tests
# =========================================================================

def test_reject_arbitrary_shell_or_invalid_action():
    """Rule: Model output cannot directly execute arbitrary shell commands."""
    with pytest.raises(ValidationError):
        ActionDefinition(
            action_id="act_bad_1",
            task_id="task_1",
            action_type="RUN_SHELL_COMMAND",  # Not in allowlist
        )

    with pytest.raises(ValidationError):
        ActionDefinition(
            action_id="act_bad_2",
            task_id="task_1",
            action_type="rmdir /s /q C:\\",  # Not in allowlist
        )


def test_valid_action_creation():
    act = ActionDefinition(
        action_id="act_001",
        task_id="task_001",
        action_type=ActionType.SET_TEMPO,
        parameters={"bpm": 128.0},
    )
    assert act.action_id == "act_001"
    assert act.status == ActionLifecycleState.PLANNED
    assert act.created_at is not None


# =========================================================================
# 2. Lifecycle State Transition Tests
# =========================================================================

def test_valid_state_transitions():
    act = ActionDefinition(
        action_id="act_trans_1",
        task_id="task_1",
        action_type=ActionType.SET_TEMPO,
        parameters={"bpm": 128.0},
    )
    # PLANNED -> READY -> RUNNING -> VERIFYING -> SUCCEEDED
    assert act.transition_to(ActionLifecycleState.READY)
    assert act.status == ActionLifecycleState.READY

    assert act.transition_to(ActionLifecycleState.RUNNING)
    assert act.status == ActionLifecycleState.RUNNING
    assert act.started_at is not None

    assert act.transition_to(ActionLifecycleState.VERIFYING)
    assert act.status == ActionLifecycleState.VERIFYING

    assert act.transition_to(ActionLifecycleState.SUCCEEDED)
    assert act.status == ActionLifecycleState.SUCCEEDED
    assert act.finished_at is not None


def test_invalid_state_transitions_raise():
    act = ActionDefinition(
        action_id="act_trans_2",
        task_id="task_1",
        action_type=ActionType.SET_TEMPO,
    )
    # Cannot jump directly from PLANNED to SUCCEEDED or VERIFYING
    with pytest.raises(ValueError, match="Invalid action state transition"):
        act.transition_to(ActionLifecycleState.SUCCEEDED)

    with pytest.raises(ValueError, match="Invalid action state transition"):
        act.transition_to(ActionLifecycleState.VERIFYING)


# =========================================================================
# 3. Risk Classification and Approval Manager Gating
# =========================================================================

def test_risk_classification():
    # Read-only is LOW
    assert classify_risk(ActionType.READ_TEMPO) == ActionRiskLevel.LOW
    assert classify_risk(ActionType.READ_CHANNELS) == ActionRiskLevel.LOW

    # Parameter tweaks are MEDIUM
    assert classify_risk(ActionType.SET_TEMPO, {"bpm": 128.0}) == ActionRiskLevel.MEDIUM
    assert classify_risk(ActionType.CREATE_MIDI_PATTERN) == ActionRiskLevel.MEDIUM

    # Export is HIGH
    assert classify_risk(ActionType.EXPORT_AUDIO) == ActionRiskLevel.HIGH

    # Explicit overwrite flag is DESTRUCTIVE
    assert classify_risk(ActionType.CREATE_MIDI_PATTERN, {"overwrite": True}) == ActionRiskLevel.DESTRUCTIVE


def test_approval_gating_and_approval_flow():
    mgr = ApprovalManager(safe_mode=True)

    # 1. Low risk action needs no approval
    low_act = ActionDefinition(
        action_id="act_low",
        task_id="task_1",
        action_type=ActionType.READ_TEMPO,
        risk_level=ActionRiskLevel.LOW,
    )
    assert mgr.check_and_gate_action(low_act) is True
    assert low_act.status == ActionLifecycleState.READY

    # 2. Destructive action MUST be gated
    dest_act = ActionDefinition(
        action_id="act_dest",
        task_id="task_1",
        action_type=ActionType.CREATE_MIDI_PATTERN,
        parameters={"overwrite": True},
        risk_level=ActionRiskLevel.DESTRUCTIVE,
    )
    can_run = mgr.check_and_gate_action(dest_act)
    assert can_run is False
    assert dest_act.status == ActionLifecycleState.AWAITING_APPROVAL
    assert mgr.is_action_executable(dest_act) is False

    # 3. User approves
    assert mgr.approve_action("act_dest") is True
    assert dest_act.status == ActionLifecycleState.READY
    assert mgr.is_action_executable(dest_act) is True


def test_approval_rejection_cancels_action():
    mgr = ApprovalManager(safe_mode=True)
    high_act = ActionDefinition(
        action_id="act_high_1",
        task_id="task_1",
        action_type=ActionType.EXPORT_AUDIO,
        risk_level=ActionRiskLevel.HIGH,
    )
    mgr.check_and_gate_action(high_act)
    assert high_act.status == ActionLifecycleState.AWAITING_APPROVAL

    # Reject
    assert mgr.reject_action("act_high_1", reason="User cancelled export") is True
    assert high_act.status == ActionLifecycleState.CANCELLED
    assert high_act.error == "User cancelled export"


# =========================================================================
# 4. Action Router & Capability Registry Tests
# =========================================================================

def test_router_selection_and_fallback():
    registry = CapabilityRegistry()
    router = ActionRouter(registry)

    # By default, SET_TEMPO prefers FL_MCP
    act = ActionDefinition(
        action_id="act_route_1",
        task_id="task_1",
        action_type=ActionType.SET_TEMPO,
    )
    route = router.route_action(act)
    assert route == "FL_MCP"

    # Disable FL_MCP route -> should fallback to GUI_AUTOMATION
    registry.set_route_active("FL_MCP", False)
    route_fallback = router.route_action(act)
    assert route_fallback == "GUI_AUTOMATION"

    # Disable GUI_AUTOMATION and MOCK -> no DAW route capable, should raise ValueError
    registry.set_route_active("GUI_AUTOMATION", False)
    registry.set_route_active("MOCK", False)
    with pytest.raises(ValueError, match="No integration route capable"):
        router.route_action(act)

    # Prefer mock routes to MOCK directly
    registry.set_route_active("MOCK", True)
    mock_route = router.route_action(act, prefer_mock=True)
    assert mock_route == "MOCK"


# =========================================================================
# 5. SQLite Persistence Tests
# =========================================================================

def test_database_persistence():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        db = DatabaseManager(db_path)

        # 1. Save and retrieve task
        db.save_task(
            task_id="task_test_1",
            prompt="Make 128 bpm techno",
            status="RUNNING",
            is_mock=True,
        )
        task_row = db.get_task("task_test_1")
        assert task_row is not None
        assert task_row["prompt"] == "Make 128 bpm techno"
        assert task_row["status"] == "RUNNING"
        assert task_row["is_mock"] == 1

        # 2. Save and retrieve action
        act = ActionDefinition(
            action_id="act_db_1",
            task_id="task_test_1",
            action_type=ActionType.SET_TEMPO,
            parameters={"bpm": 133.0},
            execution_route="FL_MCP",
            status=ActionLifecycleState.SUCCEEDED,
            verified=True,
            verification_detail="Verified 133.0 BPM readback",
        )
        db.save_action(act)
        loaded_act = db.get_action("act_db_1")
        assert loaded_act is not None
        assert loaded_act.action_type == ActionType.SET_TEMPO
        assert loaded_act.parameters == {"bpm": 133.0}
        assert loaded_act.status == ActionLifecycleState.SUCCEEDED
        assert loaded_act.verified is True

        # 3. Checkpoints
        db.save_checkpoint("chk_01", "Pre-edit snapshot", {"bpm": 130.0}, task_id="task_test_1")
        chk = db.get_checkpoint("chk_01")
        assert chk is not None
        assert chk["state"]["bpm"] == 130.0


# =========================================================================
# 6. Verification Engine Tests
# =========================================================================

def test_verification_engine_tempo():
    engine = VerificationEngine()
    act = ActionDefinition(
        action_id="act_v_1",
        task_id="t1",
        action_type=ActionType.SET_TEMPO,
        parameters={"bpm": 128.0, "tolerance": 0.05},
    )

    # Success case
    res_ok = engine.verify(act, post_state={"bpm": 128.0})
    assert res_ok.success is True
    assert res_ok.verified is True

    # Mismatch case
    res_mismatch = engine.verify(act, post_state={"bpm": 120.0})
    assert res_mismatch.success is False
    assert res_mismatch.verified is False
    assert res_mismatch.needs_recovery is True

    # Missing readback
    res_missing = engine.verify(act, post_state={})
    assert res_missing.success is False
    assert res_missing.error == "missing_post_bpm"


def test_verification_engine_export():
    engine = VerificationEngine()
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        # Write > 1KB dummy audio
        f.write(b"RIFF" + b"\x00" * 2000)
        temp_file = f.name

    try:
        act = ActionDefinition(
            action_id="act_v_exp",
            task_id="t1",
            action_type=ActionType.EXPORT_AUDIO,
            parameters={"output_path": temp_file},
        )
        outcome = engine.verify(act, post_state={"output_path": temp_file})
        assert outcome.success is True
        assert outcome.verified is True
    finally:
        if os.path.exists(temp_file):
            os.remove(temp_file)


# =========================================================================
# 7. Checkpoint & Recovery Manager Tests
# =========================================================================

def test_checkpoint_and_recovery_flow():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = DatabaseManager(Path(tmp_dir) / "test.db")
        rec_mgr = CheckpointRecoveryManager(db)

        # Create checkpoint before major edit
        chk_id = rec_mgr.create_checkpoint(
            name="Before Pattern Overwrite",
            state_snapshot={"channels": ["Kick", "Bass"], "bpm": 128.0},
            task_id="t_rec",
        )
        assert chk_id.startswith("chk_")

        # Action fails verification
        act = ActionDefinition(
            action_id="act_fail_1",
            task_id="t_rec",
            action_type=ActionType.SET_TEMPO,
            parameters={"bpm": 140.0},
            status=ActionLifecycleState.VERIFYING,
            error="bpm_mismatch",
        )
        plan = rec_mgr.handle_failed_action(act, checkpoint_id=chk_id)
        assert act.status == ActionLifecycleState.NEEDS_RECOVERY
        assert plan.can_auto_recover is True
        assert plan.checkpoint_id == chk_id
        assert len(plan.suggested_steps) > 0


# =========================================================================
# 8. Action Executor (Retries, Timeouts, and Cancellation)
# =========================================================================

@pytest.mark.asyncio
async def test_action_executor_successful_run():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = DatabaseManager(Path(tmp_dir) / "test.db")
        executor = ActionExecutor(db=db)

        act = ActionDefinition(
            action_id="act_exec_ok",
            task_id="task_exec",
            action_type=ActionType.SET_TEMPO,
            parameters={"bpm": 128.0},
        )
        result = await executor.execute_action(act, prefer_mock=True)
        assert result.status == ActionLifecycleState.SUCCEEDED
        assert result.verified is True

        # Check persistence
        loaded = db.get_action("act_exec_ok")
        assert loaded.status == ActionLifecycleState.SUCCEEDED


@pytest.mark.asyncio
async def test_action_executor_cancellation():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = DatabaseManager(Path(tmp_dir) / "test.db")
        executor = ActionExecutor(db=db)

        cancel_event = asyncio.Event()
        cancel_event.set()  # Already cancelled

        act = ActionDefinition(
            action_id="act_exec_cancel",
            task_id="task_exec",
            action_type=ActionType.CREATE_MIDI_PATTERN,
        )
        result = await executor.execute_action(act, cancel_event=cancel_event, prefer_mock=True)
        assert result.status == ActionLifecycleState.CANCELLED


@pytest.mark.asyncio
async def test_action_executor_timeout_and_retries():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = DatabaseManager(Path(tmp_dir) / "test.db")
        executor = ActionExecutor(db=db)

        # Register a handler that sleeps longer than action timeout
        async def slow_handler(action, pre_state):
            await asyncio.sleep(0.5)
            return {"bpm": 128.0}

        executor.register_handler(ActionType.SET_TEMPO.value, slow_handler)

        act = ActionDefinition(
            action_id="act_exec_timeout",
            task_id="task_exec",
            action_type=ActionType.SET_TEMPO,
            timeout_seconds=0.05,  # Very short timeout
            max_retries=1,
        )
        result = await executor.execute_action(act, prefer_mock=True)
        assert result.status == ActionLifecycleState.TIMED_OUT
        assert result.retry_count > 1
