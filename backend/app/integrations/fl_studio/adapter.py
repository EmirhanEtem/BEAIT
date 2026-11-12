"""FL Studio MCP Adapter — Phase 1 PoC.

Wraps the flstudio-mcp bridge (direct or TCP) behind a clean async interface
that our backend orchestrator uses.  This adapter never imports FL Studio
internals; it communicates over the MIDI SysEx bridge or TCP daemon.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

# Add the external flstudio-mcp src to the path so we can import its modules
_EXT_MCP_SRC = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "external", "flstudio-mcp", "src")
)
if _EXT_MCP_SRC not in sys.path:
    sys.path.insert(0, _EXT_MCP_SRC)

from fl_studio_mcp.connection import (
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
from fl_studio_mcp.protocol import (
    CMD_PING,
    CMD_GET_TEMPO,
    CMD_SET_TEMPO,
    CMD_GET_PROJECT_STATE,
    CMD_CHANNEL_LIST,
    CMD_MIXER_LIST_TRACKS,
    CMD_PATTERN_LIST,
    CMD_GET_PLAY_STATE,
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

    Fields mirror the controller's ``get_project_state`` response
    (device_FLStudioMCP.py @ 30ad112). ``None`` means *unknown* -- the
    controller does not report project title or time signature.
    """
    fl_version: Optional[Any] = None
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


class FLStudioAdapter:
    """Async-friendly adapter around the flstudio-mcp bridge."""

    def __init__(self, transport: TransportType = TransportType.TCP):
        self._transport_type = transport
        self._bridge: Optional[FLBridge | TCPBridge] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

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
                    status.error = (
                        f"fl-studio-mcp daemon unreachable at {bridge.host}:{bridge.port} ({e}). "
                        "Start it with external\\flstudio-mcp\\scripts\\start_daemon.bat"
                    )
                    return status
                self._bridge = bridge
                status.heartbeat_age = health.get("heartbeat_age")
                status.fl_studio_alive = bool(health.get("alive"))
            else:
                # Check MIDI ports first
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

    # -- project reads -------------------------------------------------------

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
        """Read current BPM (controller returns ``{"bpm", "raw"}``)."""
        result = self._call(CMD_GET_TEMPO)
        if not isinstance(result, dict) or "bpm" not in result:
            raise FLBridgeError(f"Unexpected get_tempo response: {result!r}")
        return float(result["bpm"])

    def set_tempo(self, bpm: float) -> dict:
        """Send a raw set_tempo command. Prefer :meth:`set_tempo_verified`."""
        return self._call(CMD_SET_TEMPO, {"bpm": bpm})

    def set_tempo_verified(self, bpm: float, *, tolerance: float = 0.01) -> TempoChangeResult:
        """Set BPM, then re-read it independently and compare.

        A sent command is never treated as success on its own.
        """
        before = self.get_tempo()
        self.set_tempo(bpm)
        after = self.get_tempo()
        return TempoChangeResult(requested=bpm, before=before, after=after,
                                 verified=abs(after - bpm) <= tolerance)

    def get_play_state(self) -> dict:
        """Read transport play/stop/recording state."""
        return self._call(CMD_GET_PLAY_STATE)

    def get_channels(self) -> list:
        """Read the full channel list (paginated on the wire)."""
        return self._fetch_all(CMD_CHANNEL_LIST, "channels")

    def get_mixer_tracks(self) -> list:
        """Read the full mixer track list (paginated on the wire)."""
        return self._fetch_all(CMD_MIXER_LIST_TRACKS, "tracks")

    def get_patterns(self) -> list:
        """Read the full pattern list (paginated on the wire)."""
        return self._fetch_all(CMD_PATTERN_LIST, "patterns")

    def _fetch_all(self, command: str, key: str) -> list:
        if self._bridge is None:
            raise FLBridgeError("Adapter not connected. Call connect() first.")
        return fetch_all_pages(self._bridge, command, key).get(key, [])

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

    async def async_get_channels(self) -> list:
        return await asyncio.to_thread(self.get_channels)

    async def async_get_mixer_tracks(self) -> list:
        return await asyncio.to_thread(self.get_mixer_tracks)

    async def async_get_patterns(self) -> list:
        return await asyncio.to_thread(self.get_patterns)

    # -- internal ------------------------------------------------------------

    def _call(self, command: str, params: Optional[dict] = None) -> Any:
        if self._bridge is None:
            raise FLBridgeError("Adapter not connected. Call connect() first.")
        return self._bridge.call(command, params)

