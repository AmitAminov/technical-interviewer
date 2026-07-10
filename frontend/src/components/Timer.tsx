/**
 * Interview timer (DESIGN.md §10): shows mm:ss elapsed and remaining.
 * The values come from the store — ticked locally every second while active
 * and re-synced from server `state` messages; pausing stops the tick.
 */
import type { InterviewStatus } from '../lib/store';

export interface TimerProps {
  elapsedSeconds: number;
  remainingSeconds: number;
  status: InterviewStatus;
}

export function formatClock(totalSeconds: number): string {
  const safe = Math.max(0, Math.floor(totalSeconds));
  const minutes = Math.floor(safe / 60);
  const seconds = safe % 60;
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}

export default function Timer({ elapsedSeconds, remainingSeconds, status }: TimerProps) {
  const lowTime = status !== 'completed' && remainingSeconds > 0 && remainingSeconds < 60;
  return (
    <div className="flex items-center gap-3 rounded-full border border-slate-700 bg-slate-900/80 px-4 py-1.5 font-mono text-sm">
      <span className="flex items-center gap-1.5" title="Elapsed time">
        <span
          className={`h-2 w-2 rounded-full ${
            status === 'active'
              ? 'animate-pulse bg-emerald-400'
              : status === 'paused'
                ? 'bg-amber-400'
                : 'bg-slate-500'
          }`}
        />
        <span className="text-slate-200" data-testid="timer-elapsed">
          {formatClock(elapsedSeconds)}
        </span>
      </span>
      <span className="text-slate-600">/</span>
      <span
        className={lowTime ? 'text-rose-400' : 'text-slate-400'}
        title="Remaining time"
        data-testid="timer-remaining"
      >
        {formatClock(remainingSeconds)} left
      </span>
      {status === 'paused' && (
        <span className="rounded-full bg-amber-500/20 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-amber-300">
          Paused
        </span>
      )}
    </div>
  );
}
