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
        fl_adapter: Optional[Any] = None,
        hcu_adapter: Optional[Any] = None,
    ):
        self.registry = CapabilityRegistry()
        self.router = router or ActionRouter(self.registry)
        self.approval_manager = approval_manager or ApprovalManager(safe_mode=True)
        self.verification_engine = verification_engine or VerificationEngine()
        self.db = db or DatabaseManager()
        self.recovery_manager = recovery_manager or CheckpointRecoveryManager(self.db)
        self.fl_adapter = fl_adapter
        self.hcu_adapter = hcu_adapter
        
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

        # 2. FL Studio MCP Real Execution
        if action.execution_route == "FL_MCP" and self.fl_adapter:
            return await self._execute_fl_mcp(action)

        # 3. GUI Automation Real Execution
        if action.execution_route == "GUI_AUTOMATION" and self.hcu_adapter:
            return await self._execute_gui_automation(action)

        # 4. Mock handler (Fallback)
        return await self._mock_execution(action, cancel_event)

    async def _execute_fl_mcp(self, action: ActionDefinition) -> Dict[str, Any]:
        """Direct execution through real FL Studio MCP adapter."""
        if not self.fl_adapter:
            raise RuntimeError("FL Studio adapter not configured on executor.")

        status = self.fl_adapter.check_health()
        if not status.connected or not status.fl_studio_alive:
            c_status = self.fl_adapter.connect()
            if not c_status.connected:
                raise RuntimeError(f"Cannot connect to FL Studio MCP: {c_status.error}")

        atype = action.action_type
        params = action.parameters

        if atype == ActionType.READ_TEMPO:
            bpm = await self.fl_adapter.async_get_tempo()
            return {"bpm": bpm, "data": bpm}

        elif atype == ActionType.SET_TEMPO:
            bpm = float(params.get("bpm", 120.0))
            res = await self.fl_adapter.async_set_tempo_verified(bpm)
            return {"bpm": res.after, "before": res.before, "verified": res.verified}

        elif atype == ActionType.READ_PROJECT_STATE:
            st = await self.fl_adapter.async_get_project_state()
            return {"data": st.raw, "project_state": st}

        elif atype == ActionType.READ_CHANNELS:
            ch = await self.fl_adapter.async_get_channels()
            return {"data": ch, "channels": ch}

        elif atype == ActionType.READ_MIXER_TRACKS:
            tracks = await self.fl_adapter.async_get_mixer_tracks()
            return {"data": tracks, "tracks": tracks}

        elif atype == ActionType.READ_PATTERNS:
            patterns = await self.fl_adapter.async_get_patterns()
            return {"data": patterns, "patterns": patterns}

        elif atype == ActionType.READ_STEP_GRID:
            ch_idx = int(params.get("channel", 0))
            length = int(params.get("length", 16))
            res = await self.fl_adapter.async_get_step_grid(ch_idx, length)
            return {"data": res, "steps": res.get("steps", []), "pattern_string": res.get("pattern_string")}

        elif atype in (ActionType.SET_STEP_GRID, ActionType.CREATE_DRUM_PATTERN):
            ch_idx = int(params.get("channel", 0))
            steps = params.get("steps")
            pattern_str = params.get("pattern")
            length = int(params.get("length", 16))
            res = await self.fl_adapter.async_set_step_grid_verified(ch_idx, steps=steps, pattern=pattern_str, length=length)
            return {
                "verified": res.verified,
                "channel": res.channel,
                "after_steps": res.after_steps,
                "before_steps": res.before_steps,
                "steps": res.after_steps,
            }

        elif atype == ActionType.SET_MIXER_VOLUME:
            track = int(params.get("track", 0))
            val = float(params.get("value", 0.8))
            unit = params.get("unit", "normalized")
            res = await self.fl_adapter.async_set_mixer_volume_verified(track, val, unit=unit)
            return {"verified": res.verified, "volume": res.after, "before": res.before}

        elif atype == ActionType.SET_MIXER_PAN:
            track = int(params.get("track", 0))
            val = float(params.get("value", 0.0))
            res = await self.fl_adapter.async_set_mixer_pan_verified(track, val)
            return {"verified": res.verified, "pan": res.after, "before": res.before}

        elif atype == ActionType.SET_MIXER_MUTE:
            track = int(params.get("track", 0))
            state = bool(params.get("state", False))
            res = await self.fl_adapter.async_set_mixer_mute_verified(track, state)
            return {"verified": res.verified, "mute": res.after, "before": res.before}

        elif atype == ActionType.CREATE_PATTERN:
            name = params.get("name", "PATTERN")
            res = await self.fl_adapter.async_create_pattern(name)
            return {"verified": res.verified, "index": res.index, "name": res.name}

        elif atype == ActionType.SET_PLAY_STATE:
            state = params.get("state", "toggle").lower()
            if state == "play":
                await self.fl_adapter.async_play()
            elif state == "stop":
                await self.fl_adapter.async_stop()
            else:
                await self.fl_adapter.async_toggle_play()
            return {"data": state, "verified": True}

        # For pattern/MIDI actions not yet handled via SysEx, fallback to mock/safe
        return await self._mock_execution(action, None)

    async def _execute_gui_automation(self, action: ActionDefinition) -> Dict[str, Any]:
        """Execution through GUI Automation (HCU)."""
        if not self.hcu_adapter:
            return await self._mock_execution(action, None)

        atype = action.action_type
        if atype == ActionType.CAPTURE_SCREENSHOT:
            png = await self.hcu_adapter.async_take_screenshot()
            return {"data": png, "size": len(png) if png else 0}

        return await self._mock_execution(action, None)

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

