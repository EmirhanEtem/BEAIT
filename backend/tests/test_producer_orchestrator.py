"""Unit tests for Producer Orchestrator and Safe Test Project Workflow."""

import asyncio
import pytest
from app.action_router.executor import ActionExecutor
from app.action_router.permissions import ApprovalManager
from app.database.persistence import DatabaseManager
from app.orchestration.producer import ProducerOrchestrator
from app.schemas.actions import ActionLifecycleState, ActionRiskLevel, ActionType


@pytest.fixture
def orchestrator(tmp_path):
    db_path = str(tmp_path / "test_orch.db")
    db = DatabaseManager(db_path=db_path)
    executor = ActionExecutor(db=db)
    return ProducerOrchestrator(executor=executor, db=db)


def test_plan_creation_tempo(orchestrator):
    plan = orchestrator.create_plan("Change tempo to 126.5 BPM")
    assert len(plan.actions) == 1
    act = plan.actions[0]
    assert act.action_type == ActionType.SET_TEMPO
    assert act.parameters["bpm"] == 126.5
    assert act.risk_level == ActionRiskLevel.MEDIUM


def test_plan_creation_drums(orchestrator):
    plan = orchestrator.create_plan("Create a four-on-the-floor drum beat")
    assert len(plan.actions) >= 2  # Kick and Clap actions
    assert all(a.action_type == ActionType.SET_STEP_GRID for a in plan.actions)
    kick_act = next(a for a in plan.actions if "kick" in a.description.lower())
    assert kick_act.parameters["steps"] == [0, 4, 8, 12]


def test_plan_creation_mixer(orchestrator):
    plan = orchestrator.create_plan("Set track 2 volume to -3.5 dB")
    assert len(plan.actions) == 1
    act = plan.actions[0]
    assert act.action_type == ActionType.SET_MIXER_VOLUME
    assert act.parameters["track"] == 2
    assert act.parameters["value"] == -3.5
    assert act.parameters["unit"] == "db"


def test_plan_creation_default_inspection(orchestrator):
    plan = orchestrator.create_plan("What is in my project right now?")
    assert len(plan.actions) == 2
    types = [a.action_type for a in plan.actions]
    assert ActionType.READ_PROJECT_STATE in types
    assert ActionType.READ_CHANNELS in types


@pytest.mark.asyncio
async def test_plan_dry_run_mode(orchestrator):
    plan = orchestrator.create_plan("Set tempo to 140 BPM", dry_run=True)
    assert plan.dry_run is True

    result = await orchestrator.execute_plan(plan, prefer_mock=True)
    assert result.success is True
    assert result.actions_executed == 0
    assert result.details[0]["status"] == "DRY_RUN_PREVIEW"


@pytest.mark.asyncio
async def test_plan_execution_mock_success(orchestrator):
    plan = orchestrator.create_plan("Set tempo to 132 BPM")
    result = await orchestrator.execute_plan(plan, prefer_mock=True)

    assert result.success is True
    assert result.actions_executed == 1
    assert result.actions_succeeded == 1
    assert result.details[0]["status"] == ActionLifecycleState.SUCCEEDED.value


@pytest.mark.asyncio
async def test_plan_execution_approval_gating(tmp_path):
    db_path = str(tmp_path / "test_approval.db")
    db = DatabaseManager(db_path=db_path)
    approval_mgr = ApprovalManager(safe_mode=True)
    executor = ActionExecutor(db=db, approval_manager=approval_mgr)
    orch = ProducerOrchestrator(executor=executor, db=db)

    # Action requiring approval (HIGH risk or destructive)
    plan = orch.create_plan("Set tempo to 128")
    plan.actions[0].action_type = ActionType.EXPORT_AUDIO
    plan.actions[0].parameters = {"output_path": "render.wav"}

    result = await orch.execute_plan(plan, prefer_mock=True)
    assert result.actions_awaiting_approval == 1
    assert result.details[0]["status"] == ActionLifecycleState.AWAITING_APPROVAL.value


@pytest.mark.asyncio
async def test_plan_execution_cancellation(orchestrator):
    plan = orchestrator.create_plan("Set tempo to 125 BPM")
    cancel_event = asyncio.Event()
    cancel_event.set()  # Cancelled before start

    result = await orchestrator.execute_plan(plan, cancel_event=cancel_event, prefer_mock=True)
    assert result.actions_succeeded == 0
