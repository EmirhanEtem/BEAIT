"""Windows active window detection, DPI scaling, and stale-target detection.

Uses standard ctypes user32/shcore APIs to inspect window handles, titles,
processes, bounding rectangles, and display DPI scales safely without external
binary dependencies.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import os
from dataclasses import dataclass
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Windows structures
class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]

class POINT(ctypes.Structure):
    _fields_ = [
        ("x", wintypes.LONG),
        ("y", wintypes.LONG),
    ]


@dataclass
class WindowInfo:
    """Detailed snapshot of a top-level window."""
    hwnd: int
    title: str
    pid: int
    left: int
    top: int
    right: int
    bottom: int
    width: int
    height: int
    is_foreground: bool
    is_minimized: bool
    dpi_scale: float = 1.0

    def contains_point(self, x: int, y: int) -> bool:
        """Check if coordinates fall inside the window's bounding box."""
        return self.left <= x <= self.right and self.top <= y <= self.bottom


class WindowDetector:
    """Inspects and validates foreground and target application windows on Windows."""

    def __init__(self):
        self._user32 = getattr(ctypes.windll, "user32", None)
        self._shcore = getattr(ctypes.windll, "shcore", None)

    def is_windows(self) -> bool:
        return os.name == "nt" and self._user32 is not None

    def get_foreground_window(self) -> Optional[WindowInfo]:
        """Get details for the currently focused foreground window."""
        if not self.is_windows():
            return None

        hwnd = self._user32.GetForegroundWindow()
        if not hwnd:
            return None
        return self.get_window_info(hwnd)

    def get_window_info(self, hwnd: int) -> Optional[WindowInfo]:
        """Extract full metadata for an HWND."""
        if not self.is_windows() or not hwnd:
            return None

        # 1. Window Title
        length = self._user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        self._user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value

        # 2. Process ID
        pid = wintypes.DWORD()
        self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        # 3. Window Bounds
        rect = RECT()
        self._user32.GetWindowRect(hwnd, ctypes.byref(rect))
        w = max(0, rect.right - rect.left)
        h = max(0, rect.bottom - rect.top)

        # 4. State
        fg_hwnd = self._user32.GetForegroundWindow()
        is_fg = (hwnd == fg_hwnd)
        is_min = bool(self._user32.IsIconic(hwnd))

        # 5. DPI Scale
        dpi_scale = self.get_window_dpi_scale(hwnd)

        return WindowInfo(
            hwnd=hwnd,
            title=title,
            pid=pid.value,
            left=rect.left,
            top=rect.top,
            right=rect.right,
            bottom=rect.bottom,
            width=w,
            height=h,
            is_foreground=is_fg,
            is_minimized=is_min,
            dpi_scale=dpi_scale,
        )

    def get_window_dpi_scale(self, hwnd: int) -> float:
        """Read monitor/window DPI scaling factor (e.g. 1.0 for 100%, 1.25 for 125%)."""
        if self._user32 and hasattr(self._user32, "GetDpiForWindow"):
            try:
                dpi = self._user32.GetDpiForWindow(hwnd)
                if dpi > 0:
                    return dpi / 96.0
            except Exception:
                pass
        return 1.0

    def find_windows_by_title(self, substring: str, case_sensitive: bool = False) -> List[WindowInfo]:
        """Enumerate visible top-level windows matching a title substring."""
        if not self.is_windows():
            return []

        results: List[WindowInfo] = []
        target = substring if case_sensitive else substring.lower()

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def enum_cb(hwnd, _):
            if self._user32.IsWindowVisible(hwnd):
                length = self._user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    self._user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value
                    match_title = title if case_sensitive else title.lower()
                    if target in match_title:
                        info = self.get_window_info(hwnd)
                        if info:
                            results.append(info)
            return True

        self._user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
        return results

    def is_target_stale(
        self,
        target_hwnd: int,
        expected_title_part: Optional[str] = None,
        max_position_drift: int = 50,
        baseline_bounds: Optional[tuple[int, int, int, int]] = None,
    ) -> bool:
        """Determines if a target window has become invalid, closed, or moved significantly.

        Returns True if stale / dangerous to click.
        """
        if not self.is_windows():
            return False

        if not self._user32.IsWindow(target_hwnd):
            logger.warning("Target HWND %s is no longer a valid window (closed).", target_hwnd)
            return True

        if not self._user32.IsWindowVisible(target_hwnd):
            logger.warning("Target HWND %s is not visible.", target_hwnd)
            return True

        current = self.get_window_info(target_hwnd)
        if not current or current.is_minimized:
            logger.warning("Target HWND %s cannot be inspected or is minimized.", target_hwnd)
            return True

        if expected_title_part and expected_title_part.lower() not in current.title.lower():
            logger.warning(
                "Target HWND %s title changed from expected %r to %r.",
                target_hwnd,
                expected_title_part,
                current.title,
            )
            return True

        if baseline_bounds:
            b_l, b_t, b_w, b_h = baseline_bounds
            if (
                abs(current.left - b_l) > max_position_drift
                or abs(current.top - b_t) > max_position_drift
                or abs(current.width - b_w) > max_position_drift
                or abs(current.height - b_h) > max_position_drift
            ):
                logger.warning(
                    "Target window drift detected on HWND %s: bounds moved > %d px.",
                    target_hwnd,
                    max_position_drift,
                )
                return True

        return False

    def bring_to_foreground(self, hwnd: int) -> bool:
        """Safely attempt to focus and bring the target window to foreground."""
        if not self.is_windows() or not hwnd:
            return False

        try:
            if self._user32.IsIconic(hwnd):
                # Restore if minimized (SW_RESTORE = 9)
                self._user32.ShowWindow(hwnd, 9)

            self._user32.SetForegroundWindow(hwnd)
            return True
        except Exception as e:
            logger.warning("Failed to bring window %s to foreground: %e", hwnd, e)
            return False

