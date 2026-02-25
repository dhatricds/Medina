import { useState } from 'react';
import { useProjectStore } from '../../store/projectStore';
import { submitFeedback } from '../../api/client';
import EditableCell from './EditableCell';
import ReasonModal from './ReasonModal';

export default function KeynoteTable() {
  const { projectData, updateKeynoteCount, addCorrection, highlightKeynote, projectId, feedbackItems } = useProjectStore();
  const [removeTarget, setRemoveTarget] = useState<string | null>(null);

  if (!projectData) return null;

  const canHighlight = !!projectId;

  const plans = projectData.lighting_plans;

  // Track which keynotes were user-added via feedback
  const addedKeynoteNumbers = new Set(
    feedbackItems
      .filter((f) => f.action === 'keynote_add')
      .map((f) => {
        const kn = f.fixture_data?.keynote_number;
        return kn ? String(kn) : f.fixture_code.replace('KN-', '');
      })
  );

  const handleCountChange = (keynoteNumber: string, plan: string, original: number, newCount: number) => {
    updateKeynoteCount(keynoteNumber, plan, newCount);
    addCorrection({ type: 'keynote', identifier: keynoteNumber, sheet: plan, original, corrected: newCount });
    // Persist keynote correction to backend (fire-and-forget)
    if (projectId) {
      submitFeedback(projectId, {
        action: 'keynote_count_override',
        fixture_code: `KN-${keynoteNumber}`,
        reason: 'manual_count_edit',
        reason_detail: `Keynote #${keynoteNumber} on ${plan}: ${original} -> ${newCount}`,
        fixture_data: { sheet: plan, corrected: newCount, original, keynote_number: keynoteNumber },
      }).then(() => {
        useProjectStore.setState((s) => ({ feedbackCount: s.feedbackCount + 1 }));
      }).catch(() => {});
    }
  };

  const handleRemoveKeynote = (keynoteNumber: string, reason: string, detail: string) => {
    if (!projectId) return;

    // Remove from local state
    useProjectStore.setState((s) => {
      if (!s.projectData) return {};
      const filtered = s.projectData.keynotes.filter(
        (k) => String(k.keynote_number) !== String(keynoteNumber)
      );
      return {
        projectData: {
          ...s.projectData,
          keynotes: filtered,
          summary: {
            ...s.projectData.summary,
            total_keynotes: Math.max(0, s.projectData.summary.total_keynotes - 1),
          },
        },
      };
    });

    // Submit feedback to backend (fire-and-forget)
    submitFeedback(projectId, {
      action: 'keynote_remove',
      fixture_code: `KN-${keynoteNumber}`,
      reason: reason as any,
      reason_detail: detail || `Removed keynote #${keynoteNumber}`,
      fixture_data: { keynote_number: keynoteNumber },
    }).then(() => {
      useProjectStore.setState((s) => ({ feedbackCount: s.feedbackCount + 1 }));
    }).catch(() => {});
  };

  // Group keynotes by plan — show only keynotes with count > 0
  const keynotesByPlan = plans.map((plan) => {
    const planKeynotes = projectData.keynotes.filter(
      (kn) => (kn.counts_per_plan[plan] ?? 0) > 0
    );
    return { plan, keynotes: planKeynotes };
  });

  return (
    <div className="flex-1 overflow-auto p-4 space-y-6">
      {keynotesByPlan.map(({ plan, keynotes }) => (
        <div key={plan}>
          <h3 className="text-sm font-semibold text-primary mb-2 px-1">
            {plan}
            <span className="text-text-light font-normal ml-2 text-xs">
              {keynotes.length} keynote{keynotes.length !== 1 ? 's' : ''}
            </span>
          </h3>
          {keynotes.length === 0 ? (
            <p className="text-xs text-text-light px-1">No keynotes found on this plan.</p>
          ) : (
            <table className="w-full border-collapse text-[13px] rounded overflow-hidden">
              <thead>
                <tr>
                  <th className="bg-primary text-white px-3.5 py-2 text-left font-semibold text-xs border-r border-white/10 w-[60px]">
                    #
                  </th>
                  <th className="bg-primary text-white px-3.5 py-2 text-left font-semibold text-xs border-r border-white/10">
                    Key Note
                  </th>
                  <th className="bg-[#162d4a] text-white px-3.5 py-2 text-center font-semibold text-xs w-[80px]">
                    Count
                  </th>
                </tr>
              </thead>
              <tbody>
                {keynotes.map((kn) => {
                  const count = kn.counts_per_plan[plan] ?? 0;
                  const isUserAdded = addedKeynoteNumbers.has(String(kn.keynote_number));
                  return (
                    <tr key={kn.keynote_number} className={`hover:bg-slate-100 group ${isUserAdded ? 'border-l-2 border-l-blue-400' : ''}`}>
                      <td
                        className={`px-3.5 py-2 text-left font-bold text-primary bg-slate-50 border-b border-r border-border group-hover:bg-blue-50 ${
                          canHighlight ? 'cursor-pointer hover:text-amber-600 hover:underline' : ''
                        }`}
                        onClick={canHighlight ? () => highlightKeynote(kn.keynote_number, plan) : undefined}
                        title={canHighlight ? `Click to locate keynote #${kn.keynote_number} on ${plan}` : undefined}
                      >
                        <span className="flex items-center gap-1.5">
                          <button
                            className="opacity-0 group-hover:opacity-100 text-red-400 hover:text-error transition-all cursor-pointer flex-shrink-0"
                            onClick={(e) => { e.stopPropagation(); setRemoveTarget(String(kn.keynote_number)); }}
                            title={`Remove keynote #${kn.keynote_number}`}
                          >
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                              <polyline points="3 6 5 6 21 6" />
                              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                            </svg>
                          </button>
                          <span>{kn.keynote_number}</span>
                          {isUserAdded && (
                            <span className="text-[9px] bg-blue-100 text-blue-700 px-1 py-px rounded font-semibold">NEW</span>
                          )}
                        </span>
                      </td>
                      <td className="px-3.5 py-2 text-left text-[12px] text-text-main leading-snug border-b border-r border-border group-hover:bg-slate-50">
                        {kn.keynote_text}
                      </td>
                      <EditableCell
                        value={count}
                        onChange={(newVal) => handleCountChange(kn.keynote_number, plan, count, newVal)}
                        onLocate={canHighlight && count > 0 ? () => highlightKeynote(kn.keynote_number, plan) : undefined}
                      />
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      ))}
      {keynotesByPlan.every(({ keynotes }) => keynotes.length === 0) && (
        <p className="text-sm text-text-light text-center py-4">No keynotes found on any plan.</p>
      )}

      {removeTarget && (
        <ReasonModal
          fixtureCode={`Keynote #${removeTarget}`}
          onSubmit={(reason, detail) => handleRemoveKeynote(removeTarget, reason, detail)}
          onClose={() => setRemoveTarget(null)}
        />
      )}
    </div>
  );
}
