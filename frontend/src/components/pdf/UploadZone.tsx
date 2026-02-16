import { useEffect } from 'react';
import { useProjectStore } from '../../store/projectStore';

export default function UploadZone() {
  const { loadDemo, appState, sources, loadSources, processFromSource, uploadAndProcess } = useProjectStore();

  useEffect(() => {
    loadSources();
  }, [loadSources]);

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

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (file && file.name.endsWith('.pdf')) {
      try {
        await uploadAndProcess(file);
      } catch (err) {
        console.error('Upload failed:', err);
      }
    }
  };

  return (
    <div className="flex-1 flex flex-col">
      <div className="px-3 py-2 bg-pdf-toolbar flex items-center justify-between border-b border-white/10">
        <span className="text-slate-400 text-xs">No document loaded</span>
      </div>
      <div
        className="flex-1 flex items-center justify-center p-4"
        onDragOver={(e) => e.preventDefault()}
        onDrop={handleDrop}
      >
        <div
          className="border-2 border-dashed border-white/20 rounded-xl p-10 cursor-pointer hover:border-accent transition-colors"
          onClick={() => document.getElementById('fileInput')?.click()}
        >
          <div className="text-slate-500 text-center">
            <svg viewBox="0 0 64 64" fill="none" stroke="#64748b" strokeWidth="1.5" className="w-16 h-16 mx-auto mb-4 opacity-50">
              <rect x="8" y="4" width="48" height="56" rx="4" />
              <path d="M20 18h24M20 26h24M20 34h16" />
              <rect x="36" y="40" width="12" height="12" rx="2" />
            </svg>
            <p className="font-bold text-sm text-slate-300">Drop blueprint PDF here</p>
            <p className="text-sm mt-1 text-slate-500">or click to browse</p>
          </div>
        </div>
        <input type="file" id="uploadZoneInput" accept=".pdf" className="hidden" onChange={handleFileChange} />
      </div>

      {appState === 'empty' && (
        <div className="px-4 pb-4">
          <div className="text-xs text-slate-500 mb-2 text-center">Or try a demo:</div>
          <div className="flex gap-2 justify-center mb-3">
            <button
              onClick={() => loadDemo('hcmc')}
              className="px-3 py-1.5 rounded text-xs font-semibold bg-accent/20 text-accent hover:bg-accent/30 transition-colors cursor-pointer"
            >
              HCMC (13 fixtures)
            </button>
            <button
              onClick={() => loadDemo('anoka')}
              className="px-3 py-1.5 rounded text-xs font-semibold bg-accent/20 text-accent hover:bg-accent/30 transition-colors cursor-pointer"
            >
              Anoka (10 fixtures)
            </button>
          </div>

          {sources.length > 0 && (
            <div className="border-t border-white/10 pt-3">
              <div className="text-xs text-slate-500 mb-2 text-center">Or select from library:</div>
              <div className="max-h-[200px] overflow-y-auto space-y-1">
                {sources.map((src) => (
                  <button
                    key={src.path}
                    onClick={() => processFromSource(src.path)}
                    className="w-full text-left px-3 py-2 rounded text-xs text-slate-300 hover:bg-white/10 transition-colors cursor-pointer flex items-center gap-2"
                  >
                    <span className="text-slate-500">
                      {src.type === 'folder' ? '\u{1F4C1}' : '\u{1F4C4}'}
                    </span>
                    <span className="truncate">{src.name}</span>
                    {src.size && (
                      <span className="text-slate-600 ml-auto shrink-0">
                        {(src.size / 1024 / 1024).toFixed(1)} MB
                      </span>
                    )}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
