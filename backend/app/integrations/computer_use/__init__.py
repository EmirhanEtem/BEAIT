"""GUI Automation (HCU) integration package."""

from .adapter import GUIAutomationAdapter, HCUError, HCUStatus, ScreenshotResult, ToolResult
from .window_detector import WindowDetector, WindowInfo
from .user_intervention import CursorPosition, InterventionDetector, UserInterventionError
from .safe_gui import GUIActionMarker, GUIActionOutcome, SafeGUIError, SafeGUIExecutor

__all__ = [
    "GUIAutomationAdapter",
    "HCUError",
    "HCUStatus",
    "ScreenshotResult",
    "ToolResult",
    "WindowDetector",
    "WindowInfo",
    "CursorPosition",
    "InterventionDetector",
    "UserInterventionError",
    "GUIActionMarker",
    "GUIActionOutcome",
    "SafeGUIError",
    "SafeGUIExecutor",
]
