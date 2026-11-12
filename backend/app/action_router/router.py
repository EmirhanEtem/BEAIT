"""Action Router: selects the most reliable execution route for an action."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional
from ..schemas.actions import ActionDefinition, ActionType
from .capabilities import CapabilityRegistry

logger = logging.getLogger(__name__)

# Routing table as specified in Section 5.3
PREFERRED_ROUTING_MAP: Dict[ActionType, List[str]] = {
    ActionType.READ_TEMPO: ["FL_MCP", "GUI_AUTOMATION"],
    ActionType.SET_TEMPO: ["FL_MCP", "GUI_AUTOMATION"],
    ActionType.READ_PLAY_STATE: ["FL_MCP", "GUI_AUTOMATION"],
    ActionType.SET_PLAY_STATE: ["FL_MCP", "GUI_AUTOMATION"],
    ActionType.READ_PROJECT_STATE: ["FL_MCP", "GUI_AUTOMATION"],
    ActionType.READ_CHANNELS: ["FL_MCP", "GUI_AUTOMATION"],
    ActionType.READ_MIXER_TRACKS: ["FL_MCP", "GUI_AUTOMATION"],
    ActionType.READ_PATTERNS: ["FL_MCP", "GUI_AUTOMATION"],
    ActionType.CREATE_MIDI_PATTERN: ["FL_MCP", "GUI_AUTOMATION"],
    ActionType.CREATE_DRUM_PATTERN: ["FL_MCP", "GUI_AUTOMATION"],
    ActionType.SET_CHANNEL_VOLUME: ["FL_MCP", "GUI_AUTOMATION"],
    ActionType.SET_CHANNEL_PAN: ["FL_MCP", "GUI_AUTOMATION"],
    ActionType.SET_MIXER_VOLUME: ["FL_MCP", "GUI_AUTOMATION"],
    ActionType.SET_MIXER_PAN: ["FL_MCP", "GUI_AUTOMATION"],
    ActionType.SET_MIXER_MUTE: ["FL_MCP", "GUI_AUTOMATION"],
    ActionType.SET_MIXER_SOLO: ["FL_MCP", "GUI_AUTOMATION"],
    ActionType.OPEN_PLUGIN_WINDOW: ["GUI_AUTOMATION"],
    ActionType.LOAD_PLUGIN_PRESET: ["GUI_AUTOMATION"],
    ActionType.CAPTURE_SCREENSHOT: ["GUI_AUTOMATION"],
    ActionType.SCAN_SAMPLE_DIRECTORY: ["LOCAL_SERVICE"],
    ActionType.ANALYZE_AUDIO_FILE: ["LOCAL_SERVICE"],
    ActionType.CREATE_PROJECT_CHECKPOINT: ["LOCAL_SERVICE"],
    ActionType.RESTORE_PROJECT_CHECKPOINT: ["LOCAL_SERVICE"],
    ActionType.EXPORT_AUDIO: ["GUI_AUTOMATION"],
}


class ActionRouter:
    """Routes an action to the best available and capable integration."""

    def __init__(self, registry: Optional[CapabilityRegistry] = None):
        self.registry = registry or CapabilityRegistry()

    def route_action(self, action: ActionDefinition, prefer_mock: bool = False) -> str:
        """Determines the execution route for the action.
        
        If prefer_mock is True, routes directly to MOCK.
        Otherwise evaluates the preferred routes in order, verifying capabilities.
        Raises ValueError if no capable route is available.
        """
        if prefer_mock:
            action.execution_route = "MOCK"
            return "MOCK"

        preferences = PREFERRED_ROUTING_MAP.get(action.action_type, ["FL_MCP", "GUI_AUTOMATION", "LOCAL_SERVICE"])
        capable_routes = self.registry.find_capable_routes(action.action_type)

        for preferred in preferences:
            if preferred in capable_routes:
                action.execution_route = preferred
                logger.debug("Routed %s (%s) to %s", action.action_id, action.action_type, preferred)
                return preferred

        if not capable_routes:
            raise ValueError(
                f"No integration route capable of handling action '{action.action_type.value}' is currently active."
            )

        # Fallback to any capable route
        chosen = capable_routes[0]
        action.execution_route = chosen
        logger.warning(
            "Action %s (%s) fell back to %s because preferred routes were inactive",
            action.action_id,
            action.action_type,
            chosen,
        )
        return chosen

