# Realistic talking-head sidecar (2-tier: idle loop + Wav2Lip)

Optional GPU sidecar that powers the **Realistic** avatar tier: it turns a
character image + text into a lip-synced MP4 (text → Kokoro TTS on :8012 →
Wav2Lip). The main app auto-detects it via `/api/health.lipsync_engine` and
shows the "Realistic" toggle only when it's up; otherwise it falls back to the
Classic avatar.

Only `sidecar/service.py`, `sidecar/idle_loop.py` and `sidecar/gen_talkinghead.py`
are version-controlled. The heavy runtime bits (own CUDA venv, model weights,
bundled ffmpeg, caches) are gitignored and provisioned once with the steps below.

## 2-tier full-face motion

Wav2Lip only drives the *mouth*, so lip-syncing a single still portrait leaves
the eyes/head frozen — correct lips on a dead face. To make the *whole* face
feel alive without a second heavyweight model, the sidecar runs two tiers:

- **Tier 1 — idle loop (`idle_loop.py`, CPU-only, cached once per character):**
  pre-renders a short *seamless* looping video in which the whole head drifts
  with a subtle life-like motion (a slow elliptical sway + gentle "breathing"
  scale). Because the entire portrait is warped as one, eyes, nose and every
  feature move together — not just the mouth. Pure OpenCV affine warp: no GPU,
  no extra model, no extra venv. Cached to `sidecar/cache/idle/<character>.mp4`.
- **Tier 2 — Wav2Lip on the loop:** the existing mouth-sync runs *on top of*
  the looping video instead of the still image. Wav2Lip cycles the idle frames
  with `i % len(frames)`, so the loop repeats for the full length of each line
  at essentially Wav2Lip's own latency (~+3 s/line vs the frozen portrait on a
  6 GB 3060). Its per-input face-detection is cached like any other input, and a
  background pre-warm at startup detects every character's loop so steady-state
  lines are fast regardless of which interviewer the session picks.

If the idle loop can't be produced (or a frame ever fails face-detection), the
sidecar falls back to the still image, so it can never regress below the old
frozen-portrait behaviour. Set `TI_IDLE=0` to force the still-image path.

Learned blinks / gaze would need a neural idle generator (e.g. LivePortrait);
this idle tier is the safe, self-contained motion that ships with no extra deps.

## Chosen package

[`lipsync`](https://pypi.org/project/lipsync/) (mowshon/lipsync — a modern,
pip-installable Wav2Lip). Picked over MuseTalk/SadTalker because it is the only
pure-`pip` option (no mmcv/dlib/build-tools), fits a 6 GB GPU with headroom, and
is fast. Weights are LRS2-derived = **research/non-commercial** — fine for this
personal project. For a commercial deployment, swap to MuseTalk (MIT) — see
`docs/MUSETALK.md`.

## One-time provisioning (Windows, NVIDIA GPU)

```powershell
# from repo root
cd deepfake
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip

# CUDA torch (cu118 works on a 3060-laptop / driver 555)
.\.venv\Scripts\python.exe -m pip install torch==2.0.1+cu118 torchvision==0.15.2+cu118 torchaudio==2.0.2+cu118 --index-url https://download.pytorch.org/whl/cu118

# lipsync + a prebuilt PyAV wheel (its pinned `av` has no source-build on Win)
.\.venv\Scripts\python.exe -m pip install av lipsync --no-deps
.\.venv\Scripts\python.exe -m pip install face_alignment "librosa==0.10.2.post1" opencv-python numba "numpy<2" scipy tqdm fastapi "uvicorn[standard]"

# ffmpeg (static build) -> deepfake\bin\  (ffmpeg.exe, ffprobe.exe)
#   e.g. from https://github.com/BtbN/FFmpeg-Builds (win64-gpl), extract bin\ here

# Wav2Lip weights -> deepfake\sidecar\weights\
#   download wav2lip_gan.pth (e.g. HF mirror camenduru/Wav2Lip), then convert to
#   lipsync's bare-state_dict format:
.\.venv\Scripts\python.exe -c "import torch; ck=torch.load('sidecar/weights/wav2lip_gan.pth',map_location='cpu'); sd={k.replace('module.',''):v for k,v in (ck.get('state_dict',ck)).items()}; torch.save(sd,'sidecar/weights/wav2lip_gan_ls.pth')"
```

## Run

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_deepfake.ps1   # serves :8013
```

The main app's `POST /api/lipsync` proxies to it. Requests are GPU-serialized
(one clip at a time). The idle loop for a character is generated on first use
(CPU, instant) and its face-detection cached on first line (~15–25 s for the
whole loop, or hidden by the startup pre-warm), then ~10 s/line steady-state.
Responses carry `X-Face-Mode: idle|still` so you can see which tier served.
