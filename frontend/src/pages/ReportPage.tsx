/**
 * Final report page (DESIGN.md §10 ReportPage): renders every ReportOut
 * field — score rings (overall + role readiness, 0–100), a horizontal
 * bar chart of topic scores (0–5), best/weakest answers,
 * missing concepts, feedback, study-plan checklist, next-interview
 * recommendation, questions asked, transcript summary, hints and timing.
 * Handles the "report not ready" state with retry/regenerate.
 */
import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';

import { ApiError, getReport, regenerateReport } from '../lib/api';
import { scoreTone } from '../lib/scoreTone';
import { useInterviewStore } from '../lib/store';
import {
  modeLabel,
  type AnswerHighlight,
  type Difficulty,
  type Mode,
  type ReportOut,
  type Role,
  type SessionCreate,
} from '../lib/types';

// ------------------------------------------------------------ SVG widgets
function ScoreRing({ value, label }: { value: number; label: string }) {
  const radius = 52;
  const circumference = 2 * Math.PI * radius;
  const pct = Math.max(0, Math.min(100, value));
  const dash = (pct / 100) * circumference;
  return (
    <div className="flex flex-col items-center gap-2">
      <svg viewBox="0 0 120 120" width={128} height={128} role="img" aria-label={`${label}: ${pct} out of 100`}>
        <circle cx="60" cy="60" r={radius} fill="none" className="stroke-slate-800" strokeWidth="10" />
        <circle
          cx="60"
          cy="60"
          r={radius}
          fill="none"
          className={scoreTone(pct, 100).stroke}
          strokeWidth="10"
          strokeLinecap="round"
          strokeDasharray={`${dash} ${circumference - dash}`}
          transform="rotate(-90 60 60)"
        />
        <text x="60" y="66" textAnchor="middle" className="fill-slate-100" fontSize="26" fontWeight="700">
          {pct}
        </text>
      </svg>
      <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">{label}</span>
    </div>
  );
}

/** Horizontal bar chart of topic scores (0–5) — pure SVG per DESIGN.md §10
 * (no chart lib): one row per topic with label, track, fill and value. */
function TopicBarChart({ topicScores }: { topicScores: Record<string, number> }) {
  const topics = Object.entries(topicScores);
  if (topics.length === 0) {
    return <p className="text-sm text-slate-400">No topic scores recorded.</p>;
  }
  const ROW_H = 26;
  const WIDTH = 640;
  const LABEL_W = 170;
  const VALUE_W = 40;
  const BAR_X = LABEL_W + 12;
  const BAR_W = WIDTH - BAR_X - VALUE_W;
  const height = topics.length * ROW_H;
  return (
    <svg
      viewBox={`0 0 ${WIDTH} ${height}`}
      className="w-full"
      role="img"
      aria-label="Topic scores bar chart"
      data-testid="topic-bar-chart"
    >
      {topics.map(([topic, score], i) => {
        const clamped = Math.max(0, Math.min(5, score));
        const cy = i * ROW_H + ROW_H / 2;
        const label = topic.length > 26 ? `${topic.slice(0, 25)}…` : topic;
        return (
          <g key={topic}>
            <text x={LABEL_W} y={cy + 4} textAnchor="end" fontSize="12" className="fill-slate-400">
              {label !== topic && <title>{topic}</title>}
              {label}
            </text>
            <rect x={BAR_X} y={cy - 7} width={BAR_W} height={14} rx={7} className="fill-slate-800" />
            {clamped > 0 && (
              <rect
                x={BAR_X}
                y={cy - 7}
                width={Math.max((clamped / 5) * BAR_W, 14)}
                height={14}
                rx={7}
                className={scoreTone(clamped, 5).fill}
              />
            )}
            <text
              x={WIDTH - 4}
              y={cy + 4}
              textAnchor="end"
              fontSize="12"
              fontWeight="600"
              className="fill-slate-200"
            >
              {clamped.toFixed(1)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/** Card colors follow the actual score (a "best" answer at 1.4/5 must not
 * read as green): >=4 emerald, >=2.5 amber, else rose. */
function answerCardClasses(score: number): { card: string; badge: string } {
  if (score >= 4) {
    return {
      card: 'border-emerald-500/30 bg-emerald-950/20',
      badge: 'bg-emerald-500/20 text-emerald-300',
    };
  }
  if (score >= 2.5) {
    return {
      card: 'border-amber-500/30 bg-amber-950/20',
      badge: 'bg-amber-500/20 text-amber-300',
    };
  }
  return {
    card: 'border-rose-500/30 bg-rose-950/20',
    badge: 'bg-rose-500/20 text-rose-300',
  };
}

function AnswerCard({ item }: { item: AnswerHighlight }) {
  const tone = answerCardClasses(item.score);
  return (
    <div className={`rounded-xl border p-4 ${tone.card}`}>
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm font-medium text-slate-200">{item.question}</p>
        <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-bold ${tone.badge}`}>
          {item.score.toFixed(1)}/5
        </span>
      </div>
      <p className="mt-2 text-xs leading-relaxed text-slate-400">{item.why}</p>
    </div>
  );
}

// ------------------------------------------------------------ page
type LoadState = 'loading' | 'ready' | 'not_ready' | 'error';

export default function ReportPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const setPrefill = useInterviewStore((state) => state.setPrefill);

  const [report, setReport] = useState<ReportOut | null>(null);
  const [loadState, setLoadState] = useState<LoadState>('loading');
  const [errorDetail, setErrorDetail] = useState('');
  const [regenerating, setRegenerating] = useState(false);
  const [checkedSteps, setCheckedSteps] = useState<Set<number>>(new Set());

  const load = useCallback(async () => {
    if (!id) return;
    setLoadState('loading');
    try {
      const data = await getReport(id);
      setReport(data);
      setLoadState('ready');
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setLoadState('not_ready');
      } else {
        setErrorDetail(err instanceof ApiError ? err.detail : 'Unexpected error');
        setLoadState('error');
      }
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleRegenerate = async () => {
    if (!id) return;
    setRegenerating(true);
    try {
      await regenerateReport(id);
    } catch {
      /* fall through to reload — GET reports the definitive state */
    }
    setRegenerating(false);
    void load();
  };

  const startRecommended = () => {
    if (!report?.recommended_next_interview) return;
    const rec = report.recommended_next_interview;
    const prefill: Partial<SessionCreate> = {
      role: rec.role as Role,
      mode: rec.mode as Mode,
      difficulty: rec.difficulty as Difficulty,
      focus_topics: rec.focus_topics,
    };
    setPrefill(prefill);
    navigate('/');
  };

  if (loadState === 'loading') {
    return (
      <div className="flex min-h-[60vh] items-center justify-center gap-3 text-slate-400">
        <span className="spinner" />
        Loading report…
      </div>
    );
  }

  if (loadState === 'not_ready' || loadState === 'error') {
    return (
      <div className="mx-auto max-w-lg px-6 py-20 text-center">
        <h1 className="text-2xl font-bold text-slate-100">
          {loadState === 'not_ready' ? 'Report not ready yet' : 'Could not load the report'}
        </h1>
        <p className="mt-3 text-sm leading-relaxed text-slate-400">
          {loadState === 'not_ready'
            ? 'The report for this session has not been generated yet (or generation failed). You can retry, or ask the server to regenerate it.'
            : errorDetail}
        </p>
        <div className="mt-6 flex justify-center gap-3">
          <button type="button" className="btn btn-ghost" onClick={() => void load()}>
            Retry
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => void handleRegenerate()}
            disabled={regenerating}
          >
            {regenerating ? 'Regenerating…' : 'Regenerate report'}
          </button>
        </div>
      </div>
    );
  }

  if (!report) return null;

  return (
    <div className="mx-auto max-w-4xl space-y-8 px-6 py-10">
      <header className="flex flex-wrap items-center justify-between gap-6">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-slate-100">Interview report</h1>
          <p className="mt-1 text-sm text-slate-400">
            Session report
            {report.created_at && ` · ${new Date(report.created_at).toLocaleString()}`}
          </p>
        </div>
        <div className="flex gap-8">
          <ScoreRing value={report.overall_score} label="Overall score" />
          <ScoreRing value={report.role_readiness} label="Role readiness" />
        </div>
      </header>

      <section className="card p-6">
        <h2 className="mb-4 text-lg font-semibold text-slate-200">
          Topic scores
        </h2>
        <TopicBarChart topicScores={report.topic_scores} />
      </section>

      <div className="grid gap-6 md:grid-cols-2">
        <section className="card p-6">
          <h2 className="mb-4 text-lg font-semibold text-slate-200">
            Best answers
          </h2>
          <div className="space-y-3">
            {report.best_answers.length === 0 && (
              <p className="text-sm text-slate-400">No scored answers.</p>
            )}
            {report.best_answers.map((item, index) => (
              <AnswerCard key={index} item={item} />
            ))}
          </div>
        </section>
        <section className="card p-6">
          <h2 className="mb-4 text-lg font-semibold text-slate-200">
            Weakest answers
          </h2>
          <div className="space-y-3">
            {report.weakest_answers.length === 0 && (
              <p className="text-sm text-slate-400">No scored answers.</p>
            )}
            {report.weakest_answers.map((item, index) => (
              <AnswerCard key={index} item={item} />
            ))}
          </div>
        </section>
      </div>

      {report.missing_concepts.length > 0 && (
        <section className="card p-6">
          <h2 className="mb-4 text-lg font-semibold text-slate-200">
            Missing concepts
          </h2>
          <div className="flex flex-wrap gap-2">
            {report.missing_concepts.map((concept) => (
              <span key={concept} className="chip border-amber-500/40 bg-amber-950/30 text-amber-200">
                {concept}
              </span>
            ))}
          </div>
        </section>
      )}

      <div className="grid gap-6 md:grid-cols-2">
        <section className="card p-6">
          <h2 className="mb-4 text-lg font-semibold text-slate-200">
            Technical feedback
          </h2>
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-300">
            {report.technical_feedback || '—'}
          </p>
        </section>
        <section className="card p-6">
          <h2 className="mb-4 text-lg font-semibold text-slate-200">
            Communication feedback
          </h2>
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-300">
            {report.communication_feedback || '—'}
          </p>
        </section>
      </div>

      <section className="card p-6">
        <h2 className="mb-4 text-lg font-semibold text-slate-200">
          Suggested study plan
        </h2>
        <ul className="space-y-2">
          {report.suggested_study_plan.map((item, index) => (
            <li key={index}>
              <label className="flex cursor-pointer items-start gap-3 text-sm text-slate-300">
                <input
                  type="checkbox"
                  className="mt-0.5 h-5 w-5 accent-indigo-500"
                  checked={checkedSteps.has(index)}
                  onChange={() =>
                    setCheckedSteps((current) => {
                      const next = new Set(current);
                      if (next.has(index)) next.delete(index);
                      else next.add(index);
                      return next;
                    })
                  }
                />
                <span className={checkedSteps.has(index) ? 'text-slate-400 line-through' : ''}>
                  {item}
                </span>
              </label>
            </li>
          ))}
        </ul>
      </section>

      {report.recommended_next_interview && (
        <section className="card flex flex-wrap items-center justify-between gap-4 border-indigo-500/30 p-6">
          <div>
            <h2 className="text-lg font-semibold text-slate-200">
              Recommended next interview
            </h2>
            <p className="mt-2 text-sm text-slate-200">
              <span className="font-semibold">{report.recommended_next_interview.role}</span>
              {' · '}
              {modeLabel(report.recommended_next_interview.mode)}
              {' · '}
              {report.recommended_next_interview.difficulty}
            </p>
            {report.recommended_next_interview.focus_topics.length > 0 && (
              <p className="mt-1 text-xs text-slate-400">
                Focus: {report.recommended_next_interview.focus_topics.join(', ')}
              </p>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            <Link to="/progress" className="btn btn-ghost">
              View progress
            </Link>
            <button type="button" className="btn btn-primary" onClick={startRecommended}>
              Start recommended interview
            </button>
          </div>
        </section>
      )}

      <section className="card p-6">
        <h2 className="mb-4 text-lg font-semibold text-slate-200">
          Questions asked
        </h2>
        <ol className="list-decimal space-y-1.5 pl-5 text-sm text-slate-300">
          {report.questions_asked.map((question, index) => (
            <li key={index}>{question}</li>
          ))}
        </ol>
      </section>

      <section className="card p-6">
        <h2 className="mb-4 text-lg font-semibold text-slate-200">
          Transcript summary
        </h2>
        <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-300">
          {report.transcript_summary || '—'}
        </p>
        <p className="mt-4 text-xs text-slate-400">
          Hints used (on answered questions): <span className="font-semibold text-slate-300">{report.hints_used_total}</span>
        </p>
      </section>

      {report.time_per_question.length > 0 && (
        <section className="card p-6">
          <h2 className="mb-4 text-lg font-semibold text-slate-200">
            Time per question
          </h2>
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-xs uppercase tracking-wider text-slate-400">
                <th className="py-2 pr-4 font-semibold">Question</th>
                <th className="py-2 text-right font-semibold">Time</th>
              </tr>
            </thead>
            <tbody>
              {report.time_per_question.map((row) => (
                <tr key={row.question_id} className="border-b border-slate-800/50">
                  <td className="py-2 pr-4 text-slate-300">{row.question_text}</td>
                  <td className="py-2 text-right font-mono text-slate-400">
                    {Math.round(row.seconds)}s
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
