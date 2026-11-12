"""GUI Automation Adapter (Microsoft Hybrid Computer Use).

HCU runs as an MCP server over stdio (``computer-use.exe mcp``) and exposes
exactly two tools:

* ``AX``  -- semantic channel: Windows UI Automation tree
  (modes: ``apps``, ``observe``, ``find``, ``act``)
* ``GUI`` -- visual channel: full-desktop screenshot / zoom / pixel input

This module is a small JSON-RPC client for that server. It never sends input
to the desktop by itself; callers have to use :meth:`ax_act` / :meth:`gui_act`
explicitly. Phase 1 uses only read operations plus one harmless action in a
window that the test harness owns.
"""

from __future__ import annotations

import asyncio
import base64
import itertools
import json
import logging
import os
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

_HCU_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "external", "Hybrid-Computer-Use")
)
_HCU_BINARY = os.path.join(_HCU_DIR, "artifacts", "windows", "computer-use.exe")
_HCU_PROVIDER = os.path.join(_HCU_DIR, "artifacts", "windows", "computer-use-windows-provider.exe")

MCP_PROTOCOL_VERSION = "2025-06-18"


class HCUError(RuntimeError):
    """Raised when HCU is unavailable or a tool call returns an error."""

    def __init__(self, message: str, *, code: Optional[str] = None, hint: Optional[str] = None):
        super().__init__(message)
        self.code = code
        self.hint = hint


@dataclass
class HCUStatus:
    available: bool = False
    binary_path: Optional[str] = None
    provider_present: bool = False
    version: Optional[str] = None
    tools: list[str] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class ScreenshotResult:
    success: bool = False
    path: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    error: Optional[str] = None


@dataclass
class ToolResult:
    """Normalized MCP tool result."""
    is_error: bool
    text: str
    images: list[bytes] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    def json(self) -> Any:
        """Parse the text part as JSON when possible."""
        try:
            return json.loads(self.text)
        except (ValueError, TypeError):
            return None


class GUIAutomationAdapter:
    """JSON-RPC client for the HCU MCP server."""

    def __init__(self, binary_path: Optional[str] = None, *, call_timeout: float = 60.0):
        self._binary = binary_path or _HCU_BINARY
        self._call_timeout = call_timeout
        self._proc: Optional[subprocess.Popen] = None
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self._screenshot_dir = tempfile.mkdtemp(prefix="fl_assistant_screens_")

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return
        if not os.path.isfile(self._binary):
            raise HCUError(f"HCU binary not found at: {self._binary}", code="binary_missing")
        self._proc = subprocess.Popen(
            [self._binary, "mcp"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", bufsize=1,
            cwd=os.path.dirname(self._binary),
        )
        self._rpc("initialize", {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "fl-studio-ai-assistant", "version": "0.1"},
        })
        self._notify("notifications/initialized")

    def stop(self) -> None:
        if self._proc is None:
            return
        try:
            self._proc.terminate()
            self._proc.wait(timeout=5)
        except Exception:  # pragma: no cover
            self._proc.kill()
        self._proc = None

    def __enter__(self) -> "GUIAutomationAdapter":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    # -- health --------------------------------------------------------------

    def check_availability(self) -> HCUStatus:
        """Check binary presence and that the MCP server answers tools/list."""
        status = HCUStatus(binary_path=self._binary,
                           provider_present=os.path.isfile(_HCU_PROVIDER))
        if not os.path.isfile(self._binary):
            status.error = f"HCU binary not found at: {self._binary}"
            return status
        if not status.provider_present:
            status.error = f"Windows provider missing: {_HCU_PROVIDER}"
            return status
        try:
            self.start()
            resp = self._rpc("tools/list", {})
            status.tools = [t["name"] for t in resp.get("tools", [])]
            status.available = {"AX", "GUI"}.issubset(status.tools)
            if not status.available:
                status.error = f"Unexpected tool set: {status.tools}"
        except Exception as e:
            status.error = f"HCU MCP handshake failed: {e}"
        return status

    # -- semantic channel (AX) ----------------------------------------------

    def ax_apps(self) -> ToolResult:
        """List top-level windows (read-only)."""
        return self.call_tool("AX", {"mode": "apps"})

    def ax_observe(self, window_ref: Optional[str] = None, app: Optional[str] = None) -> ToolResult:
        """Return the UIA tree of a window (read-only)."""
        args: dict[str, Any] = {"mode": "observe"}
        if window_ref:
            args["window_ref"] = window_ref
        if app:
            args["app"] = app
        return self.call_tool("AX", args)

    def ax_find(self, query: dict, window_ref: Optional[str] = None) -> ToolResult:
        """Find elements matching a query (read-only)."""
        args: dict[str, Any] = {"mode": "find", "query": query}
        if window_ref:
            args["window_ref"] = window_ref
        return self.call_tool("AX", args)

    def ax_act(self, actions: list[dict], window_ref: Optional[str] = None) -> ToolResult:
        """Run an ordered action batch. SENDS REAL INPUT."""
        args: dict[str, Any] = {"mode": "act", "actions": actions}
        if window_ref:
            args["window_ref"] = window_ref
        return self.call_tool("AX", args)

    # -- visual channel (GUI) -----------------------------------------------

    def capture_screenshot(self) -> ScreenshotResult:
        """Capture the full desktop via HCU's GUI channel (read-only)."""
        result = ScreenshotResult()
        try:
            tr = self.call_tool("GUI", {"actions": [{"type": "screenshot"}]})
            if tr.is_error:
                result.error = tr.text[:500]
                return result
            if not tr.images:
                result.error = "HCU returned no image"
                return result
            path = os.path.join(self._screenshot_dir, f"screen_{int(time.time() * 1000)}.png")
            with open(path, "wb") as f:
                f.write(tr.images[0])
            result.success, result.path = True, path
            result.width, result.height = _png_size(tr.images[0])
        except Exception as e:
            result.error = f"Screenshot failed: {e}"
        return result

    def gui_act(self, actions: list[dict]) -> ToolResult:
        """Run an ordered visual/pixel action batch on the GUI channel."""
        return self.call_tool("GUI", {"actions": actions})

    # -- generic -------------------------------------------------------------

    def call_tool(self, name: str, arguments: dict) -> ToolResult:
        if name not in ("AX", "GUI"):
            raise HCUError(f"Tool not allowlisted: {name}", code="not_allowed")
        self.start()
        resp = self._rpc("tools/call", {"name": name, "arguments": arguments})
        texts, images = [], []
        for part in resp.get("content", []):
            if part.get("type") == "text":
                texts.append(part.get("text", ""))
            elif part.get("type") == "image":
                images.append(base64.b64decode(part.get("data", "")))
        return ToolResult(is_error=bool(resp.get("isError")), text="\n".join(texts),
                          images=images, raw=resp)

    def find_app_by_name(self, name: str) -> Optional[dict]:
        """Find a running top-level window by case-insensitive name match."""
        apps_res = self.ax_apps()
        if apps_res.is_error:
            return None
        apps = apps_res.json() or []
        for app in apps:
            app_name = str(app.get("name", "")).lower()
            title = str(app.get("title", "")).lower()
            if name.lower() in app_name or name.lower() in title:
                return app
        return None

    def is_app_running(self, name: str) -> bool:
        return self.find_app_by_name(name) is not None

    # -- async wrappers ------------------------------------------------------

    async def async_check_availability(self) -> HCUStatus:
        return await asyncio.to_thread(self.check_availability)

    async def async_capture_screenshot(self) -> ScreenshotResult:
        return await asyncio.to_thread(self.capture_screenshot)

    async def async_ax_apps(self) -> ToolResult:
        return await asyncio.to_thread(self.ax_apps)

    async def async_find_app_by_name(self, name: str) -> Optional[dict]:
        return await asyncio.to_thread(self.find_app_by_name, name)

    async def async_is_app_running(self, name: str) -> bool:
        return await asyncio.to_thread(self.is_app_running, name)

    async def async_ax_observe(self, window_ref: Optional[str] = None, app: Optional[str] = None) -> ToolResult:
        return await asyncio.to_thread(self.ax_observe, window_ref, app)

    async def async_ax_find(self, query: dict, window_ref: Optional[str] = None) -> ToolResult:
        return await asyncio.to_thread(self.ax_find, query, window_ref)

    async def async_ax_act(self, actions: list[dict], window_ref: Optional[str] = None) -> ToolResult:
        return await asyncio.to_thread(self.ax_act, actions, window_ref)

    async def async_gui_act(self, actions: list[dict]) -> ToolResult:
        return await asyncio.to_thread(self.gui_act, actions)

    # -- JSON-RPC internals --------------------------------------------------

    def _send(self, msg: dict) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        self._proc.stdin.write(json.dumps(msg) + "\n")
        self._proc.stdin.flush()

    def _notify(self, method: str, params: Optional[dict] = None) -> None:
        msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        with self._lock:
            self._send(msg)

    def _rpc(self, method: str, params: dict) -> dict:
        if self._proc is None or self._proc.poll() is not None:
            raise HCUError("HCU process is not running", code="not_running")
        req_id = next(self._ids)
        with self._lock:
            self._send({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
            deadline = time.monotonic() + self._call_timeout
            assert self._proc.stdout is not None
            while True:
                if time.monotonic() > deadline:
                    raise HCUError(f"HCU timeout on {method}", code="timeout")
                line = self._proc.stdout.readline()
                if not line:
                    err = self._proc.stderr.read() if self._proc.stderr else ""
                    raise HCUError(f"HCU exited unexpectedly: {err[:500]}", code="exited")
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if msg.get("id") != req_id:
                    continue  # notification or unrelated message
                if "error" in msg:
                    e = msg["error"]
                    raise HCUError(e.get("message", str(e)), code=str(e.get("code")))
                return msg.get("result", {})


def _png_size(data: bytes) -> tuple[Optional[int], Optional[int]]:
    """Read width/height from a PNG header without extra dependencies."""
    if len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    return None, None
