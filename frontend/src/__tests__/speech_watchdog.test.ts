// Regression: ISSUE-002 — silent mic failure when SpeechRecognition is
// constructible but the speech backend never responds (no audiostart/result/
// error events after start()). The recognizer must fail loudly via onError
// so the UI can fall back to text mode instead of showing "Mic on" forever.
// Found by /qa on 2026-07-02
// Report: .gstack/qa-reports/qa-report-127-0-0-1-8011-2026-07-02.md
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { createRecognizer, SPEECH_WATCHDOG_MS } from '../lib/speech';
import type { SpeechRecognitionLike } from '../lib/speech';

type Handler = ((event: { error?: string }) => void) | null;

class DeadServiceRecognition implements SpeechRecognitionLike {
  static instances: DeadServiceRecognition[] = [];
  continuous = false;
  interimResults = false;
  lang = '';
  onresult: SpeechRecognitionLike['onresult'] = null;
  onerror: Handler = null;
  onend: (() => void) | null = null;
  onaudiostart: (() => void) | null = null;
  started = 0;
  aborted = 0;

  constructor() {
    DeadServiceRecognition.instances.push(this);
  }

  start(): void {
    this.started += 1;
    // A dead speech backend: start() succeeds, then silence forever.
  }

  stop(): void {}

  abort(): void {
    this.aborted += 1;
  }
}

const win = window as unknown as Record<string, unknown>;

describe('speech recognizer watchdog (ISSUE-002)', () => {
  let savedNative: unknown;
  let savedWebkit: unknown;

  beforeEach(() => {
    vi.useFakeTimers();
    DeadServiceRecognition.instances = [];
    savedNative = win.SpeechRecognition;
    savedWebkit = win.webkitSpeechRecognition;
    // Override both: the recognizer prefers window.SpeechRecognition, which
    // the global test setup may have populated with its own fake.
    win.SpeechRecognition = DeadServiceRecognition;
    win.webkitSpeechRecognition = DeadServiceRecognition;
  });

  afterEach(() => {
    win.SpeechRecognition = savedNative;
    win.webkitSpeechRecognition = savedWebkit;
    vi.useRealTimers();
  });

  it('reports no-speech-service and stops listening when the backend never responds', () => {
    const onError = vi.fn();
    const recognizer = createRecognizer({ onError });
    recognizer.start();
    expect(recognizer.listening).toBe(true);

    vi.advanceTimersByTime(SPEECH_WATCHDOG_MS + 50);

    expect(onError).toHaveBeenCalledWith('no-speech-service');
    expect(recognizer.listening).toBe(false);
    expect(DeadServiceRecognition.instances[0]?.aborted).toBe(1);
  });

  it('does not fire the watchdog when the service responds with audio', () => {
    const onError = vi.fn();
    const recognizer = createRecognizer({ onError });
    recognizer.start();

    DeadServiceRecognition.instances[0]?.onaudiostart?.();
    vi.advanceTimersByTime(SPEECH_WATCHDOG_MS + 50);

    expect(onError).not.toHaveBeenCalled();
    expect(recognizer.listening).toBe(true);
  });

  it('treats audio-capture errors as fatal and stops listening', () => {
    const onError = vi.fn();
    const recognizer = createRecognizer({ onError });
    recognizer.start();

    DeadServiceRecognition.instances[0]?.onerror?.({ error: 'audio-capture' });

    expect(onError).toHaveBeenCalledWith('audio-capture');
    expect(recognizer.listening).toBe(false);
  });

  it('stops listening after two consecutive network errors', () => {
    const onError = vi.fn();
    const recognizer = createRecognizer({ onError });
    recognizer.start();

    const rec = DeadServiceRecognition.instances[0];
    rec?.onerror?.({ error: 'network' });
    expect(recognizer.listening).toBe(true);
    rec?.onerror?.({ error: 'network' });

    expect(onError).toHaveBeenLastCalledWith('network');
    expect(recognizer.listening).toBe(false);
  });
});
