"""Phase 6 Tests: Music Production Engine, Specialist Agents, Arrangement Planner, and Sample Scanner."""

from __future__ import annotations

import os
import struct
import tempfile
import wave
import pytest

from app.agents import (
    ArrangerAgent,
    ComposerAgent,
    RhythmAgent,
    SoundDesignerAgent,
)
from app.integrations.filesystem import SampleScanner
from app.music_engine import (
    GenrePreset,
    GenrePresetRegistry,
    ScaleType,
    get_scale_pitches,
    read_midi_file,
)
from app.schemas.actions import ActionType


FIXTURES_MIDI_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "fixtures", "midi")
)


def _write_test_wav(
    path: str,
    *,
    duration_sec: float = 0.5,
    sample_rate: int = 44100,
    channels: int = 2,
    sampwidth_bytes: int = 2,
) -> None:
    """Create a valid uncompressed PCM WAV file for deterministic scanner tests."""
    num_frames = int(duration_sec * sample_rate)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sampwidth_bytes)
        wf.setframerate(sample_rate)
        # Silence frames
        frame_bytes = b"\x00" * (channels * sampwidth_bytes)
        wf.writeframes(frame_bytes * num_frames)


class TestGenrePresets:
    def test_load_default_presets_and_disclaimer(self):
        registry = GenrePresetRegistry()
        presets = registry.list_presets()
        assert len(presets) >= 4
        assert "starting-point heuristics" in registry.disclaimer

        mt = registry.get("melodic_techno")
        assert mt is not None
        assert mt.default_bpm == 126.0
        assert mt.default_root == "A"
        assert mt.default_scale == "natural_minor"
        assert "not universal rules" in mt.stylistic_disclaimer

    def test_register_custom_preset(self):
        registry = GenrePresetRegistry()
        custom = GenrePreset(
            key="synthwave_retro",
            display_name="Retro Synthwave",
            mood="nostalgic, neon",
            default_bpm=110.0,
            default_root="E",
            default_scale="natural_minor",
        )
        registry.register_custom_preset(custom)
        fetched = registry.get("synthwave_retro")
        assert fetched is not None
        assert fetched.default_bpm == 110.0
        assert fetched.default_root == "E"


class TestComposerAgent:
    @pytest.mark.parametrize(
        "genre,expected_root,expected_scale",
        [
            ("melodic_techno", "A", "natural_minor"),
            ("deep_house", "C", "dorian"),
            ("trap_dark", "F#", "harmonic_minor"),
            ("boom_bap_chill", "D", "natural_minor"),
        ],
    )
    def test_compose_respects_key_scale_and_bar_length(self, genre, expected_root, expected_scale):
        composer = ComposerAgent()
        bundle = composer.compose(genre=genre, bars=4, humanize=True)

        assert bundle.is_valid
        assert bundle.root == expected_root
        assert bundle.scale == expected_scale
        assert bundle.bars == 4

        allowed = set(get_scale_pitches(expected_root, ScaleType(expected_scale), start_octave=0, end_octave=9))

        for part_name, pattern in [
            ("chords", bundle.chords),
            ("bassline", bundle.bassline),
            ("melody", bundle.melody),
        ]:
            assert len(pattern.notes) > 0, f"{part_name} should not be empty"
            val = bundle.validations[part_name]
            assert val.is_valid, f"{part_name} validation errors: {val.errors}"

            for n in pattern.notes:
                assert n.pitch in allowed, (
                    f"{genre} {part_name} note pitch {n.pitch} outside {expected_root} {expected_scale}"
                )
                assert 0.0 <= n.time_bars < 4.0
                assert n.time_bars + n.length_bars <= 4.0 + 1e-6

    def test_export_midi_fixtures_and_roundtrip(self):
        os.makedirs(FIXTURES_MIDI_DIR, exist_ok=True)
        composer = ComposerAgent()
        bundle = composer.compose(
            genre="melodic_techno",
            bars=4,
            humanize=True,
            export_dir=FIXTURES_MIDI_DIR,
        )

        assert set(bundle.exported_midi_files.keys()) == {"chords", "bassline", "melody"}
        for part, path in bundle.exported_midi_files.items():
            assert os.path.isfile(path), f"Missing exported MIDI fixture: {path}"
            reloaded = read_midi_file(path)
            assert len(reloaded.notes) == len(getattr(bundle, part).notes)


class TestRhythmAgent:
    def test_build_rhythm_fits_meter_and_emits_actions(self):
        agent = RhythmAgent()
        bundle = agent.build_rhythm(genre="melodic_techno", steps=16)

        assert bundle.is_valid
        assert bundle.steps == 16
        assert len(bundle.drum_pattern.channels) == 4
        assert len(bundle.planned_actions) == 4

        for action in bundle.planned_actions:
            assert action.action_type == ActionType.SET_STEP_GRID
            assert action.parameters["length"] == 16
            for step_idx in action.parameters["steps"]:
                assert 0 <= step_idx < 16

    def test_energy_variants_filter_channels(self):
        agent = RhythmAgent()
        intro = agent.build_rhythm(genre="deep_house", steps=16, energy_variant="intro")
        breakdown = agent.build_rhythm(genre="deep_house", steps=16, energy_variant="breakdown")

        intro_by_name = {c.channel_name: c.steps for c in intro.drum_pattern.channels}
        assert intro_by_name["808 Kick"] == [0, 4, 8, 12]
        assert intro_by_name["808 Clap"] == []
        assert intro_by_name["808 Snare"] == []

        bd_by_name = {c.channel_name: c.steps for c in breakdown.drum_pattern.channels}
        assert bd_by_name["808 Kick"] == []
        assert len(bd_by_name["808 HiHat"]) > 0


class TestSoundDesignerAgent:
    def test_sound_design_plan_and_mixer_actions(self):
        designer = SoundDesignerAgent()
        plan = designer.create_sound_plan(genre="trap_dark")

        assert len(plan.layers) >= 2
        assert len(plan.mixer_targets) >= 4
        assert len(plan.planned_actions) >= 4
        assert "starting points" in plan.disclaimer

        vol_actions = [a for a in plan.planned_actions if a.action_type == ActionType.SET_MIXER_VOLUME]
        assert len(vol_actions) == len(plan.mixer_targets)


class TestArrangerAgent:
    def test_contiguous_multi_section_arrangement(self):
        arranger = ArrangerAgent()
        plan = arranger.create_arrangement(genre="melodic_techno")

        assert plan.is_contiguous
        section_names = [s.name for s in plan.sections]
        assert section_names == ["Intro", "Build", "Drop", "Breakdown", "Outro"]
        assert plan.total_bars == 48

        # Verify bar boundaries
        assert plan.sections[0].start_bar == 1
        assert plan.sections[0].end_bar == 9
        assert plan.sections[2].name == "Drop"
        assert plan.sections[2].start_bar == 17
        assert plan.sections[2].bars == 16
        assert plan.sections[4].end_bar == 49

        # Each section emits CREATE_PATTERN + ADD_ARRANGEMENT_MARKER
        assert len(plan.planned_actions) == len(plan.sections) * 2
        marker_actions = [
            a for a in plan.planned_actions if a.action_type == ActionType.ADD_ARRANGEMENT_MARKER
        ]
        assert [a.parameters["bar"] for a in marker_actions] == [1, 9, 17, 33, 41]


class TestSampleScanner:
    def test_rejects_unapproved_directory_and_traversal(self):
        with tempfile.TemporaryDirectory() as approved_dir, tempfile.TemporaryDirectory() as outside_dir:
            scanner = SampleScanner(approved_directories=[approved_dir])

            # 1. Scanning outside_dir must raise PermissionError
            with pytest.raises(PermissionError, match="outside explicitly approved"):
                scanner.scan_directory(outside_dir)

            # 2. Path traversal via .. must raise PermissionError
            traversal_path = os.path.join(approved_dir, "..", os.path.basename(outside_dir))
            with pytest.raises(PermissionError, match="outside explicitly approved"):
                scanner.scan_directory(traversal_path)

    def test_scans_wav_metadata_tags_and_audition_safety(self):
        with tempfile.TemporaryDirectory() as approved_dir:
            kick_path = os.path.join(approved_dir, "126bpm_Am_Kick_Punch.wav")
            synth_loop_path = os.path.join(approved_dir, "F#m_140BPM_Synth_Lead_Loop.wav")
            clap_path = os.path.join(approved_dir, "Clap_Tight.wav")

            _write_test_wav(kick_path, duration_sec=0.4, sample_rate=44100, channels=1, sampwidth_bytes=2)
            _write_test_wav(synth_loop_path, duration_sec=3.5, sample_rate=48000, channels=2, sampwidth_bytes=3)
            _write_test_wav(clap_path, duration_sec=0.25, sample_rate=44100, channels=2, sampwidth_bytes=2)

            scanner = SampleScanner(approved_directories=[approved_dir])
            samples = scanner.scan_directory(approved_dir)
            assert len(samples) == 3

            by_name = {s.filename: s for s in samples}

            kick = by_name["126bpm_Am_Kick_Punch.wav"]
            assert kick.category == "kick"
            assert kick.sample_type == "one_shot"
            assert kick.detected_bpm == 126.0
            assert kick.detected_key == "Am"
            assert kick.sample_rate == 44100
            assert kick.channels == 1
            assert kick.bit_depth == 16
            assert abs(kick.duration_seconds - 0.4) < 0.02

            synth = by_name["F#m_140BPM_Synth_Lead_Loop.wav"]
            assert synth.category == "synth"
            assert synth.sample_type == "loop"
            assert synth.detected_bpm == 140.0
            assert synth.detected_key == "F#m"
            assert synth.sample_rate == 48000
            assert synth.channels == 2
            assert synth.bit_depth == 24

            # Search filtering
            kicks_only = scanner.search(category="kick")
            assert len(kicks_only) == 1
            assert kicks_only[0].filename == "126bpm_Am_Kick_Punch.wav"

            loops_only = scanner.search(sample_type="loop", bpm_target=140.0, bpm_tolerance=2.0)
            assert len(loops_only) == 1
            assert loops_only[0].filename == "F#m_140BPM_Synth_Lead_Loop.wav"

            # Audition descriptor inside approved directory
            audition = scanner.prepare_audition(kick_path)
            assert audition.audition_ready is True
            assert audition.sample.category == "kick"
            assert audition.sample.sample_rate == 44100
