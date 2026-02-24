import { useState } from 'react';
import { useProjectStore } from '../../store/projectStore';
import FixtureTable from './FixtureTable';
import KeynoteTable from './KeynoteTable';
import AddFixtureModal from './AddFixtureModal';
import ChatPanel from './ChatPanel';
import FixItPanel from './FixItPanel';

export default function TabContainer() {
  const { activeTab, setActiveTab, projectData, editCount, recalcTotals, projectId, appState, error, feedbackCount, addFixtureFeedback, chatOpen, setChatOpen, fixItOpen, setFixItOpen } = useProjectStore();
  const [showAddModal, setShowAddModal] = useState(false);

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

  // Chat button component (reused in multiple places)
  const ChatButton = () => (
    <button
      className={`px-3 py-1.5 rounded-md text-xs font-semibold cursor-pointer transition-all flex items-center gap-1 ${
        chatOpen
          ? 'bg-blue-600 text-white'
          : 'bg-blue-50 text-blue-700 border border-blue-200 hover:bg-blue-100'
      }`}
      onClick={() => setChatOpen(!chatOpen)}
    >
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
        <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
      </svg>
      Chat
    </button>
  );

  if (appState === 'complete' && noSchedules && noPlans) {
    return (
      <div className="flex-1 flex flex-col overflow-hidden">
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
            <div className="mt-4 border-t border-amber-200 pt-3">
              <ChatButton />
              <p className="text-xs text-text-light mt-1.5 text-center">
                Describe page corrections in plain English
              </p>
            </div>
          </div>
        </div>
        {chatOpen && <ChatPanel />}
      </div>
    );
  }

  if (appState === 'complete' && noSchedules) {
    return (
      <div className="flex-1 flex flex-col overflow-hidden">
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
            <div className="mt-4 border-t border-amber-200 pt-3">
              <ChatButton />
              <p className="text-xs text-text-light mt-1.5 text-center">
                Describe page corrections in plain English
              </p>
            </div>
          </div>
        </div>
        {chatOpen && <ChatPanel />}
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
          <button
            className="px-3 py-1.5 rounded-md text-xs font-semibold bg-blue-50 text-blue-700 border border-blue-200 hover:bg-blue-100 cursor-pointer transition-all flex items-center gap-1"
            onClick={() => setShowAddModal(true)}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <line x1="12" y1="5" x2="12" y2="19" />
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
            Add Fixture
          </button>
          <ChatButton />
          <span className="text-xs text-text-light">Click any count cell to edit</span>
          {editCount > 0 && (
            <span className="text-[11px] text-warning font-semibold">
              {editCount} manual edit{editCount > 1 ? 's' : ''}
            </span>
          )}
          {feedbackCount > 0 && (
            <span className="text-[11px] text-blue-600 font-semibold bg-blue-50 px-2 py-0.5 rounded-full">
              {feedbackCount} correction{feedbackCount > 1 ? 's' : ''}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            className="px-3 py-1.5 rounded-md text-xs font-semibold bg-white text-text-main border border-border hover:bg-bg cursor-pointer transition-all"
            onClick={recalcTotals}
          >
            Recalculate Totals
          </button>
        </div>
      </div>

      {/* Chat Panel (replaces Fix It) */}
      {chatOpen && appState === 'complete' && <ChatPanel />}

      {/* Table */}
      {activeTab === 'lighting' ? <FixtureTable /> : <KeynoteTable />}

      {showAddModal && (
        <AddFixtureModal
          onSubmit={addFixtureFeedback}
          onClose={() => setShowAddModal(false)}
        />
      )}
    </div>
  );
}
