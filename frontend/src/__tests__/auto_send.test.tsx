/**
 * Stop-of-speech auto-submit (DESIGN.md §10): a voice final followed by
 * ~2.5s of no further speech or typing submits the answer automatically;
 * resumed speech or manual editing disarms the countdown.
 */
import { act, fireEvent, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { FakeSpeechRecognition } from './helpers/fakes';
import { startActiveInterview } from './helpers/interview';

const QUESTION = {
  type: 'interviewer',
  kind: 'question',
  text: 'What is a p-value?',
  section: 'background',
  question_id: 'q1',
  question_index: 0,
  total_questions: 5,
};

async function activeInterviewWithMicOn() {
  // The mic is on by default now (started at the "Start interview" gesture).
  const socket = await startActiveInterview();
  act(() => socket.receive(QUESTION));
  const recognizer = FakeSpeechRecognition.instances[0];
  expect(recognizer).toBeDefined();
  return { socket, recognizer };
}

describe('Stop-of-speech auto-submit', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('submits the voice answer ~2.5s after the last final result', async () => {
    const { socket, recognizer } = await activeInterviewWithMicOn();

    vi.useFakeTimers();
    act(() => recognizer.emitFinal('Probability of data under the null hypothesis.'));
    act(() => {
      vi.advanceTimersByTime(2_600);
    });

    const answers = socket.sentMessages().filter((m) => m.type === 'answer');
    expect(answers).toHaveLength(1);
    expect(answers[0].text).toBe('Probability of data under the null hypothesis.');
    expect(answers[0].input_mode).toBe('voice');
  });

  it('re-arms while the user keeps talking and disarms on manual typing', async () => {
    const { socket, recognizer } = await activeInterviewWithMicOn();

    vi.useFakeTimers();
    act(() => recognizer.emitFinal('First part of my answer.'));
    act(() => {
      vi.advanceTimersByTime(1_500);
    });
    // Resumed speech before the countdown fires: no submit yet.
    act(() => recognizer.emitPartial('and additionally'));
    act(() => {
      vi.advanceTimersByTime(2_600);
    });
    expect(socket.sentMessages().filter((m) => m.type === 'answer')).toHaveLength(0);

    // A new final re-arms the countdown — but manual editing disarms it.
    act(() => recognizer.emitFinal('and additionally the significance level.'));
    fireEvent.change(screen.getByLabelText('Answer input'), {
      target: { value: 'Edited by hand' },
    });
    act(() => {
      vi.advanceTimersByTime(5_000);
    });
    expect(socket.sentMessages().filter((m) => m.type === 'answer')).toHaveLength(0);
  });
});
