/**
 * Hint request button (DESIGN.md §10): hidden entirely when the session hint
 * policy is "none"; otherwise shows how many hints have been used (each hint
 * costs a scoring penalty server-side).
 */

export interface HintButtonProps {
  policy: string;
  hintsUsed: number;
  disabled?: boolean;
  onRequest: () => void;
}

export default function HintButton({ policy, hintsUsed, disabled, onRequest }: HintButtonProps) {
  if (policy === 'none') return null;
  return (
    <button
      type="button"
      className="btn btn-ghost"
      onClick={onRequest}
      disabled={disabled}
      title="Request a hint (small score penalty per hint)"
    >
      <svg
        width="16"
        height="16"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d="M12 2a7 7 0 0 0-4.1 12.7c.7.5 1.1 1.3 1.1 2.1v.2h6v-.2c0-.8.4-1.6 1.1-2.1A7 7 0 0 0 12 2z" />
        <line x1="9" y1="21" x2="15" y2="21" />
      </svg>
      Hint
      {hintsUsed > 0 && (
        <span className="rounded-full bg-amber-500/20 px-1.5 text-[10px] font-semibold text-amber-300">
          {hintsUsed} used
        </span>
      )}
    </button>
  );
}
