"""Session and Task Execution Manager."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import uuid
from typing import Any, Dict, List, Optional, Set
from fastapi import WebSocket

from ..integrations.computer_use import GUIAutomationAdapter
from ..integrations.fl_studio import FLStudioAdapter, TransportType
from ..orchestration.producer import ActionPlan, ProducerOrchestrator
from ..schemas.actions import ActionLifecycleState, ActionType
from ..schemas import (
    ActionItem,
    ActionStatus,
    AppEvent,
    ChatMessage,
    ConnectionState,
    CursorMarker,
    EventType,
    ExecutionRoute,
    ProjectContextInfo,
    TaskResponse,
    TaskStatus,
)

logger = logging.getLogger(__name__)


from ..database.persistence import DatabaseManager
from ..schemas.tasks import ChatSession


class TaskExecutionManager:
    """Coordinates task execution, cancellation, and event broadcasting."""

    def __init__(self, db_path: Optional[str] = None):
        self._tasks: Dict[str, TaskResponse] = {}
        self._plans: Dict[str, ActionPlan] = {}
        self._active_task_id: Optional[str] = None
        self._cancel_events: Dict[str, asyncio.Event] = {}
        self._active_connections: Set[WebSocket] = set()
        self._messages: List[ChatMessage] = []
        self._sessions: Dict[str, ChatSession] = {}
        self._session_messages: Dict[str, List[ChatMessage]] = {}
        self._active_session_id: Optional[str] = None

        self.db = DatabaseManager(db_path=db_path)
        self.fl_adapter = FLStudioAdapter(transport=TransportType.TCP)
        self.hcu_adapter = GUIAutomationAdapter()
        self.orchestrator = ProducerOrchestrator(
            fl_adapter=self.fl_adapter,
            hcu_adapter=self.hcu_adapter,
            db=self.db,
        )
        self._load_persisted_sessions()

    def _load_persisted_sessions(self) -> None:
        """Restore chat sessions, messages, and recent tasks from SQLite."""
        rows = self.db.list_chat_sessions()
        for row in rows:
            sid = row["session_id"]
            sess = ChatSession(
                session_id=sid,
                title=row["title"],
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
                message_count=int(row.get("message_count") or 0),
                last_message_preview=row.get("last_message_preview"),
            )
            self._sessions[sid] = sess
            msg_rows = self.db.list_chat_messages(sid, limit=200)
            self._session_messages[sid] = [
                ChatMessage(
                    id=m["id"],
                    session_id=m["session_id"],
                    role=m["role"],
                    text=m["text"],
                    task_id=m.get("task_id"),
                    created_at=datetime.fromisoformat(m["created_at"]),
                )
                for m in msg_rows
            ]
        for t_row in self.db.list_tasks_for_session(limit=100):
            tid = t_row["task_id"]
            if tid not in self._tasks:
                st_raw = str(t_row.get("status") or "COMPLETED")
                try:
                    st = TaskStatus(st_raw)
                except ValueError:
                    st = TaskStatus.COMPLETED
                if st in (TaskStatus.QUEUED, TaskStatus.RUNNING):
                    st = TaskStatus.FAILED
                self._tasks[tid] = TaskResponse(
                    task_id=tid,
                    session_id=t_row.get("session_id"),
                    prompt=t_row["prompt"],
                    status=st,
                    is_mock=bool(t_row.get("is_mock")),
                    created_at=datetime.fromisoformat(t_row["created_at"]),
                    completed_at=(
                        datetime.fromisoformat(t_row["completed_at"])
                        if t_row.get("completed_at")
                        else None
                    ),
                    result_summary=t_row.get("result_summary"),
                    error=t_row.get("error"),
                )
        if self._sessions:
            self._active_session_id = next(iter(self._sessions.keys()))
            self._messages = list(self._session_messages.get(self._active_session_id, []))
        else:
            self.create_session(title="Yeni Sohbet")
        
        # Latest cached states
        self.cached_connection = ConnectionState()
        self.cached_project = ProjectContextInfo()
        self.cached_cursor = CursorMarker()
        self.latest_screenshot_b64: Optional[str] = None

    # -- WebSocket connection management ------------------------------------

    async def connect_client(self, websocket: WebSocket):
        await websocket.accept()
        self._active_connections.add(websocket)
        logger.info("WebSocket client connected. Total clients: %d", len(self._active_connections))

        if not self.cached_connection.fl_studio_alive or not self.cached_connection.hcu_available:
            await self.refresh_system_health()
            await self.refresh_project_context()

        # Send initial state snapshot on connect
        await self._send_to_client(websocket, AppEvent(
            type=EventType.CONNECTION_STATUS,
            payload=self.cached_connection.model_dump(),
        ))
        await self._send_to_client(websocket, AppEvent(
            type=EventType.PROJECT_CONTEXT,
            payload=self.cached_project.model_dump(),
        ))
        active_msgs = (
            self._session_messages.get(self._active_session_id, [])
            if self._active_session_id
            else self._messages
        )
        for msg in active_msgs[-50:]:
            await self._send_to_client(websocket, AppEvent(
                type=EventType.CHAT_MESSAGE,
                payload=msg.model_dump(mode="json"),
            ))

    def disconnect_client(self, websocket: WebSocket):
        self._active_connections.discard(websocket)
        logger.info("WebSocket client disconnected. Total clients: %d", len(self._active_connections))

    async def broadcast(self, event: AppEvent):
        """Broadcast event to all connected clients."""
        dead_sockets = set()
        for ws in self._active_connections:
            try:
                await ws.send_text(event.model_dump_json())
            except Exception:
                dead_sockets.add(ws)
        self._active_connections -= dead_sockets

    async def _send_to_client(self, ws: WebSocket, event: AppEvent):
        try:
            await ws.send_text(event.model_dump_json())
        except Exception:
            pass

    # -- Health & Context Refresh --------------------------------------------

    async def refresh_system_health(self) -> ConnectionState:
        """Probe FL Studio and HCU and update status."""
        fl_status = await self.fl_adapter.async_check_health()
        if not fl_status.connected:
            fl_status = await self.fl_adapter.async_connect()
        hcu_status = await self.hcu_adapter.async_check_availability()
        
        state = ConnectionState(
            backend_online=True,
            fl_mcp_connected=fl_status.connected,
            fl_studio_alive=fl_status.fl_studio_alive,
            fl_heartbeat_age=fl_status.heartbeat_age,
            hcu_available=hcu_status.available,
            hcu_version="1.0.0" if hcu_status.available else None,
            error_message=fl_status.error or hcu_status.error,
        )
        self.cached_connection = state
        await self.broadcast(AppEvent(type=EventType.CONNECTION_STATUS, payload=state.model_dump()))
        return state

    async def refresh_project_context(self) -> ProjectContextInfo:
        """Fetch current project information from FL Studio if alive."""
        if not self.cached_connection.fl_studio_alive:
            # Explicitly unknown state when not connected
            info = ProjectContextInfo(connected=False)
            self.cached_project = info
            await self.broadcast(AppEvent(type=EventType.PROJECT_CONTEXT, payload=info.model_dump()))
            return info

        try:
            state = await self.fl_adapter.async_get_project_state()
            channels = await self.fl_adapter.async_get_channels()
            mixer_tracks = await self.fl_adapter.async_get_mixer_tracks()
            patterns = await self.fl_adapter.async_get_patterns()

            info = ProjectContextInfo(
                connected=True,
                title=state.title,  # None means unknown
                fl_version=state.fl_version,
                tempo=state.tempo,
                time_signature=None,  # Not provided by FL API, explicitly unknown
                playing=state.playing,
                recording=state.recording,
                channels=channels,
                mixer_tracks=mixer_tracks,
                patterns=patterns,
            )
            self.cached_project = info
            await self.broadcast(AppEvent(type=EventType.PROJECT_CONTEXT, payload=info.model_dump()))
            return info
        except Exception as e:
            logger.warning("Failed to refresh project context: %s", e)
            return self.cached_project

    # -- Chat Messages -------------------------------------------------------

    def _ensure_session(self, session_id: Optional[str] = None) -> ChatSession:
        if session_id:
            if session_id in self._sessions:
                self._active_session_id = session_id
                return self._sessions[session_id]
            row = self.db.get_chat_session(session_id)
            if row:
                sess = ChatSession(
                    session_id=row["session_id"],
                    title=row["title"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    updated_at=datetime.fromisoformat(row["updated_at"]),
                    message_count=int(row.get("message_count") or 0),
                    last_message_preview=row.get("last_message_preview"),
                )
                self._sessions[session_id] = sess
                self._session_messages.setdefault(session_id, [])
                self._active_session_id = session_id
                return sess
            return self.create_session(session_id=session_id)
        if self._active_session_id and self._active_session_id in self._sessions:
            return self._sessions[self._active_session_id]
        if self._sessions:
            first_sid = next(iter(self._sessions.keys()))
            self._active_session_id = first_sid
            return self._sessions[first_sid]
        return self.create_session(title="Yeni Sohbet")

    def list_sessions(self) -> List[ChatSession]:
        sessions: List[ChatSession] = []
        for row in self.db.list_chat_sessions():
            sid = row["session_id"]
            sess = ChatSession(
                session_id=sid,
                title=row["title"],
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
                message_count=int(row.get("message_count") or 0),
                last_message_preview=row.get("last_message_preview"),
            )
            self._sessions[sid] = sess
            sessions.append(sess)
        return sessions

    def get_session(self, session_id: str) -> Optional[ChatSession]:
        if session_id in self._sessions:
            row = self.db.get_chat_session(session_id)
            if row:
                self._sessions[session_id] = ChatSession(
                    session_id=row["session_id"],
                    title=row["title"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    updated_at=datetime.fromisoformat(row["updated_at"]),
                    message_count=int(row.get("message_count") or 0),
                    last_message_preview=row.get("last_message_preview"),
                )
            return self._sessions[session_id]
        row = self.db.get_chat_session(session_id)
        if not row:
            return None
        sess = ChatSession(
            session_id=row["session_id"],
            title=row["title"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            message_count=int(row.get("message_count") or 0),
            last_message_preview=row.get("last_message_preview"),
        )
        self._sessions[session_id] = sess
        return sess

    def create_session(
        self,
        title: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> ChatSession:
        sid = session_id or f"chat_{uuid.uuid4().hex[:8]}"
        clean_title = (title or "Yeni Sohbet").strip()[:80] or "Yeni Sohbet"
        row = self.db.create_chat_session(sid, title=clean_title)
        sess = ChatSession(
            session_id=sid,
            title=row["title"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            message_count=int(row.get("message_count") or 0),
            last_message_preview=row.get("last_message_preview"),
        )
        self._sessions[sid] = sess
        self._session_messages[sid] = []
        self._active_session_id = sid
        self._messages = []
        return sess

    async def rename_session(self, session_id: str, title: str) -> Optional[ChatSession]:
        row = self.db.update_chat_session_title(session_id, title)
        if not row:
            return None
        sess = ChatSession(
            session_id=row["session_id"],
            title=row["title"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            message_count=int(row.get("message_count") or 0),
            last_message_preview=row.get("last_message_preview"),
        )
        self._sessions[session_id] = sess
        await self.broadcast(AppEvent(type=EventType.SESSION_UPDATED, payload=sess.model_dump(mode="json")))
        return sess

    def delete_session(self, session_id: str) -> bool:
        deleted = self.db.delete_chat_session(session_id)
        self._sessions.pop(session_id, None)
        self._session_messages.pop(session_id, None)
        self.orchestrator._session_histories.pop(session_id, None)
        self.orchestrator._session_last_prompts.pop(session_id, None)
        if self._active_session_id == session_id:
            remaining = self.list_sessions()
            if remaining:
                self._active_session_id = remaining[0].session_id
                self._messages = list(self._session_messages.get(self._active_session_id, []))
            else:
                new_sess = self.create_session(title="Yeni Sohbet")
                self._active_session_id = new_sess.session_id
                self._messages = []
        return deleted

    async def _maybe_auto_title_session(self, session_id: str, prompt: str) -> None:
        sess = self._sessions.get(session_id)
        if not sess or sess.title.strip() not in ("Yeni Sohbet", ""):
            return
        collapsed = " ".join(prompt.strip().split())
        if not collapsed:
            return
        if len(collapsed) > 40:
            cut = collapsed[:40].rsplit(" ", 1)[0].strip()
            new_title = (cut or collapsed[:40]) + "..."
        else:
            new_title = collapsed
        await self.rename_session(session_id, new_title)

    def _get_ai_conversation_history(
        self,
        session_id: str,
        exclude_msg_id: Optional[str] = None,
        limit: int = 12,
    ) -> List[Dict[str, str]]:
        msgs = self.get_messages(session_id=session_id)
        turns: List[Dict[str, str]] = []
        for m in msgs:
            if exclude_msg_id and m.id == exclude_msg_id:
                continue
            if m.role not in ("user", "assistant"):
                continue
            txt = (m.text or "").strip()
            if not txt or txt.startswith("Starting plan for:"):
                continue
            turns.append({"role": m.role, "text": txt})
        return turns[-limit:]

    async def add_chat_message(
        self,
        role: str,
        text: str,
        task_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> ChatMessage:
        sess = self._ensure_session(session_id)
        sid = sess.session_id
        msg = ChatMessage(
            id=str(uuid.uuid4())[:8],
            session_id=sid,
            role=role,
            text=text,
            task_id=task_id,
        )
        self._session_messages.setdefault(sid, []).append(msg)
        if sid == self._active_session_id:
            self._messages.append(msg)
        self.db.save_chat_message(
            msg_id=msg.id,
            session_id=sid,
            role=role,
            text=text,
            task_id=task_id,
            created_at=msg.created_at,
        )
        sess.updated_at = msg.created_at
        sess.message_count = len(self._session_messages[sid])
        sess.last_message_preview = text.strip().replace("\n", " ")[:120]
        await self.broadcast(AppEvent(type=EventType.CHAT_MESSAGE, payload=msg.model_dump(mode="json")))
        await self.broadcast(AppEvent(type=EventType.SESSION_UPDATED, payload=sess.model_dump(mode="json")))
        return msg

    def get_messages(self, session_id: Optional[str] = None) -> List[ChatMessage]:
        sid = session_id or self._active_session_id
        if not sid:
            return list(self._messages)
        if sid in self._session_messages and self._session_messages[sid]:
            return list(self._session_messages[sid])
        rows = self.db.list_chat_messages(sid, limit=200)
        restored = [
            ChatMessage(
                id=m["id"],
                session_id=m["session_id"],
                role=m["role"],
                text=m["text"],
                task_id=m.get("task_id"),
                created_at=datetime.fromisoformat(m["created_at"]),
            )
            for m in rows
        ]
        self._session_messages[sid] = restored
        return list(restored)

    # -- Task Management -----------------------------------------------------

    def list_tasks(self, session_id: Optional[str] = None) -> List[TaskResponse]:
        if session_id:
            return [t for t in self._tasks.values() if t.session_id == session_id]
        return list(self._tasks.values())

    def get_task(self, task_id: str) -> Optional[TaskResponse]:
        return self._tasks.get(task_id)

    async def submit_task(
        self,
        prompt: str,
        is_mock: bool = True,
        session_id: Optional[str] = None,
    ) -> TaskResponse:
        sess = self._ensure_session(session_id)
        sid = sess.session_id
        task_id = f"task_{uuid.uuid4().hex[:8]}"
        task = TaskResponse(
            task_id=task_id,
            session_id=sid,
            prompt=prompt,
            is_mock=is_mock,
            status=TaskStatus.QUEUED,
        )
        self._tasks[task_id] = task
        self._cancel_events[task_id] = asyncio.Event()
        self.db.save_task(
            task_id=task_id,
            prompt=prompt,
            status=task.status.value,
            is_mock=is_mock,
            created_at=task.created_at,
            session_id=sid,
        )

        # Add user chat message & auto-title brand-new chat on first prompt
        user_msg = await self.add_chat_message("user", prompt, task_id=task_id, session_id=sid)
        await self._maybe_auto_title_session(sid, prompt)

        conv_history = self._get_ai_conversation_history(sid, exclude_msg_id=user_msg.id)
        plan_history = self.db.list_session_plan_memory(sid, limit=6)

        # Plan initial actions (in thread so LLM HTTP call never blocks event loop)
        task.actions = await asyncio.to_thread(
            self._build_plan_for_task,
            task_id,
            prompt,
            is_mock,
            sid,
            conv_history,
            plan_history,
        )
        plan = self._plans.get(task_id)
        if plan and plan.session_history_entry:
            self.db.save_session_plan_memory(sid, plan.session_history_entry)

        # Broadcast initial task state
        await self.broadcast(AppEvent(
            type=EventType.TASK_UPDATE,
            payload=task.model_dump(mode="json"),
        ))

        # Start execution in background
        asyncio.create_task(self._run_task(task_id))
        return task

    async def stop_active_task(self, task_id: Optional[str] = None) -> bool:
        """Cancel the specified task or currently active task."""
        target_id = task_id or self._active_task_id
        if not target_id or target_id not in self._tasks:
            return False

        task = self._tasks[target_id]
        if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            return False

        if target_id in self._cancel_events:
            self._cancel_events[target_id].set()

        task.status = TaskStatus.CANCELLED
        task.completed_at = datetime.now(timezone.utc)
        task.result_summary = "Task was cancelled by user."
        
        # Mark active and planned actions as CANCELLED
        for act in task.actions:
            if act.status in (ActionStatus.RUNNING, ActionStatus.PLANNED, ActionStatus.READY):
                act.status = ActionStatus.CANCELLED
                act.finished_at = datetime.now(timezone.utc)

        self._active_task_id = None
        self.db.save_task(
            task_id=task.task_id,
            prompt=task.prompt,
            status=task.status.value,
            is_mock=task.is_mock,
            created_at=task.created_at,
            completed_at=task.completed_at,
            result_summary=task.result_summary,
            error=task.error,
            session_id=task.session_id,
        )
        await self.broadcast(AppEvent(type=EventType.TASK_UPDATE, payload=task.model_dump(mode="json")))
        await self.add_chat_message(
            "system",
            f"Task {target_id} stopped by user.",
            task_id=target_id,
            session_id=task.session_id,
        )
        return True

    # -- Internal Task Execution ---------------------------------------------

    def _build_plan_for_task(
        self,
        task_id: str,
        prompt: str,
        is_mock: bool,
        session_id: Optional[str] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        session_recent_history: Optional[List[Dict[str, Any]]] = None,
    ) -> List[ActionItem]:
        ctx_dict = None
        if self.cached_project.connected:
            ctx_dict = {
                "bpm": self.cached_project.tempo,
                "playing": self.cached_project.playing,
                "channel_count": len(self.cached_project.channels),
                "channels": self.cached_project.channels,
            }
        plan = self.orchestrator.create_plan(
            prompt,
            task_id=task_id,
            project_context=ctx_dict,
            session_id=session_id,
            conversation_history=conversation_history,
            session_recent_history=session_recent_history,
        )
        self._plans[task_id] = plan

        items: List[ActionItem] = []
        for a in plan.actions:
            if is_mock:
                route = ExecutionRoute.MOCK
            elif a.execution_route == "FL_MCP":
                route = ExecutionRoute.FL_MCP
            elif a.execution_route == "GUI_AUTOMATION":
                route = ExecutionRoute.GUI_AUTOMATION
            else:
                route = ExecutionRoute.LOCAL_SERVICE

            items.append(
                ActionItem(
                    action_id=a.action_id,
                    task_id=task_id,
                    name=a.description or a.action_type.value,
                    description=a.description or a.action_type.value,
                    target="FL Studio Session",
                    route=route,
                    status=ActionStatus.PLANNED,
                )
            )
        return items

    async def _run_task(self, task_id: str):
        task = self._tasks[task_id]
        self._active_task_id = task_id
        cancel_event = self._cancel_events[task_id]
        plan = self._plans.get(task_id)

        task.status = TaskStatus.RUNNING
        await self.broadcast(AppEvent(type=EventType.TASK_UPDATE, payload=task.model_dump(mode="json")))
        if plan and plan.llm_explanation:
            await self.add_chat_message(
                "assistant",
                f"🤖 AI Prodüktör:\n{plan.llm_explanation}",
                task_id=task_id,
                session_id=task.session_id,
            )
        else:
            await self.add_chat_message(
                "assistant",
                f"Starting plan for: '{task.prompt}'",
                task_id=task_id,
                session_id=task.session_id,
            )

        try:
            plan_actions = plan.actions if plan else []
            soft_continue_types = {
                ActionType.SET_MIXER_ROUTING,
                ActionType.LOAD_MIXER_EFFECT,
                ActionType.SET_PLUGIN_PARAM,
                ActionType.SET_MIXER_TRACK_META,
                ActionType.ADD_ARRANGEMENT_MARKER,
                ActionType.AUTO_MIX_MASTER,
            }
            soft_warnings: List[str] = []
            for index, action_item in enumerate(task.actions):
                if cancel_event.is_set():
                    break

                action_item.status = ActionStatus.RUNNING
                action_item.started_at = datetime.now(timezone.utc)
                await self.broadcast(AppEvent(type=EventType.ACTION_UPDATE, payload=action_item.model_dump(mode="json")))

                # Cursor simulation for UI representation (clearly marked is_real_desktop=False)
                marker = CursorMarker(
                    active=True,
                    x=200 + index * 120,
                    y=150 + index * 60,
                    label=action_item.name,
                    is_real_desktop=False,
                )
                self.cached_cursor = marker
                await self.broadcast(AppEvent(type=EventType.CURSOR_MARKER, payload=marker.model_dump()))

                act_def = plan_actions[index] if index < len(plan_actions) else None
                if act_def:
                    executed = await self.orchestrator.executor.execute_action(
                        act_def,
                        cancel_event=cancel_event,
                        prefer_mock=task.is_mock,
                    )
                    action_item.verified = executed.verified
                    action_item.verification_detail = executed.verification_detail
                    action_item.error = executed.error
                    exec_status = executed.status
                else:
                    await asyncio.sleep(0.1)
                    action_item.verified = True
                    action_item.verification_detail = "Executed default step"
                    exec_status = ActionLifecycleState.SUCCEEDED

                if cancel_event.is_set():
                    action_item.status = ActionStatus.CANCELLED
                    action_item.finished_at = datetime.now(timezone.utc)
                    await self.broadcast(AppEvent(type=EventType.ACTION_UPDATE, payload=action_item.model_dump(mode="json")))
                    break

                if exec_status == ActionLifecycleState.SUCCEEDED:
                    action_item.status = ActionStatus.SUCCEEDED
                elif exec_status == ActionLifecycleState.AWAITING_APPROVAL:
                    action_item.status = ActionStatus.PLANNED
                    task.status = TaskStatus.QUEUED
                    await self.add_chat_message(
                        "assistant",
                        f"Action '{action_item.name}' requires explicit approval before executing.",
                        task_id=task_id,
                        session_id=task.session_id,
                    )
                    break
                else:
                    action_item.status = ActionStatus.FAILED
                    act_type = act_def.action_type if act_def else None
                    if act_type in soft_continue_types and len(task.actions) > 1:
                        soft_warnings.append(f"{action_item.name}: {action_item.error or 'doğrulanamadı'}")
                        action_item.finished_at = datetime.now(timezone.utc)
                        await self.broadcast(AppEvent(type=EventType.ACTION_UPDATE, payload=action_item.model_dump(mode="json")))
                        continue
                    task.status = TaskStatus.FAILED
                    task.error = action_item.error
                    action_item.finished_at = datetime.now(timezone.utc)
                    await self.broadcast(AppEvent(type=EventType.ACTION_UPDATE, payload=action_item.model_dump(mode="json")))
                    break

                action_item.finished_at = datetime.now(timezone.utc)
                await self.broadcast(AppEvent(type=EventType.ACTION_UPDATE, payload=action_item.model_dump(mode="json")))

            # Clear cursor
            self.cached_cursor = CursorMarker(active=False, is_real_desktop=False)
            await self.broadcast(AppEvent(type=EventType.CURSOR_MARKER, payload=self.cached_cursor.model_dump()))

            if cancel_event.is_set():
                task.status = TaskStatus.CANCELLED
                task.result_summary = "Task was cancelled by user."
            elif task.status != TaskStatus.FAILED:
                task.status = TaskStatus.COMPLETED
                task.completed_at = datetime.now(timezone.utc)
                succeeded_count = sum(1 for a in task.actions if a.status == ActionStatus.SUCCEEDED)
                task.result_summary = (
                    f"Plan executed ({succeeded_count}/{len(task.actions)} succeeded; {len(soft_warnings)} warning(s))."
                    if soft_warnings
                    else "Plan executed successfully."
                )
                if not (plan and plan.llm_explanation and len(task.actions) <= 1):
                    if soft_warnings:
                        summary_lines = [
                            f"Plan tamamlandı ({succeeded_count}/{len(task.actions)} eylem doğrulandı, {len(soft_warnings)} yardımcı adım atlandı)."
                        ]
                    else:
                        summary_lines = [
                            f"Plan tamamlandı! Toplam {len(task.actions)} eylem başarıyla yürütüldü ve doğrulandı."
                        ]
                    if plan and plan.composition:
                        summary_lines.append(
                            f"• Besteci (Composer): {plan.composition.root} {plan.composition.scale} tonunda {plan.composition.bars} barlık akor, bas ve melodi üretildi."
                        )
                    if plan and plan.arrangement:
                        sec_names = " -> ".join(f"{s.name} ({s.bars} bar)" for s in plan.arrangement.sections)
                        summary_lines.append(f"• Aranjör (Arranger): {sec_names} (Toplam {plan.arrangement.total_bars} bar).")
                    if soft_warnings:
                        summary_lines.append(f"• Atlanan / Doğrulanamayan Adımlar: {'; '.join(soft_warnings[:4])}")
                    if plan and plan.remaining_limitations:
                        summary_lines.append(f"• Not / Sınırlamalar: {' '.join(plan.remaining_limitations)}")

                    await self.add_chat_message(
                        "assistant",
                        "\n".join(summary_lines),
                        task_id=task_id,
                        session_id=task.session_id,
                    )
                await self.refresh_project_context()

        except Exception as e:
            logger.error("Error executing task %s: %s", task_id, e, exc_info=True)
            task.status = TaskStatus.FAILED
            task.error = str(e)
            task.completed_at = datetime.now(timezone.utc)
            await self.add_chat_message("assistant", f"Task failed: {e}", task_id=task_id, session_id=task.session_id)

        finally:
            self._active_task_id = None
            self.db.save_task(
                task_id=task.task_id,
                prompt=task.prompt,
                status=task.status.value,
                is_mock=task.is_mock,
                created_at=task.created_at,
                completed_at=task.completed_at,
                result_summary=task.result_summary,
                error=task.error,
                session_id=task.session_id,
            )
            await self.broadcast(AppEvent(type=EventType.TASK_UPDATE, payload=task.model_dump(mode="json")))


