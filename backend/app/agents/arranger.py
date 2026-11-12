"""Arranger Specialist Role (Section 5.2 & Phase 6).

Responsible for song section planning (Intro, Build, Drop, Breakdown, Outro),
bar math, energy curves, pattern naming, and Playlist marker actions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..music_engine import GenrePresetRegistry
from ..schemas.actions import ActionDefinition, ActionRiskLevel, ActionType


DEFAULT_SECTION_ENERGY: Dict[str, float] = {
    "Intro": 0.30,
    "Build": 0.65,
    "Drop": 1.00,
    "Breakdown": 0.40,
    "Outro": 0.25,
}

DEFAULT_SECTION_ELEMENTS: Dict[str, List[str]] = {
    "Intro": ["Kick", "HiHat", "Atmosphere Pad"],
    "Build": ["Kick", "HiHat", "Snare Roll", "Bass", "Chords"],
    "Drop": ["Kick", "Clap", "HiHat", "Snare", "Bass", "Chords", "Lead Melody"],
    "Breakdown": ["Chords", "Lead Melody", "Subtle HiHat"],
    "Outro": ["Kick", "HiHat", "Fade Pad"],
}


@dataclass
class ArrangementSection:
    """Single structural section in the song arrangement."""
    index: int
    name: str
    start_bar: int   # 1-based inclusive bar index in FL Studio Playlist
    bars: int
    end_bar: int     # 1-based exclusive end bar (start_bar + bars)
    energy_level: float
    pattern_name: str
    active_elements: List[str] = field(default_factory=list)


@dataclass
class ArrangementPlan:
    """Complete multi-section song arrangement and corresponding FL Studio actions."""
    genre_key: str
    total_bars: int
    sections: List[ArrangementSection] = field(default_factory=list)
    planned_actions: List[ActionDefinition] = field(default_factory=list)

    @property
    def is_contiguous(self) -> bool:
        """Verify that sections start at bar 1 and have no gaps or overlaps."""
        if not self.sections:
            return False
        expected_bar = 1
        for sec in self.sections:
            if sec.start_bar != expected_bar or sec.bars <= 0:
                return False
            if sec.end_bar != sec.start_bar + sec.bars:
                return False
            expected_bar = sec.end_bar
        return (expected_bar - 1) == self.total_bars


class ArrangerAgent:
    """Specialist logical module for song structure and FL Studio Playlist organization."""

    def __init__(self, preset_registry: Optional[GenrePresetRegistry] = None):
        self.presets = preset_registry or GenrePresetRegistry()

    def create_arrangement(
        self,
        *,
        task_id: str = "task_arrangement",
        genre: str = "melodic_techno",
        custom_sections: Optional[List[Dict[str, int | str]]] = None,
    ) -> ArrangementPlan:
        """Build a contiguous multi-section arrangement plan (Intro/Build/Drop/Breakdown/Outro)."""
        preset = self.presets.get(genre)
        raw_sections = custom_sections or (
            preset.section_template
            if preset and preset.section_template
            else [
                {"name": "Intro", "bars": 8},
                {"name": "Build", "bars": 8},
                {"name": "Drop", "bars": 16},
                {"name": "Breakdown", "bars": 8},
                {"name": "Outro", "bars": 8},
            ]
        )

        sections: List[ArrangementSection] = []
        actions: List[ActionDefinition] = []
        current_bar = 1

        for idx, item in enumerate(raw_sections, start=1):
            name = str(item.get("name", f"Section_{idx}"))
            bars = max(1, int(item.get("bars", 8)))
            end_bar = current_bar + bars
            energy = DEFAULT_SECTION_ENERGY.get(name, 0.50)
            elements = list(DEFAULT_SECTION_ELEMENTS.get(name, ["Kick", "Bass", "Chords"]))
            pattern_name = f"{idx:02d}_{name}"

            sec = ArrangementSection(
                index=idx,
                name=name,
                start_bar=current_bar,
                bars=bars,
                end_bar=end_bar,
                energy_level=energy,
                pattern_name=pattern_name,
                active_elements=elements,
            )
            sections.append(sec)

            # Action 1: Create named pattern for this section
            actions.append(
                ActionDefinition(
                    task_id=task_id,
                    action_type=ActionType.CREATE_PATTERN,
                    target=f"pattern:{pattern_name}",
                    description=f"Create pattern '{pattern_name}' for {name} ({bars} bars)",
                    parameters={"name": pattern_name},
                    execution_route="FL_MCP",
                    risk_level=ActionRiskLevel.LOW,
                )
            )

            # Action 2: Add Playlist time marker at the start bar of this section
            actions.append(
                ActionDefinition(
                    task_id=task_id,
                    action_type=ActionType.ADD_ARRANGEMENT_MARKER,
                    target=f"playlist:bar:{current_bar}",
                    description=f"Add Playlist time marker '{name}' at bar {current_bar}",
                    parameters={"bar": current_bar, "name": name},
                    execution_route="FL_MCP",
                    risk_level=ActionRiskLevel.LOW,
                )
            )

            current_bar = end_bar

        total_bars = current_bar - 1
        return ArrangementPlan(
            genre_key=preset.key if preset else genre,
            total_bars=total_bars,
            sections=sections,
            planned_actions=actions,
        )

