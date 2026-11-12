# FL Studio AI Assistant - Tek Komutla Baslatici (All-in-One Launcher)
param(
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $RepoRoot "backend\.venv\Scripts\python.exe"
$DiagScript = Join-Path $RepoRoot "backend\scripts\run_diagnostics.py"
$DesktopDir = Join-Path $RepoRoot "apps\desktop"
$ReleaseExe = Join-Path $DesktopDir "src-tauri\target\release\fl-studio-ai-assistant.exe"
$DebugExe = Join-Path $DesktopDir "src-tauri\target\debug\fl-studio-ai-assistant.exe"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "   FL Studio AI Assistant - Masaustu Baslatici (v1.0 RC)  " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

if (-not (Test-Path $VenvPython)) {
    Write-Error "Python sanal ortami bulunamadi: $VenvPython. Lutfen docs/setup-windows.md adimlarini izleyin."
}

# 1. FL Studio MCP TCP Daemon (Port 9787) kontrolu ve otomatik baslatma
$DaemonListening = $false
try {
    $tcp = New-Object System.Net.Sockets.TcpClient
    $tcp.Connect("127.0.0.1", 9787)
    $DaemonListening = $true
    $tcp.Close()
} catch {
    $DaemonListening = $false
}

if (-not $DaemonListening -and (-not $CheckOnly)) {
    Write-Host "[1/4] FL Studio MCP Kopru Servisi (Port 9787) baslatiliyor..." -ForegroundColor Yellow
    Start-Process -FilePath $VenvPython -ArgumentList "-m fl_studio_mcp.daemon" -WorkingDirectory $RepoRoot -WindowStyle Minimized
    Start-Sleep -Seconds 2
} else {
    Write-Host "[1/4] FL Studio MCP Kopru Servisi (Port 9787) kontrol edildi." -ForegroundColor Green
}

# 2. Sistem tanilamasi
Write-Host "[2/4] Sistem tanilamasi calistiriliyor..." -ForegroundColor Yellow
& $VenvPython $DiagScript

if ($CheckOnly) {
    Write-Host "Tanilama kontrolu tamamlandi." -ForegroundColor Green
    exit 0
}

# 3. FastAPI Backend (Port 8000) yenileme ve baslatma
$ExistingBackend = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($ExistingBackend) {
    Write-Host "[3/4] Mevcut FastAPI Backend sunucusu guncel kodla yeniden baslatiliyor..." -ForegroundColor Yellow
    foreach ($conn in $ExistingBackend) {
        Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 1
} else {
    Write-Host "[3/4] FastAPI Backend sunucusu baslatiliyor (http://127.0.0.1:8000)..." -ForegroundColor Yellow
}

Start-Process -FilePath $VenvPython -ArgumentList "-m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload" -WorkingDirectory (Join-Path $RepoRoot "backend") -WindowStyle Minimized
Start-Sleep -Seconds 2

# 4. Masaustu Arayuzu (Tauri + Vite) baslatma
$ViteListening = $false
try {
    $tcpVite = New-Object System.Net.Sockets.TcpClient
    $tcpVite.Connect("localhost", 5173)
    $ViteListening = $true
    $tcpVite.Close()
} catch {
    $ViteListening = $false
}

if (-not $ViteListening) {
    Write-Host "[4/4] On yuz sunucusu (http://localhost:5173) baslatiliyor..." -ForegroundColor Green
    Start-Process -FilePath "cmd.exe" -ArgumentList "/c pnpm dev" -WorkingDirectory $DesktopDir -WindowStyle Minimized
    Start-Sleep -Seconds 2
}

$ExistingUi = Get-Process -Name "fl-studio-ai-assistant" -ErrorAction SilentlyContinue
if (-not $ExistingUi) {
    if (Test-Path $ReleaseExe) {
        Write-Host "[4/4] Masaustu Uygulamasi aciliyor ($ReleaseExe)..." -ForegroundColor Green
        Start-Process -FilePath $ReleaseExe
    } elseif (Test-Path $DebugExe) {
        Write-Host "[4/4] Masaustu Uygulamasi aciliyor ($DebugExe)..." -ForegroundColor Green
        Start-Process -FilePath $DebugExe
    }
} else {
    Write-Host "[4/4] Masaustu Uygulamasi penceresi zaten acik (otomatik yenilendi)." -ForegroundColor Green
}

Write-Host ""
Write-Host "Hazir! FL Studio AI Assistant calisiyor:" -ForegroundColor Cyan
Write-Host "  * Masaustu Penceresi: FL Studio AI Assistant" -ForegroundColor White
Write-Host "  * Tarayici Arayuzu  : http://localhost:5173" -ForegroundColor White
Write-Host "  * Backend API / Docs: http://127.0.0.1:8000/docs" -ForegroundColor White
