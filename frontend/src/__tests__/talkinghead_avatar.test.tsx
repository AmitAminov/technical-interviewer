/**
 * TalkingHeadAvatar fallback chain: when the dynamic 3D import fails (or
 * WebGL is unavailable, as in jsdom) the existing SVG <Avatar> renders
 * unchanged. There is no renderer toggle — the interview always uses the best
 * available renderer automatically.
 */
import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import TalkingHeadAvatar from '../components/TalkingHeadAvatar';

// The 3D stack must never load for real in jsdom; make any import attempt
// blow up the way a failed network chunk load would.
vi.mock('@met4citizen/talkinghead', () => {
  throw new Error('dynamic import failed (mocked)');
});

describe('TalkingHeadAvatar', () => {
  it('renders the SVG avatar when WebGL is unavailable (jsdom default)', () => {
    render(<TalkingHeadAvatar style="Friendly" name="Friendly" speaking={false} />);
    expect(screen.getByTestId('avatar-svg-stage')).toBeInTheDocument();
    expect(
      screen.getByRole('img', { name: /Friendly interviewer avatar/ }),
    ).toBeInTheDocument();
  });

  it('falls back to the SVG avatar when the dynamic 3D import fails', async () => {
    // Pretend WebGL exists so the component actually attempts the import.
    const getContext = vi
      .spyOn(HTMLCanvasElement.prototype, 'getContext')
      .mockReturnValue({} as unknown as RenderingContext);
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);

    render(<TalkingHeadAvatar style="Strict" name="Strict" speaking={false} />);
    // 3D stage mounts first (loading state)…
    expect(screen.getByTestId('avatar-3d-stage')).toBeInTheDocument();
    // …then the import rejects and the SVG fallback takes over.
    await waitFor(() => {
      expect(screen.getByTestId('avatar-svg-stage')).toBeInTheDocument();
    });
    expect(screen.getByRole('img', { name: /Strict interviewer avatar/ })).toBeInTheDocument();
    expect(warn).toHaveBeenCalled();
    getContext.mockRestore();
  });

  it('renders no renderer toggle (the interview auto-selects)', () => {
    render(<TalkingHeadAvatar style="Friendly" name="Friendly" speaking={false} />);
    expect(screen.queryByTestId('avatar-mode-toggle')).not.toBeInTheDocument();
  });
});
