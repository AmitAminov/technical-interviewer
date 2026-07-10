/**
 * Bottom control bar of the interview room (DESIGN.md §10): mic toggle,
 * hint, skip, pause/resume, end interview, plus the always-available answer
 * composer. Voice finals accumulate into the composer and auto-submit ~2.5s
 * after speech stops (DESIGN.md §10 stop-of-speech); "Send answer" (or
 * Enter) submits immediately.
 */
import type { KeyboardEvent } from 'react';

import type { InterviewStatus } from '../lib/store';
import HintButton from './HintButton';

function MicIcon({ off }: { off?: boolean }) {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="9" y="2" width="6" height="12" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0" />
      <line x1="12" y1="18" x2="12" y2="22" />
      {off && <line x1="4" y1="3" x2="20" y2="21" />}
    </svg>
  );
}

function CameraIcon({ off }: { off?: boolean }) {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M23 7l-7 5 7 5V7z" />
      <rect x="1" y="5" width="15" height="14" rx="2" ry="2" />
      {off && <line x1="4" y1="3" x2="20" y2="21" />}
    </svg>
  );
}

export interface ControlsProps {
  status: InterviewStatus;
  micEnabled: boolean;
  micAvailable: boolean;
  cameraEnabled: boolean;
  cameraAvailable: boolean;
  hintPolicy: string;
  hintsUsed: number;
  draft: string;
  canSend: boolean;
  /** True while the interviewer is speaking — the candidate answers after. */
  speaking: boolean;
  /** Composer text direction (rtl for Hebrew interviews). */
  composerDir?: 'ltr' | 'rtl';
  onToggleMic: () => void;
  onToggleCamera: () => void;
  onHint: () => void;
  onSkip: () => void;
  onPause: () => void;
  onResume: () => void;
  onEnd: () => void;
  onDraftChange: (value: string) => void;
  onSend: () => void;
}

export default function Controls({
  status,
  micEnabled,
  micAvailable,
  cameraEnabled,
  cameraAvailable,
  hintPolicy,
  hintsUsed,
  draft,
  canSend,
  speaking,
  composerDir = 'ltr',
  onToggleMic,
  onToggleCamera,
  onHint,
  onSkip,
  onPause,
  onResume,
  onEnd,
  onDraftChange,
  onSend,
}: ControlsProps) {
  const busy = status === 'completed';

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      onSend();
    }
  };

  return (
    <div className="border-t border-slate-800 bg-slate-950/95 px-4 py-3">
      <div className="mx-auto flex max-w-6xl flex-col gap-3">
        <div className="flex items-end gap-2">
          <textarea
            className="input min-h-[44px] flex-1 resize-none max-sm:min-h-[58px]"
            dir={composerDir}
            rows={1}
            placeholder={
              speaking
                ? 'Interviewer is speaking — you can type; send when they finish'
                : micAvailable
                  ? 'Speak or type — Enter to send'
                  : 'Type your answer — Enter to send'
            }
            aria-label="Answer input"
            value={draft}
            onChange={(event) => onDraftChange(event.target.value)}
            onKeyDown={handleKeyDown}
            disabled={busy}
          />
          <button
            type="button"
            className="btn btn-primary h-[44px]"
            onClick={onSend}
            disabled={!canSend || !draft.trim()}
          >
            Send answer
          </button>
        </div>

        <div className="flex flex-wrap items-center justify-center gap-2">
          <button
            type="button"
            className={`btn ${micEnabled ? 'bg-emerald-500 text-white hover:bg-emerald-400' : 'btn-ghost'}`}
            onClick={onToggleMic}
            disabled={!micAvailable || busy}
            aria-pressed={micEnabled}
            title={micAvailable ? 'Toggle microphone' : 'Voice input unavailable'}
          >
            <MicIcon off={!micEnabled} />
            {micEnabled ? 'Mic on' : 'Mic off'}
          </button>

          <button
            type="button"
            className={`btn ${cameraEnabled ? 'bg-emerald-500 text-white hover:bg-emerald-400' : 'btn-ghost'}`}
            onClick={onToggleCamera}
            disabled={!cameraAvailable || busy}
            aria-pressed={cameraEnabled}
            title={cameraAvailable ? 'Toggle camera' : 'Camera unavailable'}
            data-testid="camera-toggle"
          >
            <CameraIcon off={!cameraEnabled} />
            {cameraEnabled ? 'Camera on' : 'Camera off'}
          </button>

          <HintButton
            policy={hintPolicy}
            hintsUsed={hintsUsed}
            onRequest={onHint}
            disabled={busy || status !== 'active'}
          />

          <button type="button" className="btn btn-ghost" onClick={onSkip} disabled={busy || status !== 'active'}>
            Skip
          </button>

          {status === 'paused' ? (
            <button type="button" className="btn btn-ghost" onClick={onResume}>
              Resume
            </button>
          ) : (
            <button type="button" className="btn btn-ghost" onClick={onPause} disabled={status !== 'active'}>
              Pause
            </button>
          )}

          <button type="button" className="btn btn-danger" onClick={onEnd} disabled={busy}>
            End interview
          </button>
        </div>
      </div>
    </div>
  );
}
