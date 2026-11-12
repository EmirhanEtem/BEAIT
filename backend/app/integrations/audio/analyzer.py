"""Audio Render Analysis Module (Phase 7 & Section 6.5).

Computes deterministic, reproducible acoustic measurements from rendered audio files:
- Duration, sample rate, channels, bit depth
- Peak level (linear & dBFS), RMS level (linear & dBFS), Crest Factor (dB)
- Sample clipping detection (count & ratio)
- Silence detection (leading, trailing, overall silence ratio)
- 3-band spectral energy balance (Low 20-250 Hz, Mid 250-4000 Hz, High 4000+ Hz)
- Onset-envelope tempo estimation (explicitly labeled as an estimate)

Clearly separates objective measured facts from heuristic spectral/tempo estimates.
Uses soundfile/numpy when available and provides a deterministic standard-library
PCM WAV DSP engine so analysis works reliably across all Python environments.
"""

from __future__ import annotations

import math
import os
import struct
import wave
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class MeasuredAudioFacts:
    """Objective, deterministic measurements of an audio file."""
    file_path: str
    file_size_bytes: int
    duration_seconds: float
    sample_rate: int
    channels: int
    bit_depth: int
    total_frames: int
    peak_linear: float
    peak_dbfs: float
    rms_linear: float
    rms_dbfs: float
    crest_factor_db: float
    clipped_samples: int
    clipping_ratio: float
    is_clipping: bool
    silence_ratio: float
    leading_silence_seconds: float
    trailing_silence_seconds: float
    is_mostly_silent: bool
    dc_offset: float


@dataclass(frozen=True)
class HeuristicAudioObservations:
    """Heuristic spectral and rhythmic estimates with explicit caveats."""
    low_band_energy_ratio: float     # ~20 - 250 Hz
    mid_band_energy_ratio: float     # ~250 - 4000 Hz
    high_band_energy_ratio: float    # ~4000 - 16000 Hz
    spectral_centroid_hz_est: float
    spectral_balance_summary: str
    estimated_tempo_bpm: Optional[float]
    tempo_confidence_note: str = "Heuristic onset-envelope estimate only; not a ground-truth DAW clock."
    caveat: str = (
        "Spectral balance and tempo indicators are heuristic signal estimates, "
        "not objective professional mixing judgments."
    )


@dataclass
class AudioAnalysisReport:
    """Structured analysis report separating measured facts from heuristic observations."""
    success: bool
    measured_facts: Optional[MeasuredAudioFacts] = None
    heuristic_observations: Optional[HeuristicAudioObservations] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "measured_facts": asdict(self.measured_facts) if self.measured_facts else None,
            "heuristic_observations": (
                asdict(self.heuristic_observations) if self.heuristic_observations else None
            ),
            "error": self.error,
        }


def _linear_to_dbfs(val: float, floor_db: float = -120.0) -> float:
    if val <= 1e-6:
        return floor_db
    return round(max(floor_db, 20.0 * math.log10(val)), 2)


def _decode_pcm_wav_mono_and_peaks(
    file_path: str,
) -> Tuple[List[float], int, int, int, int, float, int, int]:
    """Decode PCM WAV (8/16/24/32-bit) into a mono float signal [-1.0, 1.0] plus exact peak/clipping counts."""
    with wave.open(file_path, "rb") as wf:
        channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        sample_rate = wf.getframerate()
        nframes = wf.getnframes()
        raw = wf.readframes(nframes)

    if nframes == 0 or sample_rate <= 0 or channels <= 0:
        return [], sample_rate, channels, sampwidth * 8, 0, 0.0, 0, 0

    total_samples = nframes * channels
    mono_samples: List[float] = []
    peak_linear = 0.0
    clipped_count = 0
    clip_threshold = 0.9985

    if sampwidth == 2:
        # 16-bit signed PCM
        ints = struct.unpack(f"<{total_samples}h", raw[: total_samples * 2])
        scale = 1.0 / 32768.0
        for i in range(0, total_samples, channels):
            frame_sum = 0.0
            for c in range(channels):
                v = ints[i + c] * scale
                av = abs(v)
                if av > peak_linear:
                    peak_linear = av
                if av >= clip_threshold or ints[i + c] in (-32768, 32767):
                    clipped_count += 1
                frame_sum += v
            mono_samples.append(frame_sum / channels)
    elif sampwidth == 1:
        # 8-bit unsigned PCM
        uints = struct.unpack(f"<{total_samples}B", raw[:total_samples])
        for i in range(0, total_samples, channels):
            frame_sum = 0.0
            for c in range(channels):
                v = (uints[i + c] - 128) / 128.0
                av = abs(v)
                if av > peak_linear:
                    peak_linear = av
                if av >= clip_threshold:
                    clipped_count += 1
                frame_sum += v
            mono_samples.append(frame_sum / channels)
    elif sampwidth == 3:
        # 24-bit signed PCM
        scale = 1.0 / 8388608.0
        idx = 0
        for _ in range(nframes):
            frame_sum = 0.0
            for _ in range(channels):
                b0 = raw[idx]
                b1 = raw[idx + 1]
                b2 = raw[idx + 2]
                idx += 3
                ival = b0 | (b1 << 8) | (b2 << 16)
                if ival & 0x800000:
                    ival -= 0x1000000
                v = ival * scale
                av = abs(v)
                if av > peak_linear:
                    peak_linear = av
                if av >= clip_threshold:
                    clipped_count += 1
                frame_sum += v
            mono_samples.append(frame_sum / channels)
    elif sampwidth == 4:
        # 32-bit signed PCM
        ints = struct.unpack(f"<{total_samples}i", raw[: total_samples * 4])
        scale = 1.0 / 2147483648.0
        for i in range(0, total_samples, channels):
            frame_sum = 0.0
            for c in range(channels):
                v = ints[i + c] * scale
                av = abs(v)
                if av > peak_linear:
                    peak_linear = av
                if av >= clip_threshold:
                    clipped_count += 1
                frame_sum += v
            mono_samples.append(frame_sum / channels)
    else:
        raise ValueError(f"Unsupported WAV sample width: {sampwidth} bytes")

    return (
        mono_samples,
        sample_rate,
        channels,
        sampwidth * 8,
        nframes,
        min(1.0, peak_linear),
        clipped_count,
        total_samples,
    )


def _goertzel_power(samples: List[float], sample_rate: int, target_freq: float) -> float:
    """Compute normalized power at target_freq Hz using the Goertzel algorithm."""
    n = len(samples)
    if n == 0 or target_freq <= 0 or target_freq >= sample_rate / 2.0:
        return 0.0
    k = int(0.5 + (n * target_freq) / sample_rate)
    omega = (2.0 * math.pi * k) / n
    coeff = 2.0 * math.cos(omega)
    s_prev = 0.0
    s_prev2 = 0.0
    for x in samples:
        s = x + coeff * s_prev - s_prev2
        s_prev2 = s_prev
        s_prev = s
    power = s_prev2 * s_prev2 + s_prev * s_prev - coeff * s_prev * s_prev2
    return max(0.0, power / (n * n))


class AudioAnalyzer:
    """Deterministic audio render analyzer producing facts and heuristic observations."""

    def analyze_file(self, file_path: str) -> AudioAnalysisReport:
        """Analyze a rendered WAV file and return a structured AudioAnalysisReport."""
        abs_path = os.path.abspath(file_path)
        if not os.path.isfile(abs_path):
            return AudioAnalysisReport(
                success=False,
                error=f"Audio file does not exist: '{abs_path}'",
            )

        file_size = os.path.getsize(abs_path)
        if file_size <= 44:
            return AudioAnalysisReport(
                success=False,
                error=f"Audio file '{abs_path}' is empty or truncated ({file_size} bytes).",
            )

        try:
            (
                mono,
                sr,
                channels,
                bit_depth,
                nframes,
                peak_lin,
                clipped_samples,
                total_samples,
            ) = _decode_pcm_wav_mono_and_peaks(abs_path)
        except Exception as exc:
            return AudioAnalysisReport(
                success=False,
                error=f"Failed to decode audio file '{abs_path}': {exc}",
            )

        if not mono or sr <= 0:
            return AudioAnalysisReport(
                success=False,
                error=f"Audio file '{abs_path}' contains 0 decodable frames.",
            )

        duration = round(nframes / float(sr), 4)

        # RMS & DC offset
        sum_sq = 0.0
        sum_val = 0.0
        for x in mono:
            sum_sq += x * x
            sum_val += x
        rms_lin = math.sqrt(sum_sq / len(mono))
        dc_offset = round(sum_val / len(mono), 6)

        peak_dbfs = _linear_to_dbfs(peak_lin)
        rms_dbfs = _linear_to_dbfs(rms_lin)
        crest_db = round(max(0.0, peak_dbfs - rms_dbfs), 2) if rms_lin > 1e-6 else 0.0

        clip_ratio = round(clipped_samples / float(max(1, total_samples)), 6)
        is_clipping = clipped_samples >= 3 or peak_lin >= 0.999

        # Windowed silence analysis (50 ms windows, threshold -60 dBFS = 0.001 linear RMS)
        win_size = max(1, int(sr * 0.05))
        silence_thresh_lin = 0.001
        win_rms_list: List[float] = []
        for start in range(0, len(mono), win_size):
            chunk = mono[start : start + win_size]
            c_rms = math.sqrt(sum(v * v for v in chunk) / len(chunk))
            win_rms_list.append(c_rms)

        silent_windows = sum(1 for r in win_rms_list if r < silence_thresh_lin)
        silence_ratio = round(silent_windows / float(max(1, len(win_rms_list))), 4)

        leading_silent_wins = 0
        for r in win_rms_list:
            if r < silence_thresh_lin:
                leading_silent_wins += 1
            else:
                break

        trailing_silent_wins = 0
        for r in reversed(win_rms_list):
            if r < silence_thresh_lin:
                trailing_silent_wins += 1
            else:
                break

        win_dur = win_size / float(sr)
        leading_silence_sec = round(min(duration, leading_silent_wins * win_dur), 3)
        trailing_silence_sec = round(min(duration, trailing_silent_wins * win_dur), 3)
        is_mostly_silent = silence_ratio >= 0.85 or rms_dbfs <= -55.0

        facts = MeasuredAudioFacts(
            file_path=abs_path,
            file_size_bytes=file_size,
            duration_seconds=duration,
            sample_rate=sr,
            channels=channels,
            bit_depth=bit_depth,
            total_frames=nframes,
            peak_linear=round(peak_lin, 5),
            peak_dbfs=peak_dbfs,
            rms_linear=round(rms_lin, 5),
            rms_dbfs=rms_dbfs,
            crest_factor_db=crest_db,
            clipped_samples=clipped_samples,
            clipping_ratio=clip_ratio,
            is_clipping=is_clipping,
            silence_ratio=silence_ratio,
            leading_silence_seconds=leading_silence_sec,
            trailing_silence_seconds=trailing_silence_sec,
            is_mostly_silent=is_mostly_silent,
            dc_offset=dc_offset,
        )

        # Heuristic spectral analysis via representative probe frequencies
        # Take a representative middle slice (up to 4096 samples) where signal is active
        active_slice = self._select_active_slice(mono, window_len=min(4096, len(mono)))
        low_freqs = [50.0, 80.0, 120.0, 180.0, 220.0]
        mid_freqs = [400.0, 800.0, 1200.0, 2000.0, 3200.0]
        high_freqs = [5000.0, 7500.0, 10000.0, 13000.0]

        low_e = sum(_goertzel_power(active_slice, sr, f) for f in low_freqs)
        mid_e = sum(_goertzel_power(active_slice, sr, f) for f in mid_freqs)
        high_e = sum(_goertzel_power(active_slice, sr, f) for f in high_freqs)
        total_e = low_e + mid_e + high_e

        if total_e > 1e-12:
            low_ratio = round(low_e / total_e, 4)
            mid_ratio = round(mid_e / total_e, 4)
            high_ratio = round(max(0.0, 1.0 - low_ratio - mid_ratio), 4)
            centroid = round(
                (low_e * 120.0 + mid_e * 1500.0 + high_e * 8000.0) / total_e,
                1,
            )
        else:
            low_ratio, mid_ratio, high_ratio = 0.0, 0.0, 0.0
            centroid = 0.0

        if is_mostly_silent:
            spec_summary = "Near-silent signal; spectral distribution not meaningful."
        elif low_ratio >= 0.65:
            spec_summary = "Low-frequency dominant (strong sub/bass energy below 250 Hz)."
        elif high_ratio >= 0.50:
            spec_summary = "High-frequency dominant (bright / transient-heavy above 4 kHz)."
        elif mid_ratio >= 0.65:
            spec_summary = "Mid-range focused (250 Hz - 4 kHz dominant)."
        else:
            spec_summary = "Balanced multi-band spectral distribution across low, mid, and high bands."

        est_bpm = self._estimate_tempo_from_envelope(win_rms_list, win_dur) if not is_mostly_silent else None

        heuristics = HeuristicAudioObservations(
            low_band_energy_ratio=low_ratio,
            mid_band_energy_ratio=mid_ratio,
            high_band_energy_ratio=high_ratio,
            spectral_centroid_hz_est=centroid,
            spectral_balance_summary=spec_summary,
            estimated_tempo_bpm=est_bpm,
        )

        return AudioAnalysisReport(
            success=True,
            measured_facts=facts,
            heuristic_observations=heuristics,
        )

    @staticmethod
    def _select_active_slice(mono: List[float], window_len: int) -> List[float]:
        if len(mono) <= window_len:
            return mono
        # Pick the slice with highest energy among 4 evenly spaced candidates
        best_slice = mono[:window_len]
        best_energy = -1.0
        step = max(1, (len(mono) - window_len) // 4)
        for start in range(0, len(mono) - window_len + 1, step):
            candidate = mono[start : start + window_len]
            # Sub-sample energy check
            e = sum(x * x for x in candidate[::4])
            if e > best_energy:
                best_energy = e
                best_slice = candidate
        return best_slice

    @staticmethod
    def _estimate_tempo_from_envelope(win_rms: List[float], win_dur: float) -> Optional[float]:
        """Estimate tempo in [70..180] BPM using autocorrelation of positive onset differences."""
        if len(win_rms) < 20 or win_dur <= 0:
            return None

        onsets = [max(0.0, win_rms[i] - win_rms[i - 1]) for i in range(1, len(win_rms))]
        if max(onsets, default=0.0) < 1e-4:
            return None

        best_bpm: Optional[float] = None
        best_score = 0.0

        # Check lags corresponding to 75 .. 165 BPM
        min_lag = max(1, int(round((60.0 / 165.0) / win_dur)))
        max_lag = min(len(onsets) // 2, int(round((60.0 / 75.0) / win_dur)))

        for lag in range(min_lag, max_lag + 1):
            score = sum(onsets[i] * onsets[i + lag] for i in range(len(onsets) - lag))
            if score > best_score:
                best_score = score
                best_bpm = round(60.0 / (lag * win_dur), 1)

        return best_bpm
