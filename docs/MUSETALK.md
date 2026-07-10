# Photoreal deepfake lip-sync — the MuseTalk upgrade path

This app ships a **three-tier interviewer renderer** (toggle in the interview
room, top-right of the avatar):

| Tier | What it is | Lip-sync | Runs where |
| --- | --- | --- | --- |
| **Photo** (default) | An Imagen-4-generated photorealistic character (`frontend/public/interviewers/`, sampled per session), animated with a viseme-driven mouth + blink + idle breathing | Real-time, from the Kokoro viseme timeline we already have | 100% in-browser, zero extra deps |
| **3D** | `@met4citizen/talkinghead` with photo-realistic GLB avatars (Avaturn / Avatar SDK) | Real-time, genuine morph-target visemes | In-browser (WebGL) |
| **Classic** | Hand-drawn SVG avatar | Viseme mouth shapes | In-browser |

The **Photo** tier gives you a real photorealistic face that lip-syncs to the
spoken text in real time, with no server round-trip. It deliberately does **not**
try to fake precise phoneme mouth shapes on the still (which reads as uncanny).

## Why not a true "deepfake" out of the box?

We researched the open-source landscape (see the `lipsync-research` workflow).
The honest conclusion: **photorealistic AND true real-time in-browser lip-sync
do not coexist in open source today.** Every neural talking-photo model
(Wav2Lip, SadTalker, VideoReTalking, EchoMimic, Hallo, AniPortrait) is a batch
PyTorch/GPU pipeline that renders a *video file* offline (seconds to minutes per
clip) and/or ships **non-commercial** weights. There is no mature WASM/WebGL 2D
photo-deepfake engine.

The **one** credible option is **MuseTalk** — and it needs a local GPU server.

## MuseTalk (TMElyralab) — the deepfake upgrade

- **License:** MIT on **both code and weights** (commercially usable) — the key
  differentiator vs every other real-time-ish option.
- **Input:** a single still image (our Imagen character) → lip-syncs a short
  looping idle clip to arbitrary audio.
- **Speed:** ~30 fps (33 ms/frame) on an RTX 3090/4090-class GPU; sub-second
  first-frame *after* a one-time per-avatar "preparation" pass. On a weak GPU it
  is NOT real-time — this is a hard GPU dependency.
- **Quality caveat:** 256×256 mouth/face inpaint region, static head, occasional
  jitter. Good, not 4K.

### Architecture (drops into the existing seam)

`frontend/src/lib/voice.ts` already exposes a `VoiceSink` interface
(`speak(chunk) / marker / interrupt`). The 3D head is one implementation; a
**`MuseTalkSink` is a drop-in second one** — the plumbing already exists.

```
Kokoro TTS (/api/voice/tts)  ──audio──►  MuseTalk GPU service  ──frames──►  <video>/<canvas>
        (existing)                        (new, local :PORT)                 MuseTalkSink
```

Because you need the audio *before* you can lip-sync it, Kokoro and MuseTalk run
**sequentially**, so they don't fight for the GPU at the same instant.

### Steps to enable (roughly a day of work + a good GPU)

1. **Stand up MuseTalk locally** (its own Python venv, CUDA PyTorch, download the
   MIT weights): `git clone https://github.com/TMElyralab/MuseTalk`, follow its
   README, expose a small FastAPI endpoint `POST /lipsync {image_id, audio_wav}`
   → streamed 256×256 frames (or a short MP4 per utterance).
2. **Per-character preparation at generation time** (not on the hot path): when
   `scripts`/the Imagen generator creates a character, also run MuseTalk's
   face-detect/align + VAE-latent precompute once and cache the artifacts; and
   generate a 2–3 s subtle idle loop (blink/micro-motion) to drive.
3. **Backend proxy:** add `TI_MUSETALK_URL` to `backend/app/config.py` and an
   `/api/lipsync` proxy in `routes_voice.py` (mirror the `/api/voice/tts` proxy).
4. **Frontend `MuseTalkSink`:** implement the `VoiceSink` interface in
   `voice.ts` to POST the chunk audio to `/api/lipsync` and render returned
   frames into a `<video>`/`<canvas>`, using the same marker callbacks the 3D
   head uses. Add a `musetalk` avatar mode in `TalkingHeadAvatar.tsx`, gated on a
   health probe of the service (transparent fallback to the Photo tier).

Keep the **Photo tier as the reliable default and fallback** — enable MuseTalk
behind the toggle/health-probe so a missing or slow GPU service never breaks the
interview.
