"""Unit and integration tests for Phase 5: GUI Automation & Safe Visual Operation."""

import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest

from app.integrations.computer_use import (
    CursorPosition,
    GUIActionMarker,
    GUIAutomationAdapter,
    InterventionDetector,
    SafeGUIError,
    SafeGUIExecutor,
    ScreenshotResult,
    ToolResult,
    UserInterventionError,
    WindowDetector,
    WindowInfo,
)


def _make_window(
    hwnd: int = 1001,
    title: str = "FL Studio 2025",
    left: int = 100,
    top: int = 100,
    right: int = 1300,
    bottom: int = 900,
    is_foreground: bool = True,
    is_minimized: bool = False,
) -> WindowInfo:
    return WindowInfo(
        hwnd=hwnd,
        title=title,
        pid=4242,
        left=left,
        top=top,
        right=right,
        bottom=bottom,
        width=right - left,
        height=bottom - top,
        is_foreground=is_foreground,
        is_minimized=is_minimized,
        dpi_scale=1.0,
    )


def test_window_info_contains_point():
    win = _make_window(left=100, top=100, right=500, bottom=400)
    assert win.contains_point(250, 250) is True
    assert win.contains_point(100, 100) is True
    assert win.contains_point(50, 250) is False
    assert win.contains_point(250, 450) is False


def test_stale_target_detection_title_and_drift():
    detector = WindowDetector()
    detector.is_windows = MagicMock(return_value=True)
    detector._user32 = MagicMock()
    detector._user32.IsWindow.return_value = 1
    detector._user32.IsWindowVisible.return_value = 1

    # Case 1: Valid unchanged window
    win = _make_window(hwnd=1001, title="FL Studio 2025 - MyTrack.flp", left=100, top=100, right=1100, bottom=800)
    detector.get_window_info = MagicMock(return_value=win)

    assert detector.is_target_stale(1001, expected_title_part="FL Studio", baseline_bounds=(100, 100, 1000, 700)) is False

    # Case 2: Title changed to a different application
    win_wrong_title = _make_window(hwnd=1001, title="Notepad - Untitled")
    detector.get_window_info = MagicMock(return_value=win_wrong_title)
    assert detector.is_target_stale(1001, expected_title_part="FL Studio") is True

    # Case 3: Window drifted significantly (> 50px)
    win_drifted = _make_window(hwnd=1001, title="FL Studio 2025", left=400, top=400, right=1400, bottom=1100)
    detector.get_window_info = MagicMock(return_value=win_drifted)
    assert detector.is_target_stale(1001, expected_title_part="FL Studio", baseline_bounds=(100, 100, 1000, 700)) is True

    # Case 4: Window closed
    detector._user32.IsWindow.return_value = 0
    assert detector.is_target_stale(1001) is True


@pytest.mark.asyncio
async def test_safe_click_blocks_stale_or_unfocused_window():
    adapter = MagicMock(spec=GUIAutomationAdapter)
    detector = MagicMock(spec=WindowDetector)
    intervention = InterventionDetector()
    intervention.verify_or_raise = MagicMock()

    # Window is stale
    detector.is_target_stale.return_value = True
    executor = SafeGUIExecutor(adapter=adapter, window_detector=detector, intervention_detector=intervention)

    win = _make_window()
    outcome = await executor.safe_click(win, "Channel Rack Button", fallback_coords=(200, 200))
    assert outcome.success is False
    assert outcome.method_used == "failed"
    assert "stale" in (outcome.error or "").lower()

    # Window is not stale, but unfocused and cannot be brought to foreground
    detector.is_target_stale.return_value = False
    unfocused_win = _make_window(is_foreground=False)
    detector.get_window_info.return_value = unfocused_win
    detector.bring_to_foreground.return_value = False

    outcome_unfocused = await executor.safe_click(unfocused_win, "Mixer Slot 1", fallback_coords=(200, 200))
    assert outcome_unfocused.success is False
    assert "not focused" in (outcome_unfocused.error or "").lower()


@pytest.mark.asyncio
async def test_semantic_uia_click_preferred_and_emits_markers():
    adapter = MagicMock(spec=GUIAutomationAdapter)
    detector = MagicMock(spec=WindowDetector)
    intervention = MagicMock(spec=InterventionDetector)

    win = _make_window()
    detector.is_target_stale.return_value = False
    detector.get_window_info.return_value = win

    # Semantic find returns a matching UIA element
    adapter.async_ax_find = AsyncMock(
        return_value=ToolResult(
            is_error=False,
            text='{"matches": [{"ref": "uia_btn_42", "x": 320, "y": 240}]}',
        )
    )
    adapter.async_ax_act = AsyncMock(return_value=ToolResult(is_error=False, text='{"ok": true}'))
    adapter.async_capture_screenshot = AsyncMock(
        return_value=ScreenshotResult(success=True, path="C:/temp/post.png", width=1920, height=1080)
    )

    emitted_markers: list[GUIActionMarker] = []
    executor = SafeGUIExecutor(
        adapter=adapter,
        window_detector=detector,
        intervention_detector=intervention,
        marker_callback=lambda m: emitted_markers.append(m),
    )

    outcome = await executor.safe_click(
        win,
        "Fruity Parametric EQ 2 Slot",
        semantic_query={"name": "Fruity Parametric EQ 2"},
        fallback_coords=(350, 250),
    )

    assert outcome.success is True
    assert outcome.verified is True
    assert outcome.method_used == "semantic_uia"
    assert outcome.coordinates == (320, 240)
    assert len(emitted_markers) == 2
    assert emitted_markers[0].active is True
    assert emitted_markers[0].method == "semantic_uia"
    assert emitted_markers[1].active is False


@pytest.mark.asyncio
async def test_coordinate_fallback_requires_valid_screenshot_and_bounds():
    adapter = MagicMock(spec=GUIAutomationAdapter)
    detector = MagicMock(spec=WindowDetector)
    intervention = MagicMock(spec=InterventionDetector)

    win = _make_window(left=100, top=100, right=800, bottom=600)
    detector.is_target_stale.return_value = False
    detector.get_window_info.return_value = win

    # Semantic UIA finds nothing
    adapter.async_ax_find = AsyncMock(return_value=ToolResult(is_error=False, text="[]"))

    executor = SafeGUIExecutor(adapter=adapter, window_detector=detector, intervention_detector=intervention)

    # 1. Coordinates outside window bounds -> rejected immediately without clicking
    out_of_bounds = await executor.safe_click(
        win,
        "Outside Button",
        semantic_query={"name": "Missing"},
        fallback_coords=(950, 700),
    )
    assert out_of_bounds.success is False
    assert "outside target window bounds" in (out_of_bounds.error or "").lower()

    # 2. Coordinates inside bounds, but pre-action screenshot fails -> rejected
    adapter.async_capture_screenshot = AsyncMock(
        return_value=ScreenshotResult(success=False, error="Display capture unavailable")
    )
    no_shot = await executor.safe_click(
        win,
        "Plugin Preset Next",
        semantic_query={"name": "Missing"},
        fallback_coords=(400, 300),
    )
    assert no_shot.success is False
    assert "screenshot" in (no_shot.error or "").lower()

    # 3. Coordinates inside bounds AND valid pre-action screenshot -> succeeds
    adapter.async_capture_screenshot = AsyncMock(
        return_value=ScreenshotResult(success=True, path="C:/temp/valid.png", width=1920, height=1080)
    )
    adapter.async_gui_act = AsyncMock(return_value=ToolResult(is_error=False, text='{"ok": true}'))

    valid_fallback = await executor.safe_click(
        win,
        "Plugin Preset Next",
        semantic_query={"name": "Missing"},
        fallback_coords=(400, 300),
    )
    assert valid_fallback.success is True
    assert valid_fallback.verified is True
    assert valid_fallback.method_used == "coordinate_fallback"
    assert valid_fallback.coordinates == (400, 300)


@pytest.mark.asyncio
async def test_manual_user_mouse_intervention_aborts_sequence():
    detector = InterventionDetector(motion_threshold_pixels=15.0)
    detector._user32 = MagicMock()

    # Start at (300, 300), then simulate user moving mouse to (600, 600)
    positions = [CursorPosition(300, 300), CursorPosition(600, 600)]
    detector.get_physical_cursor = MagicMock(side_effect=positions)

    detector.start_action(target_cursor=(300, 300))
    interrupted, reason = detector.check_for_intervention()
    assert interrupted is True
    assert "moved mouse cursor" in (reason or "").lower()

    # Verify SafeGUIExecutor aborts cleanly when intervention triggers
    adapter = MagicMock(spec=GUIAutomationAdapter)
    win_det = MagicMock(spec=WindowDetector)
    win_det.is_target_stale.return_value = False
    win_det.get_window_info.return_value = _make_window()

    failing_intervention = MagicMock(spec=InterventionDetector)
    failing_intervention.verify_or_raise.side_effect = UserInterventionError("User moved mouse!")

    executor = SafeGUIExecutor(adapter=adapter, window_detector=win_det, intervention_detector=failing_intervention)
    outcome = await executor.safe_click(_make_window(), "Some Button", fallback_coords=(200, 200))
    assert outcome.success is False
    assert outcome.interrupted_by_user is True
    assert outcome.method_used == "aborted"


@pytest.mark.asyncio
async def test_global_stop_button_cancels_gui_action():
    detector = InterventionDetector()
    cancel_event = asyncio.Event()
    cancel_event.set()

    with pytest.raises(UserInterventionError) as exc_info:
        detector.verify_or_raise(cancel_event=cancel_event)
    assert "stop button" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_explicit_user_confirmation_for_risky_ui_ops():
    executor = SafeGUIExecutor()
    win = _make_window()

    # Unconfirmed risky click is blocked
    unconfirmed = await executor.safe_click(
        win,
        "Overwrite Project File",
        fallback_coords=(250, 250),
        requires_confirmation=True,
        user_confirmed=False,
    )
    assert unconfirmed.success is False
    assert unconfirmed.method_used == "aborted"
    assert "confirmation" in (unconfirmed.error or "").lower()

    # Unconfirmed risky hotkey is blocked
    unconfirmed_key = await executor.safe_hotkey(
        win,
        ["ctrl", "n"],
        "New Project Shortcut",
        requires_confirmation=True,
        user_confirmed=False,
    )
    assert unconfirmed_key.success is False
    assert unconfirmed_key.method_used == "aborted"


@pytest.mark.asyncio
async def test_safe_type_hotkey_and_drag():
    adapter = MagicMock(spec=GUIAutomationAdapter)
    detector = MagicMock(spec=WindowDetector)
    intervention = MagicMock(spec=InterventionDetector)

    win = _make_window(left=100, top=100, right=1000, bottom=800)
    detector.is_target_stale.return_value = False
    detector.get_window_info.return_value = win

    adapter.async_ax_find = AsyncMock(return_value=ToolResult(is_error=False, text="[]"))
    adapter.async_gui_act = AsyncMock(return_value=ToolResult(is_error=False, text='{"ok": true}'))
    adapter.async_capture_screenshot = AsyncMock(
        return_value=ScreenshotResult(success=True, path="C:/temp/shot.png", width=1920, height=1080)
    )

    executor = SafeGUIExecutor(adapter=adapter, window_detector=detector, intervention_detector=intervention)

    # Safe type
    type_res = await executor.safe_type(win, "Bass Lead", "Rename Channel Input")
    assert type_res.success is True
    assert type_res.verified is True

    # Safe hotkey
    key_res = await executor.safe_hotkey(win, ["F8"], "Open Plugin Picker")
    assert key_res.success is True
    assert key_res.verified is True

    # Safe drag (valid bounds)
    drag_res = await executor.safe_drag(win, (200, 200), (400, 400), "Adjust EQ Band 3")
    assert drag_res.success is True
    assert drag_res.verified is True

    # Safe drag (out of bounds -> blocked)
    bad_drag = await executor.safe_drag(win, (200, 200), (1500, 950), "Drag Outside")
    assert bad_drag.success is False
    assert "outside" in (bad_drag.error or "").lower()

