"""Risk classification and user approval permission management."""

from __future__ import annotations

import logging
from typing import Dict, Optional, Set
from ..schemas.actions import ActionDefinition, ActionLifecycleState, ActionRiskLevel, ActionType

logger = logging.getLogger(__name__)


def classify_risk(action_type: ActionType, parameters: Optional[dict] = None) -> ActionRiskLevel:
    """Deterministic risk classification rule engine."""
    params = parameters or {}

    # 1. Destructive actions
    if params.get("overwrite", False) or params.get("destructive", False):
        return ActionRiskLevel.DESTRUCTIVE

    # 2. High risk actions
    if action_type in (
        ActionType.EXPORT_AUDIO,
        ActionType.RESTORE_PROJECT_CHECKPOINT,
    ):
        return ActionRiskLevel.HIGH

    # 3. Medium risk actions (nondestructive modifications)
    if action_type in (
        ActionType.SET_TEMPO,
        ActionType.SET_PLAY_STATE,
        ActionType.CREATE_MIDI_PATTERN,
        ActionType.CREATE_DRUM_PATTERN,
        ActionType.SET_CHANNEL_VOLUME,
        ActionType.SET_CHANNEL_PAN,
        ActionType.SET_MIXER_VOLUME,
        ActionType.SET_MIXER_PAN,
        ActionType.SET_MIXER_MUTE,
        ActionType.SET_MIXER_SOLO,
        ActionType.LOAD_PLUGIN_PRESET,
        ActionType.LOAD_MIXER_EFFECT,
        ActionType.SET_PLUGIN_PARAM,
        ActionType.SET_MIXER_ROUTING,
        ActionType.SET_MIXER_TRACK_META,
        ActionType.AUTO_MIX_MASTER,
        ActionType.OPEN_PLUGIN_WINDOW,
        ActionType.CREATE_PROJECT_CHECKPOINT,
    ):
        return ActionRiskLevel.MEDIUM

    # 4. Low risk (Read-only, inspection, screenshots)
    return ActionRiskLevel.LOW


class ApprovalManager:
    """Tracks and gates actions requiring explicit user permission."""

    def __init__(self, safe_mode: bool = True):
        self.safe_mode = safe_mode
        self._pending_approvals: Dict[str, ActionDefinition] = {}
        self._approved_actions: Set[str] = set()
        self._rejected_actions: Set[str] = set()

    def check_and_gate_action(self, action: ActionDefinition) -> bool:
        """Determines if the action requires approval.
        
        If approval is required, transitions status to AWAITING_APPROVAL and returns False.
        If no approval is required, transitions status to READY and returns True.
        """
        # Always require approval for DESTRUCTIVE actions
        # Require approval for HIGH risk when safe_mode is active
        # Or if explicitly marked requires_approval
        needs_approval = (
            action.risk_level == ActionRiskLevel.DESTRUCTIVE
            or (self.safe_mode and action.risk_level == ActionRiskLevel.HIGH)
            or action.requires_approval
        )

        if needs_approval and action.action_id not in self._approved_actions:
            action.requires_approval = True
            action.transition_to(ActionLifecycleState.AWAITING_APPROVAL)
            self._pending_approvals[action.action_id] = action
            logger.info("Action %s gated: requires user approval (Risk: %s)", action.action_id, action.risk_level)
            return False

        # If already approved or not needed
        if action.status == ActionLifecycleState.PLANNED:
            action.transition_to(ActionLifecycleState.READY)
        elif action.status == ActionLifecycleState.AWAITING_APPROVAL and action.action_id in self._approved_actions:
            action.transition_to(ActionLifecycleState.READY)

        return True

    def approve_action(self, action_id: str) -> bool:
        """User explicitly grants approval for a gated action."""
        if action_id in self._pending_approvals:
            action = self._pending_approvals.pop(action_id)
            self._approved_actions.add(action_id)
            action.transition_to(ActionLifecycleState.READY)
            logger.info("Action %s approved by user. Transitioned to READY.", action_id)
            return True
        return False

    def reject_action(self, action_id: str, reason: str = "User denied approval") -> bool:
        """User explicitly rejects a gated action."""
        if action_id in self._pending_approvals:
            action = self._pending_approvals.pop(action_id)
            self._rejected_actions.add(action_id)
            action.error = reason
            action.transition_to(ActionLifecycleState.CANCELLED)
            logger.info("Action %s rejected by user: %s", action_id, reason)
            return True
        return False

    def is_action_executable(self, action: ActionDefinition) -> bool:
        """Ensures an action cannot execute while in AWAITING_APPROVAL."""
        if action.status == ActionLifecycleState.AWAITING_APPROVAL:
            return False
        return action.status in (ActionLifecycleState.READY, ActionLifecycleState.RUNNING)

