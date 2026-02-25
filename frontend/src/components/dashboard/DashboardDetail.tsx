import { useProjectStore } from '../../store/projectStore';

export default function DashboardDetail() {
  const { dashboardDetail, dashboardDetailId, closeDashboardDetail, downloadDashboardExcel } = useProjectStore();

  if (!dashboardDetail || !dashboardDetailId) return null;

  const data = dashboardDetail;
  const plans = data.lighting_plans ?? [];
  const qa = data.qa_report;

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* Header */}
      <div className="bg-card border-b border-border px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <button
            className="w-8 h-8 rounded-md flex items-center justify-center hover:bg-bg transition-all cursor-pointer"
            onClick={closeDashboardDetail}
            title="Back to dashboard"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="15 18 9 12 15 6" />
            </svg>
          </button>
          <div>
            <h2 className="text-base font-bold text-text-main">{data.project_name}</h2>
            <div className="flex items-center gap-4 mt-0.5 text-xs text-text-light">
              <span>{data.summary.total_fixture_types} fixture types</span>
              <span>{data.summary.total_fixtures} total fixtures</span>
              <span>{data.summary.total_keynotes} keynotes</span>
              <span>{plans.length} plan{plans.length !== 1 ? 's' : ''}</span>
              {qa && (
                <span className={`font-semibold ${qa.passed ? 'text-green-700' : 'text-amber-700'}`}>
                  QA: {Math.round(qa.overall_confidence * 100)}%
                </span>
              )}
            </div>
          </div>
        </div>
        <button
          className="px-4 py-2 rounded-md text-[13px] font-semibold flex items-center gap-1.5 bg-success text-white hover:bg-green-600 transition-all cursor-pointer"
          onClick={() => downloadDashboardExcel(dashboardDetailId)}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="7 10 12 15 17 10" />
            <line x1="12" y1="15" x2="12" y2="3" />
          </svg>
          Download Excel
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto">
        {/* Fixture Table */}
        {data.fixtures.length > 0 && (
          <div className="p-6">
            <h3 className="text-sm font-bold text-text-main mb-3">
              Fixture Inventory
              <span className="bg-primary text-white text-[10px] px-1.5 py-px rounded-full ml-2">
                {data.fixtures.length}
              </span>
            </h3>
            <div className="overflow-auto border border-border rounded-lg">
              <table className="w-full border-collapse text-[13px]">
                <thead className="sticky top-0 z-10">
                  <tr>
                    <th className="bg-primary text-white px-3.5 py-2.5 text-left font-semibold text-xs border-r border-white/10 whitespace-nowrap">Type</th>
                    <th className="bg-primary text-white px-3.5 py-2.5 text-left font-semibold text-xs border-r border-white/10 whitespace-nowrap">Description</th>
                    {plans.map((plan) => (
                      <th key={plan} className="bg-primary text-white px-3.5 py-2.5 text-center font-semibold text-xs border-r border-white/10 whitespace-nowrap">
                        {plan}
                      </th>
                    ))}
                    <th className="bg-[#162d4a] text-white px-3.5 py-2.5 text-center font-semibold text-xs whitespace-nowrap">Total</th>
                  </tr>
                </thead>
                <tbody>
                  {data.fixtures.map((fixture) => (
                    <tr key={fixture.code} className="hover:bg-slate-50">
                      <td className="px-3.5 py-2 text-left font-bold text-primary bg-slate-50 border-b border-r border-border whitespace-nowrap">
                        {fixture.code}
                      </td>
                      <td className="px-3.5 py-2 text-left text-xs border-b border-r border-border max-w-[200px] truncate" title={fixture.description}>
                        {fixture.description}
                      </td>
                      {plans.map((plan) => (
                        <td key={plan} className="px-3.5 py-2 text-center border-b border-r border-border tabular-nums">
                          {fixture.counts_per_plan[plan] ?? 0}
                        </td>
                      ))}
                      <td className="px-3.5 py-2 text-center font-bold bg-sky-50 border-b border-border">
                        {fixture.total}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Keynote Tables */}
        {data.keynotes.length > 0 && (
          <div className="px-6 pb-6">
            <h3 className="text-sm font-bold text-text-main mb-3">
              Key Notes
              <span className="bg-primary text-white text-[10px] px-1.5 py-px rounded-full ml-2">
                {data.keynotes.length}
              </span>
            </h3>
            <div className="space-y-4">
              {plans.map((plan) => {
                const planKeynotes = data.keynotes.filter(
                  (kn) => kn.counts_per_plan[plan] !== undefined
                );
                if (planKeynotes.length === 0) return null;
                return (
                  <div key={plan}>
                    <h4 className="text-xs font-semibold text-primary mb-2">
                      {plan}
                      <span className="text-text-light font-normal ml-2">
                        {planKeynotes.length} keynote{planKeynotes.length !== 1 ? 's' : ''}
                      </span>
                    </h4>
                    <div className="overflow-auto border border-border rounded-lg">
                      <table className="w-full border-collapse text-[13px]">
                        <thead>
                          <tr>
                            <th className="bg-primary text-white px-3.5 py-2 text-left font-semibold text-xs border-r border-white/10 w-[60px]">#</th>
                            <th className="bg-primary text-white px-3.5 py-2 text-left font-semibold text-xs border-r border-white/10">Key Note</th>
                            <th className="bg-[#162d4a] text-white px-3.5 py-2 text-center font-semibold text-xs w-[80px]">Count</th>
                          </tr>
                        </thead>
                        <tbody>
                          {planKeynotes.map((kn) => (
                            <tr key={kn.keynote_number} className="hover:bg-slate-50">
                              <td className="px-3.5 py-2 text-left font-bold text-primary bg-slate-50 border-b border-r border-border">
                                {kn.keynote_number}
                              </td>
                              <td className="px-3.5 py-2 text-left text-[12px] text-text-main leading-snug border-b border-r border-border">
                                {kn.keynote_text}
                              </td>
                              <td className="px-3.5 py-2 text-center font-semibold border-b border-border tabular-nums">
                                {kn.counts_per_plan[plan] ?? 0}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {data.fixtures.length === 0 && data.keynotes.length === 0 && (
          <div className="flex items-center justify-center py-16 text-text-light">
            <p className="text-sm">No fixture or keynote data available for this project.</p>
          </div>
        )}
      </div>
    </div>
  );
}
