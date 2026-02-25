import { useState, useMemo } from 'react';
import { useProjectStore } from '../../store/projectStore';
import type { DashboardProject } from '../../types';

function QaBadge({ score, passed }: { score: number | null; passed: boolean | null }) {
  if (score === null) {
    return <span className="text-[10px] px-2 py-0.5 rounded bg-slate-100 text-text-light">N/A</span>;
  }
  const pct = Math.round(score * 100);
  const color = passed
    ? 'bg-green-100 text-green-800'
    : pct >= 80
      ? 'bg-amber-100 text-amber-800'
      : 'bg-red-100 text-red-800';
  return <span className={`text-[11px] font-semibold px-2 py-0.5 rounded ${color}`}>{pct}%</span>;
}

function ProjectCard({ project, onView, onDelete, onEdit }: {
  project: DashboardProject;
  onView: () => void;
  onDelete: () => void;
  onEdit: () => void;
}) {
  const [confirmDelete, setConfirmDelete] = useState(false);

  const date = new Date(project.approved_at);
  const dateStr = date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });

  return (
    <div
      className="bg-card border border-border rounded-lg p-5 hover:shadow-md hover:border-primary/30 transition-all cursor-pointer group relative"
      onClick={onView}
    >
      {/* Action buttons */}
      <div className="absolute top-3 right-3 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-all">
        {/* Edit button */}
        <button
          className="w-7 h-7 rounded-md flex items-center justify-center hover:bg-blue-50 transition-all cursor-pointer"
          onClick={(e) => { e.stopPropagation(); onEdit(); }}
          title="Edit in Workspace"
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" strokeWidth="2">
            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
          </svg>
        </button>
        {/* Delete button */}
        <button
          className="w-7 h-7 rounded-md flex items-center justify-center hover:bg-red-50 transition-all cursor-pointer"
          onClick={(e) => {
            e.stopPropagation();
            if (confirmDelete) {
              onDelete();
            } else {
              setConfirmDelete(true);
              setTimeout(() => setConfirmDelete(false), 3000);
            }
          }}
          title={confirmDelete ? 'Click again to confirm' : 'Remove from dashboard'}
        >
          {confirmDelete ? (
            <span className="text-[10px] text-red-600 font-bold">?</span>
          ) : (
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" strokeWidth="2">
              <polyline points="3 6 5 6 21 6" />
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
            </svg>
          )}
        </button>
      </div>

      {/* Project name */}
      <h3 className="font-semibold text-sm text-text-main mb-3 pr-8 truncate" title={project.name}>
        {project.name}
      </h3>

      {/* Stats grid */}
      <div className="grid grid-cols-2 gap-y-2.5 gap-x-4 mb-4">
        <div>
          <div className="text-[10px] text-text-light uppercase tracking-wide">Fixture Types</div>
          <div className="text-lg font-bold text-primary">{project.fixture_types}</div>
        </div>
        <div>
          <div className="text-[10px] text-text-light uppercase tracking-wide">Total Count</div>
          <div className="text-lg font-bold text-primary">{project.total_fixtures}</div>
        </div>
        <div>
          <div className="text-[10px] text-text-light uppercase tracking-wide">Keynotes</div>
          <div className="text-sm font-semibold text-text-main">{project.keynote_count}</div>
        </div>
        <div>
          <div className="text-[10px] text-text-light uppercase tracking-wide">Plans</div>
          <div className="text-sm font-semibold text-text-main">{project.plan_count}</div>
        </div>
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between pt-3 border-t border-border">
        <span className="text-[10px] text-text-light">{dateStr}</span>
        <QaBadge score={project.qa_score} passed={project.qa_passed} />
      </div>
    </div>
  );
}

type SortOption = 'newest' | 'oldest' | 'name-asc' | 'name-desc';

function formatMonth(ym: string): string {
  const [year, month] = ym.split('-');
  const date = new Date(Number(year), Number(month) - 1);
  return date.toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
}

export default function DashboardView() {
  const { dashboardProjects, viewDashboardProject, removeDashboardProject, loadDashboardToWorkspace } = useProjectStore();
  const [search, setSearch] = useState('');
  const [monthFilter, setMonthFilter] = useState('all');
  const [sortBy, setSortBy] = useState<SortOption>('newest');

  // Derive unique months from projects for the dropdown
  const months = useMemo(() => {
    const set = new Set(
      dashboardProjects
        .filter((p) => p.approved_at)
        .map((p) => p.approved_at.slice(0, 7))
    );
    return ['all', ...Array.from(set).sort().reverse()];
  }, [dashboardProjects]);

  // Filter + sort
  const filtered = useMemo(() => {
    let result = dashboardProjects;
    if (search) {
      const q = search.toLowerCase();
      result = result.filter((p) => p.name.toLowerCase().includes(q));
    }
    if (monthFilter !== 'all') {
      result = result.filter((p) => p.approved_at.startsWith(monthFilter));
    }
    result = [...result].sort((a, b) => {
      switch (sortBy) {
        case 'newest': return b.approved_at.localeCompare(a.approved_at);
        case 'oldest': return a.approved_at.localeCompare(b.approved_at);
        case 'name-asc': return a.name.localeCompare(b.name);
        case 'name-desc': return b.name.localeCompare(a.name);
      }
    });
    return result;
  }, [dashboardProjects, search, monthFilter, sortBy]);

  if (dashboardProjects.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-text-light">
        <div className="text-center">
          <div className="w-16 h-16 rounded-full bg-slate-100 flex items-center justify-center mx-auto mb-4">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" strokeWidth="1.5">
              <rect x="3" y="3" width="7" height="7" />
              <rect x="14" y="3" width="7" height="7" />
              <rect x="3" y="14" width="7" height="7" />
              <rect x="14" y="14" width="7" height="7" />
            </svg>
          </div>
          <p className="text-base font-semibold mb-2 text-text-main">No Projects Yet</p>
          <p className="text-sm max-w-xs">
            Process a PDF in the Workspace and click "Approve" to add it here.
          </p>
        </div>
      </div>
    );
  }

  const isFiltered = search || monthFilter !== 'all';

  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="max-w-6xl mx-auto">
        <div className="mb-6">
          <h2 className="text-lg font-bold text-text-main">Approved Projects</h2>
          <p className="text-sm text-text-light mt-1">
            {dashboardProjects.length} project{dashboardProjects.length !== 1 ? 's' : ''} in inventory
          </p>
        </div>

        {/* Summary stats */}
        <div className="grid grid-cols-4 gap-4 mb-6">
          <div className="bg-card border border-border rounded-lg px-4 py-3">
            <div className="text-[10px] text-text-light uppercase tracking-wide">Projects</div>
            <div className="text-2xl font-bold text-primary">{dashboardProjects.length}</div>
          </div>
          <div className="bg-card border border-border rounded-lg px-4 py-3">
            <div className="text-[10px] text-text-light uppercase tracking-wide">Total Fixture Types</div>
            <div className="text-2xl font-bold text-primary">
              {dashboardProjects.reduce((sum, p) => sum + p.fixture_types, 0)}
            </div>
          </div>
          <div className="bg-card border border-border rounded-lg px-4 py-3">
            <div className="text-[10px] text-text-light uppercase tracking-wide">Total Fixtures</div>
            <div className="text-2xl font-bold text-primary">
              {dashboardProjects.reduce((sum, p) => sum + p.total_fixtures, 0)}
            </div>
          </div>
          <div className="bg-card border border-border rounded-lg px-4 py-3">
            <div className="text-[10px] text-text-light uppercase tracking-wide">Avg QA Score</div>
            <div className="text-2xl font-bold text-primary">
              {(() => {
                const scored = dashboardProjects.filter((p) => p.qa_score !== null);
                if (scored.length === 0) return 'N/A';
                const avg = scored.reduce((sum, p) => sum + (p.qa_score ?? 0), 0) / scored.length;
                return `${Math.round(avg * 100)}%`;
              })()}
            </div>
          </div>
        </div>

        {/* Search & Filter bar */}
        <div className="flex items-center gap-3 mb-4">
          {/* Search input */}
          <div className="relative flex-1 max-w-xs">
            <svg className="absolute left-3 top-1/2 -translate-y-1/2 text-text-light" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <input
              type="text"
              placeholder="Search projects..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full pl-9 pr-3 py-2 text-[13px] border border-border rounded-md bg-card focus:outline-none focus:ring-1 focus:ring-primary/40 focus:border-primary/40"
            />
            {search && (
              <button
                className="absolute right-2 top-1/2 -translate-y-1/2 w-5 h-5 rounded-full flex items-center justify-center hover:bg-slate-100 text-text-light cursor-pointer"
                onClick={() => setSearch('')}
              >
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
            )}
          </div>

          {/* Month filter */}
          <select
            value={monthFilter}
            onChange={(e) => setMonthFilter(e.target.value)}
            className="px-3 py-2 text-[13px] border border-border rounded-md bg-card focus:outline-none focus:ring-1 focus:ring-primary/40 cursor-pointer"
          >
            <option value="all">All Months</option>
            {months.filter((m) => m !== 'all').map((m) => (
              <option key={m} value={m}>{formatMonth(m)}</option>
            ))}
          </select>

          {/* Sort dropdown */}
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as SortOption)}
            className="px-3 py-2 text-[13px] border border-border rounded-md bg-card focus:outline-none focus:ring-1 focus:ring-primary/40 cursor-pointer"
          >
            <option value="newest">Newest First</option>
            <option value="oldest">Oldest First</option>
            <option value="name-asc">Name A-Z</option>
            <option value="name-desc">Name Z-A</option>
          </select>

          {/* Result count when filtered */}
          {isFiltered && (
            <span className="text-xs text-text-light whitespace-nowrap">
              Showing {filtered.length} of {dashboardProjects.length}
            </span>
          )}
        </div>

        {/* Project grid */}
        {filtered.length > 0 ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {filtered.map((project) => (
              <ProjectCard
                key={project.id}
                project={project}
                onView={() => viewDashboardProject(project.id)}
                onDelete={() => removeDashboardProject(project.id)}
                onEdit={() => loadDashboardToWorkspace(project.id)}
              />
            ))}
          </div>
        ) : (
          <div className="flex items-center justify-center py-12 text-text-light">
            <p className="text-sm">No projects match your search.</p>
          </div>
        )}
      </div>
    </div>
  );
}
