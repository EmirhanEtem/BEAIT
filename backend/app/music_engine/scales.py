"""Scale definitions, pitch math, and music-theory utilities."""

from __future__ import annotations

import re
from typing import Dict, List, Union
from .models import ScaleType

_NOTE_OFFSETS: Dict[str, int] = {
    "C": 0, "B#": 0,
    "C#": 1, "DB": 1,
    "D": 2,
    "D#": 3, "EB": 3,
    "E": 4, "FB": 4,
    "F": 5, "E#": 5,
    "F#": 6, "GB": 6,
    "G": 7,
    "G#": 8, "AB": 8,
    "A": 9,
    "A#": 10, "BB": 10,
    "B": 11, "CB": 11,
}

_SHARP_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_FLAT_NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]

SCALE_INTERVALS: Dict[ScaleType, List[int]] = {
    ScaleType.MAJOR: [0, 2, 4, 5, 7, 9, 11],
    ScaleType.NATURAL_MINOR: [0, 2, 3, 5, 7, 8, 10],
    ScaleType.HARMONIC_MINOR: [0, 2, 3, 5, 7, 8, 11],
    ScaleType.MELODIC_MINOR: [0, 2, 3, 5, 7, 9, 11],
    ScaleType.DORIAN: [0, 2, 3, 5, 7, 9, 10],
    ScaleType.PHRYGIAN: [0, 1, 3, 5, 7, 8, 10],
    ScaleType.LYDIAN: [0, 2, 4, 6, 7, 9, 11],
    ScaleType.MIXOLYDIAN: [0, 2, 4, 5, 7, 9, 10],
    ScaleType.MAJOR_PENTATONIC: [0, 2, 4, 7, 9],
    ScaleType.MINOR_PENTATONIC: [0, 3, 5, 7, 10],
    ScaleType.BLUES: [0, 3, 5, 6, 7, 10],
}


def note_to_midi(name: str) -> int:
    """Convert note name like 'C4', 'F#3', 'Bb5' to MIDI pitch number (0..127).

    By MIDI standard, C4 is 60 (Middle C).
    """
    clean = name.strip()
    match = re.match(r"^([A-Ga-g][#bB]?)(-?\d+)$", clean)
    if not match:
        # Fallback if no octave specified: default to octave 4
        match_no_oct = re.match(r"^([A-Ga-g][#bB]?)$", clean)
        if match_no_oct:
            note_part = match_no_oct.group(1).upper()
            octave = 4
        else:
            raise ValueError(f"Invalid note name: {name!r}")
    else:
        note_part = match.group(1).upper()
        octave = int(match.group(2))

    if note_part not in _NOTE_OFFSETS:
        raise ValueError(f"Unknown note name: {note_part!r}")

    semitone = _NOTE_OFFSETS[note_part]
    midi = (octave + 1) * 12 + semitone
    if not (0 <= midi <= 127):
        raise ValueError(f"Note {name!r} results in out-of-range MIDI pitch {midi}")
    return midi


def midi_to_note(pitch: int, use_sharps: bool = True) -> str:
    """Convert MIDI pitch number (0..127) to note name like 'C4', 'A#3'."""
    if not (0 <= pitch <= 127):
        raise ValueError(f"MIDI pitch must be between 0 and 127, got {pitch}")
    octave = (pitch // 12) - 1
    semitone = pitch % 12
    name_table = _SHARP_NAMES if use_sharps else _FLAT_NAMES
    return f"{name_table[semitone]}{octave}"


def get_scale_pitches(
    root: str,
    scale: Union[ScaleType, str],
    start_octave: int = 2,
    end_octave: int = 6,
) -> List[int]:
    """Return all valid MIDI pitches in the given key and scale across octaves."""
    if isinstance(scale, str):
        try:
            scale_enum = ScaleType(scale.lower())
        except ValueError:
            raise ValueError(f"Unknown scale type: {scale!r}")
    else:
        scale_enum = scale

    root_clean = root.strip().upper()
    # Strip octave if given
    m = re.match(r"^([A-Ga-g][#bB]?)", root_clean)
    if not m:
        raise ValueError(f"Invalid root note: {root!r}")
    root_note = m.group(1)
    if root_note not in _NOTE_OFFSETS:
        raise ValueError(f"Invalid root note: {root_note!r}")

    root_offset = _NOTE_OFFSETS[root_note]
    intervals = SCALE_INTERVALS[scale_enum]

    pitches: List[int] = []
    for octv in range(start_octave, end_octave + 1):
        oct_base = (octv + 1) * 12 + root_offset
        for interval in intervals:
            p = oct_base + interval
            if 0 <= p <= 127:
                pitches.append(p)

    return sorted(set(pitches))


def quantize_pitch_to_scale(pitch: int, allowed_pitches: List[int]) -> int:
    """Snap a MIDI pitch to the closest pitch in the allowed scale list."""
    if not allowed_pitches:
        return max(0, min(127, pitch))
    return min(allowed_pitches, key=lambda p: abs(p - pitch))

