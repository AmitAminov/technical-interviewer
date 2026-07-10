import { act, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { startActiveInterview } from './helpers/interview';

describe('End interview flow', () => {
  it('asks for confirmation and does nothing when cancelled', async () => {
    const socket = await startActiveInterview();
    const user = userEvent.setup();

    await user.click(screen.getByRole('button', { name: 'End interview' }));
    expect(screen.getByRole('dialog')).toHaveTextContent('End the interview?');

    await user.click(screen.getByRole('button', { name: 'Keep going' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(socket.sentMessages()).not.toContainEqual({ type: 'end' });
  });

  it('sends end after confirmation, then shows the report link when ready', async () => {
    const socket = await startActiveInterview();
    const user = userEvent.setup();

    await user.click(screen.getByRole('button', { name: 'End interview' }));
    await user.click(screen.getByRole('button', { name: 'Yes, end interview' }));
    expect(socket.sentMessages()).toContainEqual({ type: 'end' });

    // Server wraps up: completed state, then report generated in background.
    act(() =>
      socket.receive({
        type: 'state',
        status: 'completed',
        elapsed_seconds: 900,
        remaining_seconds: 0,
      }),
    );
    expect(screen.getByText('Interview complete')).toBeInTheDocument();
    expect(screen.getByText(/generating your report/i)).toBeInTheDocument();

    act(() => socket.receive({ type: 'report_ready', session_id: 's1' }));
    const reportLink = screen.getByRole('link', { name: 'View report' });
    expect(reportLink).toHaveAttribute('href', '/report/s1');
    expect(screen.queryByText(/generating your report/i)).not.toBeInTheDocument();
  });

  it('records interviewer messages in the transcript before ending', async () => {
    const socket = await startActiveInterview();
    act(() =>
      socket.receive({
        type: 'interviewer',
        kind: 'greeting',
        text: 'Welcome! Ready to begin?',
        section: 'background',
        question_id: null,
        question_index: 0,
        total_questions: 6,
      }),
    );
    expect(screen.getAllByText('Welcome! Ready to begin?').length).toBeGreaterThanOrEqual(1);
  });
});
