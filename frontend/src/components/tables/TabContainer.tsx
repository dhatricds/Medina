import { useProjectStore } from '../../store/projectStore';
import FixtureTable from './FixtureTable';
import KeynoteTable from './KeynoteTable';

export default function TabContainer() {
  const { activeTab, setActiveTab, projectData, editCount, recalcTotals, saveEdits, projectId, appState, error } = useProjectStore();

  const fixtureCount = projectData?.fixtures.length ?? 0;
  const keynoteCount = projectData?.keynotes.length ?? 0;

  if (appState === 'empty') {
    return (
      <div className="flex-1 flex items-center justify-center text-text-light">
        <div className="text-center">
          <p className="text-lg font-semibold mb-2">Upload a blueprint to begin</p>
          <p className="text-sm">Or try a demo project from the left panel</p>
        </div>
      </div>
    );
  }

  if (appState === 'error') {
    return (
      <div className="flex-1 flex items-center justify-center text-text-light">
        <div className="text-center">
          <div className="w-12 h-12 rounded-full bg-red-100 flex items-center justify-center mx-auto mb-3">
            <span className="text-error text-xl font-bold">!</span>
          </div>
          <p className="text-lg font-semibold mb-2 text-error">Processing Failed</p>
          <p className="text-sm max-w-md">{error || 'An unexpected error occurred'}</p>
        </div>
      </div>
    );
  }

  if (appState === 'processing' && !projectData) {
    return (
      <div className="flex-1 flex items-center justify-center text-text-light">
        <div className="text-center">
          <div className="w-12 h-12 border-4 border-primary/30 border-t-primary rounded-full animate-spin mx-auto mb-4" />
          <p className="text-lg font-semibold mb-2">Processing pipeline running</p>
          <p className="text-sm">Results will appear here when ready</p>
        </div>
      </div>
    );
  }

  const noSchedules = projectData && projectData.fixtures.length === 0;
  const noPlans = projectData && (projectData.lighting_plans?.length ?? 0) === 0;

  if (appState === 'complete' && noSchedules && noPlans) {
    return (
      <div className="flex-1 flex items-center justify-center text-text-light">
        <div className="text-center max-w-sm">
          <div className="w-14 h-14 rounded-full bg-warning/10 flex items-center justify-center mx-auto mb-4">
            <svg viewBox="0 0 24 24" fill="none" stroke="#f59e0b" strokeWidth="2" className="w-7 h-7">
              <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
              <line x1="12" y1="9" x2="12" y2="13" />
              <line x1="12" y1="17" x2="12.01" y2="17" />
            </svg>
          </div>
          <p className="text-base font-semibold mb-2 text-text-main">No Schedules or Lighting Plans Found</p>
          <p className="text-sm mb-3">The pipeline could not identify any luminaire schedule tables or lighting plan pages in this document.</p>
          <p className="text-xs text-text-light">Possible reasons:</p>
          <ul className="text-xs text-text-light text-left mt-1.5 space-y-1 list-disc list-inside">
            <li>The PDF may not contain electrical lighting sheets</li>
            <li>Page classification could not match expected sheet types</li>
            <li>The schedule table format may not be recognized</li>
            <li>Text extraction may have failed (scanned/image-only PDF)</li>
          </ul>
          <p className="text-xs text-text-light mt-3">Try a different PDF or check the agent status in the center panel for details.</p>
        </div>
      </div>
    );
  }

  if (appState === 'complete' && noSchedules) {
    return (
      <div className="flex-1 flex items-center justify-center text-text-light">
        <div className="text-center max-w-sm">
          <div className="w-14 h-14 rounded-full bg-warning/10 flex items-center justify-center mx-auto mb-4">
            <svg viewBox="0 0 24 24" fill="none" stroke="#f59e0b" strokeWidth="2" className="w-7 h-7">
              <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
              <line x1="12" y1="9" x2="12" y2="13" />
              <line x1="12" y1="17" x2="12.01" y2="17" />
            </svg>
          </div>
          <p className="text-base font-semibold mb-2 text-text-main">No Fixture Schedules Found</p>
          <p className="text-sm mb-2">Lighting plan pages were identified, but no luminaire schedule table could be extracted.</p>
          <p className="text-xs text-text-light">Without a schedule, fixture types and specifications cannot be determined. Check that the PDF includes a luminaire schedule page.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* Tabs */}
      <div className="flex bg-card border-b border-border px-4">
        <button
          className={`px-5 py-3 text-[13px] font-semibold cursor-pointer border-b-2 transition-all ${
            activeTab === 'lighting'
              ? 'text-primary border-accent'
              : 'text-text-light border-transparent hover:text-text-main'
          }`}
          onClick={() => setActiveTab('lighting')}
        >
          Lighting Inventory
          <span className="bg-primary text-white text-[10px] px-1.5 py-px rounded-full ml-1.5">
            {fixtureCount}
          </span>
        </button>
        <button
          className={`px-5 py-3 text-[13px] font-semibold cursor-pointer border-b-2 transition-all ${
            activeTab === 'keynotes'
              ? 'text-primary border-accent'
              : 'text-text-light border-transparent hover:text-text-main'
          }`}
          onClick={() => setActiveTab('keynotes')}
        >
          Keynotes
          <span className="bg-primary text-white text-[10px] px-1.5 py-px rounded-full ml-1.5">
            {keynoteCount}
          </span>
        </button>
      </div>

      {/* Toolbar */}
      <div className="px-4 py-2.5 bg-card flex items-center justify-between border-b border-border">
        <div className="flex items-center gap-3">
          <span className="text-xs text-text-light">Click any count cell to edit</span>
          {editCount > 0 && (
            <span className="text-[11px] text-warning font-semibold">
              {editCount} manual edit{editCount > 1 ? 's' : ''}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {editCount > 0 && projectId && (
            <button
              className="px-3 py-1.5 rounded-md text-xs font-semibold bg-accent text-white hover:bg-accent-hover cursor-pointer transition-all"
              onClick={saveEdits}
            >
              Save Corrections
            </button>
          )}
          <button
            className="px-3 py-1.5 rounded-md text-xs font-semibold bg-white text-text-main border border-border hover:bg-bg cursor-pointer transition-all"
            onClick={recalcTotals}
          >
            Recalculate Totals
          </button>
        </div>
      </div>

      {/* Table */}
      {activeTab === 'lighting' ? <FixtureTable /> : <KeynoteTable />}
    </div>
  );
}
