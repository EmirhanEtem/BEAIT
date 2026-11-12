"""Rhythm Specialist Role (Section 5.2 & Phase 6).

Responsible for drum pattern generation, step-sequencer step placement,
meter validation, and mapping drum tracks to FL Studio Channel Rack indices.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..music_engine import (
    DrumPattern,
    GenrePresetRegistry,
    ValidationResult,
    generate_drum_pattern,
    validate_drum_channel,
)
from ..music_engine.generator import steps_to_string
from ..schemas.actions import ActionDefinition, ActionRiskLevel, ActionType


DEFAULT_FL_DRUM_CHANNEL_MAP: Dict[str, int] = {
    "808 Kick": 0,
    "808 Clap": 1,
    "808 HiHat": 2,
    "808 Snare": 3,
}


@dataclass
class RhythmBundle:
    """Complete drum pattern and validated step-sequencer actions."""
    genre_key: str
    style: str
    tempo_bpm: float
    steps: int
    drum_pattern: DrumPattern
    validations: Dict[str, ValidationResult] = field(default_factory=dict)
    planned_actions: List[ActionDefinition] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return all(v.is_valid for v in self.validations.values())


class RhythmAgent:
    """Specialist logical module for drum programming and step-grid mapping."""

    def __init__(self, preset_registry: Optional[GenrePresetRegistry] = None):
        self.presets = preset_registry or GenrePresetRegistry()

    def build_rhythm(
        self,
        *,
        task_id: str = "task_rhythm",
        genre: str = "melodic_techno",
        style: Optional[str] = None,
        tempo_bpm: Optional[float] = None,
        steps: int = 16,
        channel_map: Optional[Dict[str, int]] = None,
        energy_variant: str = "full",
    ) -> RhythmBundle:
        """Generate a drum pattern, validate all channels, and emit FL step-grid actions."""
        preset = self.presets.get(genre)
        eff_style = style or (preset.drum_style if preset else "house")
        eff_tempo = tempo_bpm or (preset.default_bpm if preset else 124.0)
        ch_map = channel_map or dict(DEFAULT_FL_DRUM_CHANNEL_MAP)

        pattern = generate_drum_pattern(style=eff_style, length=steps, tempo=eff_tempo)

        # Energy variant filtering (e.g., intro = sparse kick/hihat only, breakdown = percussion only)
        if energy_variant == "intro":
            for ch in pattern.channels:
                if "Clap" in ch.channel_name or "Snare" in ch.channel_name:
                    ch.steps = []
                    ch.pattern_string = steps_to_string([], steps)
        elif energy_variant == "breakdown":
            for ch in pattern.channels:
                if "Kick" in ch.channel_name:
                    ch.steps = []
                    ch.pattern_string = steps_to_string([], steps)

        validations: Dict[str, ValidationResult] = {}
        actions: List[ActionDefinition] = []

        for ch in pattern.channels:
            val = validate_drum_channel(ch)
            validations[ch.channel_name] = val
            ch_idx = ch_map.get(ch.channel_name)
            if ch_idx is not None:
                actions.append(
                    ActionDefinition(
                        task_id=task_id,
                        action_type=ActionType.SET_STEP_GRID,
                        target=f"channel:{ch_idx}:{ch.channel_name}",
                        description=f"Set {ch.channel_name} step grid ({len(ch.steps)} active steps)",
                        parameters={
                            "channel": ch_idx,
                            "channel_name": ch.channel_name,
                            "steps": list(ch.steps),
                            "pattern": ch.pattern_string,
                            "length": steps,
                        },
                        execution_route="FL_MCP",
                        risk_level=ActionRiskLevel.MEDIUM,
                        requires_approval=False,
                    )
                )

        return RhythmBundle(
            genre_key=genre,
            style=eff_style,
            tempo_bpm=eff_tempo,
            steps=steps,
            drum_pattern=pattern,
            validations=validations,
            planned_actions=actions,
        )
