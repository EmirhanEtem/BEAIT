"""Editable Genre and Mood Preset Loader.

Loads musical starting-point configurations from JSON rather than hard-coded
universal rules. Explicitly surfaces stylistic disclaimers.
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

_DEFAULT_PRESETS_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "configs", "genre-presets.json")
)


class GenrePreset(BaseModel):
    key: str
    display_name: str
    mood: str
    default_bpm: float
    bpm_range: Tuple[float, float] = (80.0, 160.0)
    default_root: str = "C"
    default_scale: str = "natural_minor"
    chord_progression: List[str] = Field(default_factory=lambda: ["i", "VI", "III", "VII"])
    drum_style: str = "four_on_the_floor"
    bass_rhythm: str = "pumping"
    melody_density: float = 0.5
    velocity_variation: float = 0.05
    swing_amount: float = 0.0
    section_template: List[Dict[str, int | str]] = Field(
        default_factory=lambda: [
            {"name": "Intro", "bars": 8},
            {"name": "Build", "bars": 8},
            {"name": "Drop", "bars": 16},
            {"name": "Breakdown", "bars": 8},
            {"name": "Outro", "bars": 8},
        ]
    )
    stylistic_disclaimer: str = (
        "Genre and mood presets are editable starting-point heuristics, not universal rules "
        "or guarantees of stylistic perfection."
    )


class GenrePresetRegistry:
    """Loads and manages editable genre/mood presets."""

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or _DEFAULT_PRESETS_PATH
        self.disclaimer = (
            "Genre and mood presets are editable starting-point heuristics, not universal rules "
            "or guarantees of stylistic perfection."
        )
        self._presets: Dict[str, GenrePreset] = {}
        self.reload()

    def reload(self) -> None:
        if not os.path.isfile(self.config_path):
            return
        with open(self.config_path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        self.disclaimer = raw.get("stylistic_disclaimer", self.disclaimer)
        presets_map = raw.get("presets", {})
        self._presets.clear()
        for key, data in presets_map.items():
            self._presets[key] = GenrePreset(
                key=key,
                stylistic_disclaimer=self.disclaimer,
                **data,
            )

    def get(self, key: str) -> Optional[GenrePreset]:
        clean = key.strip().lower().replace("-", "_").replace(" ", "_")
        if clean in self._presets:
            return self._presets[clean]
        # Partial match fallback
        for k, preset in self._presets.items():
            if clean in k or k in clean:
                return preset
        return None

    def list_presets(self) -> List[GenrePreset]:
        return list(self._presets.values())

    def register_custom_preset(self, preset: GenrePreset) -> None:
        self._presets[preset.key] = preset
