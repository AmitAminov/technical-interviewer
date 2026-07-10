# Technical Interviewer — production-style single-command start.
# Serves the built frontend from the FastAPI backend at http://127.0.0.1:8011
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$env:USE_TF = "0"

# Gemini (barge-in reply) authenticates via the GCP project using Application
# Default Credentials + Vertex AI — no API key is fetched or stored locally.
# Set TI_GCP_PROJECT / TI_GCP_LOCATION to override the defaults in config.py.

# Resolve the Python interpreter: $env:TI_PYTHON > repo-local venv > python on PATH.
$py = $env:TI_PYTHON
if (-not $py) {
    foreach ($candidate in @("$root\.venv\Scripts\python.exe", "$root\venv\Scripts\python.exe")) {
        if (Test-Path $candidate) { $py = $candidate; break }
    }
}
if (-not $py) { $py = "python" }

# Build frontend if dist is missing
if (-not (Test-Path "$root\frontend\dist\index.html")) {
    Write-Host "Building frontend..." -ForegroundColor Cyan
    Push-Location "$root\frontend"
    if (-not (Test-Path "node_modules")) { npm install }
    npm run build
    Pop-Location
}

# Build wiki RAG index if missing (optional: only when a local wiki exists,
# either at .\wiki or wherever $env:TI_WIKI_DIR points).
if (-not (Test-Path "$root\backend\data\wiki_index\index.faiss")) {
    $wikiDir = $env:TI_WIKI_DIR
    if (-not $wikiDir) { $wikiDir = "$root\wiki" }
    if (Test-Path $wikiDir) {
        Write-Host "Indexing local wiki (first run only)..." -ForegroundColor Cyan
        & $py "$root\scripts\index_wiki.py"
    } else {
        Write-Host "No local wiki found ($wikiDir) - skipping RAG index; app runs without wiki grounding." -ForegroundColor Yellow
    }
}

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
    # Fire-and-forget warm-up: first inference compiles the model (~30s);
    # warming now means the first real interview utterance is fast.
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

Write-Host "Starting Technical Interviewer at http://127.0.0.1:8011" -ForegroundColor Green
Push-Location "$root\backend"
& $py -m uvicorn app.main:app --host 127.0.0.1 --port 8011
Pop-Location
