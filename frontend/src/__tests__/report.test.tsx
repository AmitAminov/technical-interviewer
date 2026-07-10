import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

import ReportPage from '../pages/ReportPage';
import { jsonResponse, sampleReport } from './helpers/fakes';

function renderReport() {
  return render(
    <MemoryRouter initialEntries={['/report/s1']}>
      <Routes>
        <Route path="/report/:id" element={<ReportPage />} />
        <Route path="/" element={<div>setup page</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('ReportPage', () => {
  it('renders every report section when the report is ready', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(sampleReport)),
    );
    renderReport();

    // score rings (overall + readiness)
    expect(await screen.findByLabelText('Overall score: 82 out of 100')).toBeInTheDocument();
    expect(screen.getByLabelText('Role readiness: 74 out of 100')).toBeInTheDocument();
    // topic bar chart (pure SVG)
    expect(screen.getByTestId('topic-bar-chart')).toBeInTheDocument();
    expect(screen.getByText('Statistics')).toBeInTheDocument();
    expect(screen.getByText('4.2')).toBeInTheDocument();
    // highlights
    expect(screen.getAllByText('Explain p-values').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Clear and rigorous.')).toBeInTheDocument();
    expect(screen.getByText('Missed novelty effects.')).toBeInTheDocument();
    // missing concepts + feedback
    expect(screen.getByText('Bonferroni correction')).toBeInTheDocument();
    expect(screen.getByText('Solid statistical fundamentals.')).toBeInTheDocument();
    expect(screen.getByText('Speak a little more slowly.')).toBeInTheDocument();
    // study plan checklist
    expect(screen.getByText('Practice SQL window functions')).toBeInTheDocument();
    // recommendation, summary, hints, timing
    expect(screen.getByRole('button', { name: /start recommended interview/i })).toBeInTheDocument();
    expect(screen.getByText(/a focused session covering statistics/i)).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument(); // hints used total
    expect(screen.getByText('93s')).toBeInTheDocument();
  });

  it('lets the user check off study plan items', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(sampleReport)),
    );
    const user = userEvent.setup();
    renderReport();
    const checkbox = (await screen.findAllByRole('checkbox'))[0];
    expect(checkbox).not.toBeChecked();
    await user.click(checkbox);
    expect(checkbox).toBeChecked();
  });

  it('shows a graceful not-ready state and recovers via regenerate', async () => {
    let reportExists = false;
    const fetchSpy = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/report/regenerate') && init?.method === 'POST') {
        reportExists = true;
        return jsonResponse(sampleReport);
      }
      if (url.endsWith('/report')) {
        return reportExists
          ? jsonResponse(sampleReport)
          : jsonResponse({ detail: 'not ready' }, 404);
      }
      return jsonResponse({ detail: 'unexpected' }, 500);
    });
    vi.stubGlobal('fetch', fetchSpy);
    const user = userEvent.setup();
    renderReport();

    expect(await screen.findByText('Report not ready yet')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /regenerate report/i }));

    expect(await screen.findByText('Interview report')).toBeInTheDocument();
    await waitFor(() =>
      expect(
        fetchSpy.mock.calls.some(
          ([input, init]) =>
            String(input).endsWith('/report/regenerate') &&
            (init as RequestInit | undefined)?.method === 'POST',
        ),
      ).toBe(true),
    );
  });
});
