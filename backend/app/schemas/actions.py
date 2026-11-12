"""Typed Action schemas, allowlist, and lifecycle definitions."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field, field_validator


class ActionType(str, Enum):
    """Strict allowlist of supported actions. Arbitrary commands/shell execution are disallowed."""
    # Transport & Project Context (Read)
    READ_TEMPO = "READ_TEMPO"
    READ_PLAY_STATE = "READ_PLAY_STATE"
    READ_PROJECT_STATE = "READ_PROJECT_STATE"
    READ_CHANNELS = "READ_CHANNELS"
    READ_MIXER_TRACKS = "READ_MIXER_TRACKS"
    READ_PATTERNS = "READ_PATTERNS"

    # Nondestructive / Controlled Edits
    SET_TEMPO = "SET_TEMPO"
    SET_PLAY_STATE = "SET_PLAY_STATE"
    CREATE_MIDI_PATTERN = "CREATE_MIDI_PATTERN"
    CREATE_DRUM_PATTERN = "CREATE_DRUM_PATTERN"
    SET_STEP_GRID = "SET_STEP_GRID"
    READ_STEP_GRID = "READ_STEP_GRID"
    CREATE_PATTERN = "CREATE_PATTERN"
    CLONE_PATTERN = "CLONE_PATTERN"
    ADD_ARRANGEMENT_MARKER = "ADD_ARRANGEMENT_MARKER"
    SET_CHANNEL_VOLUME = "SET_CHANNEL_VOLUME"
    SET_CHANNEL_PAN = "SET_CHANNEL_PAN"
    SET_MIXER_VOLUME = "SET_MIXER_VOLUME"
    SET_MIXER_PAN = "SET_MIXER_PAN"
    SET_MIXER_MUTE = "SET_MIXER_MUTE"
    SET_MIXER_SOLO = "SET_MIXER_SOLO"

    # GUI Actions (Controlled targets)
    OPEN_PLUGIN_WINDOW = "OPEN_PLUGIN_WINDOW"
    LOAD_PLUGIN_PRESET = "LOAD_PLUGIN_PRESET"
    CAPTURE_SCREENSHOT = "CAPTURE_SCREENSHOT"

    # Local Filesystem & Analysis
    SCAN_SAMPLE_DIRECTORY = "SCAN_SAMPLE_DIRECTORY"
    ANALYZE_AUDIO_FILE = "ANALYZE_AUDIO_FILE"

    # Safe Project Management
    CREATE_PROJECT_CHECKPOINT = "CREATE_PROJECT_CHECKPOINT"
    RESTORE_PROJECT_CHECKPOINT = "RESTORE_PROJECT_CHECKPOINT"

    # Export
    EXPORT_AUDIO = "EXPORT_AUDIO"


class ActionRiskLevel(str, Enum):
    LOW = "LOW"             # Read-only or completely benign actions
    MEDIUM = "MEDIUM"       # Reversible changes, nondestructive (e.g. tempo change with restore)
    HIGH = "HIGH"           # Edits that modify project arrangements or render audio
    DESTRUCTIVE = "DESTRUCTIVE"  # Overwrite existing files/patterns, delete clips, reset project


class ActionLifecycleState(str, Enum):
    PLANNED = "PLANNED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    READY = "READY"
    RUNNING = "RUNNING"
    VERIFYING = "VERIFYING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    NEEDS_RECOVERY = "NEEDS_RECOVERY"
    CANCELLED = "CANCELLED"
    SKIPPED = "SKIPPED"
    TIMED_OUT = "TIMED_OUT"


# Allowed state transitions according to Section 5.4 of specification
VALID_STATE_TRANSITIONS: Dict[ActionLifecycleState, List[ActionLifecycleState]] = {
    ActionLifecycleState.PLANNED: [
        ActionLifecycleState.AWAITING_APPROVAL,
        ActionLifecycleState.READY,
        ActionLifecycleState.CANCELLED,
        ActionLifecycleState.SKIPPED,
    ],
    ActionLifecycleState.AWAITING_APPROVAL: [
        ActionLifecycleState.READY,
        ActionLifecycleState.CANCELLED,
        ActionLifecycleState.SKIPPED,
    ],
    ActionLifecycleState.READY: [
        ActionLifecycleState.RUNNING,
        ActionLifecycleState.CANCELLED,
        ActionLifecycleState.SKIPPED,
    ],
    ActionLifecycleState.RUNNING: [
        ActionLifecycleState.VERIFYING,
        ActionLifecycleState.SUCCEEDED,
        ActionLifecycleState.FAILED,
        ActionLifecycleState.CANCELLED,
        ActionLifecycleState.TIMED_OUT,
    ],
    ActionLifecycleState.VERIFYING: [
        ActionLifecycleState.SUCCEEDED,
        ActionLifecycleState.FAILED,
        ActionLifecycleState.NEEDS_RECOVERY,
        ActionLifecycleState.CANCELLED,
    ],
    ActionLifecycleState.NEEDS_RECOVERY: [
        ActionLifecycleState.READY,
        ActionLifecycleState.FAILED,
        ActionLifecycleState.CANCELLED,
    ],
    # Terminal states
    ActionLifecycleState.SUCCEEDED: [],
    ActionLifecycleState.FAILED: [],
    ActionLifecycleState.CANCELLED: [],
    ActionLifecycleState.SKIPPED: [],
    ActionLifecycleState.TIMED_OUT: [],
}


def is_valid_transition(current: ActionLifecycleState, next_state: ActionLifecycleState) -> bool:
    """Check if state transition is allowed."""
    return next_state in VALID_STATE_TRANSITIONS.get(current, [])


class ActionDefinition(BaseModel):
    """Complete specification of a typed, verifiable action."""
    action_id: str = Field(default_factory=lambda: f"act_{uuid.uuid4().hex[:10]}")
    task_id: str
    action_type: ActionType
    target: str = ""
    description: str = ""
    parameters: Dict[str, Any] = Field(default_factory=dict)
    execution_route: str = "FL_MCP"  # FL_MCP, GUI_AUTOMATION, LOCAL_SERVICE, MOCK
    risk_level: ActionRiskLevel = ActionRiskLevel.LOW
    requires_approval: bool = False
    status: ActionLifecycleState = ActionLifecycleState.PLANNED
    timeout_seconds: float = 30.0
    retry_count: int = 0
    max_retries: int = 2
    
    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    
    # Verification & Error tracking
    verified: Optional[bool] = None
    verification_detail: Optional[str] = None
    error: Optional[str] = None

    def transition_to(self, new_state: ActionLifecycleState) -> bool:
        """Safely transition state according to lifecycle rules."""
        if not is_valid_transition(self.status, new_state):
            raise ValueError(
                f"Invalid action state transition from {self.status.value} to {new_state.value}"
            )
        self.status = new_state
        now = datetime.now(timezone.utc)
        if new_state == ActionLifecycleState.RUNNING and not self.started_at:
            self.started_at = now
        elif new_state in (
            ActionLifecycleState.SUCCEEDED,
            ActionLifecycleState.FAILED,
            ActionLifecycleState.CANCELLED,
            ActionLifecycleState.SKIPPED,
            ActionLifecycleState.TIMED_OUT,
        ):
            self.finished_at = now
        return True

