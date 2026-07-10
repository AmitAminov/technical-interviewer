import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import Timer, { formatClock } from '../components/Timer';

describe('Timer', () => {
  it('renders elapsed and remaining time as mm:ss', () => {
    render(<Timer elapsedSeconds={65} remainingSeconds={1735} status="active" />);
    expect(screen.getByTestId('timer-elapsed')).toHaveTextContent('01:05');
    expect(screen.getByTestId('timer-remaining')).toHaveTextContent('28:55');
  });

  it('shows a Paused badge while paused', () => {
    render(<Timer elapsedSeconds={30} remainingSeconds={570} status="paused" />);
    expect(screen.getByText('Paused')).toBeInTheDocument();
  });

  it('does not show the Paused badge while active', () => {
    render(<Timer elapsedSeconds={30} remainingSeconds={570} status="active" />);
    expect(screen.queryByText('Paused')).not.toBeInTheDocument();
  });

  it('never renders negative clocks', () => {
    expect(formatClock(-5)).toBe('00:00');
    expect(formatClock(0)).toBe('00:00');
    expect(formatClock(3599)).toBe('59:59');
  });
});
