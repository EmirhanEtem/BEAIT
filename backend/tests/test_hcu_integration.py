"""HCU GUI automation adapter tests.

* MOCKED  -- default run; no HCU process is started.
* REAL    -- marked ``real_hcu``; starts the built HCU binary.
             Run explicitly:  pytest -m real_hcu
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.integrations.computer_use.adapter import (  # noqa: E402
    GUIAutomationAdapter,
    HCUError,
    HCUStatus,
    _png_size,
)


# ---------------------------------------------------------------- MOCKED ---

class TestAdapterUnit:
    def test_missing_binary_reported(self):
        status = GUIAutomationAdapter(binary_path="C:/nonexistent/cu.exe").check_availability()
        assert not status.available and "not found" in status.error

    def test_start_missing_binary_raises(self):
        with pytest.raises(HCUError) as ei:
            GUIAutomationAdapter(binary_path="C:/nonexistent/cu.exe").start()
        assert ei.value.code == "binary_missing"

    def test_tool_allowlist(self):
        with pytest.raises(HCUError) as ei:
            GUIAutomationAdapter().call_tool("Shell", {})
        assert ei.value.code == "not_allowed"

    def test_status_defaults(self):
        s = HCUStatus()
        assert not s.available and s.tools == []

    def test_png_size(self):
        header = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (1365).to_bytes(4, "big") + (768).to_bytes(4, "big")
        assert _png_size(header) == (1365, 768)
        assert _png_size(b"not a png") == (None, None)


# ------------------------------------------------------------------ REAL ---

@pytest.mark.real_hcu
class TestRealHCU:
    def test_handshake_and_tools(self):
        with GUIAutomationAdapter() as hcu:
            st = hcu.check_availability()
            assert st.available, st.error
            assert st.tools == ["AX", "GUI"]

    def test_ax_apps_read_only(self):
        with GUIAutomationAdapter() as hcu:
            r = hcu.ax_apps()
            assert not r.is_error
            assert '"input_emitted":false' in r.text

    def test_screenshot(self):
        with GUIAutomationAdapter() as hcu:
            shot = hcu.capture_screenshot()
            assert shot.success, shot.error
            assert shot.width and shot.height
