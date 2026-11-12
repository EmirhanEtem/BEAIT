"""Sample Folder Scanner, Metadata Extractor, Categorizer, and Audition Workflow.

Enforces strict directory allowlisting: scanning or auditioning any path outside
explicitly approved user directories raises PermissionError.
"""

from __future__ import annotations

import os
import re
import wave
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

SUPPORTED_AUDIO_EXTENSIONS: Set[str] = {".wav", ".flac", ".ogg", ".mp3", ".aiff", ".aif"}

CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    "kick": ["kick", "bd", "bassdrum", "808_kick", "kck"],
    "snare": ["snare", "snr", "sd", "rim"],
    "clap": ["clap", "clp", "handclap"],
    "hihat": ["hihat", "hat", "hh", "chh", "ohh", "cymbal", "ride", "crash"],
    "bass": ["bass", "sub", "808", "reese", "donk"],
    "synth": ["synth", "lead", "pad", "pluck", "arp", "chord", "stab", "keys"],
    "fx": ["fx", "riser", "downlifter", "impact", "sweep", "noise", "transition"],
    "vocal": ["vocal", "vox", "acapella", "chant", "phrase"],
}


@dataclass
class SampleMetadata:
    """Extracted metadata and musical categorization for an audio sample."""
    path: str
    filename: str
    extension: str
    size_bytes: int
    category: str = "other"
    sample_type: str = "one_shot"  # "one_shot" | "loop"
    duration_seconds: Optional[float] = None
    sample_rate: Optional[int] = None
    channels: Optional[int] = None
    bit_depth: Optional[int] = None
    detected_bpm: Optional[float] = None
    detected_key: Optional[str] = None


@dataclass
class SampleAuditionPreview:
    """Safe preview payload for auditioning an approved audio sample."""
    sample: SampleMetadata
    audition_ready: bool
    recommended_channel_name: str
    notes: str = ""


class SampleScanner:
    """Scans approved sample directories, extracts audio metadata, and categorizes assets."""

    def __init__(self, approved_directories: Optional[List[str]] = None):
        self._approved_dirs: List[str] = []
        self._catalog: List[SampleMetadata] = []
        if approved_directories:
            for d in approved_directories:
                self.add_approved_directory(d)

    @property
    def approved_directories(self) -> List[str]:
        return list(self._approved_dirs)

    def add_approved_directory(self, directory: str) -> str:
        real = os.path.realpath(os.path.abspath(directory))
        if real not in self._approved_dirs:
            self._approved_dirs.append(real)
        return real

    def is_path_approved(self, target_path: str) -> bool:
        """Verify that target_path resides strictly inside an approved directory."""
        if not self._approved_dirs:
            return False
        real_target = os.path.realpath(os.path.abspath(target_path))
        for approved in self._approved_dirs:
            try:
                common = os.path.commonpath([real_target, approved])
                if os.path.normcase(common) == os.path.normcase(approved):
                    return True
            except ValueError:
                # Different drives on Windows
                continue
        return False

    def _require_approval(self, target_path: str) -> str:
        if not self.is_path_approved(target_path):
            raise PermissionError(
                f"Access denied: Path '{target_path}' is outside explicitly approved sample directories."
            )
        return os.path.realpath(os.path.abspath(target_path))

    def scan_directory(
        self,
        directory: str,
        *,
        category_filter: Optional[str] = None,
        max_results: int = 500,
    ) -> List[SampleMetadata]:
        """Recursively scan an approved directory for audio samples."""
        real_dir = self._require_approval(directory)
        if not os.path.isdir(real_dir):
            raise FileNotFoundError(f"Approved sample directory does not exist: {real_dir}")

        results: List[SampleMetadata] = []
        for root, _, files in os.walk(real_dir):
            for fname in sorted(files):
                ext = os.path.splitext(fname)[1].lower()
                if ext not in SUPPORTED_AUDIO_EXTENSIONS:
                    continue

                full_path = os.path.join(root, fname)
                if not self.is_path_approved(full_path):
                    continue

                meta = self.extract_metadata(full_path)
                if category_filter and meta.category != category_filter.lower():
                    continue

                results.append(meta)
                if len(results) >= max_results:
                    break

        self._catalog = list(results)
        return results

    def search(
        self,
        *,
        category: Optional[str] = None,
        sample_type: Optional[str] = None,
        bpm_target: Optional[float] = None,
        bpm_tolerance: float = 5.0,
        key: Optional[str] = None,
    ) -> List[SampleMetadata]:
        """Filter the scanned sample catalog by musical attributes."""
        out: List[SampleMetadata] = []
        for s in self._catalog:
            if category and s.category != category.lower():
                continue
            if sample_type and s.sample_type != sample_type.lower():
                continue
            if bpm_target is not None:
                if s.detected_bpm is None or abs(s.detected_bpm - bpm_target) > bpm_tolerance:
                    continue
            if key and (s.detected_key or "").lower() != key.lower():
                continue
            out.append(s)
        return out

    def extract_metadata(self, file_path: str) -> SampleMetadata:
        """Extract acoustic header metadata and filename tags from a single approved sample."""
        real_path = self._require_approval(file_path)
        fname = os.path.basename(real_path)
        ext = os.path.splitext(fname)[1].lower()
        size = os.path.getsize(real_path) if os.path.exists(real_path) else 0

        category = self._categorize_name(real_path)
        bpm = self._parse_bpm(fname)
        key = self._parse_key(fname)

        duration: Optional[float] = None
        sr: Optional[int] = None
        ch: Optional[int] = None
        bits: Optional[int] = None

        if ext == ".wav" and os.path.exists(real_path):
            try:
                with wave.open(real_path, "rb") as wf:
                    sr = wf.getframerate()
                    ch = wf.getnchannels()
                    bits = wf.getsampwidth() * 8
                    frames = wf.getnframes()
                    if sr and sr > 0:
                        duration = round(frames / float(sr), 3)
            except Exception:
                pass

        # Classify loop vs one-shot
        is_loop = (
            "loop" in fname.lower()
            or (bpm is not None and (duration is None or duration >= 1.5))
            or (duration is not None and duration >= 3.5)
        )
        sample_type = "loop" if is_loop else "one_shot"

        return SampleMetadata(
            path=real_path,
            filename=fname,
            extension=ext,
            size_bytes=size,
            category=category,
            sample_type=sample_type,
            duration_seconds=duration,
            sample_rate=sr,
            channels=ch,
            bit_depth=bits,
            detected_bpm=bpm,
            detected_key=key,
        )

    def prepare_audition(self, file_path: str) -> SampleAuditionPreview:
        """Validate sample for safe auditioning and recommend FL Studio channel naming."""
        meta = self.extract_metadata(file_path)
        exists = os.path.isfile(meta.path) and meta.size_bytes > 44
        rec_name = f"{meta.category.title()} - {os.path.splitext(meta.filename)[0][:20]}"
        notes = (
            f"Ready for audition ({meta.sample_type}, {meta.duration_seconds or 'unknown'}s)"
            if exists
            else "File missing or header incomplete"
        )
        return SampleAuditionPreview(
            sample=meta,
            audition_ready=exists,
            recommended_channel_name=rec_name,
            notes=notes,
        )

    @staticmethod
    def _categorize_name(path: str) -> str:
        lower = path.lower()
        for cat, keywords in CATEGORY_KEYWORDS.items():
            for kw in keywords:
                if re.search(rf"(?:^|[_\-\s\\/]){re.escape(kw)}(?:$|[_\-\s\\/0-9\.])", lower) or kw in os.path.basename(lower):
                    return cat
        return "other"

    @staticmethod
    def _parse_bpm(filename: str) -> Optional[float]:
        m = re.search(r"(\d{2,3}(?:\.\d+)?)\s*bpm", filename, re.IGNORECASE)
        if m:
            val = float(m.group(1))
            if 50.0 <= val <= 220.0:
                return val
        return None

    @staticmethod
    def _parse_key(filename: str) -> Optional[str]:
        m = re.search(r"(?:^|[_\-\s])([A-G][#b]?)\s*(maj|min|m)(?:$|[_\-\s\.])", filename)
        if m:
            root = m.group(1)
            qual = "m" if m.group(2).lower().startswith("m") and m.group(2).lower() != "maj" else "maj"
            return f"{root}{qual}"
        return None
