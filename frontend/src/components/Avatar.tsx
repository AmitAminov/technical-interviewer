/**
 * Synthetic interviewer avatar (DESIGN.md §10 Avatar.tsx).
 *
 * Pure SVG, obviously non-photoreal but professional: head + shoulders, eyes
 * that blink every 3–6s, an animated mouth cycling through 4 viseme shapes
 * while speaking, and a subtle idle sway. Each of the five interviewer styles
 * gets its own palette and accessory (Friendly = warm, Strict = navy +
 * glasses, Research professor = beard + blazer, Startup CTO = hoodie,
 * Big-tech interviewer = lanyard badge).
 */
import { useEffect, useId, useState } from 'react';

import type { InterviewerStyle } from '../lib/types';

export interface AvatarProps {
  style: InterviewerStyle;
  speaking: boolean;
  name: string;
  /** Pixel size of the (square) avatar. */
  size?: number;
  /** Increment on each TTS word boundary to advance the mouth shape. */
  wordTick?: number;
  /**
   * Explicit mouth shape (0-3) driven by real TTS visemes
   * (see visemeToMouthShape in lib/voice.ts). When provided while speaking it
   * overrides the interval/word-tick cycling for tighter mouth sync.
   */
  mouthShape?: number | null;
}

interface Palette {
  bgInner: string;
  bgOuter: string;
  skin: string;
  hair: string;
  garment: string;
  garmentDark: string;
  accent: string;
}

/** Lighten (amount>0) or darken (amount<0) a #rrggbb hex by a fraction. */
function shade(hex: string, amount: number): string {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return hex;
  const n = parseInt(m[1], 16);
  const adj = (c: number) =>
    Math.max(0, Math.min(255, Math.round(c + (amount < 0 ? c : 255 - c) * amount)));
  const r = adj((n >> 16) & 0xff);
  const g = adj((n >> 8) & 0xff);
  const b = adj(n & 0xff);
  return `#${((1 << 24) | (r << 16) | (g << 8) | b).toString(16).slice(1)}`;
}

const PALETTES: Record<InterviewerStyle, Palette> = {
  Friendly: {
    bgInner: '#92400e',
    bgOuter: '#431407',
    skin: '#f3c19d',
    hair: '#7c4a21',
    garment: '#e07a5f',
    garmentDark: '#c1583f',
    accent: '#fde68a',
  },
  Strict: {
    bgInner: '#1e3a5f',
    bgOuter: '#0b1626',
    skin: '#e8b48c',
    hair: '#26303c',
    garment: '#1e293b',
    garmentDark: '#141c29',
    accent: '#cbd5e1',
  },
  'Research professor': {
    bgInner: '#44403c',
    bgOuter: '#1c1917',
    skin: '#e6b899',
    hair: '#d6d3d1',
    garment: '#78716c',
    garmentDark: '#57534e',
    accent: '#9a3412',
  },
  'Startup CTO': {
    bgInner: '#134e4a',
    bgOuter: '#042f2e',
    skin: '#f0c8a0',
    hair: '#3f2d20',
    garment: '#4b5563',
    garmentDark: '#374151',
    accent: '#2dd4bf',
  },
  'Big-tech interviewer': {
    bgInner: '#312e81',
    bgOuter: '#14122e',
    skin: '#d9a878',
    hair: '#111827',
    garment: '#2563eb',
    garmentDark: '#1d4ed8',
    accent: '#f43f5e',
  },
};

/** Mouth viseme shapes (index 0 = closed/resting). */
function Mouth({
  idx,
  style,
  speaking,
}: {
  idx: number;
  style: InterviewerStyle;
  speaking: boolean;
}) {
  if (!speaking) {
    // Resting expression differs per persona.
    if (style === 'Strict') {
      return <path d="M106 148 L134 148" stroke="#7f1d1d" strokeWidth="3" strokeLinecap="round" fill="none" />;
    }
    if (style === 'Friendly') {
      return <path d="M102 145 Q120 158 138 145" stroke="#7f1d1d" strokeWidth="3.5" strokeLinecap="round" fill="none" />;
    }
    return <path d="M104 146 Q120 154 136 146" stroke="#7f1d1d" strokeWidth="3" strokeLinecap="round" fill="none" />;
  }
  switch (idx % 4) {
    case 0:
      return <ellipse cx="120" cy="148" rx="7" ry="3.5" fill="#7f1d1d" />;
    case 1:
      return (
        <g>
          <ellipse cx="120" cy="149" rx="10" ry="7.5" fill="#5d1414" />
          <ellipse cx="120" cy="152" rx="6" ry="3" fill="#b0596a" />
        </g>
      );
    case 2:
      return (
        <g>
          <ellipse cx="120" cy="149" rx="13" ry="9.5" fill="#5d1414" />
          <ellipse cx="120" cy="153" rx="8" ry="4" fill="#b0596a" />
          <rect x="110" y="141" width="20" height="3.5" rx="1.5" fill="#f8fafc" />
        </g>
      );
    default:
      return <rect x="108" y="144" width="24" height="7" rx="3.5" fill="#5d1414" />;
  }
}

function Hair({ style, color }: { style: InterviewerStyle; color: string }) {
  switch (style) {
    case 'Friendly':
      return <path d="M74 102 Q74 54 120 52 Q166 54 166 102 Q158 70 120 68 Q82 70 74 102 Z" fill={color} />;
    case 'Strict':
      return (
        <path d="M74 100 Q76 52 120 50 Q164 52 166 100 L166 86 Q158 60 122 60 L100 66 Q80 72 74 94 Z" fill={color} />
      );
    case 'Research professor':
      // Balding: side patches only.
      return (
        <g fill={color}>
          <path d="M72 104 Q70 82 82 70 Q78 92 80 108 Z" />
          <path d="M168 104 Q170 82 158 70 Q162 92 160 108 Z" />
        </g>
      );
    case 'Startup CTO':
      // Messy fringe.
      return (
        <path
          d="M74 102 Q72 56 120 52 Q168 56 166 102 Q160 78 148 78 L142 66 L132 76 L120 64 L108 76 L98 66 L92 78 Q80 78 74 102 Z"
          fill={color}
        />
      );
    default:
      // Big-tech: neat short cut.
      return <path d="M74 100 Q78 54 120 52 Q162 54 166 100 Q156 66 120 64 Q84 66 74 100 Z" fill={color} />;
  }
}

function Accessory({ style, palette }: { style: InterviewerStyle; palette: Palette }) {
  switch (style) {
    case 'Strict':
      return (
        <g>
          {/* glasses */}
          <circle cx="100" cy="108" r="12" fill="none" stroke={palette.accent} strokeWidth="2.5" />
          <circle cx="140" cy="108" r="12" fill="none" stroke={palette.accent} strokeWidth="2.5" />
          <path d="M112 108 L128 108" stroke={palette.accent} strokeWidth="2.5" />
          {/* shirt + tie */}
          <path d="M104 178 L120 198 L136 178 L120 186 Z" fill="#e2e8f0" />
          <path d="M116 185 L124 185 L122 212 L120 218 L118 212 Z" fill="#991b1b" />
        </g>
      );
    case 'Research professor':
      return (
        <g>
          {/* round thin glasses */}
          <circle cx="100" cy="108" r="10" fill="none" stroke="#d6d3d1" strokeWidth="1.8" />
          <circle cx="140" cy="108" r="10" fill="none" stroke="#d6d3d1" strokeWidth="1.8" />
          <path d="M110 108 L130 108" stroke="#d6d3d1" strokeWidth="1.8" />
          {/* full beard */}
          <path
            d="M86 116 Q88 162 120 168 Q152 162 154 116 Q144 140 120 140 Q96 140 86 116 Z"
            fill={PALETTES['Research professor'].hair}
          />
          {/* sweater under blazer */}
          <path d="M102 178 L120 200 L138 178 L120 188 Z" fill={PALETTES['Research professor'].accent} />
        </g>
      );
    case 'Startup CTO':
      return (
        <g>
          {/* hood collar */}
          <path d="M82 190 Q120 212 158 190 Q150 170 120 166 Q90 170 82 190 Z" fill={PALETTES['Startup CTO'].garmentDark} />
          {/* drawstrings */}
          <path d="M112 192 Q110 204 109 216" stroke="#e5e7eb" strokeWidth="2.5" fill="none" strokeLinecap="round" />
          <path d="M128 192 Q130 204 131 216" stroke="#e5e7eb" strokeWidth="2.5" fill="none" strokeLinecap="round" />
          <circle cx="109" cy="218" r="2.5" fill="#e5e7eb" />
          <circle cx="131" cy="218" r="2.5" fill="#e5e7eb" />
        </g>
      );
    case 'Big-tech interviewer':
      return (
        <g>
          {/* lanyard + badge */}
          <path d="M102 180 L118 210" stroke={PALETTES['Big-tech interviewer'].accent} strokeWidth="3.5" />
          <path d="M138 180 L122 210" stroke={PALETTES['Big-tech interviewer'].accent} strokeWidth="3.5" />
          <rect x="107" y="208" width="26" height="18" rx="2.5" fill="#f8fafc" />
          <rect x="110" y="211" width="8" height="8" rx="1" fill="#94a3b8" />
          <rect x="120" y="212" width="10" height="2" rx="1" fill="#64748b" />
          <rect x="120" y="216" width="8" height="2" rx="1" fill="#94a3b8" />
        </g>
      );
    default:
      // Friendly: open collar detail.
      return <path d="M106 178 L120 192 L134 178" stroke={PALETTES.Friendly.accent} strokeWidth="3" fill="none" strokeLinecap="round" />;
  }
}

export default function Avatar({
  style,
  speaking,
  name,
  size = 280,
  wordTick,
  mouthShape,
}: AvatarProps) {
  const palette = PALETTES[style] ?? PALETTES.Friendly;
  const gradientId = useId();
  const [blinking, setBlinking] = useState(false);
  const [mouthIdx, setMouthIdx] = useState(0);

  // Random blink every 3–6 seconds.
  useEffect(() => {
    let alive = true;
    let timer = 0;
    const schedule = () => {
      timer = window.setTimeout(
        () => {
          if (!alive) return;
          setBlinking(true);
          window.setTimeout(() => {
            if (!alive) return;
            setBlinking(false);
            schedule();
          }, 140);
        },
        3000 + Math.random() * 3000,
      );
    };
    schedule();
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, []);

  // Mouth cycles through visemes while speaking (interval fallback…
  useEffect(() => {
    if (!speaking) {
      setMouthIdx(0);
      return;
    }
    const interval = window.setInterval(() => setMouthIdx((i) => (i + 1) % 4), 140);
    return () => window.clearInterval(interval);
  }, [speaking]);

  // …and TTS word-boundary events advance it too, for tighter mouth sync).
  useEffect(() => {
    if (speaking && wordTick !== undefined) {
      setMouthIdx((i) => (i + 1) % 4);
    }
  }, [wordTick, speaking]);

  // Real viseme stream (kokoro TTS) overrides the interval/word-tick cycling.
  const displayedMouthIdx = speaking && mouthShape != null ? mouthShape : mouthIdx;

  return (
    <div className="relative inline-block" style={{ width: size, height: size }}>
      {speaking && (
        <span
          data-testid="speaking-ring"
          className="pointer-events-none absolute inset-0 rounded-full border-4 border-indigo-400/70 animate-pulse-ring"
        />
      )}
      <svg
        viewBox="0 0 240 240"
        width={size}
        height={size}
        role="img"
        aria-label={`${style} interviewer avatar${name ? ` — ${name}` : ''}`}
      >
        <title>{`${style} interviewer`}</title>
        <defs>
          <radialGradient id={gradientId} cx="50%" cy="38%" r="75%">
            <stop offset="0%" stopColor={palette.bgInner} />
            <stop offset="100%" stopColor={palette.bgOuter} />
          </radialGradient>
          {/* Skin: soft key light from upper-left → base → shadow, for
              volume instead of a flat fill. */}
          <radialGradient id={`${gradientId}-skin`} cx="40%" cy="34%" r="72%">
            <stop offset="0%" stopColor={shade(palette.skin, 0.28)} />
            <stop offset="52%" stopColor={palette.skin} />
            <stop offset="100%" stopColor={shade(palette.skin, -0.28)} />
          </radialGradient>
          <linearGradient id={`${gradientId}-hair`} x1="0" y1="0" x2="0.35" y2="1">
            <stop offset="0%" stopColor={shade(palette.hair, 0.22)} />
            <stop offset="100%" stopColor={shade(palette.hair, -0.22)} />
          </linearGradient>
          <linearGradient id={`${gradientId}-garment`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={shade(palette.garment, 0.14)} />
            <stop offset="100%" stopColor={shade(palette.garment, -0.18)} />
          </linearGradient>
          <clipPath id={`${gradientId}-clip`}>
            <circle cx="120" cy="120" r="118" />
          </clipPath>
        </defs>
        <circle cx="120" cy="120" r="118" fill={`url(#${gradientId})`} />
        <g clipPath={`url(#${gradientId}-clip)`}>
          <g className="animate-sway" style={{ transformOrigin: '120px 200px' }}>
            {/* neck (with a soft under-chin shadow for depth) */}
            <rect x="106" y="146" width="28" height="34" rx="10" fill={`url(#${gradientId}-skin)`} />
            <path d="M104 150 Q120 162 136 150 L136 156 Q120 166 104 156 Z" fill={shade(palette.skin, -0.32)} opacity="0.55" />
            {/* torso */}
            <path
              d="M36 244 Q42 188 84 178 L120 170 L156 178 Q198 188 204 244 Z"
              fill={`url(#${gradientId}-garment)`}
            />
            <path d="M84 178 Q78 182 74 194 L96 186 Z" fill={palette.garmentDark} />
            <path d="M156 178 Q162 182 166 194 L144 186 Z" fill={palette.garmentDark} />
            {/* ears */}
            <circle cx="73" cy="112" r="9" fill={`url(#${gradientId}-skin)`} />
            <circle cx="167" cy="112" r="9" fill={`url(#${gradientId}-skin)`} />
            {/* head */}
            <ellipse cx="120" cy="110" rx="47" ry="52" fill={`url(#${gradientId}-skin)`} />
            {/* cheek/jaw shadow on the shadow side + subtle blush for warmth */}
            <path d="M150 96 Q166 116 150 150 Q160 120 148 100 Z" fill={shade(palette.skin, -0.3)} opacity="0.35" />
            <ellipse cx="98" cy="128" rx="9" ry="6" fill={shade(palette.skin, 0.18)} opacity="0.5" />
            <ellipse cx="142" cy="128" rx="9" ry="6" fill={shade(palette.skin, 0.18)} opacity="0.35" />
            <Hair style={style} color={`url(#${gradientId}-hair)`} />
            {/* eyebrows */}
            {style === 'Strict' ? (
              <g stroke={palette.hair} strokeWidth="3.5" strokeLinecap="round">
                <path d="M90 94 L110 98" fill="none" />
                <path d="M150 94 L130 98" fill="none" />
              </g>
            ) : (
              <g stroke={palette.hair} strokeWidth="3.5" strokeLinecap="round">
                <path d="M90 96 Q100 92 110 95" fill="none" />
                <path d="M130 95 Q140 92 150 96" fill="none" />
              </g>
            )}
            {/* eyes: sclera + brown iris + pupil + catchlight; blink closes
                to a soft lid line rather than a flat black slit */}
            <g data-testid="avatar-eyes" data-blinking={blinking ? 'true' : 'false'}>
              {blinking ? (
                <g stroke={shade(palette.skin, -0.45)} strokeWidth="2.2" strokeLinecap="round" fill="none">
                  <path d="M92.5 108 Q100 111 107.5 108" />
                  <path d="M132.5 108 Q140 111 147.5 108" />
                </g>
              ) : (
                <g>
                  <ellipse cx="100" cy="108" rx="7.2" ry="4.6" fill="#f8fafc" />
                  <ellipse cx="140" cy="108" rx="7.2" ry="4.6" fill="#f8fafc" />
                  <circle cx="100.5" cy="108" r="3.7" fill="#5b3a1e" />
                  <circle cx="140.5" cy="108" r="3.7" fill="#5b3a1e" />
                  <circle cx="100.5" cy="108" r="1.8" fill="#1c1917" />
                  <circle cx="140.5" cy="108" r="1.8" fill="#1c1917" />
                  <circle cx="102" cy="106.3" r="1.1" fill="#f8fafc" />
                  <circle cx="142" cy="106.3" r="1.1" fill="#f8fafc" />
                  {/* upper lids for depth */}
                  <path d="M92.5 105 Q100 101.6 107.5 105" stroke={shade(palette.skin, -0.4)} strokeWidth="1.4" fill="none" strokeLinecap="round" />
                  <path d="M132.5 105 Q140 101.6 147.5 105" stroke={shade(palette.skin, -0.4)} strokeWidth="1.4" fill="none" strokeLinecap="round" />
                </g>
              )}
            </g>
            {/* nose */}
            <path d="M120 116 Q124 126 119 131 Q116 133 114 130" stroke="#c98d63" strokeWidth="2.5" fill="none" strokeLinecap="round" />
            <Accessory style={style} palette={palette} />
            {/* mouth drawn after accessory so it sits above the beard */}
            <Mouth idx={displayedMouthIdx} style={style} speaking={speaking} />
          </g>
        </g>
        <circle cx="120" cy="120" r="118" fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="2" />
      </svg>
    </div>
  );
}
