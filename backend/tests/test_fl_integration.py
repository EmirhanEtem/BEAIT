"""FL Studio adapter tests.

* MOCKED  -- default run; a fake bridge replaces MIDI/TCP. No FL Studio needed.
* REAL    -- marked ``real_fl``; requires FL Studio + flstudio-mcp daemon.
             Run explicitly:  pytest -m real_fl
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.integrations.fl_studio.adapter import (  # noqa: E402
    ConnectionStatus,
    FLStudioAdapter,
    TransportType,
)
from fl_studio_mcp.connection import FLBridgeError, FLTimeout  # noqa: E402


class FakeBridge:
    """Deterministic stand-in for FLBridge/TCPBridge (MOCKED)."""

    def __init__(self, tempo=120.0, swallow_writes=False, fail_with=None):
        self.tempo = tempo
        self.swallow_writes = swallow_writes
        self.fail_with = fail_with
        self.calls = []

    def call(self, command, params=None, timeout=None):
        self.calls.append((command, params))
        if self.fail_with:
            raise self.fail_with
        if command == "get_tempo":
            return {"bpm": self.tempo, "raw": int(self.tempo * 1000)}
        if command == "set_tempo":
            if not self.swallow_writes:
                self.tempo = float(params["bpm"])
            return {"bpm": self.tempo}
        if command == "get_project_state":
            return {"fl_version": "25.1.6", "tempo_bpm": self.tempo, "playing": False,
                    "recording": False, "pattern_number": 1, "pattern_count": 3,
                    "channel_count": 5, "mixer_track_count": 127}
        if command == "channel_list":
            start = (params or {}).get("start", 0)
            data = [{"i": i, "name": f"ch{i}"} for i in range(5)]
            page = data[start:start + 2]
            nxt = start + 2 if start + 2 < len(data) else None
            return {"total": len(data), "start": start, "next_start": nxt, "channels": page}
        if command == "ping":
            return {"fl_version": "25.1.6", "protocol_version": 2}
        raise AssertionError(f"unexpected command {command}")

    def heartbeat_age(self):
        return 0.2

    def is_alive(self):
        return True

    def close(self):
        pass


def make_adapter(**kw) -> tuple[FLStudioAdapter, FakeBridge]:
    a = FLStudioAdapter(transport=TransportType.TCP)
    fb = FakeBridge(**kw)
    a._bridge = fb
    return a, fb


# ---------------------------------------------------------------- MOCKED ---

class TestAdapterConstruction:
    def test_create_tcp_adapter(self):
        adapter = FLStudioAdapter(transport=TransportType.TCP)
        assert adapter._transport_type == TransportType.TCP
        assert adapter._bridge is None

    def test_create_direct_adapter(self):
        adapter = FLStudioAdapter(transport=TransportType.DIRECT)
        assert adapter._bridge is None

    def test_call_without_connect_raises(self):
        with pytest.raises(FLBridgeError, match="not connected"):
            FLStudioAdapter().ping()

    def test_health_without_connect(self):
        status = FLStudioAdapter().check_health()
        assert not status.connected and status.error

    def test_disconnect_is_idempotent(self):
        a = FLStudioAdapter()
        a.disconnect()
        a.disconnect()

    def test_connect_tcp_daemon_down_is_not_connected(self, monkeypatch):
        """No daemon -> connect() must NOT report connected (no faked state)."""
        monkeypatch.setenv("FLSTUDIO_MCP_TCP_PORT", "1")  # nothing listens on port 1
        status = FLStudioAdapter(TransportType.TCP).connect()
        assert not status.connected
        assert "daemon unreachable" in status.error


class TestConnectionStatus:
    def test_default_values(self):
        s = ConnectionStatus()
        assert not s.connected and not s.fl_studio_alive and s.error is None


class TestMockedReads:
    def test_read_tempo(self):
        a, _ = make_adapter(tempo=128.0)
        assert a.get_tempo() == 128.0

    def test_project_state_field_mapping(self):
        a, _ = make_adapter(tempo=140.0)
        st = a.get_project_state()
        assert st.tempo == 140.0
        assert st.channel_count == 5 and st.pattern_count == 3
        assert st.mixer_track_count == 127 and st.pattern_number == 1

    def test_paginated_channel_list(self):
        a, fb = make_adapter()
        channels = a.get_channels()
        assert [c["name"] for c in channels] == [f"ch{i}" for i in range(5)]
        assert sum(1 for c, _ in fb.calls if c == "channel_list") == 3

    def test_malformed_tempo_response_raises(self):
        a, fb = make_adapter()
        fb.call = lambda *a_, **k: {"unexpected": 1}
        with pytest.raises(FLBridgeError):
            a.get_tempo()

    def test_timeout_surfaces(self):
        a, _ = make_adapter(fail_with=FLTimeout("no answer"))
        with pytest.raises(FLTimeout):
            a.get_tempo()


class TestMockedVerifiedWrite:
    def test_set_tempo_verified_success(self):
        a, _ = make_adapter(tempo=120.0)
        r = a.set_tempo_verified(133.0)
        assert r.before == 120.0 and r.after == 133.0 and r.verified

    def test_swallowed_write_is_not_success(self):
        """FL ignores the write -> verified must be False even though the command was sent."""
        a, fb = make_adapter(tempo=120.0, swallow_writes=True)
        r = a.set_tempo_verified(133.0)
        assert ("set_tempo", {"bpm": 133.0}) in fb.calls
        assert not r.verified and r.after == 120.0


# ------------------------------------------------------------------ REAL ---

@pytest.mark.real_fl
class TestRealFLStudio:
    @pytest.fixture
    def adapter(self):
        a = FLStudioAdapter(transport=TransportType.TCP)
        status = a.connect()
        if not status.connected:
            pytest.fail(f"Daemon not reachable: {status.error}")
        yield a
        a.disconnect()

    def test_alive(self, adapter):
        s = adapter.check_health()
        assert s.fl_studio_alive, f"heartbeat age={s.heartbeat_age}"

    def test_ping(self, adapter):
        assert adapter.ping().get("protocol_version") == 2

    def test_read_tempo(self, adapter):
        assert 10 <= adapter.get_tempo() <= 999

    def test_read_project_state(self, adapter):
        st = adapter.get_project_state()
        assert st.tempo is not None and st.channel_count is not None

    def test_read_channels(self, adapter):
        assert isinstance(adapter.get_channels(), list)

    @pytest.mark.skipif(os.environ.get("FL_ALLOW_WRITE") != "1",
                        reason="write test needs explicit user approval: set FL_ALLOW_WRITE=1")
    def test_set_and_restore_tempo(self, adapter):
        original = adapter.get_tempo()
        test_bpm = 133.0 if abs(original - 133.0) > 0.01 else 127.0
        try:
            r = adapter.set_tempo_verified(test_bpm)
            assert r.verified, f"expected {test_bpm}, FL reports {r.after}"
        finally:
            restore = adapter.set_tempo_verified(original)
        assert restore.verified, f"restore failed: FL reports {restore.after}, original {original}"
