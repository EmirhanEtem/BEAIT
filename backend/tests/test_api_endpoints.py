"""Backend API and WebSocket integration tests for Phase 2."""

import pytest
import sys
import os
import json
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.main import app, manager
from app.schemas import TaskStatus, ActionStatus


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_get_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert "backend_online" in data
    assert data["backend_online"] is True
    assert "fl_mcp_connected" in data
    assert "hcu_available" in data


def test_get_context(client):
    response = client.get("/api/context")
    assert response.status_code == 200
    data = response.json()
    assert "connected" in data
    assert "channels" in data
    assert "mixer_tracks" in data


def test_get_and_update_settings(client):
    # GET settings
    response = client.get("/api/settings")
    assert response.status_code == 200
    original = response.json()
    assert original["language"] in ("tr", "en")

    # PUT settings
    updated_payload = dict(original)
    updated_payload["language"] = "en"
    updated_payload["openai_model"] = "gpt-4o-mini"
    
    put_res = client.put("/api/settings", json=updated_payload)
    assert put_res.status_code == 200
    res_data = put_res.json()
    assert res_data["language"] == "en"
    assert res_data["openai_model"] == "gpt-4o-mini"

    # Restore
    client.put("/api/settings", json=original)


def test_submit_task_and_list(client):
    req = {
        "prompt": "Create 128 BPM Techno Intro",
        "is_mock": True,
    }
    response = client.post("/api/tasks", json=req)
    assert response.status_code == 200
    task_data = response.json()
    assert task_data["prompt"] == req["prompt"]
    assert task_data["status"] in (TaskStatus.QUEUED.value, TaskStatus.RUNNING.value)
    assert len(task_data["actions"]) >= 1
    assert task_data["is_mock"] is True

    # Check list
    list_res = client.get("/api/tasks")
    assert list_res.status_code == 200
    tasks = list_res.json()
    assert any(t["task_id"] == task_data["task_id"] for t in tasks)


def test_stop_active_task(client):
    req = {
        "prompt": "Long running test task to cancel",
        "is_mock": True,
    }
    submit_res = client.post("/api/tasks", json=req)
    assert submit_res.status_code == 200
    task_id = submit_res.json()["task_id"]

    # Global stop control
    stop_res = client.post("/api/tasks/stop-active")
    assert stop_res.status_code == 200
    assert stop_res.json()["stopped"] is True

    # Verify task status is cancelled
    detail_res = client.get(f"/api/tasks/{task_id}")
    assert detail_res.status_code == 200
    assert detail_res.json()["status"] == TaskStatus.CANCELLED.value


def test_websocket_streaming(client):
    with client.websocket_connect("/ws") as websocket:
        # First message should be connection status snapshot
        data1 = websocket.receive_json()
        assert data1["type"] == "connection_status"
        assert "payload" in data1
        assert data1["payload"]["backend_online"] is True

        # Second message should be project context snapshot
        data2 = websocket.receive_json()
        assert data2["type"] == "project_context"
        assert "payload" in data2

