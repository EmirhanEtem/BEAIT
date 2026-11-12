"""Generators for rhythmic drum patterns, chords, basslines, and melodies."""

from __future__ import annotations

import random
from typing import Dict, List, Optional
from .models import (
    ChordQuality,
    DrumChannelPattern,
    DrumPattern,
    MidiNote,
    MidiPattern,
    ScaleType,
)
from .scales import get_scale_pitches, note_to_midi
from .chords import progression_to_notes


DRUM_STYLES: Dict[str, Dict[str, List[int]]] = {
    "four_on_the_floor": {
        "808 Kick": [0, 4, 8, 12],
        "808 Clap": [4, 12],
        "808 HiHat": [2, 6, 10, 14],  # Off-beat
        "808 Snare": [],
    },
    "house": {
        "808 Kick": [0, 4, 8, 12],
        "808 Clap": [4, 12],
        "808 HiHat": [2, 6, 10, 14],
        "808 Snare": [12],
    },
    "techno": {
        "808 Kick": [0, 4, 8, 12],
        "808 Clap": [4, 12],
        "808 HiHat": [0, 2, 4, 6, 8, 10, 12, 14],
        "808 Snare": [],
    },
    "trap": {
        "808 Kick": [0, 6, 10],
        "808 Clap": [4, 12],
        "808 HiHat": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
        "808 Snare": [12, 14],
    },
    "boom_bap": {
        "808 Kick": [0, 3, 8, 10],
        "808 Clap": [],
        "808 HiHat": [0, 2, 4, 6, 8, 10, 12, 14],
        "808 Snare": [4, 12],
    },
}


def steps_to_string(steps: List[int], length: int = 16) -> str:
    """Format step indices into a pattern string like 'x...x...x...x...'."""
    step_set = set(steps)
    return "".join("x" if i in step_set else "." for i in range(length))


def generate_drum_pattern(
    style: str = "four_on_the_floor",
    length: int = 16,
    tempo: float = 130.0,
) -> DrumPattern:
    """Generate a standard drum pattern with channels matching common FL Studio templates."""
    clean_style = style.lower().replace("-", "_").replace(" ", "_")
    templates = DRUM_STYLES.get(clean_style, DRUM_STYLES["four_on_the_floor"])

    channels: List[DrumChannelPattern] = []
    for ch_name, steps in templates.items():
        # Filter steps that fit within requested length
        valid_steps = [s for s in steps if s < length]
        p_str = steps_to_string(valid_steps, length)
        channels.append(
            DrumChannelPattern(
                channel_name=ch_name,
                length=length,
                steps=valid_steps,
                pattern_string=p_str,
            )
        )

    return DrumPattern(
        name=f"Drums - {style.title()}",
        length=length,
        tempo_bpm=tempo,
        channels=channels,
    )


def generate_chord_pattern(
    root: str = "C",
    scale: str = "natural_minor",
    progression: Optional[List[str]] = None,
    bars_per_chord: float = 1.0,
    octave: int = 4,
    tempo: float = 120.0,
) -> MidiPattern:
    """Generate harmonic chord progression pattern."""
    if progression is None:
        progression = ["i", "VI", "III", "VII"] if "minor" in scale else ["I", "V", "vi", "IV"]

    scale_enum = ScaleType(scale.lower()) if scale in [s.value for s in ScaleType] else ScaleType.NATURAL_MINOR
    notes = progression_to_notes(
        root=root,
        scale=scale_enum,
        numerals=progression,
        bars_per_chord=bars_per_chord,
        octave=octave,
    )

    total_bars = int(len(progression) * bars_per_chord)
    return MidiPattern(
        name=f"Chords - {root} {scale_enum.value} ({'-'.join(progression)})",
        time_signature=(4, 4),
        bars=max(1, total_bars),
        tempo_bpm=tempo,
        key_root=root,
        scale=scale_enum,
        notes=notes,
    )


def generate_bassline(
    root: str = "C",
    scale: str = "natural_minor",
    progression: Optional[List[str]] = None,
    bars_per_chord: float = 1.0,
    octave: int = 2,
    tempo: float = 120.0,
    rhythm: str = "pumping",
) -> MidiPattern:
    """Generate bassline following chord root notes."""
    if progression is None:
        progression = ["i", "VI", "III", "VII"]

    scale_enum = ScaleType(scale.lower()) if scale in [s.value for s in ScaleType] else ScaleType.NATURAL_MINOR
    root_base = note_to_midi(f"{root}{octave}")

    # Diatonic root offsets
    from .chords import MAJOR_DIATONIC, MINOR_DIATONIC
    is_minor = "minor" in scale_enum.value
    dmap = MINOR_DIATONIC if is_minor else MAJOR_DIATONIC

    notes: List[MidiNote] = []
    current_bar = 0.0

    for num in progression:
        offset, _ = dmap.get(num.strip(), (0, None))
        pitch = root_base + offset

        if rhythm == "pumping":
            # 8th note driving bass: 8 notes per bar
            subdivisions = int(bars_per_chord * 8)
            step_len = bars_per_chord / subdivisions
            for s in range(subdivisions):
                notes.append(
                    MidiNote(
                        pitch=pitch,
                        time_bars=round(current_bar + s * step_len, 4),
                        length_bars=round(step_len * 0.85, 4),
                        velocity=0.85 if s % 2 == 0 else 0.70,
                    )
                )
        else:
            # Sustained whole notes
            notes.append(
                MidiNote(
                    pitch=pitch,
                    time_bars=round(current_bar, 4),
                    length_bars=round(bars_per_chord * 0.95, 4),
                    velocity=0.85,
                )
            )

        current_bar += bars_per_chord

    return MidiPattern(
        name=f"Bassline - {root} {scale_enum.value}",
        bars=max(1, int(len(progression) * bars_per_chord)),
        tempo_bpm=tempo,
        key_root=root,
        scale=scale_enum,
        notes=notes,
    )
