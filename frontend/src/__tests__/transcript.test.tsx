import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import TranscriptPanel from '../components/TranscriptPanel';
import type { LocalTranscriptEntry } from '../lib/store';

const entries: LocalTranscriptEntry[] = [
  { id: 1, speaker: 'interviewer', text: 'Tell me about overfitting.' },
  { id: 2, speaker: 'candidate', text: 'Overfitting is when a model memorizes noise.' },
  { id: 3, speaker: 'system', text: 'Session paused.' },
];

describe('TranscriptPanel', () => {
  it('renders entries with speaker labels', () => {
    render(<TranscriptPanel entries={entries} partialText="" />);
    expect(screen.getByText('Interviewer')).toBeInTheDocument();
    expect(screen.getByText('You')).toBeInTheDocument();
    expect(screen.getByText('System')).toBeInTheDocument();
    expect(screen.getByText('Tell me about overfitting.')).toBeInTheDocument();
    expect(screen.getByText('Overfitting is when a model memorizes noise.')).toBeInTheDocument();
  });

  it('renders the live partial line in italics', () => {
    render(<TranscriptPanel entries={entries} partialText="and regularization helps" />);
    const partial = screen.getByTestId('partial-line');
    expect(partial).toHaveTextContent('and regularization helps');
    const paragraph = partial.querySelector('p');
    expect(paragraph).not.toBeNull();
    expect(paragraph).toHaveClass('italic');
  });

  it('auto-scrolls to the latest entry', () => {
    const scrollSpy = vi.fn();
    Element.prototype.scrollIntoView = scrollSpy;
    render(<TranscriptPanel entries={entries} partialText="" />);
    expect(scrollSpy).toHaveBeenCalled();
  });

  it('shows the thinking indicator while waiting', () => {
    render(<TranscriptPanel entries={entries} partialText="" waiting />);
    expect(screen.getByTestId('thinking')).toHaveTextContent('Interviewer is thinking');
  });

  it('shows an empty-state message with no entries', () => {
    render(<TranscriptPanel entries={[]} partialText="" />);
    expect(screen.getByText(/transcript will appear here/i)).toBeInTheDocument();
  });
});
