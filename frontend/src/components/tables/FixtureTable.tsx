import { useProjectStore } from '../../store/projectStore';
import EditableCell from './EditableCell';

const SPEC_COLUMNS = [
  { key: 'description', label: 'Description' },
] as const;

export default function FixtureTable() {
  const { projectData, updateFixtureCount, addCorrection } = useProjectStore();
  if (!projectData) return null;

  const plans = projectData.lighting_plans;

  const handleCountChange = (code: string, plan: string, original: number, newCount: number) => {
    updateFixtureCount(code, plan, newCount);
    addCorrection({ type: 'lighting', identifier: code, sheet: plan, original, corrected: newCount });
  };

  return (
    <div className="flex-1 overflow-auto">
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
            <tr key={fixture.code} className="hover:bg-slate-100 group">
              <td className="px-3.5 py-2 text-left font-bold text-primary bg-slate-50 sticky left-0 z-[5] border-b border-r border-border group-hover:bg-blue-50 whitespace-nowrap">
                {fixture.code}
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
                return (
                  <EditableCell
                    key={plan}
                    value={count}
                    onChange={(newVal) => handleCountChange(fixture.code, plan, count, newVal)}
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
    </div>
  );
}
