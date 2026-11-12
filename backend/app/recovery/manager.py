"""Checkpoint and safe recovery manager."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from ..database.persistence import DatabaseManager
from ..schemas.actions import ActionDefinition, ActionLifecycleState

logger = logging.getLogger(__name__)


@dataclass
class RecoveryPlan:
    action_id: str
    checkpoint_id: Optional[str]
    suggested_steps: list[str]
    can_auto_recover: bool


class CheckpointRecoveryManager:
    """Manages project state snapshots, checkpoints, and safe failure recovery."""

    def __init__(self, db: Optional[DatabaseManager] = None):
        self.db = db or DatabaseManager()
        self._active_checkpoints: Dict[str, dict] = {}

    def create_checkpoint(self, name: str, state_snapshot: dict, task_id: Optional[str] = None) -> str:
        """Captures a snapshot of the current project state before risky changes."""
        checkpoint_id = f"chk_{uuid.uuid4().hex[:8]}"
        data = {
            "checkpoint_id": checkpoint_id,
            "name": name,
            "task_id": task_id,
            "state": state_snapshot,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._active_checkpoints[checkpoint_id] = data
        self.db.save_checkpoint(checkpoint_id, name, state_snapshot, task_id)
        logger.info("Project checkpoint created: %s (%s)", checkpoint_id, name)
        return checkpoint_id

    def get_checkpoint(self, checkpoint_id: str) -> Optional[dict]:
        return self._active_checkpoints.get(checkpoint_id) or self.db.get_checkpoint(checkpoint_id)

    def handle_failed_action(
        self,
        action: ActionDefinition,
        checkpoint_id: Optional[str] = None,
    ) -> RecoveryPlan:
        """Transitions action to NEEDS_RECOVERY and produces a safe recovery plan."""
        action.transition_to(ActionLifecycleState.NEEDS_RECOVERY)
        logger.warning(
            "Action %s failed verification and transitioned to NEEDS_RECOVERY (error: %s)",
            action.action_id,
            action.error,
        )

        steps = []
        can_auto_recover = False

        if checkpoint_id and self.get_checkpoint(checkpoint_id):
            steps.append(f"Restore initial project snapshot from checkpoint {checkpoint_id}")
            can_auto_recover = True
        else:
            steps.append("Halt execution sequence safely.")
            steps.append("Present failure reason to user without executing unverified rollback commands.")

        return RecoveryPlan(
            action_id=action.action_id,
            checkpoint_id=checkpoint_id,
            suggested_steps=steps,
            can_auto_recover=can_auto_recover,
        )

