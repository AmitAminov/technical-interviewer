/**
 * Global Zustand store (DESIGN.md §10 store.ts): session config, WS state,
 * transcript entries, scores, timer, hints, avatar speaking state.
 */
import { create } from 'zustand';

import type { ScoreMessage, SessionCreate, SessionOut, Speaker, WsStatus } from './types';

export type InterviewStatus = 'idle' | 'active' | 'paused' | 'completed';

export interface LocalTranscriptEntry {
  id: number;
  speaker: Speaker;
  text: string;
}

const USER_ID_KEY = 'ti_user_id';
const USER_NAME_KEY = 'ti_user_name';

function readStored(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStored(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* storage unavailable — non-fatal */
  }
}

let entrySeq = 0;

export interface InterviewStore {
  // identity (persisted to localStorage so SessionsPage can list history)
  userId: string | null;
  userName: string;
  setUser: (id: string, name: string) => void;

  // setup prefill for "Start recommended interview"
  prefill: Partial<SessionCreate> | null;
  setPrefill: (prefill: Partial<SessionCreate> | null) => void;

  // session + connection
  session: SessionOut | null;
  setSession: (session: SessionOut | null) => void;
  wsStatus: WsStatus;
  setWsStatus: (status: WsStatus) => void;

  // interview runtime
  status: InterviewStatus;
  setStatus: (status: InterviewStatus) => void;
  elapsedSeconds: number;
  remainingSeconds: number;
  syncTimer: (elapsed: number, remaining: number) => void;
  tick: () => void;

  entries: LocalTranscriptEntry[];
  addEntry: (speaker: Speaker, text: string) => void;
  partialText: string;
  setPartial: (text: string) => void;

  scores: ScoreMessage[];
  lastScore: ScoreMessage | null;
  addScore: (score: ScoreMessage) => void;
  dismissScore: () => void;

  hintsUsed: number;
  setHintsUsed: (n: number) => void;

  section: string;
  sectionIndex: number;
  totalSections: number;
  setSection: (name: string, index: number, total: number) => void;
  setSectionName: (name: string) => void;

  questionIndex: number;
  totalQuestions: number;
  questionOpen: boolean;
  currentQuestionId: string | null;
  questionShownAt: number | null;
  openQuestion: (id: string | null, index: number, total: number) => void;
  closeQuestion: () => void;

  speaking: boolean;
  setSpeaking: (speaking: boolean) => void;
  wordTick: number;
  bumpWord: () => void;

  micEnabled: boolean;
  setMicEnabled: (enabled: boolean) => void;
  micError: string | null;
  setMicError: (message: string | null) => void;

  waiting: boolean;
  setWaiting: (waiting: boolean) => void;
  checkinPending: boolean;
  setCheckinPending: (pending: boolean) => void;
  reportReady: boolean;
  setReportReady: (ready: boolean) => void;
  errorMessage: string | null;
  setError: (message: string | null) => void;

  /** Reset all per-interview runtime state (keeps user identity + prefill). */
  resetInterview: () => void;
}

const runtimeDefaults = {
  session: null as SessionOut | null,
  wsStatus: 'idle' as WsStatus,
  status: 'idle' as InterviewStatus,
  elapsedSeconds: 0,
  remainingSeconds: 0,
  entries: [] as LocalTranscriptEntry[],
  partialText: '',
  scores: [] as ScoreMessage[],
  lastScore: null as ScoreMessage | null,
  hintsUsed: 0,
  section: '',
  sectionIndex: 0,
  totalSections: 0,
  questionIndex: 0,
  totalQuestions: 0,
  questionOpen: false,
  currentQuestionId: null as string | null,
  questionShownAt: null as number | null,
  speaking: false,
  wordTick: 0,
  micEnabled: false,
  micError: null as string | null,
  waiting: false,
  checkinPending: false,
  reportReady: false,
  errorMessage: null as string | null,
};

export const useInterviewStore = create<InterviewStore>()((set) => ({
  userId: readStored(USER_ID_KEY),
  userName: readStored(USER_NAME_KEY) ?? '',
  setUser: (id, name) => {
    writeStored(USER_ID_KEY, id);
    writeStored(USER_NAME_KEY, name);
    set({ userId: id, userName: name });
  },

  prefill: null,
  setPrefill: (prefill) => set({ prefill }),

  ...runtimeDefaults,

  setSession: (session) =>
    set((state) => ({
      session,
      // Initialize the countdown from duration until the server sends real
      // elapsed/remaining values in `state` messages.
      remainingSeconds:
        session && state.status === 'idle' && state.elapsedSeconds === 0
          ? session.duration_minutes * 60
          : state.remainingSeconds,
    })),
  setWsStatus: (wsStatus) => set({ wsStatus }),
  setStatus: (status) => set({ status }),
  syncTimer: (elapsed, remaining) =>
    set({ elapsedSeconds: elapsed, remainingSeconds: Math.max(0, remaining) }),
  tick: () =>
    set((state) =>
      state.status === 'active'
        ? {
            elapsedSeconds: state.elapsedSeconds + 1,
            remainingSeconds: Math.max(0, state.remainingSeconds - 1),
          }
        : {},
    ),

  addEntry: (speaker, text) =>
    set((state) => ({
      entries: [...state.entries, { id: (entrySeq += 1), speaker, text }],
    })),
  setPartial: (partialText) => set({ partialText }),

  addScore: (score) =>
    set((state) => ({ scores: [...state.scores, score], lastScore: score })),
  dismissScore: () => set({ lastScore: null }),

  setHintsUsed: (hintsUsed) => set({ hintsUsed }),

  setSection: (section, sectionIndex, totalSections) =>
    set({ section, sectionIndex, totalSections }),
  setSectionName: (section) => set({ section }),

  openQuestion: (currentQuestionId, questionIndex, totalQuestions) =>
    set({
      currentQuestionId,
      questionIndex,
      totalQuestions,
      questionOpen: true,
      questionShownAt: Date.now(),
    }),
  closeQuestion: () => set({ questionOpen: false, questionShownAt: null }),

  setSpeaking: (speaking) => set({ speaking }),
  bumpWord: () => set((state) => ({ wordTick: state.wordTick + 1 })),

  setMicEnabled: (micEnabled) => set({ micEnabled }),
  setMicError: (micError) => set({ micError }),

  setWaiting: (waiting) => set({ waiting }),
  setCheckinPending: (checkinPending) => set({ checkinPending }),
  setReportReady: (reportReady) => set({ reportReady }),
  setError: (errorMessage) => set({ errorMessage }),

  resetInterview: () => set({ ...runtimeDefaults }),
}));
