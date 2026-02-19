import { useState } from 'react';
import { useProjectStore } from '../../store/projectStore';
import WarningModal from '../qa/WarningModal';

export default function BottomBar() {
  const { projectData, feedbackCount, editCount, getCorrectionSummary } = useProjectStore();
  const [showWarnings, setShowWarnings] = useState(false);

  const qa = projectData?.qa_report;
  const warningCount = qa?.warnings.length ?? 0;
  const summary = getCorrectionSummary();

  return (
    <>
      <div className="bg-card border-t border-border px-6 py-2.5 flex items-center justify-between">
        <div className="flex items-center gap-4">
          {/* Correction stats */}
          {summary.totalDiffs > 0 ? (
            <div className="flex items-center gap-1.5 text-xs font-semibold text-blue-700">
              <span className="w-2 h-2 rounded-full bg-blue-500" />
              {summary.totalDiffs} correction{summary.totalDiffs !== 1 ? 's' : ''}
              {summary.countChanges > 0 && (
                <span className="text-text-light font-normal ml-1">
                  ({summary.countChanges} count{summary.countChanges !== 1 ? 's' : ''})
                </span>
              )}
              {summary.fixtureAdds > 0 && (
                <span className="text-green-600 font-normal ml-1">
                  +{summary.fixtureAdds} added
                </span>
              )}
              {summary.fixtureRemoves > 0 && (
                <span className="text-red-600 font-normal ml-1">
                  -{summary.fixtureRemoves} removed
                </span>
              )}
            </div>
          ) : (
            <span className="text-xs text-text-light">No corrections</span>
          )}

          {/* Pipeline warnings — clickable */}
          {warningCount > 0 && (
            <button
              className="flex items-center gap-1.5 text-xs font-semibold text-amber-700 px-2.5 py-1 rounded-md hover:bg-amber-50 cursor-pointer transition-all"
              onClick={() => setShowWarnings(true)}
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
                <line x1="12" y1="9" x2="12" y2="13" />
                <line x1="12" y1="17" x2="12.01" y2="17" />
              </svg>
              {warningCount} review item{warningCount !== 1 ? 's' : ''}
            </button>
          )}
        </div>

        {/* Right side: fixture/keynote summary */}
        {projectData && (
          <div className="flex items-center gap-3 text-[11px] text-text-light">
            <span>{projectData.fixtures.length} fixture type{projectData.fixtures.length !== 1 ? 's' : ''}</span>
            <span className="text-border">|</span>
            <span>{projectData.summary.total_fixtures} total</span>
            <span className="text-border">|</span>
            <span>{projectData.keynotes.length} keynote{projectData.keynotes.length !== 1 ? 's' : ''}</span>
            <span className="text-border">|</span>
            <span>{projectData.lighting_plans.length} plan{projectData.lighting_plans.length !== 1 ? 's' : ''}</span>
          </div>
        )}
      </div>
      {showWarnings && <WarningModal onClose={() => setShowWarnings(false)} />}
    </>
  );
}
