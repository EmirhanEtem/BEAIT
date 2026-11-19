"""Capability registry for DAW integrations and automation backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Set
from ..schemas.actions import ActionType


@dataclass
class RouteCapabilities:
    route_name: str
    supported_actions: Set[ActionType] = field(default_factory=set)
    read_only_actions: Set[ActionType] = field(default_factory=set)
    write_actions: Set[ActionType] = field(default_factory=set)
    is_active: bool = True

    def can_handle(self, action_type: ActionType) -> bool:
        return self.is_active and action_type in self.supported_actions


class CapabilityRegistry:
    """Maintains known capabilities of each execution route."""

    def __init__(self):
        self._routes: Dict[str, RouteCapabilities] = {}
        self._initialize_defaults()

    def _initialize_defaults(self):
        # 1. FL Studio MCP Integration
        fl_mcp_supported = {
            ActionType.READ_TEMPO,
            ActionType.READ_PLAY_STATE,
            ActionType.READ_PROJECT_STATE,
            ActionType.READ_CHANNELS,
            ActionType.READ_MIXER_TRACKS,
            ActionType.READ_PATTERNS,
            ActionType.READ_STEP_GRID,
            ActionType.SET_TEMPO,
            ActionType.SET_PLAY_STATE,
            ActionType.CREATE_MIDI_PATTERN,
            ActionType.CREATE_DRUM_PATTERN,
            ActionType.SET_STEP_GRID,
            ActionType.CREATE_PATTERN,
            ActionType.CLONE_PATTERN,
            ActionType.ADD_ARRANGEMENT_MARKER,
            ActionType.SET_CHANNEL_VOLUME,
            ActionType.SET_CHANNEL_PAN,
            ActionType.SET_MIXER_VOLUME,
            ActionType.SET_MIXER_PAN,
            ActionType.SET_MIXER_MUTE,
            ActionType.SET_MIXER_SOLO,
            ActionType.SET_PLUGIN_PARAM,
            ActionType.SET_MIXER_ROUTING,
            ActionType.SET_MIXER_TRACK_META,
            ActionType.AUTO_MIX_MASTER,
        }
        fl_mcp_reads = {
            ActionType.READ_TEMPO,
            ActionType.READ_PLAY_STATE,
            ActionType.READ_PROJECT_STATE,
            ActionType.READ_CHANNELS,
            ActionType.READ_MIXER_TRACKS,
            ActionType.READ_PATTERNS,
            ActionType.READ_STEP_GRID,
        }
        self.register_route(
            RouteCapabilities(
                route_name="FL_MCP",
                supported_actions=fl_mcp_supported,
                read_only_actions=fl_mcp_reads,
                write_actions=fl_mcp_supported - fl_mcp_reads,
                is_active=True,
            )
        )

        # 2. Windows GUI Automation (HCU)
        hcu_supported = {
            ActionType.OPEN_PLUGIN_WINDOW,
            ActionType.LOAD_PLUGIN_PRESET,
            ActionType.LOAD_MIXER_EFFECT,
            ActionType.SET_MIXER_ROUTING,
            ActionType.CAPTURE_SCREENSHOT,
            ActionType.EXPORT_AUDIO,
            # Fallback capabilities for when MCP is unavailable:
            ActionType.SET_TEMPO,
            ActionType.CREATE_DRUM_PATTERN,
        }
        self.register_route(
            RouteCapabilities(
                route_name="GUI_AUTOMATION",
                supported_actions=hcu_supported,
                read_only_actions={ActionType.CAPTURE_SCREENSHOT},
                write_actions=hcu_supported - {ActionType.CAPTURE_SCREENSHOT},
                is_active=True,
            )
        )

        # 3. Local Service (Filesystem & Python audio engine)
        local_supported = {
            ActionType.SCAN_SAMPLE_DIRECTORY,
            ActionType.ANALYZE_AUDIO_FILE,
            ActionType.CREATE_PROJECT_CHECKPOINT,
            ActionType.RESTORE_PROJECT_CHECKPOINT,
        }
        self.register_route(
            RouteCapabilities(
                route_name="LOCAL_SERVICE",
                supported_actions=local_supported,
                read_only_actions={ActionType.SCAN_SAMPLE_DIRECTORY, ActionType.ANALYZE_AUDIO_FILE},
                write_actions={ActionType.CREATE_PROJECT_CHECKPOINT, ActionType.RESTORE_PROJECT_CHECKPOINT},
                is_active=True,
            )
        )

        # 4. Mock Route (Always supports everything for deterministic tests)
        self.register_route(
            RouteCapabilities(
                route_name="MOCK",
                supported_actions=set(ActionType),
                read_only_actions=set(),
                write_actions=set(ActionType),
                is_active=True,
            )
        )

    def register_route(self, caps: RouteCapabilities):
        self._routes[caps.route_name] = caps

    def get_route(self, route_name: str) -> RouteCapabilities | None:
        return self._routes.get(route_name)

    def set_route_active(self, route_name: str, is_active: bool):
        if route_name in self._routes:
            self._routes[route_name].is_active = is_active

    def find_capable_routes(self, action_type: ActionType) -> List[str]:
        """Return list of active routes capable of handling the action."""
        capable = []
        for name, caps in self._routes.items():
            if caps.can_handle(action_type):
                capable.append(name)
        return capable

    async def discover_fl_capabilities(self, adapter) -> RouteCapabilities:
        """Probe the live FL Studio connection and dynamically update capabilities."""
        fl_route = self._routes.get("FL_MCP")
        if not fl_route:
            fl_route = RouteCapabilities(route_name="FL_MCP")
            self.register_route(fl_route)

        try:
            status = await adapter.async_check_health()
            if not status.connected or not status.fl_studio_alive:
                fl_route.is_active = False
                return fl_route

            fl_route.is_active = True
            # Verified operational set
            fl_route.supported_actions = {
                ActionType.READ_TEMPO,
                ActionType.READ_PLAY_STATE,
                ActionType.READ_PROJECT_STATE,
                ActionType.READ_CHANNELS,
                ActionType.READ_MIXER_TRACKS,
                ActionType.READ_PATTERNS,
                ActionType.READ_STEP_GRID,
                ActionType.SET_TEMPO,
                ActionType.SET_PLAY_STATE,
                ActionType.SET_STEP_GRID,
                ActionType.CREATE_DRUM_PATTERN,
                ActionType.CREATE_PATTERN,
                ActionType.CLONE_PATTERN,
                ActionType.ADD_ARRANGEMENT_MARKER,
                ActionType.SET_MIXER_VOLUME,
                ActionType.SET_MIXER_PAN,
                ActionType.SET_MIXER_MUTE,
                ActionType.SET_MIXER_SOLO,
                ActionType.LOAD_PLUGIN_PRESET,
                ActionType.LOAD_MIXER_EFFECT,
                ActionType.SET_PLUGIN_PARAM,
                ActionType.SET_MIXER_ROUTING,
                ActionType.SET_MIXER_TRACK_META,
                ActionType.AUTO_MIX_MASTER,
            }
            fl_route.read_only_actions = {
                ActionType.READ_TEMPO,
                ActionType.READ_PLAY_STATE,
                ActionType.READ_PROJECT_STATE,
                ActionType.READ_CHANNELS,
                ActionType.READ_MIXER_TRACKS,
                ActionType.READ_PATTERNS,
                ActionType.READ_STEP_GRID,
            }
            fl_route.write_actions = fl_route.supported_actions - fl_route.read_only_actions
        except Exception:
            fl_route.is_active = False

        return fl_route


