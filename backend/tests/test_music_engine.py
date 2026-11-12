"""Unit tests for Music & MIDI Engine."""

import os
import tempfile
import pytest
from app.music_engine import (
    ChordQuality,
    DrumChannelPattern,
    MidiNote,
    ScaleType,
    build_chord,
    export_midi_file,
    generate_bassline,
    generate_chord_pattern,
    generate_drum_pattern,
    get_scale_pitches,
    midi_to_note,
    note_to_midi,
    quantize_pitch_to_scale,
    read_midi_file,
    validate_drum_channel,
    validate_midi_notes,
)


def test_note_midi_conversion():
    assert note_to_midi("C4") == 60
    assert note_to_midi("A4") == 69
    assert note_to_midi("C-1") == 0
    assert note_to_midi("G9") == 127
    assert note_to_midi("F#3") == 54
    assert note_to_midi("Bb3") == 58

    assert midi_to_note(60) == "C4"
    assert midi_to_note(69) == "A4"
    assert midi_to_note(54) == "F#3"
    assert midi_to_note(58, use_sharps=False) == "Bb3"

    with pytest.raises(ValueError):
        note_to_midi("InvalidNote")


def test_scale_generation_and_quantization():
    c_major = get_scale_pitches("C", ScaleType.MAJOR, start_octave=4, end_octave=4)
    # C4, D4, E4, F4, G4, A4, B4
    expected = [60, 62, 64, 65, 67, 69, 71]
    assert c_major == expected

    a_minor = get_scale_pitches("A", ScaleType.NATURAL_MINOR, start_octave=4, end_octave=4)
    # A4, B4, C5, D5, E5, F5, G5
    expected_minor = [69, 71, 72, 74, 76, 77, 79]
    assert a_minor == expected_minor

    # Quantize F#4 (66) to C major -> should snap to F4 (65) or G4 (67)
    snapped = quantize_pitch_to_scale(66, c_major)
    assert snapped in (65, 67)


def test_chord_construction():
    # C major triad: C4(60), E4(64), G4(67)
    c_maj = build_chord(60, ChordQuality.MAJOR)
    assert c_maj == [60, 64, 67]

    # C minor triad: C4(60), Eb4(63), G4(67)
    c_min = build_chord(60, ChordQuality.MINOR)
    assert c_min == [60, 63, 67]

    # Inversion 1: E4(64), G4(67), C5(72)
    inv1 = build_chord(60, ChordQuality.MAJOR, inversion=1)
    assert inv1 == [64, 67, 72]


def test_drum_pattern_generation():
    pattern = generate_drum_pattern("four_on_the_floor", length=16, tempo=128.0)
    assert pattern.length == 16
    assert pattern.tempo_bpm == 128.0

    ch_map = {c.channel_name: c for c in pattern.channels}
    assert "808 Kick" in ch_map
    assert ch_map["808 Kick"].steps == [0, 4, 8, 12]
    assert ch_map["808 Kick"].pattern_string == "x...x...x...x..."

    assert "808 Clap" in ch_map
    assert ch_map["808 Clap"].steps == [4, 12]


def test_midi_validation_success():
    notes = [
        MidiNote(pitch=60, time_bars=0.0, length_bars=0.25, velocity=0.8),
        MidiNote(pitch=64, time_bars=0.25, length_bars=0.25, velocity=0.8),
        MidiNote(pitch=67, time_bars=0.5, length_bars=0.5, velocity=0.8),
    ]
    res = validate_midi_notes(notes, expected_root="C", expected_scale=ScaleType.MAJOR)
    assert res.is_valid is True
    assert len(res.errors) == 0


def test_midi_validation_errors():
    # Note with invalid pitch
    with pytest.raises(ValueError):
        MidiNote(pitch=150, time_bars=0.0, length_bars=1.0)

    # Note with non-positive length
    with pytest.raises(ValueError):
        MidiNote(pitch=60, time_bars=0.0, length_bars=0.0)

    # Note with negative time
    with pytest.raises(ValueError):
        MidiNote(pitch=60, time_bars=-1.0, length_bars=1.0)


def test_drum_channel_validation():
    ch_ok = DrumChannelPattern(channel_name="Kick", length=16, steps=[0, 4, 8, 12])
    res_ok = validate_drum_channel(ch_ok)
    assert res_ok.is_valid is True

    ch_err = DrumChannelPattern(channel_name="Kick", length=16, steps=[0, 20])
    res_err = validate_drum_channel(ch_err)
    assert res_err.is_valid is False
    assert any("outside range" in e for e in res_err.errors)


def test_midi_file_export_and_import():
    pat = generate_chord_pattern(root="A", scale="natural_minor", progression=["i", "VI", "III", "VII"])
    with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        exported_path = export_midi_file(pat, tmp_path)
        assert os.path.exists(exported_path)
        assert os.path.getsize(exported_path) > 50

        # Read it back and verify notes
        read_pat = read_midi_file(exported_path)
        assert len(read_pat.notes) == len(pat.notes)
        assert read_pat.tempo_bpm == pat.tempo_bpm
        # Compare pitch sets
        orig_pitches = [n.pitch for n in pat.notes]
        read_pitches = [n.pitch for n in read_pat.notes]
        assert orig_pitches == read_pitches
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

