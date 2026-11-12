"""Project Memory, User Preferences, and Session Task History (Phase 8).

Persists user musical preferences, approved sample directories, and
completed task summaries with honest limitation reporting.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class UserMusicalPreferences:
    """Persistent user preferences for musical defaults and safety settings."""
    preferred_genre: str = "melodic_techno"
    preferred_bpm: float = 126.0
    preferred_root: str = "A"
    preferred_scale: str = "natural_minor"
    safe_mode: bool = True
    approved_sample_directories: List[str] = field(default_factory=list)


@dataclass
class TaskSummaryRecord:
    """Auditable summary of an executed production workflow task."""
    task_id: str
    plan_id: str
    prompt: str
    parsed_intent: Dict[str, Any]
    actions_planned: int
    actions_succeeded: int
    actions_verified: int
    actions_failed: int
    actions_awaiting_approval: int
    completed_steps: List[str] = field(default_factory=list)
    exported_midi_files: Dict[str, str] = field(default_factory=dict)
    remaining_limitations: List[str] = field(default_factory=list)
    critic_summary: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ProjectMemoryManager:
    """Manages persistent user preferences and session task summaries."""

    def __init__(self, storage_path: Optional[str] = None):
        self.storage_path = storage_path
        self.preferences = UserMusicalPreferences()
        self.task_history: List[TaskSummaryRecord] = []
        if self.storage_path and os.path.isfile(self.storage_path):
            self.load()

    def update_preferences(self, **kwargs: Any) -> UserMusicalPreferences:
        for k, v in kwargs.items():
            if hasattr(self.preferences, k):
                setattr(self.preferences, k, v)
        self.save()
        return self.preferences

    def record_task_summary(self, summary: TaskSummaryRecord) -> None:
        self.task_history.append(summary)
        self.save()

    def get_recent_summaries(self, limit: int = 20) -> List[TaskSummaryRecord]:
        return list(reversed(self.task_history[-limit:]))

    def save(self) -> None:
        if not self.storage_path:
            return
        os.makedirs(os.path.dirname(os.path.abspath(self.storage_path)), exist_ok=True)
        payload = {
            "preferences": asdict(self.preferences),
            "task_history": [asdict(t) for t in self.task_history],
        }
        with open(self.storage_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

    def load(self) -> None:
        if not self.storage_path or not os.path.isfile(self.storage_path):
            return
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            prefs_raw = raw.get("preferences", {})
            self.preferences = UserMusicalPreferences(**prefs_raw)
            self.task_history = [
                TaskSummaryRecord(**item) for item in raw.get("task_history", [])
            ]
        except Exception:
            pass

