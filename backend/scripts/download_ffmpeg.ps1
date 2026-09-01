# Скачивает статические Windows-сборки ffmpeg.exe/ffprobe.exe и кладёт их
# в backend/ (рядом с desktop_main.py) — то же место, где их при сборке
# .exe/Tauri ищет app/config.py (FFMPEG_PATH/FFPROBE_PATH). Бинарники не
# хранятся в git (~100МБ каждый) — их нужно скачать один раз перед сборкой
# или локальной разработкой без системного ffmpeg.
#
# Использование:
#   powershell -ExecutionPolicy Bypass -File backend\scripts\download_ffmpeg.ps1

$ErrorActionPreference = "Stop"

$backendDir = Split-Path -Parent $PSScriptRoot
$zipUrl = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
$zipPath = Join-Path $env:TEMP "ffmpeg-essentials.zip"
$extractDir = Join-Path $env:TEMP "ffmpeg-essentials-extracted"

Write-Host "Скачиваю $zipUrl ..."
Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath

Write-Host "Распаковываю..."
if (Test-Path $extractDir) { Remove-Item -Recurse -Force $extractDir }
Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force

$binDir = Get-ChildItem -Path $extractDir -Directory | Select-Object -First 1
$ffmpegExe = Join-Path $binDir.FullName "bin\ffmpeg.exe"
$ffprobeExe = Join-Path $binDir.FullName "bin\ffprobe.exe"

Copy-Item $ffmpegExe (Join-Path $backendDir "ffmpeg.exe") -Force
Copy-Item $ffprobeExe (Join-Path $backendDir "ffprobe.exe") -Force

Remove-Item $zipPath -Force
Remove-Item -Recurse -Force $extractDir

Write-Host "Готово: backend\ffmpeg.exe и backend\ffprobe.exe"
