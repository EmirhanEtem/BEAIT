"""Unit and mocked integration tests for FL Studio Adapter Phase 4 features."""

from unittest.mock import MagicMock
import pytest
from app.integrations.fl_studio.adapter import (
    FLStudioAdapter,
    MixerMuteChangeResult,
    MixerPanChangeResult,
    MixerVolumeChangeResult,
    PatternCreateResult,
    StepGridChangeResult,
    TransportType,
)
from app.sessions.test_project import TestProjectSession


@pytest.fixture
def mocked_adapter():
    adapter = FLStudioAdapter(transport=TransportType.TCP)
    mock_bridge = MagicMock()
    adapter._bridge = mock_bridge
    return adapter, mock_bridge


def test_step_grid_mocked_verified_success(mocked_adapter):
    adapter, bridge = mocked_adapter

    # 1st call: get_step_grid (before) -> steps [0, 4]
    # 2nd call: set_step_grid -> sets [0, 4, 8, 12]
    # 3rd call: get_step_grid (after) -> steps [0, 4, 8, 12]
    bridge.call.side_effect = [
        {"channel": 0, "length": 16, "steps": [0, 4]},
        {"channel": 0, "length": 16, "steps": [0, 4, 8, 12]},
        {"channel": 0, "length": 16, "steps": [0, 4, 8, 12]},
    ]

    res = adapter.set_step_grid_verified(0, steps=[0, 4, 8, 12], length=16)
    assert isinstance(res, StepGridChangeResult)
    assert res.channel == 0
    assert res.requested_steps == [0, 4, 8, 12]
    assert res.before_steps == [0, 4]
    assert res.after_steps == [0, 4, 8, 12]
    assert res.verified is True


def test_step_grid_mocked_verified_failure(mocked_adapter):
    adapter, bridge = mocked_adapter

    # After call returns mismatched steps
    bridge.call.side_effect = [
        {"channel": 0, "length": 16, "steps": []},
        {"channel": 0, "length": 16, "steps": []},
        {"channel": 0, "length": 16, "steps": [0]},  # mismatch!
    ]

    res = adapter.set_step_grid_verified(0, steps=[0, 4, 8, 12], length=16)
    assert res.verified is False
    assert res.after_steps == [0]


def test_mixer_volume_verified_success(mocked_adapter):
    adapter, bridge = mocked_adapter

    # 1. get_mixer_track (before)
    # 2. set_mixer_volume
    # 3. get_mixer_track (after)
    bridge.call.side_effect = [
        {"i": 1, "vol_norm": 0.8, "vol_db": 0.0},
        {"track": 1, "vol_norm": 0.65},
        {"i": 1, "vol_norm": 0.65, "vol_db": -1.8},
    ]

    res = adapter.set_mixer_volume_verified(1, 0.65, unit="normalized")
    assert isinstance(res, MixerVolumeChangeResult)
    assert res.verified is True
    assert res.before == 0.8
    assert res.after == 0.65


def test_mixer_pan_verified_success(mocked_adapter):
    adapter, bridge = mocked_adapter

    bridge.call.side_effect = [
        {"i": 2, "pan": 0.0},
        {"track": 2, "pan": -0.5},
        {"i": 2, "pan": -0.5},
    ]

    res = adapter.set_mixer_pan_verified(2, -0.5)
    assert isinstance(res, MixerPanChangeResult)
    assert res.verified is True
    assert res.before == 0.0
    assert res.after == -0.5


def test_mixer_mute_verified_success(mocked_adapter):
    adapter, bridge = mocked_adapter

    bridge.call.side_effect = [
        {"i": 3, "mute": False},
        {"track": 3, "mute": True},
        {"i": 3, "mute": True},
    ]

    res = adapter.set_mixer_mute_verified(3, True)
    assert isinstance(res, MixerMuteChangeResult)
    assert res.verified is True
    assert res.before is False
    assert res.after is True


def test_pattern_create_success(mocked_adapter):
    adapter, bridge = mocked_adapter

    bridge.call.return_value = {"ok": True, "index": 2, "name": "Intro_Beat"}
    res = adapter.create_pattern("Intro_Beat")
    assert isinstance(res, PatternCreateResult)
    assert res.verified is True
    assert res.index == 2
    assert res.name == "Intro_Beat"


def test_transport_commands(mocked_adapter):
    adapter, bridge = mocked_adapter

    bridge.call.return_value = {"ok": True}
    adapter.play()
    bridge.call.assert_called_with("play", None)

    adapter.stop()
    bridge.call.assert_called_with("stop", None)

    adapter.toggle_play()
    bridge.call.assert_called_with("toggle_play", None)


@pytest.mark.asyncio
async def test_session_baseline_capture_and_restore(mocked_adapter):
    adapter, bridge = mocked_adapter
    session = TestProjectSession(adapter)

    # Mock responses for capture_baseline
    bridge.call.side_effect = [
        {"bpm": 130.0},                                              # get_tempo
        {"tempo_bpm": 130.0, "channel_count": 1, "pattern_number": 1, "mixer_track_count": 10}, # project state
        {"total": 1, "start": 0, "next_start": None, "channels": [{"i": 0, "name": "808 Kick"}]}, # channel list page
        {"channel": 0, "length": 16, "steps": [0, 4]},               # step grid
        {"i": 0, "name": "Master", "vol_norm": 0.8},                 # mixer 0
    ]

    baseline = await session.capture_baseline()
    assert baseline.tempo == 130.0
    assert 0 in baseline.step_grids
    assert baseline.step_grids[0] == [0, 4]

    # Mock responses for restore_baseline
    # 1. set_tempo_verified (before, set, after)
    # 2. set_step_grid_verified (before, set, after)
    # 3. set_mixer_volume_verified (before, set, after)
    bridge.call.side_effect = [
        {"bpm": 140.0}, {"bpm": 130.0}, {"bpm": 130.0},  # tempo restore
        {"channel": 0, "steps": [0, 2]}, {"channel": 0, "steps": [0, 4]}, {"channel": 0, "steps": [0, 4]}, # grid restore
        {"i": 0, "vol_norm": 0.5}, {"track": 0, "vol_norm": 0.8}, {"i": 0, "vol_norm": 0.8}, # mixer restore
    ]

    restored = await session.restore_baseline()
    assert restored.get("tempo_restored") is True
    assert restored.get("grid_restores", {}).get(0) is True
    assert restored.get("master_volume_restored") is True
