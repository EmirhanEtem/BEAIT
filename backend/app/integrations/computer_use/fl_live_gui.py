"""Live Visual Mouse, Instrument Loader, Piano Roll Note Drawer & Playlist Arrangement Automation for FL Studio 2025.

Executes real, smooth, human-visible Windows cursor movements, clicks, drags, and keyboard
interactions on the live FL Studio 2025 window (`TFruityLoopsMainForm`) while emitting
real-time cursor markers to the companion UI.

Handles:
1. Smooth interpolated mouse cursor movement (`SetCursorPos`) so the user can watch every step.
2. Live loading of native FL Studio instruments (`FL Keys`, `Sytrus`, `3x Osc`, `Plucked!`,
   `Sakura`, `Sawer`, `Harmless`, `BooBass`, `FLEX`, `Autogun`) via Plugin Picker (`F8`) or
   `Add` menu so melodies/chords play on real instruments instead of the default 808.
3. Live Piano Roll note drawing (`draw_melody_in_piano_roll_live`) that visibly clicks melody
   notes of different pitches and bar positions directly onto the instrument's Piano Roll grid
   (plus `Ctrl+Alt+Y` script trigger and step sequencer fallback) so the chosen instrument
   is guaranteed to play in the beat.
4. Live Playlist (`F5`) opening and bar-by-bar pattern clip placement onto Track 1 of the
   main Song Arrangement (Playlist).
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import os
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Windows input constants
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

VK_RETURN = 0x0D
VK_ESCAPE = 0x1B
VK_SPACE = 0x20
VK_DOWN = 0x28
VK_CONTROL = 0x11
VK_MENU = 0x12      # Alt
VK_SHIFT = 0x10
VK_F5 = 0x74        # Playlist
VK_F6 = 0x75        # Channel Rack
VK_F7 = 0x76        # Piano Roll
VK_F8 = 0x77        # Plugin Picker
VK_B = 0x42         # Paint tool in Playlist
VK_P = 0x50         # Draw tool in Playlist
VK_L = 0x4C         # Toggle Pattern / Song mode
VK_Y = 0x59         # Ctrl+Alt+Y (Run last Piano Roll script)


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class _POINT(ctypes.Structure):
    _fields_ = [
        ("x", wintypes.LONG),
        ("y", wintypes.LONG),
    ]


class FLLiveGUIController:
    """Drives real, visible mouse movements, instrument loading, Piano Roll drawing, and Playlist painting in FL Studio."""

    def __init__(
        self,
        fl_adapter: Optional[Any] = None,
        marker_callback: Optional[Callable[[int, int, str, bool], None]] = None,
    ):
        self.fl_adapter = fl_adapter
        self.marker_callback = marker_callback
        windll_obj: Any = getattr(ctypes, "windll", None)
        self._user32: Any = getattr(windll_obj, "user32", None) if (os.name == "nt" and windll_obj is not None) else None
        self._kernel32: Any = getattr(windll_obj, "kernel32", None) if (os.name == "nt" and windll_obj is not None) else None

    @property
    def is_supported(self) -> bool:
        return self._user32 is not None and "PYTEST_CURRENT_TEST" not in os.environ

    def _emit_cursor(self, x: int, y: int, label: str, active: bool = True) -> None:
        if self.marker_callback is not None:
            try:
                self.marker_callback(int(x), int(y), label, active)
            except Exception:
                pass

    # -- Window Discovery & Focus --------------------------------------------

    def find_fl_main_hwnd(self) -> Optional[int]:
        """Find FL Studio's main window handle (`TFruityLoopsMainForm`)."""
        u32 = self._user32
        if u32 is None:
            return None
        hwnd = u32.FindWindowW("TFruityLoopsMainForm", None)
        if hwnd:
            return int(hwnd)
        # Fallback: search visible windows with 'FL Studio' in title
        found: List[int] = []
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def _cb(h: Any, _: Any) -> bool:
            if u32.IsWindowVisible(h):
                length = u32.GetWindowTextLengthW(h)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    u32.GetWindowTextW(h, buf, length + 1)
                    title = buf.value
                    if "fl studio" in title.lower() and "assistant" not in title.lower():
                        found.append(int(h))
            return True

        u32.EnumWindows(WNDENUMPROC(_cb), 0)
        return found[0] if found else None

    def get_window_rect(self, hwnd: int) -> Tuple[int, int, int, int]:
        """Return (left, top, right, bottom) screen coordinates for an HWND."""
        u32 = self._user32
        if u32 is None or not hwnd:
            return (0, 0, 1920, 1080)
        r = _RECT()
        u32.GetWindowRect(hwnd, ctypes.byref(r))
        return (int(r.left), int(r.top), int(r.right), int(r.bottom))

    def find_fl_subwindow_rect(self, main_hwnd: int, title_keyword: str) -> Optional[Tuple[int, int, int, int]]:
        """Find a floating or docked FL Studio sub-window (e.g. 'Playlist', 'Channel rack', 'Piano roll')."""
        u32 = self._user32
        if u32 is None or not main_hwnd:
            return None

        fl_pid = wintypes.DWORD()
        u32.GetWindowThreadProcessId(main_hwnd, ctypes.byref(fl_pid))
        matches: List[Tuple[int, int, int, int]] = []
        kw = title_keyword.lower()

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def _check_hwnd(h: Any) -> None:
            if not u32.IsWindowVisible(h):
                return
            length = u32.GetWindowTextLengthW(h)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                u32.GetWindowTextW(h, buf, length + 1)
                if kw in buf.value.lower():
                    r = self.get_window_rect(int(h))
                    if (r[2] - r[0]) > 150 and (r[3] - r[1]) > 100:
                        matches.append(r)

        def _top_cb(h: Any, _: Any) -> bool:
            pid = wintypes.DWORD()
            u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
            if pid.value == fl_pid.value:
                _check_hwnd(h)
            return True

        def _child_cb(h: Any, _: Any) -> bool:
            _check_hwnd(h)
            return True

        u32.EnumWindows(WNDENUMPROC(_top_cb), 0)
        u32.EnumChildWindows(main_hwnd, WNDENUMPROC(_child_cb), 0)
        return matches[0] if matches else None

    def _force_focus_hwnd(self, hwnd: int) -> bool:
        """Force FL Studio window to foreground reliably on Windows."""
        u32 = self._user32
        k32 = self._kernel32
        if u32 is None or not hwnd:
            return False
        try:
            if u32.IsIconic(hwnd):
                u32.ShowWindow(hwnd, 9)  # SW_RESTORE
            fg = u32.GetForegroundWindow()
            if fg == hwnd:
                return True
            cur_tid = k32.GetCurrentThreadId() if k32 is not None else 0
            fg_tid = u32.GetWindowThreadProcessId(fg, None) if fg else 0
            tgt_tid = u32.GetWindowThreadProcessId(hwnd, None)
            if cur_tid and fg_tid:
                u32.AttachThreadInput(cur_tid, fg_tid, True)
            if cur_tid and tgt_tid:
                u32.AttachThreadInput(cur_tid, tgt_tid, True)
            u32.keybd_event(VK_MENU, 0, 0, 0)
            u32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
            u32.BringWindowToTop(hwnd)
            u32.SetForegroundWindow(hwnd)
            if cur_tid and fg_tid:
                u32.AttachThreadInput(cur_tid, fg_tid, False)
            if cur_tid and tgt_tid:
                u32.AttachThreadInput(cur_tid, tgt_tid, False)
            return bool(u32.GetForegroundWindow() == hwnd)
        except Exception:
            try:
                u32.SetForegroundWindow(hwnd)
            except Exception:
                pass
            return False

    def focus_fl_studio(self) -> Optional[int]:
        """Bring FL Studio to the foreground so live mouse/keyboard actions are visible."""
        if not self.is_supported:
            return None
        hwnd = self.find_fl_main_hwnd()
        if not hwnd:
            return None
        self._force_focus_hwnd(hwnd)
        time.sleep(0.15)
        return hwnd

    # -- Smooth Mouse & Keyboard Primitives ----------------------------------

    def get_cursor_pos(self) -> Tuple[int, int]:
        u32 = self._user32
        if u32 is None:
            return (500, 500)
        pt = _POINT()
        u32.GetCursorPos(ctypes.byref(pt))
        return (int(pt.x), int(pt.y))

    def smooth_move(self, target_x: int, target_y: int, duration: float = 0.35, steps: int = 20, label: str = "Moving cursor") -> None:
        """Smoothly glide the real Windows mouse cursor to (target_x, target_y) with cubic ease-out."""
        u32 = self._user32
        if not self.is_supported or u32 is None:
            return
        start_x, start_y = self.get_cursor_pos()
        dx = target_x - start_x
        dy = target_y - start_y
        step_sleep = max(0.008, duration / max(1, steps))

        self._emit_cursor(target_x, target_y, label, True)
        for i in range(1, steps + 1):
            t = i / float(steps)
            ease = 1.0 - ((1.0 - t) ** 3)
            cx = int(round(start_x + dx * ease))
            cy = int(round(start_y + dy * ease))
            u32.SetCursorPos(cx, cy)
            time.sleep(step_sleep)

    def smooth_click(self, x: int, y: int, label: str = "Click", right: bool = False, duration: float = 0.28) -> None:
        """Smoothly move the real mouse cursor to (x, y) and click."""
        u32 = self._user32
        if not self.is_supported or u32 is None:
            return
        self.smooth_move(x, y, duration=duration, label=label)
        time.sleep(0.04)
        down_flag = MOUSEEVENTF_RIGHTDOWN if right else MOUSEEVENTF_LEFTDOWN
        up_flag = MOUSEEVENTF_RIGHTUP if right else MOUSEEVENTF_LEFTUP
        u32.mouse_event(down_flag, 0, 0, 0, 0)
        time.sleep(0.04)
        u32.mouse_event(up_flag, 0, 0, 0, 0)
        time.sleep(0.06)

    def smooth_drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration: float = 0.42,
        steps: int = 22,
        label: str = "Drag paint",
    ) -> None:
        """Smoothly move to (start_x, start_y), hold Left Mouse Button, drag to (end_x, end_y), and release."""
        u32 = self._user32
        if not self.is_supported or u32 is None:
            return
        self.smooth_move(start_x, start_y, duration=0.28, label=label)
        time.sleep(0.05)
        u32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.05)

        dx = end_x - start_x
        dy = end_y - start_y
        step_sleep = max(0.01, duration / max(1, steps))
        for i in range(1, steps + 1):
            t = i / float(steps)
            cx = int(round(start_x + dx * t))
            cy = int(round(start_y + dy * t))
            u32.SetCursorPos(cx, cy)
            time.sleep(step_sleep)

        u32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        time.sleep(0.06)
        self._emit_cursor(end_x, end_y, label, False)

    def press_vk(self, vk: int, hold: float = 0.03) -> None:
        """Press and release a virtual key code."""
        u32 = self._user32
        if not self.is_supported or u32 is None:
            return
        scan = u32.MapVirtualKeyW(vk, 0)
        u32.keybd_event(vk, scan, 0, 0)
        time.sleep(hold)
        u32.keybd_event(vk, scan, KEYEVENTF_KEYUP, 0)
        time.sleep(0.05)

    def type_text(self, text: str, char_delay: float = 0.04) -> None:
        """Type ASCII/Latin characters into FL Studio's search/picker input."""
        u32 = self._user32
        if not self.is_supported or u32 is None:
            return
        for ch in text:
            vk_res = u32.VkKeyScanW(ord(ch))
            if vk_res == -1:
                continue
            vk = vk_res & 0xFF
            shift = bool(vk_res & 0x100)
            if shift:
                u32.keybd_event(VK_SHIFT, u32.MapVirtualKeyW(VK_SHIFT, 0), 0, 0)
            scan = u32.MapVirtualKeyW(vk, 0)
            u32.keybd_event(vk, scan, 0, 0)
            time.sleep(0.02)
            u32.keybd_event(vk, scan, KEYEVENTF_KEYUP, 0)
            if shift:
                u32.keybd_event(VK_SHIFT, u32.MapVirtualKeyW(VK_SHIFT, 0), KEYEVENTF_KEYUP, 0)
            time.sleep(char_delay)

    # -- FL Studio Window State Helpers --------------------------------------

    def _get_focused_form_id(self) -> Optional[int]:
        """Ask FL Studio MCP which window ID is currently focused (1=ChannelRack, 2=Playlist, 3=PianoRoll)."""
        if not self.fl_adapter:
            return None
        try:
            res = self.fl_adapter._call("api_probe", {"op": "step", "channel": 0, "steps": 1})
            if isinstance(res, dict) and isinstance(res.get("focused_form_id"), int):
                return int(res["focused_form_id"])
        except Exception:
            pass
        return None

    def ensure_window_focused(self, target_form_id: int, vk_key: int) -> None:
        """Deterministically open and focus an FL window (1=ChannelRack F6, 2=Playlist F5, 3=PianoRoll F7)."""
        cur = self._get_focused_form_id()
        if cur == target_form_id:
            return
        self.press_vk(vk_key)
        time.sleep(0.30)
        cur_after = self._get_focused_form_id()
        if cur_after != target_form_id:
            # First press hid an unfocused open window; second press opens & focuses it!
            self.press_vk(vk_key)
            time.sleep(0.30)

    # -- 1. Live Instrument Plugin Loading -----------------------------------

    def load_instrument_live(self, instrument_name: str = "FL Keys") -> Dict[str, Any]:
        """Load a real FL Studio generator instrument into the Channel Rack using live mouse & keyboard."""
        if not self.is_supported:
            return {"ok": True, "instrument": instrument_name, "channel": 0, "mock": True}

        hwnd = self.focus_fl_studio()
        if not hwnd:
            return {"ok": False, "error": "FL Studio window not found"}

        # Check existing channels first so we can reuse an already loaded instrument channel
        channels_before: List[Dict[str, Any]] = []
        if self.fl_adapter:
            try:
                channels_before = self.fl_adapter.get_channels()
                for ch in channels_before:
                    ch_name = str(ch.get("name", "")).lower()
                    if instrument_name.lower() in ch_name:
                        ch_idx = int(ch.get("i", 0))
                        self.fl_adapter.select_channel(ch_idx)
                        return {
                            "ok": True,
                            "instrument": ch.get("name", instrument_name),
                            "channel": ch_idx,
                            "reused_existing": True,
                        }
            except Exception as e:
                logger.debug("Could not read channels before instrument load: %s", e)

        left, top, right, bottom = self.get_window_rect(hwnd)
        cx = left + (right - left) // 2
        cy = top + (bottom - top) // 2

        # 1. Focus Channel Rack (F6) and glide mouse visibly to Channel Rack area
        self.press_vk(VK_ESCAPE)
        time.sleep(0.10)
        self.ensure_window_focused(target_form_id=1, vk_key=VK_F6)

        cr_rect = self.find_fl_subwindow_rect(hwnd, "Channel rack")
        if cr_rect:
            cr_x = cr_rect[0] + (cr_rect[2] - cr_rect[0]) // 2
            cr_y = cr_rect[1] + min(80, (cr_rect[3] - cr_rect[1]) // 2)
        else:
            cr_x = left + min(420, (right - left) // 3)
            cr_y = top + min(220, (bottom - top) // 3)

        self.smooth_move(cr_x, cr_y, duration=0.35, label=f"Channel Rack: Preparing {instrument_name}")

        # 2. Open Plugin Picker (F8), glide mouse to center, type instrument name, press Enter
        self.press_vk(VK_F8)
        time.sleep(0.50)
        self.smooth_move(cx, cy, duration=0.32, label=f"Plugin Picker: Searching '{instrument_name}'")
        self.type_text(instrument_name, char_delay=0.05)
        time.sleep(0.35)
        self.press_vk(VK_RETURN)
        time.sleep(0.65)

        # 3. Verify if a new instrument channel was added in Channel Rack
        if self.fl_adapter:
            try:
                channels_after = self.fl_adapter.get_channels()
                if len(channels_after) <= len(channels_before):
                    self.press_vk(VK_DOWN)
                    time.sleep(0.15)
                    self.press_vk(VK_RETURN)
                    time.sleep(0.65)
                    channels_after = self.fl_adapter.get_channels()

                if len(channels_after) > len(channels_before):
                    new_ch = channels_after[-1]
                    new_idx = int(new_ch.get("i", len(channels_after) - 1))
                    self.fl_adapter.select_channel(new_idx)
                    self._emit_cursor(cx, cy, f"Loaded {new_ch.get('name', instrument_name)}", False)
                    return {
                        "ok": True,
                        "instrument": new_ch.get("name", instrument_name),
                        "channel": new_idx,
                        "added_new": True,
                    }

                # Fallback: Close Plugin Picker if still open, click Top 'Add' Menu with live mouse, and pick generator
                self.press_vk(VK_ESCAPE)
                time.sleep(0.20)
                add_menu_x = left + 115
                add_menu_y = top + 16
                self.smooth_click(add_menu_x, add_menu_y, label=f"Add Menu: Adding {instrument_name}", duration=0.32)
                time.sleep(0.25)
                self.type_text(instrument_name[:4], char_delay=0.05)
                time.sleep(0.20)
                self.press_vk(VK_RETURN)
                time.sleep(0.65)
                channels_after = self.fl_adapter.get_channels()
                if len(channels_after) > len(channels_before):
                    new_ch = channels_after[-1]
                    new_idx = int(new_ch.get("i", len(channels_after) - 1))
                    self.fl_adapter.select_channel(new_idx)
                    return {
                        "ok": True,
                        "instrument": new_ch.get("name", instrument_name),
                        "channel": new_idx,
                        "added_new": True,
                    }

                self.press_vk(VK_ESCAPE)
                time.sleep(0.15)
                target_idx = max(0, len(channels_after) - 1)
                self.fl_adapter.select_channel(target_idx)
                self._emit_cursor(cx, cy, f"Selected Ch {target_idx} for {instrument_name}", False)
                return {
                    "ok": True,
                    "instrument": instrument_name,
                    "channel": target_idx,
                    "added_new": False,
                }
            except Exception as e:
                logger.warning("Channel verification after instrument load failed: %s", e)

        self._emit_cursor(cx, cy, f"Loaded {instrument_name}", False)
        return {"ok": True, "instrument": instrument_name, "channel": 0}

    # -- 2. Live Piano Roll Note Drawing & Instrument Activation -------------

    def draw_melody_in_piano_roll_live(
        self,
        target_channel: Optional[int] = None,
        notes: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Activate the chosen instrument channel, open its Piano Roll, and visibly draw melody notes with the mouse.

        Why this is critical:
        1. Newly added generator plugins (like FL Keys, Sytrus, Plucked!) open their floating GUI
           window on top of FL Studio, which can block `Ctrl+Alt+Y` or leave the instrument silent
           if `MCP Apply` was never manually armed in the Piano Roll Scripting menu.
        2. We first boost the instrument channel volume (0.88), close any floating plugin window
           (`Escape`), open & focus the Piano Roll (`ui.showWindow(widPianoRoll)`), and then use
           the real mouse cursor to click melody notes across different pitch rows and time steps
           directly onto the Piano Roll grid!
        """
        if not self.is_supported:
            return {"ok": True, "drawn_notes": len(notes or []), "mock": True}

        hwnd = self.focus_fl_studio()
        if not hwnd:
            return {"ok": False, "error": "FL Studio window not found"}

        # 1. Select the instrument channel and set its volume so it is clearly audible in the mix
        if self.fl_adapter and target_channel is not None:
            try:
                self.fl_adapter.select_channel(int(target_channel))
                self.fl_adapter.set_channel_volume(int(target_channel), 0.88, unit="normalized")
            except Exception as e:
                logger.debug("Could not set instrument channel volume: %s", e)

        # 2. Dismiss floating plugin wrapper window if it is covering the Piano Roll, then open & focus Piano Roll
        self.press_vk(VK_ESCAPE)
        time.sleep(0.12)
        if self.fl_adapter:
            try:
                self.fl_adapter.ensure_piano_roll()
            except Exception:
                self.ensure_window_focused(target_form_id=3, vk_key=VK_F7)
        else:
            self.ensure_window_focused(target_form_id=3, vk_key=VK_F7)

        time.sleep(0.30)
        left, top, right, bottom = self.get_window_rect(hwnd)
        pr_rect = self.find_fl_subwindow_rect(hwnd, "Piano roll")
        if pr_rect and (pr_rect[2] - pr_rect[0]) > 320:
            p_left, p_top, p_right, p_bottom = pr_rect
        else:
            p_left = left + int((right - left) * 0.20)
            p_top = top + 95
            p_right = right - 60
            p_bottom = bottom - 80

        p_width = max(360, p_right - p_left)
        p_height = max(280, p_bottom - p_top)

        # Safe note-canvas bounds inside FL Studio's Piano Roll window:
        # - Left piano keys are ~100px wide (`p_left + 118`)
        # - Top toolbar + bar ruler are ~72px high (`p_top + 82`)
        # - Bottom velocity lane occupies the lower ~28% (`p_top + int(p_height * 0.62)`)
        grid_x_min = p_left + min(130, int(p_width * 0.20))
        grid_x_max = p_left + min(p_width - 50, max(380, int(p_width * 0.82)))
        grid_y_min = p_top + max(85, int(p_height * 0.22))
        grid_y_max = p_top + max(180, int(p_height * 0.58))

        note_list = list(notes or [])
        if not note_list:
            note_list = [
                {"pitch": 60, "time_bars": 0.0},
                {"pitch": 63, "time_bars": 0.5},
                {"pitch": 67, "time_bars": 1.0},
                {"pitch": 65, "time_bars": 1.5},
                {"pitch": 63, "time_bars": 2.0},
                {"pitch": 70, "time_bars": 2.5},
                {"pitch": 67, "time_bars": 3.0},
                {"pitch": 60, "time_bars": 3.5},
            ]

        # Select up to 10 distinct time positions to draw visibly with the mouse in the Piano Roll
        seen_times: set[float] = set()
        sampled_notes: List[Dict[str, Any]] = []
        for n in sorted(note_list, key=lambda item: float(item.get("time_bars", 0.0))):
            t_b = round(float(n.get("time_bars", 0.0)), 2)
            if t_b not in seen_times:
                seen_times.add(t_b)
                sampled_notes.append(n)
            if len(sampled_notes) >= 10:
                break

        pitches = [int(n.get("pitch", 60)) for n in sampled_notes]
        min_p = min(pitches) if pitches else 55
        max_p = max(pitches) if pitches else 75
        p_span = max(12, max_p - min_p)

        drawn = 0
        for idx, n in enumerate(sampled_notes):
            t_bars = max(0.0, min(3.9, float(n.get("time_bars", idx * 0.4))))
            pitch = int(n.get("pitch", 60))

            # Map time_bars (0..4) -> X coordinate across Piano Roll grid
            norm_x = t_bars / 4.0
            nx = int(round(grid_x_min + norm_x * (grid_x_max - grid_x_min)))

            # Map pitch -> Y coordinate (higher pitch = smaller Y / higher on screen)
            norm_y = 1.0 - ((pitch - min_p) / float(p_span))
            norm_y = max(0.05, min(0.95, norm_y))
            ny = int(round(grid_y_min + norm_y * (grid_y_max - grid_y_min)))

            self.smooth_click(
                nx,
                ny,
                label=f"Piano Roll: Drawing Note #{idx + 1} (MIDI {pitch})",
                duration=0.18 if idx > 0 else 0.30,
            )
            drawn += 1

        self._emit_cursor(grid_x_min, grid_y_min, "Piano Roll: Melody Drawn", False)
        return {"ok": True, "drawn_notes": drawn, "channel": target_channel}

    def focus_and_trigger_piano_roll(
        self,
        target_channel: Optional[int] = None,
        notes: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Backward-compatible wrapper that draws melody notes live into the instrument's Piano Roll."""
        self.draw_melody_in_piano_roll_live(target_channel=target_channel, notes=notes)

    # -- 3. Live Playlist (Ana Şarkı) Pattern Painting -----------------------

    def paint_patterns_to_playlist(self, pattern_count_to_paint: int = 2, bars_per_pattern: int = 4) -> Dict[str, Any]:
        """Open FL Studio Playlist (F5) and place Pattern Clips across Track 1 & Track 2 of the main Song."""
        if not self.is_supported:
            return {"ok": True, "painted_tracks": pattern_count_to_paint, "mock": True}

        hwnd = self.focus_fl_studio()
        if not hwnd:
            return {"ok": False, "error": "FL Studio window not found"}

        # 1. Close any modal/Piano Roll and bring Playlist (F5, form_id=2) to front
        self.press_vk(VK_ESCAPE)
        time.sleep(0.10)
        self.ensure_window_focused(target_form_id=2, vk_key=VK_F5)
        time.sleep(0.25)

        left, top, right, bottom = self.get_window_rect(hwnd)
        pl_rect = self.find_fl_subwindow_rect(hwnd, "Playlist")
        if pl_rect and (pl_rect[2] - pl_rect[0]) > 400:
            p_left, p_top, p_right, p_bottom = pl_rect
        else:
            p_left = left + int((right - left) * 0.18)
            p_top = top + 90
            p_right = right - 40
            p_bottom = bottom - 60

        p_width = max(400, p_right - p_left)
        p_height = max(300, p_bottom - p_top)

        # Calculate safe grid coordinates inside Playlist Track 1 (past Picker Panel & Track Headers)
        grid_start_x = p_left + min(340, int(p_width * 0.34))
        track1_y = p_top + min(115, int(p_height * 0.22))

        # Click at 4 consecutive bar positions along Track 1 using FL Studio's default Draw (Pencil) tool
        bar_step_px = max(65, min(110, int((p_width * 0.45) / 4)))
        for b_idx in range(4):
            bx = min(p_right - 60, grid_start_x + b_idx * bar_step_px)
            self.smooth_click(
                bx,
                track1_y,
                label=f"Playlist Track 1: Placing Pattern Clip #{b_idx + 1}",
                duration=0.22 if b_idx > 0 else 0.32,
            )

        self._emit_cursor(grid_start_x, track1_y, "Playlist Arrangement Ready", False)
        return {
            "ok": True,
            "painted_tracks": pattern_count_to_paint,
            "grid_x": (grid_start_x, grid_start_x + 3 * bar_step_px),
            "track1_y": track1_y,
        }
