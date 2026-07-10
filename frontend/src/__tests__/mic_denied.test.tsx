import { act, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { FakeSpeechRecognition, removeSpeechRecognition } from './helpers/fakes';
import { renderInterview, startActiveInterview } from './helpers/interview';

describe('Microphone fallback states', () => {
  it('shows a text-only mode banner when speech recognition is unsupported', async () => {
    removeSpeechRecognition();
    await renderInterview();

    const banner = await screen.findByTestId('text-mode-banner');
    expect(banner).toHaveTextContent(/text-only mode/i);
    // mic control disabled, typing still available
    expect(screen.getByRole('button', { name: /mic off/i })).toBeDisabled();
    expect(screen.getByLabelText('Answer input')).toBeEnabled();
  });

  it('falls back to text mode when the mic permission is denied at runtime', async () => {
    await startActiveInterview();

    // The mic starts on by default at the Start gesture; simulate the browser
    // denying access at runtime.
    const recognizer = FakeSpeechRecognition.instances[0];
    expect(recognizer).toBeDefined();
    expect(screen.getByRole('button', { name: /mic on/i })).toBeInTheDocument();
    act(() => recognizer.emitError('not-allowed'));

    const banner = await screen.findByTestId('mic-error-banner');
    expect(banner).toHaveTextContent(/denied.*text-only mode/i);
    // mic switched back off and disabled
    expect(screen.getByRole('button', { name: /mic off/i })).toBeDisabled();
    expect(screen.getByLabelText('Answer input')).toBeEnabled();
  });
});
