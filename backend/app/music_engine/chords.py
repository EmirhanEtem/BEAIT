"""Chord construction and harmonic progression utilities."""

from __future__ import annotations

from typing import Dict, List, Union
from .models import ChordQuality, MidiNote, ScaleType
from .scales import note_to_midi

CHORD_FORMULAS: Dict[ChordQuality, List[int]] = {
    ChordQuality.MAJOR: [0, 4, 7],
    ChordQuality.MINOR: [0, 3, 7],
    ChordQuality.DIMINISHED: [0, 3, 6],
    ChordQuality.AUGMENTED: [0, 4, 8],
    ChordQuality.MAJOR_7TH: [0, 4, 7, 11],
    ChordQuality.MINOR_7TH: [0, 3, 7, 10],
    ChordQuality.DOMINANT_7TH: [0, 4, 7, 10],
    ChordQuality.DIMINISHED_7TH: [0, 3, 6, 9],
    ChordQuality.HALF_DIMINISHED: [0, 3, 6, 10],
    ChordQuality.SUSPENDED_2: [0, 2, 7],
    ChordQuality.SUSPENDED_4: [0, 5, 7],
    ChordQuality.ADD_9: [0, 4, 7, 14],
}

# Diatonic chord mapping in Major scale
MAJOR_DIATONIC: Dict[str, tuple[int, ChordQuality]] = {
    "I": (0, ChordQuality.MAJOR),
    "ii": (2, ChordQuality.MINOR),
    "iii": (4, ChordQuality.MINOR),
    "IV": (5, ChordQuality.MAJOR),
    "V": (7, ChordQuality.MAJOR),
    "vi": (9, ChordQuality.MINOR),
    "vii°": (11, ChordQuality.DIMINISHED),
    "vii": (11, ChordQuality.DIMINISHED),
}

# Diatonic chord mapping in Natural Minor scale
MINOR_DIATONIC: Dict[str, tuple[int, ChordQuality]] = {
    "i": (0, ChordQuality.MINOR),
    "ii°": (2, ChordQuality.DIMINISHED),
    "ii": (2, ChordQuality.DIMINISHED),
    "III": (3, ChordQuality.MAJOR),
    "iv": (5, ChordQuality.MINOR),
    "v": (7, ChordQuality.MINOR),
    "V": (7, ChordQuality.MAJOR),  # Harmonic minor dominant
    "VI": (8, ChordQuality.MAJOR),
    "VII": (10, ChordQuality.MAJOR),
    "vii°": (11, ChordQuality.DIMINISHED),
}


def build_chord(root_midi: int, quality: Union[ChordQuality, str], inversion: int = 0) -> List[int]:
    """Build a list of MIDI note pitches for a chord with optional inversion."""
    if isinstance(quality, str):
        try:
            q_enum = ChordQuality(quality.lower())
        except ValueError:
            raise ValueError(f"Unknown chord quality: {quality!r}")
    else:
        q_enum = quality

    intervals = CHORD_FORMULAS[q_enum]
    pitches = [root_midi + interval for interval in intervals]

    # Inversions: shift the lowest note up an octave
    inv = inversion % len(pitches)
    for i in range(inv):
        pitches[i] += 12

    pitches = sorted(p for p in pitches if 0 <= p <= 127)
    return pitches


def progression_to_notes(
    root: str,
    scale: Union[ScaleType, str],
    numerals: List[str],
    bars_per_chord: float = 1.0,
    octave: int = 4,
    velocity: float = 0.75,
) -> List[MidiNote]:
    """Convert a Roman numeral chord progression into a list of timed MidiNotes."""
    scale_type = ScaleType(scale.lower()) if isinstance(scale, str) else scale
    root_base_midi = note_to_midi(f"{root}{octave}")

    is_minor = scale_type in (
        ScaleType.NATURAL_MINOR,
        ScaleType.HARMONIC_MINOR,
        ScaleType.MELODIC_MINOR,
        ScaleType.DORIAN,
        ScaleType.PHRYGIAN,
        ScaleType.MINOR_PENTATONIC,
    )
    diatonic_map = MINOR_DIATONIC if is_minor else MAJOR_DIATONIC

    notes: List[MidiNote] = []
    current_bar = 0.0

    for num in numerals:
        clean_num = num.strip()
        if clean_num not in diatonic_map:
            # Fallback for unrecognized numerals: treat as tonic
            semitone_offset, quality = (0, ChordQuality.MINOR if is_minor else ChordQuality.MAJOR)
        else:
            semitone_offset, quality = diatonic_map[clean_num]

        chord_root = root_base_midi + semitone_offset
        chord_pitches = build_chord(chord_root, quality)

        for pitch in chord_pitches:
            notes.append(
                MidiNote(
                    pitch=pitch,
                    time_bars=round(current_bar, 4),
                    length_bars=round(bars_per_chord * 0.95, 4),  # slight gap for phrasing
                    velocity=velocity,
                )
            )

        current_bar += bars_per_chord

    return notes
