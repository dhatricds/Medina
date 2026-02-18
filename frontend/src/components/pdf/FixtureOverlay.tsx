import { useProjectStore } from '../../store/projectStore';

interface Props {
  renderedWidth: number;
  renderedHeight: number;
}

export default function FixtureOverlay({ renderedWidth, renderedHeight }: Props) {
  const { highlight, clearHighlight, toggleMarker } = useProjectStore();
  const { fixtureCode, keynoteNumber, positions, pageWidth, pageHeight, loading, rejectedIndices } = highlight;

  const hasTarget = fixtureCode || keynoteNumber;
  if (!hasTarget) return null;

  const label = fixtureCode ?? `#${keynoteNumber}`;
  const isKeynote = !!keynoteNumber;

  // Loading state
  if (loading) {
    return (
      <div
        className="absolute inset-0 z-20 flex items-center justify-center"
        style={{ pointerEvents: 'none' }}
      >
        <div className="bg-black/60 text-white px-3 py-1.5 rounded text-xs animate-pulse">
          Locating {label}...
        </div>
      </div>
    );
  }

  // No positions available (VLM-counted or old project)
  if (positions.length === 0 && !loading) {
    return (
      <div
        className="absolute inset-0 z-20 cursor-pointer"
        onClick={clearHighlight}
      >
        <div className="absolute top-3 left-1/2 -translate-x-1/2 bg-amber-600/90 text-white px-3 py-1.5 rounded text-xs shadow-lg">
          Positions not available for {label} (AI vision counted)
        </div>
      </div>
    );
  }

  if (!pageWidth || !pageHeight || !renderedWidth || !renderedHeight) return null;

  const scaleX = renderedWidth / pageWidth;
  const scaleY = renderedHeight / pageHeight;

  const acceptedCount = positions.length - rejectedIndices.size;

  return (
    <div
      className="absolute inset-0 z-20"
      onClick={(e) => {
        // Only dismiss when clicking the background, not a marker
        if (e.target === e.currentTarget) clearHighlight();
      }}
    >
      {/* Count badge */}
      <div className={`absolute top-3 left-1/2 -translate-x-1/2 ${isKeynote ? 'bg-amber-500' : 'bg-red-600'} text-white px-3 py-1 rounded-full text-xs font-semibold shadow-lg z-30 pointer-events-none select-none`}>
        {label}: {acceptedCount}/{positions.length} accepted
      </div>

      {/* Hint */}
      <div className="absolute top-10 left-1/2 -translate-x-1/2 bg-black/50 text-white/80 px-2 py-0.5 rounded text-[10px] z-30 pointer-events-none select-none whitespace-nowrap">
        Click marker to reject/accept &middot; Click background to dismiss
      </div>

      {/* Position markers */}
      {positions.map((pos, i) => {
        const left = pos.x0 * scaleX;
        const top = pos.top * scaleY;
        const width = (pos.x1 - pos.x0) * scaleX;
        const height = (pos.bottom - pos.top) * scaleY;
        const pad = Math.max(4, Math.min(width, height) * 0.5);
        const rejected = rejectedIndices.has(i);

        const borderColor = rejected
          ? 'border-gray-400'
          : isKeynote ? 'border-amber-400' : 'border-red-500';
        const bgColor = rejected
          ? 'bg-gray-400/10'
          : isKeynote ? 'bg-amber-400/20' : 'bg-red-500/20';

        return (
          <div
            key={i}
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
            {/* X mark for rejected markers */}
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
    </div>
  );
}
