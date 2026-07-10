/**
 * Interviewer character — one fixed photorealistic face per interviewer STYLE
 * (not sampled by role). The style you choose determines the interviewer you
 * get, and that face's gender always matches the style's voice gender
 * (STYLE_VOICES), so the voice and the character agree in every language.
 *
 * Faces live under public/interviewers/ with a manifest.json. A deploy with
 * differently-licensed images (e.g. the public GitHub repo) ships its own files
 * + manifest and sets its own STYLE_CHARACTER ids; unknown ids fall back to any
 * gender-matched face, so the interview still shows a consistent character.
 */
import type { InterviewerStyle } from './types';
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
  mouth?: FeatureBox;
  eyes?: { l: FeatureBox; r: FeatureBox };
  skin?: string;
  lip?: string;
}

interface Manifest {
  model: string;
  characters: Character[];
}

/** Voice gender for a style — mirrors STYLE_VOICES (af_* = female, am_* = male). */
export function genderForStyle(style: InterviewerStyle): 'male' | 'female' {
  return STYLE_VOICES[style]?.voice.startsWith('af_') ? 'female' : 'male';
}

/**
 * Each interviewer style → the manifest character id to show for it. Ids must be
 * gender-consistent with genderForStyle (3 female styles, 2 male). These are the
 * local asset ids; a differently-licensed deploy overrides them, and any id not
 * in the manifest falls back to a gender-matched face below.
 */
const STYLE_CHARACTER: Record<InterviewerStyle, string> = {
  Friendly: 'data-scientist-0', // female
  'Research professor': 'algorithm-researcher-0', // female
  'Big-tech interviewer': 'ai-engineer-0', // female
  Strict: 'algorithm-researcher-2', // male
  'Startup CTO': 'ai-engineer-2', // male
};

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

export const characterImageUrl = (c: Character): string => `/interviewers/${c.file}`;

/**
 * The interviewer character for the chosen style: the face assigned to that
 * style, guaranteed to match its voice gender. Falls back to any gender-matched
 * face (then any face) when the assigned id isn't in the manifest, and returns
 * null only if the pool couldn't load — callers then use the 3D/SVG head.
 */
export async function getSessionCharacter(style: InterviewerStyle): Promise<Character | null> {
  const manifest = await loadManifest();
  if (!manifest.characters.length) return null;

  const gender = genderForStyle(style);
  const wantId = STYLE_CHARACTER[style];
  return (
    manifest.characters.find((c) => c.id === wantId && c.gender === gender) ??
    manifest.characters.find((c) => c.id === wantId) ??
    manifest.characters.find((c) => c.gender === gender) ??
    manifest.characters[0] ??
    null
  );
}
