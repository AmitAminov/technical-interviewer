/**
 * Progress page: cross-session growth tracking for the current user —
 * readiness trend (pure-SVG line chart, 0–100), per-topic trend rows with
 * delta arrows vs the previous session (0–5, same HTML-bar pattern as the
 * report's topic chart), current weak/strong topic chips, a prioritized
 * study curriculum (Now / Next / Later checklist persisted in localStorage)
 * and a session-history mini-table linking to each report.
 */
import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { ApiError, getProgress } from '../lib/api';
import { scoreTone } from '../lib/scoreTone';
import { useInterviewStore } from '../lib/store';
import {
  modeLabel,
  type CurriculumItem,
  type CurriculumPriority,
  type ProgressOut,
  type ReadinessPoint,
  type TopicTrendPoint,
} from '../lib/types';

// ----------------------------------------------------- curriculum persistence
const CURRICULUM_DONE_KEY = 'ti_curriculum_done';

function readDoneTitles(): Set<string> {
  try {
    const raw = window.localStorage.getItem(CURRICULUM_DONE_KEY);
    if (!raw) return new Set();
    const parsed = JSON.parse(raw) as unknown;
    return new Set(
      Array.isArray(parsed) ? parsed.filter((v): v is string => typeof v === 'string') : [],
    );
  } catch {
    return new Set();
  }
}

function writeDoneTitles(titles: Set<string>): void {
  try {
    window.localStorage.setItem(CURRICULUM_DONE_KEY, JSON.stringify([...titles]));
  } catch {
    /* storage unavailable — non-fatal */
  }
}

// ------------------------------------------------------------ SVG widgets
function shortDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

/** Pure-SVG readiness line chart: score 0–100 vs session index, one dot per
 * session (scoreTone colors) plus a connecting line and date labels. */
function ReadinessTrendChart({ points }: { points: ReadinessPoint[] }) {
  if (points.length === 0) {
    return <p className="text-sm text-slate-400">No readiness scores recorded yet.</p>;
  }
  const width = 640;
  const height = 220;
  const pad = { top: 20, right: 24, bottom: 34, left: 40 };
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const x = (i: number) =>
    pad.left + (points.length === 1 ? innerW / 2 : (i / (points.length - 1)) * innerW);
  const y = (score: number) =>
    pad.top + innerH - (Math.max(0, Math.min(100, score)) / 100) * innerH;
  const linePath = points
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(p.score).toFixed(1)}`)
    .join(' ');
  // Thin out date labels when the history is long so they stay readable.
  const labelStep = Math.max(1, Math.ceil(points.length / 8));
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="w-full"
      role="img"
      aria-label={`Role readiness trend across ${points.length} session${points.length === 1 ? '' : 's'}, latest ${Math.round(points[points.length - 1].score)} out of 100`}
      data-testid="readiness-trend"
    >
      {[0, 50, 100].map((v) => (
        <g key={v}>
          <line
            x1={pad.left}
            x2={width - pad.right}
            y1={y(v)}
            y2={y(v)}
            className="stroke-slate-800"
            strokeWidth="1"
          />
          <text x={pad.left - 8} y={y(v) + 3.5} textAnchor="end" className="fill-slate-500" fontSize="10">
            {v}
          </text>
        </g>
      ))}
      {points.length > 1 && (
        <path
          d={linePath}
          fill="none"
          className="stroke-indigo-400"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      )}
      {points.map((p, i) => (
        <g key={p.session_id}>
          <circle cx={x(i)} cy={y(p.score)} r="4.5" className={scoreTone(p.score, 100).fill} />
          <text
            x={x(i)}
            y={y(p.score) - 9}
            textAnchor="middle"
            className="fill-slate-300"
            fontSize="10"
            fontWeight="700"
          >
            {Math.round(p.score)}
          </text>
          {(i % labelStep === 0 || i === points.length - 1) && (
            <text
              x={x(i)}
              y={height - pad.bottom + 18}
              textAnchor="middle"
              className="fill-slate-500"
              fontSize="10"
            >
              {shortDate(p.created_at)}
            </text>
          )}
        </g>
      ))}
    </svg>
  );
}

// ------------------------------------------------------------ topic trends
/** ▲ emerald / ▼ rose / – slate delta vs the previous session (text glyphs,
 * not emoji, with explicit aria-labels for screen readers). */
function DeltaArrow({ delta }: { delta: number | null }) {
  const base = 'w-14 shrink-0 text-right text-xs font-semibold';
  if (delta === null) {
    return (
      <span className={`${base} text-slate-500`} aria-label="No previous session to compare">
        –
      </span>
    );
  }
  const rounded = Math.round(delta * 10) / 10;
  if (rounded > 0) {
    return (
      <span
        className={`${base} text-emerald-400`}
        aria-label={`Improved by ${rounded.toFixed(1)} since the previous session`}
      >
        ▲ {rounded.toFixed(1)}
      </span>
    );
  }
  if (rounded < 0) {
    return (
      <span
        className={`${base} text-rose-400`}
        aria-label={`Dropped by ${Math.abs(rounded).toFixed(1)} since the previous session`}
      >
        ▼ {Math.abs(rounded).toFixed(1)}
      </span>
    );
  }
  return (
    <span className={`${base} text-slate-400`} aria-label="No change since the previous session">
      –
    </span>
  );
}

/** Compact per-topic row: name, last-score bar (same HTML-bar pattern as the
 * report's topic chart, 0–5) and the delta vs the previous session. */
function TopicTrendRow({ topic, points }: { topic: string; points: TopicTrendPoint[] }) {
  const last = points[points.length - 1];
  const prev = points.length > 1 ? points[points.length - 2] : null;
  const clamped = Math.max(0, Math.min(5, last?.score ?? 0));
  return (
    <div className="flex items-center gap-3" data-testid={`topic-trend-${topic}`}>
      <span className="basis-40 shrink-0 truncate text-right text-xs text-slate-400" title={topic}>
        {topic}
      </span>
      <div className="h-3.5 flex-1 overflow-hidden rounded-full bg-slate-800">
        <div
          className={`h-full rounded-full ${scoreTone(clamped, 5).bg}`}
          style={{ width: `${(clamped / 5) * 100}%` }}
        />
      </div>
      <span className="w-8 shrink-0 text-xs font-semibold text-slate-200">{clamped.toFixed(1)}</span>
      <DeltaArrow delta={prev && last ? last.score - prev.score : null} />
    </div>
  );
}

// ------------------------------------------------------------ curriculum
const PRIORITY_GROUPS: Array<{ priority: CurriculumPriority; label: string }> = [
  { priority: 1, label: 'Now' },
  { priority: 2, label: 'Next' },
  { priority: 3, label: 'Later' },
];

function CurriculumRow({
  item,
  done,
  onToggle,
}: {
  item: CurriculumItem;
  done: boolean;
  onToggle: () => void;
}) {
  return (
    <li>
      <label className="flex cursor-pointer items-start gap-3 text-sm text-slate-300">
        <input
          type="checkbox"
          className="mt-0.5 h-5 w-5 accent-indigo-500"
          checked={done}
          onChange={onToggle}
        />
        <span className="min-w-0 flex-1">
          <span className={`font-medium ${done ? 'text-slate-400 line-through' : 'text-slate-200'}`}>
            {item.title}
          </span>
          <span className="mt-0.5 block text-xs leading-relaxed text-slate-400">{item.reason}</span>
          {item.wiki_refs.length > 0 && (
            <span className="mt-1.5 flex flex-wrap gap-1.5">
              {item.wiki_refs.map((ref) => (
                <span
                  key={ref}
                  className="chip border-slate-700 bg-slate-800/70 px-2 py-0.5 text-[11px] text-slate-300"
                >
                  {ref}
                </span>
              ))}
            </span>
          )}
        </span>
      </label>
    </li>
  );
}

// ------------------------------------------------------------ page
type LoadState = 'loading' | 'ready' | 'error';

function EmptyState() {
  return (
    <div className="mx-auto max-w-lg px-6 py-20 text-center">
      <h1 className="text-2xl font-bold text-slate-100">No progress to show yet</h1>
      <p className="mt-3 text-sm leading-relaxed text-slate-400">
        Complete an interview to start tracking progress.
      </p>
      <Link to="/" className="btn btn-primary mt-6">
        Set up an interview
      </Link>
    </div>
  );
}

export default function ProgressPage() {
  const userId = useInterviewStore((state) => state.userId);

  const [progress, setProgress] = useState<ProgressOut | null>(null);
  const [loadState, setLoadState] = useState<LoadState>('loading');
  const [errorDetail, setErrorDetail] = useState('');
  const [doneTitles, setDoneTitles] = useState<Set<string>>(() => readDoneTitles());

  const load = useCallback(async () => {
    if (!userId) {
      setLoadState('ready');
      return;
    }
    setLoadState('loading');
    try {
      const data = await getProgress(userId);
      setProgress(data);
      setLoadState('ready');
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        // Unknown user on the server — same as having no history.
        setProgress(null);
        setLoadState('ready');
      } else {
        setErrorDetail(err instanceof ApiError ? err.detail : 'Unexpected error');
        setLoadState('error');
      }
    }
  }, [userId]);

  useEffect(() => {
    void load();
  }, [load]);

  const toggleDone = (title: string) => {
    setDoneTitles((current) => {
      const next = new Set(current);
      if (next.has(title)) next.delete(title);
      else next.add(title);
      writeDoneTitles(next);
      return next;
    });
  };

  if (loadState === 'loading') {
    return (
      <div className="flex min-h-[60vh] items-center justify-center gap-3 text-slate-400">
        <span className="spinner" />
        Loading progress…
      </div>
    );
  }

  if (loadState === 'error') {
    return (
      <div className="mx-auto max-w-lg px-6 py-20 text-center">
        <h1 className="text-2xl font-bold text-slate-100">Could not load your progress</h1>
        <p className="mt-3 text-sm leading-relaxed text-slate-400">{errorDetail}</p>
        <div className="mt-6 flex justify-center">
          <button type="button" className="btn btn-primary" onClick={() => void load()}>
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (!userId || !progress || progress.sessions.length === 0) {
    return <EmptyState />;
  }

  // Weakest-latest first: ascending by each topic's most recent score.
  const topicRows = Object.entries(progress.topic_trends)
    .filter(([, points]) => points.length > 0)
    .sort(([, a], [, b]) => a[a.length - 1].score - b[b.length - 1].score);

  const latestReadiness =
    progress.readiness_trend.length > 0
      ? progress.readiness_trend[progress.readiness_trend.length - 1].score
      : null;

  // Mini-table shows the latest session first (sessions arrive chronological).
  const historyRows = [...progress.sessions].reverse();

  return (
    <div className="mx-auto max-w-4xl space-y-8 px-6 py-10">
      <header className="flex flex-wrap items-center justify-between gap-6">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-slate-100">Your progress</h1>
          <p className="mt-1 text-sm text-slate-400">
            Readiness, topic trends and a study plan across {progress.sessions.length} session
            {progress.sessions.length === 1 ? '' : 's'}.
          </p>
        </div>
        {latestReadiness !== null && (
          <div className="text-right">
            <p className={`text-3xl font-bold ${scoreTone(latestReadiness, 100).text}`}>
              {Math.round(latestReadiness)}
              <span className="text-base font-semibold text-slate-500">/100</span>
            </p>
            <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">
              Current readiness
            </p>
          </div>
        )}
      </header>

      <section className="card p-6">
        <h2 className="mb-4 text-lg font-semibold text-slate-200">Role readiness trend</h2>
        <ReadinessTrendChart points={progress.readiness_trend} />
      </section>

      <section className="card p-6">
        <h2 className="mb-4 text-lg font-semibold text-slate-200">Topic trends</h2>
        {topicRows.length === 0 ? (
          <p className="text-sm text-slate-400">No topic scores recorded yet.</p>
        ) : (
          <div className="space-y-2.5" data-testid="topic-trends">
            {topicRows.map(([topic, points]) => (
              <TopicTrendRow key={topic} topic={topic} points={points} />
            ))}
          </div>
        )}
        {(progress.current_weak_topics.length > 0 || progress.current_strong_topics.length > 0) && (
          <div className="mt-5 space-y-3 border-t border-slate-800 pt-4">
            {progress.current_weak_topics.length > 0 && (
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                  Needs work
                </span>
                {progress.current_weak_topics.map((topic) => (
                  <span key={topic} className="chip border-rose-500/40 bg-rose-950/30 text-rose-200">
                    {topic}
                  </span>
                ))}
              </div>
            )}
            {progress.current_strong_topics.length > 0 && (
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                  Strengths
                </span>
                {progress.current_strong_topics.map((topic) => (
                  <span
                    key={topic}
                    className="chip border-emerald-500/40 bg-emerald-950/30 text-emerald-200"
                  >
                    {topic}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}
      </section>

      {progress.curriculum.length > 0 && (
        <section className="card p-6">
          <h2 className="mb-4 text-lg font-semibold text-slate-200">Study curriculum</h2>
          <div className="space-y-5">
            {PRIORITY_GROUPS.map(({ priority, label }) => {
              const items = progress.curriculum.filter((item) => item.priority === priority);
              if (items.length === 0) return null;
              return (
                <div key={priority}>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
                    {label}
                  </h3>
                  <ul className="space-y-3">
                    {items.map((item) => (
                      <CurriculumRow
                        key={item.title}
                        item={item}
                        done={doneTitles.has(item.title)}
                        onToggle={() => toggleDone(item.title)}
                      />
                    ))}
                  </ul>
                </div>
              );
            })}
          </div>
        </section>
      )}

      <section className="card p-6">
        <h2 className="mb-4 text-lg font-semibold text-slate-200">Session history</h2>
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-slate-800 text-xs uppercase tracking-wider text-slate-400">
              <th className="py-2 pr-4 font-semibold">Date</th>
              <th className="py-2 pr-4 font-semibold">Interview</th>
              <th className="py-2 pr-4 text-right font-semibold">Score</th>
              <th className="py-2 pr-4 text-right font-semibold">Readiness</th>
              <th className="py-2 text-right font-semibold">Report</th>
            </tr>
          </thead>
          <tbody>
            {historyRows.map((session) => (
              <tr key={session.id} className="border-b border-slate-800/50">
                <td className="py-2 pr-4 whitespace-nowrap text-slate-400">
                  {new Date(session.created_at).toLocaleDateString()}
                </td>
                <td className="py-2 pr-4 text-slate-300">
                  <span className="font-medium text-slate-200">{session.role}</span>
                  <span className="text-slate-400">
                    {' '}
                    · {modeLabel(session.mode)} · {session.difficulty}
                  </span>
                </td>
                <td className="py-2 pr-4 text-right font-mono text-slate-300">
                  {session.overall_score !== null ? Math.round(session.overall_score) : '—'}
                </td>
                <td className="py-2 pr-4 text-right font-mono text-slate-300">
                  {session.role_readiness !== null ? Math.round(session.role_readiness) : '—'}
                </td>
                <td className="py-2 text-right">
                  <Link
                    to={`/report/${session.id}`}
                    className="text-indigo-300 transition-colors hover:text-indigo-200"
                  >
                    View report
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
