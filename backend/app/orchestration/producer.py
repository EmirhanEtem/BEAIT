"""Producer Orchestrator — Central coordination of user intent, planning, and execution.

Converts musical and DAW commands into typed Action plans, handles dry runs,
enforces safety/approval gating, and coordinates execution with verification.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from ..action_router.executor import ActionExecutor
from ..action_router.permissions import classify_risk
from ..database.persistence import DatabaseManager
from ..integrations.fl_studio.adapter import FLStudioAdapter
from ..music_engine.generator import generate_drum_pattern
from ..schemas.actions import (
    ActionDefinition,
    ActionLifecycleState,
    ActionRiskLevel,
    ActionType,
)

logger = logging.getLogger(__name__)


@dataclass
class ActionPlan:
    """An ordered list of typed actions to achieve a user's musical intent."""
    plan_id: str
    task_id: str
    prompt: str
    actions: List[ActionDefinition] = field(default_factory=list)
    dry_run: bool = False
    requires_approval: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class PlanExecutionResult:
    """Summary of plan execution outcomes."""
    plan_id: str
    task_id: str
    success: bool
    actions_executed: int
    actions_succeeded: int
    actions_failed: int
    actions_awaiting_approval: int
    details: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None


class ProducerOrchestrator:
    """Coordinates natural intent parsing, plan creation, gating, and execution."""

    def __init__(
        self,
        executor: Optional[ActionExecutor] = None,
        fl_adapter: Optional[FLStudioAdapter] = None,
        db: Optional[DatabaseManager] = None,
        event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self.db = db or DatabaseManager()
        self.fl_adapter = fl_adapter
        self.executor = executor or ActionExecutor(db=self.db, fl_adapter=fl_adapter)
        self.event_callback = event_callback

    def create_plan(
        self,
        prompt: str,
        task_id: Optional[str] = None,
        dry_run: bool = False,
    ) -> ActionPlan:
        """Parse natural language command and produce a structured ActionPlan."""
        t_id = task_id or f"task_{uuid.uuid4().hex[:8]}"
        p_id = f"plan_{uuid.uuid4().hex[:8]}"
        clean = prompt.strip().lower()

        actions: List[ActionDefinition] = []

        # 1. Parse BPM / Tempo commands
        bpm_match = re.search(r"(?:set|change)?\s*(?:tempo|bpm)\s*(?:to|=)?\s*(\d+(?:\.\d+)?)", clean)
        if bpm_match:
            bpm_val = float(bpm_match.group(1))
            actions.append(
                ActionDefinition(
                    task_id=t_id,
                    action_type=ActionType.SET_TEMPO,
                    description=f"Change project tempo to {bpm_val} BPM",
                    parameters={"bpm": bpm_val, "tolerance": 0.05},
                    risk_level=ActionRiskLevel.MEDIUM,
                )
            )

        # 2. Parse Drum Pattern commands
        elif any(k in clean for k in ("drum", "beat", "kick", "4-on-the-floor", "four on the floor", "house beat", "trap beat")):
            style = "four_on_the_floor"
            if "trap" in clean:
                style = "trap"
            elif "boom bap" in clean or "boombap" in clean:
                style = "boom_bap"
            elif "techno" in clean:
                style = "techno"

            dp = generate_drum_pattern(style=style, length=16)
            for ch in dp.channels:
                if ch.steps:  # only create actions for active channels
                    # Determine target channel index if named
                    ch_idx = 0
                    if "kick" in ch.channel_name.lower():
                        ch_idx = 0
                    elif "clap" in ch.channel_name.lower():
                        ch_idx = 1
                    elif "hihat" in ch.channel_name.lower() or "hat" in ch.channel_name.lower():
                        ch_idx = 2
                    elif "snare" in ch.channel_name.lower():
                        ch_idx = 3

                    actions.append(
                        ActionDefinition(
                            task_id=t_id,
                            action_type=ActionType.SET_STEP_GRID,
                            description=f"Set {ch.channel_name} step grid ({style}): {ch.pattern_string}",
                            parameters={
                                "channel": ch_idx,
                                "steps": ch.steps,
                                "pattern": ch.pattern_string,
                                "length": ch.length,
                            },
                            risk_level=ActionRiskLevel.MEDIUM,
                        )
                    )

        # 3. Parse Mixer commands
        elif "mixer" in clean or "volume" in clean:
            vol_match = re.search(r"(?:track|mixer)\s*(\d+).*?(?:volume|vol).*?(-?\d+(?:\.\d+)?)", clean)
            if vol_match:
                track_idx = int(vol_match.group(1))
                val = float(vol_match.group(2))
                unit = "db" if "db" in clean else "normalized"
                actions.append(
                    ActionDefinition(
                        task_id=t_id,
                        action_type=ActionType.SET_MIXER_VOLUME,
                        description=f"Set mixer track {track_idx} volume to {val} ({unit})",
                        parameters={"track": track_idx, "value": val, "unit": unit},
                        risk_level=ActionRiskLevel.MEDIUM,
                    )
                )

        # 4. Parse Transport commands
        elif "play" in clean:
            actions.append(
                ActionDefinition(
                    task_id=t_id,
                    action_type=ActionType.SET_PLAY_STATE,
                    description="Start FL Studio transport playback",
                    parameters={"state": "play"},
                    risk_level=ActionRiskLevel.LOW,
                )
            )
        elif "stop" in clean:
            actions.append(
                ActionDefinition(
                    task_id=t_id,
                    action_type=ActionType.SET_PLAY_STATE,
                    description="Stop FL Studio transport playback",
                    parameters={"state": "stop"},
                    risk_level=ActionRiskLevel.LOW,
                )
            )

        # 5. Default: Context read / inspection
        if not actions:
            actions.append(
                ActionDefinition(
                    task_id=t_id,
                    action_type=ActionType.READ_PROJECT_STATE,
                    description="Read current FL Studio project state",
                    parameters={},
                    risk_level=ActionRiskLevel.LOW,
                )
            )
            actions.append(
                ActionDefinition(
                    task_id=t_id,
                    action_type=ActionType.READ_CHANNELS,
                    description="Read FL Studio channel rack channels",
                    parameters={},
                    risk_level=ActionRiskLevel.LOW,
                )
            )

        # Check if any action requires approval
        requires_approval = any(
            a.risk_level in (ActionRiskLevel.HIGH, ActionRiskLevel.DESTRUCTIVE)
            for a in actions
        )

        return ActionPlan(
            plan_id=p_id,
            task_id=t_id,
            prompt=prompt,
            actions=actions,
            dry_run=dry_run,
            requires_approval=requires_approval,
        )

    async def execute_plan(
        self,
        plan: ActionPlan,
        cancel_event: Optional[asyncio.Event] = None,
        prefer_mock: bool = False,
    ) -> PlanExecutionResult:
        """Execute all actions in the plan sequentially with verification and safety checks."""
        logger.info("Executing plan %s (dry_run=%s, actions=%d)", plan.plan_id, plan.dry_run, len(plan.actions))

        if plan.dry_run:
            logger.info("Dry run requested; plan generated without executing DAW mutations.")
            return PlanExecutionResult(
                plan_id=plan.plan_id,
                task_id=plan.task_id,
                success=True,
                actions_executed=0,
                actions_succeeded=0,
                actions_failed=0,
                actions_awaiting_approval=0,
                details=[{"action_id": a.action_id, "type": a.action_type, "desc": a.description, "status": "DRY_RUN_PREVIEW"} for a in plan.actions],
            )

        succeeded = 0
        failed = 0
        awaiting = 0
        details: List[Dict[str, Any]] = []

        for action in plan.actions:
            if cancel_event and cancel_event.is_set():
                logger.info("Plan execution cancelled by user event.")
                action.transition_to(ActionLifecycleState.CANCELLED)
                break

            executed_action = await self.executor.execute_action(
                action,
                cancel_event=cancel_event,
                prefer_mock=prefer_mock,
            )

            status = executed_action.status
            details.append({
                "action_id": executed_action.action_id,
                "action_type": executed_action.action_type.value,
                "status": status.value,
                "verified": executed_action.verified,
                "verification_detail": executed_action.verification_detail,
                "error": executed_action.error,
            })

            if status == ActionLifecycleState.SUCCEEDED:
                succeeded += 1
            elif status == ActionLifecycleState.AWAITING_APPROVAL:
                awaiting += 1
                logger.info("Action %s requires approval; halting subsequent plan steps.", action.action_id)
                break
            else:
                failed += 1
                logger.warning("Action %s failed with status %s; halting plan.", action.action_id, status)
                break

        overall_success = (failed == 0 and awaiting == 0)
        return PlanExecutionResult(
            plan_id=plan.plan_id,
            task_id=plan.task_id,
            success=overall_success,
            actions_executed=succeeded + failed + awaiting,
            actions_succeeded=succeeded,
            actions_failed=failed,
            actions_awaiting_approval=awaiting,
            details=details,
        )
