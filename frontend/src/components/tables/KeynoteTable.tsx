import { useState } from 'react';
import { useProjectStore } from '../../store/projectStore';
import { submitFeedback } from '../../api/client';
import EditableCell from './EditableCell';

export default function KeynoteTable() {
  const { projectData, updateKeynoteCount, addCorrection, highlightKeynote, projectId, removeKeynoteFeedback } = useProjectStore();
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null); // "keynoteNumber_plan"
  if (!projectData) return null;

  const canHighlight = !!projectId;

  const plans = projectData.lighting_plans;

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

  const handleDelete = (keynoteNumber: string, plan: string) => {
    const key = `${keynoteNumber}_${plan}`;
    if (confirmDelete === key) {
      // Second click — actually delete
      removeKeynoteFeedback(keynoteNumber, plan);
      setConfirmDelete(null);
    } else {
      // First click — ask for confirmation
      setConfirmDelete(key);
      // Auto-reset after 3 seconds
      setTimeout(() => setConfirmDelete((cur) => cur === key ? null : cur), 3000);
    }
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
                  <th className="bg-[#162d4a] text-white px-2 py-2 text-center font-semibold text-xs w-[40px]">
                  </th>
                </tr>
              </thead>
              <tbody>
                {keynotes.map((kn) => {
                  const count = kn.counts_per_plan[plan] ?? 0;
                  const deleteKey = `${kn.keynote_number}_${plan}`;
                  const isConfirming = confirmDelete === deleteKey;
                  return (
                    <tr key={kn.keynote_number} className="hover:bg-slate-100 group">
                      <td
                        className={`px-3.5 py-2 text-left font-bold text-primary bg-slate-50 border-b border-r border-border group-hover:bg-blue-50 ${
                          canHighlight ? 'cursor-pointer hover:text-amber-600 hover:underline' : ''
                        }`}
                        onClick={canHighlight ? () => highlightKeynote(kn.keynote_number, plan) : undefined}
                        title={canHighlight ? `Click to locate keynote #${kn.keynote_number} on ${plan}` : undefined}
                      >
                        {kn.keynote_number}
                      </td>
                      <td className="px-3.5 py-2 text-left text-[12px] text-text-main leading-snug border-b border-r border-border group-hover:bg-slate-50">
                        {kn.keynote_text}
                      </td>
                      <EditableCell
                        value={count}
                        onChange={(newVal) => handleCountChange(kn.keynote_number, plan, count, newVal)}
                        onLocate={canHighlight && count > 0 ? () => highlightKeynote(kn.keynote_number, plan) : undefined}
                      />
                      <td className="px-1 py-2 text-center border-b border-border">
                        <button
                          className={`p-1 rounded transition-colors cursor-pointer ${
                            isConfirming
                              ? 'bg-red-500 text-white hover:bg-red-600'
                              : 'text-text-light hover:text-red-500 hover:bg-red-50'
                          }`}
                          onClick={() => handleDelete(String(kn.keynote_number), plan)}
                          title={isConfirming ? 'Click again to confirm delete' : 'Delete this keynote (false detection)'}
                        >
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <polyline points="3 6 5 6 21 6" />
                            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                          </svg>
                        </button>
                      </td>
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
    </div>
  );
}
