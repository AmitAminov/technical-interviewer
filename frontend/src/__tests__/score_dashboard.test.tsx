import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import ScoreDashboard from '../components/ScoreDashboard';
import type { ScoreMessage } from '../lib/types';

const score: ScoreMessage = {
  type: 'score',
  question_id: 'q1',
  scores: {
    correctness: 4,
    depth: 3,
    clarity: 5,
    structure: 3,
    practicality: 2,
    mathematical_rigor: 1,
    tradeoff_awareness: 4,
    communication: 5,
  },
  overall: 3.7,
  feedback: 'Good coverage of the main points; go deeper on the math next time.',
};

describe('ScoreDashboard', () => {
  it('renders all 8 rubric metrics with values', () => {
    render(<ScoreDashboard score={score} />);
    for (const label of [
      'Correctness',
      'Depth',
      'Clarity',
      'Structure',
      'Practicality',
      'Mathematical rigor',
      'Trade-off awareness',
      'Communication',
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(screen.getAllByText('5/5')).toHaveLength(2); // clarity + communication
    expect(screen.getByText('1/5')).toBeInTheDocument(); // mathematical rigor
  });

  it('renders the weighted overall score', () => {
    render(<ScoreDashboard score={score} />);
    expect(screen.getByTestId('score-overall')).toHaveTextContent('3.7');
  });

  it('scales metric bars by value', () => {
    render(<ScoreDashboard score={score} />);
    expect(screen.getByTestId('metric-bar-correctness')).toHaveStyle({ width: '80%' });
    expect(screen.getByTestId('metric-bar-mathematical_rigor')).toHaveStyle({ width: '20%' });
  });

  it('shows the feedback text', () => {
    render(<ScoreDashboard score={score} />);
    expect(screen.getByText(/go deeper on the math/i)).toBeInTheDocument();
  });
});
