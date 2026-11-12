"""Phase 1 FL Studio proof of concept (REAL integration, not mocked).

Requires: loopMIDI ports "FLStudioMCP RX"/"FLStudioMCP TX", FL Studio open with
the FLStudioMCP controller enabled, and the flstudio-mcp daemon running.

Usage (from backend/):
    .venv\\Scripts\\python scripts\\poc_fl.py           # read-only
    .venv\\Scripts\\python scripts\\poc_fl.py --write   # + BPM change & restore
                                                       #   (only with user approval)
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.integrations.fl_studio import FLStudioAdapter, TransportType  # noqa: E402


def step(report: dict, name: str, fn):
    try:
        value = fn()
        report[name] = {"ok": True, "value": value}
        print(f"[PASS] {name}: {value}")
        return value
    except Exception as e:  # report every failure, never crash
        report[name] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        print(f"[FAIL] {name}: {type(e).__name__}: {e}")
        return None


def main() -> int:
    report: dict = {}
    a = FLStudioAdapter(transport=TransportType.TCP)
    status = a.connect()
    report["connect"] = {"connected": status.connected, "alive": status.fl_studio_alive,
                         "heartbeat_age": status.heartbeat_age, "error": status.error}
    print("[INFO] connect:", report["connect"])
    if not status.connected:
        print(json.dumps(report, indent=1))
        return 1

    step(report, "ping", a.ping)
    step(report, "get_tempo", a.get_tempo)
    step(report, "project_state", lambda: a.get_project_state().raw)
    step(report, "play_state", a.get_play_state)
    step(report, "channels", lambda: [c.get("name") for c in a.get_channels()])
    step(report, "patterns", lambda: len(a.get_patterns()))
    step(report, "mixer_tracks", lambda: len(a.get_mixer_tracks()))

    if "--write" in sys.argv:
        original = a.get_tempo()
        test_bpm = 133.0 if abs(original - 133.0) > 0.01 else 127.0
        try:
            step(report, "set_tempo_verified", lambda: vars(a.set_tempo_verified(test_bpm)))
        finally:
            step(report, "restore_tempo", lambda: vars(a.set_tempo_verified(original)))

    a.disconnect()
    print("\nREPORT:", json.dumps(report, indent=1, ensure_ascii=False, default=str))
    return 0 if all(v.get("ok", True) for v in report.values() if isinstance(v, dict)) else 2


if __name__ == "__main__":
    raise SystemExit(main())

