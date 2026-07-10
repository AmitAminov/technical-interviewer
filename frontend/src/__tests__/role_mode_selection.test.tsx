import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
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

describe('Role and mode selection', () => {
  it('shows role-specific focus topics after picking a role', async () => {
    const user = userEvent.setup();
    renderSetup();

    expect(screen.queryByRole('button', { name: 'Transformers' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /^AI Engineer/ }));
    expect(screen.getByRole('button', { name: 'Transformers' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'GPU memory' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /^Algorithm Researcher/ }));
    expect(screen.queryByRole('button', { name: 'Transformers' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Dynamic programming' })).toBeInTheDocument();
  });

  it('marks the selected role as pressed', async () => {
    const user = userEvent.setup();
    renderSetup();
    const roleButton = screen.getByRole('button', { name: /^Data Scientist/ });
    expect(roleButton).toHaveAttribute('aria-pressed', 'false');
    await user.click(roleButton);
    expect(roleButton).toHaveAttribute('aria-pressed', 'true');
  });

  it('shows the Deep Dive mode and no longer renders a duration slider', async () => {
    const user = userEvent.setup();
    renderSetup();

    await user.click(screen.getByRole('button', { name: /^Deep Dive/ }));
    expect(screen.getByRole('button', { name: /^Deep Dive/ })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    // Duration is derived from the mode now; the slider was removed.
    expect(
      screen.queryByRole('slider', { name: 'Duration (minutes)' }),
    ).not.toBeInTheDocument();
  });
});
