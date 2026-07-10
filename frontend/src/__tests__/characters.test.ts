/** Character pool sampling: gender-matched to voice, stable per session. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  __resetCharacterCacheForTests,
  genderForStyle,
  getSessionCharacter,
} from '../lib/characters';

const MANIFEST = {
  model: 'imagen',
  characters: [
    { id: 'data-scientist-0', role: 'data-scientist', gender: 'female', file: 'data-scientist-0.jpg' },
    { id: 'data-scientist-2', role: 'data-scientist', gender: 'male', file: 'data-scientist-2.jpg' },
    { id: 'ai-engineer-0', role: 'ai-engineer', gender: 'female', file: 'ai-engineer-0.jpg' },
  ],
};

beforeEach(() => {
  window.localStorage.clear();
  __resetCharacterCacheForTests();
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({ ok: true, json: async () => MANIFEST }) as unknown as Response),
  );
});
afterEach(() => vi.unstubAllGlobals());

describe('interviewer character sampling', () => {
  it('maps interviewer style to the matching voice gender', () => {
    expect(genderForStyle('Friendly')).toBe('female'); // af_bella
    expect(genderForStyle('Startup CTO')).toBe('male'); // am_fenrir
  });

  it('samples a role- and gender-matched character (male voice → male face)', async () => {
    const c = await getSessionCharacter('sess-1', 'Data Scientist', 'Strict');
    expect(c).not.toBeNull();
    expect(c!.role).toBe('data-scientist');
    expect(c!.gender).toBe('male');
  });

  it('is stable for the same session id and persists the choice', async () => {
    const a = await getSessionCharacter('sess-2', 'Data Scientist', 'Friendly');
    const b = await getSessionCharacter('sess-2', 'Data Scientist', 'Friendly');
    expect(a!.id).toBe(b!.id);
    expect(a!.gender).toBe('female');
    expect(JSON.parse(window.localStorage.getItem('ti_interviewer_char')!)['sess-2']).toBe(a!.id);
  });

  it('returns null when the manifest is malformed (graceful fallback to 3D/SVG)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: true, json: async () => ({ notAManifest: true }) }) as unknown as Response),
    );
    const c = await getSessionCharacter('sess-x', 'AI Engineer', 'Friendly');
    expect(c).toBeNull();
  });
});
