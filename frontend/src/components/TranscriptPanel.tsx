/**
 * Live transcript panel (DESIGN.md §10): auto-scrolling, speaker-labeled,
 * with the in-progress partial line shown in italics.
 */
import { useEffect, useRef } from 'react';

import type { LocalTranscriptEntry } from '../lib/store';

export interface TranscriptPanelProps {
  entries: LocalTranscriptEntry[];
  partialText: string;
  /** Show the "interviewer is thinking" indicator. */
  waiting?: boolean;
  /** Text direction for the spoken content (rtl for Hebrew). */
  dir?: 'ltr' | 'rtl';
}

const SPEAKER_META: Record<string, { label: string; color: string }> = {
  interviewer: { label: 'Interviewer', color: 'text-indigo-300' },
  candidate: { label: 'You', color: 'text-emerald-300' },
  system: { label: 'System', color: 'text-slate-400' },
};

export default function TranscriptPanel({
  entries,
  partialText,
  waiting,
  dir = 'ltr',
}: TranscriptPanelProps) {
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [entries.length, partialText, waiting]);

  return (
    <div
      className="flex h-full flex-col gap-3 overflow-y-auto px-4 py-3"
      role="log"
      aria-label="Interview transcript"
    >
      {entries.length === 0 && !partialText && (
        <p className="mt-6 text-center text-sm text-slate-400">
          The conversation transcript will appear here.
        </p>
      )}
      {entries.map((entry) => {
        const meta = SPEAKER_META[entry.speaker] ?? SPEAKER_META.system;
        return (
          <div key={entry.id} className="animate-fade-in">
            <span className={`text-xs font-semibold uppercase tracking-wider ${meta.color}`}>
              {meta.label}
            </span>
            <p
              dir={dir}
              className="mt-0.5 whitespace-pre-wrap text-sm leading-relaxed text-slate-200"
            >
              {entry.text}
            </p>
          </div>
        );
      })}
      {partialText && (
        <div data-testid="partial-line">
          <span className="text-xs font-semibold uppercase tracking-wider text-emerald-300/70">
            You (speaking…)
          </span>
          <p dir={dir} className="mt-0.5 text-sm italic leading-relaxed text-slate-400">
            {partialText}
          </p>
        </div>
      )}
      {waiting && (
        <div className="flex items-center gap-1.5 text-xs text-slate-400" data-testid="thinking">
          <span>Interviewer is thinking</span>
          <span className="animate-typing-dot">●</span>
          <span className="animate-typing-dot [animation-delay:0.2s]">●</span>
          <span className="animate-typing-dot [animation-delay:0.4s]">●</span>
        </div>
      )}
      <div ref={endRef} />
    </div>
  );
}
