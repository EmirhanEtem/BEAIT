"""Event schemas for WebSocket streaming and desktop companion UI."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class EventType(str, Enum):
    CONNECTION_STATUS = "connection_status"
    PROJECT_CONTEXT = "project_context"
    CHAT_MESSAGE = "chat_message"
    TASK_UPDATE = "task_update"
    ACTION_UPDATE = "action_update"
    CURSOR_MARKER = "cursor_marker"
    SCREEN_PREVIEW = "screen_preview"
    NOTIFICATION = "notification"


class ActionStatus(str, Enum):
    PLANNED = "PLANNED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    READY = "READY"
    RUNNING = "RUNNING"
    VERIFYING = "VERIFYING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    SKIPPED = "SKIPPED"


class TaskStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ExecutionRoute(str, Enum):
    FL_MCP = "FL_MCP"
    GUI_AUTOMATION = "GUI_AUTOMATION"
    LOCAL_SERVICE = "LOCAL_SERVICE"
    MOCK = "MOCK"


class ActionItem(BaseModel):
    action_id: str
    task_id: str
    name: str
    description: str
    target: str = ""
    route: ExecutionRoute = ExecutionRoute.MOCK
    status: ActionStatus = ActionStatus.PLANNED
    risk_level: str = "low"  # low, medium, high
    requires_approval: bool = False
    verified: Optional[bool] = None
    verification_detail: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error: Optional[str] = None


class CursorMarker(BaseModel):
    active: bool = False
    x: Optional[float] = None
    y: Optional[float] = None
    label: Optional[str] = None
    is_real_desktop: bool = False  # Mandatory rule: accurately report whether real cursor moved or UI visualization only


class ChatMessage(BaseModel):
    id: str
    role: str  # user, assistant, system
    text: str
    task_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ConnectionState(BaseModel):
    backend_online: bool = True
    fl_mcp_connected: bool = False
    fl_studio_alive: bool = False
    fl_heartbeat_age: Optional[float] = None
    hcu_available: bool = False
    hcu_version: Optional[str] = None
    error_message: Optional[str] = None


class ProjectContextInfo(BaseModel):
    connected: bool = False
    title: Optional[str] = None  # None indicates explicitly unknown
    fl_version: Optional[str] = None
    tempo: Optional[float] = None
    time_signature: Optional[str] = None  # None indicates explicitly unknown
    playing: Optional[bool] = None
    recording: Optional[bool] = None
    channels: List[Dict[str, Any]] = Field(default_factory=list)
    mixer_tracks: List[Dict[str, Any]] = Field(default_factory=list)
    patterns: List[Dict[str, Any]] = Field(default_factory=list)


class AppEvent(BaseModel):
    type: EventType
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: Dict[str, Any]

