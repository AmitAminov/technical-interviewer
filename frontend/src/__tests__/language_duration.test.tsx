/**
 * Setup form: the duration bar was removed (duration is derived from the mode),
 * and the language selector offers English + Hebrew (DESIGN.md §2, §10).
 */
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import SetupPage from '../pages/SetupPage';

function renderSetup() {
  return render(
    <MemoryRouter>
      <SetupPage />
    </MemoryRouter>,
  );
}

describe('Duration removal and language options', () => {
  it('no longer renders a duration slider', () => {
    renderSetup();
    expect(
      screen.queryByRole('slider', { name: 'Duration (minutes)' }),
    ).not.toBeInTheDocument();
  });

  it('presents "Deep Dive" rather than the internal "Deep Research" value', () => {
    renderSetup();
    expect(screen.getByRole('button', { name: /^Deep Dive/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Deep Research/ })).not.toBeInTheDocument();
  });

  it('offers English and Hebrew interview languages', () => {
    renderSetup();
    const select = screen.getByLabelText('Language') as HTMLSelectElement;
    const values = Array.from(select.options).map((o) => o.value);
    expect(values).toContain('en');
    expect(values).toContain('he');
    expect(screen.getByRole('option', { name: /Hebrew/ })).toBeInTheDocument();
  });
});
