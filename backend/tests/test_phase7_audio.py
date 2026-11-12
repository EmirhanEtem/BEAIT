"""Phase 7 Tests: Audio Rendering Workflow, Acoustic Analysis, and Critic Feedback."""

from __future__ import annotations

import json
import math
import os
import struct
import tempfile
import wave
import pytest

from app.agents import CriticAgent
from app.integrations.audio import (
    AudioAnalyzer,
    FLRenderWorkflow,
    RenderSettings,
)
from app.schemas.actions import ActionLifecycleState, ActionType


FIXTURES_AUDIO_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "fixtures", "audio")
)


def _synthesize_wav(
    path: str,
    *,
    duration_sec: float = 1.0,
    sample_rate: int = 44100,
    channels: int = 2,
    freqs_amps: list[tuple[float, float]] | None = None,
    clip: bool = False,
) -> None:
    """Generate a deterministic 16-bit PCM WAV file with specified frequencies and amplitudes."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    nframes = int(duration_sec * sample_rate)
    if freqs_amps is None:
        freqs_amps = [(110.0, 0.35), (440.0, 0.25), (2000.0, 0.10)]

    frames = bytearray()
    for i in range(nframes):
        t = i / float(sample_rate)
        # Add subtle quarter-note amplitude pulse (120 BPM = 2 Hz) for onset envelope
        pulse = 0.85 + 0.15 * math.sin(2.0 * math.pi * 2.0 * t)
        val = sum(amp * math.sin(2.0 * math.pi * freq * t) for freq, amp in freqs_amps) * pulse
        if clip:
            val = val * 4.0
        clamped = max(-1.0, min(1.0, val))
        pcm_int = int(round(clamped * 32767.0))
        frame_bytes = struct.pack("<h", pcm_int) * channels
        frames.extend(frame_bytes)

    with wave.open(path, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(bytes(frames))


class TestFLRenderWorkflow:
    def test_blocks_overwrite_without_explicit_approval(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "existing_render.wav")
            _synthesize_wav(out_path, duration_sec=0.5)
            original_size = os.path.getsize(out_path)

            workflow = FLRenderWorkflow(
                dialog_inspector=lambda: {"dialog_detected": True, "format": "WAV", "sample_rate": 44100}
            )
            res = workflow.execute_render(
                RenderSettings(output_path=out_path, overwrite_approved=False)
            )

            assert res.success is False
            assert res.status == "AWAITING_OVERWRITE_APPROVAL"
            assert res.file_exists is True
            assert res.file_size_bytes == original_size
            assert "overwrite_approved=True" in (res.error or "")

    def test_fails_honestly_when_export_dialog_not_detected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "new_render.wav")
            workflow = FLRenderWorkflow(
                dialog_inspector=lambda: {"dialog_detected": False}
            )
            res = workflow.execute_render(RenderSettings(output_path=out_path))

            assert res.success is False
            assert res.status == "DIALOG_NOT_FOUND"
            assert res.dialog_detected is False

    def test_fails_honestly_when_rendered_file_missing_or_corrupt(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "corrupt_render.wav")
            # Write truncated 12-byte invalid WAV
            with open(out_path, "wb") as f:
                f.write(b"RIFF\x00\x00\x00\x00WAVE")

            workflow = FLRenderWorkflow(
                dialog_inspector=lambda: {"dialog_detected": True, "format": "WAV", "sample_rate": 44100},
                render_Write_hook=lambda s: True,
            )
            res = workflow.execute_render(
                RenderSettings(output_path=out_path, overwrite_approved=True)
            )

            assert res.success is False
            assert res.status == "VERIFICATION_FAILED"
            assert res.integrity_verified is False

    def test_successful_render_and_example_fixture_generation(self):
        os.makedirs(FIXTURES_AUDIO_DIR, exist_ok=True)
        example_wav = os.path.join(FIXTURES_AUDIO_DIR, "example_render.wav")

        workflow = FLRenderWorkflow(
            dialog_inspector=lambda: {
                "dialog_detected": True,
                "dialog_title": "FL Studio - Rendering to example_render.wav",
                "format": "WAV",
                "sample_rate": 44100,
            },
            render_Write_hook=lambda s: (_synthesize_wav(s.output_path, duration_sec=2.0) or True),
        )
        res = workflow.execute_render(
            RenderSettings(output_path=example_wav, sample_rate=44100, bit_depth=16, overwrite_approved=True)
        )

        assert res.success is True
        assert res.status == "SUCCEEDED"
        assert res.integrity_verified is True
        assert abs(res.duration_seconds - 2.0) < 0.01
        assert res.file_size_bytes > 350000


class TestAudioAnalyzer:
    def test_reproducible_analysis_and_report_export(self):
        example_wav = os.path.join(FIXTURES_AUDIO_DIR, "example_render.wav")
        if not os.path.isfile(example_wav):
            _synthesize_wav(example_wav, duration_sec=2.0)

        analyzer = AudioAnalyzer()
        rep1 = analyzer.analyze_file(example_wav)
        rep2 = analyzer.analyze_file(example_wav)

        assert rep1.success is True
        assert rep1.measured_facts == rep2.measured_facts
        assert rep1.heuristic_observations == rep2.heuristic_observations

        facts = rep1.measured_facts
        assert facts is not None
        assert facts.sample_rate == 44100
        assert facts.channels == 2
        assert facts.bit_depth == 16
        assert facts.is_clipping is False
        assert facts.is_mostly_silent is False
        assert -6.0 <= facts.peak_dbfs <= -2.0
        assert -14.0 <= facts.rms_dbfs <= -6.0

        obs = rep1.heuristic_observations
        assert obs is not None
        total_ratio = obs.low_band_energy_ratio + obs.mid_band_energy_ratio + obs.high_band_energy_ratio
        assert abs(total_ratio - 1.0) < 0.005
        assert "heuristic signal estimates" in obs.caveat

        # Save example structured analysis report JSON fixture
        report_json_path = os.path.join(FIXTURES_AUDIO_DIR, "example_analysis_report.json")
        with open(report_json_path, "w", encoding="utf-8") as f:
            json.dump(rep1.to_dict(), f, indent=2)
        assert os.path.isfile(report_json_path)

    def test_detects_digital_clipping(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            clip_wav = os.path.join(tmpdir, "clipped.wav")
            _synthesize_wav(clip_wav, duration_sec=0.5, clip=True)

            analyzer = AudioAnalyzer()
            rep = analyzer.analyze_file(clip_wav)
            assert rep.success is True
            assert rep.measured_facts is not None
            assert rep.measured_facts.is_clipping is True
            assert rep.measured_facts.clipped_samples > 100
            assert rep.measured_facts.peak_dbfs >= -0.05

    def test_detects_excessive_silence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            silent_wav = os.path.join(tmpdir, "silent.wav")
            _synthesize_wav(silent_wav, duration_sec=0.5, freqs_amps=[(440.0, 0.0)])

            analyzer = AudioAnalyzer()
            rep = analyzer.analyze_file(silent_wav)
            assert rep.success is True
            assert rep.measured_facts is not None
            assert rep.measured_facts.is_mostly_silent is True
            assert rep.measured_facts.silence_ratio == 1.0
            assert rep.measured_facts.rms_dbfs == -120.0

    def test_detects_low_frequency_dominance(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sub_wav = os.path.join(tmpdir, "sub_only.wav")
            _synthesize_wav(sub_wav, duration_sec=0.5, freqs_amps=[(80.0, 0.6)])

            analyzer = AudioAnalyzer()
            rep = analyzer.analyze_file(sub_wav)
            assert rep.success is True
            assert rep.heuristic_observations is not None
            assert rep.heuristic_observations.low_band_energy_ratio >= 0.80
            assert "Low-frequency dominant" in rep.heuristic_observations.spectral_balance_summary


class TestCriticAgent:
    def test_critic_distinguishes_measured_facts_from_subjective_recommendations(self):
        example_wav = os.path.join(FIXTURES_AUDIO_DIR, "example_render.wav")
        if not os.path.isfile(example_wav):
            _synthesize_wav(example_wav, duration_sec=2.0)

        analyzer = AudioAnalyzer()
        analysis = analyzer.analyze_file(example_wav)

        critic = CriticAgent()
        feedback = critic.evaluate_render(analysis, expected_duration_seconds=2.0)

        assert feedback.render_valid is True
        assert feedback.overall_health == "HEALTHY"
        assert "never guarantee objective artistic perfection" in feedback.objectivity_disclaimer

        categories = {f.category for f in feedback.measured_findings}
        assert "MEASURED_FACT" in categories
        assert "HEURISTIC_OBSERVATION" in categories
        assert len(feedback.subjective_recommendations) >= 1

    def test_critic_clipping_proposes_approval_gated_revision(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            clip_wav = os.path.join(tmpdir, "clipped.wav")
            _synthesize_wav(clip_wav, duration_sec=0.5, clip=True)

            analysis = AudioAnalyzer().analyze_file(clip_wav)
            feedback = CriticAgent().evaluate_render(analysis)

            assert feedback.overall_health == "CRITICAL_ISSUES"
            codes = [f.code for f in feedback.measured_findings]
            assert "DIGITAL_CLIPPING_DETECTED" in codes

            assert len(feedback.proposed_revisions) >= 1
            for rev in feedback.proposed_revisions:
                assert rev.action_type == ActionType.SET_MIXER_VOLUME
                assert rev.requires_approval is True
                assert rev.status == ActionLifecycleState.AWAITING_APPROVAL

    def test_critic_handles_failed_render_honestly(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_wav = os.path.join(tmpdir, "does_not_exist.wav")
            analysis = AudioAnalyzer().analyze_file(missing_wav)
            feedback = CriticAgent().evaluate_render(analysis)

            assert feedback.render_valid is False
            assert feedback.overall_health == "RENDER_FAILED"
            assert feedback.measured_findings[0].code == "RENDER_INVALID"
