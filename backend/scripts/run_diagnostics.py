"""Standalone CLI helper to run FL Studio AI Assistant system diagnostics."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    # Ensure UTF-8 stdout on Windows terminals
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    backend_dir = Path(__file__).resolve().parents[1]
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))

    os.chdir(backend_dir.parent)

    from app.config import SystemDiagnosticsService

    rep = SystemDiagnosticsService().run_diagnostics(probe_live_fl=True)
    status_label = "HAZIR (READY)" if rep.overall_ready else "EKSIK KONTROL VAR (DEGRADED)"
    print(f"  Genel Durum: {status_label}")
    for check in rep.checks:
        print(f"  - [{check.status}] {check.name}: {check.detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

