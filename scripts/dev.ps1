# Technical Interviewer — dev mode: backend on 8011 with reload + Vite dev server on 5173.
$root = Split-Path -Parent $PSScriptRoot
$env:USE_TF = "0"

# Resolve the Python interpreter: $env:TI_PYTHON > repo-local venv > python on PATH.
$py = $env:TI_PYTHON
if (-not $py) {
    foreach ($candidate in @("$root\.venv\Scripts\python.exe", "$root\venv\Scripts\python.exe")) {
        if (Test-Path $candidate) { $py = $candidate; break }
    }
}
if (-not $py) { $py = "python" }

# Launch voice sidecar (HeadTTS) if provisioned (scripts/setup_voice.ps1)
if (Test-Path "$root\voice\headtts\package.json") {
    $voiceUp = $false
    try {
        $hello = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8012/v1/hello" -TimeoutSec 1
        if ("$hello".StartsWith("HeadTTS")) { $voiceUp = $true }
    } catch {}
    if (-not $voiceUp) {
        Write-Host "Starting voice sidecar (HeadTTS) on http://127.0.0.1:8012" -ForegroundColor Cyan
        Start-Process -FilePath "node" `
            -ArgumentList "./modules/headtts-node.mjs", "--config", "../headtts.config.json" `
            -WorkingDirectory "$root\voice\headtts" -WindowStyle Hidden
    }
    # Fire-and-forget warm-up (first inference compiles the model, ~30s).
    $warmScript = @'
for ($i = 0; $i -lt 60; $i++) {
  try { $h = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8012/v1/hello" -TimeoutSec 2; if ("$h".StartsWith("HeadTTS")) { break } } catch { Start-Sleep -Milliseconds 500 }
}
try { Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8012/v1/synthesize" -ContentType "application/json" -Body '{"input":"Warm-up."}' -TimeoutSec 300 | Out-Null } catch {}
'@
    $warmEnc = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($warmScript))
    Start-Process powershell -WindowStyle Hidden -ArgumentList "-NoProfile", "-EncodedCommand", $warmEnc
} else {
    Write-Host "Voice sidecar not provisioned (run scripts\setup_voice.ps1); continuing without it." -ForegroundColor Yellow
}

Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "`$env:USE_TF='0'; Set-Location '$root\backend'; & '$py' -m uvicorn app.main:app --host 127.0.0.1 --port 8011 --reload"
)
Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "Set-Location '$root\frontend'; npm run dev"
)
Write-Host "Backend: http://127.0.0.1:8011  |  Frontend dev: http://localhost:5173" -ForegroundColor Green
