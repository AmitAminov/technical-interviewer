# Natural barge-in with adaptive reply — design

**Date:** 2026-07-07
**Branch:** portfolio-polish
**Status:** approved (design), pending implementation plan

## Problem

The interviewer speaks each line to completion and only listens to the
candidate afterward. A candidate cannot interrupt ("wait, can you repeat
that?", "I don't follow") the way a real interviewer conversation allows.
We want the candidate to be able to talk over the interviewer; the interviewer
should stop, react appropriately to the interjection, and continue naturally.

## Grounding facts (current code)

- **The mic is already always-on.** `speech.ts createRecognizer` runs
  `continuous + interimResults` with auto-restart on `onend`; it never stops
  until `stop()`. The frontend simply *ignores* recognition results while the
  interviewer speaks.
- **Barge-in was deliberately disabled** (commit 6fd6333). The mic hears the
  interviewer's own TTS through the speakers, so acting on those results made
  the interviewer interrupt itself. `InterviewPage.sttSuppressed()` returns
  true while `store.speaking` (+ `STT_ECHO_GUARD_MS` 800ms tail); `onPartial`
  / `onFinal` early-return when suppressed.
- **The frontend already sends `interrupt` and `partial_transcript`** over the
  WebSocket; `orchestrator._on_interrupt` is currently a **no-op** (returns a
  state ack only).
- **A cloud LLM already exists.** `app/llm/provider.py` is a provider chain
  (AnthropicAPI → ClaudeCLI → Offline) exposing `complete_text()`. The main
  interview flow (greeting, questions, hints, scoring) uses it.

Therefore this feature is: (A) un-gate the mic *safely* and detect a genuine
barge-in on the frontend, (B) add a backend reply path, (C) add one isolated
low-latency LLM link for the reply.

## Decisions (locked with the user)

1. **Behavior:** stop + adaptive reply. Interviewer stops mid-sentence; backend
   generates a short, phase-aware reply to the interjection, then normal flow
   continues. (Not stop-and-listen-only; not a full free-form conversational
   agent.)
2. **Reply LLM:** Gemini Flash, used **only** for the barge-in reply (fast,
   ~0.5–1s; `gemini-api-key` secret). Main question/scoring chain unchanged.
   Falls back to the existing provider chain → deterministic offline reply.

## Architecture

Three units, each independently testable.

### A. Frontend barge-in detection — `InterviewPage.tsx`, `speech.ts`

While the interviewer is speaking, instead of ignoring STT entirely, watch for
a **sustained candidate utterance**: a partial transcript reaching
`BARGE_IN_MIN_WORDS` (default **3**) words while `store.speaking`.

On trigger:
1. `voiceEngine.interrupt()` — stop the interviewer's TTS immediately.
2. `useInterviewStore.getState().setSpeaking(false)`.
3. `socket.send({ type: 'barge_in', text: <partial so far> })`.
4. Stop suppressing STT (the interviewer has stopped, so no more echo) — the
   remainder of the candidate's utterance is captured normally as their turn.
   The trigger words are not lost: the recognizer finalizes the whole utterance
   (interim text accumulates into the eventual `onFinal`), so the full
   interjection — trigger words included — lands in the candidate's answer.

**Echo handling (the crux), two cheap layers — no custom DSP:**
- **Native AEC.** Change `enableMic`'s `getUserMedia({ audio: true })` to
  `getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true,
  autoGainControl: true } })`. The browser cancels the interviewer's audio out
  of the mic input. This is the single most important line.
- **Sustained threshold.** The 3-word minimum means a stray echoed word or an
  "mm-hmm" backchannel does not trigger a barge-in.
  `// ponytail: word-count heuristic; raise threshold or add a confidence/energy
  gate if false barge-ins show up in real use.`
- **Optional soft UX hint.** "For the most natural back-and-forth, use
  headphones" in the start gate. Headphones eliminate echo entirely.

`sttSuppressed()` is refined: fully suppress only for the `STT_ECHO_GUARD_MS`
tail after the interviewer stops (echo decay); during active speaking, feed
partials to the barge-in detector instead of dropping them.

### B. Backend adaptive reply — `orchestrator.py`

- Register a new `barge_in` handler in the `handle()` dispatch map (alongside
  the existing `interrupt` no-op, which stays for plain mic-toggle TTS-cancel).
- `_on_barge_in(db, sess, m)`:
  1. Persist the interjection text to the transcript (partial upsert, reusing
     the `_on_partial` machinery).
  2. Call `interviewer.barge_in_reply(context, interjection, phase, style,
     gemini_provider)`.
  3. If it returns a non-empty reply → return an `interviewer` message
     (`kind: "reply"`) that the frontend speaks via the existing `speakLine`.
  4. If it returns empty → return only a state ack (the candidate has started
     answering; the interviewer stays stopped and listens — no interjection).
- The candidate's original question stays open; their subsequent `answer`
  flows through the normal path.

**Prompt nuance (handles "natural" without a state machine):**
`barge_in_reply` instructs the model to return EITHER a 1–2 sentence reply
(when the candidate asked to repeat / clarify / pushed back) OR an empty string
(when the candidate has simply begun answering — do not interject). Context
includes the current question text, section/phase, and interviewer style.

### C. Gemini Flash provider — `app/llm/provider.py`, `interviewer.py`

- Add a `GeminiAPI` provider implementing the provider interface
  (`complete_text`, and `complete_json` if trivially needed). Calls the
  Generative Language API:
  `POST https://generativelanguage.googleapis.com/v1beta/models/<model>:generateContent?key=<GEMINI_API_KEY>`
  where `<model>` is a current Gemini Flash model (default `gemini-2.5-flash`),
  confirmed against the API's `ListModels` at implementation time.
- **Key loading mirrors `ANTHROPIC_API_KEY`.** Read `GEMINI_API_KEY` from
  `config.settings` / env, injected by the start script from Secret Manager
  (`gcloud secrets versions access latest --secret=gemini-api-key`), exactly
  the way the Anthropic key is provided. No key is printed or committed.
- **Isolation:** Gemini is NOT inserted at the head of the global chain. A
  dedicated accessor (e.g. `get_fast_provider()`), or the Gemini provider
  passed explicitly into `barge_in_reply`, keeps the main flow untouched.
- **Fallback chain for the reply:** Gemini error/timeout → existing provider
  chain (`complete_text`) → deterministic offline reply
  (e.g. "Sure — let me clarify. <re-state current question>").

## Data flow

```
candidate talks over interviewer
  → recognizer onPartial (while store.speaking)
  → partial ≥ BARGE_IN_MIN_WORDS
  → frontend: voiceEngine.interrupt(); setSpeaking(false);
              send barge_in{text}; un-suppress STT
  → backend _on_barge_in
      → persist interjection
      → Gemini Flash barge_in_reply(context, interjection, phase, style)
          → non-empty reply  → interviewer{kind:"reply"} → frontend speaks it
          → empty            → state ack only (stay stopped, keep listening)
  → candidate continues / answers → normal answer + scoring flow
```

## Error handling

- Gemini timeout/error → existing provider → offline canned reply. Never hangs.
- False-positive barge-in (echo past AEC + threshold): interviewer stops and
  gives a brief reply — mildly annoying, not broken; threshold is tunable.
- `interrupt` message retained for explicit TTS cancel (mic toggle); `barge_in`
  is the new adaptive path. The two do not conflict.

## Testing

- **Frontend unit:** partial ≥ threshold while speaking → `voiceEngine.interrupt`
  called + `barge_in` sent + speaking cleared; partial < threshold → ignored;
  after barge-in, the ongoing utterance is captured (not suppressed). Extend the
  interview test helper (which already stubs `voiceEngine`).
- **Backend unit:** `_on_barge_in` returns an `interviewer` reply when the
  (mocked) reply LLM returns text, and only a state ack when it returns empty;
  Gemini provider mocked.
- **Gemini provider unit:** `complete_text` against a mocked HTTP response;
  malformed/HTTP-error response → raises so the caller falls through to the
  existing chain.
- **Browser QA remains unavailable on this machine** (headless Chrome won't
  launch) — use codex diff review + the unit suites, as in prior sessions.

## Out of scope (YAGNI)

- Streaming replies (one short reply per barge-in is enough).
- Full free-form conversational dialogue / dialogue-state machine.
- Making Gemini the global provider for all interviewer text.
- Custom acoustic echo cancellation (native AEC + threshold suffice).

## New/changed surface (summary)

- `frontend/src/lib/speech.ts` — (maybe) expose enough for barge-in detection;
  AEC constraints live in `InterviewPage.enableMic`.
- `frontend/src/pages/InterviewPage.tsx` — barge-in detector, AEC constraints,
  `barge_in` send, refined `sttSuppressed`, optional headphones hint.
- `frontend/src/lib/ws.ts` / `types.ts` — `barge_in` client message type.
- `backend/app/core/orchestrator.py` — `barge_in` dispatch + `_on_barge_in`.
- `backend/app/llm/provider.py` — `GeminiAPI` provider + `get_fast_provider()`.
- `backend/app/llm/interviewer.py` — `barge_in_reply(...)`.
- `backend/app/config.py` — `GEMINI_API_KEY` setting.
- Start script — inject `GEMINI_API_KEY` from the `gemini-api-key` secret.
