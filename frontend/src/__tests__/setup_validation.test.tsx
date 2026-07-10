import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

import SetupPage from '../pages/SetupPage';
import { jsonResponse, sampleSession } from './helpers/fakes';

function renderSetup() {
  return render(
    <MemoryRouter>
      <SetupPage />
    </MemoryRouter>,
  );
}

describe('SetupPage validation', () => {
  it('blocks submission and shows clear errors for missing required fields', async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    const user = userEvent.setup();
    renderSetup();

    await user.click(screen.getByRole('button', { name: /start interview/i }));

    expect(screen.getByText('Enter your name.')).toBeInTheDocument();
    expect(screen.getByText('Select a role.')).toBeInTheDocument();
    expect(screen.getByText('Select an interview mode.')).toBeInTheDocument();
    expect(screen.getByText('Select a difficulty level.')).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('creates the user and session when the form is valid', async () => {
    const fetchSpy = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/users') {
        return jsonResponse({
          id: 'u1',
          name: 'Amit',
          target_roles: ['Data Scientist'],
          created_at: '2026-07-02T09:00:00Z',
        });
      }
      if (url === '/api/sessions') {
        return jsonResponse(sampleSession);
      }
      return jsonResponse({ detail: 'unexpected' }, 500);
    });
    vi.stubGlobal('fetch', fetchSpy);
    const user = userEvent.setup();
    renderSetup();

    await user.type(screen.getByLabelText('Your name'), 'Amit');
    await user.click(screen.getByRole('button', { name: /^Data Scientist/ }));
    await user.click(screen.getByRole('button', { name: /^Standard/ }));
    await user.click(screen.getByRole('button', { name: 'Senior' }));
    await user.click(screen.getByRole('button', { name: /start interview/i }));

    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2));
    const [usersUrl, usersInit] = fetchSpy.mock.calls[0] as unknown as [string, RequestInit];
    expect(usersUrl).toBe('/api/users');
    expect(JSON.parse(String(usersInit.body))).toMatchObject({ name: 'Amit' });

    const [sessionsUrl, sessionsInit] = fetchSpy.mock.calls[1] as unknown as [string, RequestInit];
    expect(sessionsUrl).toBe('/api/sessions');
    const body = JSON.parse(String(sessionsInit.body));
    expect(body).toMatchObject({
      user_id: 'u1',
      role: 'Data Scientist',
      mode: 'Standard',
      difficulty: 'Senior',
    });
    // Standard mode duration must stay within the 45–60 range.
    expect(body.duration_minutes).toBeGreaterThanOrEqual(45);
    expect(body.duration_minutes).toBeLessThanOrEqual(60);
  });

  it('requires a resume file when the resume toggle is on', async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    const user = userEvent.setup();
    renderSetup();

    await user.type(screen.getByLabelText('Your name'), 'Amit');
    await user.click(screen.getByRole('button', { name: /^Data Scientist/ }));
    await user.click(screen.getByRole('button', { name: /^Standard/ }));
    await user.click(screen.getByRole('button', { name: 'Senior' }));
    await user.click(screen.getByLabelText(/use my resume/i));
    await user.click(screen.getByRole('button', { name: /start interview/i }));

    expect(screen.getByText(/attach a \.pdf or \.txt resume/i)).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
