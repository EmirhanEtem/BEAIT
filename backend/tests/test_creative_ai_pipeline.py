"""Tests for CreativeBeatEngine, AI-API-first ModelProviderAdapter,
FLStudioAdapter mixer/plugin controls, MixMasterEngine, and multi-track ProducerOrchestrator.
"""

from __future__ import annotations

import io
import json
import urllib.error
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from app.action_router.executor import ActionExecutor
from app.database.persistence import DatabaseManager
from app.integrations.fl_studio.adapter import FLStudioAdapter, TransportType
from app.model_providers.provider import (
    ModelProviderAdapter,
    ProviderConfig,
    normalize_llm_plan,
    redact_secrets,
)
from app.music_engine.creative_engine import CreativeBeatEngine
from app.music_engine.mix_master import MixMasterEngine
from app.orchestration.producer import MAX_BOUNDED_PLAN_ACTIONS, ProducerOrchestrator
from app.schemas.actions import ActionLifecycleState, ActionType


class _FakeHTTPResponse:
    def __init__(self, payload: dict):
        self._bytes = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._bytes

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _sample_ai_beat(genre: str = "phonk", bpm: float = 132.0, inst: str = "Sakura") -> dict:
    return {
        "ai_response": f"Özel {bpm} BPM {genre} üretimi hazır!",
        "intent_type": "full_production",
        "genre": genre,
        "mood": "aggressive",
        "tempo_bpm": bpm,
        "key": "F#",
        "scale": "phrygian",
        "swing": 0.14,
        "chord_progression": ["F#m", "G", "Em", "F#m"],
        "sections": [
            {"name": "Intro", "bars": 4},
            {"name": "Drop", "bars": 8},
        ],
        "drum_channels": [
            {"channel": 0, "name": "Kick", "steps": [0, 3, 6, 10], "length": 16},
            {"channel": 1, "name": "Clap", "steps": [4, 12], "length": 16},
            {"channel": 2, "name": "HiHat", "steps": [0, 2, 4, 6, 8, 10, 12, 14, 15], "length": 16},
        ],
        "tracks": [
            {
                "role": "chords",
                "instrument_name": "FL Keys",
                "fallbacks": ["FLEX", "Sytrus"],
                "notes": [
                    {"pitch": 54, "time_bars": 0.0, "length_bars": 1.0, "velocity": 0.78},
                    {"pitch": 57, "time_bars": 0.0, "length_bars": 1.0, "velocity": 0.76},
                    {"pitch": 61, "time_bars": 0.0, "length_bars": 1.0, "velocity": 0.76},
                ],
            },
            {
                "role": "bass",
                "instrument_name": "BooBass",
                "fallbacks": ["3x Osc", "Transistor Bass"],
                "notes": [
                    {"pitch": 30, "time_bars": 0.0, "length_bars": 0.75, "velocity": 0.94, "porta": False},
                    {"pitch": 42, "time_bars": 0.75, "length_bars": 0.25, "velocity": 0.88, "porta": True},
                ],
            },
            {
                "role": "lead",
                "instrument_name": inst,
                "fallbacks": ["FLEX", "Sytrus"],
                "notes": [
                    {"pitch": 66, "time_bars": 0.0, "length_bars": 0.5, "velocity": 0.90},
                    {"pitch": 67, "time_bars": 0.5, "length_bars": 0.5, "velocity": 0.88},
                    {"pitch": 73, "time_bars": 1.0, "length_bars": 0.75, "velocity": 0.92},
                ],
            },
        ],
        "channel_mix": [
            {"channel": 0, "volume": 0.90, "pan": 0.0},
            {"channel": 2, "volume": 0.65, "pan": 0.12},
        ],
        "fx_plan": {
            "chords": ["Fruity Parametric EQ 2", "Fruity Reeverb 2"],
            "bass": ["Fruity Parametric EQ 2", "Fruity Fast Dist"],
            "lead": ["Fruity Parametric EQ 2", "Fruity Delay 3"],
            "drums": ["Fruity Soft Clipper"],
            "master": ["Fruity Parametric EQ 2", "Fruity Soft Clipper", "Fruity Limiter"],
        },
        "fx_params": {
            "lead": {"delay_wet": 0.30, "air_boost": 0.62},
            "master": {"ceiling": 0.93, "clipper_thresh": 0.80},
        },
        "mix": {"enabled": True, "loud": True, "wide_stereo": True, "style": "aggressive"},
        "play_state": "play",
    }


def test_creative_beat_engine_diversity_and_rich_structure():
    engine = CreativeBeatEngine()
    phonk = engine.generate("bana 135 bpm sert agresif drift phonk beat yap")
    lofi = engine.generate("bana 82 bpm sakin hüzünlü piyano lofi beat yap")

    assert phonk["genre"] != lofi["genre"]
    assert phonk["tempo_bpm"] != lofi["tempo_bpm"]
    assert len(phonk["tracks"]) >= 3
    assert len(lofi["tracks"]) >= 3

    phonk_roles = {t["role"]: t for t in phonk["tracks"]}
    assert set(phonk_roles.keys()) >= {"chords", "bass", "lead"}
    assert any(n.get("porta") is True for n in phonk_roles["bass"]["notes"])
    assert "master" in phonk["fx_plan"]
    assert any("piano" in t["instrument_name"].lower() or t["instrument_name"] == "FL Keys" for t in lofi["tracks"])


def test_provider_ai_api_first_openai_not_overwritten():
    ai_json = _sample_ai_beat(genre="dark_trap", bpm=144.0, inst="Sakura")
    cfg = ProviderConfig(provider_name="openai", model_name="gpt-4o", api_key="sk-testsecretkey123456")
    adapter = ModelProviderAdapter(config=cfg)

    openai_resp = {
        "choices": [{"message": {"content": json.dumps(ai_json)}}]
    }
    with patch("urllib.request.urlopen", return_value=_FakeHTTPResponse(openai_resp)) as mock_open:
        plan = adapter.generate_music_plan(
            user_prompt="144 bpm karanlık trap beat yap",
            project_context={"bpm": 120.0},
            recent_history=[{"prompt": "house", "genre": "house", "tempo_bpm": 124.0, "key": "C"}],
            allow_in_pytest=True,
        )

    assert mock_open.called
    assert plan is not None
    assert plan["plan_source"] == "ai_api"
    assert plan["provider"] == "openai"
    assert plan["tempo_bpm"] == 144.0
    assert plan["key"] == "F#"
    assert plan["scale"] == "phrygian"
    assert [t["instrument_name"] for t in plan["tracks"]] == ["FL Keys", "BooBass", "Sakura"]
    assert plan["fx_plan"]["master"] == ["Fruity Parametric EQ 2", "Fruity Soft Clipper", "Fruity Limiter"]


def test_provider_gemini_and_quota_failover_and_redaction():
    ai_json = _sample_ai_beat(genre="synthwave", bpm=108.0, inst="FLEX")
    gemini_resp = {
        "candidates": [{"content": {"parts": [{"text": json.dumps(ai_json)}]}}]
    }

    gemini_cfg = ProviderConfig(provider_name="gemini", model_name="gemini-2.5-flash", api_key="AIzaSyFakeSecretKey1234567890")
    adapter = ModelProviderAdapter(config=gemini_cfg)

    with patch("urllib.request.urlopen", return_value=_FakeHTTPResponse(gemini_resp)) as mock_open:
        plan = adapter.generate_music_plan("synthwave yap", allow_in_pytest=True)

    req_obj = mock_open.call_args[0][0]
    assert "generativelanguage.googleapis.com" in req_obj.full_url
    assert plan is not None
    assert plan["plan_source"] == "ai_api"
    assert plan["provider"] == "gemini"
    assert plan["tempo_bpm"] == 108.0

    # Quota 429 fallback to CreativeBeatEngine discloses fallback cleanly and redacts secrets
    err_429 = urllib.error.HTTPError(
        url="https://api.openai.com/v1/chat/completions",
        code=429,
        msg="Too Many Requests",
        hdrs=None,
        fp=io.BytesIO(b'{"error": {"message": "insufficient_quota for sk-liveSecret999999999"}}'),
    )
    oa_cfg = ProviderConfig(provider_name="openai", model_name="gpt-4o", api_key="sk-liveSecret999999999")
    oa_adapter = ModelProviderAdapter(config=oa_cfg)
    with patch("urllib.request.urlopen", side_effect=err_429):
        fb_plan = oa_adapter.generate_music_plan("130 bpm phonk beat yap", allow_in_pytest=True)
        chat_plan = oa_adapter.generate_music_plan("selam", allow_in_pytest=True)

    assert fb_plan is not None
    assert fb_plan["plan_source"] == "creative_fallback"
    assert "sk-liveSecret999999999" not in fb_plan["ai_response"]
    assert "sk-liveSecret999999999" not in fb_plan.get("api_error", "")
    assert "yaratıcı yerel motor" in fb_plan["ai_response"]

    assert chat_plan is not None
    assert chat_plan["intent_type"] == "chat_only"
    assert "AIzaSyFakeSecretKey1234567890" not in redact_secrets("key=AIzaSyFakeSecretKey1234567890")


def test_gemini_same_provider_fallback_on_free_tier_429_and_model_list():
    from app.model_providers.provider import DEFAULT_GEMINI_MODEL, list_available_models

    assert DEFAULT_GEMINI_MODEL == "gemini-3.5-flash-lite"

    ai_json = _sample_ai_beat(genre="trap", bpm=140.0, inst="FL Keys")
    gemini_ok = {"candidates": [{"content": {"parts": [{"text": json.dumps(ai_json)}]}}]}
    err_pro_429 = urllib.error.HTTPError(
        url="https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-pro-preview:generateContent",
        code=429,
        msg="Too Many Requests",
        hdrs=None,
        fp=io.BytesIO(b'{"error":{"code":429,"message":"FreeTier limit: 0"}}'),
    )
    pro_cfg = ProviderConfig(
        provider_name="gemini",
        model_name="gemini-3.1-pro-preview",
        api_key="AIzaSyFakeSecretKey1234567890",
    )
    adapter = ModelProviderAdapter(config=pro_cfg)
    with patch("urllib.request.urlopen", side_effect=[err_pro_429, _FakeHTTPResponse(gemini_ok)]) as mock_open:
        plan = adapter.generate_music_plan("Kanye West Runaway tarzi piyano beat yap", allow_in_pytest=True)

    assert mock_open.call_count == 2
    assert plan is not None
    assert plan["plan_source"] == "ai_api"
    assert plan["provider"] == "gemini"
    assert plan["model"] == "gemini-3.5-flash-lite"

    catalog = list_available_models("gemini", live=False)
    model_ids = [m["id"] for m in catalog["models"]]
    assert "gemini-3.5-flash-lite" in model_ids
    assert "gemini-2.5-flash" not in model_ids


def test_adapter_mixer_routing_peaks_and_plugin_pagination():
    adapter = FLStudioAdapter(transport=TransportType.TCP)
    bridge = MagicMock()
    adapter._bridge = bridge

    bridge.call.side_effect = [
        {"track": 4, "name": "Chords"},
        {"track": 4, "color": {"r": 70, "g": 140, "b": 235}},
        {"src": 4, "dst": 0, "enabled": True},
        {"track": 0, "peak_l": 0.85, "peak_r": 0.82, "peak_max": 0.85},
        {"track": 4, "slots": [{"slot": 0, "name": "Fruity Parametric EQ 2"}]},
        {
            "track": 4,
            "slot": 0,
            "plugin": "Fruity Parametric EQ 2",
            "total": 3,
            "start": 0,
            "next_start": 2,
            "params": [{"i": 0, "name": "Band 1 Freq", "v": 0.2}, {"i": 1, "name": "Band 1 Level", "v": 0.5}],
        },
        {
            "track": 4,
            "slot": 0,
            "plugin": "Fruity Parametric EQ 2",
            "total": 3,
            "start": 2,
            "next_start": None,
            "params": [{"i": 2, "name": "Band 7 Level", "v": 0.55}],
        },
        {"track": 4, "slot": 0, "param": 1, "name": "Band 1 Level", "v": 0.0},
    ]

    assert adapter.set_mixer_name(4, "Chords")["name"] == "Chords"
    assert adapter.set_mixer_color(4, 70, 140, 235)["track"] == 4
    assert adapter.set_mixer_route(4, 0, True)["enabled"] is True
    assert adapter.get_mixer_peaks(0)["peak_max"] == 0.85
    assert adapter.plugin_list(4)["slots"][0]["slot"] == 0
    all_params = adapter.plugin_get_params(4, 0)
    assert len(all_params["params"]) == 3
    assert all_params["truncated"] is False
    # Clamp check (< 0 -> 0.0)
    adapter.plugin_set_param(4, 0, 1, -0.5)
    assert bridge.call.call_args[0][1]["value"] == 0.0


@pytest.mark.asyncio
async def test_mix_master_semantic_param_matching_and_peak_staging():
    engine = MixMasterEngine()
    fake_params = [
        {"i": 0, "name": "Band 1 Freq", "v": 0.1},
        {"i": 1, "name": "Band 1 Level", "v": 0.5},
        {"i": 12, "name": "Band 7 Level", "v": 0.5},
    ]
    matched = engine.match_plugin_params(
        "Fruity Parametric EQ 2",
        fake_params,
        role="lead",
        fx_params={"low_cut": 0.26, "air_boost": 0.62},
    )
    by_idx = {u["param"]: u["value"] for u in matched}
    assert by_idx[0] == 0.26
    assert by_idx[12] == 0.62

    mock_adapter = MagicMock()
    mock_adapter.async_set_mixer_name = AsyncMock(return_value={})
    mock_adapter.async_set_mixer_color = AsyncMock(return_value={})
    mock_adapter.async_set_mixer_pan_verified = AsyncMock(return_value=MagicMock(verified=True))
    mock_adapter.async_set_mixer_volume_verified = AsyncMock(return_value=MagicMock(verified=True))
    mock_adapter.async_plugin_list = AsyncMock(return_value={"slots": [{"slot": 0, "name": "Fruity Limiter"}]})
    mock_adapter.async_plugin_get_params = AsyncMock(
        return_value={"params": [{"i": 2, "name": "Ceiling", "v": 1.0}, {"i": 3, "name": "Gain", "v": 0.5}]}
    )
    mock_adapter.async_plugin_set_param = AsyncMock(return_value={"v": 0.93})
    mock_adapter.async_plugin_get_param = AsyncMock(return_value={"v": 0.93})
    # Hot peak first (0.97), then attenuated below 0.89 after Master trim
    mock_adapter.async_get_mixer_peaks = AsyncMock(side_effect=[{"peak_max": 0.97}, {"peak_max": 0.86}])

    res = await engine.run_auto_mix_master(
        mock_adapter,
        role_tracks={"drums": 1, "chords": 4, "bass": 5, "lead": 6},
        mix_cfg={"loud": True, "wide_stereo": True},
        fx_params={"master": {"ceiling": 0.93}},
    )
    assert res["verified"] is True
    assert res["master_peak_before"] == 0.97
    assert res["master_peak_after"] == 0.86
    assert res["master_volume"] < 0.80


@pytest.mark.asyncio
async def test_orchestrator_end_to_end_with_ai_multitrack_plan(tmp_path):
    db = DatabaseManager(db_path=str(tmp_path / "orch_ai.db"))
    executor = ActionExecutor(db=db)
    fake_provider = MagicMock(spec=ModelProviderAdapter)
    fake_provider.generate_music_plan.return_value = normalize_llm_plan(
        _sample_ai_beat(),
        plan_source="ai_api",
        provider_name="openai",
        model_name="gpt-4o",
    )

    orchestrator = ProducerOrchestrator(executor=executor, db=db, model_provider=fake_provider)
    plan = orchestrator.create_plan("132 bpm agresif phonk beat yap, plugin ve mix yap")

    assert len(plan.actions) <= MAX_BOUNDED_PLAN_ACTIONS
    atypes = [a.action_type for a in plan.actions]
    assert ActionType.LOAD_PLUGIN_PRESET in atypes
    assert atypes.count(ActionType.CREATE_MIDI_PATTERN) == 3
    assert ActionType.SET_MIXER_ROUTING in atypes
    assert ActionType.SET_MIXER_TRACK_META in atypes
    assert ActionType.LOAD_MIXER_EFFECT in atypes
    assert ActionType.SET_PLUGIN_PARAM in atypes
    assert ActionType.AUTO_MIX_MASTER in atypes
    assert ActionType.ADD_ARRANGEMENT_MARKER in atypes

    result = await orchestrator.execute_plan(plan, prefer_mock=True)
    assert result.success is True
    assert result.actions_failed == 0
    assert result.actions_succeeded == len(plan.actions)
    assert all(d["verified"] is True for d in result.details)

    # All instrument creation + MIDI patterns must precede Mixer routing
    midi_indices = [i for i, a in enumerate(plan.actions) if a.action_type == ActionType.CREATE_MIDI_PATTERN]
    routing_indices = [i for i, a in enumerate(plan.actions) if a.action_type == ActionType.SET_MIXER_ROUTING]
    assert max(midi_indices) < min(routing_indices)
    fx_actions = [a for a in plan.actions if a.action_type == ActionType.LOAD_MIXER_EFFECT]
    assert fx_actions and any(a.parameters.get("fallbacks") for a in fx_actions)


def test_live_gui_load_track_instrument_does_not_reuse_fallback_existing_channel():
    from app.integrations.computer_use.fl_live_gui import FLLiveGUIController

    adapter = MagicMock()
    channels_initial = [
        {"i": 0, "name": "Kick"},
        {"i": 1, "name": "Clap"},
        {"i": 2, "name": "Hat"},
        {"i": 3, "name": "Snare"},
        {"i": 4, "name": "FL Keys"},
    ]
    channels_after_load = channels_initial + [{"i": 5, "name": "Sakura"}]
    adapter.get_channels.side_effect = [channels_initial, channels_after_load]

    gui = FLLiveGUIController(fl_adapter=adapter)
    typed = []
    with (
        patch.object(FLLiveGUIController, "is_supported", new_callable=PropertyMock, return_value=True),
        patch.object(gui, "focus_fl_studio", return_value=1234),
        patch.object(gui, "ensure_window_focused"),
        patch.object(gui, "find_fl_subwindow_rect", return_value=(0, 0, 800, 600)),
        patch.object(gui, "smooth_click"),
        patch.object(gui, "press_vk"),
        patch.object(gui, "type_text", side_effect=lambda txt, **kw: typed.append(txt)),
        patch("app.integrations.computer_use.fl_live_gui.time.sleep"),
    ):
        res = gui.load_track_instrument_live(
            instrument_name="Sakura",
            fallbacks=["FLEX", "FL Keys"],
            exclude_channels=[],
            role="lead",
        )

    assert res["ok"] is True
    assert res["reused"] is False
    assert res["channel"] == 5
    assert res["instrument"] == "Sakura"
    assert typed == ["Sakura"]


def test_live_gui_route_channel_selects_channel_before_focus_and_ctrl_l():
    from app.integrations.computer_use.fl_live_gui import FLLiveGUIController

    call_order = []
    adapter = MagicMock()
    routed_flag = {"done": False}

    def fake_get_channel(idx):
        return {"i": idx, "target_fx_track": 3 if routed_flag["done"] else 0}

    def fake_select_channel(idx):
        call_order.append(("select_channel", idx))

    adapter.get_channel.side_effect = fake_get_channel
    adapter.select_channel.side_effect = fake_select_channel

    gui = FLLiveGUIController(fl_adapter=adapter)

    def fake_select_mixer(hwnd, mixer_track):
        call_order.append(("select_mixer_track_live", mixer_track))

    def fake_press_combo(mods, vk):
        call_order.append(("ctrl_l", vk))
        routed_flag["done"] = True

    with (
        patch.object(FLLiveGUIController, "is_supported", new_callable=PropertyMock, return_value=True),
        patch.object(gui, "focus_fl_studio", return_value=1234),
        patch.object(gui, "select_mixer_track_live", side_effect=fake_select_mixer),
        patch.object(gui, "press_combo", side_effect=fake_press_combo),
        patch("app.integrations.computer_use.fl_live_gui.time.sleep"),
    ):
        res = gui.route_channel_to_mixer_track_live(channel_idx=4, mixer_track=3)

    assert res["ok"] is True
    assert res["verified"] is True
    assert res["target_mixer_track"] == 3
    assert call_order == [
        ("select_channel", 4),
        ("select_mixer_track_live", 3),
        ("ctrl_l", 0x4C),
    ]


def test_orchestrator_creates_separate_role_patterns_and_4bar_drums(tmp_path):
    db = DatabaseManager(db_path=str(tmp_path / "orch_patterns.db"))
    executor = ActionExecutor(db=db)
    fake_provider = MagicMock(spec=ModelProviderAdapter)
    fake_provider.generate_music_plan.return_value = normalize_llm_plan(
        _sample_ai_beat(genre="trap", bpm=140.0, inst="Sakura"),
        plan_source="ai_api",
        provider_name="gemini",
        model_name="gemini-3.5-flash-lite",
    )

    orchestrator = ProducerOrchestrator(executor=executor, db=db, model_provider=fake_provider)
    plan = orchestrator.create_plan("140 bpm trap beat yap")

    pat_actions = [a for a in plan.actions if a.action_type == ActionType.CREATE_PATTERN]
    assert [a.parameters.get("role") for a in pat_actions] == ["drums", "chords", "bass", "lead"]
    assert pat_actions[0].parameters["name"].startswith("01")
    assert pat_actions[1].parameters["name"].startswith("02")

    # 1-bar drums should be coherently expanded to 64 steps (4 bars) to lock phase with 4-bar melodic tracks
    step_actions = [a for a in plan.actions if a.action_type == ActionType.SET_STEP_GRID]
    assert step_actions
    assert all(a.parameters["length"] == 64 for a in step_actions)

    # All tracks inside normalized plan should be cleanly phase-locked up to 4 bars
    norm_plan = fake_provider.generate_music_plan.return_value
    for trk in norm_plan["tracks"]:
        assert max(n["time_bars"] + n["length_bars"] for n in trk["notes"]) >= 3.0


def test_live_gui_mixer_fx_aborts_if_mixer_not_focused_and_strips_fruity():
    from app.integrations.computer_use.fl_live_gui import FLLiveGUIController

    assert FLLiveGUIController._clean_effect_query("Fruity Parametric EQ 2") == "Parametric EQ 2"
    assert FLLiveGUIController._clean_effect_query("Fruity Reeverb 2") == "Reeverb 2"

    adapter = MagicMock()
    adapter.plugin_list.return_value = {"slots": []}
    adapter.get_channels.return_value = [{"i": 0, "name": "Kick"}]
    gui = FLLiveGUIController(fl_adapter=adapter)
    pressed_f8 = []

    with (
        patch.object(FLLiveGUIController, "is_supported", new_callable=PropertyMock, return_value=True),
        patch.object(gui, "focus_fl_studio", return_value=1234),
        patch.object(gui, "select_mixer_track_live"),
        patch.object(gui, "ensure_window_focused"),
        patch.object(gui, "_get_focused_form_id", return_value=1),  # Channel Rack stuck focused instead of Mixer
        patch.object(gui, "press_vk", side_effect=lambda vk, **kw: pressed_f8.append(vk)),
        patch("app.integrations.computer_use.fl_live_gui.time.sleep"),
    ):
        res = gui.load_mixer_effect_live(mixer_track=2, plugin_name="Fruity Reeverb 2")

    assert res["ok"] is False
    assert "Mixer window could not gain focus" in res["error"]
    assert 0x77 not in pressed_f8  # Must NEVER open Plugin Picker when Mixer is not focused!


def test_live_gui_daisy_chains_overflow_mixer_bus_when_10_slots_full():
    from app.integrations.computer_use.fl_live_gui import FLLiveGUIController

    adapter = MagicMock()
    full_10_slots = [{"slot": i, "name": f"SlotPlugin{i}"} for i in range(10)]
    reverb_slot = [{"slot": 0, "name": "Fruity Reeverb 2"}]

    # Track 6 is 10/10 full; spare track 20 is clean initially, then receives Fruity Reeverb 2
    slot_calls = {6: list(full_10_slots), 20: []}

    def fake_plugin_list(track):
        return {"track": track, "slots": list(slot_calls.get(track, []))}

    def fake_get_routing(track):
        if track == 6:
            return {"track": 6, "name": "Lead", "routes_to": [{"dst": 0, "dst_name": "Master"}]}
        return {"track": track, "name": f"Insert {track}", "routes_to": [{"dst": 0, "dst_name": "Master"}]}

    adapter.plugin_list.side_effect = fake_plugin_list
    adapter.get_mixer_routing.side_effect = fake_get_routing
    adapter.get_channels.return_value = [{"i": 0, "name": "Kick"}]

    gui = FLLiveGUIController(fl_adapter=adapter)

    def fake_press_vk(vk, **kw):
        # Enter drops Fruity Reeverb 2 into the daisy-chained track 20
        if vk == 0x0D:
            slot_calls[20] = list(reverb_slot)

    with (
        patch.object(FLLiveGUIController, "is_supported", new_callable=PropertyMock, return_value=True),
        patch.object(gui, "focus_fl_studio", return_value=1234),
        patch.object(gui, "_dismiss_fl_error_dialog_if_any", return_value=False),
        patch.object(gui, "select_mixer_track_live"),
        patch.object(gui, "_get_focused_form_id", return_value=0),
        patch.object(gui, "press_vk", side_effect=fake_press_vk),
        patch.object(gui, "type_text"),
        patch("app.integrations.computer_use.fl_live_gui.time.sleep"),
    ):
        res = gui.load_mixer_effect_live(mixer_track=6, plugin_name="Fruity Reeverb 2")

    assert res["ok"] is True
    assert res["loaded"] is True
    assert res["daisy_chained"] is True
    assert res["source_mixer_track"] == 6
    assert res["mixer_track"] == 20
    assert res["plugin_name"] == "Fruity Reeverb 2"

    # Must disable direct Master route on track 6 so audio does NOT double-play, and route 6 -> 20 -> 0
    adapter.set_mixer_route.assert_any_call(20, 0, enabled=True)
    adapter.set_mixer_route.assert_any_call(6, 0, enabled=False)
    adapter.set_mixer_route.assert_any_call(6, 20, enabled=True)


def test_live_gui_master_9_plugins_plus_limiter_chains_to_pre_master():
    """Reproduces the 9-plugin + Fruity Limiter (10/10) Master bug and verifies Pre-Master FX+ chaining."""
    from app.integrations.computer_use.fl_live_gui import FLLiveGUIController

    adapter = MagicMock()
    master_10_slots = [{"slot": 0, "name": "Fruity Limiter"}] + [
        {"slot": i, "name": f"ExtraPlugin{i}"} for i in range(1, 10)
    ]
    slot_calls = {0: list(master_10_slots), 19: []}
    selected_state = {"track": 0}

    def fake_plugin_list(track):
        return {"track": track, "slots": list(slot_calls.get(track, []))}

    def fake_get_routing(track):
        if track == 1:
            return {"track": 1, "name": "Kick / Drums", "routes_to": [{"dst": 0, "dst_name": "Master"}]}
        if track == 19:
            return {"track": 19, "name": "Insert 19", "routes_to": [{"dst": 0, "dst_name": "Master"}]}
        return {"track": track, "name": f"Insert {track}", "routes_to": []}

    def fake_select_mixer_track(track, focus=True):
        selected_state["track"] = track
        return {"ok": True, "track": track, "selected": track}

    adapter.plugin_list.side_effect = fake_plugin_list
    adapter.get_mixer_routing.side_effect = fake_get_routing
    adapter.get_channels.return_value = [{"i": 0, "name": "Kick"}]
    adapter.select_mixer_track.side_effect = fake_select_mixer_track
    adapter.get_selected_mixer_track.side_effect = lambda: {"ok": True, "selected": selected_state["track"]}

    gui = FLLiveGUIController(fl_adapter=adapter)

    def fake_press_vk(vk, **kw):
        # F8+Return drops onto whichever Mixer track FL actually has selected right now
        if vk == 0x0D and selected_state["track"] == 19:
            slot_calls[19] = [{"slot": 0, "name": "Fruity Parametric EQ 2"}]

    with (
        patch.object(FLLiveGUIController, "is_supported", new_callable=PropertyMock, return_value=True),
        patch.object(gui, "focus_fl_studio", return_value=1234),
        patch.object(gui, "_dismiss_fl_error_dialog_if_any", return_value=False),
        patch.object(gui, "ensure_window_focused"),
        patch.object(gui, "find_fl_subwindow_rect", return_value=None),
        patch.object(gui, "_get_focused_form_id", return_value=0),
        patch.object(gui, "press_vk", side_effect=fake_press_vk),
        patch.object(gui, "type_text"),
        patch("app.integrations.computer_use.fl_live_gui.time.sleep"),
    ):
        res = gui.load_mixer_effect_live(
            mixer_track=0,
            plugin_name="Fruity Parametric EQ 2",
            fallbacks=["Fruity 7 Band EQ"],
        )

    assert res["ok"] is True
    assert res["daisy_chained"] is True
    assert res["source_mixer_track"] == 0
    assert res["mixer_track"] == 19
    assert selected_state["track"] == 19
    adapter.set_mixer_name.assert_any_call(19, "Pre-Master FX+")
    adapter.set_mixer_route.assert_any_call(19, 0, enabled=True)
    adapter.set_mixer_route.assert_any_call(1, 19, enabled=True)
    adapter.set_mixer_route.assert_any_call(1, 0, enabled=False)


def test_live_gui_aborts_if_mixer_track_mismatch_or_fx_leaked_to_master():
    """Never spam fallbacks onto Master (Track 0) if track selection didn't switch or F8 leaked to Master."""
    from app.integrations.computer_use.fl_live_gui import FLLiveGUIController

    # Case 1: Active track stays stuck on Master (0) when requesting Track 4 -> must abort BEFORE VK_F8
    adapter1 = MagicMock()
    adapter1.plugin_list.return_value = {"slots": []}
    adapter1.get_channels.return_value = [{"i": 0, "name": "Kick"}]
    adapter1.select_mixer_track.return_value = {"ok": False, "selected": 0}
    adapter1.get_selected_mixer_track.return_value = {"ok": True, "selected": 0}
    gui1 = FLLiveGUIController(fl_adapter=adapter1)
    f8_calls = []

    with (
        patch.object(FLLiveGUIController, "is_supported", new_callable=PropertyMock, return_value=True),
        patch.object(gui1, "focus_fl_studio", return_value=1234),
        patch.object(gui1, "_dismiss_fl_error_dialog_if_any", return_value=False),
        patch.object(gui1, "ensure_window_focused"),
        patch.object(gui1, "find_fl_subwindow_rect", return_value=None),
        patch.object(gui1, "_read_fl_hint", return_value="Master"),
        patch.object(gui1, "press_vk", side_effect=lambda vk, **kw: f8_calls.append(vk)),
        patch("app.integrations.computer_use.fl_live_gui.time.sleep"),
    ):
        res1 = gui1.load_mixer_effect_live(mixer_track=4, plugin_name="Fruity Parametric EQ 2")

    assert res1["ok"] is False
    assert "could not be selected" in res1["error"]
    assert 0x77 not in f8_calls

    # Case 2: Track 4 was empty, candidate 1 accidentally landed on Master (0) -> must stop before retrying fallbacks!
    adapter2 = MagicMock()
    master_slots = [{"slot": 0, "name": "Fruity Limiter"}]
    adapter2.plugin_list.side_effect = lambda t: {"track": t, "slots": list(master_slots) if t == 0 else []}
    adapter2.get_channels.return_value = [{"i": 0, "name": "Kick"}]
    adapter2.select_mixer_track.return_value = {"ok": True, "track": 4, "selected": 4}
    adapter2.get_selected_mixer_track.return_value = {"ok": True, "selected": 4}
    gui2 = FLLiveGUIController(fl_adapter=adapter2)
    f8_attempts = []

    def fake_vk2(vk, **kw):
        if vk == 0x77:
            f8_attempts.append(vk)
        elif vk == 0x0D:
            master_slots.append({"slot": len(master_slots), "name": "Fruity Compressor"})

    with (
        patch.object(FLLiveGUIController, "is_supported", new_callable=PropertyMock, return_value=True),
        patch.object(gui2, "focus_fl_studio", return_value=1234),
        patch.object(gui2, "_dismiss_fl_error_dialog_if_any", return_value=False),
        patch.object(gui2, "ensure_window_focused"),
        patch.object(gui2, "find_fl_subwindow_rect", return_value=None),
        patch.object(gui2, "_get_focused_form_id", return_value=0),
        patch.object(gui2, "press_vk", side_effect=fake_vk2),
        patch.object(gui2, "type_text"),
        patch("app.integrations.computer_use.fl_live_gui.time.sleep"),
    ):
        res2 = gui2.load_mixer_effect_live(
            mixer_track=4,
            plugin_name="Fruity Compressor",
            fallbacks=["Fruity Limiter", "Maximus"],
        )

    assert res2["ok"] is False
    assert "Master (Track 0)" in res2["error"]
    assert len(f8_attempts) == 1  # Stopped immediately on first candidate instead of trying fallbacks!


def test_live_gui_route_channel_uses_direct_set_target_fx_track_and_extended_keys():
    from app.integrations.computer_use.fl_live_gui import FLLiveGUIController, KEYEVENTF_EXTENDEDKEY, VK_RIGHT

    adapter = MagicMock()
    adapter.get_channel.return_value = {"i": 5, "target_fx_track": 0}
    adapter.set_channel_target_mixer.return_value = {
        "ok": True,
        "channel": 5,
        "mixer_track": 4,
        "target_mixer_track": 4,
    }
    gui = FLLiveGUIController(fl_adapter=adapter)
    with patch.object(FLLiveGUIController, "is_supported", new_callable=PropertyMock, return_value=True):
        res = gui.route_channel_to_mixer_track_live(channel_idx=5, mixer_track=4)

    assert res["ok"] is True
    assert res["verified"] is True
    assert res["target_mixer_track"] == 4
    assert res["method"] == "setTargetFxTrack"

    # Extended key flag must be passed for arrow keys under Windows Delphi UI
    fake_u32 = MagicMock()
    fake_u32.MapVirtualKeyW.return_value = 77
    gui._user32 = fake_u32
    with (
        patch.object(FLLiveGUIController, "is_supported", new_callable=PropertyMock, return_value=True),
        patch("app.integrations.computer_use.fl_live_gui.time.sleep"),
    ):
        gui.press_vk(VK_RIGHT)
    first_call_flags = fake_u32.keybd_event.call_args_list[0][0][2]
    assert (first_call_flags & KEYEVENTF_EXTENDEDKEY) == KEYEVENTF_EXTENDEDKEY


def test_song_request_detection_and_grounding_pipeline():
    from app.model_providers.song_research import analyze_song_request, research_song

    sq1 = analyze_song_request("bana Kanye West in Runway şarkısını yap")
    assert sq1.is_song_reference is True
    assert "kanye" in sq1.search_query.lower() and "runway" in sq1.search_query.lower()
    assert sq1.explicit_user_bpm is None

    sq2 = analyze_song_request("Bana Juice WRLD - Lucid Dreams şarkısının bir replikasını yap bpm falan aynı olsun")
    assert sq2.is_song_reference is True
    assert sq2.artist_hint == "Juice WRLD"
    assert sq2.title_hint == "Lucid Dreams"

    # Generic style beats must NOT be forced into single-song lookup
    sq3 = analyze_song_request("travis scott tarzı karanlık 140 bpm trap beat yap")
    assert sq3.is_song_reference is False
    assert sq3.explicit_user_bpm == 140.0

    # Mock iTunes + Deezer + Gemini Search Grounding (assert NO responseMimeType on search call)
    seen_calls = []

    def fake_urlopen(req, timeout=10):
        url = req.full_url
        body = json.loads(req.data.decode("utf-8")) if getattr(req, "data", None) else None
        seen_calls.append((url, body))

        if "itunes.apple.com" in url:
            return _FakeHTTPResponse({
                "results": [{
                    "artistName": "Kanye West",
                    "trackName": "Runaway",
                    "primaryGenreName": "Hip-Hop/Rap",
                    "collectionName": "My Beautiful Dark Twisted Fantasy",
                    "releaseDate": "2010-11-22",
                    "trackTimeMillis": 548000,
                }]
            })
        if "api.deezer.com/search" in url:
            return _FakeHTTPResponse({
                "data": [{"id": 999111, "title": "Runaway", "artist": {"name": "Kanye West"}, "duration": 548}]
            })
        if "api.deezer.com/track/999111" in url:
            return _FakeHTTPResponse({
                "id": 999111, "title": "Runaway", "artist": {"name": "Kanye West"}, "bpm": 85, "duration": 548
            })
        if "generativelanguage.googleapis.com" in url:
            if body and "tools" in body:
                # Stage-1 research MUST NOT combine google_search with responseMimeType
                assert "responseMimeType" not in body.get("generationConfig", {})
                search_json = {
                    "artist": "Kanye West",
                    "title": "Runaway",
                    "bpm": 85.0,
                    "alt_bpm_note": "85 BPM steady boom-bap groove",
                    "key": "E",
                    "scale": "major",
                    "genre": "hip_hop",
                    "chord_progression": ["E", "D#m", "C#m", "A"],
                    "signature_riff_notes": [
                        {"pitch": 88, "note": "E6", "time_bars": 0.0, "length_bars": 0.35, "velocity": 0.92},
                        {"pitch": 87, "note": "D#6", "time_bars": 2.0, "length_bars": 0.35, "velocity": 0.90},
                    ],
                    "melody_description": "Iconic sparse high E6 piano notes descending E6->D#6->C#6->A5",
                    "bass_pattern": "Deep warm bass following E-D#-C#-A roots",
                    "drum_groove": "85 BPM heavy boom-bap kick and snappy snare",
                }
                return _FakeHTTPResponse({
                    "candidates": [{
                        "content": {"parts": [{"text": "```json\n" + json.dumps(search_json) + "\n```"}]},
                        "groundingMetadata": {
                            "webSearchQueries": ["Kanye West Runaway BPM key notes"],
                            "groundingChunks": [{"web": {"title": "tunebat.com", "uri": "https://tunebat.com"}}],
                        },
                    }]
                })
            # Stage-2 JSON composition: simulate Flash-Lite drifting to 78 BPM; verify dossier + temp + lock!
            user_prompt_txt = body["contents"][0]["parts"][0]["text"]
            assert "VERIFIED INTERNET SONG RESEARCH DOSSIER" in user_prompt_txt
            assert "85.0 BPM" in user_prompt_txt
            assert body["generationConfig"]["temperature"] == 0.35
            drifted_ai_json = _sample_ai_beat(genre="hip_hop", bpm=78.0, inst="FL Keys")
            return _FakeHTTPResponse({
                "candidates": [{"content": {"parts": [{"text": json.dumps(drifted_ai_json)}]}}]
            })
        raise AssertionError(f"Unexpected URL in test: {url}")

    gemini_cfg = ProviderConfig(
        provider_name="gemini",
        model_name="gemini-3.5-flash-lite",
        api_key="AIzaSyFakeTestResearchKey12345678",
    )
    adapter = ModelProviderAdapter(config=gemini_cfg)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        plan = adapter.generate_music_plan("bana Kanye West in Runway şarkısını yap", allow_in_pytest=True)

    assert plan is not None
    assert plan["plan_source"] == "ai_api"
    # Post-normalization BPM guard must lock drifted 78.0 back to verified 85.0!
    assert plan["tempo_bpm"] == 85.0
    assert plan["song_research"]["label"] == "Kanye West - Runaway"
    assert plan["song_research"]["bpm"] == 85.0
    assert plan["song_research"]["confidence"] == "high"
    # Verify Stage-1 research also works directly for half/double time reconciliation
    assert any("api.deezer.com/track/999111" in u for u, _ in seen_calls)
    _ = research_song  # imported check


def test_playlist_painting_clears_calibrates_uses_song_mode_and_verifies():
    from app.integrations.computer_use.fl_live_gui import FLLiveGUIController, VK_CONTROL, VK_DELETE

    adapter = MagicMock()
    pl_state = {
        "song_ticks": 1920,  # Previous beat leftover clips exist at start!
        "loop_mode": 0,
        "vis_bar": 0,
        "selected_pattern": 2,
    }
    selected_patterns = []

    def fake_select_pattern(idx, deselect=True):
        selected_patterns.append(idx)
        pl_state["selected_pattern"] = idx
        return {"ok": True, "selected": idx}

    def fake_set_loop_mode(mode="song"):
        pl_state["loop_mode"] = 1 if mode == "song" else 0
        return {"ok": True, "loop_mode": pl_state["loop_mode"]}

    def fake_get_playlist_state(max_tracks=8):
        return {
            "ok": True,
            "loop_mode": pl_state["loop_mode"],
            "song_length_ticks": pl_state["song_ticks"],
            "song_length_bars": round(pl_state["song_ticks"] / 384.0, 2),
            "vis_bar": pl_state["vis_bar"],
            "pattern_number": pl_state["selected_pattern"],
        }

    adapter.select_pattern.side_effect = fake_select_pattern
    adapter.set_loop_mode.side_effect = fake_set_loop_mode
    adapter.get_playlist_state.side_effect = fake_get_playlist_state

    clicks = []
    combos = []
    vks = []

    def fake_combo(mods, vk):
        combos.append((tuple(mods), vk))
        if vk == 0x41:  # Ctrl+A
            pass
        elif vk == 0x42:  # Ctrl+B
            pl_state["vis_bar"] = 4
            pl_state["song_ticks"] += 1536

    def fake_vk(vk, **kw):
        vks.append(vk)
        if vk == VK_DELETE and combos and combos[-1][1] == 0x41:
            pl_state["song_ticks"] = 0  # Cleared leftover clips!
        elif vk == 0x24:  # VK_HOME
            pl_state["vis_bar"] = 0

    def fake_click(x, y, **kw):
        clicks.append((x, y, kw.get("right", False)))
        if not kw.get("right") and y >= 225 and x >= 300:
            # First candidate at p_top+108 = 208 misses Marker Lane; y>=225 (228) hits Track 1!
            if pl_state["song_ticks"] == 0:
                pl_state["song_ticks"] = 1536

    gui = FLLiveGUIController(fl_adapter=adapter)
    with (
        patch.object(FLLiveGUIController, "is_supported", new_callable=PropertyMock, return_value=True),
        patch.object(gui, "focus_fl_studio", return_value=1234),
        patch.object(gui, "ensure_window_focused"),
        patch.object(gui, "find_fl_subwindow_rect", return_value=(100, 100, 1200, 750)),
        patch.object(gui, "_detect_playlist_bar1_x", return_value=420),
        patch.object(gui, "smooth_click", side_effect=fake_click),
        patch.object(gui, "press_combo", side_effect=fake_combo),
        patch.object(gui, "press_vk", side_effect=fake_vk),
        patch.object(gui, "_emit_cursor"),
        patch("app.integrations.computer_use.fl_live_gui.time.sleep"),
    ):
        res = gui.paint_arrangement_to_playlist(
            sections=[
                {"name": "Intro", "bars": 4, "roles": ["chords", "lead"]},
                {"name": "Build", "bars": 4, "roles": ["drums", "chords", "bass"]},
                {"name": "Drop", "bars": 8, "roles": ["drums", "chords", "bass", "lead"]},
            ],
            bars_per_pattern=4,
            role_patterns={"drums": 5, "chords": 6, "bass": 7, "lead": 8},
            clear_existing=True,
        )

    assert res["ok"] is True
    assert res["verified"] is True
    assert res["loop_mode"] == 1
    assert res["song_length_ticks"] > 0
    assert selected_patterns == [5, 6, 7, 8]
    assert (tuple([VK_CONTROL]), 0x41) in combos  # Old clips cleared with Ctrl+A
    # Intro (bar 1) lifted via right-click ONLY after vis_bar reset cleanly, for drums & bass
    right_clicks = [c for c in clicks if c[2] is True]
    assert len(right_clicks) == 2

    # Failure case: if clicks never produce any clip (song_length_ticks stays 0), verified MUST be False!
    adapter_fail = MagicMock()
    adapter_fail.select_pattern.return_value = {"ok": True, "selected": 5}
    adapter_fail.set_loop_mode.return_value = {"ok": True, "loop_mode": 1}
    adapter_fail.get_playlist_state.return_value = {"ok": True, "song_length_ticks": 0, "song_length_bars": 0.0, "loop_mode": 1, "vis_bar": 0}
    gui_fail = FLLiveGUIController(fl_adapter=adapter_fail)
    with (
        patch.object(FLLiveGUIController, "is_supported", new_callable=PropertyMock, return_value=True),
        patch.object(gui_fail, "focus_fl_studio", return_value=1234),
        patch.object(gui_fail, "ensure_window_focused"),
        patch.object(gui_fail, "find_fl_subwindow_rect", return_value=(100, 100, 1200, 750)),
        patch.object(gui_fail, "_detect_playlist_bar1_x", return_value=420),
        patch.object(gui_fail, "smooth_click"),
        patch.object(gui_fail, "press_combo"),
        patch.object(gui_fail, "press_vk"),
        patch.object(gui_fail, "_emit_cursor"),
        patch("app.integrations.computer_use.fl_live_gui.time.sleep"),
    ):
        fail_res = gui_fail.paint_arrangement_to_playlist(
            sections=[{"name": "Intro", "bars": 4}, {"name": "Drop", "bars": 4}],
            role_patterns={"drums": 5},
        )
    assert fail_res["ok"] is False
    assert fail_res["verified"] is False


@pytest.mark.asyncio
async def test_generator_plugin_tuning_and_multiband_compressor():
    """MixMasterEngine configures generator presets/knobs (slot=-1) & Fruity Multiband Compressor."""
    from app.music_engine.mix_master import MixMasterEngine

    engine = MixMasterEngine()
    mb_updates = engine.match_plugin_params(
        "Fruity Multiband Compressor",
        [
            {"i": 0, "name": "Low Threshold", "v": 0.5},
            {"i": 1, "name": "Mid Threshold", "v": 0.5},
            {"i": 2, "name": "High Threshold", "v": 0.5},
            {"i": 3, "name": "Gain", "v": 0.5},
        ],
        role="drums",
        mix_cfg={"mood": "aggressive", "loud": True},
    )
    assert len(mb_updates) >= 3

    boobass_updates = engine.match_generator_params(
        "BooBass",
        [{"i": 0, "name": "Bass", "v": 0.5}, {"i": 1, "name": "Mid", "v": 0.5}, {"i": 2, "name": "Treble", "v": 0.5}],
        role="bass",
        generator_params={"sub": 0.85, "warmth": 0.35, "brightness": 0.25},
    )
    by_name = {u["name"]: u["value"] for u in boobass_updates}
    assert by_name["Bass"] == 0.85
    assert by_name["Mid"] == 0.35
    assert by_name["Treble"] == 0.25

    fake_adapter = MagicMock()
    fake_adapter.async_find_plugin_preset = AsyncMock(
        return_value={"matched": True, "plugin_name": "FLEX", "name_f6": "Dark Bell Lead"}
    )
    fake_adapter.async_plugin_get_params = AsyncMock(
        return_value={
            "track": 6,
            "slot": -1,
            "plugin": "FLEX",
            "params": [
                {"i": 0, "name": "Macro 1 - Cutoff", "v": 0.5},
                {"i": 1, "name": "Macro 3 - Attack", "v": 0.5},
                {"i": 2, "name": "Macro 6 - Reverb", "v": 0.2},
            ],
        }
    )
    set_calls = []

    async def _set_param(trk, sl, prm, val):
        set_calls.append((trk, sl, prm, val))
        return {"track": trk, "slot": sl, "param": prm, "v": val}

    fake_adapter.async_plugin_set_param = AsyncMock(side_effect=_set_param)
    fake_adapter.async_plugin_get_param = AsyncMock(side_effect=lambda t, s, p: {"v": 0.65})

    res = await engine.tune_generator_plugin(
        fake_adapter,
        channel=6,
        plugin_name="FLEX",
        role="lead",
        preset_hint="Dark Bell",
        generator_params={"cutoff": 0.66, "attack": 0.08, "reverb": 0.31},
    )
    assert res["verified"] is True
    assert res["slot"] == -1
    assert res["preset_matched"] is True
    assert res["updated_count"] == 3
    assert all(c[0] == 6 and c[1] == -1 for c in set_calls)


def test_creative_variation_brief_and_sparse_enricher():
    """Creative seed avoids recent Am clichés and sparse 4-bar drafts get enriched cleanly."""
    from app.model_providers.provider import (
        _SYSTEM_PRODUCER_PROMPT,
        build_creative_variation_brief,
        enrich_sparse_ai_tracks,
    )

    assert "generator_params" in _SYSTEM_PRODUCER_PROMPT
    assert "preset_hint" in _SYSTEM_PRODUCER_PROMPT
    assert "Am9" not in _SYSTEM_PRODUCER_PROMPT

    brief = build_creative_variation_brief(
        "yaratıcı trap beat yap",
        recent_history=[{"key": "A", "scale": "natural_minor", "instruments": ["FL Keys", "BooBass", "Sytrus"]}],
    )
    assert "Suggested Key & Scale:" in brief
    assert "Instrument Palette" in brief
    assert "A natural_minor" not in brief

    # Sparse 4-bar draft (>= 2.0 bars) is enriched cleanly in-scale
    sparse_plan = {
        "intent_type": "full_production",
        "genre": "trap",
        "mood": "dark",
        "key": "F#",
        "scale": "dorian",
        "tracks": [
            {
                "role": "bass",
                "instrument_name": "3x Osc",
                "notes": [
                    {"pitch": 30, "time_bars": 0.0, "length_bars": 0.5, "velocity": 0.9},
                    {"pitch": 35, "time_bars": 1.0, "length_bars": 0.5, "velocity": 0.9},
                    {"pitch": 33, "time_bars": 2.0, "length_bars": 0.5, "velocity": 0.9},
                    {"pitch": 32, "time_bars": 3.0, "length_bars": 0.5, "velocity": 0.9},
                ],
            },
            {
                "role": "lead",
                "instrument_name": "Harmless",
                "notes": [
                    {"pitch": 66, "time_bars": 0.0, "length_bars": 0.5, "velocity": 0.85},
                    {"pitch": 69, "time_bars": 1.5, "length_bars": 0.5, "velocity": 0.85},
                    {"pitch": 73, "time_bars": 2.5, "length_bars": 0.5, "velocity": 0.85},
                    {"pitch": 71, "time_bars": 3.5, "length_bars": 0.5, "velocity": 0.85},
                ],
            },
        ],
    }
    enriched = enrich_sparse_ai_tracks(sparse_plan, is_song_reference=False)
    assert enriched["sparse_enriched"] is True
    assert len(enriched["tracks"][0]["notes"]) >= 10
    assert len(enriched["tracks"][1]["notes"]) >= 14
    assert "generator_params" in enriched["tracks"][0]

    # Compact <2-bar unit fixture is untouched
    short_fixture = {
        "intent_type": "full_production",
        "key": "C",
        "scale": "natural_minor",
        "tracks": [
            {
                "role": "lead",
                "instrument_name": "FLEX",
                "notes": [{"pitch": 60, "time_bars": 0.0, "length_bars": 0.25, "velocity": 0.8}],
            }
        ],
    }
    untouched = enrich_sparse_ai_tracks(short_fixture, is_song_reference=False)
    assert len(untouched["tracks"][0]["notes"]) == 1


@pytest.mark.asyncio
async def test_executor_generator_set_plugin_param_and_playlist_stale_1199_ticks_guard():
    """Executor tunes generator slot=-1 via role_channels; Playlist rejects stale 1199 ticks & recovers unselected Ctrl+B."""
    from app.action_router.executor import ActionExecutor
    from app.integrations.computer_use.fl_live_gui import FLLiveGUIController, VK_CONTROL, VK_E
    from app.schemas.actions import ActionDefinition, ActionType

    adapter = MagicMock()
    adapter.async_find_plugin_preset = AsyncMock(return_value={"matched": True, "plugin_name": "Sytrus", "name_f6": "Glass Bell"})
    adapter.async_plugin_get_params = AsyncMock(
        return_value={"track": 3, "slot": -1, "plugin": "Sytrus", "params": [{"i": 0, "name": "Mod X", "v": 0.5}]}
    )
    adapter.async_plugin_set_param = AsyncMock(return_value={"track": 3, "slot": -1, "param": 0, "v": 0.68})
    adapter.async_plugin_get_param = AsyncMock(return_value={"v": 0.68})

    executor = ActionExecutor(fl_adapter=adapter)
    executor._get_task_ctx("t_gen")["role_channels"]["lead"] = 3
    action = ActionDefinition(
        task_id="t_gen",
        action_type=ActionType.SET_PLUGIN_PARAM,
        description="Tune generator",
        parameters={"slot": -1, "role": "lead", "plugin_name": "Sytrus", "preset_hint": "Glass Bell"},
    )
    res = await executor._execute_fl_mcp(action)
    assert res["verified"] is True
    assert res["channel"] == 3
    assert res["slot"] == -1
    assert res["updated_count"] == 1

    # 1. Stale 1199 ticks cannot pass Playlist verification if clicks fail to grow past 1199
    stale_adapter = MagicMock()
    stale_adapter.select_pattern.return_value = {"ok": True, "selected": 5}
    stale_adapter.set_loop_mode.return_value = {"ok": True, "loop_mode": 1}
    stale_adapter.get_playlist_state.return_value = {
        "ok": True, "song_length_ticks": 1199, "song_length_bars": 3.1224, "loop_mode": 1, "vis_bar": 0,
    }
    gui_stale = FLLiveGUIController(fl_adapter=stale_adapter)
    with (
        patch.object(FLLiveGUIController, "is_supported", new_callable=PropertyMock, return_value=True),
        patch.object(gui_stale, "focus_fl_studio", return_value=1234),
        patch.object(gui_stale, "ensure_window_focused"),
        patch.object(gui_stale, "find_fl_subwindow_rect", return_value=(100, 100, 1200, 750)),
        patch.object(gui_stale, "_detect_playlist_bar1_x", return_value=420),
        patch.object(gui_stale, "smooth_click"),
        patch.object(gui_stale, "press_combo"),
        patch.object(gui_stale, "press_vk"),
        patch.object(gui_stale, "_emit_cursor"),
        patch("app.integrations.computer_use.fl_live_gui.time.sleep"),
    ):
        stale_res = gui_stale.paint_arrangement_to_playlist(
            sections=[{"name": "Intro", "bars": 4}, {"name": "Drop", "bars": 8}],
            role_patterns={"drums": 5},
        )
    assert stale_res["ok"] is False
    assert stale_res["verified"] is False

    # 2. If 1st bare Ctrl+B fails to grow ticks, VK_E marquee drag selects the Bar-1 clip and Ctrl+B succeeds!
    pl_state = {"song_ticks": 1199, "selected": False, "loop_mode": 1, "vis_bar": 0}
    rec_adapter = MagicMock()
    rec_adapter.select_pattern.return_value = {"ok": True, "selected": 5}
    rec_adapter.set_loop_mode.return_value = {"ok": True, "loop_mode": 1}
    rec_adapter.get_playlist_state.side_effect = lambda **kw: {
        "ok": True,
        "song_length_ticks": pl_state["song_ticks"],
        "song_length_bars": round(pl_state["song_ticks"] / 384.0, 4),
        "loop_mode": pl_state["loop_mode"],
        "vis_bar": pl_state["vis_bar"],
    }

    combos_seen = []

    def rec_combo(mods, vk):
        combos_seen.append(vk)
        if vk == 0x42 and pl_state["selected"]:
            pl_state["song_ticks"] += 1536

    def rec_vk(vk, **kw):
        if vk == 0x2E and combos_seen and combos_seen[-1] == 0x41:
            pl_state["song_ticks"] = 0

    def rec_click(x, y, **kw):
        if not kw.get("right") and y <= 260 and pl_state["song_ticks"] == 0:
            pl_state["song_ticks"] = 1536  # Draw leaves unselected -> bare Ctrl+B will fail until VK_E drag!

    def rec_drag(x1, y1, x2, y2, **kw):
        pl_state["selected"] = True  # VK_E marquee selects clip!

    gui_rec = FLLiveGUIController(fl_adapter=rec_adapter)
    with (
        patch.object(FLLiveGUIController, "is_supported", new_callable=PropertyMock, return_value=True),
        patch.object(gui_rec, "focus_fl_studio", return_value=1234),
        patch.object(gui_rec, "ensure_window_focused"),
        patch.object(gui_rec, "find_fl_subwindow_rect", return_value=(100, 100, 1200, 750)),
        patch.object(gui_rec, "_detect_playlist_bar1_x", return_value=420),
        patch.object(gui_rec, "smooth_click", side_effect=rec_click),
        patch.object(gui_rec, "smooth_drag", side_effect=rec_drag),
        patch.object(gui_rec, "press_combo", side_effect=rec_combo),
        patch.object(gui_rec, "press_vk", side_effect=rec_vk),
        patch.object(gui_rec, "_emit_cursor"),
        patch("app.integrations.computer_use.fl_live_gui.time.sleep"),
    ):
        rec_res = gui_rec.paint_arrangement_to_playlist(
            sections=[{"name": "Intro", "bars": 4}, {"name": "Drop", "bars": 8}],
            role_patterns={"drums": 5},
        )
    assert rec_res["ok"] is True
    assert rec_res["verified"] is True
    assert rec_res["song_length_ticks"] >= 3072


@pytest.mark.asyncio
async def test_master_limiter_never_mutes_to_neg_inf_and_playlist_avoids_bar9_drift():
    """Guard against Fruity Limiter -INFdB (0.0 ceiling) mute, real FL25 Multiband/Sytrus names, and Bar 9 drift."""
    from app.integrations.computer_use.fl_live_gui import FLLiveGUIController
    from app.model_providers.provider import normalize_llm_plan
    from app.music_engine.mix_master import MixMasterEngine

    # 1. LLM emitting ceiling=0.0 (thinking 0 dBFS) is sanitized cleanly in both normalize_llm_plan and MixMasterEngine
    plan = normalize_llm_plan({
        "intent_type": "full_production",
        "tempo_bpm": 130,
        "fx_params": {"master": {"ceiling": 0.0, "clipper_thresh": 0.0}},
        "tracks": [
            {
                "role": "lead",
                "instrument_name": "Sytrus",
                "notes": [{"pitch": 62, "time_bars": 0.0, "length_bars": 0.5, "velocity": 0.85}],
            }
        ],
    })
    assert 0.44 <= plan["fx_params"]["master"]["ceiling"] <= 0.54
    assert plan["fx_params"]["master"]["clipper_thresh"] >= 0.58

    engine = MixMasterEngine()
    lim_updates = engine.match_plugin_params(
        "Fruity Limiter",
        [
            {"i": 0, "name": "Gain", "v": 0.5},
            {"i": 2, "name": "Limiter ceiling", "v": 0.5},
            {"i": 5, "name": "Limiter release time", "v": 0.4},
            {"i": 15, "name": "Noise gain", "v": 1.0},
            {"i": 16, "name": "Noise threshold", "v": 0.0},
        ],
        role="master",
        fx_params={"ceiling": 0.0, "gain": 0.0},
        mix_cfg={"target_ceiling_db": -1.0, "mood": "dark", "loud": True},
    )
    lim_map = {u["name"]: u["value"] for u in lim_updates}
    assert 0.44 <= lim_map["Limiter ceiling"] <= 0.54  # NEVER 0.0 (-INFdB)!
    assert lim_map["Gain"] >= 0.48
    assert "Noise gain" not in lim_map

    # 2. Real FL Studio 25 Multiband Compressor (L/M/H Threshold, Output, Master volume) & Sytrus (Master level)
    mb25 = engine.match_plugin_params(
        "Fruity Multiband Compressor",
        [
            {"i": 0, "name": "Master volume", "v": 0.5},
            {"i": 5, "name": "H Output", "v": 0.333},
            {"i": 6, "name": "H Threshold", "v": 0.7},
            {"i": 7, "name": "H Ratio", "v": 0.42},
            {"i": 14, "name": "M Output", "v": 0.333},
            {"i": 15, "name": "M Threshold", "v": 0.75},
            {"i": 22, "name": "L Output", "v": 0.333},
            {"i": 23, "name": "L Threshold", "v": 0.7},
        ],
        role="drums",
        mix_cfg={"mood": "dark", "loud": True},
    )
    mb25_map = {u["name"]: u["value"] for u in mb25}
    assert {"L Threshold", "M Threshold", "H Threshold", "Master volume"} <= set(mb25_map)
    assert mb25_map["Master volume"] >= 0.50

    sy_updates = engine.match_generator_params(
        "Sytrus",
        [
            {"i": 0, "name": "Main - Master level", "v": 0.8},
            {"i": 2, "name": "Main - Master pitch", "v": 0.5},
            {"i": 3, "name": "Main - Volume attack", "v": 0.1},
        ],
        role="lead",
        generator_params={"attack": 0.95, "master pitch": 0.0, "cutoff": 0.0},
    )
    sy_map = {u["name"]: u["value"] for u in sy_updates}
    assert "Main - Master pitch" not in sy_map
    assert sy_map["Main - Master level"] >= 0.75
    assert sy_map["Main - Volume attack"] <= 0.45

    # 3. Playlist calibration rejects a far-right Bar 9 hit (13.0 bars), erases it, and locks onto Bar 1 (4.0 bars),
    # while rewinding scrolled vis_bar (e.g. 21) back to 1 across rows!
    pl_state = {"clips": [], "vis_bar": 1, "song_pos": 0.0, "tool": "draw"}
    scroll_adapter = MagicMock()
    scroll_adapter.select_pattern.return_value = {"ok": True, "selected": 1}
    scroll_adapter.set_loop_mode.return_value = {"ok": True, "loop_mode": 1}

    def _set_pos(beats):
        prev = pl_state["song_pos"]
        pl_state["song_pos"] = float(beats)
        if float(beats) == 0.0 and prev > 0.0:
            pl_state["vis_bar"] = 1

    scroll_adapter.set_song_position.side_effect = _set_pos
    scroll_adapter.get_playlist_state.side_effect = lambda **kw: {
        "ok": True,
        "song_length_ticks": max((c[1] for c in pl_state["clips"]), default=0),
        "song_length_bars": round(max((c[1] for c in pl_state["clips"]), default=0) / 384.0, 4),
        "loop_mode": 1,
        "vis_bar": pl_state["vis_bar"],
    }

    placed_x_clicks = []

    def _pl_vk(vk, **kw):
        if vk == 0x50:  # VK_P
            pl_state["tool"] = "draw"
        elif vk == 0x45:  # VK_E
            pl_state["tool"] = "select"

    def _pl_click(x, y, **kw):
        if kw.get("right"):
            pl_state["clips"] = [c for c in pl_state["clips"] if abs(c[0] - x) > 15]
            return
        if pl_state["tool"] != "draw" or y < 220:
            return
        if x >= 350:
            placed_x_clicks.append(x)
            # Canvas starts at x=350 (Bar 1 -> 4.0 bars); x=500 lands at Bar 9 (13.0 bars!)
            end_ticks = 4992 if (x >= 460 or pl_state["vis_bar"] > 1) else 1536
            pl_state["clips"].append((x, end_ticks))

    def _pl_combo(mods, vk):
        if vk == 0x42:  # Ctrl+B scrolls FL right to vis_bar=21 while keeping song_pos=0!
            pl_state["vis_bar"] = 21
            if pl_state["clips"]:
                last_x, last_end = pl_state["clips"][-1]
                pl_state["clips"].append((last_x + 120, last_end + 1536))

    gui_bar1 = FLLiveGUIController(fl_adapter=scroll_adapter)
    with (
        patch.object(FLLiveGUIController, "is_supported", new_callable=PropertyMock, return_value=True),
        patch.object(gui_bar1, "focus_fl_studio", return_value=1234),
        patch.object(gui_bar1, "ensure_window_focused"),
        patch.object(gui_bar1, "find_fl_subwindow_rect", return_value=(100, 100, 1200, 750)),
        patch.object(gui_bar1, "_detect_playlist_bar1_x", return_value=500),  # Misleading dark marker at Bar 9!
        patch.object(gui_bar1, "smooth_click", side_effect=_pl_click),
        patch.object(gui_bar1, "press_combo", side_effect=_pl_combo),
        patch.object(gui_bar1, "press_vk", side_effect=_pl_vk),
        patch.object(gui_bar1, "_emit_cursor"),
        patch("app.integrations.computer_use.fl_live_gui.time.sleep"),
    ):
        bar1_res = gui_bar1.paint_arrangement_to_playlist(
            sections=[{"name": "Intro", "bars": 4}, {"name": "Drop", "bars": 8}],
            bars_per_pattern=4,
            role_patterns={"drums": 1, "chords": 2},
            clear_existing=False,
        )

    assert bar1_res["ok"] is True, f"Unexpected bar1_res={bar1_res}"
    assert bar1_res["song_length_bars"] <= 16.0  # Rejects 13-bar Bar-9 drift & rewinds vis_bar=21 back to 1!
    assert min(placed_x_clicks) < 460








