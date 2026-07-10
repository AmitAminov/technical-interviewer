/**
 * Per-answer score dashboard (DESIGN.md §10): the 8 rubric metrics (1–5)
 * as bars, the weighted overall score and the interviewer's feedback.
 * Rendered inside the slide-in score toast after each scored answer.
 */
import { scoreTone } from '../lib/scoreTone';
import { METRIC_LABELS, type ScoreMessage } from '../lib/types';

export interface ScoreDashboardProps {
  score: ScoreMessage;
  compact?: boolean;
}

export default function ScoreDashboard({ score, compact = false }: ScoreDashboardProps) {
  return (
    <div data-testid="score-dashboard">
      <div className="mb-3 flex items-baseline justify-between">
        <h3 className="text-sm font-semibold text-slate-200">Answer score</h3>
        <span className="text-2xl font-bold text-indigo-300" data-testid="score-overall">
          {score.overall.toFixed(1)}
          <span className="ml-0.5 text-xs font-normal text-slate-400">/5</span>
        </span>
      </div>
      <div className={`grid gap-x-6 gap-y-1.5 ${compact ? 'grid-cols-1' : 'grid-cols-2'}`}>
        {METRIC_LABELS.map(([key, label]) => {
          const value = score.scores[key];
          return (
            <div key={key} className="flex items-center gap-2">
              <span className="w-32 shrink-0 truncate text-xs text-slate-400">{label}</span>
              <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-800">
                <span
                  className={`block h-full rounded-full ${scoreTone(value, 5).bg}`}
                  style={{ width: `${(value / 5) * 100}%` }}
                  data-testid={`metric-bar-${key}`}
                />
              </span>
              <span className="w-7 text-right text-xs font-medium text-slate-300">{value}/5</span>
            </div>
          );
        })}
      </div>
      {score.feedback && (
        <p className="mt-3 border-t border-slate-800 pt-2 text-xs leading-relaxed text-slate-400">
          {score.feedback}
        </p>
      )}
    </div>
  );
}
