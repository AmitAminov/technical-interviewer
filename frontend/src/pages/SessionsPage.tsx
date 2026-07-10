/**
 * Sessions page (DESIGN.md §10 SessionsPage): the user's interview history
 * with status/score, report links and privacy actions (delete session /
 * transcript / recording) — each behind a confirmation.
 */
import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import ConfirmDialog from '../components/ConfirmDialog';
import {
  ApiError,
  deleteRecording,
  deleteSession,
  deleteTranscript,
  getUserSessions,
} from '../lib/api';
import { useInterviewStore } from '../lib/store';
import { modeLabel, type SessionOut } from '../lib/types';

type DeleteKind = 'session' | 'transcript' | 'recording';

const DELETE_PROMPTS: Record<DeleteKind, { title: string; body: string; confirmLabel: string }> = {
  session: {
    title: 'Delete this session?',
    body: 'Delete this session and all its data (transcript, scores, report)? This cannot be undone.',
    confirmLabel: 'Delete session',
  },
  transcript: {
    title: 'Delete this transcript?',
    body: 'Delete the transcript for this session?',
    confirmLabel: 'Delete transcript',
  },
  recording: {
    title: 'Delete this recording?',
    body: 'Delete the recording for this session?',
    confirmLabel: 'Delete recording',
  },
};

const STATUS_STYLES: Record<string, string> = {
  completed: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
  active: 'bg-sky-500/15 text-sky-300 border-sky-500/30',
  paused: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
  ready: 'bg-indigo-500/15 text-indigo-300 border-indigo-500/30',
  planning: 'bg-slate-500/15 text-slate-300 border-slate-500/30',
  created: 'bg-slate-500/15 text-slate-300 border-slate-500/30',
  cancelled: 'bg-rose-500/15 text-rose-300 border-rose-500/30',
};

export default function SessionsPage() {
  const userId = useInterviewStore((state) => state.userId);
  const [sessions, setSessions] = useState<SessionOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!userId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await getUserSessions(userId);
      setSessions(
        [...data].sort(
          (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
        ),
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Could not load sessions.');
    }
    setLoading(false);
  }, [userId]);

  useEffect(() => {
    void load();
  }, [load]);

  const [pendingDelete, setPendingDelete] = useState<{
    kind: DeleteKind;
    session: SessionOut;
  } | null>(null);

  const confirmPendingDelete = async () => {
    if (!pendingDelete) return;
    const { kind, session } = pendingDelete;
    setPendingDelete(null);
    try {
      if (kind === 'session') {
        await deleteSession(session.id);
        setNotice('Session deleted.');
        void load();
      } else if (kind === 'transcript') {
        await deleteTranscript(session.id);
        setNotice('Transcript deleted.');
      } else {
        await deleteRecording(session.id);
        setNotice('Recording deleted.');
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Delete failed.');
    }
  };

  if (!userId) {
    return (
      <div className="mx-auto max-w-lg px-6 py-20 text-center">
        <h1 className="text-2xl font-bold text-slate-100">No interviews yet</h1>
        <p className="mt-3 text-sm text-slate-400">
          Once you run your first mock interview, your history will show up here.
        </p>
        <Link to="/" className="btn btn-primary mt-6">
          Set up an interview
        </Link>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl px-6 py-10">
      <header className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-slate-100">Your sessions</h1>
          <p className="mt-1 text-sm text-slate-400">
            Interview history, reports and privacy controls.
          </p>
        </div>
        <div className="flex gap-2">
          <Link to="/progress" className="btn btn-ghost">
            View progress
          </Link>
          <Link to="/" className="btn btn-primary">
            New interview
          </Link>
        </div>
      </header>

      {notice && (
        <div className="mb-4 rounded-xl border border-emerald-500/30 bg-emerald-950/30 px-4 py-2.5 text-sm text-emerald-200">
          {notice}
        </div>
      )}
      {error && (
        <div className="mb-4 rounded-xl border border-rose-500/30 bg-rose-950/30 px-4 py-2.5 text-sm text-rose-200" role="alert">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex items-center gap-3 py-16 text-slate-400">
          <span className="spinner" />
          Loading sessions…
        </div>
      ) : sessions.length === 0 ? (
        <p className="py-16 text-center text-sm text-slate-400">No sessions yet.</p>
      ) : (
        <ul className="space-y-3">
          {sessions.map((session) => (
            <li key={session.id} className="card p-5">
              <div className="flex flex-wrap items-center gap-3">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold text-slate-100">
                    {session.role}
                    <span className="ml-2 font-normal text-slate-400">
                      {modeLabel(session.mode)} · {session.difficulty} · {session.duration_minutes} min
                    </span>
                  </p>
                  <p className="mt-0.5 text-xs text-slate-400">
                    {new Date(session.created_at).toLocaleString()} · {session.interviewer_style}
                  </p>
                </div>
                <span
                  className={`chip capitalize ${STATUS_STYLES[session.status] ?? STATUS_STYLES.created}`}
                >
                  {session.status}
                </span>
                {session.overall_score !== null && (
                  <span className="rounded-full bg-indigo-500/15 px-3 py-1 text-sm font-bold text-indigo-300">
                    {Math.round(session.overall_score)}/100
                  </span>
                )}
              </div>
              <div className="mt-3 flex flex-wrap gap-2 border-t border-slate-800 pt-3">
                {['ready', 'active', 'paused', 'created'].includes(session.status) && (
                  <Link to={`/interview/${session.id}`} className="btn btn-primary btn-sm">
                    {session.status === 'ready' || session.status === 'created' ? 'Start' : 'Resume'}
                  </Link>
                )}
                {session.status === 'completed' && (
                  <Link to={`/report/${session.id}`} className="btn btn-ghost btn-sm">
                    View report
                  </Link>
                )}
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => setPendingDelete({ kind: 'transcript', session })}
                >
                  Delete transcript
                </button>
                {session.record_session && (
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={() => setPendingDelete({ kind: 'recording', session })}
                  >
                    Delete recording
                  </button>
                )}
                <button
                  type="button"
                  className="btn btn-danger-outline btn-sm"
                  onClick={() => setPendingDelete({ kind: 'session', session })}
                >
                  Delete session
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      <ConfirmDialog
        open={pendingDelete !== null}
        title={pendingDelete ? DELETE_PROMPTS[pendingDelete.kind].title : ''}
        body={pendingDelete ? DELETE_PROMPTS[pendingDelete.kind].body : ''}
        confirmLabel={pendingDelete ? DELETE_PROMPTS[pendingDelete.kind].confirmLabel : ''}
        danger
        onConfirm={() => void confirmPendingDelete()}
        onCancel={() => setPendingDelete(null)}
      />
    </div>
  );
}
