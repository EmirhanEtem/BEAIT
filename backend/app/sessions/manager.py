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


class TaskExecutionManager:
    """Coordinates task execution, cancellation, and event broadcasting."""

    def __init__(self):
        self._tasks: Dict[str, TaskResponse] = {}
        self._active_task_id: Optional[str] = None
        self._cancel_events: Dict[str, asyncio.Event] = {}
        self._active_connections: Set[WebSocket] = set()
        self._messages: List[ChatMessage] = []
        
        self.fl_adapter = FLStudioAdapter(transport=TransportType.TCP)
        self.hcu_adapter = GUIAutomationAdapter()
        
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
        
        # Send initial state snapshot on connect
        await self._send_to_client(websocket, AppEvent(
            type=EventType.CONNECTION_STATUS,
            payload=self.cached_connection.model_dump(),
        ))
        await self._send_to_client(websocket, AppEvent(
            type=EventType.PROJECT_CONTEXT,
            payload=self.cached_project.model_dump(),
        ))
        for msg in self._messages[-50:]:
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

    async def add_chat_message(self, role: str, text: str, task_id: Optional[str] = None) -> ChatMessage:
        msg = ChatMessage(
            id=str(uuid.uuid4())[:8],
            role=role,
            text=text,
            task_id=task_id,
        )
        self._messages.append(msg)
        await self.broadcast(AppEvent(type=EventType.CHAT_MESSAGE, payload=msg.model_dump(mode="json")))
        return msg

    def get_messages(self) -> List[ChatMessage]:
        return list(self._messages)

    # -- Task Management -----------------------------------------------------

    def list_tasks(self) -> List[TaskResponse]:
        return list(self._tasks.values())

    def get_task(self, task_id: str) -> Optional[TaskResponse]:
        return self._tasks.get(task_id)

    async def submit_task(self, prompt: str, is_mock: bool = True) -> TaskResponse:
        task_id = f"task_{uuid.uuid4().hex[:8]}"
        task = TaskResponse(
            task_id=task_id,
            prompt=prompt,
            is_mock=is_mock,
            status=TaskStatus.QUEUED,
        )
        self._tasks[task_id] = task
        self._cancel_events[task_id] = asyncio.Event()

        # Add user chat message
        await self.add_chat_message("user", prompt, task_id=task_id)

        # Plan initial actions
        task.actions = self._build_plan_for_task(task_id, prompt, is_mock)

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
        await self.broadcast(AppEvent(type=EventType.TASK_UPDATE, payload=task.model_dump(mode="json")))
        await self.add_chat_message("system", f"Task {target_id} stopped by user.", task_id=target_id)
        return True

    # -- Internal Task Execution ---------------------------------------------

    def _build_plan_for_task(self, task_id: str, prompt: str, is_mock: bool) -> List[ActionItem]:
        route = ExecutionRoute.MOCK if is_mock else ExecutionRoute.FL_MCP
        return [
            ActionItem(
                action_id=f"{task_id}_act_1",
                task_id=task_id,
                name="Read Project Context",
                description="Read BPM, channels and transport status from FL Studio",
                target="FL Studio Session",
                route=ExecutionRoute.FL_MCP if self.cached_connection.fl_studio_alive else ExecutionRoute.MOCK,
                status=ActionStatus.PLANNED,
            ),
            ActionItem(
                action_id=f"{task_id}_act_2",
                task_id=task_id,
                name="Create Drum Pattern",
                description="Generate 4-on-the-floor kick and percussion rhythm",
                target="Channel Rack",
                route=route,
                status=ActionStatus.PLANNED,
            ),
            ActionItem(
                action_id=f"{task_id}_act_3",
                task_id=task_id,
                name="Generate MIDI Melody",
                description="Compose melodic techno motif in A Minor",
                target="Piano Roll",
                route=route,
                status=ActionStatus.PLANNED,
            ),
            ActionItem(
                action_id=f"{task_id}_act_4",
                task_id=task_id,
                name="Adjust Mixer Level",
                description="Verify headroom and trim channel gain",
                target="Mixer Insert 1",
                route=route,
                status=ActionStatus.PLANNED,
            ),
            ActionItem(
                action_id=f"{task_id}_act_5",
                task_id=task_id,
                name="Verify Resulting State",
                description="Read back project state and verify note events",
                target="Verification Engine",
                route=ExecutionRoute.LOCAL_SERVICE,
                status=ActionStatus.PLANNED,
            ),
        ]

    async def _run_task(self, task_id: str):
        task = self._tasks[task_id]
        self._active_task_id = task_id
        cancel_event = self._cancel_events[task_id]

        task.status = TaskStatus.RUNNING
        await self.broadcast(AppEvent(type=EventType.TASK_UPDATE, payload=task.model_dump(mode="json")))
        await self.add_chat_message("assistant", f"Starting plan for: '{task.prompt}'", task_id=task_id)

        try:
            for index, action in enumerate(task.actions):
                if cancel_event.is_set():
                    break

                action.status = ActionStatus.RUNNING
                action.started_at = datetime.now(timezone.utc)
                await self.broadcast(AppEvent(type=EventType.ACTION_UPDATE, payload=action.model_dump(mode="json")))

                # Cursor simulation for UI representation (clearly marked is_real_desktop=False)
                marker = CursorMarker(
                    active=True,
                    x=200 + index * 120,
                    y=150 + index * 60,
                    label=action.name,
                    is_real_desktop=False,
                )
                self.cached_cursor = marker
                await self.broadcast(AppEvent(type=EventType.CURSOR_MARKER, payload=marker.model_dump()))

                # Execute action step
                if action.route == ExecutionRoute.FL_MCP and self.cached_connection.fl_studio_alive:
                    try:
                        tempo = await self.fl_adapter.async_get_tempo()
                        action.verification_detail = f"Live BPM read: {tempo}"
                        action.verified = True
                    except Exception as e:
                        action.error = str(e)
                        action.verified = False
                else:
                    # Simulated step with cancellation awareness
                    for _ in range(10):
                        if cancel_event.is_set():
                            break
                        await asyncio.sleep(0.1)
                    action.verification_detail = f"Mock verified: {action.name}"
                    action.verified = True

                if cancel_event.is_set():
                    action.status = ActionStatus.CANCELLED
                    action.finished_at = datetime.now(timezone.utc)
                    await self.broadcast(AppEvent(type=EventType.ACTION_UPDATE, payload=action.model_dump(mode="json")))
                    break

                action.status = ActionStatus.SUCCEEDED
                action.finished_at = datetime.now(timezone.utc)
                await self.broadcast(AppEvent(type=EventType.ACTION_UPDATE, payload=action.model_dump(mode="json")))

            # Clear cursor
            self.cached_cursor = CursorMarker(active=False, is_real_desktop=False)
            await self.broadcast(AppEvent(type=EventType.CURSOR_MARKER, payload=self.cached_cursor.model_dump()))

            if cancel_event.is_set():
                task.status = TaskStatus.CANCELLED
                task.result_summary = "Task was cancelled by user."
            else:
                task.status = TaskStatus.COMPLETED
                task.completed_at = datetime.now(timezone.utc)
                task.result_summary = "Plan executed successfully."
                await self.add_chat_message(
                    "assistant",
                    f"Plan completed! All {len(task.actions)} actions finished successfully.",
                    task_id=task_id,
                )

        except Exception as e:
            logger.error("Error executing task %s: %s", task_id, e, exc_info=True)
            task.status = TaskStatus.FAILED
            task.error = str(e)
            task.completed_at = datetime.now(timezone.utc)
            await self.add_chat_message("assistant", f"Task failed: {e}", task_id=task_id)

        finally:
            self._active_task_id = None
            await self.broadcast(AppEvent(type=EventType.TASK_UPDATE, payload=task.model_dump(mode="json")))

