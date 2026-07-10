/** Current interview section + question progress pill (DESIGN.md §10). */

export interface SectionIndicatorProps {
  section: string;
  sectionIndex: number;
  totalSections: number;
  questionIndex: number;
  totalQuestions: number;
}

export default function SectionIndicator({
  section,
  sectionIndex,
  totalSections,
  questionIndex,
  totalQuestions,
}: SectionIndicatorProps) {
  return (
    <div className="flex items-center gap-3 rounded-full border border-slate-700 bg-slate-900/80 px-4 py-1.5 text-sm">
      <span className="font-medium capitalize text-indigo-300">
        {section || 'Waiting to begin'}
      </span>
      {totalSections > 0 && (
        <span className="flex items-center gap-1" aria-label={`Section ${sectionIndex + 1} of ${totalSections}`}>
          {Array.from({ length: totalSections }, (_, i) => (
            <span
              key={i}
              className={`h-1.5 w-1.5 rounded-full ${i <= sectionIndex ? 'bg-indigo-400' : 'bg-slate-700'}`}
            />
          ))}
        </span>
      )}
      {totalQuestions > 0 && (
        <span className="text-xs text-slate-400">
          Q {Math.min(questionIndex + 1, totalQuestions)}/{totalQuestions}
        </span>
      )}
    </div>
  );
}
