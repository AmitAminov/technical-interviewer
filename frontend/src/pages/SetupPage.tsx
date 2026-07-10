/**
 * Setup page (DESIGN.md §10): configure the interview, create the user and
 * session (POST /api/users + /api/sessions — synchronous planning), then
 * navigate into the interview room.
 */
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import SetupForm, { type SetupPayload } from '../components/SetupForm';
import { ApiError, createSession, createUser } from '../lib/api';
import { useInterviewStore } from '../lib/store';

export default function SetupPage() {
  const navigate = useNavigate();
  const userName = useInterviewStore((state) => state.userName);
  const prefill = useInterviewStore((state) => state.prefill);
  const setUser = useInterviewStore((state) => state.setUser);
  const setPrefill = useInterviewStore((state) => state.setPrefill);
  const [submitting, setSubmitting] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);

  const handleSubmit = async (payload: SetupPayload) => {
    setSubmitting(true);
    setApiError(null);
    try {
      const user = await createUser({
        name: payload.name,
        target_roles: [payload.session.role],
      });
      setUser(user.id, user.name);
      const session = await createSession({ ...payload.session, user_id: user.id });
      setPrefill(null);
      navigate(`/interview/${session.id}`);
    } catch (err) {
      const message =
        err instanceof ApiError
          ? `Could not create the session: ${err.detail}`
          : 'Could not reach the interview server. Is the backend running on port 8011?';
      setApiError(message);
      setSubmitting(false);
    }
  };

  return (
    <div className="mx-auto max-w-4xl px-6 py-10">
      <header className="mb-8">
        <h1 className="text-3xl font-bold tracking-tight text-slate-100">
          Set up your mock interview
        </h1>
        <p className="mt-2 max-w-prose text-sm leading-relaxed text-slate-400">
          A realistic, voice-driven technical interview with an AI interviewer. Pick a role, a
          format and a persona — you will get structured scoring and a full report at the end.
        </p>
      </header>

      {apiError && (
        <div
          className="mb-6 rounded-xl border border-rose-500/40 bg-rose-950/40 px-4 py-3 text-sm text-rose-200"
          role="alert"
        >
          {apiError}
        </div>
      )}

      <SetupForm
        initialName={userName}
        prefill={prefill}
        submitting={submitting}
        onSubmit={handleSubmit}
      />
    </div>
  );
}
