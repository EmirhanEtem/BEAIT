# FL Studio AI Assistant — First-Run Verification & Launcher Script (Phase 9)
param(
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $RepoRoot "backend\.venv\Scripts\python.exe"
$DesktopExe = Join-Path $RepoRoot "apps\desktop\src-tauri\target\release\fl-studio-ai-assistant.exe"
if (-not (Test-Path $DesktopExe)) {
    $DesktopExe = Join-Path $RepoRoot "apps\desktop\src-tauri\target\debug\fl-studio-ai-assistant.exe"
}

Write-Host "=== FL Studio AI Assistant Release Candidate Launcher ===" -ForegroundColor Cyan

if (-not (Test-Path $VenvPython)) {
    Write-Error "Python virtual environment not found at $VenvPython. See docs/setup-windows.md."
}

Write-Host "[1/3] Running pre-flight diagnostics..." -ForegroundColor Yellow
& $VenvPython -c "import sys; sys.path.insert(0, 'backend'); from app.config import SystemDiagnosticsService; rep = SystemDiagnosticsService().run_diagnostics(); print('Diagnostics Ready:', rep.overall_ready); [print(f'  - {c.name}: {c.status} ({c.detail})') for c in rep.checks]"

if ($CheckOnly) {
    Write-Host "Pre-flight check completed." -ForegroundColor Green
    exit 0
}

Write-Host "[2/3] Starting FastAPI Backend on http://127.0.0.1:8000 ..." -ForegroundColor Yellow
$BackendProc = Start-Process -FilePath $VenvPython -ArgumentList "-m uvicorn app.main:app --host 127.0.0.1 --port 8000" -WorkingDirectory (Join-Path $RepoRoot "backend") -PassThru

if (Test-Path $DesktopExe) {
    Write-Host "[3/3] Launching Desktop Companion ($DesktopExe)..." -ForegroundColor Green
    Start-Process -FilePath $DesktopExe
} else {
    Write-Warning "Desktop executable not found at $DesktopExe. Build with 'pnpm tauri build' in apps/desktop."
}
