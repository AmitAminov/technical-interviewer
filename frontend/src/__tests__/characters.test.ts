/** Interviewer character: one fixed face per style, gender-matched to the voice. */
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
  __resetCharacterCacheForTests();
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({ ok: true, json: async () => MANIFEST }) as unknown as Response),
  );
});
afterEach(() => vi.unstubAllGlobals());

describe('interviewer character by style', () => {
  it('maps interviewer style to the matching voice gender', () => {
    expect(genderForStyle('Friendly')).toBe('female'); // af_bella
    expect(genderForStyle('Startup CTO')).toBe('male'); // am_fenrir
  });

  it('returns a gender-matched face for the style (male style → male face)', async () => {
    // 'Strict' is male; its assigned id isn't in this manifest, so it falls
    // back to a gender-matched face — which must still be male.
    const c = await getSessionCharacter('Strict');
    expect(c).not.toBeNull();
    expect(c!.gender).toBe('male');
  });

  it('returns the assigned face when present, and is deterministic per style', async () => {
    const a = await getSessionCharacter('Friendly');
    const b = await getSessionCharacter('Friendly');
    expect(a!.id).toBe('data-scientist-0'); // the Friendly-assigned id is in the manifest
    expect(a!.gender).toBe('female');
    expect(a!.id).toBe(b!.id);
  });

  it('returns null when the manifest is malformed (graceful fallback to 3D/SVG)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: true, json: async () => ({ notAManifest: true }) }) as unknown as Response),
    );
    const c = await getSessionCharacter('Friendly');
    expect(c).toBeNull();
  });
});
