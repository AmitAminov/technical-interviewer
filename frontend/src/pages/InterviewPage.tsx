/**
 * The interview room (DESIGN.md §10 InterviewPage): video-call layout with
 * the interviewer avatar on the left (candidate camera thumbnail bottom-right)
 * and a live transcript on the right; timer + section indicator on top and
 * the control bar at the bottom.
 *
 * Owns the WebSocket lifecycle (typed protocol per DESIGN.md §4), speech
 * recognition/synthesis wiring, the 12s silence detector, and the local
 * 1s timer tick between server `state` syncs.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import ConfirmDialog from '../components/ConfirmDialog';
import Controls from '../components/Controls';
import ScoreDashboard from '../components/ScoreDashboard';
import SectionIndicator from '../components/SectionIndicator';
import TalkingHeadAvatar from '../components/TalkingHeadAvatar';
import Timer from '../components/Timer';
import TranscriptPanel from '../components/TranscriptPanel';
import VideoPreview from '../components/VideoPreview';
import { getSession } from '../lib/api';
import { getSessionCharacter, type Character } from '../lib/characters';
import { createRecognizer, speechRecognitionSupported, type Recognizer } from '../lib/speech';
import { useInterviewStore } from '../lib/store';
import { languageOption } from '../lib/types';
import type { InterviewerStyle, ServerMessage, WsStatus } from '../lib/types';
import {
  STYLE_VOICES,
  visemeToMouthShape,
  voiceEngine,
  type VoiceEngineName,
} from '../lib/voice';
import { InterviewSocket } from '../lib/ws';

const SILENCE_MS = 12_000;
/** Stop-of-speech: a voice final with no further speech or typing for this
 * long auto-submits the answer (DESIGN.md §10 — "answer submit on
 * stop-of-speech OR explicit Send"). */
const AUTO_SEND_MS = 2_500;
/** The mic hears the interviewer's own voice through the speakers. We ignore
 * speech recognition entirely while the interviewer is speaking, and for this
 * short tail afterwards, so the interviewer's audio (and its echo) can never
 * interrupt itself or get captured as the candidate's answer. */
const STT_ECHO_GUARD_MS = 800;
/** A partial transcript reaching this many words while the interviewer is
 * speaking is treated as a genuine barge-in (not stray echo / a backchannel).
 * ponytail: word-count heuristic; raise it or add a confidence/energy gate if
 * false barge-ins show up in real use. */
const BARGE_IN_MIN_WORDS = 3;

/** Unicode-aware word split (works for English and Hebrew). */
const tokenizeWords = (s: string): string[] =>
  s
    .toLowerCase()
    .split(/\s+/)
    .map((w) => w.replace(/[^\p{L}\p{N}']/gu, ''))
    .filter(Boolean);

/** A partial heard while the interviewer is speaking is almost always the mic
 * catching the interviewer's own voice through the speakers. Treat it as echo
 * (not a barge-in) when most of the heard words already appear in the line the
 * interviewer is currently saying — only genuinely different speech interrupts.
 * This stops false barge-ins from cutting the interviewer off mid-sentence
 * (which left the full caption on screen with the speech "too quick"). */
function looksLikeInterviewerEcho(heardText: string): boolean {
  const entries = useInterviewStore.getState().entries;
  for (let i = entries.length - 1; i >= 0; i -= 1) {
    if (entries[i].speaker !== 'interviewer') continue;
    const said = new Set(tokenizeWords(entries[i].text));
    const heard = tokenizeWords(heardText);
    if (!heard.length) return false;
    const overlap = heard.filter((w) => said.has(w)).length / heard.length;
    return overlap >= 0.5;
  }
  return false;
}

const WS_STATUS_META: Record<WsStatus, { label: string; dot: string }> = {
  idle: { label: 'Connecting', dot: 'bg-slate-500' },
  connecting: { label: 'Connecting', dot: 'bg-amber-400 animate-pulse' },
  open: { label: 'Live', dot: 'bg-emerald-400' },
  reconnecting: { label: 'Reconnecting', dot: 'bg-amber-400 animate-pulse' },
  closed: { label: 'Disconnected', dot: 'bg-slate-500' },
  failed: { label: 'Connection lost', dot: 'bg-rose-500' },
};

export default function InterviewPage() {
  const { id } = useParams<{ id: string }>();
  const store = useInterviewStore();

  const socketRef = useRef<InterviewSocket | null>(null);
  const recognizerRef = useRef<Recognizer | null>(null);
  const lastActivityRef = useRef<number>(Date.now());
  const silenceSentRef = useRef(false);
  const voiceContributedRef = useRef(false);
  const autoSendTimerRef = useRef<number | null>(null);
  const sendAnswerRef = useRef<() => void>(() => {});
  // Suppress speech recognition until this timestamp (set when the interviewer
  // stops speaking) so its trailing audio/echo isn't treated as candidate input.
  const sttGuardUntilRef = useRef(0);
  const prevSpeakingRef = useRef(false);
  const bargeInRef = useRef(false);

  const [draft, setDraft] = useState('');
  const [confirmEnd, setConfirmEnd] = useState(false);
  const [scoreToastHovered, setScoreToastHovered] = useState(false);
  const [mouthShape, setMouthShape] = useState<number | null>(null);
  const [voiceName, setVoiceName] = useState<VoiceEngineName>(voiceEngine.engineName);
  const [character, setCharacter] = useState<Character | null>(null);
  // The interview only begins after an explicit "Start" click on this page —
  // that user gesture unlocks audio autoplay (needed for TTS) and is where we
  // request microphone access.
  const [started, setStarted] = useState(false);
  // True once the interviewer's first line is actually being spoken. Until then
  // we show a "Preparing your interview…" loading screen so the TTS/3D warm-up
  // feels intentional rather than broken.
  const [interviewReady, setInterviewReady] = useState(false);
  // Camera is on by default (like the mic); each has its own toggle in Controls.
  const [cameraEnabled, setCameraEnabled] = useState(true);

  const sttAvailable = useMemo(() => speechRecognitionSupported(), []);
  const cameraSupported = useMemo(
    () =>
      typeof navigator !== 'undefined' &&
      Boolean(navigator.mediaDevices && navigator.mediaDevices.getUserMedia),
    [],
  );
  // Probe the local Kokoro sidecar once and keep the badge in sync with the
  // engine actually being used (it flips to "browser" on fallback).
  useEffect(() => {
    const unsubscribe = voiceEngine.subscribe(setVoiceName);
    void voiceEngine.probe().then(setVoiceName);
    return unsubscribe;
  }, []);

  const speakLine = useCallback((text: string) => {
    const sess = useInterviewStore.getState().session;
    const style = (sess?.interviewer_style ?? 'Friendly') as InterviewerStyle;
    const lang = languageOption(sess?.language);
    const styleVoice = STYLE_VOICES[style] ?? STYLE_VOICES.Friendly;

    // The interviewer's turn starts the moment a line is queued — not ~1s later
    // when the first Kokoro chunk starts playing — so the candidate can't answer
    // (and the backend's next line can't pile up) before this one is spoken.
    // Cleared in onEnd once no line remains active or queued.
    useInterviewStore.getState().setSpeaking(true);
    voiceEngine.speak(text, { ...styleVoice, lang: lang.bcp47 }, {
      onStart: () => {
        setInterviewReady(true); // first line is being spoken — drop the loader
      },
      onWord: () => useInterviewStore.getState().bumpWord(),
      onViseme: (viseme) => setMouthShape(visemeToMouthShape(viseme)),
      onEnd: () => {
        // Keep the turn open if another line is already queued behind this one
        // (the backend often sends greeting + first question back-to-back) so
        // the candidate can't answer, and no line is skipped, in the gap.
        if (!voiceEngine.speaking) {
          useInterviewStore.getState().setSpeaking(false);
          setMouthShape(null);
        }
      },
    });
  }, []);

  const handleServerMessage = useCallback(
    (message: ServerMessage) => {
      const state = useInterviewStore.getState();
      switch (message.type) {
        case 'interviewer': {
          state.setWaiting(false);
          state.addEntry('interviewer', message.text);
          if (message.section) state.setSectionName(message.section);
          if (message.kind === 'question' || message.kind === 'followup') {
            state.openQuestion(message.question_id, message.question_index, message.total_questions);
            lastActivityRef.current = Date.now();
            silenceSentRef.current = false;
            voiceContributedRef.current = false;
          }
          if (message.kind === 'checkin') state.setCheckinPending(true);
          speakLine(message.text);
          break;
        }
        case 'hint': {
          state.setWaiting(false);
          state.setHintsUsed(message.hints_used);
          state.addEntry('interviewer', `Hint (level ${message.level}): ${message.text}`);
          lastActivityRef.current = Date.now();
          silenceSentRef.current = false;
          speakLine(message.text);
          break;
        }
        case 'score':
          state.setWaiting(false);
          state.addScore(message);
          break;
        case 'section_change':
          state.setSection(message.section, message.section_index, message.total_sections);
          break;
        case 'state':
          state.setStatus(message.status);
          state.syncTimer(message.elapsed_seconds, message.remaining_seconds);
          break;
        case 'report_ready':
          state.setReportReady(true);
          break;
        case 'error':
          state.setWaiting(false);
          state.setError(message.message);
          break;
      }
    },
    [speakLine],
  );

  // Session fetch + socket lifecycle.
  useEffect(() => {
    if (!id) return;
    const state = useInterviewStore.getState();
    state.resetInterview();
    getSession(id)
      .then((session) => {
        useInterviewStore.getState().setSession(session);
        // The interviewer character is fixed per interviewer style (gender
        // always matches the style's voice), so voice and face agree.
        void getSessionCharacter(session.interviewer_style as InterviewerStyle).then(setCharacter);
      })
      .catch(() =>
        useInterviewStore.getState().setError('Could not load this session. Does it exist?'),
      );
    const socket = new InterviewSocket(id, {
      onMessage: handleServerMessage,
      onStatus: (status) => useInterviewStore.getState().setWsStatus(status),
    });
    socketRef.current = socket;
    // NB: do NOT connect yet — beginInterview() connects after the Start gesture.
    return () => {
      socket.close();
      recognizerRef.current?.stop();
      if (autoSendTimerRef.current !== null) {
        window.clearTimeout(autoSendTimerRef.current);
        autoSendTimerRef.current = null;
      }
      voiceEngine.interrupt();
    };
  }, [id, handleServerMessage]);

  // Connect (which auto-sends {type:'start'}) only after the user clicks Start.
  useEffect(() => {
    if (!started) return;
    socketRef.current?.connect();
    // Safety: never let the "Preparing…" loader hang if the first line's audio
    // or video never fires (WS stall, TTS failure, autoplay block).
    const t = window.setTimeout(() => setInterviewReady(true), 30_000);
    return () => window.clearTimeout(t);
  }, [started]);

  // 1s heartbeat: local timer tick + silence detection (12s with no speech
  // or typing while a question is open → send {"type":"silence"} once).
  useEffect(() => {
    const timer = window.setInterval(() => {
      const state = useInterviewStore.getState();
      if (state.status !== 'active') return;
      state.tick();
      if (
        state.questionOpen &&
        !state.speaking &&
        !silenceSentRef.current &&
        Date.now() - lastActivityRef.current >= SILENCE_MS
      ) {
        silenceSentRef.current = true;
        socketRef.current?.send({
          type: 'silence',
          seconds: Math.round((Date.now() - lastActivityRef.current) / 100) / 10,
        });
      }
    }, 1000);
    return () => window.clearInterval(timer);
  }, []);

  // Auto-dismiss the score toast (paused while hovered).
  useEffect(() => {
    setScoreToastHovered(false);
  }, [store.lastScore]);
  useEffect(() => {
    if (!store.lastScore || scoreToastHovered) return;
    const timer = window.setTimeout(() => useInterviewStore.getState().dismissScore(), 8000);
    return () => window.clearTimeout(timer);
  }, [store.lastScore, scoreToastHovered]);

  // Arm the echo guard whenever the interviewer stops speaking, so the tail of
  // its voice picked up by the mic isn't processed as candidate speech.
  useEffect(() => {
    if (prevSpeakingRef.current && !store.speaking) {
      if (bargeInRef.current) {
        bargeInRef.current = false; // candidate is mid-utterance — no echo tail
      } else {
        sttGuardUntilRef.current = Date.now() + STT_ECHO_GUARD_MS;
      }
    }
    prevSpeakingRef.current = store.speaking;
  }, [store.speaking]);

  // True while the mic should be ignored: the interviewer is speaking (its voice
  // is coming through the speakers into the mic) or just stopped.
  const sttSuppressed = () =>
    useInterviewStore.getState().speaking || Date.now() < sttGuardUntilRef.current;

  const sendInterruptIfSpeaking = () => {
    const state = useInterviewStore.getState();
    if (state.speaking) {
      socketRef.current?.send({ type: 'interrupt' });
      voiceEngine.interrupt();
      state.setSpeaking(false);
    }
  };

  // Candidate talked over the interviewer: stop the interviewer's speech, tell
  // the backend (which may reply adaptively), and let the ongoing utterance be
  // captured as the candidate's turn. bargeInRef suppresses the echo-tail guard
  // so the candidate's own continuing words are not dropped.
  const bargeIn = (text: string) => {
    const state = useInterviewStore.getState();
    if (!state.speaking) return;
    bargeInRef.current = true;
    voiceEngine.interrupt();
    state.setSpeaking(false);
    socketRef.current?.send({ type: 'barge_in', text });
    state.setPartial(text);
    lastActivityRef.current = Date.now();
  };

  const cancelAutoSend = useCallback(() => {
    if (autoSendTimerRef.current !== null) {
      window.clearTimeout(autoSendTimerRef.current);
      autoSendTimerRef.current = null;
    }
  }, []);

  // Stop-of-speech submit: armed by each voice final; disarmed by resumed
  // speech (partial), manual typing, mic-off, or an explicit Send.
  const scheduleAutoSend = useCallback(() => {
    cancelAutoSend();
    autoSendTimerRef.current = window.setTimeout(() => {
      autoSendTimerRef.current = null;
      const state = useInterviewStore.getState();
      if (
        state.status === 'active' &&
        state.questionOpen &&
        state.micEnabled &&
        !state.speaking &&
        !state.partialText
      ) {
        sendAnswerRef.current();
      }
    }, AUTO_SEND_MS);
  }, [cancelAutoSend]);

  const ensureRecognizer = (): Recognizer => {
    if (!recognizerRef.current) {
      recognizerRef.current = createRecognizer({
        onPartial: (text) => {
          const state = useInterviewStore.getState();
          // While the interviewer is speaking, a sustained utterance is a
          // barge-in; a short one is ignored (likely residual echo).
          if (state.speaking) {
            const words = text.trim().split(/\s+/).filter(Boolean);
            if (words.length >= BARGE_IN_MIN_WORDS && !looksLikeInterviewerEcho(text)) {
              bargeIn(text);
            }
            return;
          }
          // Echo tail after the interviewer stops: still ignore briefly.
          if (Date.now() < sttGuardUntilRef.current) return;
          cancelAutoSend();
          state.setPartial(text);
          socketRef.current?.send({ type: 'partial_transcript', text });
          lastActivityRef.current = Date.now();
        },
        onFinal: (text) => {
          // Same guard: don't fold the interviewer's echoed words into the answer.
          if (sttSuppressed()) return;
          const state = useInterviewStore.getState();
          state.setPartial('');
          setDraft((current) => (current ? `${current.trimEnd()} ${text}` : text));
          voiceContributedRef.current = true;
          lastActivityRef.current = Date.now();
          scheduleAutoSend();
        },
        onError: (error) => {
          const state = useInterviewStore.getState();
          if (error === 'not-allowed' || error === 'service-not-allowed') {
            state.setMicError('Microphone access was denied — continuing in text-only mode.');
            state.setMicEnabled(false);
          } else if (error === 'audio-capture') {
            state.setMicError('No microphone was found — continuing in text-only mode.');
            state.setMicEnabled(false);
          } else if (error === 'no-speech-service' || error === 'network') {
            state.setMicError(
              'The speech service is not responding — continuing in text-only mode.'
            );
            state.setMicEnabled(false);
          }
        },
      });
    }
    return recognizerRef.current;
  };

  // Acquire (then immediately release) the microphone up front — exactly like
  // the camera — so the browser's permission grant resolves before speech
  // recognition starts. Without this the recognizer's 6s "no speech service"
  // watchdog can trip while the permission prompt is still open and silently
  // drop the mic to "off", which is why it looked like the mic defaulted off.
  const enableMic = async () => {
    if (!sttAvailable) return;
    try {
      const stream = await navigator.mediaDevices?.getUserMedia?.({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      stream?.getTracks().forEach((track) => track.stop());
    } catch {
      /* denied / no device — the recognizer's onError surfaces it below */
    }
    const state = useInterviewStore.getState();
    try {
      ensureRecognizer().start(languageOption(state.session?.language).bcp47);
      state.setMicEnabled(true);
    } catch {
      state.setMicEnabled(false);
    }
  };

  const toggleMic = () => {
    if (!sttAvailable) return;
    const state = useInterviewStore.getState();
    if (state.micEnabled) {
      recognizerRef.current?.stop();
      cancelAutoSend();
      state.setMicEnabled(false);
      state.setPartial('');
      return;
    }
    sendInterruptIfSpeaking();
    void enableMic();
  };

  const toggleCamera = () => {
    if (!cameraSupported) return;
    setCameraEnabled((on) => !on);
  };

  // The Start gesture: enables the mic by default (prompting for permission),
  // unlocks audio autoplay, then connects.
  const beginInterview = () => {
    // Microphone on by default — enableMic prompts for permission (behind this
    // Start gesture) and starts recognition; denial is handled by onError.
    void enableMic();
    // Unlock the AudioContext for TTS playback (this click is the gesture).
    void voiceEngine.probe();
    setStarted(true);
  };

  const sendAnswer = () => {
    cancelAutoSend();
    const state = useInterviewStore.getState();
    const text = draft.trim();
    // Turn-taking: don't submit while the interviewer is still speaking, so the
    // candidate answers after it finishes and the backend's next line can't pile
    // up ahead of the speech.
    if (!text || state.status !== 'active' || state.speaking) return;
    const durationSeconds = state.questionShownAt
      ? Math.round(((Date.now() - state.questionShownAt) / 1000) * 10) / 10
      : 0;
    socketRef.current?.send({
      type: 'answer',
      text,
      duration_seconds: durationSeconds,
      input_mode: voiceContributedRef.current ? 'voice' : 'text',
    });
    state.addEntry('candidate', text);
    state.closeQuestion();
    state.setPartial('');
    state.setWaiting(true);
    setDraft('');
    voiceContributedRef.current = false;
    lastActivityRef.current = Date.now();
  };

  const handleDraftChange = (value: string) => {
    cancelAutoSend();
    setDraft(value);
    lastActivityRef.current = Date.now();
  };
  // Keep the auto-send timer pointed at the latest sendAnswer closure (it
  // captures the current draft).
  sendAnswerRef.current = sendAnswer;

  const requestHint = () => {
    socketRef.current?.send({ type: 'hint_request' });
    useInterviewStore.getState().setWaiting(true);
  };

  const pause = () => {
    socketRef.current?.send({ type: 'pause' });
    useInterviewStore.getState().setStatus('paused');
  };

  const resume = () => {
    socketRef.current?.send({ type: 'resume' });
    useInterviewStore.getState().setStatus('active');
  };

  const skip = () => {
    socketRef.current?.send({ type: 'skip' });
    useInterviewStore.getState().closeQuestion();
    useInterviewStore.getState().setWaiting(true);
  };

  const confirmEndNow = () => {
    setConfirmEnd(false);
    voiceEngine.interrupt();
    socketRef.current?.send({ type: 'end' });
  };

  const answerCheckin = (wantsMoreTime: boolean) => {
    socketRef.current?.send({ type: 'more_time_response', wants_more_time: wantsMoreTime });
    useInterviewStore.getState().setCheckinPending(false);
    lastActivityRef.current = Date.now();
    silenceSentRef.current = false;
  };

  const style = (store.session?.interviewer_style ?? 'Friendly') as InterviewerStyle;
  const wsMeta = WS_STATUS_META[store.wsStatus] ?? WS_STATUS_META.idle;
  const candidateName = store.userName || 'Candidate';
  const lang = languageOption(store.session?.language);
  const convoDir = lang.rtl ? 'rtl' : 'ltr';

  return (
    <div className="flex h-screen flex-col bg-slate-950">
      {/* start gate: a user gesture that unlocks audio/video playback and
          requests the microphone before the interview begins */}
      {!started && !store.errorMessage && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/95 p-4">
          <div className="card-solid w-full max-w-md p-8 text-center animate-slide-in">
            {character && (
              <img
                src={`/interviewers/${character.file}`}
                alt=""
                className="mx-auto mb-5 h-28 w-28 rounded-full object-cover ring-2 ring-indigo-500/40"
                draggable={false}
              />
            )}
            <h3 className="text-xl font-semibold text-slate-100">Ready when you are</h3>
            <p className="mt-2 text-sm text-slate-400">
              {(store.session?.role ?? 'Technical')} interview
              {store.session ? ` · ${store.session.interviewer_style}` : ''}. We'll turn on your
              microphone and camera so you can answer out loud (you can also type) — switch
              either off anytime from the controls below.
            </p>
            <p className="mt-2 text-xs text-slate-500">
              Tip: use headphones for the most natural back-and-forth — you can
              interrupt the interviewer just by speaking.
            </p>
            <button
              type="button"
              className="btn btn-primary mt-6 w-full py-3 text-base"
              onClick={beginInterview}
              disabled={!store.session}
              data-testid="begin-interview"
            >
              {store.session ? 'Start interview' : 'Loading…'}
            </button>
          </div>
        </div>
      )}
      {/* preparing-interviewer loading screen: covers the realistic-video warm-up
          (first clip generation) so the start feels smooth, not broken */}
      {started && !interviewReady && !store.errorMessage && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-950/95 p-4">
          <div className="flex flex-col items-center text-center">
            {character && (
              <img
                src={`/interviewers/${character.file}`}
                alt=""
                className="mb-6 h-32 w-32 rounded-full object-cover opacity-60 ring-2 ring-indigo-500/30"
                draggable={false}
              />
            )}
            <div
              className="mb-4 h-8 w-8 animate-spin rounded-full border-2 border-slate-600 border-t-indigo-400"
              aria-hidden="true"
            />
            <h3 className="text-lg font-semibold text-slate-100">Preparing your interview…</h3>
          </div>
        </div>
      )}
      {/* top bar */}
      <header className="flex flex-wrap items-center gap-3 border-b border-slate-800 bg-slate-950/95 px-4 py-2.5">
        <div className="mr-2 flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-full bg-indigo-400" aria-hidden="true" />
          <span className="text-sm font-semibold tracking-tight text-slate-200">
            Technical Interviewer
          </span>
        </div>
        {store.session && (
          <span className="rounded-full border border-slate-700 bg-slate-900/80 px-3 py-1 text-xs text-slate-300">
            {store.session.role} · {store.session.difficulty}
          </span>
        )}
        <SectionIndicator
          section={store.section}
          sectionIndex={store.sectionIndex}
          totalSections={store.totalSections}
          questionIndex={store.questionIndex}
          totalQuestions={store.totalQuestions}
        />
        <div className="ml-auto flex items-center gap-3">
          <Timer
            elapsedSeconds={store.elapsedSeconds}
            remainingSeconds={store.remainingSeconds}
            status={store.status}
          />
          <span className="flex items-center gap-1.5 text-xs text-slate-400" data-testid="ws-status">
            <span className={`h-2 w-2 rounded-full ${wsMeta.dot}`} />
            {wsMeta.label}
          </span>
          <span
            className="rounded-full border border-slate-800 bg-slate-900/70 px-2 py-0.5 text-[10px] text-slate-500"
            data-testid="voice-engine-badge"
            title="Text-to-speech engine in use"
          >
            Voice: {voiceName === 'kokoro' ? 'Kokoro (local)' : 'browser'}
          </span>
        </div>
      </header>

      {/* banners */}
      {!sttAvailable && (
        <div
          className="border-b border-amber-500/30 bg-amber-950/40 px-4 py-2 text-center text-sm text-amber-200"
          data-testid="text-mode-banner"
        >
          Voice input is not supported in this browser — running in text-only mode. Type your
          answers below; everything else works normally.
        </div>
      )}
      {store.micError && (
        <div
          className="border-b border-amber-500/30 bg-amber-950/40 px-4 py-2 text-center text-sm text-amber-200"
          data-testid="mic-error-banner"
        >
          {store.micError}
        </div>
      )}
      {store.errorMessage && (
        <div
          className="border-b border-rose-500/30 bg-rose-950/40 px-4 py-2 text-center text-sm text-rose-200"
          role="alert"
        >
          {store.errorMessage}
        </div>
      )}

      {/* main stage */}
      <main className="flex min-h-0 flex-1 flex-col gap-4 p-4 lg:flex-row">
        {/* interviewer panel */}
        <section className="relative flex min-w-0 flex-[3] flex-col items-center justify-center overflow-hidden rounded-2xl border border-slate-800 bg-gradient-to-b from-slate-900 to-slate-950 max-lg:min-h-[260px] lg:min-h-0">
          <TalkingHeadAvatar
            style={style}
            speaking={store.speaking}
            name={style}
            size={300}
            wordTick={store.wordTick}
            mouthShape={mouthShape}
          />
          <p className="mt-3 text-sm font-medium text-slate-300">{style}</p>
          <p className="text-xs text-slate-400">
            {character ? 'AI interviewer' : 'AI interviewer — synthetic avatar'}
          </p>

          {/* caption: last interviewer line */}
          {store.entries.length > 0 && (
            <div className="absolute inset-x-6 bottom-4 mx-auto max-w-2xl max-lg:pr-44">
              {(() => {
                const lastInterviewer = [...store.entries]
                  .reverse()
                  .find((entry) => entry.speaker === 'interviewer');
                return lastInterviewer ? (
                  <p
                    dir={convoDir}
                    className="rounded-xl bg-black/50 px-4 py-2.5 text-center text-sm leading-relaxed text-slate-100 backdrop-blur"
                  >
                    {lastInterviewer.text}
                  </p>
                ) : null;
              })()}
            </div>
          )}

          {/* candidate self-view */}
          <div className="absolute bottom-4 right-4 h-28 w-40">
            <VideoPreview name={candidateName} enabled={cameraEnabled} />
          </div>

          {/* check-in prompt */}
          {store.checkinPending && (
            <div className="absolute left-1/2 top-6 flex -translate-x-1/2 items-center gap-3 rounded-xl border border-indigo-500/40 bg-slate-900/95 px-4 py-3 text-sm text-slate-200 shadow-xl animate-slide-in">
              <span>Need more time on this one?</span>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => answerCheckin(true)}>
                Yes, more time
              </button>
              <button type="button" className="btn btn-primary btn-sm" onClick={() => answerCheckin(false)}>
                No, move on
              </button>
            </div>
          )}
        </section>

        {/* transcript panel */}
        <aside className="flex min-h-[200px] w-full flex-col overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/50 lg:w-[380px] lg:min-w-[300px]">
          <div className="border-b border-slate-800 px-4 py-2.5">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-400">
              Live transcript
            </h2>
          </div>
          <div className="min-h-0 flex-1">
            <TranscriptPanel
              entries={store.entries}
              partialText={store.partialText}
              waiting={store.waiting}
              dir={convoDir}
            />
          </div>
        </aside>
      </main>

      {/* score toast */}
      {store.lastScore && (
        <div
          className="fixed z-40 animate-slide-in max-lg:inset-x-3 max-lg:bottom-32 lg:right-6 lg:top-20 lg:w-96"
          role="status"
          aria-live="polite"
          onMouseEnter={() => setScoreToastHovered(true)}
          onMouseLeave={() => setScoreToastHovered(false)}
        >
          <div className="card-solid border-indigo-500/30 p-4 shadow-2xl shadow-black/60">
            <ScoreDashboard score={store.lastScore} />
            <button
              type="button"
              className="-mx-2 -mb-1.5 mt-0.5 rounded px-2 py-1.5 text-xs text-slate-400 hover:text-slate-300"
              onClick={() => store.dismissScore()}
            >
              Dismiss
            </button>
          </div>
        </div>
      )}

      {/* controls */}
      <Controls
        status={store.status}
        micEnabled={store.micEnabled}
        micAvailable={sttAvailable && !store.micError}
        cameraEnabled={cameraEnabled}
        cameraAvailable={cameraSupported}
        hintPolicy={store.session?.hint_policy ?? 'on_request'}
        hintsUsed={store.hintsUsed}
        draft={draft}
        canSend={store.status === 'active' && !store.speaking}
        speaking={store.speaking}
        composerDir={convoDir}
        onToggleMic={toggleMic}
        onToggleCamera={toggleCamera}
        onHint={requestHint}
        onSkip={skip}
        onPause={pause}
        onResume={resume}
        onEnd={() => setConfirmEnd(true)}
        onDraftChange={handleDraftChange}
        onSend={sendAnswer}
      />

      {/* end-interview confirmation */}
      <ConfirmDialog
        open={confirmEnd}
        title="End the interview?"
        body="The interviewer will wrap up and your report will be generated from the answers so far. This cannot be undone."
        confirmLabel="Yes, end interview"
        cancelLabel="Keep going"
        danger
        onConfirm={confirmEndNow}
        onCancel={() => setConfirmEnd(false)}
      />

      {/* completion overlay */}
      {store.status === 'completed' && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4">
          <div className="card-solid w-full max-w-md p-8 text-center animate-slide-in">
            <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-emerald-500/20 text-2xl">
              ✓
            </span>
            <h3 className="mt-4 text-xl font-semibold text-slate-100">Interview complete</h3>
            {store.reportReady ? (
              <>
                <p className="mt-2 text-sm text-slate-400">Your full report is ready.</p>
                <Link to={`/report/${id}`} className="btn btn-primary mt-5 w-full">
                  View report
                </Link>
              </>
            ) : (
              <p className="mt-2 flex items-center justify-center gap-2 text-sm text-slate-400">
                <span className="spinner h-3 w-3" />
                Generating your report…
              </p>
            )}
            <Link to="/sessions" className="mt-3 block text-xs text-slate-400 hover:text-slate-300">
              Back to sessions
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}
