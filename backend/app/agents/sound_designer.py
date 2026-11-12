"""Sound Designer Specialist Role (Section 5.2 & Phase 6).

Responsible for instrument selection, layering recommendations, and
initial mixer level/pan balancing with verifiable FL Studio actions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..music_engine import GenrePresetRegistry
from ..schemas.actions import ActionDefinition, ActionRiskLevel, ActionType


@dataclass
class LayeringRecommendation:
    """Instrument layering recommendation for a role in the mix."""
    role: str
    primary_timbre: str
    layer_timbre: str
    high_pass_hz: int
    stereo_width_pct: int
    rationale: str


@dataclass
class MixerRecommendation:
    """Target level and pan setting for a mixer track."""
    track_index: int
    track_name: str
    volume: float  # 0.0 .. 1.0 (0.8 = unity in FL Studio)
    pan: float     # -1.0 .. 1.0
    eq_note: str


@dataclass
class SoundDesignPlan:
    """Structured sound design, layering, and initial mix balance plan."""
    genre_key: str
    layers: List[LayeringRecommendation] = field(default_factory=list)
    mixer_targets: List[MixerRecommendation] = field(default_factory=list)
    planned_actions: List[ActionDefinition] = field(default_factory=list)
    disclaimer: str = (
        "Layering and mixer level targets are structured starting points; "
        "final tonal balance depends on specific sample/plugin selection."
    )


class SoundDesignerAgent:
    """Specialist logical module for timbre selection, layering, and initial mix balance."""

    def __init__(self, preset_registry: Optional[GenrePresetRegistry] = None):
        self.presets = preset_registry or GenrePresetRegistry()

    def create_sound_plan(
        self,
        *,
        task_id: str = "task_sound_design",
        genre: str = "melodic_techno",
    ) -> SoundDesignPlan:
        """Build layering recommendations and initial mixer actions for the genre."""
        preset = self.presets.get(genre)
        g_key = preset.key if preset else genre.lower()

        if "trap" in g_key:
            layers = [
                LayeringRecommendation(
                    role="Low End",
                    primary_timbre="Sustained 808 Sub Bass (Mono)",
                    layer_timbre="Short Punchy Kick (Transient top layer)",
                    high_pass_hz=30,
                    stereo_width_pct=0,
                    rationale="Keep sub frequencies centered and sidechain kick transient above 60 Hz.",
                ),
                LayeringRecommendation(
                    role="Harmonic Bed",
                    primary_timbre="Dark Detuned Bell / Pluck",
                    layer_timbre="Filtered Warm Pad (-12 dB/oct LP at 1.8 kHz)",
                    high_pass_hz=180,
                    stereo_width_pct=65,
                    rationale="Leave 40-160 Hz clean for the 808 while providing stereo atmosphere.",
                ),
            ]
            mixer_targets = [
                MixerRecommendation(1, "Kick", volume=0.82, pan=0.0, eq_note="Boost 55 Hz, notch 250 Hz"),
                MixerRecommendation(2, "Clap / Snare", volume=0.76, pan=0.0, eq_note="High-pass 150 Hz, crisp 3.5 kHz"),
                MixerRecommendation(3, "HiHat", volume=0.64, pan=-0.12, eq_note="High-pass 450 Hz"),
                MixerRecommendation(4, "808 Bass", volume=0.80, pan=0.0, eq_note="Mono below 120 Hz, light saturation"),
            ]
        else:
            layers = [
                LayeringRecommendation(
                    role="Bass Foundation",
                    primary_timbre="Mono Saw/Sub Rolling Bass",
                    layer_timbre="Stereo Mid-Bass Pluck (chorused > 200 Hz)",
                    high_pass_hz=35,
                    stereo_width_pct=25,
                    rationale="Tight mono sub anchor combined with wide mid-range harmonic movement.",
                ),
                LayeringRecommendation(
                    role="Lead & Chords",
                    primary_timbre="Analog Poly Synth Pad",
                    layer_timbre="Arpeggiated Pluck Lead (delay synced 1/8D)",
                    high_pass_hz=160,
                    stereo_width_pct=75,
                    rationale="High-pass pads above 160 Hz to prevent low-mid mud against the bassline.",
                ),
            ]
            mixer_targets = [
                MixerRecommendation(1, "Kick", volume=0.80, pan=0.0, eq_note="Tight 50 Hz fundamental, clean 200 Hz"),
                MixerRecommendation(2, "Clap", volume=0.74, pan=0.04, eq_note="High-pass 180 Hz, airy reverb tail"),
                MixerRecommendation(3, "HiHat", volume=0.66, pan=-0.10, eq_note="High-pass 500 Hz"),
                MixerRecommendation(4, "Bass & Synths", volume=0.75, pan=0.0, eq_note="Sidechain ducking to Kick"),
            ]

        actions: List[ActionDefinition] = []
        for m in mixer_targets:
            actions.append(
                ActionDefinition(
                    task_id=task_id,
                    action_type=ActionType.SET_MIXER_VOLUME,
                    target=f"mixer:{m.track_index}:{m.track_name}",
                    description=f"Set Mixer Track {m.track_index} ({m.track_name}) volume to {m.volume:.2f}",
                    parameters={"track_index": m.track_index, "volume": m.volume},
                    execution_route="FL_MCP",
                    risk_level=ActionRiskLevel.LOW,
                )
            )
            if abs(m.pan) > 1e-4:
                actions.append(
                    ActionDefinition(
                        task_id=task_id,
                        action_type=ActionType.SET_MIXER_PAN,
                        target=f"mixer:{m.track_index}:{m.track_name}",
                        description=f"Set Mixer Track {m.track_index} ({m.track_name}) pan to {m.pan:+.2f}",
                        parameters={"track_index": m.track_index, "pan": m.pan},
                        execution_route="FL_MCP",
                        risk_level=ActionRiskLevel.LOW,
                    )
                )

        return SoundDesignPlan(
            genre_key=g_key,
            layers=layers,
            mixer_targets=mixer_targets,
            planned_actions=actions,
        )
