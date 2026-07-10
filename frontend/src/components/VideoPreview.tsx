/**
 * Candidate camera self-view (DESIGN.md §10): mirrored getUserMedia preview
 * in a thumbnail tile. When the camera is unavailable or permission is
 * denied it degrades to an initials tile — the interview remains fully
 * usable without video.
 */
import { useEffect, useRef, useState } from 'react';

export interface VideoPreviewProps {
  name: string;
  /** When false, the camera is released and an "off" tile is shown. */
  enabled?: boolean;
}

export function initialsOf(name: string): string {
  const parts = name
    .split(/\s+/)
    .map((part) => part.trim())
    .filter(Boolean);
  if (parts.length === 0) return 'You'.slice(0, 2).toUpperCase();
  return parts
    .slice(0, 2)
    .map((part) => (part[0] ?? '').toUpperCase())
    .join('');
}

export default function VideoPreview({ name, enabled = true }: VideoPreviewProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [state, setState] = useState<'pending' | 'live' | 'denied' | 'off'>('pending');

  useEffect(() => {
    // Camera turned off from the controls: release the device and show the tile.
    if (!enabled) {
      setState('off');
      return;
    }
    let cancelled = false;
    let stream: MediaStream | null = null;
    const mediaDevices = navigator.mediaDevices;
    if (!mediaDevices || typeof mediaDevices.getUserMedia !== 'function') {
      setState('denied');
      return;
    }
    setState('pending');
    mediaDevices
      .getUserMedia({ video: true })
      .then((mediaStream) => {
        if (cancelled) {
          mediaStream.getTracks().forEach((track) => track.stop());
          return;
        }
        stream = mediaStream;
        setState('live');
        const video = videoRef.current;
        if (video) {
          video.srcObject = mediaStream;
          try {
            const playing = video.play();
            if (playing && typeof playing.catch === 'function') {
              playing.catch(() => {
                /* autoplay blocked — muted preview will start on interaction */
              });
            }
          } catch {
            /* jsdom / older browsers */
          }
        }
      })
      .catch(() => {
        if (!cancelled) setState('denied');
      });
    return () => {
      cancelled = true;
      stream?.getTracks().forEach((track) => track.stop());
    };
  }, [enabled]);

  return (
    <div className="relative h-full w-full overflow-hidden rounded-xl border border-slate-700/80 bg-slate-900 shadow-xl shadow-black/50">
      <video
        ref={videoRef}
        muted
        playsInline
        autoPlay
        className={`h-full w-full object-cover ${state === 'live' ? '' : 'hidden'}`}
        style={{ transform: 'scaleX(-1)' }}
        data-testid="camera-video"
      />
      {state !== 'live' && (
        <div
          className="flex h-full w-full flex-col items-center justify-center gap-1 bg-gradient-to-br from-slate-800 to-slate-900"
          data-testid="camera-fallback"
        >
          <span className="flex h-12 w-12 items-center justify-center rounded-full bg-indigo-500/30 text-lg font-bold text-indigo-200">
            {initialsOf(name)}
          </span>
          <span className="text-[10px] uppercase tracking-wider text-slate-400">
            {state === 'pending' ? 'Starting camera…' : 'Camera off'}
          </span>
        </div>
      )}
      <span className="absolute bottom-1.5 left-2 rounded bg-black/50 px-1.5 py-0.5 text-[10px] font-medium text-slate-200">
        {name || 'You'}
      </span>
    </div>
  );
}
