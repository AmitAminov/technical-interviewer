/**
 * VoiceEngine unit tests (DESIGN.md voice pipeline): sentence chunking with a
 * short first chunk, kokoro synthesis with word/viseme timeline callbacks,
 * health-gated fallback to speechSynthesis, mid-utterance failure fallback,
 * and interrupt aborting in-flight fetches.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  chunkText,
  FIRST_CHUNK_MAX_CHARS,
  STYLE_VOICES,
  visemeToMouthShape,
  VoiceEngine,
} from '../lib/voice';
import type { FakeSpeechSynthesis } from './helpers/fakes';
import { jsonResponse } from './helpers/fakes';

// ------------------------------------------------------------- audio stubs
class StubSource {
  buffer: unknown = null;

  onended: (() => void) | null = null;

  startedAt: number | null = null;

  stopped = false;

  connect(): void {
    /* noop */
  }

  start(at?: number): void {
    this.startedAt = at ?? 0;
  }

  stop(): void {
    this.stopped = true;
  }
}

class StubAudioContext {
  static instances: StubAudioContext[] = [];

  currentTime = 0;

  state = 'running';

  destination = {};

  sources: StubSource[] = [];

  constructor() {
    StubAudioContext.instances.push(this);
  }

  resume(): Promise<void> {
    return Promise.resolve();
  }

  createBufferSource(): StubSource {
    const source = new StubSource();
    this.sources.push(source);
    return source;
  }

  decodeAudioData(_buffer: ArrayBuffer): Promise<AudioBuffer> {
    return Promise.resolve({ duration: 2 } as unknown as AudioBuffer);
  }
}

// rAF harness: frames only run when pumped, like a real (visible) tab.
let rafQueue: FrameRequestCallback[] = [];

function pumpFrame(): void {
  const callbacks = rafQueue;
  rafQueue = [];
  callbacks.forEach((cb) => cb(performance.now()));
}

function ttsPayload(words: string[]) {
  return {
    audio: btoa('RIFF-fake-wav-bytes'),
    audioEncoding: 'wav',
    words,
    wtimes: words.map((_, i) => i * 300),
    wdurations: words.map(() => 250),
    visemes: ['aa', 'PP'],
    vtimes: [50, 400],
    vdurations: [100, 100],
  };
}

function fakeSynth(): FakeSpeechSynthesis {
  return window.speechSynthesis as unknown as FakeSpeechSynthesis;
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

let engine: VoiceEngine;

beforeEach(() => {
  StubAudioContext.instances = [];
  rafQueue = [];
  vi.stubGlobal('AudioContext', StubAudioContext);
  vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
    rafQueue.push(cb);
    return rafQueue.length;
  });
  vi.stubGlobal('cancelAnimationFrame', () => undefined);
  engine = new VoiceEngine();
});

afterEach(() => {
  engine.resetForTests();
});

// ---------------------------------------------------------------- chunking
describe('chunkText', () => {
  it('keeps a short first sentence as the first chunk', () => {
    const chunks = chunkText('Hello Amit. Welcome to your mock interview today.');
    expect(chunks[0]).toBe('Hello Amit.');
  });

  it('clause-splits even a short first sentence for faster first audio', () => {
    const chunks = chunkText("Hi Amit, it's great to meet you! Ready when you are.");
    expect(chunks[0]).toBe('Hi Amit,');
    expect(chunks.join(' ')).toBe("Hi Amit, it's great to meet you! Ready when you are.");
  });

  it('splits a long first sentence at the first clause boundary under ~60 chars', () => {
    const text =
      'Welcome to your senior data-science interview, where we will cover statistics and machine learning in depth today.';
    const chunks = chunkText(text);
    expect(chunks[0].length).toBeLessThanOrEqual(FIRST_CHUNK_MAX_CHARS + 1);
    expect(chunks[0]).toBe('Welcome to your senior data-science interview,');
    // No text is lost.
    expect(chunks.join(' ').replace(/\s+/g, ' ')).toBe(text);
  });

  it('merges later sentences into medium chunks and never exceeds the hard cap', () => {
    const long = Array.from({ length: 40 }, (_, i) => `Sentence number ${i} here.`).join(' ');
    const chunks = chunkText(long);
    expect(chunks.length).toBeGreaterThan(1);
    chunks.forEach((chunk) => expect(chunk.length).toBeLessThanOrEqual(500));
    expect(chunks.join(' ')).toBe(long);
  });

  it('returns no chunks for blank input', () => {
    expect(chunkText('   ')).toEqual([]);
  });
});

// ------------------------------------------------------------ viseme mapping
describe('visemeToMouthShape', () => {
  it('maps all 15 Oculus visemes onto the 4 SVG mouth shapes', () => {
    expect(visemeToMouthShape('sil')).toBe(0);
    ['O', 'U'].forEach((v) => expect(visemeToMouthShape(v)).toBe(1));
    ['aa', 'E', 'I'].forEach((v) => expect(visemeToMouthShape(v)).toBe(2));
    ['PP', 'SS', 'TH', 'CH', 'FF', 'kk', 'nn', 'RR', 'DD'].forEach((v) =>
      expect(visemeToMouthShape(v)).toBe(3),
    );
  });
});

// ---------------------------------------------------------------- speaking
describe('VoiceEngine.speak (kokoro path)', () => {
  it('synthesizes chunks and fires start/word/viseme/end in timeline order', async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/health') return jsonResponse({ voice_engine: 'headtts' });
      const body = JSON.parse(String(init?.body)) as { input: string; voice: string };
      return jsonResponse(ttsPayload(body.input.split(' ')));
    });
    vi.stubGlobal('fetch', fetchMock);

    const events: string[] = [];
    engine.speak('Hello there. Second sentence of the interviewer line follows here.', STYLE_VOICES.Friendly, {
      onStart: () => events.push('start'),
      onWord: (index) => events.push(`word:${index}`),
      onViseme: (viseme) => events.push(`viseme:${viseme}`),
      onEnd: () => events.push('end'),
    });

    await vi.waitFor(() => {
      expect(StubAudioContext.instances[0]?.sources.length).toBe(2);
    });
    expect(engine.engineName).toBe('kokoro');

    // TTS requests carried the style voice + speed and chunked sentences.
    const ttsCalls = fetchMock.mock.calls.filter(([url]) => url === '/api/voice/tts');
    expect(ttsCalls.length).toBe(2);
    const first = JSON.parse(String((ttsCalls[0][1] as RequestInit).body));
    expect(first).toMatchObject({
      input: 'Hello there.',
      voice: 'af_bella',
      speed: 1.0,
      language: 'en-us',
      audioEncoding: 'wav',
    });

    const ctx = StubAudioContext.instances[0];
    // Advance the audio clock past the first word + viseme and pump a frame.
    ctx.currentTime = 0.15;
    pumpFrame();
    expect(events[0]).toBe('start');
    expect(events).toContain('word:0');
    expect(events).toContain('viseme:aa');

    // Far future: remaining words fire, stale visemes are skipped.
    ctx.currentTime = 60;
    pumpFrame();
    expect(events.filter((e) => e === 'viseme:PP').length).toBe(0);

    // Both chunks end → utterance ends exactly once.
    ctx.sources.forEach((source) => source.onended?.());
    expect(events.filter((e) => e === 'end')).toEqual(['end']);
    // Words fired in ascending order per chunk.
    const wordIndexes = events.filter((e) => e.startsWith('word:'));
    expect(wordIndexes[0]).toBe('word:0');
  });

  it('falls back to speechSynthesis when the health probe reports no sidecar', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ voice_engine: 'unavailable' })),
    );
    const onEnd = vi.fn();
    engine.speak('Hello candidate.', STYLE_VOICES.Strict, { onEnd });
    await flush();
    expect(fakeSynth().spoken.length).toBe(1);
    expect(fakeSynth().spoken[0].text).toBe('Hello candidate.');
    expect(engine.engineName).toBe('browser');
    // No kokoro audio was scheduled.
    expect(StubAudioContext.instances.length).toBe(0);
  });

  it('falls back to speechSynthesis when a synthesis call fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url === '/api/health') return jsonResponse({ voice_engine: 'headtts' });
        return jsonResponse({ detail: 'sidecar down' }, 503);
      }),
    );
    const onError = vi.fn();
    engine.speak('This one fails over.', STYLE_VOICES.Friendly, { onError });
    await vi.waitFor(() => {
      expect(fakeSynth().spoken.length).toBe(1);
    });
    expect(fakeSynth().spoken[0].text).toBe('This one fails over.');
    expect(onError).toHaveBeenCalled();
    expect(engine.engineName).toBe('browser');
  });

  it('interrupt() aborts in-flight fetches and ends the utterance once', async () => {
    const signals: AbortSignal[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url === '/api/health') return jsonResponse({ voice_engine: 'headtts' });
        signals.push(init?.signal as AbortSignal);
        return new Promise<Response>(() => undefined); // hang forever
      }),
    );
    const onEnd = vi.fn();
    engine.speak('Interrupt me. Please do it now.', STYLE_VOICES['Startup CTO'], { onEnd });
    await vi.waitFor(() => {
      expect(signals.length).toBe(1);
    });
    expect(signals[0].aborted).toBe(false);
    engine.interrupt();
    expect(signals[0].aborted).toBe(true);
    expect(onEnd).toHaveBeenCalledTimes(1);
    engine.interrupt();
    expect(onEnd).toHaveBeenCalledTimes(1);
  });

  it('queues back-to-back speak() calls instead of cutting the first one off', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ voice_engine: 'unavailable' })),
    );
    engine.speak('Greeting line.', STYLE_VOICES.Friendly, {});
    engine.speak('First question line.', STYLE_VOICES.Friendly, {});
    await flush();
    // Only the greeting is speaking; the question waits its turn.
    expect(fakeSynth().spoken.length).toBe(1);
    expect(fakeSynth().spoken[0].text).toBe('Greeting line.');
    fakeSynth().spoken[0].onend?.();
    await flush();
    expect(fakeSynth().spoken.length).toBe(2);
    expect(fakeSynth().spoken[1].text).toBe('First question line.');
  });

  it('stays "speaking" across back-to-back lines until the queue fully drains', async () => {
    // Browser path keeps timing deterministic (each line ends on onend()).
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ voice_engine: 'unavailable' })),
    );
    expect(engine.speaking).toBe(false);

    // The turn-taking gate: speakLine clears store.speaking in onEnd only when
    // !voiceEngine.speaking, so a line queued behind the current one must keep
    // speaking=true at the current line's onEnd (else the candidate could answer
    // in the greeting→question gap and the next line would pile up).
    let speakingAtGreetingEnd: boolean | null = null;
    engine.speak('Greeting line.', STYLE_VOICES.Friendly, {
      onEnd: () => {
        speakingAtGreetingEnd = engine.speaking;
      },
    });
    engine.speak('First question line.', STYLE_VOICES.Friendly, {});
    await flush();
    expect(engine.speaking).toBe(true); // greeting active, question queued

    fakeSynth().spoken[0].onend?.();
    expect(speakingAtGreetingEnd).toBe(true); // question still queued → turn open
    await flush();
    expect(engine.speaking).toBe(true); // question now speaking

    fakeSynth().spoken[1].onend?.();
    expect(engine.speaking).toBe(false); // queue drained → turn ends
  });

  it('routes chunks to a registered sink instead of local playback', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url === '/api/health') return jsonResponse({ voice_engine: 'headtts' });
        const body = JSON.parse(String(init?.body)) as { input: string };
        return jsonResponse(ttsPayload(body.input.split(' ')));
      }),
    );
    const spoken: Array<{ words: string[] }> = [];
    const markers: Array<() => void> = [];
    engine.setSink({
      speak: (chunk) => spoken.push({ words: chunk.words }),
      marker: (cb) => markers.push(cb),
      interrupt: vi.fn(),
    });
    const events: string[] = [];
    engine.speak('Hi there. A second sentence rides along with this one.', STYLE_VOICES.Friendly, {
      onStart: () => events.push('start'),
      onEnd: () => events.push('end'),
    });
    await vi.waitFor(() => {
      expect(spoken.length).toBe(2);
    });
    // No local sources were created — the sink owns playback.
    expect(StubAudioContext.instances[0]?.sources ?? []).toHaveLength(0);
    // Markers bracket the utterance: start before chunk 1, end after last.
    expect(markers.length).toBe(2);
    markers[0]();
    markers[1]();
    expect(events).toEqual(['start', 'end']);
    expect(spoken[0].words).toEqual(['Hi', 'there.']);
  });
});
