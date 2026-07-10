/**
 * Shared domain types — mirrors backend/app/schemas.py exactly (DESIGN.md §2).
 * The string enums here are the single source of truth on the client; do not
 * introduce alternative spellings anywhere in the UI.
 */

// ---------------------------------------------------------------- enums
export type Role = 'Data Scientist' | 'Algorithm Researcher' | 'AI Engineer';
export type Mode = 'Quick Practice' | 'Standard' | 'Deep Research';
export type Difficulty =
  | 'Junior'
  | 'Mid-level'
  | 'Senior'
  | 'Research-level'
  | 'Staff/Lead-level';
export type HintPolicy = 'none' | 'on_request' | 'adaptive';
export type InterviewerStyle =
  | 'Friendly'
  | 'Strict'
  | 'Research professor'
  | 'Startup CTO'
  | 'Big-tech interviewer';
export type QuestionSource = 'local_wiki' | 'internet' | 'generated' | 'seed';
export type SessionStatus =
  | 'created'
  | 'planning'
  | 'ready'
  | 'active'
  | 'paused'
  | 'completed'
  | 'cancelled';
export type Speaker = 'interviewer' | 'candidate' | 'system';

export const ROLES: Role[] = ['Data Scientist', 'Algorithm Researcher', 'AI Engineer'];
export const MODES: Mode[] = ['Quick Practice', 'Standard', 'Deep Research'];
export const DIFFICULTIES: Difficulty[] = [
  'Junior',
  'Mid-level',
  'Senior',
  'Research-level',
  'Staff/Lead-level',
];
export const HINT_POLICIES: HintPolicy[] = ['none', 'on_request', 'adaptive'];
export const INTERVIEWER_STYLES: InterviewerStyle[] = [
  'Friendly',
  'Strict',
  'Research professor',
  'Startup CTO',
  'Big-tech interviewer',
];

export const MODE_DURATION_RANGES: Record<Mode, [number, number]> = {
  'Quick Practice': [10, 20],
  Standard: [45, 60],
  'Deep Research': [60, 90],
};

/**
 * Human-facing labels for the interview modes. The wire/DB value stays the
 * `Mode` enum (the backend keys planning logic on it); only the label the
 * candidate sees changes — "Deep Research" is presented as "Deep Dive".
 */
export const MODE_LABELS: Record<Mode, string> = {
  'Quick Practice': 'Quick Practice',
  Standard: 'Standard',
  'Deep Research': 'Deep Dive',
};

/** Show a mode's label, tolerating an unknown/legacy value from the server. */
export function modeLabel(mode: string | undefined | null): string {
  if (!mode) return '';
  return MODE_LABELS[mode as Mode] ?? mode;
}

/**
 * Duration range used before an interview mode is chosen: the union of all
 * mode ranges, so the slider is always usable and merely narrows once a mode
 * is picked (see MODE_DURATION_RANGES).
 */
export const DURATION_FULL_RANGE: [number, number] = [10, 90];

export interface LanguageOption {
  code: string;
  label: string;
  /** Right-to-left script — drives `dir="rtl"` in the interview room. */
  rtl: boolean;
  /** BCP-47 tag for Web Speech recognition/synthesis. */
  bcp47: string;
}

export const LANGUAGES: LanguageOption[] = [
  { code: 'en', label: 'English', rtl: false, bcp47: 'en-US' },
  { code: 'he', label: 'עברית · Hebrew', rtl: true, bcp47: 'he-IL' },
];

/** Resolve a stored language code to its option (falls back to English). */
export function languageOption(code: string | undefined | null): LanguageOption {
  return LANGUAGES.find((l) => l.code === code) ?? LANGUAGES[0];
}

export const TRACK_TOPICS: Record<Role, string[]> = {
  'Data Scientist': [
    'Python',
    'SQL',
    'Statistics',
    'Probability',
    'A/B testing',
    'Experiment design',
    'Feature engineering',
    'Supervised learning',
    'Unsupervised learning',
    'Model evaluation',
    'Business case reasoning',
    'Data cleaning',
    'Communication of insights',
  ],
  'Algorithm Researcher': [
    'Algorithms',
    'Data structures',
    'Complexity analysis',
    'Probability',
    'Optimization',
    'Graph algorithms',
    'Dynamic programming',
    'Mathematical proofs',
    'Research paper understanding',
    'Experimental design',
    'Benchmarking',
  ],
  'AI Engineer': [
    'Deep learning',
    'Transformers',
    'LLMs',
    'RAG',
    'Embeddings',
    'Fine-tuning',
    'Evaluation',
    'Agents',
    'MLOps',
    'Model serving',
    'Latency optimization',
    'Distributed training',
    'GPU memory',
    'Safety and monitoring',
  ],
};

// ---------------------------------------------------------------- users
export interface UserCreate {
  name: string;
  target_roles: Role[];
}

export interface UserOut {
  id: string;
  name: string;
  target_roles: string[];
  created_at: string;
}

// ---------------------------------------------------------------- sessions
export interface SessionCreate {
  user_id: string;
  role: Role;
  mode: Mode;
  difficulty: Difficulty;
  duration_minutes: number;
  language: string;
  hint_policy: HintPolicy;
  interviewer_style: InterviewerStyle;
  use_resume: boolean;
  use_job_description: boolean;
  use_wiki: boolean;
  allow_internet: boolean;
  record_session: boolean;
  disable_cloud_ai: boolean;
  resume_text: string | null;
  job_description: string | null;
  focus_topics: string[];
}

export interface InterviewPlan {
  role: string;
  duration_minutes: number;
  sections: string[];
  difficulty: string;
  section_questions: Record<string, string[]>;
  focus_topics: string[];
  rubric_notes: Record<string, string[]>;
}

export interface SessionOut {
  id: string;
  user_id: string;
  role: string;
  mode: string;
  difficulty: string;
  duration_minutes: number;
  language: string;
  hint_policy: string;
  interviewer_style: string;
  use_resume: boolean;
  use_job_description: boolean;
  use_wiki: boolean;
  allow_internet: boolean;
  record_session: boolean;
  disable_cloud_ai: boolean;
  status: SessionStatus | string;
  overall_score: number | null;
  plan: InterviewPlan | null;
  created_at: string;
  completed_at: string | null;
}

// ------------------------------------------------------ questions & scoring
export interface QuestionBankItem {
  id: string;
  role: Role;
  topic: string;
  difficulty: Difficulty;
  question_text: string;
  expected_points: string[];
  followups: string[];
  is_behavioral: boolean;
  source: QuestionSource;
}

export interface MetricScores {
  correctness: number;
  depth: number;
  clarity: number;
  structure: number;
  practicality: number;
  mathematical_rigor: number;
  tradeoff_awareness: number;
  communication: number;
}

export const METRIC_LABELS: Array<[keyof MetricScores, string]> = [
  ['correctness', 'Correctness'],
  ['depth', 'Depth'],
  ['clarity', 'Clarity'],
  ['structure', 'Structure'],
  ['practicality', 'Practicality'],
  ['mathematical_rigor', 'Mathematical rigor'],
  ['tradeoff_awareness', 'Trade-off awareness'],
  ['communication', 'Communication'],
];

// ---------------------------------------------------------- transcript & rag
export interface TranscriptEntryOut {
  id: string;
  session_id: string;
  ts: string;
  speaker: Speaker;
  text: string;
}

export interface TranscriptOut {
  session_id: string;
  entries: TranscriptEntryOut[];
}

export interface RagResult {
  text: string;
  source: string;
  score: number;
}

export interface SourceCitationOut {
  id: string;
  session_id: string | null;
  url: string;
  title: string;
  quality: 'high' | 'medium' | 'rejected';
  fetched_at: string;
  notes: string;
}

// ---------------------------------------------------------------- report
export interface AnswerHighlight {
  question: string;
  score: number;
  why: string;
}

export interface NextInterviewRec {
  role: string;
  mode: string;
  difficulty: string;
  focus_topics: string[];
}

export interface TimePerQuestion {
  question_id: string;
  question_text: string;
  seconds: number;
}

export interface ReportOut {
  session_id: string;
  overall_score: number;
  role_readiness: number;
  topic_scores: Record<string, number>;
  best_answers: AnswerHighlight[];
  weakest_answers: AnswerHighlight[];
  missing_concepts: string[];
  communication_feedback: string;
  technical_feedback: string;
  suggested_study_plan: string[];
  recommended_next_interview: NextInterviewRec | null;
  questions_asked: string[];
  transcript_summary: string;
  hints_used_total: number;
  time_per_question: TimePerQuestion[];
  created_at: string | null;
}

// ---------------------------------------------------------------- progress
export interface ProgressSessionSummary {
  id: string;
  created_at: string;
  role: string;
  mode: string;
  difficulty: string;
  overall_score: number | null; // 0–100
  role_readiness: number | null; // 0–100
}

export interface ReadinessPoint {
  session_id: string;
  created_at: string;
  score: number; // 0–100
}

export interface TopicTrendPoint {
  session_id: string;
  created_at: string;
  score: number; // 0–5
}

export type CurriculumPriority = 1 | 2 | 3;

export interface CurriculumItem {
  title: string;
  reason: string;
  wiki_refs: string[];
  priority: CurriculumPriority;
  source_sessions: string[];
}

export interface ProgressOut {
  user_id: string;
  /** Chronological (oldest first), like readiness_trend / topic_trends. */
  sessions: ProgressSessionSummary[];
  readiness_trend: ReadinessPoint[];
  topic_trends: Record<string, TopicTrendPoint[]>;
  current_weak_topics: string[];
  current_strong_topics: string[];
  curriculum: CurriculumItem[];
}

export interface HealthOut {
  status: string;
  version: string;
  llm_provider: string;
  wiki_index_loaded: boolean;
}

// ------------------------------------------------------- WS protocol (§4)
export type InputMode = 'voice' | 'text';

export type ClientMessage =
  | { type: 'start' }
  | { type: 'answer'; text: string; duration_seconds: number; input_mode: InputMode }
  | { type: 'partial_transcript'; text: string }
  | { type: 'hint_request' }
  | { type: 'silence'; seconds: number }
  | { type: 'interrupt' }
  | { type: 'barge_in'; text: string }
  | { type: 'pause' }
  | { type: 'resume' }
  | { type: 'skip' }
  | { type: 'end' }
  | { type: 'more_time_response'; wants_more_time: boolean };

export type InterviewerKind =
  | 'greeting'
  | 'question'
  | 'followup'
  | 'checkin'
  | 'ack'
  | 'reply'
  | 'closing';

export interface InterviewerMessage {
  type: 'interviewer';
  kind: InterviewerKind;
  text: string;
  section: string;
  question_id: string | null;
  question_index: number;
  total_questions: number;
}

export interface HintMessage {
  type: 'hint';
  level: number;
  text: string;
  question_id: string;
  hints_used: number;
}

export interface ScoreMessage {
  type: 'score';
  question_id: string;
  scores: MetricScores;
  overall: number;
  feedback: string;
}

export interface SectionChangeMessage {
  type: 'section_change';
  section: string;
  section_index: number;
  total_sections: number;
}

export interface StateMessage {
  type: 'state';
  status: 'active' | 'paused' | 'completed';
  elapsed_seconds: number;
  remaining_seconds: number;
}

export interface ReportReadyMessage {
  type: 'report_ready';
  session_id: string;
}

export interface WsErrorMessage {
  type: 'error';
  message: string;
}

export type ServerMessage =
  | InterviewerMessage
  | HintMessage
  | ScoreMessage
  | SectionChangeMessage
  | StateMessage
  | ReportReadyMessage
  | WsErrorMessage;

export type WsStatus = 'idle' | 'connecting' | 'open' | 'reconnecting' | 'closed' | 'failed';
