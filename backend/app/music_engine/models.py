"""Data models for the music and MIDI generation engine.

Provides type-safe representations of MIDI notes, melodic/harmonic patterns,
drum step patterns, and chord progressions.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional, Tuple
from pydantic import BaseModel, Field, model_validator


class ScaleType(str, Enum):
    MAJOR = "major"
    NATURAL_MINOR = "natural_minor"
    HARMONIC_MINOR = "harmonic_minor"
    MELODIC_MINOR = "melodic_minor"
    DORIAN = "dorian"
    PHRYGIAN = "phrygian"
    LYDIAN = "lydian"
    MIXOLYDIAN = "mixolydian"
    MAJOR_PENTATONIC = "major_pentatonic"
    MINOR_PENTATONIC = "minor_pentatonic"
    BLUES = "blues"


class ChordQuality(str, Enum):
    MAJOR = "major"
    MINOR = "minor"
    DIMINISHED = "diminished"
    AUGMENTED = "augmented"
    MAJOR_7TH = "major_7th"
    MINOR_7TH = "minor_7th"
    DOMINANT_7TH = "dominant_7th"
    DIMINISHED_7TH = "diminished_7th"
    HALF_DIMINISHED = "half_diminished"
    SUSPENDED_2 = "sus2"
    SUSPENDED_4 = "sus4"
    ADD_9 = "add9"


class MidiNote(BaseModel):
    """Represents a single MIDI note event.

    Pitches are standard MIDI note numbers (0-127, where 60 = Middle C / C4 in MIDI,
    displayed as C5 in FL Studio default naming).
    Timing and length are expressed in bars (e.g. 0.25 = 1 beat in 4/4 time).
    """

    pitch: int = Field(ge=0, le=127, description="MIDI note number (0..127, 60 = C4/C5)")
    time_bars: float = Field(ge=0.0, description="Start time in bars from start of pattern")
    length_bars: float = Field(gt=0.0, description="Duration in bars (must be > 0)")
    velocity: float = Field(default=0.787, ge=0.0, le=1.0, description="Normalized velocity 0.0..1.0")
    channel: int = Field(default=0, ge=0, le=15, description="MIDI channel (0..15)")
    pan: float = Field(default=0.0, ge=-1.0, le=1.0, description="Pan position (-1.0 to 1.0)")

    @model_validator(mode="after")
    def validate_finite_floats(self) -> MidiNote:
        import math
        for attr in ("time_bars", "length_bars", "velocity", "pan"):
            val = getattr(self, attr)
            if not math.isfinite(val):
                raise ValueError(f"Field {attr} must be a finite number, got {val}")
        return self


class MidiPattern(BaseModel):
    """Collection of notes forming a musical phrase, melody, chord progression, or bassline."""

    name: str = Field(default="Pattern", max_length=128)
    time_signature: Tuple[int, int] = Field(default=(4, 4), description="(numerator, denominator)")
    bars: int = Field(default=4, ge=1, le=128, description="Length of pattern in bars")
    tempo_bpm: float = Field(default=120.0, ge=20.0, le=999.0)
    key_root: Optional[str] = Field(default=None, description="Root note (e.g. 'C', 'F#', 'Bb')")
    scale: Optional[ScaleType] = Field(default=None)
    notes: List[MidiNote] = Field(default_factory=list)


class DrumChannelPattern(BaseModel):
    """Step-sequencer pattern for a single channel (e.g., Kick, Snare, Hi-Hat)."""

    channel_name: str = Field(description="Channel label, e.g. '808 Kick'")
    channel_index: Optional[int] = Field(default=None, ge=0, description="FL Studio channel index if known")
    length: int = Field(default=16, ge=1, le=256, description="Total steps (16 = 1 bar of 16th notes)")
    steps: List[int] = Field(default_factory=list, description="List of active step indices (0-based)")
    pattern_string: Optional[str] = Field(default=None, description="e.g. 'x...x...x...x...'")


class DrumPattern(BaseModel):
    """Full drum kit pattern across multiple drum instruments."""

    name: str = Field(default="Drum Pattern", max_length=128)
    length: int = Field(default=16, ge=1, le=256)
    tempo_bpm: float = Field(default=130.0, ge=20.0, le=999.0)
    channels: List[DrumChannelPattern] = Field(default_factory=list)
