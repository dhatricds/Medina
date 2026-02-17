import { useState, useRef, useCallback } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import 'react-pdf/dist/Page/AnnotationLayer.css';
import 'react-pdf/dist/Page/TextLayer.css';
import { useProjectStore } from '../../store/projectStore';
import { getPdfUrl, getPageImageUrl } from '../../api/client';

// Configure pdf.js worker from CDN
pdfjs.GlobalWorkerOptions.workerSrc = `https://unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;

const MIN_ZOOM = 0.25;
const MAX_ZOOM = 4;
const ZOOM_STEP = 0.25;

export default function PdfViewer() {
  const { projectData, projectId, currentPage, totalPages, setCurrentPage, appState } = useProjectStore();
  const [zoom, setZoom] = useState(1);
  const [numPages, setNumPages] = useState<number | null>(null);
  const [pdfError, setPdfError] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const [containerWidth, setContainerWidth] = useState(0);
  const sheetIndex = projectData?.sheet_index ?? [];
  const pages = projectData?.pages ?? [];

  const currentSheet = sheetIndex[currentPage - 1];
  const currentPageEntry = pages[currentPage - 1];
  const pageLabel = currentSheet
    ? `${currentSheet.sheet_code} ${currentSheet.description}`
    : currentPageEntry
      ? `${currentPageEntry.sheet_code} ${currentPageEntry.description}`
      : '';

  const hasProject = projectId && appState === 'complete';
  const canNavigate = totalPages > 1;

  const zoomIn = useCallback(() => setZoom(z => Math.min(MAX_ZOOM, z + ZOOM_STEP)), []);
  const zoomOut = useCallback(() => setZoom(z => Math.max(MIN_ZOOM, z - ZOOM_STEP)), []);
  const zoomReset = useCallback(() => setZoom(1), []);

  const goToPrev = useCallback(() => {
    if (currentPage > 1) {
      setZoom(1);
      setCurrentPage(currentPage - 1);
    }
  }, [currentPage, setCurrentPage]);

  const goToNext = useCallback(() => {
    if (currentPage < totalPages) {
      setZoom(1);
      setCurrentPage(currentPage + 1);
    }
  }, [currentPage, totalPages, setCurrentPage]);

  const handleWheel = useCallback((e: React.WheelEvent) => {
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault();
      setZoom(z => {
        const delta = e.deltaY > 0 ? -ZOOM_STEP : ZOOM_STEP;
        return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, z + delta));
      });
    }
  }, []);

  // Measure container width so react-pdf can fit the page
  const measuredRef = useCallback((node: HTMLDivElement | null) => {
    if (node) {
      const observer = new ResizeObserver(entries => {
        for (const entry of entries) {
          setContainerWidth(entry.contentRect.width - 32); // minus padding
        }
      });
      observer.observe(node);
      containerRef.current = node;
      setContainerWidth(node.clientWidth - 32);
    }
  }, []);

  const onDocumentLoadSuccess = useCallback(({ numPages: n }: { numPages: number }) => {
    setNumPages(n);
    setPdfError(false);
  }, []);

  const onDocumentLoadError = useCallback(() => {
    setPdfError(true);
  }, []);

  const zoomPercent = Math.round(zoom * 100);
  const pdfUrl = hasProject ? getPdfUrl(projectId) : null;
  const pageWidth = containerWidth > 0 ? containerWidth * zoom : undefined;

  return (
    <div className="flex-1 flex flex-col">
      <div className="px-3 py-2 bg-pdf-toolbar flex items-center justify-between border-b border-white/10">
        <span className="text-slate-400 text-xs truncate mr-2">
          {totalPages > 0
            ? `Page ${currentPage} of ${totalPages} — ${pageLabel}`
            : appState === 'processing'
              ? 'Processing...'
              : 'No document loaded'
          }
        </span>
        <div className="flex gap-1.5 items-center shrink-0">
          {hasProject && (
            <>
              <button
                className="bg-white/10 border-none text-white px-2 py-1 rounded text-xs cursor-pointer hover:bg-white/20 disabled:opacity-30"
                onClick={zoomOut}
                disabled={zoom <= MIN_ZOOM}
                title="Zoom out"
              >
                &minus;
              </button>
              <button
                className="bg-white/10 border-none text-white px-2 py-1 rounded text-[10px] cursor-pointer hover:bg-white/20 min-w-[44px] text-center"
                onClick={zoomReset}
                title="Reset zoom"
              >
                {zoomPercent}%
              </button>
              <button
                className="bg-white/10 border-none text-white px-2 py-1 rounded text-xs cursor-pointer hover:bg-white/20 disabled:opacity-30"
                onClick={zoomIn}
                disabled={zoom >= MAX_ZOOM}
                title="Zoom in"
              >
                +
              </button>
              <div className="w-px h-4 bg-white/20 mx-1" />
            </>
          )}
          {canNavigate && (
            <>
              <button
                className="bg-white/10 border-none text-white px-2.5 py-1 rounded text-xs cursor-pointer hover:bg-white/20 disabled:opacity-30"
                onClick={goToPrev}
                disabled={currentPage <= 1}
              >
                &#9664;
              </button>
              <button
                className="bg-white/10 border-none text-white px-2.5 py-1 rounded text-xs cursor-pointer hover:bg-white/20 disabled:opacity-30"
                onClick={goToNext}
                disabled={currentPage >= totalPages}
              >
                &#9654;
              </button>
            </>
          )}
        </div>
      </div>

      <div
        ref={measuredRef}
        className="flex-1 overflow-auto p-4"
        onWheel={handleWheel}
        style={{ cursor: zoom > 1 ? 'grab' : 'default' }}
      >
        <div
          className="flex items-center justify-center"
          style={{ minHeight: '100%', minWidth: '100%' }}
        >
          {pdfUrl && !pdfError ? (
            <Document
              file={pdfUrl}
              onLoadSuccess={onDocumentLoadSuccess}
              onLoadError={onDocumentLoadError}
              loading={
                <div className="text-center text-slate-500">
                  <div className="w-12 h-12 border-4 border-accent/30 border-t-accent rounded-full animate-spin mx-auto mb-4" />
                  <p className="text-sm">Loading PDF...</p>
                </div>
              }
            >
              <Page
                pageNumber={currentPage}
                width={pageWidth}
                renderTextLayer={true}
                renderAnnotationLayer={true}
                loading={
                  <div className="text-slate-500 text-sm">Rendering page...</div>
                }
              />
            </Document>
          ) : hasProject && pdfError ? (
            /* Fallback to image-based rendering for folder projects */
            <img
              src={getPageImageUrl(projectId, currentPage, 300)}
              alt={`Page ${currentPage}`}
              className="object-contain rounded shadow-lg transition-transform duration-150"
              style={{
                width: `${zoom * 100}%`,
                maxWidth: 'none',
              }}
              draggable={false}
              onError={() => {}}
            />
          ) : appState === 'processing' ? (
            <div className="text-center text-slate-500">
              <div className="w-12 h-12 border-4 border-accent/30 border-t-accent rounded-full animate-spin mx-auto mb-4" />
              <p className="text-sm">Pipeline running...</p>
              <p className="text-xs mt-1 text-slate-600">Check agent progress in the center panel</p>
            </div>
          ) : (
            <div className="text-center text-slate-500">
              <svg viewBox="0 0 64 64" fill="none" stroke="#64748b" strokeWidth="1.5" className="w-16 h-16 mx-auto mb-4 opacity-30">
                <rect x="8" y="4" width="48" height="56" rx="4" />
                <path d="M20 18h24M20 26h24M20 34h16" />
              </svg>
              <p className="text-sm">PDF viewer available in live mode</p>
              <p className="text-xs mt-1 text-slate-600">Demo mode shows data only</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
