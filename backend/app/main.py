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

from dataclasses import asdict
from .agents import CriticAgent
from .config import PrivacySafeLogExporter, SystemDiagnosticsService
from .integrations.audio import AudioAnalyzer
from .integrations.filesystem import SampleScanner
from .music_engine import GenrePresetRegistry
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

def _build_initial_app_settings() -> AppSettings:
    from .model_providers import DEFAULT_GEMINI_MODEL, ProviderConfig

    configured = ProviderConfig.all_configured_from_env()
    primary = configured[0] if configured else ProviderConfig.from_env()
    gem_cfg = ProviderConfig.from_env("gemini")
    oa_cfg = ProviderConfig.from_env("openai")
    anth_cfg = ProviderConfig.from_env("anthropic")
    loc_cfg = ProviderConfig.from_env("local")
    gem_model = gem_cfg.model_name
    if gem_model in ("gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3.1-pro-preview"):
        gem_model = DEFAULT_GEMINI_MODEL
    return AppSettings(
        llm_provider=primary.provider_name,
        openai_model=oa_cfg.model_name,
        openai_base_url=oa_cfg.base_url,
        gemini_model=gem_model,
        anthropic_model=anth_cfg.model_name,
        local_model_url=loc_cfg.base_url,
        local_model_name=loc_cfg.model_name,
    )


def _apply_settings_to_manager(new_settings: AppSettings) -> None:
    from .model_providers import ProviderConfig

    cfg = ProviderConfig.from_env(provider_override=new_settings.llm_provider)
    prov = (new_settings.llm_provider or "openai").lower()
    if prov == "openai":
        cfg.model_name = new_settings.openai_model
        cfg.base_url = new_settings.openai_base_url
    elif prov == "gemini":
        cfg.model_name = new_settings.gemini_model
    elif prov == "anthropic":
        cfg.model_name = new_settings.anthropic_model
    elif prov == "local":
        cfg.model_name = new_settings.local_model_name
        cfg.base_url = new_settings.local_model_url
    manager.orchestrator.model_provider.config = cfg
    if getattr(manager.orchestrator.executor, "approval_manager", None) is not None:
        manager.orchestrator.executor.approval_manager.safe_mode = new_settings.safe_mode


# Global singleton execution manager
manager = TaskExecutionManager()
app_settings = _build_initial_app_settings()
_apply_settings_to_manager(app_settings)
diagnostics_service = SystemDiagnosticsService(
    fl_adapter=manager.fl_adapter,
    hcu_adapter=manager.hcu_adapter,
)


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
    if not manager.cached_connection.fl_studio_alive or not manager.cached_connection.hcu_available:
        await manager.refresh_system_health()
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
async def list_tasks(session_id: Optional[str] = None):
    return manager.list_tasks(session_id=session_id)


@app.post("/api/tasks", response_model=TaskResponse)
async def submit_task(request: TaskCreateRequest):
    return await manager.submit_task(
        prompt=request.prompt,
        is_mock=request.is_mock,
        session_id=request.session_id,
    )


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

from .schemas.tasks import ChatSession, ChatSessionCreateRequest, ChatSessionUpdateRequest


class SendMessageRequest(BaseModel):
    text: str
    session_id: Optional[str] = None
    is_mock: bool = True


@app.get("/api/chat/messages", response_model=List[ChatMessage])
async def get_messages(session_id: Optional[str] = None):
    return manager.get_messages(session_id=session_id)


@app.post("/api/chat/messages", response_model=ChatMessage)
async def send_chat_message(req: SendMessageRequest):
    # If it's a command/request from user, also trigger task submission
    task = await manager.submit_task(
        prompt=req.text,
        is_mock=req.is_mock,
        session_id=req.session_id,
    )
    msgs = manager.get_messages(session_id=task.session_id)
    if not msgs:
        raise HTTPException(status_code=500, detail="Message creation failed")
    return msgs[-1]


@app.get("/api/chats", response_model=List[ChatSession])
async def list_chat_sessions():
    return manager.list_sessions()


@app.post("/api/chats", response_model=ChatSession)
async def create_chat_session(req: Optional[ChatSessionCreateRequest] = None):
    title = req.title if req else None
    return manager.create_session(title=title)


@app.get("/api/chats/{session_id}", response_model=ChatSession)
async def get_chat_session(session_id: str):
    sess = manager.get_session(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return sess


@app.patch("/api/chats/{session_id}", response_model=ChatSession)
async def rename_chat_session(session_id: str, req: ChatSessionUpdateRequest):
    sess = await manager.rename_session(session_id, req.title)
    if not sess:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return sess


@app.delete("/api/chats/{session_id}")
async def delete_chat_session(session_id: str):
    if not manager.get_session(session_id):
        raise HTTPException(status_code=404, detail="Chat session not found")
    deleted = manager.delete_session(session_id)
    return {
        "deleted": deleted,
        "sessions": [s.model_dump(mode="json") for s in manager.list_sessions()],
        "active_session_id": manager._active_session_id,
    }


@app.get("/api/chats/{session_id}/messages", response_model=List[ChatMessage])
async def get_chat_session_messages(session_id: str):
    if not manager.get_session(session_id):
        raise HTTPException(status_code=404, detail="Chat session not found")
    manager._active_session_id = session_id
    manager._messages = manager.get_messages(session_id=session_id)
    return manager._messages


@app.post("/api/chats/{session_id}/select", response_model=ChatSession)
async def select_chat_session(session_id: str):
    sess = manager.get_session(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Chat session not found")
    manager._active_session_id = session_id
    manager._messages = manager.get_messages(session_id=session_id)
    return sess


# -- Settings Endpoints ------------------------------------------------------

@app.get("/api/settings", response_model=AppSettings)
async def get_settings():
    return app_settings


@app.put("/api/settings", response_model=AppSettings)
async def update_settings(new_settings: AppSettings):
    global app_settings
    app_settings = new_settings
    _apply_settings_to_manager(new_settings)
    return app_settings


class ModelTestRequest(BaseModel):
    provider: str = "gemini"
    model: str = ""
    base_url: Optional[str] = None


@app.get("/api/providers/models")
async def get_provider_models(provider: Optional[str] = None, live: bool = True):
    from .model_providers import list_available_models
    target_provider = (provider or app_settings.llm_provider or "openai").lower()
    base_url = None
    if target_provider == "openai":
        base_url = app_settings.openai_base_url
    elif target_provider == "local":
        base_url = app_settings.local_model_url
    return await asyncio.to_thread(
        list_available_models,
        target_provider,
        base_url=base_url,
        live=live,
    )


@app.post("/api/providers/test-model")
async def test_selected_model(req: ModelTestRequest):
    from .model_providers import test_provider_model
    return await asyncio.to_thread(
        test_provider_model,
        req.provider,
        req.model,
        base_url=req.base_url,
    )


# -- Screen & Preview Endpoints ----------------------------------------------

@app.post("/api/screen/capture")
async def capture_screen():
    res = await manager.hcu_adapter.async_capture_screenshot()
    return {"success": res.success, "width": res.width, "height": res.height, "error": res.error}


# -- Diagnostics & Log Export Endpoints (Phase 9) ----------------------------

@app.get("/api/diagnostics")
async def get_diagnostics():
    report = diagnostics_service.run_diagnostics(probe_live_fl=False)
    return report.to_dict()


class LogExportRequest(BaseModel):
    output_path: str


@app.post("/api/logs/export")
async def export_logs(req: LogExportRequest):
    report = diagnostics_service.run_diagnostics(probe_live_fl=False)
    written_path = PrivacySafeLogExporter.export_sanitized_logs(
        req.output_path,
        diagnostics=report,
        memory=manager.orchestrator.memory,
    )
    return {"exported": True, "path": written_path}


# -- Production Engine, Audio Analysis & Sample Scanner Endpoints ------------

@app.get("/api/presets")
async def list_genre_presets():
    registry = GenrePresetRegistry()
    return {
        "stylistic_disclaimer": registry.disclaimer,
        "presets": [p.model_dump() for p in registry.list_presets()],
    }


class ProductionPlanRequest(BaseModel):
    prompt: str
    dry_run: bool = True
    midi_export_dir: Optional[str] = None


@app.post("/api/production/plan")
async def create_production_plan(req: ProductionPlanRequest):
    plan = manager.orchestrator.create_plan(
        req.prompt,
        dry_run=req.dry_run,
        midi_export_dir=req.midi_export_dir,
    )
    return {
        "plan_id": plan.plan_id,
        "task_id": plan.task_id,
        "dry_run": plan.dry_run,
        "requires_approval": plan.requires_approval,
        "parsed_intent": asdict(plan.parsed_intent) if plan.parsed_intent else None,
        "actions": [a.model_dump(mode="json") for a in plan.actions],
        "arrangement": asdict(plan.arrangement) if plan.arrangement else None,
        "remaining_limitations": plan.remaining_limitations,
        "prompt_disclosure": asdict(plan.prompt_disclosure) if plan.prompt_disclosure else None,
    }


class AudioAnalyzeRequest(BaseModel):
    file_path: str
    expected_duration_seconds: Optional[float] = None


@app.post("/api/audio/analyze")
async def analyze_audio_render(req: AudioAnalyzeRequest):
    analysis = AudioAnalyzer().analyze_file(req.file_path)
    critic_report = CriticAgent().evaluate_render(
        analysis,
        expected_duration_seconds=req.expected_duration_seconds,
    )
    return {
        "analysis": analysis.to_dict(),
        "critic_feedback": {
            "render_valid": critic_report.render_valid,
            "overall_health": critic_report.overall_health,
            "measured_findings": [asdict(f) for f in critic_report.measured_findings],
            "subjective_recommendations": critic_report.subjective_recommendations,
            "proposed_revisions": [r.model_dump(mode="json") for r in critic_report.proposed_revisions],
            "requires_user_approval_for_revisions": critic_report.requires_user_approval_for_revisions,
            "objectivity_disclaimer": critic_report.objectivity_disclaimer,
        },
    }


class SampleScanRequest(BaseModel):
    directory: str
    approved_directories: List[str]
    category_filter: Optional[str] = None


@app.post("/api/samples/scan")
async def scan_samples_endpoint(req: SampleScanRequest):
    scanner = SampleScanner(approved_directories=req.approved_directories)
    try:
        samples = scanner.scan_directory(req.directory, category_filter=req.category_filter)
        return {"count": len(samples), "samples": [asdict(s) for s in samples]}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/api/memory/history")
async def get_memory_history():
    mem = manager.orchestrator.memory
    return {
        "preferences": asdict(mem.preferences),
        "recent_summaries": [asdict(s) for s in mem.get_recent_summaries()],
    }



