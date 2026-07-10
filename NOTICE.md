# Third-party components

This project uses the following third-party components. Package dependencies are declared in
`backend/requirements.txt` and `frontend/package.json`; the components below deserve explicit
attribution beyond a dependency line.

## Voice sidecar (optional, not committed to this repo)

- **[HeadTTS](https://github.com/met4citizen/HeadTTS)** by met4citizen — MIT License.
  `scripts/setup_voice.ps1` clones it at a pinned commit
  (`c08f4ca8b3253b3e908e501486a1e068e606be5c`, v1.3.0) into `voice/headtts/` (gitignored) and
  applies two local patches (`voice/patch_headtts.mjs`): a Windows-compatible postinstall and a
  127.0.0.1 bind. The HeadTTS source is never redistributed by this repository.
- **[Kokoro-82M](https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX-timestamped)**
  (ONNX, timestamped) — Apache License 2.0. Downloaded by HeadTTS at provisioning time;
  runs fully locally.

## 3D talking head (frontend)

- **[@met4citizen/talkinghead](https://github.com/met4citizen/TalkingHead)** — MIT License.
  npm dependency that renders the lip-synced 3D interviewer (with
  [three.js](https://threejs.org/), MIT).
- **Avatar models** (`frontend/public/avatars/*.glb`) — copied from the TalkingHead repository;
  created with [Ready Player Me](https://readyplayer.me/) (CC BY-NC 4.0) and
  [Avaturn](https://avaturn.me) (non-commercial use). **These models are licensed for
  non-commercial use only** — see `frontend/public/avatars/LICENSES.md` and replace them
  before any commercial use.

## RAG / embeddings

- **[sentence-transformers/all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2)**
  — Apache License 2.0. Downloaded from the Hugging Face Hub on first index build.
- **[FAISS](https://github.com/facebookresearch/faiss)** (faiss-cpu) — MIT License.
