"""Deterministic validation for generated MIDI notes and drum step patterns."""

from __future__ import annotations

import math
from typing import List, Optional, Tuple
from .models import DrumChannelPattern, MidiNote, ScaleType
from .scales import get_scale_pitches


class ValidationResult:
    def __init__(self, is_valid: bool, errors: Optional[List[str]] = None, warnings: Optional[List[str]] = None):
        self.is_valid = is_valid
        self.errors = errors or []
        self.warnings = warnings or []

    def __repr__(self) -> str:
        return f"ValidationResult(is_valid={self.is_valid}, errors={len(self.errors)}, warnings={len(self.warnings)})"


def validate_midi_notes(
    notes: List[MidiNote],
    *,
    max_polyphony: int = 16,
    max_bars: float = 128.0,
    expected_root: Optional[str] = None,
    expected_scale: Optional[ScaleType] = None,
) -> ValidationResult:
    """Deterministically validates a list of MidiNote events before sending to FL Studio."""
    errors: List[str] = []
    warnings: List[str] = []

    if not notes:
        warnings.append("Note list is empty.")
        return ValidationResult(is_valid=True, warnings=warnings)

    allowed_pitches = None
    if expected_root and expected_scale:
        try:
            allowed_pitches = set(get_scale_pitches(expected_root, expected_scale))
        except Exception as e:
            warnings.append(f"Could not compute scale pitches for {expected_root} {expected_scale}: {e}")

    seen_events = set()
    out_of_scale_count = 0

    for idx, note in enumerate(notes):
        # 1. Pitch bounds
        if not (0 <= note.pitch <= 127):
            errors.append(f"Note #{idx}: pitch {note.pitch} outside standard range [0..127]")

        # 2. Timing bounds
        if note.time_bars < 0.0 or not math.isfinite(note.time_bars):
            errors.append(f"Note #{idx}: time_bars {note.time_bars} is invalid or negative")

        if note.length_bars <= 0.0 or not math.isfinite(note.length_bars):
            errors.append(f"Note #{idx}: length_bars {note.length_bars} must be strictly positive")

        if note.time_bars + note.length_bars > max_bars:
            errors.append(f"Note #{idx}: note ends at {note.time_bars + note.length_bars} bars, exceeding limit {max_bars}")

        # 3. Velocity bounds
        if not (0.0 <= note.velocity <= 1.0) or not math.isfinite(note.velocity):
            errors.append(f"Note #{idx}: velocity {note.velocity} must be between 0.0 and 1.0")

        # 4. Duplicate checks
        event_key = (note.pitch, round(note.time_bars, 4), note.channel)
        if event_key in seen_events:
            warnings.append(f"Note #{idx}: duplicate note event at pitch {note.pitch}, bar {note.time_bars}")
        seen_events.add(event_key)

        # 5. Scale conformance
        if allowed_pitches is not None and note.pitch not in allowed_pitches:
            out_of_scale_count += 1

    if allowed_pitches and out_of_scale_count > 0:
        ratio = (out_of_scale_count / len(notes)) * 100.0
        warnings.append(f"{out_of_scale_count}/{len(notes)} notes ({ratio:.1f}%) are outside the specified scale {expected_root} {expected_scale}")

    # 6. Polyphony density check (slice-based)
    time_points = sorted(set(n.time_bars for n in notes))
    for t in time_points:
        active = sum(1 for n in notes if n.time_bars <= t < (n.time_bars + n.length_bars))
        if active > max_polyphony:
            errors.append(f"Polyphony exceeded at bar {t}: {active} concurrent notes (limit: {max_polyphony})")
            break

    is_valid = len(errors) == 0
    return ValidationResult(is_valid=is_valid, errors=errors, warnings=warnings)


def validate_drum_channel(
    pattern: DrumChannelPattern,
) -> ValidationResult:
    """Validates step indices for a single drum channel."""
    errors: List[str] = []
    warnings: List[str] = []

    if pattern.length < 1 or pattern.length > 256:
        errors.append(f"Channel {pattern.channel_name}: length {pattern.length} must be between 1 and 256")

    invalid_steps = [s for s in pattern.steps if not (0 <= s < pattern.length)]
    if invalid_steps:
        errors.append(f"Channel {pattern.channel_name}: steps {invalid_steps} outside range [0..{pattern.length - 1}]")

    # Check duplicates
    if len(pattern.steps) != len(set(pattern.steps)):
        warnings.append(f"Channel {pattern.channel_name}: duplicate steps detected, deduplicating")
        pattern.steps = sorted(set(pattern.steps))

    is_valid = len(errors) == 0
    return ValidationResult(is_valid=is_valid, errors=errors, warnings=warnings)
