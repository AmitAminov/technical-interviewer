/**
 * Interview setup form (DESIGN.md §10 SetupPage): role / mode / difficulty /
 * duration / language / hint policy / interviewer style plus privacy and
 * context toggles. Validates required fields and mode-appropriate duration
 * before handing a SessionCreate payload (minus user_id) to the parent.
 */
import { useRef, useState } from 'react';

import {
  DIFFICULTIES,
  HINT_POLICIES,
  INTERVIEWER_STYLES,
  LANGUAGES,
  MODES,
  MODE_DURATION_RANGES,
  MODE_LABELS,
  ROLES,
  TRACK_TOPICS,
  type Difficulty,
  type HintPolicy,
  type InterviewerStyle,
  type Mode,
  type Role,
  type SessionCreate,
} from '../lib/types';
import Avatar from './Avatar';

export type SetupPayload = { name: string; session: Omit<SessionCreate, 'user_id'> };

export interface SetupFormProps {
  initialName?: string;
  prefill?: Partial<SessionCreate> | null;
  submitting?: boolean;
  onSubmit: (payload: SetupPayload) => void;
}

interface FormErrors {
  name?: string;
  role?: string;
  mode?: string;
  difficulty?: string;
  resume?: string;
}

const HINT_POLICY_LABELS: Record<HintPolicy, string> = {
  none: 'No hints',
  on_request: 'On request',
  adaptive: 'Adaptive',
};

const MODE_BLURBS: Record<Mode, string> = {
  'Quick Practice': '10–20 min warm-up',
  Standard: '45–60 min full loop',
  'Deep Research': '60–90 min deep dive',
};

function defaultDuration(mode: Mode): number {
  const [min, max] = MODE_DURATION_RANGES[mode];
  return Math.round((min + max) / 2);
}

export default function SetupForm({ initialName, prefill, submitting, onSubmit }: SetupFormProps) {
  const [name, setName] = useState(initialName ?? '');
  const [role, setRole] = useState<Role | ''>((prefill?.role as Role | undefined) ?? '');
  const [mode, setMode] = useState<Mode | ''>((prefill?.mode as Mode | undefined) ?? '');
  const [difficulty, setDifficulty] = useState<Difficulty | ''>(
    (prefill?.difficulty as Difficulty | undefined) ?? '',
  );
  const [duration, setDuration] = useState<number>(
    prefill?.duration_minutes ?? (prefill?.mode ? defaultDuration(prefill.mode as Mode) : 50),
  );
  const [language, setLanguage] = useState('en');
  const [hintPolicy, setHintPolicy] = useState<HintPolicy>(prefill?.hint_policy ?? 'on_request');
  const [style, setStyle] = useState<InterviewerStyle>(prefill?.interviewer_style ?? 'Friendly');
  const [focusTopics, setFocusTopics] = useState<string[]>(prefill?.focus_topics ?? []);

  const [useResume, setUseResume] = useState(false);
  const [resumeText, setResumeText] = useState<string | null>(null);
  const [resumeFileName, setResumeFileName] = useState('');
  const [resumeIsPdf, setResumeIsPdf] = useState(false);
  const [useJd, setUseJd] = useState(false);
  const [jdText, setJdText] = useState('');
  const [useWiki, setUseWiki] = useState(true);
  const [allowInternet, setAllowInternet] = useState(false);
  const [recordSession, setRecordSession] = useState(false);
  const [disableCloudAi, setDisableCloudAi] = useState(false);

  const [errors, setErrors] = useState<FormErrors>({});
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const topics = role ? TRACK_TOPICS[role] : [];

  const pickMode = (next: Mode) => {
    setMode(next);
    // Duration is no longer user-editable — default it to the middle of the
    // chosen mode's range.
    setDuration(defaultDuration(next));
  };

  const toggleTopic = (topic: string) => {
    setFocusTopics((current) =>
      current.includes(topic) ? current.filter((t) => t !== topic) : [...current, topic],
    );
  };

  const handleResumeFile = (file: File | null) => {
    setErrors((e) => ({ ...e, resume: undefined }));
    if (!file) {
      setResumeText(null);
      setResumeFileName('');
      setResumeIsPdf(false);
      return;
    }
    const lower = file.name.toLowerCase();
    const reader = new FileReader();
    if (lower.endsWith('.txt')) {
      reader.onload = () => {
        setResumeText(typeof reader.result === 'string' ? reader.result : '');
        setResumeFileName(file.name);
        setResumeIsPdf(false);
      };
      reader.readAsText(file);
    } else if (lower.endsWith('.pdf')) {
      // PDFs are sent as a base64 data-URL string in resume_text; the backend
      // parsing module detects the "data:application/pdf;base64," prefix and
      // extracts the text server-side with pypdf.
      reader.onload = () => {
        setResumeText(typeof reader.result === 'string' ? reader.result : '');
        setResumeFileName(file.name);
        setResumeIsPdf(true);
      };
      reader.readAsDataURL(file);
    } else {
      setErrors((e) => ({ ...e, resume: 'Only .pdf or .txt files are supported.' }));
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const validate = (): FormErrors => {
    const next: FormErrors = {};
    if (!name.trim()) next.name = 'Enter your name.';
    if (!role) next.role = 'Select a role.';
    if (!mode) next.mode = 'Select an interview mode.';
    if (!difficulty) next.difficulty = 'Select a difficulty level.';
    if (useResume && !resumeText) next.resume = 'Attach a .pdf or .txt resume, or turn the toggle off.';
    return next;
  };

  const handleSubmit = () => {
    const next = validate();
    setErrors(next);
    if (Object.keys(next).length > 0 || !role || !mode || !difficulty) return;
    onSubmit({
      name: name.trim(),
      session: {
        role,
        mode,
        difficulty,
        duration_minutes: duration,
        language,
        hint_policy: hintPolicy,
        interviewer_style: style,
        use_resume: useResume && Boolean(resumeText),
        use_job_description: useJd && Boolean(jdText.trim()),
        use_wiki: useWiki,
        allow_internet: allowInternet,
        record_session: recordSession,
        disable_cloud_ai: disableCloudAi,
        resume_text: useResume ? resumeText : null,
        job_description: useJd && jdText.trim() ? jdText : null,
        focus_topics: focusTopics,
      },
    });
  };

  const fieldError = (message?: string) =>
    message ? (
      <p className="mt-1 text-xs font-medium text-rose-400" role="alert">
        {message}
      </p>
    ) : null;

  return (
    <form
      className="space-y-8"
      onSubmit={(event) => {
        event.preventDefault();
        handleSubmit();
      }}
      noValidate
    >
      {/* name */}
      <div>
        <label className="label" htmlFor="candidate-name">
          Your name
        </label>
        <input
          id="candidate-name"
          className="input max-w-sm"
          placeholder="e.g. Amit Aminov"
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
        {fieldError(errors.name)}
      </div>

      {/* role */}
      <div>
        <span className="label">Target role</span>
        <div className="grid gap-3 sm:grid-cols-3">
          {ROLES.map((r) => (
            <button
              key={r}
              type="button"
              aria-pressed={role === r}
              onClick={() => setRole(r)}
              className={`selectable rounded-xl border px-4 py-3 text-left text-sm transition-colors ${
                role === r
                  ? 'border-indigo-400 bg-indigo-500/15 text-indigo-100 shadow-lg shadow-indigo-950/30'
                  : 'border-slate-700 bg-slate-900/60 text-slate-300 hover:border-slate-500'
              }`}
            >
              <span className="block font-semibold">{r}</span>
              <span className="mt-1 block text-xs text-slate-400">
                {TRACK_TOPICS[r].slice(0, 3).join(' · ')}…
              </span>
            </button>
          ))}
        </div>
        {fieldError(errors.role)}
      </div>

      {/* mode */}
      <div>
        <span className="label">Interview mode</span>
        <div className="grid gap-3 sm:grid-cols-3">
          {MODES.map((m) => (
            <button
              key={m}
              type="button"
              aria-pressed={mode === m}
              onClick={() => pickMode(m)}
              className={`selectable rounded-xl border px-4 py-3 text-left text-sm transition-colors ${
                mode === m
                  ? 'border-indigo-400 bg-indigo-500/15 text-indigo-100 shadow-lg shadow-indigo-950/30'
                  : 'border-slate-700 bg-slate-900/60 text-slate-300 hover:border-slate-500'
              }`}
            >
              <span className="block font-semibold">{MODE_LABELS[m]}</span>
              <span className="mt-1 block text-xs text-slate-400">{MODE_BLURBS[m]}</span>
            </button>
          ))}
        </div>
        {fieldError(errors.mode)}
      </div>

      {/* difficulty */}
      <div>
        <span className="label">Difficulty</span>
        <div className="flex flex-wrap gap-2">
          {DIFFICULTIES.map((d) => (
            <button
              key={d}
              type="button"
              aria-pressed={difficulty === d}
              onClick={() => setDifficulty(d)}
              className={`chip selectable ${
                difficulty === d
                  ? 'border-indigo-400 bg-indigo-500/20 text-indigo-100'
                  : 'border-slate-700 bg-slate-900/60 text-slate-300 hover:border-slate-500'
              }`}
            >
              {d}
            </button>
          ))}
        </div>
        {fieldError(errors.difficulty)}
      </div>

      {/* language (duration is set automatically from the chosen mode) */}
      <div>
        <label className="label" htmlFor="language-select">
          Language
        </label>
        <select
          id="language-select"
          className="input max-w-[12rem]"
          value={language}
          onChange={(event) => setLanguage(event.target.value)}
        >
          {LANGUAGES.map((l) => (
            <option key={l.code} value={l.code}>
              {l.label}
            </option>
          ))}
        </select>
        <p className="mt-1 text-xs text-slate-400">
          Hebrew runs the interview in עברית (right-to-left) and uses your browser's
          Hebrew voice for speech.
        </p>
      </div>

      {/* hint policy */}
      <div>
        <span className="label">Hint policy</span>
        <div className="inline-flex overflow-hidden rounded-lg border border-slate-700">
          {HINT_POLICIES.map((p) => (
            <button
              key={p}
              type="button"
              aria-pressed={hintPolicy === p}
              onClick={() => setHintPolicy(p)}
              className={`selectable px-4 py-2 text-sm transition-colors ${
                hintPolicy === p
                  ? 'bg-indigo-500 text-white'
                  : 'bg-slate-900/60 text-slate-300 hover:bg-slate-800'
              }`}
            >
              {HINT_POLICY_LABELS[p]}
            </button>
          ))}
        </div>
        <p className="mt-1 text-xs text-slate-400">Each hint slightly reduces the answer score.</p>
      </div>

      {/* interviewer style */}
      <div>
        <span className="label">Interviewer style</span>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          {INTERVIEWER_STYLES.map((s) => (
            <button
              key={s}
              type="button"
              aria-pressed={style === s}
              onClick={() => setStyle(s)}
              className={`selectable flex flex-col items-center gap-2 rounded-xl border p-3 transition-colors ${
                style === s
                  ? 'border-indigo-400 bg-indigo-500/15 shadow-lg shadow-indigo-950/30'
                  : 'border-slate-700 bg-slate-900/60 hover:border-slate-500'
              }`}
            >
              <Avatar style={s} speaking={false} name={s} size={72} />
              <span className="text-center text-xs font-medium text-slate-200">{s}</span>
            </button>
          ))}
        </div>
      </div>

      {/* focus topics */}
      {role && (
        <div>
          <span className="label">Focus topics (optional)</span>
          <div className="flex flex-wrap gap-2">
            {topics.map((topic) => (
              <button
                key={topic}
                type="button"
                aria-pressed={focusTopics.includes(topic)}
                onClick={() => toggleTopic(topic)}
                className={`chip selectable ${
                  focusTopics.includes(topic)
                    ? 'border-emerald-400 bg-emerald-500/20 text-emerald-100'
                    : 'border-slate-700 bg-slate-900/60 text-slate-400 hover:border-slate-500'
                }`}
              >
                {topic}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* context & privacy toggles */}
      <div className="card space-y-4 p-5">
        <h3 className="text-sm font-semibold text-slate-200">Context &amp; privacy</h3>

        <label className="flex items-start gap-3 text-sm text-slate-300">
          <input
            type="checkbox"
            className="mt-0.5 h-5 w-5 accent-indigo-500"
            checked={useResume}
            onChange={(event) => setUseResume(event.target.checked)}
          />
          <span>
            <span className="font-medium">Use my resume</span>
            <span className="block text-xs text-slate-400">
              Tailors questions to your experience. Stored encrypted, deletable any time.
            </span>
          </span>
        </label>
        {useResume && (
          <div className="ml-7 space-y-1">
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.txt"
              aria-label="Resume file"
              className="block text-xs text-slate-400 file:mr-3 file:rounded-lg file:border-0 file:bg-slate-800 file:px-3 file:py-1.5 file:text-xs file:text-slate-200"
              onChange={(event) => handleResumeFile(event.target.files?.[0] ?? null)}
            />
            {resumeFileName && (
              <p className="text-xs text-emerald-300">
                Attached: {resumeFileName}
                {resumeIsPdf && <span className="text-slate-400"> — PDF parsed server-side</span>}
              </p>
            )}
            {fieldError(errors.resume)}
          </div>
        )}

        <label className="flex items-start gap-3 text-sm text-slate-300">
          <input
            type="checkbox"
            className="mt-0.5 h-5 w-5 accent-indigo-500"
            checked={useJd}
            onChange={(event) => setUseJd(event.target.checked)}
          />
          <span>
            <span className="font-medium">Use a job description</span>
            <span className="block text-xs text-slate-400">Focuses the plan on the posting's skills.</span>
          </span>
        </label>
        {useJd && (
          <textarea
            className="input ml-7 min-h-[90px] w-auto flex-1"
            style={{ width: 'calc(100% - 1.75rem)' }}
            placeholder="Paste the job description here…"
            aria-label="Job description"
            value={jdText}
            onChange={(event) => setJdText(event.target.value)}
          />
        )}

        <label className="flex items-start gap-3 text-sm text-slate-300">
          <input
            type="checkbox"
            className="mt-0.5 h-5 w-5 accent-indigo-500"
            checked={useWiki}
            onChange={(event) => setUseWiki(event.target.checked)}
          />
          <span>
            <span className="font-medium">Use local knowledge wiki</span>
            <span className="block text-xs text-slate-400">Grounds questions in your local notes (RAG).</span>
          </span>
        </label>

        <label className="flex items-start gap-3 text-sm text-slate-300">
          <input
            type="checkbox"
            className="mt-0.5 h-5 w-5 accent-indigo-500"
            checked={allowInternet}
            onChange={(event) => setAllowInternet(event.target.checked)}
          />
          <span>
            <span className="font-medium">Allow internet research</span>
            <span className="block text-xs text-slate-400">
              Lets the research agent fetch fresh questions; all sources are logged.
            </span>
          </span>
        </label>

        <label className="flex items-start gap-3 text-sm text-slate-300">
          <input
            type="checkbox"
            className="mt-0.5 h-5 w-5 accent-indigo-500"
            checked={recordSession}
            onChange={(event) => setRecordSession(event.target.checked)}
          />
          <span>
            <span className="font-medium">Record session</span>
            <span className="block text-xs text-slate-400">Keeps the transcript for later review.</span>
          </span>
        </label>

        <label className="flex items-start gap-3 text-sm text-slate-300">
          <input
            type="checkbox"
            className="mt-0.5 h-5 w-5 accent-indigo-500"
            checked={disableCloudAi}
            onChange={(event) => setDisableCloudAi(event.target.checked)}
          />
          <span>
            <span className="font-medium">Disable cloud AI</span>
            <span className="block text-xs text-slate-400">Runs entirely on local models/fallbacks.</span>
          </span>
        </label>
      </div>

      <div className="flex items-center gap-4">
        <button type="submit" className="btn btn-primary px-8 py-3 text-base" disabled={submitting}>
          {submitting ? 'Preparing your interview…' : 'Start interview'}
        </button>
        {submitting && (
          <span className="text-sm text-slate-400">
            Building your interview plan — this can take a few seconds.
          </span>
        )}
      </div>
    </form>
  );
}
