/**
 * Barge-in: a sustained candidate utterance while the interviewer is speaking
 * stops the interviewer's TTS and notifies the backend; a short (echo-like)
 * partial does not.
 */
import { act } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { FakeSpeechRecognition } from './helpers/fakes';
import { startActiveInterview } from './helpers/interview';
import { useInterviewStore } from '../lib/store';
import { voiceEngine } from '../lib/voice';

describe('Barge-in over the interviewer', () => {
  afterEach(() => vi.restoreAllMocks());

  it('interrupts and notifies the backend on a sustained interjection', async () => {
    const socket = await startActiveInterview();
    const recognizer = FakeSpeechRecognition.instances[0];
    const interruptSpy = vi.spyOn(voiceEngine, 'interrupt');
    act(() => useInterviewStore.getState().setSpeaking(true));

    act(() => recognizer.emitPartial('wait can you repeat'));

    expect(interruptSpy).toHaveBeenCalled();
    expect(useInterviewStore.getState().speaking).toBe(false);
    const barge = socket.sentMessages().filter((msg) => msg.type === 'barge_in');
    expect(barge).toHaveLength(1);
    expect(barge[0].text).toBe('wait can you repeat');
  });

  it('ignores a short echo-like partial while speaking', async () => {
    const socket = await startActiveInterview();
    const recognizer = FakeSpeechRecognition.instances[0];
    act(() => useInterviewStore.getState().setSpeaking(true));
    const interruptSpy = vi.spyOn(voiceEngine, 'interrupt');

    act(() => recognizer.emitPartial('mm'));

    expect(useInterviewStore.getState().speaking).toBe(true);
    expect(socket.sentMessages().filter((m) => m.type === 'barge_in')).toHaveLength(0);
    expect(interruptSpy).not.toHaveBeenCalled();
  });

  it('does not barge in on the interviewer\'s own echoed words', async () => {
    const socket = await startActiveInterview();
    const recognizer = FakeSpeechRecognition.instances[0];
    const interruptSpy = vi.spyOn(voiceEngine, 'interrupt');
    const store = useInterviewStore.getState();
    // The interviewer is currently saying this line; the mic re-hears part of it.
    act(() => store.addEntry('interviewer', 'Tell me about a project you are proud of'));
    act(() => useInterviewStore.getState().setSpeaking(true));

    // >=3 words, but every word is from the interviewer's own line → echo.
    act(() => recognizer.emitPartial('about a project you are proud'));

    expect(interruptSpy).not.toHaveBeenCalled();
    expect(useInterviewStore.getState().speaking).toBe(true);
    expect(socket.sentMessages().filter((m) => m.type === 'barge_in')).toHaveLength(0);
  });
});
