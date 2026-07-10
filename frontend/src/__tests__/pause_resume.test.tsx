import { act, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { startActiveInterview } from './helpers/interview';

describe('Pause / resume flow', () => {
  it('sends start on socket open and syncs the timer from server state', async () => {
    const socket = await startActiveInterview();
    expect(socket.sentMessages()[0]).toEqual({ type: 'start' });
    // remaining 1200s from the state message
    expect(screen.getByTestId('timer-remaining')).toHaveTextContent('20:00');
    expect(screen.queryByText('Paused')).not.toBeInTheDocument();
  });

  it('sends pause, shows paused state, then resumes', async () => {
    const socket = await startActiveInterview();
    const user = userEvent.setup();

    await user.click(screen.getByRole('button', { name: 'Pause' }));
    expect(socket.sentMessages()).toContainEqual({ type: 'pause' });
    expect(screen.getByText('Paused')).toBeInTheDocument();

    const resumeButton = screen.getByRole('button', { name: 'Resume' });
    await user.click(resumeButton);
    expect(socket.sentMessages()).toContainEqual({ type: 'resume' });
    expect(screen.queryByText('Paused')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Pause' })).toBeInTheDocument();
  });

  it('reflects a server-driven pause via state messages', async () => {
    const socket = await startActiveInterview();
    act(() =>
      socket.receive({
        type: 'state',
        status: 'paused',
        elapsed_seconds: 65,
        remaining_seconds: 1135,
      }),
    );
    expect(screen.getByText('Paused')).toBeInTheDocument();
    expect(screen.getByTestId('timer-elapsed')).toHaveTextContent('01:05');
  });
});
