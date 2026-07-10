/**
 * Browser speech wrapper (DESIGN.md §10 speech.ts).
 *
 * STT: webkitSpeechRecognition || SpeechRecognition behind a small interface
 * with an `isSupported` flag. Continuous + interim results; interim text goes
 * to `onPartial`, finalized utterances to `onFinal`. When recognition is not
 * supported the app falls back to text-only mode (banner in InterviewPage).
 *
 * TTS: speechSynthesis with utterance onstart/onboundary/onend events driving
 * a speaking state and per-word events for the avatar mouth. `interrupt()`
 * cancels synthesis (used when the candidate starts talking over the
 * interviewer).
 */

// ---------------------------------------------------------------- STT types
export interface SpeechRecognitionAlternativeLike {
  transcript: string;
}

export interface SpeechRecognitionResultLike {
  isFinal: boolean;
  0: SpeechRecognitionAlternativeLike;
  length: number;
}

export interface SpeechRecognitionEventLike {
  resultIndex: number;
  results: ArrayLike<SpeechRecognitionResultLike>;
}

export interface SpeechRecognitionLike {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: ((event: { error?: string }) => void) | null;
  onend: (() => void) | null;
  onaudiostart?: (() => void) | null;
  start(): void;
  stop(): void;
  abort?(): void;
}

type SpeechRecognitionCtor = new () => SpeechRecognitionLike;

declare global {
  interface Window {
    SpeechRecognition?: SpeechRecognitionCtor;
    webkitSpeechRecognition?: SpeechRecognitionCtor;
  }
}

function recognitionCtor(): SpeechRecognitionCtor | null {
  if (typeof window === 'undefined') return null;
  return window.SpeechRecognition ?? window.webkitSpeechRecognition ?? null;
}

export function speechRecognitionSupported(): boolean {
  return recognitionCtor() !== null;
}

export interface RecognizerCallbacks {
  /** Live interim transcript (whole in-progress utterance). */
  onPartial?: (text: string) => void;
  /** A finalized utterance chunk. */
  onFinal?: (text: string) => void;
  /** Recognition error name, e.g. "not-allowed" when mic permission denied. */
  onError?: (error: string) => void;
}

export interface Recognizer {
  readonly isSupported: boolean;
  readonly listening: boolean;
  start(lang?: string): void;
  stop(): void;
}

/**
 * Create a recognizer that keeps listening until `stop()` is called
 * (Chrome ends continuous recognition after silence, so we auto-restart).
 */
/**
 * If the speech service never signals life (no audiostart/result/error) within
 * this window after start(), treat the mic as dead. Catches Chromium builds
 * where SpeechRecognition is constructible but no speech backend exists:
 * start() succeeds and then nothing ever fires.
 */
export const SPEECH_WATCHDOG_MS = 6000;

export function createRecognizer(callbacks: RecognizerCallbacks): Recognizer {
  const Ctor = recognitionCtor();
  let instance: SpeechRecognitionLike | null = null;
  let shouldListen = false;
  let lang = 'en-US';
  let watchdog: ReturnType<typeof setTimeout> | null = null;
  let networkErrors = 0;

  const clearWatchdog = () => {
    if (watchdog !== null) {
      clearTimeout(watchdog);
      watchdog = null;
    }
  };

  const fatal = (error: string) => {
    shouldListen = false;
    clearWatchdog();
    try {
      if (instance?.abort) instance.abort();
      else instance?.stop();
    } catch {
      /* already stopped */
    }
    callbacks.onError?.(error);
  };

  const armWatchdog = () => {
    clearWatchdog();
    watchdog = setTimeout(() => {
      if (shouldListen) fatal('no-speech-service');
    }, SPEECH_WATCHDOG_MS);
  };

  const build = (): SpeechRecognitionLike | null => {
    if (!Ctor) return null;
    const rec = new Ctor();
    rec.continuous = true;
    rec.interimResults = true;
    rec.lang = lang;
    rec.onaudiostart = () => {
      networkErrors = 0;
      clearWatchdog();
    };
    rec.onresult = (event) => {
      clearWatchdog();
      let interim = '';
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        if (!result) continue;
        const transcript = result[0]?.transcript ?? '';
        if (result.isFinal) {
          const finalText = transcript.trim();
          if (finalText) callbacks.onFinal?.(finalText);
        } else {
          interim += transcript;
        }
      }
      if (interim.trim()) callbacks.onPartial?.(interim.trim());
    };
    rec.onerror = (event) => {
      const error = event.error ?? 'unknown';
      // The service responded at all, so the dead-service watchdog can rest;
      // fatal handling below decides whether listening continues.
      clearWatchdog();
      if (
        error === 'not-allowed' ||
        error === 'service-not-allowed' ||
        error === 'audio-capture'
      ) {
        fatal(error);
        return;
      }
      if (error === 'network') {
        networkErrors += 1;
        if (networkErrors >= 2) {
          fatal(error);
          return;
        }
      }
      callbacks.onError?.(error);
    };
    rec.onend = () => {
      // Auto-restart while the user still wants the mic on.
      if (shouldListen) {
        try {
          rec.start();
          armWatchdog();
        } catch {
          /* start() throws if already started — ignore */
        }
      }
    };
    return rec;
  };

  return {
    get isSupported() {
      return Ctor !== null;
    },
    get listening() {
      return shouldListen;
    },
    start(nextLang?: string) {
      if (!Ctor) return;
      if (nextLang) lang = nextLang;
      shouldListen = true;
      networkErrors = 0;
      if (!instance) instance = build();
      try {
        instance?.start();
        armWatchdog();
      } catch {
        /* already started */
      }
    },
    stop() {
      shouldListen = false;
      clearWatchdog();
      try {
        instance?.stop();
      } catch {
        /* already stopped */
      }
    },
  };
}

// ---------------------------------------------------------------- TTS
export interface SpeakCallbacks {
  /** Synthesis actually started producing audio. */
  onStart?: () => void;
  /** A word boundary was reached (drives avatar mouth). */
  onWord?: (charIndex: number) => void;
  /** Synthesis finished, errored, or was cancelled. */
  onEnd?: () => void;
}

export function ttsSupported(): boolean {
  return (
    typeof window !== 'undefined' &&
    'speechSynthesis' in window &&
    'SpeechSynthesisUtterance' in window
  );
}

/**
 * Pick an installed voice whose language matches a BCP-47 tag (by primary
 * subtag, e.g. "he" from "he-IL"). Returns null when none is installed, in
 * which case the platform default voice is used.
 */
function voiceForLang(lang: string): SpeechSynthesisVoice | null {
  if (!ttsSupported() || typeof window.speechSynthesis.getVoices !== 'function') {
    return null;
  }
  const base = lang.split('-')[0].toLowerCase();
  const voices = window.speechSynthesis.getVoices() ?? [];
  return (
    voices.find((v) => v.lang?.toLowerCase() === lang.toLowerCase()) ??
    voices.find((v) => v.lang?.toLowerCase().startsWith(base)) ??
    null
  );
}

/**
 * Speak a line of interviewer dialogue. When TTS is unavailable the callbacks
 * resolve immediately so `speaking` state never gets stuck. `lang` (BCP-47)
 * selects a matching installed voice — used for non-English interviews.
 */
export function speak(text: string, callbacks: SpeakCallbacks = {}, lang?: string): void {
  if (!text.trim()) {
    callbacks.onEnd?.();
    return;
  }
  if (!ttsSupported()) {
    callbacks.onEnd?.();
    return;
  }
  const utterance = new SpeechSynthesisUtterance(text);
  if (lang) {
    utterance.lang = lang;
    const match = voiceForLang(lang);
    if (match) utterance.voice = match;
  }
  utterance.rate = 1.02;
  utterance.pitch = 1.0;
  let ended = false;
  const finish = () => {
    if (!ended) {
      ended = true;
      callbacks.onEnd?.();
    }
  };
  utterance.onstart = () => callbacks.onStart?.();
  utterance.onboundary = (event: SpeechSynthesisEvent) => {
    callbacks.onWord?.(event.charIndex ?? 0);
  };
  utterance.onend = finish;
  utterance.onerror = finish;
  window.speechSynthesis.speak(utterance);
}

/** Cancel any in-flight synthesis (user interrupted the interviewer). */
export function interrupt(): void {
  if (ttsSupported()) {
    window.speechSynthesis.cancel();
  }
}
