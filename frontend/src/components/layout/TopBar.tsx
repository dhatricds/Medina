import { useProjectStore } from '../../store/projectStore';
import { useAuthStore } from '../../store/authStore';

export default function TopBar() {
  const {
    view, setView, projectData, appState, downloadExcel,
    uploadAndProcess, reset, loadSources, loadDashboard,
    approveCurrentProject, projectId, approvedProjectIds,
    feedbackCount, reprocessWithFeedback, getCorrectionSummary,
  } = useProjectStore();
  const { user, logout } = useAuthStore();

  const isApproved = projectId ? approvedProjectIds.has(projectId) : false;
  const correctionSummary = appState === 'complete' ? getCorrectionSummary() : null;

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      try {
        await uploadAndProcess(file);
      } catch (err) {
        console.error('Upload failed:', err);
      }
    }
    e.target.value = '';
  };

  return (
    <div className="bg-primary text-white px-6 py-3 flex items-center justify-between shadow-lg z-50">
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2.5 text-lg font-bold tracking-tight">
          <img src="/cds-vision-logo.png" className="h-7 w-auto" alt="CDS Vision" />
          Blueprint Estimation System
        </div>

        {/* View toggle tabs */}
        <div className="flex ml-4 bg-white/10 rounded-md p-0.5">
          <button
            className={`px-3.5 py-1.5 rounded text-[12px] font-semibold transition-all cursor-pointer ${
              view === 'dashboard' || view === 'dashboard_detail'
                ? 'bg-white text-primary shadow-sm'
                : 'text-white/70 hover:text-white'
            }`}
            onClick={() => {
              setView('dashboard');
              loadDashboard();
            }}
          >
            Dashboard
          </button>
          <button
            className={`px-3.5 py-1.5 rounded text-[12px] font-semibold transition-all cursor-pointer ${
              view === 'workspace'
                ? 'bg-white text-primary shadow-sm'
                : 'text-white/70 hover:text-white'
            }`}
            onClick={() => setView('workspace')}
          >
            Workspace
          </button>
        </div>

        {view === 'workspace' && projectData && (
          <div className="text-[13px] text-slate-400 ml-2">
            <div className="text-white font-semibold text-sm">{projectData.project_name}</div>
            <div>{projectData.total_pages ?? projectData.pages?.length ?? projectData.sheet_index.length} sheets</div>
          </div>
        )}
      </div>
      <div className="flex gap-2.5">
        {/* Approve button — visible when workspace has complete results */}
        {view === 'workspace' && appState === 'complete' && projectId && (
          isApproved ? (
            <div className="px-4 py-2 rounded-md text-[13px] font-semibold flex items-center gap-1.5 bg-green-700/50 text-green-200 border border-green-600/30">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <polyline points="20 6 9 17 4 12" />
              </svg>
              Approved
            </div>
          ) : (
            <>
              {correctionSummary && correctionSummary.needsRerun && (
                <div className="px-3 py-1.5 rounded-md text-[11px] font-medium bg-yellow-500/20 text-yellow-200 border border-yellow-500/30">
                  Schedule changes — consider Re-run All
                </div>
              )}
              <button
                className="px-4 py-2 rounded-md text-[13px] font-semibold flex items-center gap-1.5 bg-success text-white hover:bg-green-600 transition-all cursor-pointer"
                onClick={approveCurrentProject}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
                Approve
                {correctionSummary && correctionSummary.totalDiffs > 0 && (
                  <span className="bg-white/20 text-[10px] px-1.5 py-px rounded-full ml-0.5">
                    {correctionSummary.totalDiffs}
                  </span>
                )}
              </button>
            </>
          )
        )}

        {view === 'workspace' && appState !== 'empty' && (
          <button
            className="px-4 py-2 rounded-md text-[13px] font-semibold flex items-center gap-1.5 bg-accent text-white hover:bg-accent-hover transition-all cursor-pointer"
            onClick={() => { reset(); loadSources(); }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="12" y1="5" x2="12" y2="19" />
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
            New Project
          </button>
        )}
        {view === 'workspace' && (
          <>
            <button
              className="px-4 py-2 rounded-md text-[13px] font-semibold flex items-center gap-1.5 bg-white/10 text-white border border-white/20 hover:bg-white/20 transition-all cursor-pointer"
              onClick={() => document.getElementById('fileInput')?.click()}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="17 8 12 3 7 8" />
                <line x1="12" y1="3" x2="12" y2="15" />
              </svg>
              Upload PDF
            </button>
            <input type="file" id="fileInput" accept=".pdf" className="hidden" onChange={handleFileChange} />
            <button
              className={`px-4 py-2 rounded-md text-[13px] font-semibold flex items-center gap-1.5 transition-all cursor-pointer ${
                feedbackCount > 0 && appState === 'complete'
                  ? 'bg-blue-500 text-white hover:bg-blue-600 ring-2 ring-blue-300 ring-offset-1 animate-pulse'
                  : 'bg-white/10 text-white border border-white/20 hover:bg-white/20'
              } disabled:opacity-50 disabled:cursor-not-allowed disabled:animate-none`}
              onClick={reprocessWithFeedback}
              disabled={appState !== 'complete' || feedbackCount === 0}
              title={feedbackCount > 0 ? `Re-run pipeline with ${feedbackCount} correction${feedbackCount > 1 ? 's' : ''}` : 'No corrections to apply'}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polyline points="23 4 23 10 17 10" />
                <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
              </svg>
              Re-run All
              {feedbackCount > 0 && (
                <span className="bg-white/20 text-[10px] px-1.5 py-px rounded-full ml-0.5">
                  {feedbackCount}
                </span>
              )}
            </button>
            <button
              className="px-4 py-2 rounded-md text-[13px] font-semibold flex items-center gap-1.5 bg-success text-white hover:bg-green-600 transition-all cursor-pointer disabled:opacity-50"
              onClick={downloadExcel}
              disabled={appState !== 'demo' && appState !== 'complete'}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="7 10 12 15 17 10" />
                <line x1="12" y1="15" x2="12" y2="3" />
              </svg>
              Download Excel
            </button>
          </>
        )}

        {/* User info + logout */}
        {user && (
          <div className="flex items-center gap-2 ml-2 pl-2 border-l border-white/20">
            <div className="text-right">
              <div className="text-[12px] font-medium text-white leading-tight">{user.name}</div>
              <div className="text-[10px] text-white/50 leading-tight">{user.tenant_name}</div>
            </div>
            <button
              className="p-1.5 rounded hover:bg-white/10 transition-colors cursor-pointer"
              onClick={logout}
              title="Sign out"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-white/70">
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                <polyline points="16 17 21 12 16 7" />
                <line x1="21" y1="12" x2="9" y2="12" />
              </svg>
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
