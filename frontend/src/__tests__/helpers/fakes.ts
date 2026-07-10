/**
 * Controllable fakes for browser APIs used by the app: WebSocket,
 * SpeechRecognition, speechSynthesis, getUserMedia. Installed fresh before
 * every test by setupTests.ts.
 */
import { vi } from 'vitest';

import type { ProgressOut, ReportOut, SessionOut } from '../../lib/types';

// ---------------------------------------------------------------- WebSocket
export class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  static reset(): void {
    FakeWebSocket.instances = [];
  }

  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

  readyState = FakeWebSocket.CONNECTING;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: ((event?: unknown) => void) | null = null;
  onerror: ((event?: unknown) => void) | null = null;

  constructor(public url: string) {
    FakeWebSocket.instances.push(this);
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.({});
  }

  // -- test helpers ---------------------------------------------------------
  /** Simulate the server accepting the connection. */
  open(): void {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }

  /** Simulate a server → client JSON message. */
  receive(message: unknown): void {
    this.onmessage?.({ data: JSON.stringify(message) });
  }

  sentMessages(): Array<Record<string, unknown>> {
    return this.sent.map((raw) => JSON.parse(raw) as Record<string, unknown>);
  }
}

// ------------------------------------------------------- SpeechRecognition
interface FakeRecognitionResultEvent {
  resultIndex: number;
  results: Array<{ isFinal: boolean; 0: { transcript: string }; length: number }>;
}

export class FakeSpeechRecognition {
  static instances: FakeSpeechRecognition[] = [];
  static reset(): void {
    FakeSpeechRecognition.instances = [];
  }

  continuous = false;
  interimResults = false;
  lang = '';
  started = false;
  onresult: ((event: FakeRecognitionResultEvent) => void) | null = null;
  onerror: ((event: { error?: string }) => void) | null = null;
  onend: (() => void) | null = null;

  constructor() {
    FakeSpeechRecognition.instances.push(this);
  }

  start(): void {
    this.started = true;
  }

  stop(): void {
    this.started = false;
    this.onend?.();
  }

  // -- test helpers ---------------------------------------------------------
  emitPartial(text: string): void {
    this.onresult?.({
      resultIndex: 0,
      results: [{ isFinal: false, 0: { transcript: text }, length: 1 }],
    });
  }

  emitFinal(text: string): void {
    this.onresult?.({
      resultIndex: 0,
      results: [{ isFinal: true, 0: { transcript: text }, length: 1 }],
    });
  }

  emitError(error: string): void {
    this.onerror?.({ error });
  }
}

// ------------------------------------------------------------------- TTS
export class FakeUtterance {
  rate = 1;
  pitch = 1;
  onstart: (() => void) | null = null;
  onboundary: ((event: { charIndex: number }) => void) | null = null;
  onend: (() => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(public text: string) {}
}

export interface FakeSpeechSynthesis {
  spoken: FakeUtterance[];
  speak: (utterance: FakeUtterance) => void;
  cancel: () => void;
  getVoices: () => unknown[];
}

export function createFakeSpeechSynthesis(): FakeSpeechSynthesis {
  const synthesis: FakeSpeechSynthesis = {
    spoken: [],
    speak: (utterance) => {
      synthesis.spoken.push(utterance);
    },
    cancel: vi.fn(),
    getVoices: () => [],
  };
  return synthesis;
}

// ---------------------------------------------------------------- media
export function createFakeStream(): MediaStream {
  const track = { stop: vi.fn(), kind: 'video' };
  return {
    getTracks: () => [track],
    getVideoTracks: () => [track],
    getAudioTracks: () => [],
  } as unknown as MediaStream;
}

// ------------------------------------------------------------- installers
export function installBrowserMocks(): void {
  FakeWebSocket.reset();
  FakeSpeechRecognition.reset();

  (globalThis as Record<string, unknown>).WebSocket = FakeWebSocket;
  const win = window as unknown as Record<string, unknown>;
  win.SpeechRecognition = FakeSpeechRecognition;
  win.webkitSpeechRecognition = FakeSpeechRecognition;

  Object.defineProperty(window, 'speechSynthesis', {
    configurable: true,
    writable: true,
    value: createFakeSpeechSynthesis(),
  });
  (globalThis as Record<string, unknown>).SpeechSynthesisUtterance = FakeUtterance;

  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    writable: true,
    value: { getUserMedia: vi.fn().mockResolvedValue(createFakeStream()) },
  });

  window.matchMedia =
    window.matchMedia ||
    ((query: string) =>
      ({
        matches: false,
        media: query,
        onchange: null,
        addListener: () => undefined,
        removeListener: () => undefined,
        addEventListener: () => undefined,
        removeEventListener: () => undefined,
        dispatchEvent: () => false,
      }) as MediaQueryList);

  Element.prototype.scrollIntoView = vi.fn();
  window.HTMLMediaElement.prototype.play = vi.fn().mockResolvedValue(undefined);
  window.HTMLMediaElement.prototype.pause = vi.fn();
}

/** Remove STT constructors to simulate an unsupported browser. */
export function removeSpeechRecognition(): void {
  const win = window as unknown as Record<string, unknown>;
  delete win.SpeechRecognition;
  delete win.webkitSpeechRecognition;
}

// ---------------------------------------------------------------- fixtures
export function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

export const sampleSession: SessionOut = {
  id: 's1',
  user_id: 'u1',
  role: 'Data Scientist',
  mode: 'Quick Practice',
  difficulty: 'Senior',
  duration_minutes: 20,
  language: 'en',
  hint_policy: 'on_request',
  interviewer_style: 'Friendly',
  use_resume: false,
  use_job_description: false,
  use_wiki: true,
  allow_internet: false,
  record_session: false,
  disable_cloud_ai: false,
  status: 'ready',
  overall_score: null,
  plan: null,
  created_at: '2026-07-02T09:00:00Z',
  completed_at: null,
};

/** A finished session with a report-scale (0-100) overall score. */
export const completedSession: SessionOut = {
  ...sampleSession,
  id: 's2',
  status: 'completed',
  overall_score: 82,
  completed_at: '2026-07-02T09:20:00Z',
};

/** Two chronological sessions with readiness and topic trends plus a
 * three-priority curriculum — exercises every ProgressPage section. */
export const sampleProgress: ProgressOut = {
  user_id: 'u1',
  sessions: [
    {
      id: 's1',
      created_at: '2026-06-20T09:00:00Z',
      role: 'Data Scientist',
      mode: 'Quick Practice',
      difficulty: 'Senior',
      overall_score: 61,
      role_readiness: 55,
    },
    {
      id: 's2',
      created_at: '2026-07-01T09:00:00Z',
      role: 'Data Scientist',
      mode: 'Standard',
      difficulty: 'Senior',
      overall_score: 82,
      role_readiness: 74,
    },
  ],
  readiness_trend: [
    { session_id: 's1', created_at: '2026-06-20T09:00:00Z', score: 55 },
    { session_id: 's2', created_at: '2026-07-01T09:00:00Z', score: 74 },
  ],
  topic_trends: {
    Statistics: [
      { session_id: 's1', created_at: '2026-06-20T09:00:00Z', score: 3.0 },
      { session_id: 's2', created_at: '2026-07-01T09:00:00Z', score: 4.2 },
    ],
    SQL: [
      { session_id: 's1', created_at: '2026-06-20T09:00:00Z', score: 3.5 },
      { session_id: 's2', created_at: '2026-07-01T09:00:00Z', score: 2.4 },
    ],
  },
  current_weak_topics: ['SQL'],
  current_strong_topics: ['Statistics'],
  curriculum: [
    {
      title: 'Practice SQL window functions',
      reason: 'SQL dropped to 2.4 in your latest session.',
      wiki_refs: ['sql/window-functions'],
      priority: 1,
      source_sessions: ['s2'],
    },
    {
      title: 'Review experiment design basics',
      reason: 'Recurring gaps in A/B testing follow-ups.',
      wiki_refs: [],
      priority: 2,
      source_sessions: ['s1', 's2'],
    },
    {
      title: 'Read an intro to causal inference',
      reason: 'Stretch goal once statistics stays strong.',
      wiki_refs: ['stats/causal-inference'],
      priority: 3,
      source_sessions: ['s2'],
    },
  ],
};

/** A progress payload for a known user with no completed history. */
export const emptyProgress: ProgressOut = {
  user_id: 'u1',
  sessions: [],
  readiness_trend: [],
  topic_trends: {},
  current_weak_topics: [],
  current_strong_topics: [],
  curriculum: [],
};

export const sampleReport: ReportOut = {
  session_id: 's1',
  overall_score: 82,
  role_readiness: 74,
  topic_scores: { Statistics: 4.2, SQL: 3.1, Probability: 2.4 },
  best_answers: [{ question: 'Explain p-values', score: 4.5, why: 'Clear and rigorous.' }],
  weakest_answers: [
    { question: 'Explain A/B testing pitfalls', score: 2.0, why: 'Missed novelty effects.' },
  ],
  missing_concepts: ['Bonferroni correction'],
  communication_feedback: 'Speak a little more slowly.',
  technical_feedback: 'Solid statistical fundamentals.',
  suggested_study_plan: [
    'Review experiment design basics',
    'Practice SQL window functions',
    'Read an intro to causal inference',
  ],
  recommended_next_interview: {
    role: 'Data Scientist',
    mode: 'Standard',
    difficulty: 'Senior',
    focus_topics: ['Statistics'],
  },
  questions_asked: ['Explain p-values', 'Explain A/B testing pitfalls'],
  transcript_summary: 'A focused session covering statistics and SQL.',
  hints_used_total: 2,
  time_per_question: [{ question_id: 'q1', question_text: 'Explain p-values', seconds: 93.2 }],
  created_at: '2026-07-02T10:00:00Z',
};
