import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import VideoPreview from '../components/VideoPreview';
import { initialsOf } from '../components/VideoPreview';

describe('VideoPreview camera fallback', () => {
  it('shows an initials tile when camera permission is denied', async () => {
    (navigator.mediaDevices.getUserMedia as ReturnType<typeof vi.fn>).mockRejectedValue(
      new DOMException('Permission denied', 'NotAllowedError'),
    );
    render(<VideoPreview name="Amit Aminov" />);

    expect(await screen.findByText('AA')).toBeInTheDocument();
    expect(screen.getByText('Camera off')).toBeInTheDocument();
    expect(screen.getByTestId('camera-video')).toHaveClass('hidden');
  });

  it('shows the mirrored video once the camera stream starts', async () => {
    render(<VideoPreview name="Amit Aminov" />);
    await waitFor(() => expect(screen.getByTestId('camera-video')).not.toHaveClass('hidden'));
    expect(screen.getByTestId('camera-video')).toHaveStyle({ transform: 'scaleX(-1)' });
    expect(screen.queryByTestId('camera-fallback')).not.toBeInTheDocument();
  });

  it('falls back when mediaDevices is entirely unavailable', async () => {
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      writable: true,
      value: undefined,
    });
    render(<VideoPreview name="Solo" />);
    expect(await screen.findByText('S')).toBeInTheDocument();
    expect(screen.getByText('Camera off')).toBeInTheDocument();
  });

  it('derives initials sensibly', () => {
    expect(initialsOf('Amit Aminov')).toBe('AA');
    expect(initialsOf('Cher')).toBe('C');
    expect(initialsOf('')).toBe('YO');
  });
});
