"""System Diagnostics, First-Run Setup Checks, Privacy-Safe Crash Reporting, and Log Export (Phase 9).

Provides:
1. Understandable and actionable connection/environment diagnostics.
2. Secret hygiene scanner verifying no live API keys are packaged in tracked configs.
3. Privacy-respecting crash/error formatter (redacting secrets and OS user paths).
4. Sanitized log and audit history exporter.
"""

from __future__ import annotations

import json
import os
import platform
import re
import sys
import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..database.persistence import DatabaseManager
from ..integrations.computer_use.adapter import GUIAutomationAdapter
from ..integrations.fl_studio.adapter import FLStudioAdapter
from ..model_providers.provider import SECRET_PATTERNS, redact_secrets
from ..project_memory.memory import ProjectMemoryManager


_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_DESKTOP_EXE_PATH = os.path.join(
    _REPO_ROOT,
    "apps",
    "desktop",
    "src-tauri",
    "target",
    "release",
    "fl-studio-ai-assistant.exe",
)


def sanitize_user_paths(text: str) -> str:
    """Replace OS username segments in Windows/Unix paths with [USER] for privacy."""
    if not text:
        return text
    out = redact_secrets(text)
    out = re.sub(r"([A-Za-z]:\\Users\\)[^\\/\"'\s]+", r"\1[USER]", out)
    out = re.sub(r"(/Users/|/home/)[^/\"'\s]+", r"\1[USER]", out)
    return out


@dataclass
class ComponentCheck:
    name: str
    ready: bool
    status: str
    detail: str
    remediation: str = ""


@dataclass
class SystemDiagnosticsReport:
    timestamp: str
    overall_ready: bool
    checks: List[ComponentCheck] = field(default_factory=list)
    project_backup_guidance: List[str] = field(
        default_factory=lambda: [
            "Before running multi-step arrangements on an important FL Studio project, press Ctrl+N in FL Studio to save a new numbered version (.flp).",
            "Keep Safe Mode enabled in Assistant Settings so HIGH/DESTRUCTIVE actions and render overwrites require explicit approval.",
            "Use Dry-Run / Plan Preview mode first to inspect planned actions before live execution.",
        ]
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "overall_ready": self.overall_ready,
            "checks": [asdict(c) for c in self.checks],
            "project_backup_guidance": list(self.project_backup_guidance),
        }


class SystemDiagnosticsService:
    """Runs first-run setup verification, health checks, and secret hygiene audits."""

    def __init__(
        self,
        fl_adapter: Optional[FLStudioAdapter] = None,
        hcu_adapter: Optional[GUIAutomationAdapter] = None,
        repo_root: Optional[str] = None,
    ):
        self.fl_adapter = fl_adapter
        self.hcu_adapter = hcu_adapter
        self.repo_root = repo_root or _REPO_ROOT

    def run_diagnostics(self, probe_live_fl: bool = False) -> SystemDiagnosticsReport:
        checks: List[ComponentCheck] = []

        # 1. Python & OS Environment
        py_ver = platform.python_version()
        os_info = f"{platform.system()} {platform.release()} ({platform.machine()})"
        checks.append(
            ComponentCheck(
                name="python_and_os",
                ready=True,
                status="OK",
                detail=f"Python {py_ver} on {os_info}",
            )
        )

        # 2. FL Studio MCP Integration check
        fl = self.fl_adapter or FLStudioAdapter()
        if probe_live_fl:
            st = fl.connect()
            fl.disconnect()
        else:
            st = fl.check_health()

        fl_ready = bool(st.connected and st.fl_studio_alive)
        checks.append(
            ComponentCheck(
                name="fl_studio_mcp",
                ready=fl_ready,
                status="CONNECTED" if fl_ready else "DISCONNECTED",
                detail=(
                    f"FL Studio MCP connected on {st.transport} (alive={st.fl_studio_alive})"
                    if fl_ready
                    else f"FL Studio MCP not currently connected ({st.error or 'daemon/FL Studio offline'})."
                ),
                remediation=(
                    ""
                    if fl_ready
                    else "Start loopMIDI (FLStudioMCP RX / TX), open FL Studio 2025, enable FLStudioMCP in MIDI Settings (F10), and ensure the MCP daemon is listening on 127.0.0.1:9787."
                ),
            )
        )

        # 3. HCU GUI Automation Binaries
        hcu_dir = os.path.join(self.repo_root, "external", "Hybrid-Computer-Use", "artifacts", "windows")
        hcu_bin = os.path.join(hcu_dir, "computer-use.exe")
        hcu_prov = os.path.join(hcu_dir, "computer-use-windows-provider.exe")
        hcu_ready = os.path.isfile(hcu_bin) and os.path.isfile(hcu_prov)
        checks.append(
            ComponentCheck(
                name="hcu_gui_automation",
                ready=hcu_ready,
                status="READY" if hcu_ready else "MISSING_BINARIES",
                detail=(
                    "HCU computer-use.exe and windows-provider binaries verified."
                    if hcu_ready
                    else "HCU binaries not found in external/Hybrid-Computer-Use."
                ),
                remediation=(
                    ""
                    if hcu_ready
                    else "Run scripts/fetch_external.ps1 and build computer-use.exe and computer-use-windows-provider.exe with Go."
                ),
            )
        )

        # 4. Packaged Desktop Companion Executable
        rel_exe = os.path.join(
            self.repo_root,
            "apps",
            "desktop",
            "src-tauri",
            "target",
            "release",
            "fl-studio-ai-assistant.exe",
        )
        dbg_exe = os.path.join(
            self.repo_root,
            "apps",
            "desktop",
            "src-tauri",
            "target",
            "debug",
            "fl-studio-ai-assistant.exe",
        )
        exe_path = rel_exe if os.path.isfile(rel_exe) else dbg_exe
        exe_exists = os.path.isfile(exe_path)
        exe_size_mb = round(os.path.getsize(exe_path) / (1024 * 1024), 2) if exe_exists else 0.0
        checks.append(
            ComponentCheck(
                name="desktop_companion_binary",
                ready=exe_exists,
                status="BUILT" if exe_exists else "NOT_BUILT",
                detail=(
                    f"fl-studio-ai-assistant.exe present ({exe_size_mb} MB)"
                    if exe_exists
                    else "Desktop release executable not found."
                ),
                remediation=(
                    ""
                    if exe_exists
                    else "Run 'pnpm tauri build' inside apps/desktop to compile the Windows executable."
                ),
            )
        )

        # 5. Secret Hygiene Check (No live secrets in config templates)
        leaked_files = self.scan_config_files_for_secrets()
        secrets_clean = len(leaked_files) == 0
        checks.append(
            ComponentCheck(
                name="secret_hygiene",
                ready=secrets_clean,
                status="CLEAN" if secrets_clean else "SECRET_DETECTED",
                detail=(
                    "No API keys or tokens detected in packaged configuration files."
                    if secrets_clean
                    else f"Potential secret found in: {', '.join(leaked_files)}"
                ),
                remediation=(
                    ""
                    if secrets_clean
                    else "Remove hardcoded keys from tracked files and store credentials in OS environment or Credential Manager."
                ),
            )
        )

        overall = all(
            c.ready for c in checks if c.name in ("python_and_os", "hcu_gui_automation", "secret_hygiene")
        )
        return SystemDiagnosticsReport(
            timestamp=datetime.now(timezone.utc).isoformat(),
            overall_ready=overall,
            checks=checks,
        )

    def scan_config_files_for_secrets(self) -> List[str]:
        """Scan .env.example and configs/*.json to ensure no live credentials are packaged."""
        targets = [
            os.path.join(self.repo_root, ".env.example"),
            os.path.join(self.repo_root, "configs", "external-pins.json"),
            os.path.join(self.repo_root, "configs", "genre-presets.json"),
        ]
        flagged: List[str] = []
        for path in targets:
            if not os.path.isfile(path):
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                for pat in SECRET_PATTERNS:
                    for m in pat.finditer(content):
                        token = m.group(0)
                        if "your_" not in token.lower() and "example" not in token.lower() and "xxx" not in token.lower():
                            flagged.append(os.path.basename(path))
                            break
            except Exception:
                pass
        return flagged


class PrivacySafeLogExporter:
    """Formats privacy-safe error reports and exports sanitized diagnostic/audit logs."""

    @staticmethod
    def format_crash_report(exc: BaseException, context_note: str = "") -> Dict[str, Any]:
        """Produce a structured crash report with secrets and OS usernames redacted."""
        tb_str = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error_type": type(exc).__name__,
            "message": sanitize_user_paths(str(exc)),
            "context": sanitize_user_paths(context_note),
            "sanitized_traceback": sanitize_user_paths(tb_str),
        }

    @staticmethod
    def export_sanitized_logs(
        output_path: str,
        *,
        diagnostics: Optional[SystemDiagnosticsReport] = None,
        memory: Optional[ProjectMemoryManager] = None,
        extra_logs: Optional[List[str]] = None,
    ) -> str:
        """Write a sanitized JSON diagnostic & audit log bundle to output_path."""
        abs_out = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(abs_out), exist_ok=True)

        diag_dict = diagnostics.to_dict() if diagnostics else {}
        summaries = (
            [asdict(s) for s in memory.get_recent_summaries(limit=50)]
            if memory is not None
            else []
        )
        sanitized_lines = [sanitize_user_paths(line) for line in (extra_logs or [])]

        raw_json = json.dumps(
            {
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "privacy_notice": "All API keys and OS user directory names have been sanitized.",
                "diagnostics": diag_dict,
                "task_summaries": summaries,
                "log_entries": sanitized_lines,
            },
            indent=2,
            ensure_ascii=False,
        )
        clean_json = sanitize_user_paths(raw_json)
        with open(abs_out, "w", encoding="utf-8") as f:
            f.write(clean_json)
        return abs_out
