import { useCallback } from 'react';
import { useProjectStore } from '../../store/projectStore';

interface Props {
  renderedWidth: number;
  renderedHeight: number;
}

export default function FixtureOverlay({ renderedWidth, renderedHeight }: Props) {
  const { highlight, clearHighlight, toggleMarker, addMarkerAtPosition, removeAddedMarker } = useProjectStore();
  const { fixtureCode, keynoteNumber, positions, pageWidth, pageHeight, loading, rejectedIndices, addedPositions, addMode } = highlight;

  const hasTarget = fixtureCode || keynoteNumber;
  if (!hasTarget) return null;

  const isKeynote = !!keynoteNumber;

  // Handle background click: add marker in add mode, dismiss otherwise
  const handleBackgroundClick = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    if (e.target !== e.currentTarget) return;
    if (addMode && pageWidth && pageHeight && renderedWidth && renderedHeight) {
      const rect = e.currentTarget.getBoundingClientRect();
      const clickX = e.clientX - rect.left;
      const clickY = e.clientY - rect.top;
      const pdfX = clickX / (renderedWidth / pageWidth);
      const pdfY = clickY / (renderedHeight / pageHeight);
      addMarkerAtPosition(pdfX, pdfY);
    } else {
      clearHighlight();
    }
  }, [addMode, pageWidth, pageHeight, renderedWidth, renderedHeight, addMarkerAtPosition, clearHighlight]);

  // Loading state
  if (loading) {
    return (
      <div
        className="absolute inset-0 z-20 flex items-center justify-center"
        style={{ pointerEvents: 'none' }}
      >
        <div className="bg-black/60 text-white px-3 py-1.5 rounded text-xs animate-pulse">
          Locating {fixtureCode ?? `#${keynoteNumber}`}...
        </div>
      </div>
    );
  }

  // No positions — just a click-to-dismiss overlay (controls shown in PdfViewer's sticky bar)
  if (positions.length === 0 && addedPositions.length === 0 && !loading) {
    return (
      <div
        className="absolute inset-0 z-20 cursor-pointer"
        onClick={clearHighlight}
      />
    );
  }

  if (!pageWidth || !pageHeight || !renderedWidth || !renderedHeight) return null;

  const scaleX = renderedWidth / pageWidth;
  const scaleY = renderedHeight / pageHeight;

  return (
    <div
      className="absolute inset-0 z-20"
      onClick={handleBackgroundClick}
      style={{ cursor: addMode ? 'crosshair' : 'default' }}
    >
      {/* Pipeline-detected position markers */}
      {positions.map((pos, i) => {
        const left = pos.x0 * scaleX;
        const top = pos.top * scaleY;
        const width = (pos.x1 - pos.x0) * scaleX;
        const height = (pos.bottom - pos.top) * scaleY;
        const pad = Math.max(4, Math.min(width, height) * 0.5);
        const rejected = rejectedIndices.has(i);

        const borderColor = rejected
          ? 'border-gray-400'
          : isKeynote ? 'border-blue-500' : 'border-red-500';
        const bgColor = rejected
          ? 'bg-gray-400/10'
          : isKeynote ? 'bg-blue-500/25' : 'bg-red-500/20';

        return (
          <div
            key={`p-${i}`}
            className={`absolute border-2 ${borderColor} ${bgColor} rounded-sm cursor-pointer transition-all duration-150 ${rejected ? 'opacity-50' : 'animate-pulse hover:ring-2 hover:ring-white/60'}`}
            style={{
              left: left - pad,
              top: top - pad,
              width: width + pad * 2,
              height: height + pad * 2,
            }}
            onClick={(e) => {
              e.stopPropagation();
              toggleMarker(i);
            }}
            title={rejected ? 'Click to re-accept this marker' : 'Click to reject this marker'}
          >
            {rejected && (
              <svg
                className="absolute inset-0 w-full h-full text-red-500/70 pointer-events-none"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth={3}
              >
                <line x1="4" y1="4" x2="20" y2="20" />
                <line x1="20" y1="4" x2="4" y2="20" />
              </svg>
            )}
          </div>
        );
      })}

      {/* User-added markers (green) */}
      {addedPositions.map((pos, i) => {
        const left = pos.x0 * scaleX;
        const top = pos.top * scaleY;
        const width = (pos.x1 - pos.x0) * scaleX;
        const height = (pos.bottom - pos.top) * scaleY;
        const pad = Math.max(4, Math.min(width, height) * 0.5);

        return (
          <div
            key={`a-${i}`}
            className="absolute border-2 border-green-500 bg-green-500/25 rounded-sm cursor-pointer animate-pulse hover:ring-2 hover:ring-white/60"
            style={{
              left: left - pad,
              top: top - pad,
              width: width + pad * 2,
              height: height + pad * 2,
            }}
            onClick={(e) => {
              e.stopPropagation();
              removeAddedMarker(i);
            }}
            title="User-added marker (click to remove)"
          >
            {/* + icon */}
            <svg
              className="absolute inset-0 w-full h-full text-green-600/70 pointer-events-none"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth={3}
            >
              <line x1="12" y1="5" x2="12" y2="19" />
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
          </div>
        );
      })}
    </div>
  );
}
