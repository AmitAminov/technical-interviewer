/**
 * Typed REST client for the FastAPI backend (DESIGN.md §3).
 * All paths are relative — the Vite dev server proxies /api to 127.0.0.1:8011
 * and in production the backend serves the built frontend itself.
 */
import type {
  HealthOut,
  ProgressOut,
  QuestionBankItem,
  RagResult,
  ReportOut,
  Role,
  SessionCreate,
  SessionOut,
  SourceCitationOut,
  TranscriptOut,
  UserOut,
} from './types';

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(detail);
    this.name = 'ApiError';
  }
}

const JSON_HEADERS = { 'Content-Type': 'application/json' };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch (err) {
    throw new ApiError(0, err instanceof Error ? err.message : 'Network error');
  }
  if (!res.ok) {
    let detail = res.statusText || `HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (body && body.detail !== undefined) {
        detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
      }
    } catch {
      /* non-JSON error body — keep statusText */
    }
    throw new ApiError(res.status, detail);
  }
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

// ---------------------------------------------------------------- endpoints
export const getHealth = (): Promise<HealthOut> => request('/api/health');

export const createUser = (payload: { name: string; target_roles: Role[] }): Promise<UserOut> =>
  request('/api/users', { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify(payload) });

export const getUser = (userId: string): Promise<UserOut> =>
  request(`/api/users/${encodeURIComponent(userId)}`);

export const getUserSessions = (userId: string): Promise<SessionOut[]> =>
  request(`/api/users/${encodeURIComponent(userId)}/sessions`);

export const getProgress = (userId: string): Promise<ProgressOut> =>
  request(`/api/users/${encodeURIComponent(userId)}/progress`);

export const createSession = (payload: SessionCreate): Promise<SessionOut> =>
  request('/api/sessions', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });

export const getSession = (sessionId: string): Promise<SessionOut> =>
  request(`/api/sessions/${encodeURIComponent(sessionId)}`);

export const getTranscript = (sessionId: string): Promise<TranscriptOut> =>
  request(`/api/sessions/${encodeURIComponent(sessionId)}/transcript`);

export const getReport = (sessionId: string): Promise<ReportOut> =>
  request(`/api/sessions/${encodeURIComponent(sessionId)}/report`);

export const regenerateReport = (sessionId: string): Promise<ReportOut> =>
  request(`/api/sessions/${encodeURIComponent(sessionId)}/report/regenerate`, { method: 'POST' });

export const getSources = (sessionId: string): Promise<SourceCitationOut[]> =>
  request(`/api/sessions/${encodeURIComponent(sessionId)}/sources`);

export const deleteSession = (sessionId: string): Promise<void> =>
  request(`/api/sessions/${encodeURIComponent(sessionId)}`, { method: 'DELETE' });

export const deleteTranscript = (sessionId: string): Promise<void> =>
  request(`/api/sessions/${encodeURIComponent(sessionId)}/transcript`, { method: 'DELETE' });

export const deleteRecording = (sessionId: string): Promise<void> =>
  request(`/api/sessions/${encodeURIComponent(sessionId)}/recording`, { method: 'DELETE' });

export const getQuestionBank = (filters: {
  role?: string;
  difficulty?: string;
  topic?: string;
}): Promise<QuestionBankItem[]> => {
  const params = new URLSearchParams();
  if (filters.role) params.set('role', filters.role);
  if (filters.difficulty) params.set('difficulty', filters.difficulty);
  if (filters.topic) params.set('topic', filters.topic);
  const qs = params.toString();
  return request(`/api/question-bank${qs ? `?${qs}` : ''}`);
};

export const ragSearch = (query: string, k = 5): Promise<{ results: RagResult[] }> =>
  request('/api/rag/search', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify({ query, k }),
  });
