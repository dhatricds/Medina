import { useState } from 'react';
import { useProjectStore } from '../../store/projectStore';
import WarningModal from '../qa/WarningModal';

export default function BottomBar() {
  const { projectData } = useProjectStore();
  const [showWarnings, setShowWarnings] = useState(false);

  const qa = projectData?.qa_report;
  const warningCount = qa?.warnings.length ?? 0;
  const verified = projectData
    ? projectData.fixtures.length + projectData.keynotes.length - warningCount
    : 0;

  return (
    <>
      <div className="bg-card border-t border-border px-6 py-2.5 flex items-center justify-between">
        <div className="flex items-center">
          <span className="text-xs font-bold text-text-light uppercase tracking-wider">QA Summary</span>
          <div className="flex gap-4 ml-5">
            <div className="flex items-center gap-1.5 text-xs font-semibold text-green-800 px-2.5 py-1 rounded-md hover:bg-bg cursor-pointer">
              <span className="w-2 h-2 rounded-full bg-success" />
              {verified} Verified
            </div>
            <div
              className="flex items-center gap-1.5 text-xs font-semibold text-amber-800 px-2.5 py-1 rounded-md hover:bg-bg cursor-pointer"
              onClick={() => warningCount > 0 && setShowWarnings(true)}
            >
              <span className="w-2 h-2 rounded-full bg-warning" />
              {warningCount} Warning{warningCount !== 1 ? 's' : ''}
            </div>
            <div className="flex items-center gap-1.5 text-xs font-semibold text-red-800 px-2.5 py-1 rounded-md hover:bg-bg cursor-pointer">
              <span className="w-2 h-2 rounded-full bg-error" />
              0 Errors
            </div>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {qa && (
            <span className="text-[10px] px-2 py-0.5 rounded bg-bg text-text-light font-mono">
              Confidence: {(qa.overall_confidence * 100).toFixed(0)}%
            </span>
          )}
          <span className="text-[10px] px-2 py-0.5 rounded bg-bg text-text-light font-mono">
            claude-sonnet
          </span>
        </div>
      </div>
      {showWarnings && <WarningModal onClose={() => setShowWarnings(false)} />}
    </>
  );
}
