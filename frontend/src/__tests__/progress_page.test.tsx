import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

import { useInterviewStore } from '../lib/store';
import ProgressPage from '../pages/ProgressPage';
import { emptyProgress, jsonResponse, sampleProgress } from './helpers/fakes';

function renderProgress() {
  return render(
    <MemoryRouter initialEntries={['/progress']}>
      <ProgressPage />
    </MemoryRouter>,
  );
}

describe('ProgressPage', () => {
  it('renders the readiness trend, topic trends and curriculum from the API payload', async () => {
    useInterviewStore.setState({ userId: 'u1' });
    const fetchMock = vi.fn(async (_input: RequestInfo | URL) => jsonResponse(sampleProgress));
    vi.stubGlobal('fetch', fetchMock);
    renderProgress();

    // readiness trend chart (pure SVG) with the latest score in the label
    expect(
      await screen.findByLabelText('Role readiness trend across 2 sessions, latest 74 out of 100'),
    ).toBeInTheDocument();
    expect(String(fetchMock.mock.calls[0][0])).toBe('/api/users/u1/progress');

    // topic rows sorted weakest-latest first (SQL 2.4 before Statistics 4.2)
    const trends = screen.getByTestId('topic-trends');
    const rows = within(trends).getAllByTestId(/topic-trend-/);
    expect(rows[0]).toHaveTextContent('SQL');
    expect(rows[1]).toHaveTextContent('Statistics');
    // delta arrows vs the previous session, with accessible labels
    expect(
      within(rows[0]).getByLabelText('Dropped by 1.1 since the previous session'),
    ).toHaveTextContent('▼');
    expect(
      within(rows[1]).getByLabelText('Improved by 1.2 since the previous session'),
    ).toHaveTextContent('▲');

    // weak / strong topic chips
    expect(screen.getByText('Needs work')).toBeInTheDocument();
    expect(screen.getByText('Strengths')).toBeInTheDocument();

    // curriculum grouped by priority with reasons and wiki-ref chips
    expect(screen.getByText('Now')).toBeInTheDocument();
    expect(screen.getByText('Next')).toBeInTheDocument();
    expect(screen.getByText('Later')).toBeInTheDocument();
    expect(screen.getByText('Practice SQL window functions')).toBeInTheDocument();
    expect(screen.getByText('SQL dropped to 2.4 in your latest session.')).toBeInTheDocument();
    expect(screen.getByText('sql/window-functions')).toBeInTheDocument();

    // session history mini-table linking each session to its report
    const reportLinks = screen.getAllByRole('link', { name: 'View report' });
    expect(reportLinks).toHaveLength(2);
    expect(reportLinks.map((link) => link.getAttribute('href'))).toEqual(
      expect.arrayContaining(['/report/s1', '/report/s2']),
    );
  });

  it('shows the empty state with a CTA when the user has no history', async () => {
    useInterviewStore.setState({ userId: 'u1' });
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(emptyProgress)),
    );
    renderProgress();

    expect(
      await screen.findByText('Complete an interview to start tracking progress.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Set up an interview' })).toHaveAttribute('href', '/');
  });

  it('treats an unknown user (404) as having no history', async () => {
    useInterviewStore.setState({ userId: 'ghost' });
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ detail: 'user not found' }, 404)),
    );
    renderProgress();

    expect(
      await screen.findByText('Complete an interview to start tracking progress.'),
    ).toBeInTheDocument();
  });

  it('persists curriculum checklist state in localStorage across remounts', async () => {
    useInterviewStore.setState({ userId: 'u1' });
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(sampleProgress)),
    );
    const user = userEvent.setup();
    const first = renderProgress();

    const checkbox = await screen.findByRole('checkbox', {
      name: /practice sql window functions/i,
    });
    expect(checkbox).not.toBeChecked();
    await user.click(checkbox);
    expect(checkbox).toBeChecked();
    expect(window.localStorage.getItem('ti_curriculum_done')).toContain(
      'Practice SQL window functions',
    );

    // a fresh mount restores the checked state from localStorage
    first.unmount();
    renderProgress();
    expect(
      await screen.findByRole('checkbox', { name: /practice sql window functions/i }),
    ).toBeChecked();
    // unchecking clears it from storage
    await user.click(
      screen.getByRole('checkbox', { name: /practice sql window functions/i }),
    );
    expect(window.localStorage.getItem('ti_curriculum_done')).not.toContain(
      'Practice SQL window functions',
    );
  });
});
