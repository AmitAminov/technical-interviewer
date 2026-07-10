/**
 * VoiceEngine — the single TTS entry point for the app.
 *
 * Primary path ("kokoro"): POST /api/voice/tts (same-origin proxy to the
 * local HeadTTS/Kokoro sidecar) which returns base64 WAV audio plus word and
 * viseme timestamps. Text is split into sentence chunks (a short first chunk
 * for fast time-to-first-audio), chunk n+1 is prefetched while chunk n plays,
 * and all chunks are scheduled gaplessly on a single AudioContext. Word and
 * viseme callbacks are fired from a requestAnimationFrame loop that compares
 * the timeline against AudioContext.currentTime, so a backgrounded tab never
 * fires a burst of stale events (stale visemes are skipped on catch-up).
 *
 * Fallback path ("browser"): the existing speechSynthesis wrapper in
 * speech.ts, used when the sidecar is unavailable (health probe) or when a
 * synthesis call fails mid-utterance.
 *
 * A "sink" (the 3D talking head) can register itself; when present it takes
 * over audio playback: each decoded chunk payload (AudioBuffer + word/viseme
 * timelines — exactly the shape TalkingHead.speakAudio expects) is handed to
 * the sink instead of being scheduled locally.
 */
import {
  interrupt as browserInterrupt,
  speak as browserSpeak,
  ttsSupported,
} from './speech';
import type { InterviewerStyle } from './types';

// ------------------------------------------------------------ voice mapping
export type VoiceEngineName = 'kokoro' | 'browser';
export type KokoroVoice = 'af_bella' | 'am_fenrir';

export interface VoiceStyleOpts {
  voice: KokoroVoice;
  speed: number;
  /**
   * BCP-47 language tag of the line. The Kokoro sidecar only synthesizes
   * English, so a non-`en-*` tag routes the utterance to the browser's
   * speechSynthesis (which may have e.g. a Hebrew voice) instead.
   */
  lang?: string;
}

/**
 * Interviewer style → Kokoro voice. Only two voices ship with the sidecar
 * (af_bella, am_fenrir — verified against voice/headtts/voices), so styles
 * are further differentiated by speaking speed.
 */
export const STYLE_VOICES: Record<InterviewerStyle, VoiceStyleOpts> = {
  Friendly: { voice: 'af_bella', speed: 1.0 },
  'Research professor': { voice: 'af_bella', speed: 0.9 },
  'Big-tech interviewer': { voice: 'af_bella', speed: 1.05 },
  Strict: { voice: 'am_fenrir', speed: 0.95 },
  'Startup CTO': { voice: 'am_fenrir', speed: 1.1 },
};

// ------------------------------------------------------------- viseme → SVG
/**
 * Map the 15 Oculus viseme IDs onto the SVG avatar's 4 mouth shapes:
 * 0 = closed/near-closed, 1 = rounded (O/U), 2 = open (aa/E/I),
 * 3 = consonant bar (PP/FF/TH/DD/kk/CH/SS/nn/RR).
 */
export function visemeToMouthShape(viseme: string): number {
  switch (viseme) {
    case 'sil':
      return 0;
    case 'aa':
    case 'E':
    case 'I':
      return 2;
    case 'O':
    case 'U':
      return 1;
    default:
      return 3;
  }
}

// ------------------------------------------------------------- text chunking
/** Max length of the first chunk — kept short for fast first audio. */
export const FIRST_CHUNK_MAX_CHARS = 60;
/** Target size for subsequent chunks (sentences merged greedily). */
export const CHUNK_TARGET_CHARS = 220;
/** Sidecar hard limit per request. */
export const CHUNK_HARD_MAX_CHARS = 500;

function splitSentences(text: string): string[] {
  return text
    .split(/(?<=[.!?…])\s+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

/** Hard-split an over-long sentence at spaces below the sidecar limit. */
function hardSplit(sentence: string, max: number): string[] {
  const parts: string[] = [];
  let rest = sentence;
  while (rest.length > max) {
    let cut = rest.lastIndexOf(' ', max);
    if (cut <= 0) cut = max;
    parts.push(rest.slice(0, cut).trim());
    rest = rest.slice(cut).trim();
  }
  if (rest) parts.push(rest);
  return parts;
}

/**
 * Split text into synthesis chunks: a short first chunk (first clause or
 * sentence boundary ≤ ~60 chars) so the first audio arrives fast, then
 * sentences merged greedily up to CHUNK_TARGET_CHARS.
 */
export function chunkText(text: string): string[] {
  const normalized = text.replace(/\s+/g, ' ').trim();
  if (!normalized) return [];

  const sentences = splitSentences(normalized);
  const chunks: string[] = [];
  let remainder: string[] = [];

  // Find the first clause boundary (",", ";", ":" or dash) within the
  // window — but not so early that the chunk is a stub.
  const firstClauseCut = (sentence: string): number => {
    const window = sentence.slice(0, FIRST_CHUNK_MAX_CHARS + 1);
    const clause = /[,;:—–]\s/g;
    let match: RegExpExecArray | null;
    while ((match = clause.exec(window)) !== null) {
      if (match.index >= 6) return match.index + 1; // include the punctuation
    }
    return -1;
  };

  const first = sentences[0] ?? normalized;
  let cut = firstClauseCut(first);
  // Splitting at a clause is only worth an extra request if a meaningful
  // remainder exists (shaves time-to-first-audio on long greetings).
  if (cut !== -1 && first.length - cut < 8) cut = -1;
  if (cut === -1 && first.length > FIRST_CHUNK_MAX_CHARS) {
    const space = first.slice(0, FIRST_CHUNK_MAX_CHARS + 1).lastIndexOf(' ');
    cut = space > 12 ? space : Math.min(first.length, FIRST_CHUNK_MAX_CHARS);
  }
  if (cut === -1) {
    chunks.push(first);
    remainder = sentences.slice(1);
  } else {
    chunks.push(first.slice(0, cut).trim());
    const firstRest = first.slice(cut).trim();
    remainder = firstRest ? [firstRest, ...sentences.slice(1)] : sentences.slice(1);
  }

  // Merge the remaining sentences greedily up to the target size.
  let current = '';
  const flush = () => {
    if (current) {
      chunks.push(current);
      current = '';
    }
  };
  for (const sentence of remainder) {
    const pieces =
      sentence.length > CHUNK_HARD_MAX_CHARS
        ? hardSplit(sentence, CHUNK_HARD_MAX_CHARS - 50)
        : [sentence];
    for (const piece of pieces) {
      if (!current) current = piece;
      else if (current.length + piece.length + 1 <= CHUNK_TARGET_CHARS) {
        current = `${current} ${piece}`;
      } else {
        flush();
        current = piece;
      }
    }
  }
  flush();
  return chunks;
}

// ---------------------------------------------------------------- payloads
/** Raw HeadTTS response for one chunk. */
interface TtsResponse {
  audio: string;
  audioEncoding: string;
  words: string[];
  wtimes: number[];
  wdurations: number[];
  visemes: string[];
  vtimes: number[];
  vdurations: number[];
}

/**
 * Decoded per-chunk payload — exactly the shape TalkingHead.speakAudio
 * consumes natively (AudioBuffer + ms timelines).
 */
export interface TtsChunk {
  audio: AudioBuffer;
  words: string[];
  wtimes: number[];
  wdurations: number[];
  visemes: string[];
  vtimes: number[];
  vdurations: number[];
}

/** Playback sink (the 3D talking head) that takes over audio + lipsync. */
export interface VoiceSink {
  /** Queue a chunk. onWord fires as each word is spoken. */
  speak(chunk: TtsChunk, onWord: (index: number, words: string[]) => void): void;
  /** Queue a marker callback (fires when the queue reaches it). */
  marker(callback: () => void): void;
  /** Stop playback and flush the sink's queue. */
  interrupt(): void;
}

export interface VoiceSpeakCallbacks {
  onStart?: () => void;
  /** A word started (index into the current chunk's word list). */
  onWord?: (index: number, wordsForChunk: string[]) => void;
  /** A viseme started (Oculus viseme ID, e.g. "aa", "PP", "sil"). */
  onViseme?: (visemeId: string) => void;
  /** Called every animation frame while speaking with elapsed seconds. */
  onSpeakingFrame?: (tSeconds: number) => void;
  onEnd?: () => void;
  onError?: (error: unknown) => void;
}

// ------------------------------------------------------------- health probe
const HEALTH_TTL_MS = 30_000;
/** While degraded to the browser voice, re-probe much sooner so the natural
 * voice recovers quickly once the sidecar warms up or comes back. */
const HEALTH_TTL_DEGRADED_MS = 5_000;

type EngineListener = (engine: VoiceEngineName) => void;

function base64ToArrayBuffer(base64: string): ArrayBuffer {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}

// ------------------------------------------------------------- timeline
interface TimelineEvent {
  /** Absolute AudioContext time in seconds. */
  t: number;
  kind: 'start' | 'word' | 'viseme';
  wordIndex?: number;
  words?: string[];
  viseme?: string;
}

/** Visemes older than this on rAF catch-up are considered stale and skipped. */
const STALE_VISEME_S = 0.18;

interface Utterance {
  id: number;
  callbacks: VoiceSpeakCallbacks;
  aborters: Set<AbortController>;
  sources: Set<AudioBufferSourceNode>;
  timeline: TimelineEvent[];
  pointer: number;
  raf: number | null;
  playhead: number;
  startedAtCtx: number | null;
  /** All chunks scheduled (no more fetches pending). */
  fullyQueued: boolean;
  /** Number of sink markers / sources still outstanding. */
  ended: boolean;
}

// --------------------------------------------------------------- the engine
export class VoiceEngine {
  private ctx: AudioContext | null = null;

  private sink: VoiceSink | null = null;

  private utteranceSeq = 0;

  private active: Utterance | null = null;

  /** Utterances waiting behind the active one (speechSynthesis-like FIFO). */
  private pending: Array<{ text: string; opts: VoiceStyleOpts; callbacks: VoiceSpeakCallbacks }> =
    [];

  private engine: VoiceEngineName = 'browser';

  private healthCheckedAt = 0;

  private healthPromise: Promise<VoiceEngineName> | null = null;

  private listeners = new Set<EngineListener>();

  // ------------------------------------------------------------ engine name
  get engineName(): VoiceEngineName {
    return this.engine;
  }

  subscribe(listener: EngineListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private setEngine(engine: VoiceEngineName): void {
    if (this.engine !== engine) {
      this.engine = engine;
      this.listeners.forEach((listener) => listener(engine));
    }
  }

  /** Probe /api/health for the sidecar (cached ~30s). */
  probe(): Promise<VoiceEngineName> {
    const now = Date.now();
    const ttl = this.engine === 'kokoro' ? HEALTH_TTL_MS : HEALTH_TTL_DEGRADED_MS;
    if (this.healthPromise && now - this.healthCheckedAt < ttl) {
      return this.healthPromise;
    }
    this.healthCheckedAt = now;
    this.healthPromise = (async (): Promise<VoiceEngineName> => {
      try {
        const res = await fetch('/api/health');
        if (!res.ok) throw new Error(`health ${res.status}`);
        const body = (await res.json()) as { voice_engine?: string };
        const engine: VoiceEngineName = body.voice_engine === 'headtts' ? 'kokoro' : 'browser';
        this.setEngine(engine);
        return engine;
      } catch {
        this.setEngine('browser');
        return 'browser';
      }
    })();
    return this.healthPromise;
  }

  // ------------------------------------------------------------------ sink
  /** Register (or clear) the 3D-head playback sink. */
  setSink(sink: VoiceSink | null): void {
    this.sink = sink;
  }

  get hasSink(): boolean {
    return this.sink !== null;
  }

  /** True while an utterance is playing or one is queued behind it. Lets the
   * interviewer's turn stay open across back-to-back lines (greeting → first
   * question) so the candidate can't answer in the gap between them. */
  get speaking(): boolean {
    return this.active !== null || this.pending.length > 0;
  }

  // ------------------------------------------------------------------ speak
  /**
   * Queue a line of dialogue. Like speechSynthesis, consecutive speak()
   * calls play sequentially (the backend often sends greeting + first
   * question back-to-back); interrupt() flushes everything.
   */
  speak(text: string, opts: VoiceStyleOpts, callbacks: VoiceSpeakCallbacks = {}): void {
    const trimmed = text.trim();
    if (!trimmed) {
      callbacks.onEnd?.();
      return;
    }
    if (this.active) {
      this.pending.push({ text: trimmed, opts, callbacks });
      return;
    }
    this.startUtterance(trimmed, opts, callbacks);
  }

  private startUtterance(
    text: string,
    opts: VoiceStyleOpts,
    callbacks: VoiceSpeakCallbacks,
  ): void {
    const utterance: Utterance = {
      id: (this.utteranceSeq += 1),
      callbacks,
      aborters: new Set(),
      sources: new Set(),
      timeline: [],
      pointer: 0,
      raf: null,
      playhead: 0,
      startedAtCtx: null,
      fullyQueued: false,
      ended: false,
    };
    this.active = utterance;
    void this.run(utterance, text, opts);
  }

  private async run(utterance: Utterance, text: string, opts: VoiceStyleOpts): Promise<void> {
    // Hebrew uses Google Cloud TTS (gendered, real audio) via /api/voice/tts;
    // English uses the local Kokoro sidecar; any other language has no cloud
    // voice here, so it falls back to the browser's built-in speech.
    const lang = (opts.lang || 'en-us').toLowerCase();
    const isHebrew = lang.startsWith('he');
    if (!isHebrew) {
      if (!lang.startsWith('en')) {
        this.speakViaBrowser(utterance, text, opts.lang);
        return;
      }
      const engine = await this.probe();
      if (this.isStale(utterance)) return;
      if (engine !== 'kokoro') {
        this.speakViaBrowser(utterance, text);
        return;
      }
    }
    const ttsLang = isHebrew ? 'he-IL' : 'en-us';

    const chunks = chunkText(text);
    if (chunks.length === 0) {
      this.finish(utterance);
      return;
    }

    let next: Promise<TtsChunk> | null = this.fetchChunk(utterance, chunks[0], opts, ttsLang);
    for (let i = 0; i < chunks.length; i += 1) {
      let chunk: TtsChunk;
      try {
        chunk = await (next as Promise<TtsChunk>);
      } catch (error) {
        if (this.isStale(utterance)) return;
        utterance.callbacks.onError?.(error);
        this.setEngine('browser');
        this.healthPromise = null;
        this.healthCheckedAt = 0;
        // Transparent fallback for the rest of this utterance.
        this.fallbackRemainder(utterance, chunks.slice(i).join(' '));
        return;
      }
      if (this.isStale(utterance)) return;
      // Kokoro audio is confirmed flowing for this utterance: make the
      // reported engine match the audio source (a transient earlier failure
      // may have left it on 'browser' while the cached probe said kokoro).
      if (!isHebrew) this.setEngine('kokoro');
      next = i + 1 < chunks.length ? this.fetchChunk(utterance, chunks[i + 1], opts, ttsLang) : null;
      // Swallow prefetch rejection here; it is re-awaited (and handled) on
      // the next loop iteration.
      next?.catch(() => undefined);
      this.scheduleChunk(utterance, chunk, i === 0, i === chunks.length - 1);
    }
    utterance.fullyQueued = true;
    this.maybeFinish(utterance);
  }

  private isStale(utterance: Utterance): boolean {
    return this.active !== utterance || utterance.ended;
  }

  // ------------------------------------------------------------- kokoro path
  private async fetchChunk(
    utterance: Utterance,
    input: string,
    opts: VoiceStyleOpts,
    ttsLang: string,
  ): Promise<TtsChunk> {
    const aborter = new AbortController();
    utterance.aborters.add(aborter);
    try {
      const res = await fetch('/api/voice/tts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: aborter.signal,
        body: JSON.stringify({
          input: input.slice(0, CHUNK_HARD_MAX_CHARS),
          voice: opts.voice,
          language: ttsLang,
          speed: opts.speed,
          audioEncoding: 'wav',
        }),
      });
      if (!res.ok) throw new Error(`tts ${res.status}`);
      const body = (await res.json()) as TtsResponse;
      const ctx = this.audioContext();
      if (!ctx) throw new Error('AudioContext unavailable');
      const audio = await ctx.decodeAudioData(base64ToArrayBuffer(body.audio));
      return {
        audio,
        words: body.words ?? [],
        wtimes: body.wtimes ?? [],
        wdurations: body.wdurations ?? [],
        visemes: body.visemes ?? [],
        vtimes: body.vtimes ?? [],
        vdurations: body.vdurations ?? [],
      };
    } finally {
      utterance.aborters.delete(aborter);
    }
  }

  private audioContext(): AudioContext | null {
    if (this.ctx) return this.ctx;
    const Ctor =
      (globalThis as { AudioContext?: typeof AudioContext }).AudioContext ??
      (globalThis as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctor) return null;
    try {
      this.ctx = new Ctor();
    } catch {
      return null;
    }
    return this.ctx;
  }

  private scheduleChunk(
    utterance: Utterance,
    chunk: TtsChunk,
    isFirst: boolean,
    isLast: boolean,
  ): void {
    // 3D-head sink takes over playback + lipsync natively.
    if (this.sink) {
      try {
        const sink = this.sink;
        if (isFirst) {
          sink.marker(() => {
            if (!this.isStale(utterance)) utterance.callbacks.onStart?.();
          });
        }
        sink.speak(chunk, (index, words) => {
          if (!this.isStale(utterance)) utterance.callbacks.onWord?.(index, words);
        });
        if (isLast) {
          sink.marker(() => this.finish(utterance));
        }
        return;
      } catch (error) {
        // Sink broke (e.g. 3D head disposed mid-utterance) — fall through to
        // local playback for this and subsequent chunks.
        utterance.callbacks.onError?.(error);
        this.sink = null;
      }
    }

    const ctx = this.audioContext();
    if (!ctx) {
      this.fallbackRemainder(utterance, chunk.words.join(' '));
      return;
    }
    if (ctx.state === 'suspended') void ctx.resume().catch(() => undefined);

    const startAt = Math.max(utterance.playhead, ctx.currentTime + 0.03);
    const source = ctx.createBufferSource();
    source.buffer = chunk.audio;
    source.connect(ctx.destination);
    source.onended = () => {
      utterance.sources.delete(source);
      this.maybeFinish(utterance);
    };
    source.start(startAt);
    utterance.sources.add(source);
    utterance.playhead = startAt + chunk.audio.duration;

    if (isFirst) {
      utterance.startedAtCtx = startAt;
      utterance.timeline.push({ t: startAt, kind: 'start' });
    }
    chunk.words.forEach((_, i) => {
      utterance.timeline.push({
        t: startAt + (chunk.wtimes[i] ?? 0) / 1000,
        kind: 'word',
        wordIndex: i,
        words: chunk.words,
      });
    });
    chunk.visemes.forEach((viseme, i) => {
      utterance.timeline.push({
        t: startAt + (chunk.vtimes[i] ?? 0) / 1000,
        kind: 'viseme',
        viseme,
      });
    });
    utterance.timeline.sort((a, b) => a.t - b.t);
    this.ensureRafLoop(utterance, ctx);
  }

  /**
   * rAF timeline pump: fires word/viseme callbacks when the AudioContext
   * clock passes them. In a hidden tab rAF stops, so on catch-up we skip
   * visemes that are already stale instead of replaying a burst.
   */
  private ensureRafLoop(utterance: Utterance, ctx: AudioContext): void {
    if (utterance.raf !== null) return;
    const tick = () => {
      if (this.isStale(utterance)) {
        utterance.raf = null;
        return;
      }
      const now = ctx.currentTime;
      while (
        utterance.pointer < utterance.timeline.length &&
        utterance.timeline[utterance.pointer].t <= now
      ) {
        const event = utterance.timeline[utterance.pointer];
        utterance.pointer += 1;
        if (event.kind === 'start') {
          utterance.callbacks.onStart?.();
        } else if (event.kind === 'word') {
          utterance.callbacks.onWord?.(event.wordIndex ?? 0, event.words ?? []);
        } else if (event.kind === 'viseme' && now - event.t <= STALE_VISEME_S) {
          utterance.callbacks.onViseme?.(event.viseme ?? 'sil');
        }
      }
      if (utterance.startedAtCtx !== null && now >= utterance.startedAtCtx) {
        utterance.callbacks.onSpeakingFrame?.(now - utterance.startedAtCtx);
      }
      utterance.raf = requestAnimationFrame(tick);
    };
    utterance.raf = requestAnimationFrame(tick);
  }

  private maybeFinish(utterance: Utterance): void {
    if (utterance.fullyQueued && utterance.sources.size === 0 && !this.sink) {
      // Drain any remaining timeline events (e.g. the final viseme) before
      // ending so callback ordering stays sane.
      this.finish(utterance);
    }
  }

  // ------------------------------------------------------------ browser path
  private speakViaBrowser(utterance: Utterance, text: string, lang?: string): void {
    this.setEngine('browser');
    if (!ttsSupported()) {
      this.finish(utterance);
      return;
    }
    let wordCounter = 0;
    browserSpeak(
      text,
      {
        onStart: () => {
          if (!this.isStale(utterance)) utterance.callbacks.onStart?.();
        },
        onWord: () => {
          if (!this.isStale(utterance)) {
            utterance.callbacks.onWord?.(wordCounter, []);
            wordCounter += 1;
          }
        },
        onEnd: () => this.finish(utterance),
      },
      lang,
    );
  }

  /** Speak the unsynthesized remainder of a failed utterance via the browser. */
  private fallbackRemainder(utterance: Utterance, remainder: string): void {
    if (!remainder.trim()) {
      utterance.fullyQueued = true;
      this.maybeFinish(utterance);
      return;
    }
    if (utterance.sources.size > 0) {
      // Let already-scheduled audio finish, then continue with browser TTS.
      // fullyQueued stays false so maybeFinish() won't end the utterance
      // before the browser part has spoken.
      let remaining = utterance.sources.size;
      utterance.sources.forEach((source) => {
        source.onended = () => {
          utterance.sources.delete(source);
          remaining -= 1;
          if (remaining <= 0 && !this.isStale(utterance)) {
            this.speakViaBrowser(utterance, remainder);
          }
        };
      });
      return;
    }
    this.speakViaBrowser(utterance, remainder);
  }

  // -------------------------------------------------------------- lifecycle
  private finish(utterance: Utterance): void {
    if (utterance.ended) return;
    utterance.ended = true;
    if (utterance.raf !== null) {
      cancelAnimationFrame(utterance.raf);
      utterance.raf = null;
    }
    if (this.active === utterance) this.active = null;
    utterance.callbacks.onEnd?.();
    // Play the next queued line (unless a new speak() already started one).
    if (!this.active) {
      const next = this.pending.shift();
      if (next) this.startUtterance(next.text, next.opts, next.callbacks);
    }
  }

  /** Stop all playback, abort in-flight fetches, flush the queue. */
  interrupt(): void {
    this.pending = [];
    const utterance = this.active;
    if (utterance) {
      utterance.aborters.forEach((aborter) => aborter.abort());
      utterance.aborters.clear();
      utterance.sources.forEach((source) => {
        source.onended = null;
        try {
          source.stop();
        } catch {
          /* not started yet */
        }
      });
      utterance.sources.clear();
      this.finish(utterance);
    }
    try {
      this.sink?.interrupt();
    } catch {
      /* sink already gone */
    }
    browserInterrupt();
  }

  /** Test hook: clear cached health + audio context. */
  resetForTests(): void {
    this.pending = [];
    this.interrupt();
    this.healthPromise = null;
    this.healthCheckedAt = 0;
    this.engine = 'browser';
    this.listeners.clear();
    this.ctx = null;
    this.sink = null;
  }
}

/** App-wide singleton. */
export const voiceEngine = new VoiceEngine();
