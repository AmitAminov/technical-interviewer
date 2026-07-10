/**
 * Shared score → color mapping (DESIGN.md palette): emerald / sky / amber /
 * rose steps used by the per-answer dashboard (0–5) and the report page
 * rings + topic bars (0–100 and 0–5). Returns full Tailwind class names so
 * the JIT scanner picks them up.
 */
export interface ScoreTone {
  bg: string;
  fill: string;
  stroke: string;
  text: string;
}

const TONES = {
  emerald: {
    bg: 'bg-emerald-400',
    fill: 'fill-emerald-400',
    stroke: 'stroke-emerald-400',
    text: 'text-emerald-400',
  },
  sky: {
    bg: 'bg-sky-400',
    fill: 'fill-sky-400',
    stroke: 'stroke-sky-400',
    text: 'text-sky-400',
  },
  amber: {
    bg: 'bg-amber-400',
    fill: 'fill-amber-400',
    stroke: 'stroke-amber-400',
    text: 'text-amber-400',
  },
  rose: {
    bg: 'bg-rose-400',
    fill: 'fill-rose-400',
    stroke: 'stroke-rose-400',
    text: 'text-rose-400',
  },
} as const satisfies Record<string, ScoreTone>;

export function scoreTone(value: number, scale: 5 | 100): ScoreTone {
  const [high, mid, low] = scale === 100 ? [75, 50, 30] : [4, 3, 2];
  if (value >= high) return TONES.emerald;
  if (value >= mid) return TONES.sky;
  if (value >= low) return TONES.amber;
  return TONES.rose;
}
