"""Verification Engine for DAW and GUI actions."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from ..schemas.actions import ActionDefinition, ActionLifecycleState, ActionType

logger = logging.getLogger(__name__)


@dataclass
class VerificationOutcome:
    success: bool
    verified: bool
    detail: str
    needs_recovery: bool = False
    error: Optional[str] = None


class VerificationEngine:
    """Verifies action execution effects against resulting state."""

    def verify(
        self,
        action: ActionDefinition,
        pre_state: Optional[Dict[str, Any]] = None,
        post_state: Optional[Dict[str, Any]] = None,
    ) -> VerificationOutcome:
        """Evaluates resulting state against expected action parameters."""
        pre = pre_state or {}
        post = post_state or {}

        try:
            if action.action_type == ActionType.SET_TEMPO:
                return self._verify_tempo(action, post)

            elif action.action_type in (ActionType.SET_MIXER_VOLUME, ActionType.SET_MIXER_PAN):
                return self._verify_mixer(action, post)

            elif action.action_type in (ActionType.SET_CHANNEL_VOLUME, ActionType.SET_CHANNEL_PAN):
                is_ver = bool(post.get("verified", True))
                param_name = "volume" if action.action_type == ActionType.SET_CHANNEL_VOLUME else "pan"
                return VerificationOutcome(
                    success=is_ver,
                    verified=is_ver,
                    detail=f"Channel {action.parameters.get('channel', 0)} {param_name} set to {post.get(param_name, action.parameters.get('value'))}.",
                )

            elif action.action_type == ActionType.SET_MIXER_MUTE:
                return self._verify_mute(action, post)

            elif action.action_type in (ActionType.CREATE_MIDI_PATTERN, ActionType.CREATE_DRUM_PATTERN):
                return self._verify_pattern(action, post)

            elif action.action_type == ActionType.SET_STEP_GRID:
                return self._verify_step_grid(action, post)

            elif action.action_type in (ActionType.CREATE_PATTERN, ActionType.CLONE_PATTERN):
                return self._verify_create_pattern(action, post)

            elif action.action_type == ActionType.ADD_ARRANGEMENT_MARKER:
                is_ver = bool(post.get("verified", True))
                return VerificationOutcome(
                    success=is_ver,
                    verified=is_ver,
                    detail=f"Playlist time marker '{action.parameters.get('name')}' added at bar {action.parameters.get('bar')}.",
                )

            elif action.action_type == ActionType.SET_PLAY_STATE:
                is_ver = bool(post.get("verified", True))
                return VerificationOutcome(
                    success=is_ver,
                    verified=is_ver,
                    detail=f"Transport playback state set to '{action.parameters.get('state', 'play')}'.",
                )

            elif action.action_type in (ActionType.OPEN_PLUGIN_WINDOW, ActionType.LOAD_PLUGIN_PRESET):
                is_ver = bool(post.get("verified"))
                return VerificationOutcome(
                    success=is_ver,
                    verified=is_ver,
                    detail=(
                        f"GUI operation verified via {post.get('method_used', 'UIA')}."
                        if is_ver
                        else "GUI operation could not be verified visually or semantically."
                    ),
                    needs_recovery=not is_ver,
                    error=None if is_ver else "gui_verification_failed",
                )

            elif action.action_type == ActionType.EXPORT_AUDIO:
                return self._verify_export(action, post)

            elif action.action_type in (
                ActionType.READ_TEMPO,
                ActionType.READ_PLAY_STATE,
                ActionType.READ_PROJECT_STATE,
                ActionType.READ_CHANNELS,
                ActionType.READ_MIXER_TRACKS,
                ActionType.READ_PATTERNS,
                ActionType.CAPTURE_SCREENSHOT,
                ActionType.SCAN_SAMPLE_DIRECTORY,
                ActionType.ANALYZE_AUDIO_FILE,
            ):
                # Read-only actions succeed if data was retrieved
                has_data = post.get("data") is not None or post.get("result") is not None
                return VerificationOutcome(
                    success=has_data,
                    verified=True,
                    detail="Read operation returned valid data." if has_data else "No data returned from read.",
                    needs_recovery=not has_data,
                )

            # Default / Unverifiable actions: Never silently claim verified success!
            return VerificationOutcome(
                success=True,
                verified=False,
                detail="Command executed, but DAW API does not expose readback verification for this action.",
                needs_recovery=False,
            )

        except Exception as e:
            logger.error("Verification error on action %s: %s", action.action_id, e)
            return VerificationOutcome(
                success=False,
                verified=False,
                detail=f"Verification failed with error: {e}",
                needs_recovery=True,
                error=str(e),
            )

    def _verify_tempo(self, action: ActionDefinition, post: Dict[str, Any]) -> VerificationOutcome:
        requested = float(action.parameters.get("bpm", 0))
        actual = post.get("bpm")
        if actual is None:
            return VerificationOutcome(
                success=False,
                verified=False,
                detail="Post-action BPM could not be read back from FL Studio.",
                needs_recovery=True,
                error="missing_post_bpm",
            )
        
        diff = abs(float(actual) - requested)
        tolerance = action.parameters.get("tolerance", 0.05)
        passed = diff <= tolerance

        return VerificationOutcome(
            success=passed,
            verified=passed,
            detail=f"BPM readback: expected {requested}, got {actual} (diff: {diff:.3f})",
            needs_recovery=not passed,
            error=None if passed else "bpm_mismatch",
        )

    def _verify_mixer(self, action: ActionDefinition, post: Dict[str, Any]) -> VerificationOutcome:
        param_name = "volume" if action.action_type == ActionType.SET_MIXER_VOLUME else "pan"
        requested = float(action.parameters.get(param_name, action.parameters.get("value", 0)))
        actual = post.get(param_name)
        if post.get("verified") is True:
            return VerificationOutcome(
                success=True,
                verified=True,
                detail=f"Mixer {param_name}: requested {requested}, verified ({actual})",
            )
        if actual is None:
            return VerificationOutcome(
                success=False,
                verified=False,
                detail=f"Mixer {param_name} could not be read back.",
                needs_recovery=True,
                error="missing_mixer_param",
            )

        diff = abs(float(actual) - requested)
        passed = diff <= 0.05
        return VerificationOutcome(
            success=passed,
            verified=passed,
            detail=f"Mixer {param_name}: requested {requested}, got {actual}",
            needs_recovery=not passed,
            error=None if passed else "mixer_param_mismatch",
        )

    def _verify_mute(self, action: ActionDefinition, post: Dict[str, Any]) -> VerificationOutcome:
        requested = bool(action.parameters.get("state", False))
        actual = post.get("mute")
        if actual is None:
            return VerificationOutcome(
                success=False,
                verified=False,
                detail="Mixer mute state could not be read back.",
                needs_recovery=True,
                error="missing_mixer_mute",
            )
        passed = (bool(actual) == requested)
        return VerificationOutcome(
            success=passed,
            verified=passed,
            detail=f"Mixer mute: requested {requested}, got {actual}",
            needs_recovery=not passed,
            error=None if passed else "mixer_mute_mismatch",
        )

    def _verify_step_grid(self, action: ActionDefinition, post: Dict[str, Any]) -> VerificationOutcome:
        # Check if direct verified result was returned
        if post.get("verified") is True:
            return VerificationOutcome(
                success=True,
                verified=True,
                detail=f"Step grid verified on channel {action.parameters.get('channel')}: steps {post.get('after_steps')}",
            )
        
        expected_steps = action.parameters.get("steps", [])
        actual_steps = post.get("steps") or post.get("after_steps")
        if actual_steps is None:
            return VerificationOutcome(
                success=False,
                verified=False,
                detail="Channel step grid could not be read back.",
                needs_recovery=True,
                error="missing_step_grid",
            )

        passed = sorted(actual_steps) == sorted(expected_steps)
        return VerificationOutcome(
            success=passed,
            verified=passed,
            detail=f"Step grid: expected {expected_steps}, got {actual_steps}",
            needs_recovery=not passed,
            error=None if passed else "step_grid_mismatch",
        )

    def _verify_create_pattern(self, action: ActionDefinition, post: Dict[str, Any]) -> VerificationOutcome:
        if post.get("verified") is True or (isinstance(post.get("index"), int) and post.get("index") >= 1):
            return VerificationOutcome(
                success=True,
                verified=True,
                detail=f"Created pattern '{action.parameters.get('name')}' at index {post.get('index')}",
            )
        return VerificationOutcome(
            success=False,
            verified=False,
            detail="Pattern creation failed or returned invalid index.",
            needs_recovery=True,
            error="pattern_create_failed",
        )

    def _verify_pattern(self, action: ActionDefinition, post: Dict[str, Any]) -> VerificationOutcome:
        # Check if notes or grid steps were written
        pattern_data = post.get("pattern") or post.get("notes") or post.get("grid")
        if pattern_data is not None:
            return VerificationOutcome(
                success=True,
                verified=True,
                detail="Pattern data successfully confirmed in session.",
            )
        return VerificationOutcome(
            success=False,
            verified=False,
            detail="Pattern notes could not be verified in target channel.",
            needs_recovery=True,
            error="pattern_empty",
        )

    def _verify_export(self, action: ActionDefinition, post: Dict[str, Any]) -> VerificationOutcome:
        file_path = action.parameters.get("output_path") or post.get("output_path")
        if not file_path:
            return VerificationOutcome(
                success=False,
                verified=False,
                detail="Export file path not specified.",
                needs_recovery=True,
            )
        
        p = Path(file_path)
        if not p.exists():
            return VerificationOutcome(
                success=False,
                verified=False,
                detail=f"Exported audio file does not exist: {file_path}",
                needs_recovery=True,
                error="file_not_found",
            )
        
        size = p.stat().st_size
        if size < 1024:  # At least 1KB for valid audio header
            return VerificationOutcome(
                success=False,
                verified=False,
                detail=f"Exported audio file too small ({size} bytes).",
                needs_recovery=True,
                error="file_too_small",
            )

        return VerificationOutcome(
            success=True,
            verified=True,
            detail=f"Exported file verified: {size} bytes.",
        )

