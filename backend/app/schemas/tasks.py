"""Task and session schemas."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from .events import ActionItem, TaskStatus


class TaskCreateRequest(BaseModel):
    prompt: str
    is_mock: bool = False
    session_id: Optional[str] = None
    parameters: Dict[str, Any] = Field(default_factory=dict)


class TaskResponse(BaseModel):
    task_id: str
    session_id: Optional[str] = None
    prompt: str
    status: TaskStatus = TaskStatus.QUEUED
    is_mock: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    actions: List[ActionItem] = Field(default_factory=list)
    result_summary: Optional[str] = None
    error: Optional[str] = None


class ChatSession(BaseModel):
    session_id: str
    title: str = "Yeni Sohbet"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    message_count: int = 0
    last_message_preview: Optional[str] = None


class ChatSessionCreateRequest(BaseModel):
    title: Optional[str] = None


class ChatSessionUpdateRequest(BaseModel):
    title: str


class SessionInfo(BaseModel):
    session_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    active_task_id: Optional[str] = None

