/**
 * Interviewer character pool (photorealistic faces generated with Imagen 4,
 * bundled under public/interviewers/). A character is sampled once per session
 * at interview initialization, matched to the interview's role and to the
 * gender of the chosen interviewer style's voice (so face and voice agree).
 * The choice is persisted per session id in localStorage so it stays stable
 * across reloads.
 */
import type { InterviewerStyle, Role } from './types';
import { STYLE_VOICES } from './voice';

/** Normalized (0..1 of image) box for a face feature. */
export interface FeatureBox {
  cx: number;
  cy: number;
  w: number;
  h: number;
}

export interface Character {
  id: string;
  role: string;
  gender: 'male' | 'female';
  file: string;
  /** Mouth centre/size, from offline MediaPipe FaceMesh — positions the
   *  viseme-driven lip animation. */
  mouth?: FeatureBox;
  eyes?: { l: FeatureBox; r: FeatureBox };
  /** Sampled colours so overlays blend with the photo. */
  skin?: string;
  lip?: string;
}

interface Manifest {
  model: string;
  characters: Character[];
}

const ROLE_SLUG: Record<Role, string> = {
  'Data Scientist': 'data-scientist',
  'Algorithm Researcher': 'algorithm-researcher',
  'AI Engineer': 'ai-engineer',
};

/** Voice gender for a style — mirrors STYLE_VOICES (af_* = female, am_* = male). */
export function genderForStyle(style: InterviewerStyle): 'male' | 'female' {
  return STYLE_VOICES[style]?.voice.startsWith('af_') ? 'female' : 'male';
}

const EMPTY: Manifest = { model: '', characters: [] };

let manifestCache: Promise<Manifest> | null = null;
function loadManifest(): Promise<Manifest> {
  if (!manifestCache) {
    manifestCache = fetch('/interviewers/manifest.json')
      .then((r) => (r.ok ? r.json() : EMPTY))
      // Guard against a non-manifest response (e.g. a mocked fetch in tests).
      .then((m: unknown) =>
        m && Array.isArray((m as Manifest).characters) ? (m as Manifest) : EMPTY,
      )
      .catch(() => EMPTY);
  }
  return manifestCache;
}

/** Test hook: drop the cached manifest so a fresh fetch mock takes effect. */
export function __resetCharacterCacheForTests(): void {
  manifestCache = null;
}

const STORE_KEY = 'ti_interviewer_char';

function readStore(): Record<string, string> {
  try {
    return JSON.parse(window.localStorage.getItem(STORE_KEY) || '{}');
  } catch {
    return {};
  }
}
function writeStore(store: Record<string, string>): void {
  try {
    window.localStorage.setItem(STORE_KEY, JSON.stringify(store));
  } catch {
    /* storage unavailable — non-fatal, character just re-samples */
  }
}

/** Stable string hash → non-negative int, so a session always maps to the
 *  same character even before the choice is persisted. */
function hash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i += 1) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return h;
}

export const characterImageUrl = (c: Character): string => `/interviewers/${c.file}`;

/**
 * Return the character for a session, sampling (and persisting) one on first
 * call. Falls back gracefully (gender-only, then any) if a role pool is empty,
 * and returns null if the pool couldn't load — callers then use the 3D/SVG
 * avatar instead.
 */
export async function getSessionCharacter(
  sessionId: string,
  role: Role,
  style: InterviewerStyle,
): Promise<Character | null> {
  const manifest = await loadManifest();
  if (!manifest.characters.length) return null;

  const store = readStore();
  const pinnedId = store[sessionId];
  if (pinnedId) {
    const found = manifest.characters.find((c) => c.id === pinnedId);
    if (found) return found;
  }

  const gender = genderForStyle(style);
  const slug = ROLE_SLUG[role];
  const byRoleAndGender = manifest.characters.filter((c) => c.role === slug && c.gender === gender);
  const byGender = manifest.characters.filter((c) => c.gender === gender);
  const pool = byRoleAndGender.length ? byRoleAndGender : byGender.length ? byGender : manifest.characters;

  const pick = pool[hash(sessionId) % pool.length];
  store[sessionId] = pick.id;
  writeStore(store);
  return pick;
}
