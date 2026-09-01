# Собирает backend в единый .exe (PyInstaller) и раскладывает его вместе
# с ffmpeg.exe/ffprobe.exe (см. download_ffmpeg.ps1) как sidecar-бинарники
# Tauri в frontend/src-tauri/binaries/ — с суффиксом целевой платформы,
# которого требует Tauri для externalBin (Command::sidecar()).
#
# Использование (из корня репозитория или откуда угодно):
#   powershell -ExecutionPolicy Bypass -File backend\scripts\build_exe.ps1

$ErrorActionPreference = "Stop"

$backendDir = Split-Path -Parent $PSScriptRoot
$repoRoot = Split-Path -Parent $backendDir
$venvPython = Join-Path $backendDir ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    throw "Не найден backend\.venv — сначала: python -m venv .venv && .venv\Scripts\pip install -r requirements.txt"
}

foreach ($bin in @("ffmpeg.exe", "ffprobe.exe")) {
    if (-not (Test-Path (Join-Path $backendDir $bin))) {
        throw "Не найден backend\$bin — сначала запусти backend\scripts\download_ffmpeg.ps1"
    }
}

Write-Host "Собираю backend через PyInstaller..."
Push-Location $backendDir
try {
    & $venvPython -m PyInstaller --noconfirm shorts-backend.spec
} finally {
    Pop-Location
}

$targetTriple = (& "$backendDir\.venv\Scripts\python.exe" -c "import platform; print('x86_64-pc-windows-msvc' if platform.machine().endswith('64') else 'i686-pc-windows-msvc')").Trim()

$binariesDir = Join-Path $repoRoot "frontend\src-tauri\binaries"
New-Item -ItemType Directory -Force -Path $binariesDir | Out-Null

Copy-Item (Join-Path $backendDir "dist\shorts-backend.exe") (Join-Path $binariesDir "shorts-backend-$targetTriple.exe") -Force
Copy-Item (Join-Path $backendDir "ffmpeg.exe") (Join-Path $binariesDir "ffmpeg-$targetTriple.exe") -Force
Copy-Item (Join-Path $backendDir "ffprobe.exe") (Join-Path $binariesDir "ffprobe-$targetTriple.exe") -Force

Write-Host "Готово: frontend\src-tauri\binaries\*-$targetTriple.exe"
Write-Host "Дальше: cd frontend && npm run tauri build"
