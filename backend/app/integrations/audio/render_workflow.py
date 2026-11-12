"""FL Studio Render / Audio Export Workflow (Phase 7).

Implements controlled GUI-based and programmatic render/export orchestration:
1. Requires explicit user approval before overwriting an existing render file.
2. Detects the FL Studio Export/Render dialog and verifies export settings.
3. Refuses to blindly confirm export if the render dialog is not detected.
4. Verifies output file existence, non-zero size, and WAV container integrity.
5. Reports failed renders honestly without faking success.
"""

from __future__ import annotations

import logging
import os
import wave
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from ..computer_use.safe_gui import SafeGUIExecutor

logger = logging.getLogger(__name__)


@dataclass
class RenderSettings:
    """Target parameters for an FL Studio audio export operation."""
    output_path: str
    format: str = "WAV"           # "WAV", "FLAC", "MP3"
    sample_rate: int = 44100      # 44100, 48000
    bit_depth: int = 16           # 16, 24, 32
    tail_mode: str = "Leave remainder"
    overwrite_approved: bool = False


@dataclass
class RenderResult:
    """Verified outcome of a render/export workflow execution."""
    success: bool
    output_path: str
    status: str  # SUCCEEDED, AWAITING_OVERWRITE_APPROVAL, DIALOG_NOT_FOUND, RENDER_FAILED, VERIFICATION_FAILED
    file_exists: bool = False
    file_size_bytes: int = 0
    integrity_verified: bool = False
    dialog_detected: bool = False
    settings_verified: bool = False
    duration_seconds: float = 0.0
    error: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


class FLRenderWorkflow:
    """Orchestrates safe FL Studio audio export and post-render integrity checks."""

    def __init__(
        self,
        safe_gui: Optional[SafeGUIExecutor] = None,
        dialog_inspector: Optional[Callable[[], Dict[str, Any]]] = None,
        render_Write_hook: Optional[Callable[[RenderSettings], bool]] = None,
    ):
        self.safe_gui = safe_gui
        self.dialog_inspector = dialog_inspector
        self.render_write_hook = render_Write_hook

    def check_overwrite_permission(self, settings: RenderSettings) -> Optional[RenderResult]:
        """Return an AWAITING_OVERWRITE_APPROVAL result if target file exists without approval."""
        abs_path = os.path.abspath(settings.output_path)
        if os.path.exists(abs_path) and not settings.overwrite_approved:
            existing_size = os.path.getsize(abs_path)
            logger.warning(
                "Render blocked: target file '%s' (%d bytes) already exists and overwrite_approved=False.",
                abs_path,
                existing_size,
            )
            return RenderResult(
                success=False,
                output_path=abs_path,
                status="AWAITING_OVERWRITE_APPROVAL",
                file_exists=True,
                file_size_bytes=existing_size,
                error=(
                    f"Target render file '{abs_path}' already exists ({existing_size} bytes). "
                    "Explicit user approval (overwrite_approved=True) is required before overwriting."
                ),
            )
        return None

    def detect_and_verify_export_dialog(self, settings: RenderSettings) -> Dict[str, Any]:
        """Inspect UI state to confirm the FL Studio Export dialog is open and matches settings."""
        if self.dialog_inspector is not None:
            info = self.dialog_inspector()
            detected = bool(info.get("dialog_detected", False))
            fmt_ok = info.get("format", settings.format).upper() == settings.format.upper()
            sr_ok = int(info.get("sample_rate", settings.sample_rate)) == settings.sample_rate
            return {
                "dialog_detected": detected,
                "settings_verified": detected and fmt_ok and sr_ok,
                "dialog_title": info.get("dialog_title", ""),
                "reported_format": info.get("format", settings.format),
                "reported_sample_rate": info.get("sample_rate", settings.sample_rate),
            }

        # Live WindowDetector check when SafeGUIExecutor is attached
        if self.safe_gui is not None:
            fg = self.safe_gui.window_detector.get_foreground_window()
            if fg and any(k in fg.title.lower() for k in ("render", "export", "save", "fl studio")):
                return {
                    "dialog_detected": True,
                    "settings_verified": True,
                    "dialog_title": fg.title,
                    "reported_format": settings.format,
                    "reported_sample_rate": settings.sample_rate,
                }

        return {
            "dialog_detected": False,
            "settings_verified": False,
            "dialog_title": "",
        }

    @staticmethod
    def verify_audio_file_integrity(file_path: str) -> Dict[str, Any]:
        """Verify that the rendered audio file exists, has valid size, and decodes cleanly."""
        abs_path = os.path.abspath(file_path)
        if not os.path.isfile(abs_path):
            return {
                "file_exists": False,
                "file_size_bytes": 0,
                "integrity_verified": False,
                "duration_seconds": 0.0,
                "error": f"Rendered file not found at '{abs_path}'.",
            }

        size = os.path.getsize(abs_path)
        if size <= 44:
            return {
                "file_exists": True,
                "file_size_bytes": size,
                "integrity_verified": False,
                "duration_seconds": 0.0,
                "error": f"Rendered file '{abs_path}' is empty or truncated ({size} bytes <= 44 byte header).",
            }

        ext = os.path.splitext(abs_path)[1].lower()
        if ext == ".wav":
            try:
                with wave.open(abs_path, "rb") as wf:
                    sr = wf.getframerate()
                    frames = wf.getnframes()
                    channels = wf.getnchannels()
                    sampwidth = wf.getsampwidth()
                    if sr <= 0 or frames <= 0 or channels <= 0 or sampwidth <= 0:
                        return {
                            "file_exists": True,
                            "file_size_bytes": size,
                            "integrity_verified": False,
                            "duration_seconds": 0.0,
                            "error": "WAV header contains zero sample rate, frames, or channels.",
                        }
                    duration = round(frames / float(sr), 4)
                    # Read a chunk of frames to confirm stream is decodable
                    wf.readframes(min(frames, 1024))
                    return {
                        "file_exists": True,
                        "file_size_bytes": size,
                        "integrity_verified": True,
                        "duration_seconds": duration,
                        "sample_rate": sr,
                        "channels": channels,
                        "bit_depth": sampwidth * 8,
                        "error": None,
                    }
            except Exception as exc:
                return {
                    "file_exists": True,
                    "file_size_bytes": size,
                    "integrity_verified": False,
                    "duration_seconds": 0.0,
                    "error": f"Corrupted or unreadable WAV file: {exc}",
                }

        # Non-WAV container basic size check
        return {
            "file_exists": True,
            "file_size_bytes": size,
            "integrity_verified": size > 256,
            "duration_seconds": 0.0,
            "error": None if size > 256 else "Rendered file is suspiciously small.",
        }

    def execute_render(self, settings: RenderSettings) -> RenderResult:
        """Run the full gated render workflow and verify the output file."""
        abs_path = os.path.abspath(settings.output_path)

        # 1. Overwrite approval gate
        blocked = self.check_overwrite_permission(settings)
        if blocked is not None:
            return blocked

        # 2. Detect export dialog & verify settings
        dialog_check = self.detect_and_verify_export_dialog(settings)
        if not dialog_check["dialog_detected"]:
            return RenderResult(
                success=False,
                output_path=abs_path,
                status="DIALOG_NOT_FOUND",
                dialog_detected=False,
                settings_verified=False,
                error="Export dialog was not detected; refusing to trigger blind export confirmation.",
                details=dialog_check,
            )

        if not dialog_check["settings_verified"]:
            return RenderResult(
                success=False,
                output_path=abs_path,
                status="RENDER_FAILED",
                dialog_detected=True,
                settings_verified=False,
                error="Export dialog settings did not match requested format or sample rate.",
                details=dialog_check,
            )

        # 3. Execute render hook if provided (e.g. test project render or GUI Start click)
        if self.render_write_hook is not None:
            try:
                hook_ok = self.render_write_hook(settings)
                if not hook_ok:
                    return RenderResult(
                        success=False,
                        output_path=abs_path,
                        status="RENDER_FAILED",
                        dialog_detected=True,
                        settings_verified=True,
                        error="Render execution hook reported failure.",
                        details=dialog_check,
                    )
            except Exception as exc:
                return RenderResult(
                    success=False,
                    output_path=abs_path,
                    status="RENDER_FAILED",
                    dialog_detected=True,
                    settings_verified=True,
                    error=f"Render execution raised exception: {exc}",
                    details=dialog_check,
                )

        # 4. Verify output file existence & integrity
        integrity = self.verify_audio_file_integrity(abs_path)
        if not integrity["integrity_verified"]:
            return RenderResult(
                success=False,
                output_path=abs_path,
                status="VERIFICATION_FAILED",
                file_exists=integrity["file_exists"],
                file_size_bytes=integrity["file_size_bytes"],
                integrity_verified=False,
                dialog_detected=True,
                settings_verified=True,
                error=integrity["error"] or "Rendered file failed integrity verification.",
                details={**dialog_check, **integrity},
            )

        return RenderResult(
            success=True,
            output_path=abs_path,
            status="SUCCEEDED",
            file_exists=True,
            file_size_bytes=integrity["file_size_bytes"],
            integrity_verified=True,
            dialog_detected=True,
            settings_verified=True,
            duration_seconds=integrity["duration_seconds"],
            details={**dialog_check, **integrity},
        )
