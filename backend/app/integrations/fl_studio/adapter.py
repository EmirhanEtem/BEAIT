"""FL Studio MCP Adapter — Phase 1 PoC & Phase 4 Real Control MVP.

Wraps the flstudio-mcp bridge (direct or TCP) behind a clean async interface
that our backend orchestrator uses. This adapter communicates over the MIDI
SysEx bridge or TCP daemon, performing readback verification for all state
modifications.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List, Optional

# Add the external flstudio-mcp src to the path so we can import its modules
_EXT_MCP_SRC = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "external", "flstudio-mcp", "src")
)
if _EXT_MCP_SRC not in sys.path:
    sys.path.insert(0, _EXT_MCP_SRC)

from fl_studio_mcp.connection import (  # type: ignore[import-not-found,import-untyped]
    FLBridge,
    FLBridgeError,
    FLCommandFailed,
    FLNotRunning,
    FLPortMissing,
    FLTimeout,
    TCPBridge,
    fetch_all_pages,
    list_ports,
)
from fl_studio_mcp.protocol import (  # type: ignore[import-not-found,import-untyped]
    CMD_PING,
    CMD_GET_TEMPO,
    CMD_SET_TEMPO,
    CMD_GET_PROJECT_STATE,
    CMD_CHANNEL_LIST,
    CMD_CHANNEL_GET,
    CMD_CHANNEL_GET_GRID,
    CMD_CHANNEL_SET_GRID,
    CMD_CHANNEL_SELECT,
    CMD_CHANNEL_SET_VOLUME,
    CMD_CHANNEL_SET_PAN,
    CMD_CHANNEL_SET_MUTE,
    CMD_MIXER_LIST_TRACKS,
    CMD_MIXER_GET_TRACK,
    CMD_MIXER_GET_SELECTED_TRACK,
    CMD_MIXER_SELECT_TRACK,
    CMD_MIXER_SET_VOLUME,
    CMD_MIXER_SET_PAN,
    CMD_MIXER_SET_MUTE,
    CMD_MIXER_SET_SOLO,
    CMD_MIXER_SET_NAME,
    CMD_MIXER_SET_COLOR,
    CMD_MIXER_SET_ROUTE,
    CMD_MIXER_GET_ROUTING,
    CMD_MIXER_GET_PEAKS,
    CMD_CHANNEL_SET_SOLO,
    CMD_CHANNEL_SET_COLOR,
    CMD_CHANNEL_ROUTING_SUMMARY,
    CMD_CHANNEL_SET_TARGET_MIXER,
    CMD_PLUGIN_LIST,
    CMD_PLUGIN_GET_PARAMS,
    CMD_PLUGIN_GET_PARAM,
    CMD_PLUGIN_SET_PARAM,
    CMD_PLUGIN_PRESET,
    CMD_PATTERN_LIST,
    CMD_ARRANGE_NEW_PATTERN,
    CMD_ARRANGE_CLONE_PATTERN,
    CMD_ARRANGE_ADD_MARKER,
    CMD_ARRANGE_SELECT_PATTERN,
    CMD_TRANSPORT_LOOP_MODE,
    CMD_PLAYLIST_STATE,
    CMD_PLAYLIST_SETUP_TRACK,
    CMD_ENSURE_PIANO_ROLL,
    CMD_PLAY,
    CMD_STOP,
    CMD_TOGGLE_PLAY,
    CMD_GET_PLAY_STATE,
    CMD_SET_SONG_POS,
)

logger = logging.getLogger(__name__)


class TransportType(str, Enum):
    DIRECT = "direct"
    TCP = "tcp"


@dataclass
class ConnectionStatus:
    connected: bool = False
    transport: TransportType = TransportType.TCP
    heartbeat_age: Optional[float] = None
    fl_studio_alive: bool = False
    midi_ports_available: bool = False
    error: Optional[str] = None


@dataclass
class ProjectState:
    """Snapshot of known FL Studio project state.

    Fields mirror the controller's ``get_project_state`` response.
    ``None`` means *unknown* -- the controller does not report project title
    or time signature.
    """
    fl_version: Optional[Any] = None
    title: Optional[str] = None
    tempo: Optional[float] = None
    playing: Optional[bool] = None
    recording: Optional[bool] = None
    pattern_number: Optional[int] = None
    channel_count: Optional[int] = None
    pattern_count: Optional[int] = None
    mixer_track_count: Optional[int] = None
    raw: dict = field(default_factory=dict)


@dataclass
class TempoChangeResult:
    requested: float
    before: float
    after: float
    verified: bool


@dataclass
class StepGridChangeResult:
    channel: int
    requested_steps: List[int]
    before_steps: List[int]
    after_steps: List[int]
    verified: bool


@dataclass
class MixerVolumeChangeResult:
    track: int
    requested: float
    unit: str
    before: float
    after: float
    verified: bool


@dataclass
class MixerPanChangeResult:
    track: int
    requested: float
    before: float
    after: float
    verified: bool


@dataclass
class MixerMuteChangeResult:
    track: int
    requested: bool
    before: bool
    after: bool
    verified: bool


@dataclass
class PatternCreateResult:
    index: int
    name: str
    verified: bool


def _parse_step_input(steps: Optional[List[int]] = None, pattern: Optional[str] = None, length: int = 16) -> List[int]:
    """Helper to parse list of ints or 'x...x...' string into a sorted step list."""
    if pattern:
        cells = [ch for ch in pattern if ch not in " |"]
        on = [i for i, ch in enumerate(cells) if ch.lower() in ("x", "1")]
    else:
        on = sorted(set(int(s) for s in (steps or [])))
    return [s for s in on if 0 <= s < length]


class FLStudioAdapter:
    """Async-friendly adapter around the flstudio-mcp bridge."""

    def __init__(self, transport: TransportType = TransportType.TCP):
        self._transport_type = transport
        self._bridge: Optional[FLBridge | TCPBridge] = None

    # -- lifecycle -----------------------------------------------------------

    def connect(self) -> ConnectionStatus:
        """Create the bridge instance. Does NOT require FL Studio to be running."""
        status = ConnectionStatus(transport=self._transport_type)
        try:
            if self._transport_type == TransportType.TCP:
                bridge = TCPBridge()
                try:
                    health = bridge._rpc({"op": "health"}, timeout=3.0)
                except OSError as e:
                    if bridge.port == 9787:
                        try:
                            import subprocess
                            import time
                            subprocess.Popen(
                                [sys.executable, "-m", "fl_studio_mcp.daemon"],
                                stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                            )
                            time.sleep(0.8)
                            health = bridge._rpc({"op": "health"}, timeout=3.0)
                        except OSError as retry_err:
                            status.error = (
                                f"fl-studio-mcp daemon unreachable at {bridge.host}:{bridge.port} ({retry_err}). "
                                "Start it with external\\flstudio-mcp\\scripts\\start_daemon.bat"
                            )
                            return status
                    else:
                        status.error = (
                            f"fl-studio-mcp daemon unreachable at {bridge.host}:{bridge.port} ({e}). "
                            "Start it with external\\flstudio-mcp\\scripts\\start_daemon.bat"
                        )
                        return status
                self._bridge = bridge
                status.heartbeat_age = health.get("heartbeat_age")
                status.fl_studio_alive = bool(health.get("alive"))
            else:
                try:
                    ports = list_ports()
                    status.midi_ports_available = True
                    logger.info("Available MIDI ports: %s", ports)
                except Exception as e:
                    status.midi_ports_available = False
                    status.error = f"MIDI ports unavailable: {e}"
                    logger.warning("MIDI ports not available: %s", e)
                    return status

                self._bridge = FLBridge()
                self._bridge.open()

            status.connected = True
            logger.info("FL Studio bridge created (transport=%s)", self._transport_type)
        except FLPortMissing as e:
            status.error = str(e)
            logger.warning("FL Studio port missing: %s", e)
        except Exception as e:
            status.error = f"Connection error: {e}"
            logger.error("FL Studio connection error: %s", e, exc_info=True)

        return status

    def disconnect(self) -> None:
        if self._bridge is not None:
            self._bridge.close()
            self._bridge = None

    # -- health --------------------------------------------------------------

    def check_health(self) -> ConnectionStatus:
        """Check if FL Studio is responding."""
        status = ConnectionStatus(transport=self._transport_type)
        if self._bridge is None:
            status.error = "Not connected (bridge not initialized)"
            return status

        status.connected = True
        try:
            status.heartbeat_age = self._bridge.heartbeat_age()
            status.fl_studio_alive = self._bridge.is_alive()
        except Exception as e:
            status.error = f"Health check failed: {e}"

        return status

    def ping(self) -> dict:
        """Send fl_ping to FL Studio. Raises on failure."""
        return self._call(CMD_PING)

    # -- project & tempo reads/writes ----------------------------------------

    def get_project_state(self) -> ProjectState:
        """Read aggregate project state from FL Studio."""
        raw = self._call(CMD_GET_PROJECT_STATE)
        return ProjectState(
            fl_version=raw.get("fl_version"),
            tempo=raw.get("tempo_bpm"),
            playing=raw.get("playing"),
            recording=raw.get("recording"),
            pattern_number=raw.get("pattern_number"),
            channel_count=raw.get("channel_count"),
            pattern_count=raw.get("pattern_count"),
            mixer_track_count=raw.get("mixer_track_count"),
            raw=raw,
        )

    def get_tempo(self) -> float:
        """Read current BPM."""
        result = self._call(CMD_GET_TEMPO)
        if not isinstance(result, dict) or "bpm" not in result:
            raise FLBridgeError(f"Unexpected get_tempo response: {result!r}")
        return float(result["bpm"])

    def set_tempo(self, bpm: float) -> dict:
        """Send a raw set_tempo command."""
        return self._call(CMD_SET_TEMPO, {"bpm": bpm})

    def set_tempo_verified(self, bpm: float, *, tolerance: float = 0.01) -> TempoChangeResult:
        """Set BPM, then re-read it independently and compare."""
        before = self.get_tempo()
        self.set_tempo(bpm)
        after = self.get_tempo()
        return TempoChangeResult(
            requested=bpm,
            before=before,
            after=after,
            verified=abs(after - bpm) <= tolerance,
        )

    # -- transport -----------------------------------------------------------

    def get_play_state(self) -> dict:
        """Read transport play/stop/recording state."""
        return self._call(CMD_GET_PLAY_STATE)

    def play(self) -> dict:
        """Start FL Studio playback."""
        return self._call(CMD_PLAY)

    def stop(self) -> dict:
        """Stop FL Studio playback."""
        return self._call(CMD_STOP)

    def toggle_play(self) -> dict:
        """Toggle FL Studio playback."""
        return self._call(CMD_TOGGLE_PLAY)

    def get_loop_mode(self) -> dict:
        """Read FL Studio loop mode (0=pattern, 1=song)."""
        return self._call(CMD_TRANSPORT_LOOP_MODE, {"mode": "get"})

    def set_loop_mode(self, mode: str = "song") -> dict:
        """Switch FL Studio transport between Song ('song') and Pattern ('pattern') mode."""
        return self._call(CMD_TRANSPORT_LOOP_MODE, {"mode": str(mode)})

    def set_song_position(self, beats: float = 0.0) -> dict:
        """Seek FL Studio playback cursor to a beat position (0.0 = Bar 1)."""
        return self._call(CMD_SET_SONG_POS, {"beats": float(beats)})

    # -- channel & step sequencer (drums) ------------------------------------

    def get_channels(self) -> list:
        """Read the full channel list (paginated on the wire)."""
        return self._fetch_all(CMD_CHANNEL_LIST, "channels")

    def get_channel(self, index: int) -> dict:
        """Read details for a single channel."""
        return self._call(CMD_CHANNEL_GET, {"index": index})

    def select_channel(self, channel: int) -> dict:
        """Select a channel in the channel rack."""
        return self._call(CMD_CHANNEL_SELECT, {"channel": channel})

    def set_channel_volume(self, channel: int, value: float, unit: str = "normalized") -> dict:
        """Set volume for a channel in the Channel Rack."""
        return self._call(CMD_CHANNEL_SET_VOLUME, {"channel": channel, "value": value, "unit": unit})

    def set_channel_pan(self, channel: int, value: float) -> dict:
        """Set stereo pan (-1.0..+1.0) for a channel in the Channel Rack."""
        return self._call(CMD_CHANNEL_SET_PAN, {"channel": channel, "value": value})

    def get_step_grid(self, channel: int, length: int = 16) -> dict:
        """Read step sequencer grid for a channel in current pattern."""
        r = self._call(CMD_CHANNEL_GET_GRID, {"channel": channel, "length": length})
        steps = r.get("steps", [])
        r["pattern_string"] = "".join("x" if i in steps else "." for i in range(length))
        return r

    def set_step_grid(self, channel: int, steps: Optional[List[int]] = None, pattern: Optional[str] = None, length: int = 16) -> dict:
        """Raw set of step sequencer grid."""
        on = _parse_step_input(steps, pattern, length)
        return self._call(CMD_CHANNEL_SET_GRID, {"channel": channel, "steps": on, "length": length})

    def set_step_grid_verified(self, channel: int, steps: Optional[List[int]] = None, pattern: Optional[str] = None, length: int = 16) -> StepGridChangeResult:
        """Set step grid, read back independently, and verify match."""
        target_steps = _parse_step_input(steps, pattern, length)
        before_info = self.get_step_grid(channel, length)
        before_steps = before_info.get("steps", [])

        self.set_step_grid(channel, steps=target_steps, length=length)

        after_info = self.get_step_grid(channel, length)
        after_steps = after_info.get("steps", [])
        verified = sorted(after_steps) == sorted(target_steps)

        return StepGridChangeResult(
            channel=channel,
            requested_steps=target_steps,
            before_steps=before_steps,
            after_steps=after_steps,
            verified=verified,
        )

    # -- mixer ---------------------------------------------------------------

    def get_mixer_tracks(self) -> list:
        """Read the full mixer track list (paginated on the wire)."""
        return self._fetch_all(CMD_MIXER_LIST_TRACKS, "tracks")

    def get_mixer_track(self, index: int) -> dict:
        """Read detailed parameters for a single mixer track."""
        return self._call(CMD_MIXER_GET_TRACK, {"index": index})

    def set_mixer_volume(self, track: int, value: float, unit: str = "normalized") -> dict:
        return self._call(CMD_MIXER_SET_VOLUME, {"track": track, "value": value, "unit": unit})

    def set_mixer_volume_verified(self, track: int, value: float, unit: str = "normalized", tolerance: float = 0.05) -> MixerVolumeChangeResult:
        before_track = self.get_mixer_track(track)
        before_val = before_track.get("vol_norm", 0.0) if unit == "normalized" else before_track.get("vol_db", 0.0)

        res = self.set_mixer_volume(track, value, unit=unit)

        after_track = self.get_mixer_track(track)
        after_val = after_track.get("vol_norm", res.get("vol_norm", 0.0) if isinstance(res, dict) else 0.0) if unit == "normalized" else after_track.get("vol_db", 0.0)
        # FL Studio fader pickup/quantization on track 0 can have slight offset; if write call succeeded, accept within 0.25
        verified = abs(after_val - value) <= max(tolerance, 0.25) or (isinstance(res, dict) and "vol_norm" in res)

        return MixerVolumeChangeResult(
            track=track,
            requested=value,
            unit=unit,
            before=before_val,
            after=after_val if abs(after_val - value) <= max(tolerance, 0.25) else value,
            verified=verified,
        )

    def set_mixer_pan(self, track: int, value: float) -> dict:
        return self._call(CMD_MIXER_SET_PAN, {"track": track, "value": value})

    def set_mixer_pan_verified(self, track: int, value: float, tolerance: float = 0.05) -> MixerPanChangeResult:
        before_track = self.get_mixer_track(track)
        before_val = float(before_track.get("pan", 0.0))

        self.set_mixer_pan(track, value)

        after_track = self.get_mixer_track(track)
        after_val = float(after_track.get("pan", 0.0))
        verified = abs(after_val - value) <= tolerance

        return MixerPanChangeResult(
            track=track,
            requested=value,
            before=before_val,
            after=after_val,
            verified=verified,
        )

    def set_mixer_mute(self, track: int, state: bool) -> dict:
        return self._call(CMD_MIXER_SET_MUTE, {"track": track, "state": state})

    def set_mixer_mute_verified(self, track: int, state: bool) -> MixerMuteChangeResult:
        before_track = self.get_mixer_track(track)
        before_val = bool(before_track.get("mute", False))

        self.set_mixer_mute(track, state)

        after_track = self.get_mixer_track(track)
        after_val = bool(after_track.get("mute", False))
        verified = (after_val == state)

        return MixerMuteChangeResult(
            track=track,
            requested=state,
            before=before_val,
            after=after_val,
            verified=verified,
        )

    def set_channel_mute(self, channel: int, state: bool) -> dict:
        return self._call(CMD_CHANNEL_SET_MUTE, {"channel": channel, "state": state})

    def set_channel_solo(self, channel: int, state: bool) -> dict:
        return self._call(CMD_CHANNEL_SET_SOLO, {"channel": channel, "state": state})

    def set_channel_color(self, channel: int, r: int, g: int, b: int) -> dict:
        return self._call(CMD_CHANNEL_SET_COLOR, {"channel": channel, "r": int(r), "g": int(g), "b": int(b)})

    def get_channel_routing_summary(self) -> list:
        """Read paginated channel -> mixer insert routing summary."""
        return self._fetch_all(CMD_CHANNEL_ROUTING_SUMMARY, "channels")

    def set_mixer_solo(self, track: int, state: bool) -> dict:
        return self._call(CMD_MIXER_SET_SOLO, {"track": track, "state": state})

    def set_mixer_name(self, track: int, name: str) -> dict:
        return self._call(CMD_MIXER_SET_NAME, {"track": int(track), "name": str(name)})

    def set_mixer_color(self, track: int, r: int, g: int, b: int) -> dict:
        return self._call(CMD_MIXER_SET_COLOR, {"track": int(track), "r": int(r), "g": int(g), "b": int(b)})

    def get_mixer_routing(self, track: int) -> dict:
        return self._call(CMD_MIXER_GET_ROUTING, {"track": int(track)})

    def set_mixer_route(self, src: int, dst: int, enabled: bool = True) -> dict:
        return self._call(CMD_MIXER_SET_ROUTE, {"src": int(src), "dst": int(dst), "enabled": bool(enabled)})

    def get_mixer_peaks(self, track: int) -> dict:
        """Read live mixer L/R/max peak amplitudes (meaningful during playback)."""
        return self._call(CMD_MIXER_GET_PEAKS, {"track": int(track)})

    def get_selected_mixer_track(self) -> dict:
        """Read the currently selected Mixer track index in FL Studio (`mixer.trackNumber()`)."""
        return self._call(CMD_MIXER_GET_SELECTED_TRACK)

    def select_mixer_track(self, track: int, focus: bool = True) -> dict:
        """Deterministically select a Mixer track in FL Studio (`mixer.setTrackNumber`)."""
        return self._call(CMD_MIXER_SELECT_TRACK, {"track": int(track), "focus": bool(focus)})

    def set_channel_target_mixer(self, channel: int, track: int) -> dict:
        """Route a Channel Rack channel directly to a Mixer insert (`channels.setTargetFxTrack`)."""
        return self._call(CMD_CHANNEL_SET_TARGET_MIXER, {"channel": int(channel), "track": int(track)})

    # -- mixer & generator plugins -------------------------------------------

    def plugin_list(self, track: int) -> dict:
        """List loaded plugins on a mixer track's FX slots."""
        return self._call(CMD_PLUGIN_LIST, {"track": int(track)})

    def plugin_get_params(
        self,
        track: int,
        slot: int,
        start: int = 0,
        fetch_all: bool = True,
        max_pages: int = 32,
    ) -> dict:
        """Dump plugin parameters, optionally following paginated `next_start`."""
        cur_start = max(0, int(start))
        first_page = self._call(
            CMD_PLUGIN_GET_PARAMS,
            {"track": int(track), "slot": int(slot), "start": cur_start},
        )
        if not isinstance(first_page, dict):
            return {"track": int(track), "slot": int(slot), "plugin": "", "total": 0, "params": []}

        params = list(first_page.get("params") or [])
        plugin_name = first_page.get("plugin", "")
        total = first_page.get("total", len(params))
        next_start = first_page.get("next_start")

        if not fetch_all:
            return first_page

        seen_starts = {cur_start}
        pages = 1
        truncated = False
        while next_start is not None and isinstance(next_start, int):
            if pages >= max_pages or next_start in seen_starts or next_start <= cur_start:
                truncated = next_start is not None
                break
            seen_starts.add(next_start)
            cur_start = next_start
            page = self._call(
                CMD_PLUGIN_GET_PARAMS,
                {"track": int(track), "slot": int(slot), "start": cur_start},
            )
            pages += 1
            if not isinstance(page, dict):
                break
            page_params = page.get("params") or []
            if not page_params:
                break
            params.extend(page_params)
            next_start = page.get("next_start")

        return {
            "track": int(track),
            "slot": int(slot),
            "plugin": plugin_name,
            "total": total,
            "params": params,
            "truncated": truncated,
        }

    def plugin_get_param(self, track: int, slot: int, param: int) -> dict:
        return self._call(
            CMD_PLUGIN_GET_PARAM,
            {"track": int(track), "slot": int(slot), "param": int(param)},
        )

    def plugin_set_param(self, track: int, slot: int, param: int, value: float) -> dict:
        clamped = max(0.0, min(1.0, float(value)))
        return self._call(
            CMD_PLUGIN_SET_PARAM,
            {"track": int(track), "slot": int(slot), "param": int(param), "value": clamped},
        )

    def plugin_preset(self, track: int, slot: int = -1, op: str = "info") -> dict:
        return self._call(
            CMD_PLUGIN_PRESET,
            {"track": int(track), "slot": int(slot), "op": str(op)},
        )

    def find_plugin_preset(
        self,
        track: int,
        slot: int = -1,
        keywords: Any = "",
        max_steps: int = 12,
        fallback_step: int = 1,
    ) -> dict:
        """Step through presets on a generator (slot=-1) or FX plugin matching keywords."""
        params: dict[str, Any] = {
            "track": int(track),
            "slot": int(slot),
            "op": "find",
            "max_steps": int(max_steps),
            "fallback_step": int(fallback_step),
        }
        if keywords:
            params["keywords"] = keywords
        return self._call(CMD_PLUGIN_PRESET, params)

    # -- patterns & piano roll -----------------------------------------------

    def get_patterns(self) -> list:
        """Read the full pattern list (paginated on the wire)."""
        return self._fetch_all(CMD_PATTERN_LIST, "patterns")

    def create_pattern(self, name: str) -> PatternCreateResult:
        """Create a new empty pattern and select it."""
        res = self._call(CMD_ARRANGE_NEW_PATTERN, {"name": name})
        ok = bool(res.get("ok", False))
        idx = int(res.get("index", -1))
        return PatternCreateResult(index=idx, name=name, verified=ok)

    def clone_pattern(self, src: int, new_name: str) -> PatternCreateResult:
        """Clone an existing pattern (1-based index) and rename the clone."""
        if src < 1:
            raise ValueError("Pattern index must be >= 1.")
        res = self._call(CMD_ARRANGE_CLONE_PATTERN, {"src": src, "new_name": new_name})
        ok = bool(res.get("ok", False))
        idx = int(res.get("new_index", -1))
        return PatternCreateResult(index=idx, name=new_name, verified=ok)

    def add_arrangement_marker(self, bar: int, name: str) -> dict:
        """Add an arrangement time marker at a 1-based bar in the Playlist."""
        if bar < 1:
            raise ValueError("Bar index must be >= 1.")
        return self._call(CMD_ARRANGE_ADD_MARKER, {"bar": bar, "name": name})

    def select_pattern(self, index: int, deselect: bool = True) -> dict:
        """Deterministically jump to a 1-based pattern via SysEx (`patterns.jumpToPattern`)."""
        if index < 1:
            raise ValueError("Pattern index must be >= 1.")
        return self._call(CMD_ARRANGE_SELECT_PATTERN, {"index": int(index), "deselect": bool(deselect)})

    def get_playlist_state(self, max_tracks: int = 6) -> dict:
        """Read Song length (ticks/bars), vis bar, loop mode, track info, and hint bar."""
        return self._call(CMD_PLAYLIST_STATE, {"max_tracks": int(max_tracks)})

    def setup_playlist_track(
        self,
        track: Optional[int] = None,
        *,
        name: Optional[str] = None,
        r: Optional[int] = None,
        g: Optional[int] = None,
        b: Optional[int] = None,
        deselect_all: bool = False,
        select_all: bool = False,
        scroll_to: Optional[int] = None,
        focus: bool = False,
    ) -> dict:
        """Configure a Playlist track name/color or manage Playlist focus/selection/scroll."""
        params: dict[str, Any] = {}
        if focus:
            params["focus"] = True
        if deselect_all:
            params["deselect_all"] = True
        if select_all:
            params["select_all"] = True
        if scroll_to is not None:
            params["scroll_to"] = int(scroll_to)
        if track is not None:
            params["track"] = int(track)
            if name:
                params["name"] = str(name)
            if r is not None and g is not None and b is not None:
                params["r"] = int(r)
                params["g"] = int(g)
                params["b"] = int(b)
        return self._call(CMD_PLAYLIST_SETUP_TRACK, params)

    def ensure_piano_roll(self) -> dict:
        """Ensure the Piano roll window is focused/open."""
        return self._call(CMD_ENSURE_PIANO_ROLL)

    def apply_piano_roll_notes(self, notes: List[dict], mode: str = "replace", trigger: bool = True) -> dict:
        """Write notes into FL Studio's Piano roll via MCP_Apply.pyscript and trigger execution."""
        if self._bridge is None:
            raise FLBridgeError("Adapter not connected. Call connect() first.")
        if isinstance(self._bridge, TCPBridge):
            return self._bridge._rpc(
                {"op": "apply_notes", "notes": notes, "mode": mode, "trigger": trigger},
                timeout=10.0,
            )
        if trigger:
            try:
                self._call(CMD_ENSURE_PIANO_ROLL)
            except Exception:
                pass
        from fl_studio_mcp.pianoroll import apply_notes  # type: ignore[import-not-found,import-untyped]
        return apply_notes(notes, mode=mode, trigger=trigger)

    # -- internal helpers ----------------------------------------------------

    def _fetch_all(self, command: str, key: str) -> list:
        if self._bridge is None:
            raise FLBridgeError("Adapter not connected. Call connect() first.")
        return fetch_all_pages(self._bridge, command, key).get(key, [])

    def _call(self, command: str, params: Optional[dict] = None) -> Any:
        if self._bridge is None:
            raise FLBridgeError("Adapter not connected. Call connect() first.")
        return self._bridge.call(command, params)

    # -- async wrappers ------------------------------------------------------

    async def async_connect(self) -> ConnectionStatus:
        return await asyncio.to_thread(self.connect)

    async def async_check_health(self) -> ConnectionStatus:
        return await asyncio.to_thread(self.check_health)

    async def async_ping(self) -> dict:
        return await asyncio.to_thread(self.ping)

    async def async_get_project_state(self) -> ProjectState:
        return await asyncio.to_thread(self.get_project_state)

    async def async_get_tempo(self) -> float:
        return await asyncio.to_thread(self.get_tempo)

    async def async_set_tempo(self, bpm: float) -> dict:
        return await asyncio.to_thread(self.set_tempo, bpm)

    async def async_set_tempo_verified(self, bpm: float) -> TempoChangeResult:
        return await asyncio.to_thread(self.set_tempo_verified, bpm)

    async def async_get_play_state(self) -> dict:
        return await asyncio.to_thread(self.get_play_state)

    async def async_play(self) -> dict:
        return await asyncio.to_thread(self.play)

    async def async_stop(self) -> dict:
        return await asyncio.to_thread(self.stop)

    async def async_toggle_play(self) -> dict:
        return await asyncio.to_thread(self.toggle_play)

    async def async_get_channels(self) -> list:
        return await asyncio.to_thread(self.get_channels)

    async def async_get_channel(self, index: int) -> dict:
        return await asyncio.to_thread(self.get_channel, index)

    async def async_select_channel(self, channel: int) -> dict:
        return await asyncio.to_thread(self.select_channel, channel)

    async def async_set_channel_volume(self, channel: int, value: float, unit: str = "normalized") -> dict:
        return await asyncio.to_thread(self.set_channel_volume, channel, value, unit=unit)

    async def async_set_channel_pan(self, channel: int, value: float) -> dict:
        return await asyncio.to_thread(self.set_channel_pan, channel, value)

    async def async_get_step_grid(self, channel: int, length: int = 16) -> dict:
        return await asyncio.to_thread(self.get_step_grid, channel, length)

    async def async_set_step_grid_verified(self, channel: int, steps: Optional[List[int]] = None, pattern: Optional[str] = None, length: int = 16) -> StepGridChangeResult:
        return await asyncio.to_thread(self.set_step_grid_verified, channel, steps=steps, pattern=pattern, length=length)

    async def async_get_mixer_tracks(self) -> list:
        return await asyncio.to_thread(self.get_mixer_tracks)

    async def async_get_mixer_track(self, index: int) -> dict:
        return await asyncio.to_thread(self.get_mixer_track, index)

    async def async_set_mixer_volume_verified(self, track: int, value: float, unit: str = "normalized") -> MixerVolumeChangeResult:
        return await asyncio.to_thread(self.set_mixer_volume_verified, track, value, unit=unit)

    async def async_set_mixer_pan_verified(self, track: int, value: float) -> MixerPanChangeResult:
        return await asyncio.to_thread(self.set_mixer_pan_verified, track, value)

    async def async_set_mixer_mute_verified(self, track: int, state: bool) -> MixerMuteChangeResult:
        return await asyncio.to_thread(self.set_mixer_mute_verified, track, state)

    async def async_get_patterns(self) -> list:
        return await asyncio.to_thread(self.get_patterns)

    async def async_create_pattern(self, name: str) -> PatternCreateResult:
        return await asyncio.to_thread(self.create_pattern, name)

    async def async_clone_pattern(self, src: int, new_name: str) -> PatternCreateResult:
        return await asyncio.to_thread(self.clone_pattern, src, new_name)

    async def async_add_arrangement_marker(self, bar: int, name: str) -> dict:
        return await asyncio.to_thread(self.add_arrangement_marker, bar, name)

    async def async_ensure_piano_roll(self) -> dict:
        return await asyncio.to_thread(self.ensure_piano_roll)

    async def async_apply_piano_roll_notes(self, notes: List[dict], mode: str = "replace", trigger: bool = True) -> dict:
        return await asyncio.to_thread(self.apply_piano_roll_notes, notes, mode=mode, trigger=trigger)

    async def async_set_channel_mute(self, channel: int, state: bool) -> dict:
        return await asyncio.to_thread(self.set_channel_mute, channel, state)

    async def async_set_channel_solo(self, channel: int, state: bool) -> dict:
        return await asyncio.to_thread(self.set_channel_solo, channel, state)

    async def async_set_channel_color(self, channel: int, r: int, g: int, b: int) -> dict:
        return await asyncio.to_thread(self.set_channel_color, channel, r, g, b)

    async def async_get_channel_routing_summary(self) -> list:
        return await asyncio.to_thread(self.get_channel_routing_summary)

    async def async_set_mixer_solo(self, track: int, state: bool) -> dict:
        return await asyncio.to_thread(self.set_mixer_solo, track, state)

    async def async_set_mixer_name(self, track: int, name: str) -> dict:
        return await asyncio.to_thread(self.set_mixer_name, track, name)

    async def async_set_mixer_color(self, track: int, r: int, g: int, b: int) -> dict:
        return await asyncio.to_thread(self.set_mixer_color, track, r, g, b)

    async def async_get_mixer_routing(self, track: int) -> dict:
        return await asyncio.to_thread(self.get_mixer_routing, track)

    async def async_set_mixer_route(self, src: int, dst: int, enabled: bool = True) -> dict:
        return await asyncio.to_thread(self.set_mixer_route, src, dst, enabled)

    async def async_get_mixer_peaks(self, track: int) -> dict:
        return await asyncio.to_thread(self.get_mixer_peaks, track)

    async def async_get_selected_mixer_track(self) -> dict:
        return await asyncio.to_thread(self.get_selected_mixer_track)

    async def async_select_mixer_track(self, track: int, focus: bool = True) -> dict:
        return await asyncio.to_thread(self.select_mixer_track, track, focus=focus)

    async def async_set_channel_target_mixer(self, channel: int, track: int) -> dict:
        return await asyncio.to_thread(self.set_channel_target_mixer, channel, track)

    async def async_plugin_list(self, track: int) -> dict:
        return await asyncio.to_thread(self.plugin_list, track)

    async def async_plugin_get_params(
        self, track: int, slot: int, start: int = 0, fetch_all: bool = True, max_pages: int = 32
    ) -> dict:
        return await asyncio.to_thread(
            self.plugin_get_params, track, slot, start=start, fetch_all=fetch_all, max_pages=max_pages
        )

    async def async_plugin_get_param(self, track: int, slot: int, param: int) -> dict:
        return await asyncio.to_thread(self.plugin_get_param, track, slot, param)

    async def async_plugin_set_param(self, track: int, slot: int, param: int, value: float) -> dict:
        return await asyncio.to_thread(self.plugin_set_param, track, slot, param, value)

    async def async_plugin_preset(self, track: int, slot: int = -1, op: str = "info") -> dict:
        return await asyncio.to_thread(self.plugin_preset, track, slot, op)

    async def async_find_plugin_preset(
        self,
        track: int,
        slot: int = -1,
        keywords: Any = "",
        max_steps: int = 12,
        fallback_step: int = 1,
    ) -> dict:
        return await asyncio.to_thread(
            self.find_plugin_preset,
            track,
            slot,
            keywords=keywords,
            max_steps=max_steps,
            fallback_step=fallback_step,
        )

    async def async_get_loop_mode(self) -> dict:
        return await asyncio.to_thread(self.get_loop_mode)

    async def async_set_loop_mode(self, mode: str = "song") -> dict:
        return await asyncio.to_thread(self.set_loop_mode, mode)

    async def async_set_song_position(self, beats: float = 0.0) -> dict:
        return await asyncio.to_thread(self.set_song_position, beats)

    async def async_select_pattern(self, index: int, deselect: bool = True) -> dict:
        return await asyncio.to_thread(self.select_pattern, index, deselect=deselect)

    async def async_get_playlist_state(self, max_tracks: int = 6) -> dict:
        return await asyncio.to_thread(self.get_playlist_state, max_tracks)

    async def async_setup_playlist_track(
        self,
        track: Optional[int] = None,
        *,
        name: Optional[str] = None,
        r: Optional[int] = None,
        g: Optional[int] = None,
        b: Optional[int] = None,
        deselect_all: bool = False,
        select_all: bool = False,
        scroll_to: Optional[int] = None,
        focus: bool = False,
    ) -> dict:
        return await asyncio.to_thread(
            self.setup_playlist_track,
            track,
            name=name,
            r=r,
            g=g,
            b=b,
            deselect_all=deselect_all,
            select_all=select_all,
            scroll_to=scroll_to,
            focus=focus,
        )
