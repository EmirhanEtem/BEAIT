"""Phase 1 HCU proof of concept (REAL integration, not mocked).

Steps:
  1. MCP handshake + tool list
  2. AX apps (read-only window inventory)
  3. GUI screenshot (read-only)
  4. Optional --act: harmless action in a window owned by this script.
     A separate Tk process shows a text box; we locate it through the UIA
     tree and write text with UIA set_value (no foreground / keyboard needed),
     then read the value back from the Tk process and close it.
     No other application receives input.

Usage (from backend/):
    .venv\\Scripts\\python scripts\\poc_hcu.py
    .venv\\Scripts\\python scripts\\poc_hcu.py --act
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

TEST_WINDOW_TITLE = "FLAssistant HCU Test Window"
TEST_TEXT = "hcu-poc-ok"


def run_test_window(out_file: str) -> None:
    """Child-process mode: show a Tk entry and mirror its value to out_file."""
    import tkinter as tk

    root = tk.Tk()
    root.title(TEST_WINDOW_TITLE)
    root.geometry("420x120+60+60")
    var = tk.StringVar()
    tk.Entry(root, textvariable=var, width=40).pack(padx=20, pady=30)
    deadline = time.monotonic() + 40

    def poll() -> None:
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(var.get())
        if time.monotonic() > deadline or os.path.exists(out_file + ".close"):
            root.destroy()
            return
        root.after(100, poll)

    root.after(100, poll)
    root.mainloop()


def _find_window_ref(apps_text: str, title: str) -> str | None:
    for line in apps_text.splitlines():
        m = re.match(r"\s*(w\d+)\s+\"(.*?)\"", line)
        if m and title in m.group(2):
            return m.group(1)
    return None


def _first_ref(text: str) -> str | None:
    m = re.search(r"\b(r\d+)\b", text)
    return m.group(1) if m else None


def main() -> int:
    from app.integrations.computer_use import GUIAutomationAdapter

    act = "--act" in sys.argv
    report: dict = {}
    with GUIAutomationAdapter() as hcu:
        st = hcu.check_availability()
        report["availability"] = {"available": st.available, "tools": st.tools, "error": st.error}
        print("[1] availability:", report["availability"])
        if not st.available:
            return 1

        apps = hcu.ax_apps()
        win_count = len(re.findall(r"^\s*w\d+", apps.text, re.M))
        report["ax_apps"] = {"tool_error": apps.is_error, "windows_visible": win_count}
        print("[2] AX apps:", report["ax_apps"])
        print(apps.text[:1500])

        shot = hcu.capture_screenshot()
        report["screenshot"] = {"ok": shot.success, "size": [shot.width, shot.height],
                                "path": shot.path, "error": shot.error}
        print("[3] screenshot:", report["screenshot"])

        if act:
            out_file = os.path.join(tempfile.mkdtemp(prefix="hcu_poc_"), "value.txt")
            child = subprocess.Popen([
                "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "hcu_test_window.ps1"),
                "-OutFile", out_file,
            ])
            try:
                wref = None
                for _ in range(30):
                    time.sleep(0.3)
                    wref = _find_window_ref(hcu.ax_apps().text, TEST_WINDOW_TITLE)
                    if wref:
                        break
                report["act"] = {"window_ref": wref}
                print("[4a] test window ref:", wref)
                if wref:
                    found = hcu.ax_find({"role": "edit"}, window_ref=wref)
                    eref = _first_ref(found.text)
                    print("[4b] find edit (error=%s): %s" % (found.is_error, found.text[:600]))
                    report["act"]["edit_ref"] = eref
                    if eref:
                        res = hcu.ax_act([{"type": "set_value", "ref": eref, "value": TEST_TEXT}],
                                         window_ref=wref)
                        print("[4c] set_value (error=%s): %s" % (res.is_error, res.text[:800]))
                        time.sleep(0.5)
                        with open(out_file, encoding="utf-8-sig") as f:
                            read_back = f.read()
                        report["act"].update(tool_error=res.is_error, read_back=read_back,
                                             verified=read_back == TEST_TEXT)
                print("[4d] verification:", report["act"])
            finally:
                open(out_file + ".close", "w").close()
                try:
                    child.wait(5)
                except subprocess.TimeoutExpired:
                    child.kill()

    print("\nREPORT:", json.dumps(report, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--window":
        run_test_window(sys.argv[2])
    else:
        raise SystemExit(main())
