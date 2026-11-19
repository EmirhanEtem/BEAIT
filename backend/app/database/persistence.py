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
            # Idempotent migration: attach optional session_id column to tasks
            task_cols = {
                row[1]
                for row in conn.execute("PRAGMA table_info(tasks)").fetchall()
            }
            if "session_id" not in task_cols:
                conn.execute("ALTER TABLE tasks ADD COLUMN session_id TEXT")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    session_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    text TEXT NOT NULL,
                    task_id TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_chat_messages_session_created
                ON chat_messages (session_id, created_at)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chat_session_plans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_chat_session_plans_session
                ON chat_session_plans (session_id, id)
            """)

    # -- Tasks ---------------------------------------------------------------

    def save_task(self, task_id: str, prompt: str, status: str, is_mock: bool,
                  created_at: Optional[datetime] = None, completed_at: Optional[datetime] = None,
                  result_summary: Optional[str] = None, error: Optional[str] = None,
                  session_id: Optional[str] = None):
        c_at = (created_at or datetime.now(timezone.utc)).isoformat()
        done_at = completed_at.isoformat() if completed_at else None
        with self._session() as conn:
            conn.execute("""
                INSERT INTO tasks
                (task_id, prompt, status, is_mock, created_at, completed_at, result_summary, error, session_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    prompt = excluded.prompt,
                    status = excluded.status,
                    is_mock = excluded.is_mock,
                    completed_at = COALESCE(excluded.completed_at, tasks.completed_at),
                    result_summary = COALESCE(excluded.result_summary, tasks.result_summary),
                    error = COALESCE(excluded.error, tasks.error),
                    session_id = COALESCE(excluded.session_id, tasks.session_id)
            """, (task_id, prompt, status, 1 if is_mock else 0, c_at, done_at, result_summary, error, session_id))

    def list_tasks_for_session(self, session_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        with self._session() as conn:
            if session_id:
                cur = conn.execute(
                    "SELECT * FROM tasks WHERE session_id = ? ORDER BY created_at ASC, rowid ASC LIMIT ?",
                    (session_id, limit),
                )
            else:
                cur = conn.execute(
                    "SELECT * FROM tasks ORDER BY created_at ASC, rowid ASC LIMIT ?",
                    (limit,),
                )
            rows = cur.fetchall()
        results: List[Dict[str, Any]] = []
        for row in rows:
            d = dict(row)
            d["is_mock"] = bool(d.get("is_mock"))
            results.append(d)
        return results

    def create_chat_session(
        self,
        session_id: str,
        title: str = "Yeni Sohbet",
        created_at: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        now_iso = (created_at or datetime.now(timezone.utc)).isoformat()
        clean_title = (title or "Yeni Sohbet").strip()[:80] or "Yeni Sohbet"
        with self._session() as conn:
            conn.execute("""
                INSERT INTO chat_sessions (session_id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    title = excluded.title,
                    updated_at = excluded.updated_at
            """, (session_id, clean_title, now_iso, now_iso))
        return self.get_chat_session(session_id) or {
            "session_id": session_id,
            "title": clean_title,
            "created_at": now_iso,
            "updated_at": now_iso,
            "message_count": 0,
            "last_message_preview": None,
        }

    def get_chat_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._session() as conn:
            cur = conn.execute(
                """
                SELECT
                    s.session_id,
                    s.title,
                    s.created_at,
                    s.updated_at,
                    (SELECT COUNT(*) FROM chat_messages m WHERE m.session_id = s.session_id) AS message_count,
                    (
                        SELECT m.text
                        FROM chat_messages m
                        WHERE m.session_id = s.session_id
                        ORDER BY m.created_at DESC, m.rowid DESC
                        LIMIT 1
                    ) AS last_message_preview
                FROM chat_sessions s
                WHERE s.session_id = ?
                """,
                (session_id,),
            )
            row = cur.fetchone()
        if not row:
            return None
        item = dict(row)
        if item.get("last_message_preview"):
            item["last_message_preview"] = str(item["last_message_preview"]).strip().replace("\n", " ")[:120]
        return item

    def list_chat_sessions(self) -> List[Dict[str, Any]]:
        with self._session() as conn:
            cur = conn.execute(
                """
                SELECT
                    s.session_id,
                    s.title,
                    s.created_at,
                    s.updated_at,
                    (SELECT COUNT(*) FROM chat_messages m WHERE m.session_id = s.session_id) AS message_count,
                    (
                        SELECT m.text
                        FROM chat_messages m
                        WHERE m.session_id = s.session_id
                        ORDER BY m.created_at DESC, m.rowid DESC
                        LIMIT 1
                    ) AS last_message_preview
                FROM chat_sessions s
                ORDER BY s.updated_at DESC, s.created_at DESC, s.rowid DESC
                """
            )
            rows = cur.fetchall()
        sessions: List[Dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            if item.get("last_message_preview"):
                item["last_message_preview"] = str(item["last_message_preview"]).strip().replace("\n", " ")[:120]
            sessions.append(item)
        return sessions

    def update_chat_session_title(
        self,
        session_id: str,
        title: str,
        updated_at: Optional[datetime] = None,
    ) -> Optional[Dict[str, Any]]:
        clean_title = (title or "").strip()[:80]
        if not clean_title:
            return self.get_chat_session(session_id)
        now_iso = (updated_at or datetime.now(timezone.utc)).isoformat()
        with self._session() as conn:
            conn.execute(
                "UPDATE chat_sessions SET title = ?, updated_at = ? WHERE session_id = ?",
                (clean_title, now_iso, session_id),
            )
        return self.get_chat_session(session_id)

    def touch_chat_session(self, session_id: str, updated_at: Optional[datetime] = None) -> None:
        now_iso = (updated_at or datetime.now(timezone.utc)).isoformat()
        with self._session() as conn:
            conn.execute(
                "UPDATE chat_sessions SET updated_at = ? WHERE session_id = ?",
                (now_iso, session_id),
            )

    def delete_chat_session(self, session_id: str) -> bool:
        with self._session() as conn:
            conn.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM chat_session_plans WHERE session_id = ?", (session_id,))
            conn.execute("UPDATE tasks SET session_id = NULL WHERE session_id = ?", (session_id,))
            cur = conn.execute("DELETE FROM chat_sessions WHERE session_id = ?", (session_id,))
            return cur.rowcount > 0

    def save_chat_message(
        self,
        msg_id: str,
        session_id: str,
        role: str,
        text: str,
        task_id: Optional[str] = None,
        created_at: Optional[datetime] = None,
    ) -> None:
        c_at = (created_at or datetime.now(timezone.utc)).isoformat()
        with self._session() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO chat_messages (id, session_id, role, text, task_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (msg_id, session_id, role, text, task_id, c_at),
            )
            conn.execute(
                "UPDATE chat_sessions SET updated_at = ? WHERE session_id = ?",
                (c_at, session_id),
            )

    def list_chat_messages(self, session_id: str, limit: int = 200) -> List[Dict[str, Any]]:
        with self._session() as conn:
            cur = conn.execute(
                """
                SELECT id, session_id, role, text, task_id, created_at
                FROM (
                    SELECT id, session_id, role, text, task_id, created_at, rowid AS _rid
                    FROM chat_messages
                    WHERE session_id = ?
                    ORDER BY created_at DESC, rowid DESC
                    LIMIT ?
                )
                ORDER BY created_at ASC, _rid ASC
                """,
                (session_id, limit),
            )
            rows = cur.fetchall()
        return [dict(row) for row in rows]

    def save_session_plan_memory(
        self,
        session_id: str,
        summary: Dict[str, Any],
        created_at: Optional[datetime] = None,
    ) -> None:
        c_at = (created_at or datetime.now(timezone.utc)).isoformat()
        with self._session() as conn:
            conn.execute(
                """
                INSERT INTO chat_session_plans (session_id, summary_json, created_at)
                VALUES (?, ?, ?)
                """,
                (session_id, json.dumps(summary, ensure_ascii=False), c_at),
            )

    def list_session_plan_memory(self, session_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        with self._session() as conn:
            cur = conn.execute(
                """
                SELECT summary_json
                FROM chat_session_plans
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (session_id, limit),
            )
            rows = cur.fetchall()
        results: List[Dict[str, Any]] = []
        for row in reversed(rows):
            try:
                parsed = json.loads(row["summary_json"])
                if isinstance(parsed, dict):
                    results.append(parsed)
            except Exception:
                continue
        return results

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
