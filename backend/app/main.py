"""FastAPI Backend Server for FL Studio AI Assistant."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging
import os
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .schemas import (
    AppSettings,
    ChatMessage,
    ConnectionState,
    ProjectContextInfo,
    TaskCreateRequest,
    TaskResponse,
)
from .sessions import TaskExecutionManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("fl_assistant_backend")

# Global singleton execution manager
manager = TaskExecutionManager()
app_settings = AppSettings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing FL Studio AI Assistant Backend...")
    # Initial health check
    await manager.refresh_system_health()
    await manager.refresh_project_context()
    yield
    logger.info("Shutting down FL Studio AI Assistant Backend...")
    manager.fl_adapter.disconnect()
    manager.hcu_adapter.stop()


app = FastAPI(
    title="FL Studio AI Assistant Backend",
    version="0.2.0",
    description="Backend API and WebSocket event streaming for FL Studio AI Assistant companion",
    lifespan=lifespan,
)

# CORS configuration for desktop frontend (Vite/Tauri)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -- WebSocket Endpoint ------------------------------------------------------

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect_client(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # Handle client-to-server WS actions if needed
            logger.debug("Received WS message: %s", data)
    except WebSocketDisconnect:
        manager.disconnect_client(websocket)
    except Exception as e:
        logger.warning("WS connection error: %s", e)
        manager.disconnect_client(websocket)


# -- Health & Context Endpoints ----------------------------------------------

@app.get("/api/health", response_model=ConnectionState)
async def get_health():
    return manager.cached_connection


@app.post("/api/health/refresh", response_model=ConnectionState)
async def refresh_health():
    state = await manager.refresh_system_health()
    await manager.refresh_project_context()
    return state


@app.get("/api/context", response_model=ProjectContextInfo)
async def get_context():
    return manager.cached_project


@app.post("/api/context/refresh", response_model=ProjectContextInfo)
async def refresh_context():
    return await manager.refresh_project_context()


# -- Task Management Endpoints -----------------------------------------------

@app.get("/api/tasks", response_model=List[TaskResponse])
async def list_tasks():
    return manager.list_tasks()


@app.post("/api/tasks", response_model=TaskResponse)
async def submit_task(request: TaskCreateRequest):
    return await manager.submit_task(prompt=request.prompt, is_mock=request.is_mock)


@app.get("/api/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: str):
    task = manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.post("/api/tasks/{task_id}/stop")
async def stop_task(task_id: str):
    success = await manager.stop_active_task(task_id)
    return {"task_id": task_id, "stopped": success}


@app.post("/api/tasks/stop-active")
async def stop_active_task():
    success = await manager.stop_active_task()
    return {"stopped": success}


# -- Chat Endpoints ----------------------------------------------------------

class SendMessageRequest(BaseModel):
    text: str


@app.get("/api/chat/messages", response_model=List[ChatMessage])
async def get_messages():
    return manager.get_messages()


@app.post("/api/chat/messages", response_model=ChatMessage)
async def send_chat_message(req: SendMessageRequest):
    # If it's a command/request from user, also trigger task submission
    task = await manager.submit_task(prompt=req.text, is_mock=True)
    return manager.get_messages()[-1]


# -- Settings Endpoints ------------------------------------------------------

@app.get("/api/settings", response_model=AppSettings)
async def get_settings():
    return app_settings


@app.put("/api/settings", response_model=AppSettings)
async def update_settings(new_settings: AppSettings):
    global app_settings
    app_settings = new_settings
    return app_settings


# -- Screen & Preview Endpoints ----------------------------------------------

@app.post("/api/screen/capture")
async def capture_screen():
    res = await manager.hcu_adapter.async_capture_screenshot()
    return {"success": res.success, "width": res.width, "height": res.height, "error": res.error}

