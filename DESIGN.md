# Technical Interviewer — Architecture Contract

This document is the **binding contract** for all implementation agents. It maps 1:1 to
`technical_interviewer_software_specification.pdf`. Where the spec says "recommended", this
contract makes the concrete choice. Do not deviate without recording the deviation.

## 0. Environment (fixed)

- Python: 3.10+ in a virtualenv (see README for setup; CI runs 3.10). **Every Python process must set env
  `USE_TF=0` before importing transformers/sentence_transformers** (guards against machines
  with a broken TensorFlow install). Set it defensively at the top of entrypoints via
  `os.environ.setdefault("USE_TF", "0")` **before** any ML import.
- Node v20+ and npm available on PATH.
- Local wiki (optional): a directory of markdown notes at `wiki/` in the repo root, or wherever
  env `TI_WIKI_DIR` points. Development used a personal AI/ML/DS knowledge base
  (`concepts/*.md` ~204 files, `sources/*.md`, `index.md`): markdown with a `**Summary**:` line,
  Obsidian `[[wiki-links]]`, `## In the sources`, `## Related pages` sections. The app must
  boot and run fully without it (retriever reports unloaded; wiki grounding is skipped).
- Claude Code CLI v2.1.195 on PATH as `claude` (headless: `claude -p "<prompt>" --output-format json`).
- No ANTHROPIC_API_KEY / OPENAI_API_KEY currently set. No `codex` CLI. The spec's "Codex agents"
  are implemented as agent roles running on the LLM provider chain (below).
- Installed py packages: fastapi, uvicorn, websockets(12), sqlalchemy, aiosqlite, pydantic v2,
  sentence-transformers, faiss-cpu, torch(cuda), pypdf, anthropic, cryptography, bs4, httpx,
  pytest, pytest-asyncio, jinja2, python-multipart.
- Backend port: **8011**. Vite dev port: 5173 (proxy `/api` and `/ws` → 8011).

## 1. Repository layout & file ownership

```
Technical_Interviewer/
  DESIGN.md                     (this file)
  README.md                     [owner: integrator]
  scripts/
    index_wiki.py               [B] build FAISS index from wiki
    run_qa.py                   [B] run Codex QA Agent, print spec-format QA report
    start.ps1                   [integrator] one-command run (backend serves built frontend)
    dev.ps1                     [integrator]
  backend/
    requirements.txt            [pinned already]
    pytest.ini                  [D]
    app/
      __init__.py               [A]
      config.py                 [pinned already — do not rewrite, extend only if essential]
      schemas.py                [pinned already — do not rewrite; single source of truth]
      main.py                   [A] FastAPI app: REST routers + WS route + static serving of ../frontend/dist if exists
      database.py               [A] SQLAlchemy engine/session (sqlite: backend/data/app.db)
      models.py                 [A] ORM models
      security/crypto.py        [A] Fernet encrypt/decrypt; key auto-generated at backend/data/secret.key
      api/
        __init__.py routes_users.py routes_sessions.py routes_reports.py
        routes_privacy.py routes_misc.py            [A]
      ws/interview_ws.py        [A] WebSocket endpoint /ws/interview/{session_id}
      core/
        orchestrator.py         [A] interview state machine
        question_selector.py    [A] bank filtering, no-dup selection
        hints.py                [A] hint policy + 5 levels + penalty
        scoring.py              [A] weighted formula + role weights (calls llm/scorer for raw metrics)
        report_generator.py     [A] final report (all spec §8 fields), recoverable
        transcript.py           [A] autosaving transcript store (encrypted at rest)
        parsing.py              [A] resume (pdf via pypdf + txt) & job description parsing → topics/skills
      llm/
        provider.py             [B] provider chain: AnthropicAPI → ClaudeCLI → Offline
        interviewer.py          [B] greeting/question phrasing/followup/checkin/closing generation
        scorer.py               [B] evaluate_answer() → MetricScores (LLM w/ JSON schema, heuristic fallback)
      rag/
        indexer.py              [B] chunking + embedding + FAISS build
        retriever.py            [B] WikiRetriever.search()
      agents/
        research_agent.py       [B] internet research (untrusted-content hardened), source logging, bank update
        planning_agent.py       [B] interview plan builder (spec §6.2 output shape)
        qa_agent.py             [B] runs tests/latency/scoring-consistency/security checks → spec §12.3 report
    data/
      question_bank.json        [B] seed bank (≥120 questions, schema below)
      wiki_index/               (generated)
    tests/
      unit/  ai_logic/  integration/   [D]
      conftest.py fixtures/            [D]
  frontend/                      [C] Vite + React 18 + TS + Tailwind + Zustand
    src/pages: SetupPage InterviewPage ReportPage SessionsPage
    src/components: Avatar TranscriptPanel Timer SectionIndicator ScoreDashboard HintButton
                    VideoPreview Controls SetupForm
    src/lib: api.ts ws.ts speech.ts store.ts types.ts
    src/__tests__/ (Vitest + @testing-library/react, jsdom)
```

Owners: **A** = backend-core agent, **B** = ai-rag-agents agent, **C** = frontend agent,
**D** = test agent (runs after A+B). Never write outside your owned files.

## 2. Domain enums (exact strings, everywhere incl. DB and TS)

- roles: `"Data Scientist" | "Algorithm Researcher" | "AI Engineer"`
- modes: `"Quick Practice" | "Standard" | "Deep Research"` (10–20 / 45–60 / 60–90 min).
  These are the wire/DB values; the UI **displays** "Deep Research" as "Deep Dive" via
  `MODE_LABELS`/`modeLabel` (frontend/src/lib/types.ts). Do not rename the enum value.
- difficulty: `"Junior" | "Mid-level" | "Senior" | "Research-level" | "Staff/Lead-level"`
- hint_policy: `"none" | "on_request" | "adaptive"`
- interviewer_style: `"Friendly" | "Strict" | "Research professor" | "Startup CTO" | "Big-tech interviewer"`
- session status: `"created" | "planning" | "ready" | "active" | "paused" | "completed" | "cancelled"`
- question source: `"local_wiki" | "internet" | "generated" | "seed"`
- languages: `"en" | "he"` (+ free string). UI offers English and Hebrew (`LANGUAGES` in
  frontend/src/lib/types.ts). Hebrew runs the interview room right-to-left, uses `he-IL`
  Web-Speech recognition, and synthesizes via the browser's Hebrew voice (the Kokoro sidecar
  is English-only, so non-`en` lines skip it). Interviewer/scorer text is produced in Hebrew by
  the LLM (`_lang_directive`); fully-offline Hebrew uses Hebrew fallback templates for the
  persona lines, but bank question bodies stay English offline (translation needs the LLM).

Track topics (spec §5) — use these exact topic lists for bank/plan/filtering:
- Data Scientist: Python, SQL, Statistics, Probability, A/B testing, Experiment design,
  Feature engineering, Supervised learning, Unsupervised learning, Model evaluation,
  Business case reasoning, Data cleaning, Communication of insights
- Algorithm Researcher: Algorithms, Data structures, Complexity analysis, Probability,
  Optimization, Graph algorithms, Dynamic programming, Mathematical proofs,
  Research paper understanding, Experimental design, Benchmarking
- AI Engineer: Deep learning, Transformers, LLMs, RAG, Embeddings, Fine-tuning, Evaluation,
  Agents, MLOps, Model serving, Latency optimization, Distributed training, GPU memory,
  Safety and monitoring

## 3. REST API (all under /api, JSON; FastAPI)

- `GET  /api/health` → `{status:"ok", version, llm_provider, wiki_index_loaded}`
- `POST /api/users` `{name, target_roles[]}` → UserOut
- `GET  /api/users/{user_id}` → UserOut
- `GET  /api/users/{user_id}/sessions` → SessionOut[]
- `POST /api/sessions` SessionCreate (schemas.py) → SessionOut (status becomes `ready` after
  synchronous planning; planning = research agent (if allow_internet) + planning agent + RAG.
  Must complete < 30s; internet research has an 8s overall cap and falls back gracefully.)
- `GET  /api/sessions/{id}` → SessionOut (includes plan)
- `GET  /api/sessions/{id}/transcript` → TranscriptOut
- `GET  /api/sessions/{id}/report` → ReportOut (404 w/ detail "not ready" if absent;
  `POST /api/sessions/{id}/report/regenerate` recovers a failed generation)
- `GET  /api/sessions/{id}/sources` → SourceCitationOut[]
- `DELETE /api/sessions/{id}` (full delete) ; `DELETE /api/sessions/{id}/transcript` ;
  `DELETE /api/sessions/{id}/recording`
- `GET  /api/question-bank?role=&difficulty=&topic=` → QuestionBankItem[]
- `POST /api/rag/search` `{query, k=5}` → `{results:[{text, source, score}]}`
- `POST /api/qa/run` → `{report: str, passed: bool}` (runs qa_agent; may take ~min)

## 4. WebSocket protocol — `/ws/interview/{session_id}`

All messages JSON `{type, ...}`. Server drives the interview; client renders + speaks.

Client → Server:
- `{"type":"start"}` — begin/resume delivery
- `{"type":"answer","text":str,"duration_seconds":float,"input_mode":"voice"|"text"}`
- `{"type":"partial_transcript","text":str}` — live partial (persist last partial as safety)
- `{"type":"hint_request"}`
- `{"type":"silence","seconds":float}` — client-detected silence (send at ≥12s stuck)
- `{"type":"interrupt"}` — user began speaking over TTS
- `{"type":"pause"}` / `{"type":"resume"}` / `{"type":"skip"}` / `{"type":"end"}`
- `{"type":"more_time_response","wants_more_time":bool}`

Server → Client:
- `{"type":"interviewer","kind":"greeting"|"question"|"followup"|"checkin"|"ack"|"closing",
   "text":str,"section":str,"question_id":str|null,"question_index":int,"total_questions":int}`
- `{"type":"hint","level":1-5,"text":str,"question_id":str,"hints_used":int}`
- `{"type":"score","question_id":str,"scores":{correctness,depth,clarity,structure,practicality,
   mathematical_rigor,tradeoff_awareness,communication},"overall":float,"feedback":str}`
- `{"type":"section_change","section":str,"section_index":int,"total_sections":int}`
- `{"type":"state","status":"active"|"paused"|"completed","elapsed_seconds":float,
   "remaining_seconds":float}`
- `{"type":"report_ready","session_id":str}`
- `{"type":"error","message":str}`

Flow (spec §6.3): greeting → background question → per plan section: technical questions →
answer → (optional followup, max 1 per question, decided by `llm/interviewer.decide_followup`) →
score each major answer (background/behavioral answers get scored too but flagged
`is_behavioral`) → adaptive hint offer if `silence` and policy allows → closing → report
generated in background task → `report_ready`.

## 5. Data model (SQLAlchemy; spec §11 superset)

- `User(id uuid str pk, name, target_roles json, created_at)`
- `InterviewSession(id, user_id fk, role, mode, difficulty, duration_minutes, language,
   hint_policy, interviewer_style, use_resume, use_job_description, use_wiki, allow_internet,
   record_session, disable_cloud_ai, resume_text_enc, job_description_enc, plan json,
   status, overall_score float|null, current_section_idx, current_question_idx,
   elapsed_seconds float, created_at, completed_at|null)`
- `Question(id, session_id fk, topic, difficulty, question_text, source, expected_points json,
   section, order_idx, is_behavioral bool, asked_at|null)`
- `Answer(id, question_id fk, transcript_enc, duration_seconds, hints_used int, created_at)`
- `Score(id, answer_id fk, correctness, depth, clarity, structure, practicality,
   mathematical_rigor, tradeoff_awareness, communication  # all int 1-5
   , overall float, feedback text)`
- `TranscriptEntry(id, session_id fk, ts, speaker "interviewer"|"candidate"|"system", text_enc)`
- `SourceCitation(id, session_id fk|null, url, title, quality "high"|"medium"|"rejected",
   fetched_at, notes)`
- `Report(id, session_id fk unique, content_enc json-str, created_at, generation_failed bool)`

`*_enc` columns hold Fernet-encrypted text (security/crypto.py). Transcript autosaves on every
message. Report content JSON = ReportOut in schemas.py.

## 6. Scoring (spec §7.5)

8 metrics, each int 1–5. Weighted overall (0–5, round 2dp). Weights by role (sum = 1.0):

| metric              | base/DS-adj      | Data Scientist | Algorithm Researcher | AI Engineer |
|---------------------|------------------|----------------|----------------------|-------------|
| correctness         | 0.30             | 0.30           | 0.25                 | 0.25        |
| depth               | 0.20             | 0.15           | 0.20                 | 0.15        |
| clarity             | 0.15             | 0.10           | 0.10                 | 0.10        |
| structure           | 0.10             | 0.10           | 0.10                 | 0.10        |
| practicality        | 0.10             | 0.15           | 0.05                 | 0.15        |
| mathematical_rigor  | 0.00             | 0.10           | 0.15                 | 0.00        |
| tradeoff_awareness  | 0.10             | 0.05           | 0.10                 | 0.20        |
| communication       | 0.05             | 0.05           | 0.05                 | 0.05        |

(The "base" column is the spec's suggested formula and is used for unknown roles.)
Hint penalty: `overall = max(1.0, overall - 0.15 * hints_used)` applied by core/scoring.py.
`core.scoring.compute_overall(metrics: MetricScores, role: str, hints_used: int) -> float` is pure
and unit-tested. Raw metrics come from `llm/scorer.evaluate_answer(...)`.

## 7. Module interfaces A↔B (pin exactly)

```python
# app/rag/retriever.py  [B]
class WikiRetriever:
    def __init__(self, index_dir: str = settings.wiki_index_dir): ...
    @property
    def loaded(self) -> bool: ...
    def search(self, query: str, k: int = 5) -> list[RagResult]  # schemas.RagResult
def get_retriever() -> WikiRetriever  # cached singleton; returns unloaded-but-safe object if no index

# app/llm/provider.py  [B]
class LLMProvider:  # chain facade
    name: str
    def complete_text(self, system: str, prompt: str, max_tokens: int = 800, timeout: float = 20.0) -> str
    def complete_json(self, system: str, prompt: str, schema_model: type[BaseModel],
                      timeout: float = 30.0) -> BaseModel  # validated; falls down chain on failure
def get_provider(disable_cloud_ai: bool = False, fast_only: bool = False) -> LLMProvider
# Chain: AnthropicAPI (if key & not disabled) → ClaudeCLI (local, allowed even when cloud disabled;
# it is the configured local agent runtime) → Offline (always succeeds, deterministic).
# NOTE: ClaudeCLI is skipped when env TI_DISABLE_CLAUDE_CLI=1 (tests set this for speed/determinism).
# DECIDED DEVIATION: fast_only=True drops ClaudeCLI from the chain (10-20s per headless call).
# The live WS loop and synchronous session planning use fast_only=True to meet their 2.5s/30s
# budgets; only background report generation uses the full chain including the CLI.

# app/llm/scorer.py  [B]
def evaluate_answer(question: QuestionBankItem | QuestionOut, transcript: str, role: str,
                    context_snippets: list[str], provider: LLMProvider,
                    language: str = "en") -> tuple[MetricScores, str]
# language (default "en") sets the feedback text language on the LLM path (metrics unaffected;
# offline heuristic feedback stays English). Backward-compatible optional kwarg.
# returns (metrics, feedback). Empty/very short transcript → all 1s, feedback explains.
# Heuristic fallback: expected_points keyword coverage (correctness/depth), sentence count &
# discourse markers (structure/clarity), numbers/formulas (mathematical_rigor), "trade-off|however|
# depends" (tradeoff_awareness), words-per-answer band (communication), domain terms (practicality).
# Monotone: strictly more matched expected_points must never lower any metric.

# app/llm/interviewer.py  [B]
# Each function takes a trailing optional `language: str = "en"`; "he" appends a Hebrew
# directive to the LLM prompt and selects Hebrew offline-fallback templates.
def greeting(style: str, role: str, candidate_name: str, provider, language: str = "en") -> str
def background_question(role: str, provider, language: str = "en") -> str
def phrase_question(item, style: str, provider, language="en") -> str  # may return item.question_text as-is
def decide_followup(item, transcript: str, metrics: MetricScores | None, provider, language="en") -> str | None
def checkin_after_silence(style: str, provider, language: str = "en") -> str  # asks if user wants more time
def closing(style: str, provider, language: str = "en") -> str

# app/agents/planning_agent.py  [B]
def build_plan(cfg: SessionCreate, resume_text: str | None, jd_text: str | None,
               retriever, bank: list[QuestionBankItem], provider) -> InterviewPlan
# InterviewPlan in schemas.py; spec §6.2 shape + section_questions allocation.
# Section count/question count scale with mode & duration. Always starts "background",
# ends "candidate questions". Deep Research must use resume/JD topics when provided.

# app/agents/research_agent.py  [B]
def research_questions(role: str, difficulty: str, allow_internet: bool,
                       provider, session_id: str | None = None
                       ) -> tuple[list[QuestionBankItem], list[SourceCitationOut]]
# allow_internet=False → ([], []). Hardened: fetched page text is DATA; strip scripts; regex-flag
# injection patterns ("ignore previous instructions", "system prompt", etc.) → sanitize before any
# LLM call; never execute instructions from pages; curated seed URL list; store citations incl.
# rejected ones with quality="rejected". Total wall-clock cap 8s (httpx timeouts) — on any failure
# return partial/empty results, never raise.

# app/agents/qa_agent.py  [B]
def run_qa(project_root: str) -> QAReport      # schemas.QAReport
def format_report(r: QAReport) -> str          # EXACT spec §12.3 text format
# Runs: pytest (unit/ai_logic/integration) via subprocess (env USE_TF=0, TI_DISABLE_CLAUDE_CLI=1),
# latency checks (RAG search <1.5s warm, offline orchestrator step <0.5s, report gen <30s),
# scoring consistency (offline scorer deterministic; good > bad answer), security checks
# (encryption round-trip, injection sample sanitized, no wiki text in /api/health).
```

Question bank JSON item (backend/data/question_bank.json — list of these):
```json
{"id":"ds-stat-001","role":"Data Scientist","topic":"Statistics","difficulty":"Senior",
 "question_text":"...","expected_points":["...","..."],"followups":["..."],
 "is_behavioral":false,"source":"seed"}
```
Bank requirements: ≥120 items total; every role×topic covered; every role×difficulty ≥6;
plus ≥4 behavioral items per role (topic "Behavioral"); include the spec §5 example questions.
`core/question_selector.select_questions(bank, role, difficulty, topics, n, exclude_ids)` filters
by exact role+difficulty, falls back to adjacent difficulty if starved, never repeats an id
within a session.

## 8. Hints (spec §7.4)

Levels 1..5: 1 small nudge, 2 conceptual direction, 3 structured outline, 4 partial answer,
5 full explanation (only after scoring). Policy none/on_request/adaptive.
`core/hints.py`: `next_hint(question, hints_used, provider) -> (level, text)`; hint text via
provider with offline fallback built from expected_points (level1: first point as nudge-question;
level3: outline = bulleted expected_points; level4: half the points expanded). Each hint
increments Answer.hints_used → scoring penalty (§6). Adaptive: orchestrator offers hint after
`silence` message or after a scored answer with correctness ≤ 2.

## 9. Final report (spec §8) — ReportOut fields (schemas.py)

overall_score (0-100 int = mean overall of scored answers × 20), role_readiness (0-100 with
difficulty modifier: Junior ×1.0 … Staff ×0.9 documented in code), topic_scores{topic: 0-5},
best_answers[{question, score, why}], weakest_answers[...], missing_concepts[] (expected_points
not covered + RAG-suggested wiki concepts), communication_feedback str, technical_feedback str,
suggested_study_plan[≥3 items], recommended_next_interview{role, mode, difficulty, focus_topics},
questions_asked[], transcript_summary str, hints_used_total int, time_per_question[{question_id,
seconds}]. Text sections via provider (offline fallback composes from scores/topics).
Generation must be recoverable: on failure Report.generation_failed=True and regenerate endpoint.

## 10. Frontend requirements (spec §7.1–7.3, §13.3)

- SetupPage: full form — role, mode, difficulty (duration is derived from the mode; the manual
  duration slider was removed as confusing),
  language, hint policy, interviewer style, toggles (resume upload .pdf/.txt + JD textarea,
  use wiki, allow internet research, record session, disable cloud AI), name. Validation with
  clear errors (required role/mode/difficulty; duration in mode range). POST /api/users +
  /api/sessions → navigate /interview/:id.
- InterviewPage: video-call layout. Left: avatar panel (large) + candidate `getUserMedia` preview
  (bottom-right thumbnail, mirrored). Right: live transcript panel (auto-scroll, speaker-labeled,
  partial line italic). Top bar: timer (mm:ss elapsed / remaining), current section indicator,
  status. Bottom controls: mic toggle, Hint button (hidden when policy none; shows hints_used),
  Skip, Pause/Resume, End Interview (confirm dialog), text-input fallback box (always available).
  Camera/mic permission denied → visible fallback states (camera: initials tile; mic: text mode
  banner). Score toast/badge after each scored answer. Silence detection: no final result & no
  typing for 12s while a question is open → send `silence`.
- speech.ts: webkitSpeechRecognition wrapper (continuous, interimResults → `partial_transcript`,
  final → answer submit on stop-of-speech OR explicit Send). speechSynthesis for interviewer
  lines; `onboundary`/word events drive avatar mouth; starting recognition while speaking sends
  `interrupt` + `speechSynthesis.cancel()`.
- Avatar.tsx: pure SVG synthetic character (obviously non-photoreal but professional): head,
  shoulders, eyes (blink every 3–6s random), animated mouth (4 viseme shapes cycling while
  speaking), subtle idle sway; 5 style variants change palette/accessory (Friendly warm,
  Strict navy+glasses, Research professor beard+blazer, Startup CTO hoodie, Big-tech badge).
  Props: `{style, speaking: boolean, name}`.
- ReportPage: renders every ReportOut field; radar/bar of topic_scores (pure SVG, no chart lib);
  study plan checklist; "Start recommended interview" button prefills setup.
- SessionsPage: session list w/ status/score, links to report, privacy actions (delete session /
  transcript / recording) with confirmation.
- store.ts (Zustand): session config, ws state, transcript entries, scores, timer, hints.
- Tests (Vitest+RTL, jsdom): setup validation, role/mode selection, timer render, transcript
  display, score dashboard, report rendering, camera-denied, mic-denied, pause/resume, end flow.
  Mock WebSocket/speech/media APIs in test setup.

## 11. Non-functional (spec §14)

- Latency: no LLM call may block > 20s (provider timeout → fallback down chain). Offline path
  responds instantly. UI shows "thinking" indicator during waits. Partial transcripts are
  client-side (<500ms by construction). Report < 30s (offline fallback guarantees).
  DECIDED DEVIATION from spec §7.3: the 2.5s interviewer-response and 1.5s final-transcript
  targets are met by construction on the fast chain (offline instant; final transcript is
  client-side) but are not hard-enforced when the Anthropic API is slow — the 20s provider
  timeout with a visible thinking indicator is the enforced bound.
- Security: Fernet encryption at rest for resume/JD/transcript/report; wiki never exposed except
  via explicit /api/rag/search; recordings only when record_session (MVP: recording = storing
  transcript audio flag; no actual A/V storage — document this); full deletion endpoints;
  all internet sources logged as SourceCitation; synthetic avatar only, no real-person likeness.
- Reliability: WS reconnect (client retries 3× with backoff, server resumes from session state);
  transcript autosave per message; report regenerate endpoint.
- Privacy toggles honored server-side: allow_internet=False → research agent never fetches;
  disable_cloud_ai=True → Anthropic API skipped (CLI+offline only).

## 12. Testing (spec §13) — owner D (backend) / C (frontend)

Backend pytest layout: tests/unit/test_users.py test_sessions.py test_question_selection.py
test_difficulty_filter.py test_hints.py test_scoring.py test_report.py test_transcript.py
test_parsing.py test_rag.py test_citations.py ; tests/ai_logic/test_no_duplicates.py
test_followup_relevance.py test_score_schema.py test_empty_answer.py test_score_quality.py
test_hint_penalty.py test_role_rubric.py test_injection.py ; tests/integration/test_full_flow.py
(TestClient: create user+session offline (use_wiki fixture index, allow_internet False,
TI_DISABLE_CLAUDE_CLI=1) → WS: start→greeting→background→answer→question→answer→followup→score→
end→report ready with all fields). RAG tests use a tiny fixture index built from 3 markdown files
in tests/fixtures/mini_wiki (build in conftest with the real indexer, k=2 — keep runtime sane by
scoping sentence-transformers model load to session fixture).
All tests must pass with no network and no API key.

## 13. Voice & talking-head avatar (spec §7.2/§7.3 V1+ upgrade)

- **TTS**: HeadTTS sidecar (`voice/headtts`, pinned c08f4ca, MIT) running
  Kokoro-82M-v1.0-ONNX-timestamped (Apache-2.0) on webgpu/**fp32** — full-precision audio with
  no quantization artifacts, measured steady-state ~0.7–0.9s per sentence (RTF≈0.1) on this GPU.
  (Verified 2026-07-03: fp16/q4f16 emit silent audio on this GPU, q8 crashes onnxruntime's
  webgpu DequantizeLinear, CPU fp32 is unusable (RTF~4); q4 works but sounds audibly robotic —
  fp32/webgpu is the only full-quality working combination.) Port 8012, REST+WS, provisioned by
  `scripts/setup_voice.ps1`,
  launched+warmed by start/dev scripts. Same-origin proxy `POST /api/voice/tts` mirrors
  `/v1/synthesize`: `{input, voice, language, speed, audioEncoding}` →
  `{audio: b64 wav 24kHz, words/wtimes/wdurations, visemes/vtimes/vdurations (Oculus), phonemes}`.
  `/api/health.voice_engine` = `headtts|unavailable` (0.5s probe, 10s cache).
- **Frontend** `src/lib/voice.ts` VoiceEngine: sentence-chunked pipeline (short first chunk,
  1-ahead prefetch, gapless AudioContext scheduling, utterance FIFO), rAF word/viseme timeline,
  `interrupt()` aborts fetches+sources, health-gated transparent fallback to speechSynthesis,
  `STYLE_VOICES` style→(voice,speed) map, sink for the 3D head.
- **Avatar** — the interview always renders the real-time **3D talking head**
  (`src/components/TalkingHeadAvatar.tsx`: `@met4citizen/talkinghead` (MIT) + three, lazy-loaded;
  raw HeadTTS payloads via `speakAudio`; two photo-realistic GLBs — Avaturn + Avatar SDK,
  gender-matched to voices; `frontend/public/avatars/LICENSES.md`). Built-in idle blink/sway/mood;
  mouth animation is viseme-driven from the TTS word/viseme timeline (standard 3D morph-target
  animation). Fallback: the SVG `Avatar.tsx` when WebGL is unavailable or the 3D stack fails to
  load. The interview begins behind a **"Start interview"** gesture (InterviewPage) that unlocks
  audio autoplay and requests the **microphone (on by default)** before connecting the WS.
  A photorealistic still character portrait (`frontend/public/interviewers/`, one fixed face per
  interviewer style via `lib/characters.ts`, gender always matching the style's voice) is shown on
  the start gate and loading screens.
- Character generation: `scripts`/tmp Imagen-4 pipeline (Gemini key from Secret Manager
  `gemini-api-key`); 12 characters (3 roles × 2F/2M), ~60KB JPEG each.
- Measured: warm idle first-audio ~450ms; ~1.8–2.7s under concurrent LLM CPU load; mouth-animation
  offset ≈ 0ms by construction (viseme timeline ships with the audio).

## 14. Progress tracking & study curriculum (spec §16)

`GET /api/users/{user_id}/progress` (ProgressOut in schemas.py): completed sessions
chronological, `readiness_trend` (0-100 per session from reports), `topic_trends`
(topic → per-session 0-5 from Score.overall via Answer→Question), `current_weak_topics`
(last-2-session avg < 3.0) / `current_strong_topics` (≥ 4.0), and `curriculum` — weak topics
(session mean < 3.5) + report missing_concepts, recency-weighted 3/2/1, case-insensitive
dedupe, priority by rank tertiles (1=Now/2=Next/3=Later), capped 15, `wiki_refs` from the RAG
retriever when loaded. Deterministic, no LLM calls (`core/progress.py`). Frontend:
`ProgressPage` at /progress (SVG readiness line chart, topic delta rows, weak/strong chips,
curriculum checklist persisted in localStorage `ti_curriculum_done`, session history table).

## 15. Codex QA Agent report format (exact, spec §12.3)

```
QA Status: PASS
Critical Issues:
- ...
Missing Tests:
- ...
Latency Problems:
- ...
Security Concerns:
- ...
Recommended Fixes:
- ...
```
(“- none” under a heading when empty.)
