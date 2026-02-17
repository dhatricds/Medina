import { useProjectStore } from '../../store/projectStore';

export default function TopBar() {
  const { projectData, appState, downloadExcel, uploadAndProcess, reset, loadSources } = useProjectStore();

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
          <svg viewBox="0 0 28 28" fill="none" className="w-7 h-7">
            <rect width="28" height="28" rx="6" fill="#e8942e" />
            <path d="M7 14h14M14 7v14M9 9l10 10M19 9L9 19" stroke="white" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
          Blueprint Estimation System
        </div>
        {projectData && (
          <div className="text-[13px] text-slate-400">
            <div className="text-white font-semibold text-sm">{projectData.project_name}</div>
            <div>{projectData.total_pages ?? projectData.pages?.length ?? projectData.sheet_index.length} sheets</div>
          </div>
        )}
      </div>
      <div className="flex gap-2.5">
        {appState !== 'empty' && (
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
          className="px-4 py-2 rounded-md text-[13px] font-semibold flex items-center gap-1.5 bg-white/10 text-white border border-white/20 hover:bg-white/20 transition-all cursor-pointer"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="23 4 23 10 17 10" />
            <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
          </svg>
          Re-run All
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
      </div>
    </div>
  );
}
