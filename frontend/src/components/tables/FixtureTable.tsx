import { useState } from 'react';
import { useProjectStore } from '../../store/projectStore';
import { submitFeedback } from '../../api/client';
import EditableCell from './EditableCell';
import ReasonModal from './ReasonModal';

const SPEC_COLUMNS = [
  { key: 'description', label: 'Description' },
] as const;

export default function FixtureTable() {
  const { projectData, updateFixtureCount, addCorrection, highlightFixture, navigateToSchedule, projectId, removeFixtureFeedback, feedbackItems } = useProjectStore();
  const reprocessDiffs = useProjectStore((s) => s.reprocessDiffs);
  const clearReprocessDiffs = useProjectStore((s) => s.clearReprocessDiffs);
  const [removeTarget, setRemoveTarget] = useState<string | null>(null);

  if (!projectData) return null;

  const canHighlight = !!projectId;

  // Check if a fixture was added via feedback
  const feedbackCodes = new Set(
    feedbackItems
      .filter((f) => f.action === 'add')
      .map((f) => f.fixture_code)
  );

  const plans = projectData.lighting_plans;

  // Count total diffs
  const hasDiffs = Object.keys(reprocessDiffs).length > 0;
  let totalChanges = 0;
  let increases = 0;
  let decreases = 0;
  if (hasDiffs) {
    for (const code of Object.keys(reprocessDiffs)) {
      for (const plan of Object.keys(reprocessDiffs[code])) {
        totalChanges++;
        const oldCount = reprocessDiffs[code][plan];
        const fixture = projectData.fixtures.find((f) => f.code === code);
        const newCount = fixture?.counts_per_plan[plan] ?? 0;
        if (newCount > oldCount) increases++;
        else if (newCount < oldCount) decreases++;
      }
    }
  }

  const handleCountChange = (code: string, plan: string, original: number, newCount: number) => {
    updateFixtureCount(code, plan, newCount);
    addCorrection({ type: 'lighting', identifier: code, sheet: plan, original, corrected: newCount });
    // Fire-and-forget: persist feedback without async store set() calls
    if (projectId) {
      submitFeedback(projectId, {
        action: 'count_override',
        fixture_code: code,
        reason: 'manual_count_edit',
        reason_detail: `Manual edit: ${original} -> ${newCount} on ${plan}`,
        fixture_data: { sheet: plan, corrected: newCount, original },
      }).then(() => {
        useProjectStore.setState((s) => ({ feedbackCount: s.feedbackCount + 1 }));
      }).catch(() => {});
    }
  };

  return (
    <div className="flex-1 overflow-auto">
      {/* Diff summary banner */}
      {hasDiffs && (
        <div className="flex items-center justify-between px-3 py-2 bg-amber-50 border-b border-amber-200 text-sm">
          <span className="text-amber-800">
            VLM recount: <strong>{totalChanges} count{totalChanges !== 1 ? 's' : ''} changed</strong>
            {increases > 0 && <span className="ml-2 text-green-700">+{increases} up</span>}
            {decreases > 0 && <span className="ml-2 text-red-700">{decreases} down</span>}
          </span>
          <button
            onClick={clearReprocessDiffs}
            className="text-xs text-amber-600 hover:text-amber-800 underline"
          >
            Dismiss
          </button>
        </div>
      )}
      <table className="w-full border-collapse text-[13px]">
        <thead className="sticky top-0 z-10">
          <tr>
            <th className="bg-primary text-white px-3.5 py-2.5 text-left font-semibold text-xs border-r border-white/10 whitespace-nowrap min-w-[60px]">
              Type
            </th>
            {SPEC_COLUMNS.map((col) => (
              <th key={col.key} className="bg-primary text-white px-3.5 py-2.5 text-left font-semibold text-xs border-r border-white/10 whitespace-nowrap">
                {col.label}
              </th>
            ))}
            {plans.map((plan) => (
              <th key={plan} className="bg-primary text-white px-3.5 py-2.5 text-center font-semibold text-xs border-r border-white/10 whitespace-nowrap">
                {plan}
              </th>
            ))}
            <th className="bg-[#162d4a] text-white px-3.5 py-2.5 text-center font-semibold text-xs whitespace-nowrap">
              Total
            </th>
          </tr>
        </thead>
        <tbody>
          {projectData.fixtures.map((fixture) => (
            <tr key={fixture.code} className={`hover:bg-slate-100 group ${feedbackCodes.has(fixture.code) ? 'border-l-2 border-l-blue-400' : ''}`}>
              <td
                className={`px-3.5 py-2 text-left font-bold text-primary bg-slate-50 sticky left-0 z-[5] border-b border-r border-border group-hover:bg-blue-50 whitespace-nowrap ${
                  (fixture.schedule_page || projectData.schedule_pages?.length) ? 'cursor-pointer hover:text-accent hover:underline' : ''
                }`}
                onClick={(fixture.schedule_page || projectData.schedule_pages?.length) ? () => navigateToSchedule(fixture.code) : undefined}
                title={(fixture.schedule_page || projectData.schedule_pages?.length) ? `View ${fixture.code} definition on schedule (${fixture.schedule_page || projectData.schedule_pages[0]})` : undefined}
              >
                <span className="flex items-center gap-1.5">
                  <button
                    className="opacity-0 group-hover:opacity-100 text-red-400 hover:text-error transition-all cursor-pointer flex-shrink-0"
                    onClick={(e) => { e.stopPropagation(); setRemoveTarget(fixture.code); }}
                    title={`Remove ${fixture.code}`}
                  >
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <polyline points="3 6 5 6 21 6" />
                      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                    </svg>
                  </button>
                  <span>{fixture.code}</span>
                  {feedbackCodes.has(fixture.code) && (
                    <span className="text-[9px] bg-blue-100 text-blue-700 px-1 py-px rounded font-semibold">NEW</span>
                  )}
                </span>
              </td>
              {SPEC_COLUMNS.map((col) => {
                const value = fixture[col.key] || '';
                return (
                  <td
                    key={col.key}
                    className="px-3.5 py-2 text-left text-xs border-b border-r border-border max-w-[200px] truncate"
                    title={value}
                  >
                    {value}
                  </td>
                );
              })}
              {plans.map((plan) => {
                const count = fixture.counts_per_plan[plan] ?? 0;
                const prevCount = reprocessDiffs[fixture.code]?.[plan];
                return (
                  <EditableCell
                    key={plan}
                    value={count}
                    onChange={(newVal) => handleCountChange(fixture.code, plan, count, newVal)}
                    onLocate={canHighlight && count > 0 ? () => highlightFixture(fixture.code, plan) : undefined}
                    previousCount={prevCount}
                  />
                );
              })}
              <td className="px-3.5 py-2 text-center font-bold bg-sky-50 border-b border-border group-hover:bg-sky-100">
                {fixture.total}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {removeTarget && (
        <ReasonModal
          fixtureCode={removeTarget}
          onSubmit={(reason, detail) => removeFixtureFeedback(removeTarget, reason, detail)}
          onClose={() => setRemoveTarget(null)}
        />
      )}
    </div>
  );
}
