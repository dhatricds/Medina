import { useProjectStore } from '../../store/projectStore';

export default function ReviewSidebar() {
  const {
    reviewPlans,
    reviewedCount,
    reviewTotal,
    reviewSidebarOpen,
    setReviewSidebarOpen,
    togglePlanReview,
    projectData,
    setCurrentPage,
    clearHighlight,
  } = useProjectStore();

  if (!reviewSidebarOpen || reviewTotal === 0) return null;

  const progress = reviewTotal > 0 ? Math.round((reviewedCount / reviewTotal) * 100) : 0;

  const navigateToPlan = (sheetCode: string) => {
    // Find the page number for this sheet code
    const pages = projectData?.pages ?? [];
    const viewportMap = projectData?.viewport_map;

    // Check viewport_map first (for composite viewport keys like E601-L1)
    if (viewportMap && viewportMap[sheetCode]) {
      clearHighlight();
      setCurrentPage(viewportMap[sheetCode]);
      return;
    }

    // Find by sheet_code in pages
    const page = pages.find(p => p.sheet_code === sheetCode);
    if (page) {
      clearHighlight();
      setCurrentPage(page.page_number);
    }
  };

  return (
    <div className="border-b border-border bg-card">
      {/* Header */}
      <div className="px-4 py-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-text-main">Review Progress</span>
          <span className="text-[10px] bg-primary/10 text-primary px-1.5 py-0.5 rounded-full font-medium">
            {reviewedCount}/{reviewTotal}
          </span>
        </div>
        <button
          className="text-text-light hover:text-text-main text-xs cursor-pointer"
          onClick={() => setReviewSidebarOpen(false)}
          title="Close review panel"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M18 6L6 18M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Progress bar */}
      <div className="px-4 pb-2">
        <div className="h-1.5 bg-border rounded-full overflow-hidden">
          <div
            className="h-full bg-green-500 rounded-full transition-all duration-300"
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>

      {/* Plan list */}
      <div className="px-2 pb-2 max-h-48 overflow-y-auto">
        {reviewPlans.map((plan) => {
          const isReviewed = plan.status === 'reviewed';
          const isSchedule = plan.type === 'schedule';

          return (
            <div
              key={plan.sheet_code}
              className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-bg group"
            >
              {/* Review checkbox */}
              <button
                className={`w-4 h-4 rounded border flex items-center justify-center shrink-0 cursor-pointer transition-all ${
                  isReviewed
                    ? 'bg-green-500 border-green-500 text-white'
                    : 'border-slate-300 hover:border-green-400'
                }`}
                onClick={() => togglePlanReview(plan.sheet_code)}
                title={isReviewed ? 'Mark as not reviewed' : 'Mark as reviewed'}
              >
                {isReviewed && (
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
                    <path d="M20 6L9 17l-5-5" />
                  </svg>
                )}
              </button>

              {/* Plan info — clickable to navigate */}
              <button
                className="flex-1 text-left text-xs cursor-pointer hover:text-primary transition-colors truncate"
                onClick={() => navigateToPlan(plan.sheet_code)}
                title={`Navigate to ${plan.sheet_code}`}
              >
                <span className={`font-medium ${isReviewed ? 'text-text-light line-through' : 'text-text-main'}`}>
                  {isSchedule ? '  ' : '  '}
                  {plan.sheet_code}
                </span>
              </button>

              {/* Corrections badge */}
              {plan.corrections_count > 0 && (
                <span className="text-[9px] bg-amber-100 text-amber-700 px-1 py-px rounded font-medium shrink-0">
                  {plan.corrections_count}
                </span>
              )}

              {/* Reviewer info */}
              {isReviewed && plan.reviewed_by_name && (
                <span className="text-[9px] text-text-light shrink-0 hidden group-hover:inline">
                  {plan.reviewed_by_name}
                </span>
              )}
            </div>
          );
        })}
      </div>

      {/* All reviewed message */}
      {reviewedCount === reviewTotal && reviewTotal > 0 && (
        <div className="px-4 pb-2">
          <div className="text-[10px] text-green-600 font-medium text-center bg-green-50 rounded py-1">
            All plans reviewed — ready to approve
          </div>
        </div>
      )}
    </div>
  );
}
