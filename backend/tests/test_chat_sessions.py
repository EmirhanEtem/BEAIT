"""Tests for multi-chat session persistence, REST endpoints, and per-chat isolated AI memory."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.database.persistence import DatabaseManager
from app.model_providers.provider import (
    ModelProviderAdapter,
    _format_api_chat_messages,
    normalize_llm_plan,
)
from app.sessions.manager import TaskExecutionManager


def _sample_ai_plan(
    *,
    ai_response: str = "Hazır! İstediğin beat kuruldu.",
    genre: str = "phonk",
    bpm: float = 130.0,
    key: str = "F#",
    scale: str = "harmonic_minor",
):
    return normalize_llm_plan(
        {
            "ai_response": ai_response,
            "intent_type": "full_production",
            "genre": genre,
            "mood": "dark",
            "tempo_bpm": bpm,
            "key": key,
            "scale": scale,
            "chord_progression": [f"{key}m", "D", "E", "C#"],
            "sections": [
                {"name": "Intro", "bars": 4, "mode": "ambient", "roles": ["chords"]},
                {"name": "Drop", "bars": 8, "mode": "full", "roles": ["drums", "chords", "bass", "lead"]},
            ],
            "drum_channels": [
                {"channel": 0, "name": "Kick", "steps": [0, 6, 10], "length": 16, "velocity": 0.92},
                {"channel": 1, "name": "Clap", "steps": [4, 12], "length": 16, "velocity": 0.88},
            ],
            "tracks": [
                {
                    "role": "chords",
                    "instrument_name": "FL Keys",
                    "preset_hint": "Dark Piano",
                    "notes": [
                        {"pitch": 54, "time_bars": 0.0, "length_bars": 0.5, "velocity": 0.78},
                        {"pitch": 57, "time_bars": 0.5, "length_bars": 0.5, "velocity": 0.74},
                        {"pitch": 61, "time_bars": 1.0, "length_bars": 0.5, "velocity": 0.76},
                        {"pitch": 54, "time_bars": 2.0, "length_bars": 0.5, "velocity": 0.78},
                    ],
                },
                {
                    "role": "bass",
                    "instrument_name": "3x Osc",
                    "preset_hint": "Sub 808",
                    "notes": [
                        {"pitch": 30, "time_bars": 0.0, "length_bars": 0.5, "velocity": 0.94},
                        {"pitch": 30, "time_bars": 1.5, "length_bars": 0.5, "velocity": 0.9},
                    ],
                },
                {
                    "role": "lead",
                    "instrument_name": "Sytrus",
                    "preset_hint": "Bell Lead",
                    "notes": [
                        {"pitch": 66, "time_bars": 0.0, "length_bars": 0.25, "velocity": 0.86},
                        {"pitch": 69, "time_bars": 0.5, "length_bars": 0.25, "velocity": 0.84},
                        {"pitch": 73, "time_bars": 1.0, "length_bars": 0.25, "velocity": 0.88},
                    ],
                },
            ],
            "play_state": "play",
        },
        plan_source="ai_api",
        provider_name="gemini",
        model_name="gemini-2.5-flash",
    )


def test_database_multi_chat_persistence_roundtrip(tmp_path):
    db_file = tmp_path / "multi_chat.db"
    db = DatabaseManager(db_path=str(db_file))

    db.create_chat_session("chat_a", title="Phonk Denemesi")
    db.create_chat_session("chat_b", title="Deep House")

    same_ts = datetime(2026, 11, 15, 10, 0, 0, tzinfo=timezone.utc)
    db.save_chat_message("m1", "chat_a", "user", "130 bpm phonk yap", created_at=same_ts)
    db.save_chat_message("m2", "chat_a", "assistant", "130 BPM Phonk hazırlandı", created_at=same_ts)
    db.save_chat_message("m3", "chat_b", "user", "124 bpm house yap", created_at=same_ts)

    db.save_session_plan_memory("chat_a", {"genre": "phonk", "tempo_bpm": 130.0, "key": "F#"})

    # Task session_id must survive subsequent status updates where session_id is omitted
    db.save_task("t1", "130 bpm phonk", "QUEUED", True, session_id="chat_a")
    db.save_task("t1", "130 bpm phonk", "COMPLETED", True, result_summary="OK")

    reloaded = DatabaseManager(db_path=str(db_file))
    msgs_a = reloaded.list_chat_messages("chat_a")
    msgs_b = reloaded.list_chat_messages("chat_b")

    assert [m["id"] for m in msgs_a] == ["m1", "m2"]
    assert [m["id"] for m in msgs_b] == ["m3"]
    assert reloaded.list_session_plan_memory("chat_a") == [{"genre": "phonk", "tempo_bpm": 130.0, "key": "F#"}]
    assert reloaded.list_session_plan_memory("chat_b") == []

    tasks_a = reloaded.list_tasks_for_session("chat_a")
    assert len(tasks_a) == 1
    assert tasks_a[0]["status"] == "COMPLETED"
    assert tasks_a[0]["session_id"] == "chat_a"

    assert reloaded.delete_chat_session("chat_a") is True
    assert reloaded.get_chat_session("chat_a") is None
    assert reloaded.list_chat_messages("chat_a") == []
    assert reloaded.list_session_plan_memory("chat_a") == []
    assert len(reloaded.list_chat_messages("chat_b")) == 1


def test_model_provider_chat_turn_formatting_and_disclosure():
    turns = _format_api_chat_messages(
        [
            {"role": "assistant", "text": "Merhaba"},  # leading assistant trimmed
            {"role": "user", "text": "130 bpm phonk yap"},
            {"role": "assistant", "text": "Phonk beat yapıldı."},
            {"role": "assistant", "text": "Plan tamamlandı!"},  # merged into single model turn
            {"role": "user", "text": "yarım kalmış mesaj"},  # folded into final user turn
        ],
        "bası güçlendir",
        assistant_role="model",
    )
    roles = [r for r, _ in turns]
    assert roles == ["user", "model", "user"]
    assert "Phonk beat yapıldı." in turns[1][1]
    assert "Plan tamamlandı!" in turns[1][1]
    assert "yarım kalmış mesaj" in turns[2][1]
    assert "bası güçlendir" in turns[2][1]

    adapter = ModelProviderAdapter()
    fresh_env = adapter.build_context_prompt(
        user_prompt="124 bpm deep house yap",
        recent_history=[],
        conversation_history=[],
    )
    assert "conversation_history" not in fresh_env.disclosed_fields
    assert "recent_history" not in fresh_env.disclosed_fields

    active_env = adapter.build_context_prompt(
        user_prompt="buna akor ekle",
        recent_history=[{"prompt": "130 bpm phonk", "genre": "phonk", "tempo_bpm": 130.0, "key": "F#"}],
        conversation_history=[
            {"role": "user", "text": "130 bpm phonk yap"},
            {"role": "assistant", "text": "F# harmonic minor tonunda phonk hazır."},
        ],
    )
    assert "conversation_history" in active_env.disclosed_fields
    assert "recent_history" in active_env.disclosed_fields
    assert "F# harmonic minor tonunda phonk hazır." in active_env.prompt_text


@pytest.mark.asyncio
async def test_manager_per_chat_ai_memory_and_clean_reset(tmp_path):
    db_file = str(tmp_path / "manager_chats.db")
    mgr = TaskExecutionManager(db_path=db_file)

    real_adapter = ModelProviderAdapter()
    calls = []

    def fake_generate(
        user_prompt,
        project_context=None,
        recent_history=None,
        user_preferences=None,
        allow_in_pytest=False,
        conversation_history=None,
    ):
        calls.append(
            {
                "user_prompt": user_prompt,
                "recent_history": list(recent_history or []),
                "conversation_history": list(conversation_history or []),
            }
        )
        if "house" in user_prompt.lower():
            return _sample_ai_plan(ai_response="124 BPM C dorian house hazır.", genre="house", bpm=124.0, key="C", scale="dorian")
        return _sample_ai_plan(ai_response="130 BPM F# phonk hazır.", genre="phonk", bpm=130.0, key="F#", scale="harmonic_minor")

    mock_provider = MagicMock(spec=ModelProviderAdapter)
    mock_provider.build_context_prompt.side_effect = real_adapter.build_context_prompt
    mock_provider.generate_music_plan.side_effect = fake_generate
    mgr.orchestrator.model_provider = mock_provider

    # Chat A: turn 1
    chat_a = mgr.create_session()
    t1 = await mgr.submit_task("130 bpm karanlık phonk beat yap", is_mock=True, session_id=chat_a.session_id)
    for _ in range(40):
        if mgr.get_task(t1.task_id).status.value == "COMPLETED":
            break
        await asyncio.sleep(0.05)

    assert len(calls) == 1
    assert calls[0]["conversation_history"] == []
    assert calls[0]["recent_history"] == []

    sess_a_after = mgr.get_session(chat_a.session_id)
    assert sess_a_after is not None
    assert "phonk" in sess_a_after.title.lower()

    # Chat A: turn 2 must remember Chat A turns & musical plan
    t2 = await mgr.submit_task("bası daha sert yap ve melodi ekle", is_mock=True, session_id=chat_a.session_id)
    for _ in range(40):
        if mgr.get_task(t2.task_id).status.value == "COMPLETED":
            break
        await asyncio.sleep(0.05)

    assert len(calls) == 2
    assert len(calls[1]["recent_history"]) == 1
    assert calls[1]["recent_history"][0]["genre"] == "phonk"
    assert any("130 bpm karanlık phonk" in turn["text"] for turn in calls[1]["conversation_history"])
    assert any("130 BPM F# phonk hazır" in turn["text"] for turn in calls[1]["conversation_history"])

    # Chat B: brand new session must start from scratch ("sıfırdan başlasın")
    chat_b = mgr.create_session()
    assert mgr.get_messages(chat_b.session_id) == []

    t3 = await mgr.submit_task("124 bpm deep house beat yap", is_mock=True, session_id=chat_b.session_id)
    for _ in range(40):
        if mgr.get_task(t3.task_id).status.value == "COMPLETED":
            break
        await asyncio.sleep(0.05)

    assert len(calls) == 3
    assert calls[2]["conversation_history"] == []
    assert calls[2]["recent_history"] == []

    # Simulate backend restart: Chat A still remembers Chat A after reload
    restarted = TaskExecutionManager(db_path=db_file)
    restarted.orchestrator.model_provider = mock_provider
    restored_sessions = {s.session_id: s for s in restarted.list_sessions()}
    assert chat_a.session_id in restored_sessions
    assert chat_b.session_id in restored_sessions

    t4 = await restarted.submit_task("tekrar yap", is_mock=True, session_id=chat_a.session_id)
    for _ in range(40):
        if restarted.get_task(t4.task_id).status.value == "COMPLETED":
            break
        await asyncio.sleep(0.05)

    assert len(calls) == 4
    assert calls[3]["user_prompt"] == "bası daha sert yap ve melodi ekle"
    assert len(calls[3]["recent_history"]) >= 1
    assert all("house" not in turn["text"].lower() for turn in calls[3]["conversation_history"])


def test_fastapi_multi_chat_rest_endpoints(tmp_path, monkeypatch):
    import app.main as main_mod

    isolated_mgr = TaskExecutionManager(db_path=str(tmp_path / "api_chats.db"))
    monkeypatch.setattr(main_mod, "manager", isolated_mgr)

    with TestClient(main_mod.app) as client:
        r_list = client.get("/api/chats")
        assert r_list.status_code == 200
        initial = r_list.json()
        assert len(initial) == 1

        r_new = client.post("/api/chats", json={"title": "Özel Beat"})
        assert r_new.status_code == 200
        new_chat = r_new.json()
        sid = new_chat["session_id"]
        assert new_chat["title"] == "Özel Beat"

        r_rename = client.patch(f"/api/chats/{sid}", json={"title": "Dark Trap #2"})
        assert r_rename.status_code == 200
        assert r_rename.json()["title"] == "Dark Trap #2"

        r_task = client.post(
            "/api/tasks",
            json={"prompt": "135 bpm trap beat yap", "is_mock": True, "session_id": sid},
        )
        assert r_task.status_code == 200
        assert r_task.json()["session_id"] == sid

        r_msgs = client.get(f"/api/chats/{sid}/messages")
        assert r_msgs.status_code == 200
        assert len(r_msgs.json()) >= 1
        assert r_msgs.json()[0]["session_id"] == sid

        r_tasks = client.get(f"/api/tasks?session_id={sid}")
        assert r_tasks.status_code == 200
        assert len(r_tasks.json()) == 1

        r_del = client.delete(f"/api/chats/{sid}")
        assert r_del.status_code == 200
        assert r_del.json()["deleted"] is True
        assert client.get(f"/api/chats/{sid}").status_code == 404

