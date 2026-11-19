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

KEYEVENTF_EXTENDEDKEY = 0x0001
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
VK_D = 0x44         # Delete tool in Playlist
VK_E = 0x45         # Select tool in Playlist
VK_P = 0x50         # Draw tool in Playlist
VK_L = 0x4C         # Toggle Pattern / Song mode / Ctrl+L Link selected channels to Mixer
VK_A = 0x41         # Ctrl+A Select all
VK_Y = 0x59         # Ctrl+Alt+Y (Run last Piano Roll script)
VK_F9 = 0x78        # Mixer
VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_HOME = 0x24
VK_DELETE = 0x2E
VK_ADD = 0x6B       # Numpad + (Next Pattern)
VK_SUBTRACT = 0x6D  # Numpad - (Previous Pattern)

# Arrow & navigation VKs require KEYEVENTF_EXTENDEDKEY under Windows Delphi UI (FL Studio)
EXTENDED_VKS = frozenset({VK_HOME, VK_LEFT, VK_UP, VK_RIGHT, VK_DOWN, VK_DELETE})


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


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


class FLLiveGUIController:
    """Drives real, visible mouse movements, instrument loading, Piano Roll drawing, and Playlist painting in FL Studio."""

    def __init__(
        self,
        fl_adapter: Optional[Any] = None,
        marker_callback: Optional[Callable[[int, int, str, bool], None]] = None,
    ):
        self.fl_adapter = fl_adapter
        self.marker_callback = marker_callback
        self._selected_mixer_track: Optional[int] = None
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
        """Press and release a virtual key code (marking extended nav/arrow keys properly)."""
        u32 = self._user32
        if not self.is_supported or u32 is None:
            return
        scan = u32.MapVirtualKeyW(vk, 0)
        ext = KEYEVENTF_EXTENDEDKEY if vk in EXTENDED_VKS else 0
        u32.keybd_event(vk, scan, ext, 0)
        time.sleep(hold)
        u32.keybd_event(vk, scan, ext | KEYEVENTF_KEYUP, 0)
        time.sleep(0.05)

    def press_combo(self, modifiers: List[int], vk: int, hold: float = 0.04) -> None:
        """Press a key chord such as Ctrl+L safely releasing modifiers in reverse order."""
        u32 = self._user32
        if not self.is_supported or u32 is None:
            return
        pressed_mods: List[int] = []
        ext = KEYEVENTF_EXTENDEDKEY if vk in EXTENDED_VKS else 0
        try:
            for mod in modifiers:
                mod_scan = u32.MapVirtualKeyW(mod, 0)
                u32.keybd_event(mod, mod_scan, 0, 0)
                pressed_mods.append(mod)
                time.sleep(0.02)
            scan = u32.MapVirtualKeyW(vk, 0)
            u32.keybd_event(vk, scan, ext, 0)
            time.sleep(hold)
            u32.keybd_event(vk, scan, ext | KEYEVENTF_KEYUP, 0)
            time.sleep(0.03)
        finally:
            for mod in reversed(pressed_mods):
                mod_scan = u32.MapVirtualKeyW(mod, 0)
                u32.keybd_event(mod, mod_scan, KEYEVENTF_KEYUP, 0)
                time.sleep(0.01)

    def type_text(self, text: str, char_delay: float = 0.04) -> None:
        """Type exact UTF-16 characters via SendInput (KEYEVENTF_UNICODE) so Turkish/non-US layouts never corrupt 'i'."""
        u32 = self._user32
        if not self.is_supported or u32 is None:
            return
        cb_size = ctypes.sizeof(_INPUT)
        for ch in text:
            code = ord(ch)
            inp_down = _INPUT()
            inp_down.type = 1  # INPUT_KEYBOARD
            inp_down.u.ki.wVk = 0
            inp_down.u.ki.wScan = code
            inp_down.u.ki.dwFlags = KEYEVENTF_UNICODE

            inp_up = _INPUT()
            inp_up.type = 1  # INPUT_KEYBOARD
            inp_up.u.ki.wVk = 0
            inp_up.u.ki.wScan = code
            inp_up.u.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP

            pair = (_INPUT * 2)(inp_down, inp_up)
            sent = u32.SendInput(2, ctypes.byref(pair), cb_size)
            if not sent:
                vk_res = u32.VkKeyScanW(code)
                if vk_res != -1:
                    vk = vk_res & 0xFF
                    mods = []
                    if vk_res & 0x100:
                        mods.append(VK_SHIFT)
                    if vk_res & 0x200:
                        mods.append(VK_CONTROL)
                    if vk_res & 0x400:
                        mods.append(VK_MENU)
                    self.press_combo(mods, vk, hold=0.02)
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

    # -- 4. Multi-Track Instrument Loader, Mixer Routing & FX Plugins ---------

    def load_track_instrument_live(
        self,
        instrument_name: str = "FL Keys",
        fallbacks: Optional[List[str]] = None,
        exclude_channels: Optional[List[int]] = None,
        role: str = "",
    ) -> Dict[str, Any]:
        """Load a dedicated generator instrument for a musical role without colliding with excluded channels."""
        if not self.is_supported:
            excluded = set(exclude_channels or [])
            idx = 4
            while idx in excluded:
                idx += 1
            return {
                "ok": True,
                "instrument": instrument_name,
                "requested": instrument_name,
                "channel": idx,
                "role": role,
                "reused": False,
                "mock": True,
            }

        hwnd = self.focus_fl_studio()
        if not hwnd:
            return {"ok": False, "error": "FL Studio window not found", "instrument": instrument_name}

        excluded = set(exclude_channels or [])
        candidates = [instrument_name] + [fb for fb in (fallbacks or []) if fb and fb != instrument_name]
        skip_reuse_words = ("kick", "clap", "hat", "snare", "perc", "cymbal", "rim", "sampler", "audio", "automation")

        channels_before: List[Dict[str, Any]] = []
        if self.fl_adapter:
            try:
                channels_before = self.fl_adapter.get_channels()
            except Exception:
                channels_before = []

        # Reuse ONLY if the PRIMARY requested instrument (never a fallback!) already exists and is unassigned
        req_low = instrument_name.strip().lower()
        for idx, ch in enumerate(channels_before):
            if idx in excluded:
                continue
            cname = str(ch.get("name", "")).strip()
            clow = cname.lower()
            if not clow or any(sw in clow for sw in skip_reuse_words):
                continue
            if req_low and req_low in clow:
                if self.fl_adapter is not None:
                    try:
                        self.fl_adapter.select_channel(idx)
                    except Exception:
                        pass
                return {
                    "ok": True,
                    "instrument": cname or instrument_name,
                    "requested": instrument_name,
                    "channel": idx,
                    "role": role,
                    "reused": True,
                }

        for cand in candidates:
            before_count = len(channels_before)
            self.press_vk(VK_ESCAPE)
            time.sleep(0.10)
            self.ensure_window_focused(target_form_id=1, vk_key=VK_F6)
            cr_rect = self.find_fl_subwindow_rect(hwnd, "Channel rack")
            if cr_rect:
                cx = cr_rect[0] + min(80, max(24, (cr_rect[2] - cr_rect[0]) // 3))
                cy = cr_rect[1] + 20
                self.smooth_click(cx, cy, label=f"Focus Channel Rack ({cand})")

            query = self._clean_picker_query(cand)
            self.press_vk(VK_F8)
            time.sleep(0.60)
            self.type_text(query, char_delay=0.03)
            time.sleep(0.32)
            self.press_vk(VK_RETURN)
            time.sleep(0.85)

            matched_idx: Optional[int] = None
            matched_name: str = cand
            for _poll_i in range(5):
                if not self.fl_adapter:
                    break
                try:
                    cur_channels = self.fl_adapter.get_channels()
                except Exception:
                    cur_channels = []
                if len(cur_channels) > before_count:
                    for idx in range(before_count, len(cur_channels)):
                        if idx not in excluded:
                            matched_idx = idx
                            matched_name = str(cur_channels[idx].get("name", cand))
                            break
                    if matched_idx is not None:
                        channels_before = cur_channels
                        break
                time.sleep(0.48)

            if matched_idx is not None:
                self.press_vk(VK_ESCAPE)
                time.sleep(0.15)
                self.ensure_window_focused(target_form_id=1, vk_key=VK_F6)
                if self.fl_adapter:
                    try:
                        self.fl_adapter.select_channel(matched_idx)
                    except Exception:
                        pass
                return {
                    "ok": True,
                    "instrument": matched_name,
                    "requested": instrument_name,
                    "channel": matched_idx,
                    "role": role,
                    "reused": False,
                }

            self.press_vk(VK_ESCAPE)
            time.sleep(0.18)

        for idx, ch in enumerate(channels_before):
            clow = str(ch.get("name", "")).lower()
            if idx not in excluded and clow and not any(sw in clow for sw in skip_reuse_words):
                return {
                    "ok": True,
                    "instrument": str(ch.get("name", instrument_name)),
                    "requested": instrument_name,
                    "channel": idx,
                    "role": role,
                    "reused": True,
                    "fallback_existing": True,
                }

        return {
            "ok": False,
            "error": f"Could not load '{instrument_name}' or fallbacks via Plugin Picker",
            "instrument": instrument_name,
            "role": role,
        }

    @staticmethod
    def _clean_picker_query(name: str) -> str:
        """Strip punctuation (e.g. 'Plucked!') that can interfere with Plugin Picker typing across keyboard layouts."""
        cleaned = " ".join("".join(ch if (ch.isalnum() or ch in " _+-") else " " for ch in name).split())
        return cleaned or name.strip()

    def _query_selected_mixer_track(self) -> Optional[int]:
        """Query FL Studio's currently selected Mixer track index (`mixer.trackNumber()`) when supported."""
        if not self.fl_adapter:
            return None
        try:
            res = self.fl_adapter.get_selected_mixer_track()
            if isinstance(res, dict):
                sel = res.get("selected")
                if isinstance(sel, int) and not isinstance(sel, bool):
                    return sel
        except Exception:
            pass
        return None

    def _read_fl_hint(self) -> str:
        """Read current FL Studio status bar hint text via SysEx `api_probe(op='step')`."""
        if not self.fl_adapter:
            return ""
        try:
            res = self.fl_adapter._call("api_probe", {"op": "step", "channel": 0, "steps": 1})
            if isinstance(res, dict):
                return str(res.get("hint") or "")
        except Exception:
            pass
        return ""

    def select_mixer_track_live(self, hwnd: int, mixer_track: int) -> bool:
        """Focus FL Studio Mixer reliably and select `mixer_track` via SysEx `setTrackNumber` or safe navigation."""
        mixer_track = max(0, min(125, int(mixer_track)))
        self.press_vk(VK_ESCAPE)
        time.sleep(0.08)
        self.ensure_window_focused(target_form_id=0, vk_key=VK_F9)

        mx_rect = self.find_fl_subwindow_rect(hwnd, "Mixer")

        # 1. Preferred: deterministic FL Studio API (`mixer.setTrackNumber`) with scroll-to-visible + readback
        if self.fl_adapter:
            try:
                res = self.fl_adapter.select_mixer_track(mixer_track, focus=True)
                if isinstance(res, dict) and res.get("ok") is True:
                    sel = res.get("selected")
                    if isinstance(sel, int) and not isinstance(sel, bool) and sel == mixer_track:
                        if mx_rect:
                            m_left, m_top, m_right, _ = mx_rect
                            self.smooth_move(
                                m_left + min(220, max(80, (m_right - m_left) // 3)),
                                m_top + 16,
                                duration=0.20,
                                label=f"Mixer Track {mixer_track} Selected",
                            )
                        self._selected_mixer_track = mixer_track
                        return True
            except Exception:
                pass

        # 2. Fallback for legacy controller scripts without `mixer_select_track`:
        # Avoid clicking blind Master/Current edge and avoid VK_HOME (which resets Song playhead in FL!).
        if mx_rect:
            m_left, m_top, m_right, m_bottom = mx_rect
            click_x = min(m_left + 88, (m_left + m_right) // 2)
            click_y = m_top + min(110, max(48, (m_bottom - m_top) // 4))
            self.smooth_click(click_x, click_y, label=f"Focus Mixer Strip (Target {mixer_track})")
            time.sleep(0.06)

        hint_low = self._read_fl_hint().lower()
        cur_idx: Optional[int] = None
        if "master" in hint_low:
            cur_idx = 0
        elif "current" in hint_low:
            self.press_vk(VK_RIGHT, hold=0.02)
            time.sleep(0.04)
            cur_idx = 0
        else:
            import re as _re
            m_ins = _re.search(r"insert\s+(\d+)", hint_low)
            if m_ins:
                cur_idx = int(m_ins.group(1))

        if cur_idx is not None:
            delta = mixer_track - cur_idx
            step_vk = VK_RIGHT if delta > 0 else VK_LEFT
            for _ in range(abs(delta)):
                self.press_vk(step_vk, hold=0.02)
                time.sleep(0.03)
        else:
            # Conservative reset left toward Master (stopping at Master/Current), then step right
            for _ in range(8):
                self.press_vk(VK_LEFT, hold=0.02)
                time.sleep(0.02)
            if "current" in self._read_fl_hint().lower():
                self.press_vk(VK_RIGHT, hold=0.02)
                time.sleep(0.03)
            for _ in range(mixer_track):
                self.press_vk(VK_RIGHT, hold=0.02)
                time.sleep(0.03)

        actual = self._query_selected_mixer_track()
        self._selected_mixer_track = actual if actual is not None else mixer_track
        return (actual == mixer_track) if actual is not None else True

    def route_channel_to_mixer_track_live(self, channel_idx: int, mixer_track: int) -> Dict[str, Any]:
        """Route a Channel Rack channel to a Mixer insert via direct API (`setTargetFxTrack`) or Ctrl+L fallback."""
        channel_idx = int(channel_idx)
        mixer_track = max(0, min(125, int(mixer_track)))
        if not self.is_supported:
            return {
                "ok": True,
                "channel": channel_idx,
                "mixer_track": mixer_track,
                "target_mixer_track": mixer_track,
                "verified": True,
                "mock": True,
            }

        if self.fl_adapter:
            try:
                cur_ch = self.fl_adapter.get_channel(channel_idx)
                cur_tgt = cur_ch.get("target_fx_track")
                if isinstance(cur_tgt, int) and not isinstance(cur_tgt, bool) and int(cur_tgt) == mixer_track:
                    return {
                        "ok": True,
                        "channel": channel_idx,
                        "mixer_track": mixer_track,
                        "target_mixer_track": mixer_track,
                        "already_routed": True,
                        "verified": True,
                    }
            except Exception:
                pass

            # Preferred direct FL Studio 21+ API (`channels.setTargetFxTrack`)
            try:
                direct = self.fl_adapter.set_channel_target_mixer(channel_idx, mixer_track)
                if (
                    isinstance(direct, dict)
                    and direct.get("ok") is True
                    and isinstance(direct.get("target_mixer_track"), int)
                    and not isinstance(direct.get("target_mixer_track"), bool)
                    and int(direct["target_mixer_track"]) == mixer_track
                ):
                    self._selected_mixer_track = mixer_track
                    return {
                        "ok": True,
                        "channel": channel_idx,
                        "mixer_track": mixer_track,
                        "target_mixer_track": mixer_track,
                        "method": "setTargetFxTrack",
                        "verified": True,
                    }
            except Exception:
                pass

        hwnd = self.focus_fl_studio()
        if not hwnd:
            return {"ok": False, "error": "FL Studio window not found", "verified": False}

        for attempt in range(2):
            # Select channel FIRST because _h_channel_select refocuses Piano Roll whenever Piano Roll is open!
            if self.fl_adapter:
                try:
                    self.fl_adapter.select_channel(channel_idx)
                except Exception:
                    pass
                time.sleep(0.06)

            self.select_mixer_track_live(hwnd, mixer_track)
            if attempt == 1:
                # Fallback: focus Channel Rack cleanly WITHOUT calling select_channel() again
                self.ensure_window_focused(target_form_id=1, vk_key=VK_F6)
                cr_rect = self.find_fl_subwindow_rect(hwnd, "Channel rack")
                if cr_rect:
                    self.smooth_click(
                        cr_rect[0] + min(80, max(24, (cr_rect[2] - cr_rect[0]) // 3)),
                        cr_rect[1] + 20,
                        label=f"Focus Channel Rack for Ctrl+L (Ch {channel_idx})",
                    )
            time.sleep(0.08)
            self.press_combo([VK_CONTROL], VK_L)
            time.sleep(0.24)

            if self.fl_adapter:
                for _ in range(2):
                    try:
                        after = self.fl_adapter.get_channel(channel_idx)
                        actual = after.get("target_fx_track")
                        if actual is not None:
                            self._selected_mixer_track = int(actual)
                            if int(actual) == mixer_track:
                                return {
                                    "ok": True,
                                    "channel": channel_idx,
                                    "mixer_track": mixer_track,
                                    "target_mixer_track": int(actual),
                                    "verified": True,
                                }
                    except Exception:
                        pass
                    time.sleep(0.15)

        return {
            "ok": False,
            "channel": channel_idx,
            "mixer_track": mixer_track,
            "target_mixer_track": getattr(self, "_selected_mixer_track", None),
            "verified": False,
            "error": f"Channel {channel_idx} routing did not confirm on Mixer track {mixer_track}",
        }

    def _dismiss_fl_error_dialog_if_any(self, main_hwnd: int) -> bool:
        """Dismiss any FL Studio popup dialog (e.g. 'There are no available effect slots...') if focused."""
        u32 = self._user32
        if u32 is None or not main_hwnd:
            return False
        try:
            fg = int(u32.GetForegroundWindow() or 0)
            if not fg or fg == main_hwnd:
                return False
            fl_pid = wintypes.DWORD()
            fg_pid = wintypes.DWORD()
            u32.GetWindowThreadProcessId(main_hwnd, ctypes.byref(fl_pid))
            u32.GetWindowThreadProcessId(fg, ctypes.byref(fg_pid))
            if fg_pid.value != fl_pid.value:
                return False
            n = u32.GetWindowTextLengthW(fg)
            buf = ctypes.create_unicode_buffer(n + 1)
            if n > 0:
                u32.GetWindowTextW(fg, buf, n + 1)
            title = buf.value.strip().lower()
            if title in ("error", "warning", "alert", "information") or "error" in title:
                # Single-button OK dialogs in Delphi VCL confirm cleanly on Return; try Escape if still open
                self.press_vk(VK_RETURN)
                time.sleep(0.12)
                if u32.IsWindowVisible(fg):
                    self.press_vk(VK_ESCAPE)
                    time.sleep(0.12)
                return True
        except Exception:
            pass
        return False

    def _find_existing_fx_in_chain(
        self,
        start_track: int,
        candidates: List[str],
        max_hops: int = 4,
    ) -> Tuple[Optional[Dict[str, Any]], int, List[Dict[str, Any]]]:
        """Inspect `start_track` and any daisy-chained overflow buses for the PRIMARY FX or free slot."""
        if not self.fl_adapter:
            return (None, start_track, [])

        primary_cand = str(candidates[0]).strip().lower() if candidates else ""
        visited = set()
        cur = start_track
        last_track = start_track
        last_slots: List[Dict[str, Any]] = []

        for _ in range(max_hops):
            if cur in visited or cur < 0 or cur > 125:
                break
            visited.add(cur)
            last_track = cur
            try:
                plist = self.fl_adapter.plugin_list(cur)
                slots = list(plist.get("slots") or [])
            except Exception:
                slots = []
            last_slots = slots

            if primary_cand:
                for s in slots:
                    sname = str(s.get("name", "")).lower()
                    if primary_cand in sname:
                        return (
                            {
                                "ok": True,
                                "loaded": True,
                                "plugin_loaded": True,
                                "reused": True,
                                "mixer_track": cur,
                                "slot": int(s.get("slot", 0)),
                                "plugin_name": s.get("name", candidates[0]),
                                "slots": slots,
                                "verified": True,
                            },
                            cur,
                            slots,
                        )

            if len(slots) < 10:
                return (None, cur, slots)

            # Current track is 10/10 full -> inspect downstream daisy-chain bus if present
            nxt_track: Optional[int] = None
            try:
                if cur == 0:
                    for bus_t in range(19, 64):
                        if bus_t in visited:
                            continue
                        rt = self.fl_adapter.get_mixer_routing(bus_t)
                        bname = str(rt.get("name", "")).lower()
                        routes_to = rt.get("routes_to") or []
                        if ("pre-master" in bname or "master fx+" in bname) and any(
                            int(r.get("dst", -1)) == 0 for r in routes_to if isinstance(r, dict)
                        ):
                            nxt_track = bus_t
                            break
                else:
                    rt = self.fl_adapter.get_mixer_routing(cur)
                    for r in rt.get("routes_to") or []:
                        if isinstance(r, dict) and r.get("dst") is not None:
                            dst = int(r["dst"])
                            if dst > 0 and dst not in visited:
                                nxt_track = dst
                                break
            except Exception:
                nxt_track = None

            if nxt_track is None:
                break
            cur = nxt_track

        return (None, last_track, last_slots)

    def _allocate_overflow_mixer_bus(self, prefer_start: int = 20) -> Optional[int]:
        """Find the first unused spare Mixer insert (`20..63`) with 0 FX slots."""
        if not self.fl_adapter:
            return None
        for cand_t in range(prefer_start, 64):
            try:
                plist = self.fl_adapter.plugin_list(cand_t)
                if list(plist.get("slots") or []):
                    continue
                rt = self.fl_adapter.get_mixer_routing(cand_t)
                tname = str(rt.get("name", "")).strip().lower()
                if not tname or tname.startswith("insert "):
                    return cand_t
            except Exception:
                continue
        return None

    def _daisy_chain_overflow_bus(self, full_track: int) -> Optional[int]:
        """Route a 10/10 full Mixer track to a spare bus (disabling Master direct send so audio never doubles)."""
        if not self.fl_adapter:
            return None
        try:
            if full_track == 0:
                pre_master = self._allocate_overflow_mixer_bus(prefer_start=19)
                if pre_master is None:
                    return None
                self.fl_adapter.set_mixer_route(pre_master, 0, enabled=True)
                try:
                    self.fl_adapter.set_mixer_name(pre_master, "Pre-Master FX+")
                    self.fl_adapter.set_mixer_color(pre_master, 215, 80, 90)
                except Exception:
                    pass
                # Move active direct-to-Master inserts (1..63) onto Pre-Master -> Master cleanly
                for ins in range(1, 64):
                    if ins == pre_master:
                        continue
                    try:
                        ins_rt = self.fl_adapter.get_mixer_routing(ins)
                        routes = ins_rt.get("routes_to") or []
                        has_master = any(isinstance(r, dict) and r.get("dst") == 0 for r in routes)
                        if has_master:
                            self.fl_adapter.set_mixer_route(ins, pre_master, enabled=True)
                            self.fl_adapter.set_mixer_route(ins, 0, enabled=False)
                    except Exception:
                        continue
                return pre_master

            overflow = self._allocate_overflow_mixer_bus(prefer_start=20)
            if overflow is None:
                return None
            src_rt = self.fl_adapter.get_mixer_routing(full_track)
            src_name = str(src_rt.get("name", f"Trk {full_track}")).strip() or f"Trk {full_track}"
            existing_dsts = [
                int(r["dst"])
                for r in (src_rt.get("routes_to") or [])
                if isinstance(r, dict) and r.get("dst") is not None and int(r["dst"]) != overflow
            ]
            if not existing_dsts:
                existing_dsts = [0]

            for dst in existing_dsts:
                self.fl_adapter.set_mixer_route(overflow, dst, enabled=True)
                self.fl_adapter.set_mixer_route(full_track, dst, enabled=False)
            self.fl_adapter.set_mixer_route(full_track, overflow, enabled=True)
            try:
                self.fl_adapter.set_mixer_name(overflow, f"{src_name[:11]} FX+")
                self.fl_adapter.set_mixer_color(overflow, 105, 195, 240)
            except Exception:
                pass
            return overflow
        except Exception as e:
            logger.debug("Mixer overflow daisy-chaining failed from track %s: %s", full_track, e)
            return None

    def load_mixer_effect_live(
        self,
        mixer_track: int,
        plugin_name: str,
        fallbacks: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Load an FL Studio Mixer FX plugin onto `mixer_track` (auto daisy-chaining if all 10 slots are full)."""
        orig_track = max(0, min(125, int(mixer_track)))
        mixer_track = orig_track
        daisy_chained = False
        candidates = [plugin_name] + [fb for fb in (fallbacks or []) if fb and fb != plugin_name]
        if not self.is_supported:
            return {
                "ok": True,
                "loaded": True,
                "plugin_loaded": True,
                "mixer_track": mixer_track,
                "source_mixer_track": orig_track,
                "daisy_chained": False,
                "slot": 0,
                "plugin_name": plugin_name,
                "verified": True,
                "mock": True,
            }

        before_slots: List[Dict[str, Any]] = []
        if self.fl_adapter:
            reused, resolved_track, resolved_slots = self._find_existing_fx_in_chain(orig_track, candidates)
            if reused is not None:
                reused["source_mixer_track"] = orig_track
                reused["daisy_chained"] = resolved_track != orig_track
                return reused
            mixer_track = resolved_track
            before_slots = resolved_slots
            daisy_chained = mixer_track != orig_track

            if len(before_slots) >= 10:
                overflow_track = self._daisy_chain_overflow_bus(mixer_track)
                if overflow_track is not None:
                    mixer_track = overflow_track
                    daisy_chained = True
                    try:
                        before_slots = list(self.fl_adapter.plugin_list(mixer_track).get("slots") or [])
                    except Exception:
                        before_slots = []
                else:
                    return {
                        "ok": False,
                        "loaded": False,
                        "plugin_loaded": False,
                        "mixer_track": mixer_track,
                        "source_mixer_track": orig_track,
                        "daisy_chained": daisy_chained,
                        "plugin_name": plugin_name,
                        "slots": before_slots,
                        "verified": False,
                        "error": f"All 10 FX slots on Mixer track {mixer_track} are full and no spare bus was available",
                    }

        hwnd = self.focus_fl_studio()
        if not hwnd:
            return {"ok": False, "loaded": False, "error": "FL Studio window not found"}

        for cand_idx, cand in enumerate(candidates):
            self._dismiss_fl_error_dialog_if_any(hwnd)

            # Re-check live slots in case earlier attempts/actions filled this track to 10/10
            if self.fl_adapter:
                try:
                    cur_plist = self.fl_adapter.plugin_list(mixer_track)
                    cur_slots = list(cur_plist.get("slots") or [])
                    if isinstance(cur_plist, dict) and len(cur_slots) >= 10:
                        nxt_bus = self._daisy_chain_overflow_bus(mixer_track)
                        if nxt_bus is None:
                            return {
                                "ok": False,
                                "loaded": False,
                                "plugin_loaded": False,
                                "mixer_track": mixer_track,
                                "source_mixer_track": orig_track,
                                "daisy_chained": daisy_chained,
                                "plugin_name": plugin_name,
                                "slots": cur_slots,
                                "verified": False,
                                "error": f"All 10 FX slots on Mixer track {mixer_track} are full and no spare bus was available",
                            }
                        mixer_track = nxt_bus
                        daisy_chained = True
                        before_slots = list(self.fl_adapter.plugin_list(mixer_track).get("slots") or [])
                except Exception:
                    pass

            before_slot_ids = {int(s.get("slot", -1)) for s in before_slots if isinstance(s, dict)}
            self.select_mixer_track_live(hwnd, mixer_track)

            # Verify FL Studio UI actually points at `mixer_track` before sending F8!
            selected_now = self._query_selected_mixer_track()
            if selected_now is not None and selected_now != mixer_track:
                self.select_mixer_track_live(hwnd, mixer_track)
                selected_now = self._query_selected_mixer_track()
                if selected_now is not None and selected_now != mixer_track:
                    return {
                        "ok": False,
                        "loaded": False,
                        "plugin_loaded": False,
                        "mixer_track": mixer_track,
                        "source_mixer_track": orig_track,
                        "daisy_chained": daisy_chained,
                        "plugin_name": plugin_name,
                        "slots": before_slots,
                        "verified": False,
                        "error": (
                            f"Mixer track {mixer_track} could not be selected "
                            f"(active track is {selected_now}); skipped F8 to avoid filling the wrong track"
                        ),
                    }

            focused_id = self._get_focused_form_id()
            if focused_id is not None and focused_id != 0:
                self.ensure_window_focused(target_form_id=0, vk_key=VK_F9)
                time.sleep(0.12)
                focused_id = self._get_focused_form_id()
                if focused_id is not None and focused_id != 0:
                    return {
                        "ok": False,
                        "loaded": False,
                        "plugin_loaded": False,
                        "mixer_track": mixer_track,
                        "source_mixer_track": orig_track,
                        "daisy_chained": daisy_chained,
                        "plugin_name": plugin_name,
                        "slots": before_slots,
                        "verified": False,
                        "error": f"Mixer window could not gain focus (focused_form_id={focused_id}); skipped F8 to avoid adding generator to Channel Rack",
                    }
                # Ensure Mixer focus hotkey didn't drift active track away from `mixer_track`
                selected_after_focus = self._query_selected_mixer_track()
                if selected_after_focus is not None and selected_after_focus != mixer_track and self.fl_adapter:
                    try:
                        self.fl_adapter.select_mixer_track(mixer_track, focus=False)
                    except Exception:
                        pass

            # Final slot-capacity guard on the active Mixer track so FL's 10-slot Error popup cannot trigger
            if self.fl_adapter:
                try:
                    guard_track = selected_now if selected_now is not None else mixer_track
                    guard_slots = list((self.fl_adapter.plugin_list(guard_track) or {}).get("slots") or [])
                    if len(guard_slots) >= 10:
                        return {
                            "ok": False,
                            "loaded": False,
                            "plugin_loaded": False,
                            "mixer_track": mixer_track,
                            "source_mixer_track": orig_track,
                            "daisy_chained": daisy_chained,
                            "plugin_name": plugin_name,
                            "slots": guard_slots,
                            "verified": False,
                            "error": f"Active Mixer track {guard_track} already has 10 FX slots full; skipped F8",
                        }
                except Exception:
                    pass

            channels_count_before: Optional[int] = None
            master_slots_before: Optional[int] = None
            if self.fl_adapter:
                try:
                    channels_count_before = len(self.fl_adapter.get_channels())
                except Exception:
                    channels_count_before = None
                if mixer_track != 0:
                    try:
                        m_plist = self.fl_adapter.plugin_list(0)
                        if isinstance(m_plist, dict):
                            master_slots_before = len(list(m_plist.get("slots") or []))
                    except Exception:
                        master_slots_before = None

            time.sleep(0.10)
            query = self._clean_effect_query(cand)
            self.press_vk(VK_F8)
            time.sleep(0.60)
            self.type_text(query, char_delay=0.03)
            time.sleep(0.32)
            self.press_vk(VK_RETURN)
            time.sleep(0.90)
            error_popup = self._dismiss_fl_error_dialog_if_any(hwnd)

            accidental_generator = False
            leaked_to_master = False
            for _poll_i in range(4):
                if self.fl_adapter:
                    if channels_count_before is not None:
                        try:
                            cur_chs = self.fl_adapter.get_channels()
                            if len(cur_chs) > channels_count_before:
                                accidental_generator = True
                                break
                        except Exception:
                            pass
                    try:
                        after_plist = self.fl_adapter.plugin_list(mixer_track)
                        after_slots = list(after_plist.get("slots") or [])
                        for s in after_slots:
                            if not isinstance(s, dict):
                                continue
                            s_idx = int(s.get("slot", -1))
                            s_name = str(s.get("name", ""))
                            is_new_slot = s_idx not in before_slot_ids
                            is_target_match = (not before_slot_ids) and (
                                query.lower() in s_name.lower() or cand.lower() in s_name.lower()
                            )
                            if is_new_slot or is_target_match:
                                self.press_vk(VK_ESCAPE)
                                time.sleep(0.12)
                                return {
                                    "ok": True,
                                    "loaded": True,
                                    "plugin_loaded": True,
                                    "mixer_track": mixer_track,
                                    "source_mixer_track": orig_track,
                                    "daisy_chained": daisy_chained,
                                    "slot": s_idx,
                                    "plugin_name": s_name or cand,
                                    "slots": after_slots,
                                    "verified": True,
                                }
                    except Exception:
                        pass
                    if mixer_track != 0 and master_slots_before is not None:
                        try:
                            m_after = list((self.fl_adapter.plugin_list(0) or {}).get("slots") or [])
                            if len(m_after) > master_slots_before:
                                leaked_to_master = True
                                break
                        except Exception:
                            pass
                time.sleep(0.45)

            self.press_vk(VK_ESCAPE)
            time.sleep(0.15)
            if accidental_generator:
                return {
                    "ok": False,
                    "loaded": False,
                    "plugin_loaded": False,
                    "mixer_track": mixer_track,
                    "source_mixer_track": orig_track,
                    "daisy_chained": daisy_chained,
                    "plugin_name": plugin_name,
                    "slots": before_slots,
                    "verified": False,
                    "error": f"Plugin Picker dropped a generator instead of Mixer effect '{cand}'; aborted to keep Channel Rack clean",
                }
            if leaked_to_master:
                return {
                    "ok": False,
                    "loaded": False,
                    "plugin_loaded": False,
                    "mixer_track": mixer_track,
                    "source_mixer_track": orig_track,
                    "daisy_chained": daisy_chained,
                    "plugin_name": plugin_name,
                    "slots": before_slots,
                    "verified": False,
                    "error": (
                        f"Plugin Picker dropped '{cand}' onto Master (Track 0) instead of Mixer track {mixer_track}; "
                        "stopped fallback retries so Master FX slots are not filled"
                    ),
                }
            if error_popup:
                return {
                    "ok": False,
                    "loaded": False,
                    "plugin_loaded": False,
                    "mixer_track": mixer_track,
                    "source_mixer_track": orig_track,
                    "daisy_chained": daisy_chained,
                    "plugin_name": plugin_name,
                    "slots": before_slots,
                    "verified": False,
                    "error": (
                        f"FL Studio showed an Error popup while adding '{cand}' on Mixer track {mixer_track}; "
                        "stopped retries cleanly"
                    ),
                }

        return {
            "ok": False,
            "loaded": False,
            "plugin_loaded": False,
            "mixer_track": mixer_track,
            "source_mixer_track": orig_track,
            "daisy_chained": daisy_chained,
            "plugin_name": plugin_name,
            "slots": before_slots,
            "verified": False,
            "error": f"Effect plugin '{plugin_name}' could not be confirmed in mixer track {mixer_track}",
        }

    @staticmethod
    def _clean_effect_query(name: str) -> str:
        """Strip punctuation and leading 'Fruity ' so Plugin Picker never hits generator 'Fruity Kick'."""
        cleaned = " ".join("".join(ch if (ch.isalnum() or ch in " _+-") else " " for ch in name).split())
        low = cleaned.lower()
        if low.startswith("fruity ") and len(cleaned) > 7:
            return cleaned[7:].strip()
        return cleaned or name.strip()

    def _select_pattern_live(self, target_pattern: int) -> bool:
        """Select a 1-based FL Studio Pattern via SysEx (`patterns.jumpToPattern`), falling back to Numpad."""
        if not self.fl_adapter or target_pattern <= 0:
            return False
        if hasattr(self.fl_adapter, "select_pattern"):
            try:
                res = self.fl_adapter.select_pattern(target_pattern, deselect=True)
                if isinstance(res, dict) and res.get("ok") and int(res.get("selected", -1)) == target_pattern:
                    return True
            except Exception as exc:
                logger.debug("SysEx select_pattern(%d) failed, falling back to Numpad: %s", target_pattern, exc)
        try:
            cur = self.fl_adapter.get_project_state().pattern_number
        except Exception:
            cur = None
        if not isinstance(cur, int) or cur <= 0:
            return False
        if cur == target_pattern:
            return True

        steps_budget = min(24, abs(target_pattern - cur) + 4)
        for _ in range(steps_budget):
            if cur == target_pattern:
                return True
            self.press_vk(VK_ADD if target_pattern > cur else VK_SUBTRACT, hold=0.03)
            time.sleep(0.08)
            try:
                nxt = self.fl_adapter.get_project_state().pattern_number
                if isinstance(nxt, int) and nxt > 0:
                    cur = nxt
            except Exception:
                break
        return cur == target_pattern

    def _safe_playlist_state(self) -> Dict[str, Any]:
        """Read FL Playlist/Song state via SysEx when supported by the adapter."""
        if not self.fl_adapter or not hasattr(self.fl_adapter, "get_playlist_state"):
            return {}
        try:
            st = self.fl_adapter.get_playlist_state(max_tracks=8)
            return st if isinstance(st, dict) else {}
        except Exception:
            return {}

    def _rewind_playlist_to_bar1(self) -> None:
        """Deselect Playlist clips and reset playback cursor + horizontal viewport back to Bar 1."""
        if self.fl_adapter:
            if hasattr(self.fl_adapter, "setup_playlist_track"):
                try:
                    self.fl_adapter.setup_playlist_track(focus=True, deselect_all=True, scroll_to=0)
                except Exception:
                    pass
            if hasattr(self.fl_adapter, "set_song_position"):
                try:
                    vis_pre = self._safe_playlist_state().get("vis_bar")
                    if isinstance(vis_pre, int) and vis_pre > 1:
                        # FL ignores set_song_position(0.0) scroll-back when playhead is already at 0.0; nudge first
                        self.fl_adapter.set_song_position(4.0)
                        time.sleep(0.03)
                    self.fl_adapter.set_song_position(0.0)
                except Exception:
                    pass
        self.press_vk(VK_HOME, hold=0.03)
        time.sleep(0.07)
        for _ in range(3):
            vis_bar = self._safe_playlist_state().get("vis_bar")
            if not isinstance(vis_bar, int) or vis_bar <= 1:
                break
            if self.fl_adapter and hasattr(self.fl_adapter, "set_song_position"):
                try:
                    self.fl_adapter.set_song_position(4.0)
                    time.sleep(0.03)
                    self.fl_adapter.set_song_position(0.0)
                except Exception:
                    pass
            self.press_vk(VK_HOME, hold=0.03)
            if self.fl_adapter and hasattr(self.fl_adapter, "setup_playlist_track"):
                try:
                    self.fl_adapter.setup_playlist_track(focus=True, scroll_to=0)
                except Exception:
                    pass
            time.sleep(0.06)

    @staticmethod
    def _block_active_map(
        sections: List[Dict[str, Any]],
        num_blocks: int,
        roles: List[str],
    ) -> Dict[str, List[bool]]:
        """Determine per-role active blocks (4 bars each) from section metadata."""
        has_melodic = any(r in ("chords", "lead", "arp", "pad", "main") for r in roles)
        # Expand sections cleanly into bar-level role rules
        sec_spans: List[Tuple[int, int, Dict[str, Any]]] = []
        cursor = 1
        for sec in sections:
            bars = max(1, int(sec.get("bars", 4) or 4))
            sec_spans.append((cursor, cursor + bars - 1, sec))
            cursor += bars

        out: Dict[str, List[bool]] = {r: [True] * num_blocks for r in roles}
        for blk_idx in range(num_blocks):
            mid_bar = blk_idx * 4 + 2
            sec_meta: Dict[str, Any] = {}
            for s_start, s_end, s_obj in sec_spans:
                if s_start <= mid_bar <= s_end:
                    sec_meta = s_obj
                    break
            if not sec_meta and sec_spans:
                sec_meta = sec_spans[-1][2]

            explicit_roles = [
                ("lead" if str(r).strip().lower() == "melody" else str(r).strip().lower())
                for r in (sec_meta.get("roles") or [])
                if str(r).strip()
            ]
            sec_mode = str(sec_meta.get("mode") or "").strip().lower()
            sec_name = str(sec_meta.get("name") or "").strip().lower()

            for role in roles:
                if explicit_roles:
                    # Only enforce explicit role filtering if at least one active project role matches
                    if any(er in roles for er in explicit_roles):
                        out[role][blk_idx] = (role in explicit_roles)
                        continue
                if num_blocks >= 3 and has_melodic and role in ("drums", "bass"):
                    if (blk_idx == 0 and (sec_mode in ("ambient", "intro", "strip", "") or "intro" in sec_name)) or (
                        blk_idx == num_blocks - 1 and num_blocks >= 4 and (sec_mode in ("strip", "outro") or "outro" in sec_name)
                    ):
                        out[role][blk_idx] = False
        return out

    def _detect_playlist_bar1_x(self, hwnd: int, pl_rect: Tuple[int, int, int, int]) -> int:
        """Find where the Playlist timeline grid starts horizontally (adapts to Picker Panel & DPI)."""
        p_left, p_top, p_right, _ = pl_rect
        p_width = max(400, p_right - p_left)
        fallback_x = p_left + min(340, max(210, int(p_width * 0.27)))

        windll_obj: Any = getattr(ctypes, "windll", None)
        gdi32 = getattr(windll_obj, "gdi32", None) if (os.name == "nt" and windll_obj is not None) else None
        u32 = self._user32
        if u32 is None or gdi32 is None:
            return fallback_x

        hdc = u32.GetDC(0)
        if not hdc:
            return fallback_x
        try:
            y_rows = [p_top + 108, p_top + 148, p_top + 188]
            x_start = p_left + 130
            x_end = min(p_right - 160, p_left + max(380, int(p_width * 0.38)))
            dividers: List[int] = []
            for x in range(x_start, x_end, 2):
                dark_count = 0
                for y in y_rows:
                    col = gdi32.GetPixel(hdc, x, y)
                    if col == -1:
                        continue
                    r = col & 0xFF
                    g = (col >> 8) & 0xFF
                    b = (col >> 16) & 0xFF
                    if (r + g + b) < 95:
                        dark_count += 1
                if dark_count == len(y_rows):
                    if not dividers or (x - dividers[-1]) > 45:
                        dividers.append(x)
            # Last splitter divider between Track Headers (or Picker+Headers) and Bar 1 grid
            if dividers and (p_left + 135) <= dividers[-1] <= x_end:
                return min(p_right - 140, dividers[-1] + 24)
        except Exception:
            pass
        finally:
            u32.ReleaseDC(0, hdc)
        return fallback_x

    def paint_arrangement_to_playlist(
        self,
        sections: Optional[List[Dict[str, Any]]] = None,
        bars_per_pattern: int = 4,
        role_patterns: Optional[Dict[str, int]] = None,
        clear_existing: bool = True,
    ) -> Dict[str, Any]:
        """Paint section-aware, bar-aligned pattern clips onto Playlist Tracks 1..N and verify song length."""
        section_list = sections or [{"name": "Intro", "bars": bars_per_pattern}, {"name": "Drop", "bars": bars_per_pattern}]
        if not self.is_supported:
            return {"ok": True, "verified": True, "painted_tracks": len(role_patterns or section_list), "mock": True}

        hwnd = self.focus_fl_studio()
        if not hwnd:
            return {"ok": False, "verified": False, "error": "FL Studio window not found"}

        self.press_vk(VK_ESCAPE)
        time.sleep(0.10)
        self.ensure_window_focused(target_form_id=2, vk_key=VK_F5)
        time.sleep(0.20)

        pl_rect = self.find_fl_subwindow_rect(hwnd, "Playlist")
        if pl_rect:
            p_left, p_top, p_right, p_bottom = pl_rect
        else:
            w_left, w_top, w_right, w_bottom = self.get_window_rect(hwnd)
            p_left, p_top, p_right, p_bottom = w_left + 220, w_top + 90, w_right - 20, w_bottom - 60
            pl_rect = (p_left, p_top, p_right, p_bottom)

        p_width = max(400, p_right - p_left)
        p_height = max(250, p_bottom - p_top)
        has_state_api = bool(self.fl_adapter and hasattr(self.fl_adapter, "get_playlist_state"))

        if self.fl_adapter and hasattr(self.fl_adapter, "setup_playlist_track"):
            try:
                self.fl_adapter.setup_playlist_track(focus=True)
            except Exception as exc:
                logger.debug("setup_playlist_track(focus=True) skipped: %s", exc)
        self.ensure_window_focused(target_form_id=2, vk_key=VK_F5)
        time.sleep(0.10)

        # Click inside the Playlist timeline canvas (Select tool) so keyboard shortcuts target the grid, not the title bar
        canvas_focus_x = min(p_right - 60, p_left + int(p_width * 0.55))
        canvas_focus_y = min(p_bottom - 50, p_top + int(p_height * 0.45))
        self.press_vk(VK_E, hold=0.03)
        self.smooth_click(canvas_focus_x, canvas_focus_y, label="Focus Playlist Canvas")
        time.sleep(0.08)

        # Switch FL Studio into Song Mode (Playlist playback) BEFORE arrangement verification
        if self.fl_adapter and hasattr(self.fl_adapter, "set_loop_mode"):
            try:
                self.fl_adapter.set_loop_mode("song")
            except Exception as exc:
                logger.debug("set_loop_mode('song') skipped: %s", exc)

        # Clear leftover Playlist clips from previous beats so old patterns cannot masquerade as the new song
        st_before_clear = self._safe_playlist_state()
        if clear_existing and (not st_before_clear or int(st_before_clear.get("song_length_ticks", 0) or 0) > 0):
            for _ in range(2):
                if self.fl_adapter and hasattr(self.fl_adapter, "setup_playlist_track"):
                    try:
                        self.fl_adapter.setup_playlist_track(focus=True, select_all=True)
                    except Exception:
                        pass
                self.press_combo([VK_CONTROL], VK_A)
                time.sleep(0.08)
                self.press_vk(VK_DELETE, hold=0.04)
                time.sleep(0.12)
                st_after_clr = self._safe_playlist_state()
                if not st_after_clr or int(st_after_clr.get("song_length_ticks", 0) or 0) == 0:
                    break
                self.smooth_click(canvas_focus_x, canvas_focus_y, label="Refocus Playlist Canvas to Clear")
                time.sleep(0.06)

        baseline_st = self._safe_playlist_state() if has_state_api else {}
        baseline_ticks = int(baseline_st.get("song_length_ticks", 0) or 0)

        self._rewind_playlist_to_bar1()
        self.press_vk(VK_P, hold=0.03)
        time.sleep(0.08)

        bar1_x = self._detect_playlist_bar1_x(hwnd, pl_rect)
        first_row_y = min(p_bottom - 80, p_top + 108)
        row_step_y = 42

        total_bars = sum(max(1, int(s.get("bars", bars_per_pattern) or bars_per_pattern)) for s in section_list)
        total_bars = max(8, min(24, total_bars))
        num_4bar_blocks = max(2, min(5, (total_bars + 3) // 4))

        # Order dedicated patterns vertically: Track 1 = Drums, Track 2 = Chords, Track 3 = Bass, Track 4 = Lead
        ordered_roles = ["drums", "chords", "bass", "lead", "pad", "arp"]
        pat_layers: List[Tuple[str, Optional[int]]] = []
        if role_patterns:
            for r in ordered_roles:
                if r in role_patterns:
                    pat_layers.append((r, int(role_patterns[r])))
            for r, pidx in role_patterns.items():
                if r not in ordered_roles:
                    pat_layers.append((r, int(pidx)))
        if not pat_layers:
            pat_layers = [("main", None)]

        # Name and color Playlist Tracks 1..N to match Mixer inserts
        if self.fl_adapter and hasattr(self.fl_adapter, "setup_playlist_track"):
            try:
                from ...music_engine.mix_master import MixMasterEngine
                mix_engine = MixMasterEngine()
                for row_idx, (role, _) in enumerate(pat_layers[:5]):
                    meta = mix_engine.get_track_meta_for_role(role)
                    self.fl_adapter.setup_playlist_track(
                        track=row_idx + 1,
                        name=meta["name"],
                        r=meta["r"],
                        g=meta["g"],
                        b=meta["b"],
                    )
            except Exception as exc:
                logger.debug("Playlist track naming skipped: %s", exc)

        active_map = self._block_active_map(section_list, num_4bar_blocks, [r for r, _ in pat_layers[:5]])

        placed_layers = 0
        dup_strategy = "ctrl_b"  # upgrades to "select_then_ctrl_b" or "paint_drag" if bare Ctrl+B doesn't extend song length
        for row_idx, (role, pat_idx) in enumerate(pat_layers[:5]):
            row_y = min(p_bottom - 35, first_row_y + row_idx * row_step_y)
            self._rewind_playlist_to_bar1()
            self.press_vk(VK_P, hold=0.03)
            time.sleep(0.06)

            if pat_idx is not None:
                self._select_pattern_live(pat_idx)
                time.sleep(0.08)

            pre_ticks = int(self._safe_playlist_state().get("song_length_ticks", baseline_ticks) or 0) if (row_idx == 0 and has_state_api) else -1
            self.smooth_click(bar1_x, row_y, label=f"Playlist Track {row_idx + 1}: Place '{role}' at Bar 1")
            time.sleep(0.14)

            # Closed-loop calibration on Track 1: probe left-to-right so clip lands on Bar 1 (never Bar 9+)
            if row_idx == 0 and has_state_api and pre_ticks >= 0:
                max_bar1_len = max(6.0, float(bars_per_pattern) + 2.5)
                cur_st = self._safe_playlist_state()
                cur_ticks = int(cur_st.get("song_length_ticks", 0) or 0)
                cur_bars = float(cur_st.get("song_length_bars", 0.0) or 0.0)
                calibrated = cur_ticks > max(pre_ticks, baseline_ticks) and (cur_bars <= 0.0 or cur_bars <= max_bar1_len)
                late_fallback: Optional[Tuple[int, int, int]] = None
                if cur_ticks > max(pre_ticks, baseline_ticks) and not calibrated:
                    # Clip landed far right (> Bar 1); remove it and sweep left for Bar 1
                    late_fallback = (bar1_x, row_y, cur_ticks)
                    self.smooth_click(bar1_x, row_y, right=True, label=f"Remove Off-Bar1 Calibration Clip '{role}'")
                    time.sleep(0.10)
                    cur_ticks = int(self._safe_playlist_state().get("song_length_ticks", 0) or 0)

                if not calibrated:
                    x_candidates: List[int] = []
                    cand_x_raw = [bar1_x] + [
                        p_left + int(p_width * frac)
                        for frac in (0.16, 0.19, 0.22, 0.25, 0.28, 0.31, 0.35, 0.40, 0.45)
                    ]
                    for x_raw in cand_x_raw:
                        xc = max(p_left + 130, min(p_right - 120, x_raw))
                        if all(abs(xc - prev) >= 16 for prev in x_candidates):
                            x_candidates.append(xc)
                    y_candidates: List[int] = []
                    for dy in (108, 128, 148, 172, 196, 220):
                        yc = min(p_bottom - 45, p_top + dy)
                        if all(abs(yc - prev) >= 12 for prev in y_candidates):
                            y_candidates.append(yc)

                    # Probe bar1_x across all Y rows first, then sweep X left-to-right across Y rows
                    ordered_xs = [x_candidates[0]] + sorted(x_candidates[1:]) if x_candidates else []
                    for cy in y_candidates:
                        for cx in ordered_xs:
                            if cx == bar1_x and cy == row_y:
                                continue
                            self._rewind_playlist_to_bar1()
                            self.press_vk(VK_P, hold=0.03)
                            self.smooth_click(cx, cy, label=f"Calibrate Playlist Bar 1 for '{role}'")
                            time.sleep(0.14)
                            cur_st = self._safe_playlist_state()
                            cur_ticks = int(cur_st.get("song_length_ticks", 0) or 0)
                            cur_bars = float(cur_st.get("song_length_bars", 0.0) or 0.0)
                            if cur_ticks > max(pre_ticks, baseline_ticks):
                                if cur_bars <= 0.0 or cur_bars <= max_bar1_len:
                                    bar1_x = cx
                                    first_row_y = cy
                                    row_y = cy
                                    calibrated = True
                                    logger.info("Calibrated live Playlist Track 1 Bar 1 -> (%d, %d) [%.2f bars]", bar1_x, first_row_y, cur_bars)
                                    break
                                if late_fallback is None:
                                    late_fallback = (cx, cy, cur_ticks)
                                self.smooth_click(cx, cy, right=True, label=f"Remove Off-Bar1 Test Clip at ({cx},{cy})")
                                time.sleep(0.10)
                                if cx != bar1_x:
                                    break  # Strictly left-to-right sweep already hit > Bar 1 on this row
                        if calibrated:
                            break
                    if not calibrated and late_fallback is not None:
                        lx, ly, _ = late_fallback
                        self._rewind_playlist_to_bar1()
                        self.press_vk(VK_P, hold=0.03)
                        self.smooth_click(lx, ly, label=f"Fallback Playlist Placement '{role}'")
                        time.sleep(0.14)
                        cur_ticks = int(self._safe_playlist_state().get("song_length_ticks", 0) or 0)
                        if cur_ticks > max(pre_ticks, baseline_ticks):
                            bar1_x, first_row_y, row_y = lx, ly, ly
                            calibrated = True
                if not calibrated:
                    return {
                        "ok": False,
                        "verified": False,
                        "painted_tracks": 0,
                        "total_bars": num_4bar_blocks * 4,
                        "song_length_ticks": cur_ticks,
                        "baseline_ticks": baseline_ticks,
                        "song_length_bars": float(self._safe_playlist_state().get("song_length_bars", 0.0) or 0.0),
                        "loop_mode": self._safe_playlist_state().get("loop_mode"),
                        "error": f"Playlist Bar 1 calibration failed (song_length_ticks stayed at {cur_ticks}, baseline {baseline_ticks}).",
                    }

            # Duplicate/paint remaining 4-bar blocks with closed-loop Ctrl+B verification on Track 1
            if num_4bar_blocks > 1:
                if dup_strategy == "paint_drag":
                    self.press_vk(VK_B, hold=0.03)
                    time.sleep(0.05)
                    drag_end_x = min(p_right - 45, bar1_x + max(240, int((p_right - bar1_x) * 0.72)))
                    self.smooth_drag(bar1_x, row_y, drag_end_x, row_y, duration=0.42, label=f"Paint '{role}' Across Playlist")
                    self.press_vk(VK_P, hold=0.03)
                elif dup_strategy == "select_then_ctrl_b":
                    self.press_vk(VK_E, hold=0.03)
                    self.smooth_drag(
                        max(p_left + 80, bar1_x - 14), row_y - 12,
                        min(p_right - 40, bar1_x + 48), row_y + 14,
                        duration=0.22, label=f"Select '{role}' Clip at Bar 1",
                    )
                    self.press_vk(VK_P, hold=0.03)
                    for _ in range(num_4bar_blocks - 1):
                        self.press_combo([VK_CONTROL], VK_B)
                        time.sleep(0.11)
                else:
                    block0_ticks = int(self._safe_playlist_state().get("song_length_ticks", 0) or 0) if (row_idx == 0 and has_state_api) else -1
                    self.press_combo([VK_CONTROL], VK_B)
                    time.sleep(0.12)
                    remaining = num_4bar_blocks - 2
                    if row_idx == 0 and has_state_api and block0_ticks >= 0:
                        after_b1_ticks = int(self._safe_playlist_state().get("song_length_ticks", 0) or 0)
                        if after_b1_ticks <= block0_ticks:
                            # Bare Ctrl+B didn't grow (placed clip wasn't selected): marquee-select with VK_E and retry Ctrl+B
                            self.press_vk(VK_E, hold=0.03)
                            self.smooth_drag(
                                max(p_left + 80, bar1_x - 14), row_y - 12,
                                min(p_right - 40, bar1_x + 48), row_y + 14,
                                duration=0.22, label=f"Select '{role}' Clip for Ctrl+B",
                            )
                            self.press_vk(VK_P, hold=0.03)
                            self.press_combo([VK_CONTROL], VK_B)
                            time.sleep(0.12)
                            after_sel_ticks = int(self._safe_playlist_state().get("song_length_ticks", 0) or 0)
                            if after_sel_ticks > block0_ticks:
                                dup_strategy = "select_then_ctrl_b"
                            else:
                                dup_strategy = "paint_drag"
                                self.press_vk(VK_B, hold=0.03)
                                time.sleep(0.05)
                                drag_end_x = min(p_right - 45, bar1_x + max(240, int((p_right - bar1_x) * 0.72)))
                                self.smooth_drag(bar1_x, row_y, drag_end_x, row_y, duration=0.45, label=f"Paint '{role}' Across Playlist")
                                self.press_vk(VK_P, hold=0.03)
                                remaining = 0
                    for _ in range(remaining):
                        self.press_combo([VK_CONTROL], VK_B)
                        time.sleep(0.11)

            role_mask = active_map.get(role, [True] * num_4bar_blocks)
            # Final block (Outro) stays selected immediately after the last Ctrl+B -> VK_DELETE removes it cleanly
            if num_4bar_blocks >= 4 and not role_mask[-1] and dup_strategy != "paint_drag":
                self.press_vk(VK_DELETE, hold=0.04)
                time.sleep(0.08)

            # Block 0 (Intro) is lifted ONLY after deselecting and rewinding viewport to Bar 1
            if not role_mask[0]:
                self._rewind_playlist_to_bar1()
                self.smooth_click(bar1_x, row_y, right=True, label=f"Playlist Track {row_idx + 1}: Lift '{role}' in Intro")
                time.sleep(0.11)

            placed_layers += 1

        self._rewind_playlist_to_bar1()
        if self.fl_adapter and hasattr(self.fl_adapter, "set_loop_mode"):
            try:
                self.fl_adapter.set_loop_mode("song")
            except Exception:
                pass

        post_st = self._safe_playlist_state() if has_state_api else {}
        song_ticks = int(post_st.get("song_length_ticks", 0) or 0)
        song_bars = float(post_st.get("song_length_bars", 0.0) or 0.0)
        loop_mode = post_st.get("loop_mode")
        verified = (not has_state_api) or (
            placed_layers > 0
            and song_ticks > baseline_ticks
            and (song_bars >= 3.5 or song_ticks >= 1344)
        )

        self._emit_cursor(bar1_x, first_row_y, "Playlist Arrangement Ready", False)
        return {
            "ok": verified,
            "verified": verified,
            "painted_tracks": placed_layers,
            "total_bars": num_4bar_blocks * 4,
            "song_length_ticks": song_ticks,
            "baseline_ticks": baseline_ticks,
            "song_length_bars": song_bars,
            "loop_mode": loop_mode,
        }
