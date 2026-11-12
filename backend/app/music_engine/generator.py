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


def generate_melody(
    root: str = "C",
    scale: str = "natural_minor",
    progression: Optional[List[str]] = None,
    bars: int = 4,
    density: float = 0.5,
    octave: int = 5,
    tempo: float = 120.0,
    seed: int = 42,
) -> MidiPattern:
    """Generate a scale-constrained melodic motif over a chord progression."""
    rng = random.Random(seed)
    if progression is None:
        progression = ["i", "VI", "III", "VII"]

    scale_enum = ScaleType(scale.lower()) if scale in [s.value for s in ScaleType] else ScaleType.NATURAL_MINOR
    allowed_pitches = get_scale_pitches(root, scale_enum, start_octave=octave, end_octave=octave + 1)
    if not allowed_pitches:
        allowed_pitches = [60, 62, 63, 65, 67, 68, 70, 72]

    notes: List[MidiNote] = []
    # 8 eighth-note slots per bar
    slots_per_bar = 8
    slot_duration = 1.0 / slots_per_bar
    current_pitch_idx = 0

    for bar_idx in range(bars):
        for slot in range(slots_per_bar):
            is_downbeat = (slot % 4 == 0)
            # Always place a note on bar start; otherwise use density probability
            if (bar_idx == 0 and slot == 0) or (is_downbeat and rng.random() < max(0.65, density)) or (rng.random() < density):
                if is_downbeat:
                    # Target stable scale degrees (root, 3rd, 5th)
                    stable_indices = [0, 2, 4]
                    current_pitch_idx = rng.choice([i for i in stable_indices if i < len(allowed_pitches)] or [0])
                else:
                    # Stepwise motion (-2, -1, +1, +2 scale steps)
                    step = rng.choice([-2, -1, 1, 2])
                    current_pitch_idx = max(0, min(len(allowed_pitches) - 1, current_pitch_idx + step))

                pitch = allowed_pitches[current_pitch_idx]
                time_bars = round(bar_idx + slot * slot_duration, 4)
                length_bars = round(slot_duration * 0.9, 4)
                vel = 0.82 if is_downbeat else 0.68

                notes.append(
                    MidiNote(
                        pitch=pitch,
                        time_bars=time_bars,
                        length_bars=length_bars,
                        velocity=vel,
                    )
                )

    return MidiPattern(
        name=f"Melody - {root} {scale_enum.value}",
        bars=bars,
        tempo_bpm=tempo,
        key_root=root,
        scale=scale_enum,
        notes=notes,
    )


def apply_humanization(
    pattern: MidiPattern,
    velocity_variation: float = 0.06,
    swing_amount: float = 0.015,
    seed: int = 101,
) -> MidiPattern:
    """Apply subtle musical velocity variation and groove/swing timing while preserving bar boundaries."""
    rng = random.Random(seed)
    humanized_notes: List[MidiNote] = []
    max_bar = float(pattern.bars)

    for note in pattern.notes:
        # 1. Velocity variation
        vel_delta = rng.uniform(-velocity_variation, velocity_variation)
        new_vel = round(max(0.05, min(1.0, note.velocity + vel_delta)), 3)

        # 2. Swing on off-beat 16ths (every odd 16th note = 0.0625 bar multiples)
        sixteenth_index = round(note.time_bars / 0.0625)
        time_offset = swing_amount if (sixteenth_index % 2 == 1) else 0.0
        new_time = round(max(0.0, note.time_bars + time_offset), 4)

        # Clamp length so note never exceeds pattern bar boundary
        max_len = max(0.01, max_bar - new_time)
        new_len = round(min(note.length_bars, max_len), 4)

        humanized_notes.append(
            MidiNote(
                pitch=note.pitch,
                time_bars=new_time,
                length_bars=new_len,
                velocity=new_vel,
                channel=note.channel,
                pan=note.pan,
            )
        )

    return MidiPattern(
        name=f"{pattern.name} (Humanized)",
        time_signature=pattern.time_signature,
        bars=pattern.bars,
        tempo_bpm=pattern.tempo_bpm,
        key_root=pattern.key_root,
        scale=pattern.scale,
        notes=humanized_notes,
    )


