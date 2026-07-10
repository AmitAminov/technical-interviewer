import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

import { useInterviewStore } from '../lib/store';
import SessionsPage from '../pages/SessionsPage';
import { completedSession, jsonResponse, sampleSession } from './helpers/fakes';

function renderSessions() {
  return render(
    <MemoryRouter>
      <SessionsPage />
    </MemoryRouter>,
  );
}

describe('SessionsPage', () => {
  it('shows the overall score on the 0-100 report scale', async () => {
    useInterviewStore.setState({ userId: 'u1' });
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse([sampleSession, completedSession])),
    );
    renderSessions();

    // completed session (overall_score: 82) renders as a rounded /100 score
    expect(await screen.findByText('82/100')).toBeInTheDocument();
    // the unscored session shows no score badge, and nothing uses the old /5 form
    expect(screen.queryByText(/\/5\b/)).not.toBeInTheDocument();
    expect(screen.getAllByText(/Data Scientist/).length).toBe(2);
  });

  it('confirms session deletion through the accessible dialog instead of window.confirm', async () => {
    useInterviewStore.setState({ userId: 'u1' });
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'DELETE') return jsonResponse({ ok: true });
      return jsonResponse([completedSession]);
    });
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();
    renderSessions();

    await user.click(await screen.findByRole('button', { name: 'Delete session' }));
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveTextContent('This cannot be undone.');

    // Cancelling closes the dialog without deleting.
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(false);

    // Confirming performs the DELETE.
    await user.click(screen.getByRole('button', { name: 'Delete session' }));
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Delete session' }));
    expect(await screen.findByText('Session deleted.')).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(true);
  });
});
