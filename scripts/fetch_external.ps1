# Recreates external/ at the pinned commits and builds HCU.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\fetch_external.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$pins = Get-Content -Raw (Join-Path $root "configs\external-pins.json") | ConvertFrom-Json
$ext = Join-Path $root "external"
New-Item -ItemType Directory -Force -Path $ext | Out-Null

foreach ($name in @("flstudio-mcp", "Hybrid-Computer-Use")) {
    $pin = $pins.$name
    $dir = Join-Path $ext $name
    if (-not (Test-Path $dir)) { git clone $pin.url $dir }
    git -C $dir fetch --quiet origin
    git -C $dir checkout --quiet $pin.commit
    Write-Output "$name -> $($pin.commit)"
}

# Build HCU (Windows provider needs .NET 8+ SDK; MCP server needs Go 1.22+)
$hcu = Join-Path $ext "Hybrid-Computer-Use"
$out = Join-Path $hcu "artifacts\windows"
New-Item -ItemType Directory -Force -Path $out | Out-Null
$proj = Join-Path $hcu "computer-use\native\windows\ComputerUse.Windows.Runtime\ComputerUse.Windows.Runtime.csproj"
dotnet publish $proj -c Release -r win-x64 --self-contained true -o (Join-Path $out "provider-publish")
if ($LASTEXITCODE -ne 0) { throw "dotnet publish failed" }
Move-Item -Force (Join-Path $out "provider-publish\computer-use-windows-provider.exe") $out
Remove-Item -Recurse -Force (Join-Path $out "provider-publish")
$ver = (Get-Content -Raw (Join-Path $hcu "VERSION")).Trim()
Push-Location (Join-Path $hcu "computer-use")
$env:CGO_ENABLED = "0"
go build -trimpath -ldflags "-s -w -X main.version=$ver" -o (Join-Path $out "computer-use.exe") .\cmd\computer-use
Pop-Location
if ($LASTEXITCODE -ne 0) { throw "go build failed" }
Write-Output "HCU built: $out"

