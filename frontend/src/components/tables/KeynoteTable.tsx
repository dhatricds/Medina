import { useProjectStore } from '../../store/projectStore';
import EditableCell from './EditableCell';

export default function KeynoteTable() {
  const { projectData, updateKeynoteCount, addCorrection } = useProjectStore();
  if (!projectData) return null;

  const plans = projectData.lighting_plans;

  const handleCountChange = (keynoteNumber: string, plan: string, original: number, newCount: number) => {
    updateKeynoteCount(keynoteNumber, plan, newCount);
    addCorrection({ type: 'keynote', identifier: keynoteNumber, sheet: plan, original, corrected: newCount });
  };

  // Group keynotes by plan — only show keynotes that appear on each plan (count > 0)
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
                  return (
                    <tr key={kn.keynote_number} className="hover:bg-slate-100 group">
                      <td className="px-3.5 py-2 text-left font-bold text-primary bg-slate-50 border-b border-r border-border group-hover:bg-blue-50">
                        {kn.keynote_number}
                      </td>
                      <td className="px-3.5 py-2 text-left text-[12px] text-text-main leading-snug border-b border-r border-border group-hover:bg-slate-50">
                        {kn.keynote_text}
                      </td>
                      <EditableCell
                        value={count}
                        onChange={(newVal) => handleCountChange(kn.keynote_number, plan, count, newVal)}
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
    </div>
  );
}
