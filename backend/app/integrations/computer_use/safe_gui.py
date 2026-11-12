"""Safe GUI Automation Executor and Visual Operation Experience (Phase 5).

Wraps raw HCU (AX + GUI) operations in a strict 7-step safety protocol:
1. Manual intervention & global STOP check
2. Active window & focus verification
3. Stale-target & window drift detection
4. Semantic UI Automation (AX) target discovery first
5. Pre-action screenshot & bounding-box validation before any coordinate fallback
6. Real-time cursor/action marker emission for the companion UI
7. Post-action visual/state verification
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from .adapter import GUIAutomationAdapter, HCUError, ScreenshotResult
from .user_intervention import InterventionDetector, UserInterventionError
from .window_detector import WindowDetector, WindowInfo

logger = logging.getLogger(__name__)


@dataclass
class GUIActionMarker:
    """Visual marker emitted to the companion UI before/during a GUI operation."""
    marker_id: str
    label: str
    target_description: str
    x: int
    y: int
    is_real_desktop: bool = True
    active: bool = True
    method: str = "semantic_uia"  # "semantic_uia" | "coordinate_fallback"


@dataclass
class GUIActionOutcome:
    """Result of a safe GUI operation."""
    success: bool
    verified: bool
    method_used: str  # "semantic_uia", "coordinate_fallback", "aborted", "failed"
    target_description: str
    coordinates: Optional[Tuple[int, int]] = None
    pre_screenshot: Optional[str] = None
    post_screenshot: Optional[str] = None
    error: Optional[str] = None
    interrupted_by_user: bool = False


class SafeGUIError(RuntimeError):
    """Raised when a GUI safety precondition fails (stale target, out-of-bounds, focus loss)."""


class SafeGUIExecutor:
    """Executes GUI actions with strict target validation, focus checks, and intervention guards."""

    def __init__(
        self,
        adapter: Optional[GUIAutomationAdapter] = None,
        window_detector: Optional[WindowDetector] = None,
        intervention_detector: Optional[InterventionDetector] = None,
        marker_callback: Optional[Callable[[GUIActionMarker], Any]] = None,
    ):
        self.adapter = adapter or GUIAutomationAdapter()
        self.window_detector = window_detector or WindowDetector()
        self.intervention_detector = intervention_detector or InterventionDetector()
        self.marker_callback = marker_callback

    async def _emit_marker(
        self,
        label: str,
        target_description: str,
        x: int,
        y: int,
        active: bool = True,
        method: str = "semantic_uia",
        is_real_desktop: bool = True,
    ) -> GUIActionMarker:
        marker = GUIActionMarker(
            marker_id=f"mkr_{uuid.uuid4().hex[:8]}",
            label=label,
            target_description=target_description,
            x=x,
            y=y,
            is_real_desktop=is_real_desktop,
            active=active,
            method=method,
        )
        if self.marker_callback:
            res = self.marker_callback(marker)
            if asyncio.iscoroutine(res):
                await res
        return marker

    def validate_preconditions(
        self,
        target_window: WindowInfo,
        expected_title_part: Optional[str] = None,
        baseline_bounds: Optional[Tuple[int, int, int, int]] = None,
        cancel_event: Optional[asyncio.Event] = None,
        auto_focus: bool = True,
    ) -> WindowInfo:
        """Step 1-3 of Safety Protocol: Check intervention, staleness, and focus."""
        # 1. Check user intervention or global STOP
        self.intervention_detector.verify_or_raise(cancel_event=cancel_event)

        # 2. Check stale target (window closed, hidden, title changed, or drifted)
        if self.window_detector.is_target_stale(
            target_window.hwnd,
            expected_title_part=expected_title_part,
            baseline_bounds=baseline_bounds,
        ):
            raise SafeGUIError(
                f"Target window (HWND={target_window.hwnd}, title={target_window.title!r}) is stale, "
                "closed, or moved beyond safe bounds. Refusing to send blind input."
            )

        # 3. Refresh window info & verify foreground focus
        current_info = self.window_detector.get_window_info(target_window.hwnd)
        if not current_info:
            raise SafeGUIError(f"Could not inspect target window HWND={target_window.hwnd}.")

        if not current_info.is_foreground:
            if auto_focus:
                logger.info("Target window %r not in foreground; attempting bring_to_foreground...", current_info.title)
                self.window_detector.bring_to_foreground(current_info.hwnd)
                current_info = self.window_detector.get_window_info(target_window.hwnd)

            if not current_info or not current_info.is_foreground:
                raise SafeGUIError(
                    f"Target window {target_window.title!r} is not focused in the foreground. "
                    "Aborting GUI action to prevent sending input to the wrong window."
                )

        # Lock expected HWND on the intervention detector
        self.intervention_detector.expected_hwnd = current_info.hwnd
        return current_info

    async def find_semantic_target(
        self,
        query: Dict[str, Any],
        window_ref: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Discover a UI Automation element semantically via HCU AX.find."""
        try:
            res = await self.adapter.async_ax_find(query=query, window_ref=window_ref)
            if res.is_error:
                return None
            data = res.json()
            if isinstance(data, dict):
                matches = data.get("matches") or data.get("elements") or []
                if matches and isinstance(matches, list):
                    return matches[0]
                if data.get("ref") or data.get("id"):
                    return data
            elif isinstance(data, list) and len(data) > 0:
                return data[0]
        except Exception as e:
            logger.debug("Semantic target discovery failed for %s: %s", query, e)
        return None

    async def safe_click(
        self,
        target_window: WindowInfo,
        target_description: str,
        *,
        semantic_query: Optional[Dict[str, Any]] = None,
        window_ref: Optional[str] = None,
        fallback_coords: Optional[Tuple[int, int]] = None,
        expected_title_part: Optional[str] = None,
        baseline_bounds: Optional[Tuple[int, int, int, int]] = None,
        cancel_event: Optional[asyncio.Event] = None,
        requires_confirmation: bool = False,
        user_confirmed: bool = False,
    ) -> GUIActionOutcome:
        """Execute a safe click: Semantic UIA first; coordinate fallback only after screenshot & bounds validation."""
        if requires_confirmation and not user_confirmed:
            return GUIActionOutcome(
                success=False,
                verified=False,
                method_used="aborted",
                target_description=target_description,
                error="Action requires explicit user confirmation before execution.",
            )

        try:
            # Pre-flight validation
            live_win = self.validate_preconditions(
                target_window,
                expected_title_part=expected_title_part,
                baseline_bounds=baseline_bounds,
                cancel_event=cancel_event,
            )

            # 1. Try Semantic UI Automation first
            if semantic_query:
                elem = await self.find_semantic_target(semantic_query, window_ref=window_ref)
                if elem:
                    elem_ref = elem.get("ref") or elem.get("id")
                    bx = int(elem.get("x", live_win.left + live_win.width // 2))
                    by = int(elem.get("y", live_win.top + live_win.height // 2))

                    await self._emit_marker(
                        label=f"Click: {target_description}",
                        target_description=target_description,
                        x=bx,
                        y=by,
                        method="semantic_uia",
                    )
                    self.intervention_detector.start_action(target_cursor=(bx, by))

                    act_res = await self.adapter.async_ax_act(
                        [{"type": "click", "target": elem_ref}],
                        window_ref=window_ref,
                    )
                    self.intervention_detector.verify_or_raise(cancel_event=cancel_event)
                    await self._emit_marker(label=target_description, target_description=target_description, x=bx, y=by, active=False)

                    if not act_res.is_error:
                        post_shot = await self.adapter.async_capture_screenshot()
                        return GUIActionOutcome(
                            success=True,
                            verified=True,
                            method_used="semantic_uia",
                            target_description=target_description,
                            coordinates=(bx, by),
                            post_screenshot=post_shot.path if post_shot.success else None,
                        )

            # 2. Coordinate Fallback (Strict Validation Required!)
            if fallback_coords is None:
                return GUIActionOutcome(
                    success=False,
                    verified=False,
                    method_used="failed",
                    target_description=target_description,
                    error="Semantic UIA target not found and no coordinate fallback was provided.",
                )

            fx, fy = fallback_coords

            # Verify coordinates lie strictly inside the live target window bounds
            if not live_win.contains_point(fx, fy):
                raise SafeGUIError(
                    f"Coordinate fallback ({fx}, {fy}) is outside target window bounds "
                    f"({live_win.left}, {live_win.top}, {live_win.right}, {live_win.bottom})."
                )

            # Mandatory pre-action screenshot validation before coordinate click
            pre_shot = await self.adapter.async_capture_screenshot()
            if not pre_shot.success or not pre_shot.path:
                raise SafeGUIError(
                    f"Cannot execute coordinate fallback without a valid pre-action screenshot: {pre_shot.error}"
                )

            if pre_shot.width and pre_shot.height:
                if not (0 <= fx < pre_shot.width and 0 <= fy < pre_shot.height):
                    raise SafeGUIError(
                        f"Coordinates ({fx}, {fy}) exceed captured screen dimensions ({pre_shot.width}x{pre_shot.height})."
                    )

            # Re-check preconditions right before clicking
            self.validate_preconditions(
                live_win,
                expected_title_part=expected_title_part,
                baseline_bounds=(live_win.left, live_win.top, live_win.width, live_win.height),
                cancel_event=cancel_event,
            )

            await self._emit_marker(
                label=f"Fallback Click: {target_description}",
                target_description=target_description,
                x=fx,
                y=fy,
                method="coordinate_fallback",
            )
            self.intervention_detector.start_action(target_cursor=(fx, fy))

            gui_res = await self.adapter.async_gui_act([{"type": "click", "x": fx, "y": fy}])
            self.intervention_detector.verify_or_raise(cancel_event=cancel_event)
            await self._emit_marker(label=target_description, target_description=target_description, x=fx, y=fy, active=False)

            if gui_res.is_error:
                return GUIActionOutcome(
                    success=False,
                    verified=False,
                    method_used="coordinate_fallback",
                    target_description=target_description,
                    coordinates=(fx, fy),
                    pre_screenshot=pre_shot.path,
                    error=gui_res.text[:300],
                )

            post_shot = await self.adapter.async_capture_screenshot()
            return GUIActionOutcome(
                success=True,
                verified=post_shot.success,
                method_used="coordinate_fallback",
                target_description=target_description,
                coordinates=(fx, fy),
                pre_screenshot=pre_shot.path,
                post_screenshot=post_shot.path if post_shot.success else None,
            )

        except UserInterventionError as ie:
            logger.warning("GUI click aborted due to user intervention: %s", ie)
            return GUIActionOutcome(
                success=False,
                verified=False,
                method_used="aborted",
                target_description=target_description,
                error=str(ie),
                interrupted_by_user=True,
            )
        except SafeGUIError as se:
            logger.warning("GUI safety check blocked click on %r: %s", target_description, se)
            return GUIActionOutcome(
                success=False,
                verified=False,
                method_used="failed",
                target_description=target_description,
                error=str(se),
            )
        except Exception as e:
            logger.error("Unexpected error in safe_click: %s", e, exc_info=True)
            return GUIActionOutcome(
                success=False,
                verified=False,
                method_used="failed",
                target_description=target_description,
                error=str(e),
            )

    async def safe_type(
        self,
        target_window: WindowInfo,
        text: str,
        target_description: str,
        *,
        semantic_query: Optional[Dict[str, Any]] = None,
        window_ref: Optional[str] = None,
        expected_title_part: Optional[str] = None,
        cancel_event: Optional[asyncio.Event] = None,
    ) -> GUIActionOutcome:
        """Safely type or set text in a target control after focus verification."""
        try:
            live_win = self.validate_preconditions(
                target_window,
                expected_title_part=expected_title_part,
                cancel_event=cancel_event,
            )
            cx = live_win.left + live_win.width // 2
            cy = live_win.top + live_win.height // 2

            await self._emit_marker(
                label=f"Type: {target_description}",
                target_description=target_description,
                x=cx,
                y=cy,
                method="semantic_uia",
            )
            self.intervention_detector.start_action()

            if semantic_query:
                elem = await self.find_semantic_target(semantic_query, window_ref=window_ref)
                if elem:
                    elem_ref = elem.get("ref") or elem.get("id")
                    act_res = await self.adapter.async_ax_act(
                        [{"type": "set_value", "target": elem_ref, "value": text}],
                        window_ref=window_ref,
                    )
                    self.intervention_detector.verify_or_raise(cancel_event=cancel_event)
                    await self._emit_marker(label=target_description, target_description=target_description, x=cx, y=cy, active=False)
                    if not act_res.is_error:
                        return GUIActionOutcome(
                            success=True,
                            verified=True,
                            method_used="semantic_uia",
                            target_description=target_description,
                            coordinates=(cx, cy),
                        )

            # Fallback to GUI type on verified foreground window
            gui_res = await self.adapter.async_gui_act([{"type": "type", "text": text}])
            self.intervention_detector.verify_or_raise(cancel_event=cancel_event)
            await self._emit_marker(label=target_description, target_description=target_description, x=cx, y=cy, active=False)

            if gui_res.is_error:
                return GUIActionOutcome(
                    success=False,
                    verified=False,
                    method_used="coordinate_fallback",
                    target_description=target_description,
                    error=gui_res.text[:300],
                )

            return GUIActionOutcome(
                success=True,
                verified=True,
                method_used="coordinate_fallback",
                target_description=target_description,
                coordinates=(cx, cy),
            )

        except UserInterventionError as ie:
            return GUIActionOutcome(
                success=False,
                verified=False,
                method_used="aborted",
                target_description=target_description,
                error=str(ie),
                interrupted_by_user=True,
            )
        except Exception as e:
            return GUIActionOutcome(
                success=False,
                verified=False,
                method_used="failed",
                target_description=target_description,
                error=str(e),
            )

    async def safe_hotkey(
        self,
        target_window: WindowInfo,
        keys: List[str],
        target_description: str,
        *,
        expected_title_part: Optional[str] = None,
        cancel_event: Optional[asyncio.Event] = None,
        requires_confirmation: bool = False,
        user_confirmed: bool = False,
    ) -> GUIActionOutcome:
        """Safely send a keyboard shortcut only when the target window is verified in foreground."""
        if requires_confirmation and not user_confirmed:
            return GUIActionOutcome(
                success=False,
                verified=False,
                method_used="aborted",
                target_description=target_description,
                error="Shortcut requires explicit user confirmation.",
            )

        try:
            live_win = self.validate_preconditions(
                target_window,
                expected_title_part=expected_title_part,
                cancel_event=cancel_event,
            )
            cx = live_win.left + live_win.width // 2
            cy = live_win.top + live_win.height // 2

            await self._emit_marker(
                label=f"Shortcut ({'+'.join(keys)}): {target_description}",
                target_description=target_description,
                x=cx,
                y=cy,
                method="semantic_uia",
            )
            self.intervention_detector.start_action()

            gui_res = await self.adapter.async_gui_act([{"type": "hotkey", "keys": keys}])
            self.intervention_detector.verify_or_raise(cancel_event=cancel_event)
            await self._emit_marker(label=target_description, target_description=target_description, x=cx, y=cy, active=False)

            if gui_res.is_error:
                return GUIActionOutcome(
                    success=False,
                    verified=False,
                    method_used="failed",
                    target_description=target_description,
                    error=gui_res.text[:300],
                )

            post_shot = await self.adapter.async_capture_screenshot()
            return GUIActionOutcome(
                success=True,
                verified=True,
                method_used="semantic_uia",
                target_description=target_description,
                coordinates=(cx, cy),
                post_screenshot=post_shot.path if post_shot.success else None,
            )

        except UserInterventionError as ie:
            return GUIActionOutcome(
                success=False,
                verified=False,
                method_used="aborted",
                target_description=target_description,
                error=str(ie),
                interrupted_by_user=True,
            )
        except Exception as e:
            return GUIActionOutcome(
                success=False,
                verified=False,
                method_used="failed",
                target_description=target_description,
                error=str(e),
            )

    async def safe_scroll(
        self,
        target_window: WindowInfo,
        x: int,
        y: int,
        delta: int,
        target_description: str,
        *,
        expected_title_part: Optional[str] = None,
        cancel_event: Optional[asyncio.Event] = None,
    ) -> GUIActionOutcome:
        """Safely scroll inside verified window bounds."""
        try:
            live_win = self.validate_preconditions(
                target_window,
                expected_title_part=expected_title_part,
                cancel_event=cancel_event,
            )
            if not live_win.contains_point(x, y):
                raise SafeGUIError(f"Scroll coordinates ({x}, {y}) outside target window bounds.")

            self.intervention_detector.start_action(target_cursor=(x, y))
            gui_res = await self.adapter.async_gui_act([{"type": "scroll", "x": x, "y": y, "delta": delta}])
            self.intervention_detector.verify_or_raise(cancel_event=cancel_event)

            return GUIActionOutcome(
                success=not gui_res.is_error,
                verified=not gui_res.is_error,
                method_used="coordinate_fallback",
                target_description=target_description,
                coordinates=(x, y),
                error=gui_res.text[:300] if gui_res.is_error else None,
            )
        except UserInterventionError as ie:
            return GUIActionOutcome(
                success=False,
                verified=False,
                method_used="aborted",
                target_description=target_description,
                error=str(ie),
                interrupted_by_user=True,
            )
        except Exception as e:
            return GUIActionOutcome(
                success=False,
                verified=False,
                method_used="failed",
                target_description=target_description,
                error=str(e),
            )

    async def safe_drag(
        self,
        target_window: WindowInfo,
        start_coords: Tuple[int, int],
        end_coords: Tuple[int, int],
        target_description: str,
        *,
        expected_title_part: Optional[str] = None,
        cancel_event: Optional[asyncio.Event] = None,
        requires_confirmation: bool = False,
        user_confirmed: bool = False,
    ) -> GUIActionOutcome:
        """Safely drag between two points strictly inside the validated target window."""
        if requires_confirmation and not user_confirmed:
            return GUIActionOutcome(
                success=False,
                verified=False,
                method_used="aborted",
                target_description=target_description,
                error="Drag operation requires explicit user confirmation.",
            )

        try:
            live_win = self.validate_preconditions(
                target_window,
                expected_title_part=expected_title_part,
                cancel_event=cancel_event,
            )
            sx, sy = start_coords
            ex, ey = end_coords
            if not live_win.contains_point(sx, sy) or not live_win.contains_point(ex, ey):
                raise SafeGUIError("Drag start or end coordinates fall outside target window bounds.")

            pre_shot = await self.adapter.async_capture_screenshot()
            if not pre_shot.success:
                raise SafeGUIError(f"Pre-drag screenshot failed: {pre_shot.error}")

            await self._emit_marker(
                label=f"Drag: {target_description}",
                target_description=target_description,
                x=sx,
                y=sy,
                method="coordinate_fallback",
            )
            self.intervention_detector.start_action(target_cursor=(ex, ey))

            gui_res = await self.adapter.async_gui_act([
                {"type": "drag", "start_x": sx, "start_y": sy, "end_x": ex, "end_y": ey}
            ])
            self.intervention_detector.verify_or_raise(cancel_event=cancel_event)
            await self._emit_marker(label=target_description, target_description=target_description, x=ex, y=ey, active=False)

            post_shot = await self.adapter.async_capture_screenshot()
            return GUIActionOutcome(
                success=not gui_res.is_error,
                verified=post_shot.success and not gui_res.is_error,
                method_used="coordinate_fallback",
                target_description=target_description,
                coordinates=(ex, ey),
                pre_screenshot=pre_shot.path,
                post_screenshot=post_shot.path if post_shot.success else None,
                error=gui_res.text[:300] if gui_res.is_error else None,
            )
        except UserInterventionError as ie:
            return GUIActionOutcome(
                success=False,
                verified=False,
                method_used="aborted",
                target_description=target_description,
                error=str(ie),
                interrupted_by_user=True,
            )
        except Exception as e:
            return GUIActionOutcome(
                success=False,
                verified=False,
                method_used="failed",
                target_description=target_description,
                error=str(e),
            )

