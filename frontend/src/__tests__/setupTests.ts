/**
 * Global Vitest setup (DESIGN.md §10 tests): jest-dom matchers, fresh
 * browser-API mocks (WebSocket / speech / media / matchMedia /
 * scrollIntoView) before each test, and a clean Zustand store.
 */
import '@testing-library/jest-dom/vitest';

import { cleanup } from '@testing-library/react';
import { afterEach, beforeEach, vi } from 'vitest';

import { useInterviewStore } from '../lib/store';
import { voiceEngine } from '../lib/voice';
import { installBrowserMocks } from './helpers/fakes';

beforeEach(() => {
  window.localStorage.clear();
  installBrowserMocks();
  voiceEngine.resetForTests();
  useInterviewStore.getState().resetInterview();
  useInterviewStore.setState({ userId: null, userName: '', prefill: null });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
