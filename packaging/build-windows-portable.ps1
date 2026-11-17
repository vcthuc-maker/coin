# Build a true copy-and-run Windows x64 portable folder.
# Run in GitHub Actions on a Windows runner with Python 3.12 for resolving wheels.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$ProgressPreference = 'SilentlyContinue'
$root = Split-Path -Parent $PSScriptRoot
$out = Join-Path $root "dist\PrePumpScanner_Portable"
$pyFolder = Join-Path $out "python"
$appFolder = Join-Path $out "app"
$embed = Join-Path $env:TEMP "python-3.12.10-embed-amd64.zip"
$embedUrl = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip"

if (Test-Path $out) { Remove-Item $out -Recurse -Force }
New-Item -ItemType Directory -Force $pyFolder, $appFolder | Out-Null
Write-Host "Copying application files..."
Get-ChildItem -Path $root -Filter '*.py' -File | Copy-Item -Destination $appFolder
Copy-Item (Join-Path $root "requirements.txt") $appFolder
if (Test-Path (Join-Path $root ".streamlit")) {
    Copy-Item (Join-Path $root ".streamlit") (Join-Path $appFolder ".streamlit") -Recurse -Force
}
foreach ($dir in @("flow", "signals", "mexc_velocity")) {
    New-Item -ItemType Directory -Force (Join-Path $appFolder "data\$dir") | Out-Null
}
if (Test-Path (Join-Path $root "data")) {
    Copy-Item (Join-Path $root "data\*") (Join-Path $appFolder "data") -Recurse -Force
}

Write-Host "Downloading official Python embeddable Windows x64 runtime..."
Invoke-WebRequest -Uri $embedUrl -OutFile $embed -UseBasicParsing
Expand-Archive -Path $embed -DestinationPath $pyFolder -Force
if (-not (Test-Path (Join-Path $pyFolder "python.exe"))) { throw "Embedded Python exe missing" }

$pth = @("python312.zip", ".", "Lib\site-packages", "import site")
Set-Content (Join-Path $pyFolder "python312._pth") -Value $pth -Encoding ASCII
$site = Join-Path $pyFolder "Lib\site-packages"
New-Item -ItemType Directory -Force $site | Out-Null

Write-Host "Resolving Windows wheels into portable site-packages..."
python -m pip install --disable-pip-version-check --no-warn-script-location --only-binary=:all: --upgrade -r (Join-Path $root "requirements.txt") --target $site
if ($LASTEXITCODE -ne 0) { throw "Wheel dependency installation failed" }

& (Join-Path $pyFolder "python.exe") -c "import streamlit, pandas, numpy, pyarrow, httpx"
if ($LASTEXITCODE -ne 0) { throw "Embedded Python dependency smoke test failed" }
& (Join-Path $pyFolder "python.exe") -c "import sys; print('Portable Python:',sys.version)"

$start = @'
@echo off
setlocal
cd /d "%~dp0app"
if not exist "..\python\python.exe" (
  echo Portable Python missing. Download the complete ZIP from GitHub Actions.
  pause
  exit /b 1
)
echo Opening Pre-Pump Scanner at http://127.0.0.1:8501
start "" "http://127.0.0.1:8501"
"..\python\python.exe" -m streamlit run "app.py" --server.address=127.0.0.1 --server.port=8501 --server.headless=true --browser.gatherUsageStats=false
if errorlevel 1 (
  echo Startup failed; read the error displayed above.
  pause
)
'@
Set-Content (Join-Path $out "START.bat") -Value $start -Encoding ASCII

$guide = @'
PRE-PUMP SCANNER PORTABLE - WINDOWS 10/11 64 BIT
=================================================
1. Extract the ENTIRE ZIP to C:\PrePumpScanner_Portable (or another folder).
2. Double-click START.bat, do NOT launch it inside the ZIP.
3. The dashboard opens at http://127.0.0.1:8501.
4. Keep the command window open. Press Ctrl+C to stop.
5. To use on another Windows x64 PC, copy the whole extracted folder.

No separate Python installation is required. Python and libraries are bundled.
Internet is required to request market data. Exchange API 403/429/451 may still
occur because of rate limits or hosting/network restrictions.
Historical GitHub cloud data does NOT automatically sync into this offline ZIP.
A future release must be downloaded for code updates.
Unsigned START.bat may trigger Windows Defender or SmartScreen prompts.
No exchange credentials are necessary. Do not add private keys/passwords.
This is a research tool, not a proven profitable trading strategy.
'@
Set-Content (Join-Path $out "HUONG_DAN.txt") -Value $guide -Encoding UTF8
$zipFile = Join-Path $root "dist\PrePumpScanner_Windows_x64_Portable.zip"
if (Test-Path $zipFile) { Remove-Item $zipFile -Force }
Compress-Archive -Path (Join-Path $out "*") -DestinationPath $zipFile -CompressionLevel Optimal
Write-Host "Created: $zipFile"
Get-Item $zipFile | Select-Object FullName,Length
