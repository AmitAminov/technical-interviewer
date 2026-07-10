/** Shared helpers for InterviewPage tests. */
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { vi } from 'vitest';

import InterviewPage from '../../pages/InterviewPage';
import { voiceEngine } from '../../lib/voice';
import { FakeWebSocket, jsonResponse, sampleSession } from './fakes';

/**
 * Render the interview room for session s1 with a mocked session fetch, click
 * the "Start interview" gate (the WS only connects after that gesture), then
 * wait for the fake WebSocket to be constructed and return it.
 */
export async function renderInterview(): Promise<FakeWebSocket> {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => jsonResponse(sampleSession)),
  );
  // Drive the interviewer's speech deterministically: real TTS is an async
  // fetch→AudioContext chain that jsdom can't run and fake timers stall. The
  // interviewer speaks and finishes synchronously here — modelling that it
  // completes its turn before the candidate answers (so store.speaking toggles
  // true→false rather than getting stuck true and blocking answer submission).
  vi.spyOn(voiceEngine, 'speak').mockImplementation((_text, _opts, callbacks) => {
    callbacks?.onStart?.();
    callbacks?.onEnd?.();
  });
  const user = userEvent.setup();
  render(
    <MemoryRouter initialEntries={['/interview/s1']}>
      <Routes>
        <Route path="/interview/:id" element={<InterviewPage />} />
        <Route path="/report/:id" element={<div>report page</div>} />
        <Route path="/sessions" element={<div>sessions page</div>} />
      </Routes>
    </MemoryRouter>,
  );
  // The start gate is enabled once the session has loaded.
  const begin = await screen.findByTestId('begin-interview');
  await waitFor(() => {
    if ((begin as HTMLButtonElement).disabled) throw new Error('session not loaded yet');
  });
  await user.click(begin);
  await waitFor(() => {
    if (FakeWebSocket.instances.length === 0) throw new Error('socket not created yet');
  });
  return FakeWebSocket.instances[0];
}

/** Open the socket and mark the interview active via a server state message. */
export async function startActiveInterview(): Promise<FakeWebSocket> {
  const socket = await renderInterview();
  act(() => socket.open());
  act(() =>
    socket.receive({
      type: 'state',
      status: 'active',
      elapsed_seconds: 0,
      remaining_seconds: 1200,
    }),
  );
  return socket;
}
