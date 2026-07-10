# Technical Interviewer — voice sidecar (HeadTTS) provisioning for a fresh machine.
#
# Clones met4citizen/HeadTTS (MIT) at a pinned commit into voice/headtts,
# installs its npm dependencies (working around a Windows-incompatible
# postinstall), applies two local patches, and pre-downloads the Kokoro
# model by starting the server once and issuing a real synthesis request.
#
# voice/headtts is fully gitignored; this script is the single source of
# truth for provisioning it. Requires: git, Node.js v20+ on PATH.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$headtts = "$root\voice\headtts"
$pinnedCommit = "c08f4ca8b3253b3e908e501486a1e068e606be5c"  # HeadTTS v1.3.0 (2026-07-02)

# ---------------------------------------------------------------- 1) clone
if (-not (Test-Path "$headtts\package.json")) {
    Write-Host "Cloning HeadTTS (pinned $pinnedCommit)..." -ForegroundColor Cyan
    New-Item -ItemType Directory -Force "$root\voice" | Out-Null
    git clone https://github.com/met4citizen/HeadTTS "$headtts"
    if ($LASTEXITCODE -ne 0) { throw "git clone failed" }
    Push-Location $headtts
    git checkout $pinnedCommit
    if ($LASTEXITCODE -ne 0) { Pop-Location; throw "git checkout $pinnedCommit failed" }
    Pop-Location
} else {
    Write-Host "voice/headtts already present, skipping clone." -ForegroundColor Yellow
}

# ---------------------------------------------------------------- 2) patches
Push-Location $headtts
try {
    # Windows postinstall fix + 127.0.0.1 bind (see voice/patch_headtts.mjs).
    node "..\patch_headtts.mjs"
    if ($LASTEXITCODE -ne 0) { throw "HeadTTS patching failed" }

    # ------------------------------------------------------------ 3) install
    if (-not (Test-Path "node_modules\@huggingface\transformers\package.json")) {
        Write-Host "Installing HeadTTS dependencies..." -ForegroundColor Cyan
        # --ignore-scripts: belt and braces vs. the original postinstall;
        # we create the cache dir ourselves right after.
        npm install --ignore-scripts
        if ($LASTEXITCODE -ne 0) { throw "npm install failed" }
    }
    node -e "require('fs').mkdirSync('./node_modules/@huggingface/transformers/.cache',{recursive:true})"

    # ----------------------------------------------- 4) model pre-download
    # Start the server once with the project config (port 8012, webgpu/q4)
    # and issue a real synthesis request so the Kokoro ONNX model lands in
    # node_modules/@huggingface/transformers/.cache. Afterwards the server
    # is fully offline-capable.
    Write-Host "Pre-downloading Kokoro model (first run only, ~100 MB)..." -ForegroundColor Cyan
    $proc = Start-Process -FilePath "node" `
        -ArgumentList "./modules/headtts-node.mjs", "--config", "../headtts.config.json" `
        -WorkingDirectory $headtts -WindowStyle Hidden -PassThru
    try {
        $deadline = (Get-Date).AddSeconds(60)
        $up = $false
        while (-not $up -and (Get-Date) -lt $deadline) {
            try {
                $hello = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8012/v1/hello" -TimeoutSec 2
                if ("$hello".StartsWith("HeadTTS")) { $up = $true }
            } catch { Start-Sleep -Milliseconds 500 }
        }
        if (-not $up) { throw "HeadTTS server did not come up on 127.0.0.1:8012" }
        Write-Host "Server up; issuing warm-up synthesis (downloads + compiles model)..." -ForegroundColor Cyan
        $body = '{"input":"Voice sidecar warm-up complete.","voice":"af_bella","language":"en-us","audioEncoding":"wav"}'
        $resp = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8012/v1/synthesize" `
            -ContentType "application/json" -Body $body -TimeoutSec 300
        if (-not $resp.audio) { throw "Synthesis returned no audio" }
        Write-Host ("Warm-up OK: {0} words, {1} visemes, {2} base64 audio chars." -f `
            $resp.words.Count, $resp.visemes.Count, $resp.audio.Length) -ForegroundColor Green
    } finally {
        if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force }
    }
    Write-Host "Voice sidecar ready. Model cache: voice\headtts\node_modules\@huggingface\transformers\.cache" -ForegroundColor Green
} finally {
    Pop-Location
}
