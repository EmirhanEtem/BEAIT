"""Manual user intervention detection and safety interruption.

Prevents automation from fighting the user or misdirecting inputs when the user
moves the mouse, switches active windows, or presses the global STOP button.
"""

from __future__ import annotations

import asyncio
import ctypes
from ctypes import wintypes
import logging
import math
import os
from dataclasses import dataclass
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class POINT(ctypes.Structure):
    _fields_ = [
        ("x", wintypes.LONG),
        ("y", wintypes.LONG),
    ]


class UserInterventionError(RuntimeError):
    """Raised when manual user action preempts or interrupts automation."""
    def __init__(self, message: str, reason: str = "manual_mouse_movement"):
        super().__init__(message)
        self.reason = reason


@dataclass
class CursorPosition:
    x: int
    y: int


class InterventionDetector:
    """Detects manual mouse movements, unexpected window changes, and user stops."""

    def __init__(
        self,
        motion_threshold_pixels: float = 20.0,
        expected_hwnd: Optional[int] = None,
    ):
        self.threshold = motion_threshold_pixels
        self.expected_hwnd = expected_hwnd
        self._user32 = getattr(ctypes.windll, "user32", None)
        self._last_cursor: Optional[CursorPosition] = None
        self._automation_target_cursor: Optional[CursorPosition] = None

    def get_physical_cursor(self) -> Optional[CursorPosition]:
        """Read instantaneous physical mouse coordinates from Windows user32."""
        if os.name != "nt" or not self._user32:
            return None

        pt = POINT()
        if self._user32.GetCursorPos(ctypes.byref(pt)):
            return CursorPosition(x=pt.x, y=pt.y)
        return None

    def start_action(self, target_cursor: Optional[Tuple[int, int]] = None):
        """Record cursor position immediately prior to firing an automated action."""
        cur = self.get_physical_cursor()
        self._last_cursor = cur
        if target_cursor:
            self._automation_target_cursor = CursorPosition(x=target_cursor[0], y=target_cursor[1])
        else:
            self._automation_target_cursor = None

    def check_for_intervention(self, cancel_event: Optional[asyncio.Event] = None) -> Tuple[bool, Optional[str]]:
        """Evaluate whether the user intervened or the action was cancelled.

        Returns (is_interrupted, reason).
        """
        # 1. Global STOP event check
        if cancel_event and cancel_event.is_set():
            return True, "User clicked global STOP button"

        # 2. Window focus check
        if self.expected_hwnd and self._user32:
            fg_hwnd = self._user32.GetForegroundWindow()
            if fg_hwnd and fg_hwnd != self.expected_hwnd:
                return True, f"Target window lost focus (active HWND switched to {fg_hwnd})"

        # 3. Mouse drift / user mouse override check
        if self._last_cursor and self._user32:
            cur = self.get_physical_cursor()
            if cur:
                # If we moved cursor by automation, compare to automation target; else compare to last seen
                ref = self._automation_target_cursor or self._last_cursor
                dist = math.hypot(cur.x - ref.x, cur.y - ref.y)
                if dist > self.threshold:
                    logger.warning(
                        "Manual user mouse movement detected! Cursor drifted %.1f px (threshold: %.1f)",
                        dist,
                        self.threshold,
                    )
                    return True, f"User moved mouse cursor by {dist:.1f}px during automation"

        return False, None

    def verify_or_raise(self, cancel_event: Optional[asyncio.Event] = None):
        """Raise UserInterventionError immediately if user intervention occurred."""
        interrupted, reason = self.check_for_intervention(cancel_event=cancel_event)
        if interrupted:
            raise UserInterventionError(
                f"Automation halted safely: {reason}",
                reason=reason or "unknown_intervention",
            )

