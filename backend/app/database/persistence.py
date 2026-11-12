"""SQLite persistence manager for actions, tasks, and checkpoints."""

from __future__ import annotations

from contextlib import contextmanager
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..schemas.actions import ActionDefinition, ActionLifecycleState, ActionRiskLevel, ActionType

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "fl_assistant.db"


class DatabaseManager:
    """Synchronous SQLite database client for audit history and checkpoints."""

    def __init__(self, db_path: Optional[Path | str] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        if isinstance(self.db_path, Path):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._str_path = str(self.db_path)
        else:
            self._str_path = str(self.db_path)
        self._init_db()

    @contextmanager
    def _session(self):
        """Context manager that guarantees connection is closed on exit (vital for Windows file locks)."""
        conn = sqlite3.connect(self._str_path)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self):
        with self._session() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    prompt TEXT NOT NULL,
                    status TEXT NOT NULL,
                    is_mock INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    result_summary TEXT,
                    error TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS actions (
                    action_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    target TEXT,
                    parameters_json TEXT,
                    execution_route TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    requires_approval INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    timeout_seconds REAL,
                    retry_count INTEGER,
                    max_retries INTEGER,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    verified INTEGER,
                    verification_detail TEXT,
                    error TEXT,
                    FOREIGN KEY (task_id) REFERENCES tasks (task_id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS checkpoints (
                    checkpoint_id TEXT PRIMARY KEY,
                    task_id TEXT,
                    name TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)

    # -- Tasks ---------------------------------------------------------------

    def save_task(self, task_id: str, prompt: str, status: str, is_mock: bool,
                  created_at: Optional[datetime] = None, completed_at: Optional[datetime] = None,
                  result_summary: Optional[str] = None, error: Optional[str] = None):
        c_at = (created_at or datetime.now(timezone.utc)).isoformat()
        done_at = completed_at.isoformat() if completed_at else None
        with self._session() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO tasks 
                (task_id, prompt, status, is_mock, created_at, completed_at, result_summary, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (task_id, prompt, status, 1 if is_mock else 0, c_at, done_at, result_summary, error))

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._session() as conn:
            cur = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
            row = cur.fetchone()
            if row:
                return dict(row)
            return None

    # -- Actions -------------------------------------------------------------

    def save_action(self, action: ActionDefinition):
        with self._session() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO actions (
                    action_id, task_id, action_type, target, parameters_json,
                    execution_route, risk_level, requires_approval, status,
                    timeout_seconds, retry_count, max_retries, created_at,
                    started_at, finished_at, verified, verification_detail, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                action.action_id,
                action.task_id,
                action.action_type.value,
                action.target,
                json.dumps(action.parameters),
                action.execution_route,
                action.risk_level.value,
                1 if action.requires_approval else 0,
                action.status.value,
                action.timeout_seconds,
                action.retry_count,
                action.max_retries,
                action.created_at.isoformat(),
                action.started_at.isoformat() if action.started_at else None,
                action.finished_at.isoformat() if action.finished_at else None,
                None if action.verified is None else (1 if action.verified else 0),
                action.verification_detail,
                action.error,
            ))

    def get_action(self, action_id: str) -> Optional[ActionDefinition]:
        with self._session() as conn:
            cur = conn.execute("SELECT * FROM actions WHERE action_id = ?", (action_id,))
            row = cur.fetchone()
            if not row:
                return None
            return ActionDefinition(
                action_id=row["action_id"],
                task_id=row["task_id"],
                action_type=ActionType(row["action_type"]),
                target=row["target"] or "",
                parameters=json.loads(row["parameters_json"]) if row["parameters_json"] else {},
                execution_route=row["execution_route"],
                risk_level=ActionRiskLevel(row["risk_level"]),
                requires_approval=bool(row["requires_approval"]),
                status=ActionLifecycleState(row["status"]),
                timeout_seconds=row["timeout_seconds"],
                retry_count=row["retry_count"],
                max_retries=row["max_retries"],
                created_at=datetime.fromisoformat(row["created_at"]),
                started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
                finished_at=datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None,
                verified=None if row["verified"] is None else bool(row["verified"]),
                verification_detail=row["verification_detail"],
                error=row["error"],
            )

    def list_actions_for_task(self, task_id: str) -> List[ActionDefinition]:
        with self._session() as conn:
            cur = conn.execute("SELECT action_id FROM actions WHERE task_id = ? ORDER BY created_at ASC", (task_id,))
            rows = cur.fetchall()
            return [self.get_action(r["action_id"]) for r in rows if r["action_id"]]

    # -- Checkpoints ---------------------------------------------------------

    def save_checkpoint(self, checkpoint_id: str, name: str, state_snapshot: dict, task_id: Optional[str] = None):
        with self._session() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO checkpoints (checkpoint_id, task_id, name, state_json, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                checkpoint_id,
                task_id,
                name,
                json.dumps(state_snapshot),
                datetime.now(timezone.utc).isoformat(),
            ))

    def get_checkpoint(self, checkpoint_id: str) -> Optional[Dict[str, Any]]:
        with self._session() as conn:
            cur = conn.execute("SELECT * FROM checkpoints WHERE checkpoint_id = ?", (checkpoint_id,))
            row = cur.fetchone()
            if not row:
                return None
            res = dict(row)
            res["state"] = json.loads(res["state_json"])
            return res
