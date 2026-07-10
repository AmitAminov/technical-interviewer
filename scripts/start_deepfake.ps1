# Technical Interviewer — deepfake talking-head sidecar (Wav2Lip via `lipsync`).
#
# Optional GPU sidecar: turns a character image + text into a lip-synced MP4
# (text -> Kokoro TTS on :8012 -> Wav2Lip). Enables the "Deepfake" avatar mode.
# Requires the one-time provisioning under deepfake/ (its own CUDA venv +
# wav2lip_gan_ls.pth weights + bundled ffmpeg). See docs/MUSETALK.md / the
# deepfake/ notes. The main app auto-detects it via /api/health.lipsync_engine.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$df = "$root\deepfake"
if (-not (Test-Path "$df\.venv\Scripts\python.exe")) {
    Write-Host "Deepfake sidecar not provisioned ($df\.venv missing)." -ForegroundColor Yellow
    exit 1
}
$env:PATH = "$df\bin;$env:PATH"           # bundled ffmpeg
$env:TI_VOICE_URL = if ($env:TI_VOICE_URL) { $env:TI_VOICE_URL } else { "http://127.0.0.1:8012" }
Write-Host "Starting deepfake sidecar (Wav2Lip) on http://127.0.0.1:8013" -ForegroundColor Green
& "$df\.venv\Scripts\python.exe" -m uvicorn service:app --host 127.0.0.1 --port 8013 --app-dir "$df\sidecar"
