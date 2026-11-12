"""Action Executor: Orchestrates routing, approvals, execution, retries, verification, and persistence."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
from typing import Any, Callable, Dict, Optional

from ..database.persistence import DatabaseManager
from ..recovery.manager import CheckpointRecoveryManager
from ..schemas.actions import (
    ActionDefinition,
    ActionLifecycleState,
    ActionRiskLevel,
    ActionType,
)
from ..verification.engine import VerificationEngine
from .capabilities import CapabilityRegistry
from .permissions import ApprovalManager, classify_risk
from .router import ActionRouter

logger = logging.getLogger(__name__)


class ActionExecutor:
    """Executes a single action safely according to the strict action protocol."""

    def __init__(
        self,
        router: Optional[ActionRouter] = None,
        approval_manager: Optional[ApprovalManager] = None,
        verification_engine: Optional[VerificationEngine] = None,
        db: Optional[DatabaseManager] = None,
        recovery_manager: Optional[CheckpointRecoveryManager] = None,
    ):
        self.registry = CapabilityRegistry()
        self.router = router or ActionRouter(self.registry)
        self.approval_manager = approval_manager or ApprovalManager(safe_mode=True)
        self.verification_engine = verification_engine or VerificationEngine()
        self.db = db or DatabaseManager()
        self.recovery_manager = recovery_manager or CheckpointRecoveryManager(self.db)
        
        # Dispatchers for mock or integration execution handlers
        self._custom_handlers: Dict[str, Callable] = {}

    def register_handler(self, route_or_type: str, handler: Callable):
        self._custom_handlers[route_or_type] = handler

    async def execute_action(
        self,
        action: ActionDefinition,
        pre_state: Optional[Dict[str, Any]] = None,
        checkpoint_id: Optional[str] = None,
        cancel_event: Optional[asyncio.Event] = None,
        prefer_mock: bool = False,
    ) -> ActionDefinition:
        """Executes the action through the complete lifecycle."""
        # 1. Classify Risk
        action.risk_level = classify_risk(action.action_type, action.parameters)

        # 2. Gate with Approval Manager
        allowed_to_run = self.approval_manager.check_and_gate_action(action)
        self.db.save_action(action)

        if not allowed_to_run:
            logger.info("Action %s is awaiting approval; halting execution.", action.action_id)
            return action

        # 3. Route Action
        self.router.route_action(action, prefer_mock=prefer_mock)
        self.db.save_action(action)

        # Check for immediate cancellation before start
        if cancel_event and cancel_event.is_set():
            action.transition_to(ActionLifecycleState.CANCELLED)
            self.db.save_action(action)
            return action

        # 4. Transition to RUNNING
        action.transition_to(ActionLifecycleState.RUNNING)
        self.db.save_action(action)

        # 5. Execution loop with bounded retries and timeout
        post_state: Dict[str, Any] = {}
        execution_succeeded = False

        while action.retry_count <= action.max_retries and not execution_succeeded:
            if cancel_event and cancel_event.is_set():
                action.transition_to(ActionLifecycleState.CANCELLED)
                self.db.save_action(action)
                return action

            try:
                # Execute inside bounded timeout
                async with asyncio.timeout(action.timeout_seconds):
                    post_state = await self._dispatch_execution(action, pre_state, cancel_event)
                execution_succeeded = True

            except asyncio.TimeoutError:
                logger.warning(
                    "Action %s timed out after %.1f s (attempt %d/%d)",
                    action.action_id,
                    action.timeout_seconds,
                    action.retry_count + 1,
                    action.max_retries + 1,
                )
                action.retry_count += 1
                if action.retry_count > action.max_retries:
                    action.error = f"Execution timed out after {action.timeout_seconds}s."
                    action.transition_to(ActionLifecycleState.TIMED_OUT)
                    self.db.save_action(action)
                    return action

            except Exception as e:
                logger.warning(
                    "Action %s failed on attempt %d: %s",
                    action.action_id,
                    action.retry_count + 1,
                    e,
                )
                action.retry_count += 1
                if action.retry_count > action.max_retries:
                    action.error = str(e)
                    break
                await asyncio.sleep(0.1)

        # 6. Verification Phase
        if cancel_event and cancel_event.is_set():
            action.transition_to(ActionLifecycleState.CANCELLED)
            self.db.save_action(action)
            return action

        action.transition_to(ActionLifecycleState.VERIFYING)
        self.db.save_action(action)

        outcome = self.verification_engine.verify(action, pre_state=pre_state, post_state=post_state)
        action.verified = outcome.verified
        action.verification_detail = outcome.detail

        if outcome.success and (outcome.verified or not outcome.needs_recovery):
            action.transition_to(ActionLifecycleState.SUCCEEDED)
            logger.info("Action %s succeeded and verified: %s", action.action_id, outcome.detail)
        else:
            action.error = outcome.error or outcome.detail
            if outcome.needs_recovery:
                self.recovery_manager.handle_failed_action(action, checkpoint_id=checkpoint_id)
            else:
                action.transition_to(ActionLifecycleState.FAILED)
            logger.warning("Action %s failed verification: %s", action.action_id, action.error)

        self.db.save_action(action)
        return action

    async def _dispatch_execution(
        self,
        action: ActionDefinition,
        pre_state: Optional[Dict[str, Any]],
        cancel_event: Optional[asyncio.Event],
    ) -> Dict[str, Any]:
        """Dispatches action to the handler corresponding to its route or registered handler."""
        # 1. Custom registered handler
        if action.action_type.value in self._custom_handlers:
            handler = self._custom_handlers[action.action_type.value]
            return await handler(action, pre_state)
        if action.execution_route in self._custom_handlers:
            handler = self._custom_handlers[action.execution_route]
            return await handler(action, pre_state)

        # 2. Mock handler
        if action.execution_route == "MOCK":
            return await self._mock_execution(action, cancel_event)

        # Default fallback execution result
        return {"result": "executed", "timestamp": datetime.now(timezone.utc).isoformat()}

    async def _mock_execution(
        self,
        action: ActionDefinition,
        cancel_event: Optional[asyncio.Event],
    ) -> Dict[str, Any]:
        """Deterministic mock handler simulating action latency."""
        for _ in range(5):
            if cancel_event and cancel_event.is_set():
                break
            await asyncio.sleep(0.02)

        # Provide matching response fields for verification
        if action.action_type == ActionType.SET_TEMPO:
            return {"bpm": action.parameters.get("bpm", 128.0)}
        elif action.action_type in (ActionType.CREATE_MIDI_PATTERN, ActionType.CREATE_DRUM_PATTERN):
            return {"pattern": {"length_bars": 4, "notes_count": 16}}
        elif action.action_type in (ActionType.SET_MIXER_VOLUME, ActionType.SET_MIXER_PAN):
            param = "volume" if action.action_type == ActionType.SET_MIXER_VOLUME else "pan"
            return {param: action.parameters.get(param, 0.8)}
        elif action.action_type == ActionType.EXPORT_AUDIO:
            return {"output_path": action.parameters.get("output_path", "test.wav")}

        return {"data": "mock_data", "action_id": action.action_id}

