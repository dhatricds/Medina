import { create } from 'zustand';
import type { ProjectData, AgentInfo, AppState, Correction, DashboardProject, ViewMode, HighlightState, FixturePosition, FixtureFeedback } from '../types';
import {
  loadDemoData,
  uploadFile,
  createFromSource,
  runProject,
  getResults,
  saveCorrections,
  listSources,
  getExcelDownloadUrl,
  downloadCorrectedExcel,
  listDashboardProjects,
  approveProject,
  getDashboardProject,
  deleteDashboardProject,
  getDashboardExcelUrl,
  editDashboardProject,
  getPagePositions,
  submitFeedback,
  getFeedback,
  removeFeedback,
  reprocessProject,
} from '../api/client';
import type { SourceItem } from '../api/client';

const emptyHighlight: HighlightState = {
  fixtureCode: null,
  keynoteNumber: null,
  targetSheetCode: null,
  positions: [],
  pageWidth: 0,
  pageHeight: 0,
  loading: false,
  rejectedIndices: new Set(),
  availablePlans: [],
  addedPositions: [],
  addMode: false,
};

/** Derive page count: prefer total_pages from backend, fall back to sheet_index length. */
function getPageCount(data: ProjectData): number {
  if (data.total_pages && data.total_pages > 0) return data.total_pages;
  if (data.pages && data.pages.length > 0) return data.pages.length;
  return data.sheet_index.length;
}

const defaultAgents: AgentInfo[] = [
  { id: 1, name: 'Search Agent', description: 'Load, discover, classify pages', status: 'pending', stats: {} },
  { id: 2, name: 'Schedule Agent', description: 'Extract fixture specs from schedule', status: 'pending', stats: {} },
  { id: 3, name: 'Count Agent', description: 'Count fixtures on plans', status: 'pending', stats: {} },
  { id: 4, name: 'Keynote Agent', description: 'Extract and count keynotes', status: 'pending', stats: {} },
  { id: 5, name: 'QA Agent', description: 'Validate and generate output', status: 'pending', stats: {} },
];

function buildDemoAgents(data: ProjectData): AgentInfo[] {
  return [
    {
      id: 1, name: 'Search Agent', description: 'Load, discover, classify pages',
      status: 'completed', time: 2.3,
      stats: {
        'Pages': getPageCount(data),
        'Plans found': data.lighting_plans.length,
        'Schedules': data.schedule_pages.length,
      },
    },
    {
      id: 2, name: 'Schedule Agent', description: 'Extract fixture specs from schedule',
      status: 'completed', time: 4.1,
      stats: {
        'Types found': data.summary.total_fixture_types,
        'Schedule pages': data.schedule_pages.join(', '),
      },
    },
    {
      id: 3, name: 'Count Agent', description: 'Count fixtures on plans',
      status: 'completed', time: 8.2,
      stats: {
        'Total fixtures': data.summary.total_fixtures,
        'Plans scanned': data.lighting_plans.length,
      },
    },
    {
      id: 4, name: 'Keynote Agent', description: 'Extract and count keynotes',
      status: 'completed', time: 5.1,
      stats: {
        'Keynotes found': data.summary.total_keynotes,
      },
    },
    {
      id: 5, name: 'QA Agent', description: 'Validate and generate output',
      status: 'completed', time: 3.4,
      stats: {
        'Confidence': `${((data.qa_report?.overall_confidence ?? 0) * 100).toFixed(0)}%`,
        'Warnings': data.qa_report?.warnings.length ?? 0,
      },
    },
  ];
}

/** Compare original pipeline output with current (edited) data. */
function computeCorrectionSummary(
  original: ProjectData | null,
  current: ProjectData | null,
): { countChanges: number; specChanges: number; fixtureAdds: number; fixtureRemoves: number; totalDiffs: number; needsRerun: boolean } {
  const result = { countChanges: 0, specChanges: 0, fixtureAdds: 0, fixtureRemoves: 0, totalDiffs: 0, needsRerun: false };
  if (!original || !current) return result;

  const origCodes = new Set(original.fixtures.map((f) => f.code));
  const currCodes = new Set(current.fixtures.map((f) => f.code));

  // Added fixtures
  for (const code of currCodes) {
    if (!origCodes.has(code)) result.fixtureAdds++;
  }
  // Removed fixtures
  for (const code of origCodes) {
    if (!currCodes.has(code)) result.fixtureRemoves++;
  }

  // Count and spec diffs for shared fixtures
  for (const cf of current.fixtures) {
    const of_ = original.fixtures.find((f) => f.code === cf.code);
    if (!of_) continue;
    // Count diffs
    const allPlans = new Set([...Object.keys(of_.counts_per_plan), ...Object.keys(cf.counts_per_plan)]);
    for (const p of allPlans) {
      if ((of_.counts_per_plan[p] ?? 0) !== (cf.counts_per_plan[p] ?? 0)) result.countChanges++;
    }
    // Spec diffs
    const specFields = ['description', 'fixture_style', 'voltage', 'mounting', 'lumens', 'cct', 'dimming', 'max_va'] as const;
    for (const field of specFields) {
      if ((of_[field] ?? '') !== (cf[field] ?? '')) result.specChanges++;
    }
  }

  // Keynote count diffs
  for (const ck of current.keynotes) {
    const ok_ = original.keynotes.find((k) => k.keynote_number === ck.keynote_number);
    if (!ok_) continue;
    const allPlans = new Set([...Object.keys(ok_.counts_per_plan), ...Object.keys(ck.counts_per_plan)]);
    for (const p of allPlans) {
      if ((ok_.counts_per_plan[p] ?? 0) !== (ck.counts_per_plan[p] ?? 0)) result.countChanges++;
    }
  }

  result.totalDiffs = result.countChanges + result.specChanges + result.fixtureAdds + result.fixtureRemoves;
  result.needsRerun = result.fixtureAdds > 0 || result.fixtureRemoves > 0;
  return result;
}

interface ProjectStore {
  // View mode
  view: ViewMode;

  // Workspace state
  appState: AppState;
  projectData: ProjectData | null;
  originalProjectData: ProjectData | null;
  agents: AgentInfo[];
  activeTab: 'lighting' | 'keynotes';
  corrections: Correction[];
  editCount: number;
  projectId: string | null;
  currentPage: number;
  totalPages: number;
  sources: SourceItem[];
  sseActive: boolean;
  error: string | null;

  // Fix It panel (deprecated, kept for compat)
  fixItOpen: boolean;
  // Chat panel (replaces Fix It)
  chatOpen: boolean;

  // Feedback state
  feedbackItems: FixtureFeedback[];
  feedbackCount: number;

  // Highlight state
  highlight: HighlightState;
  /** Persisted rejected marker indices per "code_plan" key, survives highlight re-entry. */
  savedRejections: Record<string, number[]>;
  /** Persisted user-added marker positions per "code_plan" key. */
  savedAdditions: Record<string, FixturePosition[]>;

  // Reprocess diff tracking
  /** Snapshot of projectData before a reprocess, used to compute diffs. */
  preReprocessData: ProjectData | null;
  /** Changed cells after reprocess: code → plan → oldCount. Only contains entries where count changed. */
  reprocessDiffs: Record<string, Record<string, number>>;

  // Dashboard state
  dashboardProjects: DashboardProject[];
  dashboardDetail: ProjectData | null;
  dashboardDetailId: string | null;
  approvedProjectIds: Set<string>;

  // View actions
  setView: (view: ViewMode) => void;

  // Reprocess diff actions
  savePreReprocessSnapshot: () => void;
  clearReprocessDiffs: () => void;

  // Dashboard actions
  loadDashboard: () => Promise<void>;
  approveCurrentProject: () => Promise<void>;
  viewDashboardProject: (id: string) => Promise<void>;
  closeDashboardDetail: () => void;
  removeDashboardProject: (id: string) => Promise<void>;
  downloadDashboardExcel: (id: string) => void;
  editDashboardForWorkspace: (id: string) => Promise<void>;

  // Fix It / Chat actions
  setFixItOpen: (open: boolean) => void;
  setChatOpen: (open: boolean) => void;

  // Highlight actions
  highlightFixture: (code: string, targetPlan?: string) => Promise<void>;
  highlightKeynote: (number: string, targetPlan?: string) => Promise<void>;
  navigateToSchedule: (code: string) => void;
  clearHighlight: () => void;
  toggleMarker: (index: number) => void;
  navigateHighlight: (direction: 'prev' | 'next') => void;
  toggleAddMode: () => void;
  addMarkerAtPosition: (pdfX: number, pdfY: number) => void;
  removeAddedMarker: (index: number) => void;

  // Workspace actions
  setAppState: (state: AppState) => void;
  setProjectData: (data: ProjectData) => void;
  setAgents: (agents: AgentInfo[]) => void;
  updateAgent: (id: number, update: Partial<AgentInfo>) => void;
  setActiveTab: (tab: 'lighting' | 'keynotes') => void;
  addCorrection: (correction: Correction) => void;
  updateFixtureCount: (code: string, plan: string, newCount: number) => void;
  updateKeynoteCount: (keynoteNumber: string, plan: string, newCount: number) => void;
  recalcTotals: () => void;
  setProjectId: (id: string) => void;
  setCurrentPage: (page: number) => void;
  setTotalPages: (pages: number) => void;
  setSseActive: (active: boolean) => void;
  loadDemo: (name: string) => Promise<void>;
  loadSources: () => Promise<void>;
  uploadAndProcess: (file: File) => Promise<void>;
  processFromSource: (sourcePath: string) => Promise<void>;
  fetchResults: (projectId: string) => Promise<void>;
  downloadExcel: () => void;
  saveEdits: () => Promise<void>;
  reset: () => void;

  // Feedback actions
  addFixtureFeedback: (item: FixtureFeedback) => Promise<void>;
  removeFixtureFeedback: (code: string, reason: string, detail: string) => Promise<void>;
  reprocessWithFeedback: () => Promise<void>;
  loadFeedback: (projectId: string) => Promise<void>;

  // Correction summary
  getCorrectionSummary: () => ReturnType<typeof computeCorrectionSummary>;
}

export const useProjectStore = create<ProjectStore>((set, get) => ({
  // View mode — start on dashboard
  view: 'dashboard',

  // Workspace state
  appState: 'empty',
  projectData: null,
  originalProjectData: null,
  agents: defaultAgents.map(a => ({ ...a })),
  activeTab: 'lighting',
  corrections: [],
  editCount: 0,
  projectId: null,
  currentPage: 1,
  totalPages: 0,
  sources: [],
  sseActive: false,
  error: null,

  // Fix It panel
  fixItOpen: false,
  chatOpen: false,

  // Feedback state
  feedbackItems: [],
  feedbackCount: 0,

  // Highlight state
  highlight: { ...emptyHighlight },
  savedRejections: {},
  savedAdditions: {},

  // Reprocess diff tracking
  preReprocessData: null,
  reprocessDiffs: {},

  // Dashboard state
  dashboardProjects: [],
  dashboardDetail: null,
  dashboardDetailId: null,
  approvedProjectIds: new Set(),

  // View actions
  setView: (view) => set({ view }),

  // Reprocess diff actions
  savePreReprocessSnapshot: () => {
    const { projectData } = get();
    if (projectData) {
      set({ preReprocessData: JSON.parse(JSON.stringify(projectData)) });
    }
  },
  clearReprocessDiffs: () => set({ reprocessDiffs: {}, preReprocessData: null }),

  // Dashboard actions
  loadDashboard: async () => {
    try {
      const projects = await listDashboardProjects();
      set({ dashboardProjects: projects });
    } catch {
      set({ dashboardProjects: [] });
    }
  },

  approveCurrentProject: async () => {
    const { projectId, projectData, originalProjectData } = get();
    if (!projectId) return;
    try {
      // Compare original vs current to detect user corrections
      const summary = computeCorrectionSummary(originalProjectData, projectData);
      const body: { corrected_fixtures?: unknown[]; corrected_keynotes?: unknown[] } = {};
      if (summary.totalDiffs > 0 && projectData) {
        body.corrected_fixtures = projectData.fixtures;
        body.corrected_keynotes = projectData.keynotes;
      }
      await approveProject(projectId, summary.totalDiffs > 0 ? body : undefined);
      // Refresh dashboard list
      const projects = await listDashboardProjects();
      set((s) => ({
        dashboardProjects: projects,
        approvedProjectIds: new Set([...s.approvedProjectIds, projectId]),
        view: 'dashboard',
      }));
    } catch (e) {
      console.error('Failed to approve project:', e);
    }
  },

  viewDashboardProject: async (id: string) => {
    try {
      const data = await getDashboardProject(id);
      set({
        dashboardDetail: data,
        dashboardDetailId: id,
        view: 'dashboard_detail',
      });
    } catch (e) {
      console.error('Failed to load dashboard project:', e);
    }
  },

  closeDashboardDetail: () => set({
    dashboardDetail: null,
    dashboardDetailId: null,
    view: 'dashboard',
  }),

  removeDashboardProject: async (id: string) => {
    try {
      await deleteDashboardProject(id);
      const projects = await listDashboardProjects();
      set({ dashboardProjects: projects });
    } catch (e) {
      console.error('Failed to delete dashboard project:', e);
    }
  },

  downloadDashboardExcel: (id: string) => {
    window.open(getDashboardExcelUrl(id), '_blank');
  },

  editDashboardForWorkspace: async (id: string) => {
    try {
      // Ask backend to create a workspace ProjectState from dashboard data
      const { project_id } = await editDashboardProject(id);

      // Load the project data via the standard results endpoint
      const data = await getResults(project_id);
      const originalCopy = JSON.parse(JSON.stringify(data)) as ProjectData;

      set({
        view: 'workspace',
        appState: 'complete',
        projectData: data,
        originalProjectData: originalCopy,
        projectId: project_id,
        totalPages: getPageCount(data),
        currentPage: 1,
        agents: buildDemoAgents(data),
        corrections: [],
        editCount: 0,
        error: null,
        sseActive: false,
        highlight: { ...emptyHighlight },
        savedRejections: {},
        savedAdditions: {},
        feedbackItems: [],
        feedbackCount: 0,
        preReprocessData: null,
        reprocessDiffs: {},
        dashboardDetail: null,
        dashboardDetailId: null,
      });

      // Load any existing feedback
      get().loadFeedback(project_id);
    } catch (e: any) {
      const msg = e?.message || 'Failed to open project for editing';
      console.error('Failed to open dashboard project for editing:', e);
      set({ error: msg });
    }
  },

  // Fix It / Chat actions
  setFixItOpen: (open: boolean) => set({ fixItOpen: open }),
  setChatOpen: (open: boolean) => set({ chatOpen: open, fixItOpen: false }),

  // Highlight actions
  highlightFixture: async (code: string, targetPlan?: string) => {
    const { projectId, projectData, savedRejections, savedAdditions } = get();
    if (!projectId || !projectData) return;

    // Find the target plan: explicit or first plan with count > 0
    const fixture = projectData.fixtures.find((f) => f.code === code);
    let planCode = targetPlan;
    if (!planCode && fixture) {
      planCode = projectData.lighting_plans.find(
        (p) => (fixture.counts_per_plan[p] ?? 0) > 0
      );
    }
    if (!planCode) planCode = projectData.lighting_plans[0];
    if (!planCode) return;

    // Compute plans with counts > 0 for prev/next navigation
    const availablePlans = fixture
      ? projectData.lighting_plans.filter((p) => (fixture.counts_per_plan[p] ?? 0) > 0)
      : [];

    // Find page number for this plan
    const pageEntry = projectData.pages?.find((p) => p.sheet_code === planCode);
    if (!pageEntry) return;

    // Restore saved rejections/additions for this code+plan
    const key = `${code}_${planCode}`;
    const restoredRejected = new Set(savedRejections[key] ?? []);
    const restoredAdded = savedAdditions[key] ?? [];

    // Navigate to that page
    set({
      currentPage: pageEntry.page_number,
      highlight: {
        fixtureCode: code,
        keynoteNumber: null,
        targetSheetCode: planCode,
        positions: [],
        pageWidth: 0,
        pageHeight: 0,
        loading: true,
        rejectedIndices: restoredRejected,
        availablePlans,
        addedPositions: restoredAdded,
        addMode: false,
      },
    });

    // Fetch positions
    try {
      const resp = await getPagePositions(projectId, pageEntry.page_number, planCode);
      if (resp.fixture_positions && resp.fixture_positions[code]) {
        set({
          highlight: {
            fixtureCode: code,
            keynoteNumber: null,
            targetSheetCode: planCode!,
            positions: resp.fixture_positions[code],
            pageWidth: resp.page_width ?? 0,
            pageHeight: resp.page_height ?? 0,
            loading: false,
            rejectedIndices: restoredRejected,
            availablePlans,
            addedPositions: restoredAdded,
            addMode: false,
          },
        });
      } else {
        set({
          highlight: {
            fixtureCode: code,
            keynoteNumber: null,
            targetSheetCode: planCode!,
            positions: [],
            pageWidth: 0,
            pageHeight: 0,
            loading: false,
            rejectedIndices: restoredRejected,
            availablePlans,
            addedPositions: restoredAdded,
            addMode: false,
          },
        });
      }
    } catch {
      set((s) => ({
        highlight: { ...s.highlight, loading: false },
      }));
    }
  },

  highlightKeynote: async (number: string, targetPlan?: string) => {
    const { projectId, projectData, savedRejections, savedAdditions } = get();
    if (!projectId || !projectData) return;

    const kn = projectData.keynotes.find((k) => k.keynote_number === number);
    let planCode = targetPlan;
    if (!planCode && kn) {
      planCode = projectData.lighting_plans.find(
        (p) => (kn.counts_per_plan[p] ?? 0) > 0
      );
    }
    if (!planCode) planCode = projectData.lighting_plans[0];
    if (!planCode) return;

    // Compute plans with counts > 0 for prev/next navigation
    const availablePlans = kn
      ? projectData.lighting_plans.filter((p) => (kn.counts_per_plan[p] ?? 0) > 0)
      : [];

    const pageEntry = projectData.pages?.find((p) => p.sheet_code === planCode);
    if (!pageEntry) return;

    // Restore saved rejections/additions for this keynote+plan
    const key = `kn${number}_${planCode}`;
    const restoredRejected = new Set(savedRejections[key] ?? []);
    const restoredAdded = savedAdditions[key] ?? [];

    set({
      currentPage: pageEntry.page_number,
      highlight: {
        fixtureCode: null,
        keynoteNumber: number,
        targetSheetCode: planCode,
        positions: [],
        pageWidth: 0,
        pageHeight: 0,
        loading: true,
        rejectedIndices: restoredRejected,
        availablePlans,
        addedPositions: restoredAdded,
        addMode: false,
      },
    });

    try {
      const resp = await getPagePositions(projectId, pageEntry.page_number, planCode);
      if (resp.keynote_positions && resp.keynote_positions[number]) {
        set({
          highlight: {
            fixtureCode: null,
            keynoteNumber: number,
            targetSheetCode: planCode!,
            positions: resp.keynote_positions[number],
            pageWidth: resp.page_width ?? 0,
            pageHeight: resp.page_height ?? 0,
            loading: false,
            rejectedIndices: restoredRejected,
            availablePlans,
            addedPositions: restoredAdded,
            addMode: false,
          },
        });
      } else {
        set({
          highlight: {
            fixtureCode: null,
            keynoteNumber: number,
            targetSheetCode: planCode!,
            positions: [],
            pageWidth: 0,
            pageHeight: 0,
            loading: false,
            rejectedIndices: restoredRejected,
            availablePlans,
            addedPositions: restoredAdded,
            addMode: false,
          },
        });
      }
    } catch {
      set((s) => ({
        highlight: { ...s.highlight, loading: false },
      }));
    }
  },

  clearHighlight: () => set({ highlight: { ...emptyHighlight } }),

  navigateToSchedule: (code: string) => {
    const { projectData } = get();
    if (!projectData) return;

    // Find the fixture to get its schedule_page
    const fixture = projectData.fixtures.find((f) => f.code === code);
    const scheduleCode = fixture?.schedule_page || projectData.schedule_pages[0];
    if (!scheduleCode) return;

    // Look up page number from pages array
    const pages = projectData.pages ?? [];
    const pageEntry = pages.find((p) => p.sheet_code === scheduleCode);
    if (pageEntry) {
      set({ currentPage: pageEntry.page_number, highlight: { ...emptyHighlight } });
      return;
    }

    // If scheduleCode is a page number string (e.g., "10"), navigate directly
    const asNum = parseInt(scheduleCode, 10);
    if (!isNaN(asNum) && asNum >= 1 && asNum <= pages.length) {
      set({ currentPage: asNum, highlight: { ...emptyHighlight } });
      return;
    }

    // Fallback: find schedule page index from sheet_index ordering
    const idx = projectData.sheet_index.findIndex((s) => s.sheet_code === scheduleCode);
    if (idx >= 0) {
      set({ currentPage: idx + 1, highlight: { ...emptyHighlight } });
    }
  },

  navigateHighlight: (direction: 'prev' | 'next') => {
    const { highlight, highlightFixture, highlightKeynote } = get();
    const plans = highlight.availablePlans;
    if (plans.length <= 1) return;

    const currentIdx = plans.indexOf(highlight.targetSheetCode ?? '');
    let nextIdx: number;
    if (direction === 'next') {
      nextIdx = currentIdx + 1 >= plans.length ? 0 : currentIdx + 1;
    } else {
      nextIdx = currentIdx - 1 < 0 ? plans.length - 1 : currentIdx - 1;
    }

    const nextPlan = plans[nextIdx];
    if (highlight.fixtureCode) {
      highlightFixture(highlight.fixtureCode, nextPlan);
    } else if (highlight.keynoteNumber) {
      highlightKeynote(highlight.keynoteNumber, nextPlan);
    }
  },

  toggleMarker: (index: number) => {
    const { highlight, updateFixtureCount, updateKeynoteCount, addCorrection, projectData, projectId, savedRejections } = get();
    if (!highlight.positions.length) return;

    const next = new Set(highlight.rejectedIndices);
    if (next.has(index)) {
      next.delete(index);
    } else {
      next.add(index);
    }

    const acceptedCount = highlight.positions.length - next.size + highlight.addedPositions.length;
    set({ highlight: { ...highlight, rejectedIndices: next } });

    // Persist rejections so they survive re-entry
    const plan = highlight.targetSheetCode;
    const itemKey = highlight.fixtureCode
      ? `${highlight.fixtureCode}_${plan}`
      : highlight.keynoteNumber
        ? `kn${highlight.keynoteNumber}_${plan}`
        : null;
    if (itemKey) {
      set({ savedRejections: { ...savedRejections, [itemKey]: Array.from(next) } });
    }

    // Auto-update the table count
    if (!plan || !projectData) return;

    if (highlight.fixtureCode) {
      const fixture = projectData.fixtures.find((f) => f.code === highlight.fixtureCode);
      const original = fixture?.counts_per_plan[plan] ?? 0;
      updateFixtureCount(highlight.fixtureCode, plan, acceptedCount);
      if (acceptedCount !== original) {
        addCorrection({
          type: 'lighting',
          identifier: highlight.fixtureCode,
          sheet: plan,
          original,
          corrected: acceptedCount,
        });
        // Fire-and-forget: persist feedback with rejected positions so
        // the count agent learns to skip these locations on reprocess
        if (projectId) {
          const rejectedPositions = Array.from(next).map((idx) => {
            const pos = highlight.positions[idx];
            return { x0: pos.x0, top: pos.top, x1: pos.x1, bottom: pos.bottom, cx: pos.cx, cy: pos.cy };
          });
          submitFeedback(projectId, {
            action: 'count_override',
            fixture_code: highlight.fixtureCode,
            reason: 'wrong_bounding_box',
            reason_detail: `Marker rejection: ${original} -> ${acceptedCount} on ${plan}`,
            fixture_data: { sheet: plan, corrected: acceptedCount, original, rejected_positions: rejectedPositions },
          }).then(() => {
            set((s) => ({ feedbackCount: s.feedbackCount + 1 }));
          }).catch(() => {});
        }
      }
    } else if (highlight.keynoteNumber) {
      const kn = projectData.keynotes.find((k) => k.keynote_number === highlight.keynoteNumber);
      const original = kn?.counts_per_plan[plan] ?? 0;
      updateKeynoteCount(highlight.keynoteNumber, plan, acceptedCount);
      if (acceptedCount !== original) {
        addCorrection({
          type: 'keynote',
          identifier: highlight.keynoteNumber,
          sheet: plan,
          original,
          corrected: acceptedCount,
        });
      }
    }

    // Recalculate totals after count change
    get().recalcTotals();
  },

  toggleAddMode: () => {
    const { highlight } = get();
    set({ highlight: { ...highlight, addMode: !highlight.addMode } });
  },

  addMarkerAtPosition: (pdfX: number, pdfY: number) => {
    const { highlight, updateFixtureCount, updateKeynoteCount, addCorrection, projectData, projectId, savedAdditions } = get();
    if (!highlight.addMode) return;
    const plan = highlight.targetSheetCode;
    if (!plan || !projectData) return;

    // Create a small marker box around the click point (10pt radius)
    const r = 10;
    const newPos = { x0: pdfX - r, top: pdfY - r, x1: pdfX + r, bottom: pdfY + r, cx: pdfX, cy: pdfY };
    const updatedAdded = [...highlight.addedPositions, newPos];

    // New count = pipeline positions (minus rejected) + user-added
    const acceptedPipeline = highlight.positions.length - highlight.rejectedIndices.size;
    const newCount = acceptedPipeline + updatedAdded.length;

    set({ highlight: { ...highlight, addedPositions: updatedAdded, addMode: false } });

    // Persist added positions so they survive re-entry
    const itemKey = highlight.fixtureCode
      ? `${highlight.fixtureCode}_${plan}`
      : highlight.keynoteNumber
        ? `kn${highlight.keynoteNumber}_${plan}`
        : null;
    if (itemKey) {
      set({ savedAdditions: { ...savedAdditions, [itemKey]: updatedAdded } });
    }

    // Update the table count
    if (highlight.fixtureCode) {
      const fixture = projectData.fixtures.find((f) => f.code === highlight.fixtureCode);
      const original = fixture?.counts_per_plan[plan] ?? 0;
      updateFixtureCount(highlight.fixtureCode, plan, newCount);
      addCorrection({ type: 'lighting', identifier: highlight.fixtureCode, sheet: plan, original, corrected: newCount });

      // Fire-and-forget: save added positions to feedback
      if (projectId) {
        const rejectedPositions = Array.from(highlight.rejectedIndices).map((idx) => {
          const pos = highlight.positions[idx];
          return { x0: pos.x0, top: pos.top, x1: pos.x1, bottom: pos.bottom, cx: pos.cx, cy: pos.cy };
        });
        const addedPositions = updatedAdded.map((p) => ({ x0: p.x0, top: p.top, x1: p.x1, bottom: p.bottom, cx: p.cx, cy: p.cy }));
        submitFeedback(projectId, {
          action: 'count_override',
          fixture_code: highlight.fixtureCode,
          reason: 'wrong_bounding_box',
          reason_detail: `Added missing marker + ${highlight.rejectedIndices.size} rejected on ${plan}`,
          fixture_data: { sheet: plan, corrected: newCount, original, rejected_positions: rejectedPositions, added_positions: addedPositions },
        }).then(() => {
          set((s) => ({ feedbackCount: s.feedbackCount + 1 }));
        }).catch(() => {});
      }
    } else if (highlight.keynoteNumber) {
      const kn = projectData.keynotes.find((k) => k.keynote_number === highlight.keynoteNumber);
      const original = kn?.counts_per_plan[plan] ?? 0;
      updateKeynoteCount(highlight.keynoteNumber, plan, newCount);
      addCorrection({ type: 'keynote', identifier: highlight.keynoteNumber, sheet: plan, original, corrected: newCount });
    }

    get().recalcTotals();
  },

  removeAddedMarker: (index: number) => {
    const { highlight, updateFixtureCount, updateKeynoteCount, addCorrection, projectData, projectId, savedAdditions } = get();
    const plan = highlight.targetSheetCode;
    if (!plan || !projectData) return;

    const updatedAdded = highlight.addedPositions.filter((_, i) => i !== index);
    const acceptedPipeline = highlight.positions.length - highlight.rejectedIndices.size;
    const newCount = acceptedPipeline + updatedAdded.length;

    set({ highlight: { ...highlight, addedPositions: updatedAdded } });

    // Persist to savedAdditions
    const itemKey = highlight.fixtureCode
      ? `${highlight.fixtureCode}_${plan}`
      : highlight.keynoteNumber
        ? `kn${highlight.keynoteNumber}_${plan}`
        : null;
    if (itemKey) {
      set({ savedAdditions: { ...savedAdditions, [itemKey]: updatedAdded } });
    }

    if (highlight.fixtureCode) {
      const fixture = projectData.fixtures.find((f) => f.code === highlight.fixtureCode);
      const original = fixture?.counts_per_plan[plan] ?? 0;
      updateFixtureCount(highlight.fixtureCode, plan, newCount);
      addCorrection({ type: 'lighting', identifier: highlight.fixtureCode, sheet: plan, original, corrected: newCount });
    } else if (highlight.keynoteNumber) {
      const kn = projectData.keynotes.find((k) => k.keynote_number === highlight.keynoteNumber);
      const original = kn?.counts_per_plan[plan] ?? 0;
      updateKeynoteCount(highlight.keynoteNumber, plan, newCount);
      addCorrection({ type: 'keynote', identifier: highlight.keynoteNumber, sheet: plan, original, corrected: newCount });
    }

    get().recalcTotals();
  },

  // Workspace actions
  setAppState: (state) => set({ appState: state }),
  setProjectData: (data) => set({ projectData: data }),
  setAgents: (agents) => set({ agents }),
  updateAgent: (id, update) => set((s) => ({
    agents: s.agents.map((a) => a.id === id ? { ...a, ...update } : a),
  })),
  setActiveTab: (tab) => set({ activeTab: tab }),
  addCorrection: (correction) => set((s) => ({
    corrections: [...s.corrections, correction],
    editCount: s.editCount + 1,
  })),
  updateFixtureCount: (code, plan, newCount) => set((s) => {
    if (!s.projectData) return {};
    const fixtures = s.projectData.fixtures.map((f) => {
      if (f.code === code) {
        const updatedCounts = { ...f.counts_per_plan, [plan]: newCount };
        return { ...f, counts_per_plan: updatedCounts };
      }
      return f;
    });
    return {
      projectData: { ...s.projectData, fixtures },
    };
  }),
  updateKeynoteCount: (keynoteNumber, plan, newCount) => set((s) => {
    if (!s.projectData) return {};
    const keynotes = s.projectData.keynotes.map((k) => {
      if (k.keynote_number === keynoteNumber) {
        const updatedCounts = { ...k.counts_per_plan, [plan]: newCount };
        return { ...k, counts_per_plan: updatedCounts };
      }
      return k;
    });
    return {
      projectData: { ...s.projectData, keynotes },
    };
  }),
  recalcTotals: () => set((s) => {
    if (!s.projectData) return {};
    const fixtures = s.projectData.fixtures.map((f) => ({
      ...f,
      total: Object.values(f.counts_per_plan).reduce((sum, c) => sum + c, 0),
    }));
    const keynotes = s.projectData.keynotes.map((k) => ({
      ...k,
      total: Object.values(k.counts_per_plan).reduce((sum, c) => sum + c, 0),
    }));
    const total_fixtures = fixtures.reduce((sum, f) => sum + f.total, 0);
    return {
      projectData: {
        ...s.projectData,
        fixtures,
        keynotes,
        summary: {
          ...s.projectData.summary,
          total_fixtures,
        },
      },
    };
  }),
  setProjectId: (id) => set({ projectId: id, highlight: { ...emptyHighlight } }),
  setCurrentPage: (page) => set({ currentPage: page }),
  setTotalPages: (pages) => set({ totalPages: pages }),
  setSseActive: (active) => set({ sseActive: active }),

  loadDemo: async (name: string) => {
    try {
      // Try backend API first
      const data = await loadDemoData(name);
      set({
        view: 'workspace',
        appState: 'demo',
        projectData: data,
        agents: buildDemoAgents(data),
        corrections: [],
        editCount: 0,
        projectId: null,
        currentPage: 1,
        totalPages: getPageCount(data),
        error: null,
      });
    } catch {
      // Fallback: load from static public files (works without backend)
      try {
        const resp = await fetch(`/demo/${name}.json`);
        if (!resp.ok) throw new Error('Demo data not available');
        const data: ProjectData = await resp.json();
        set({
          view: 'workspace',
          appState: 'demo',
          projectData: data,
          agents: buildDemoAgents(data),
          corrections: [],
          editCount: 0,
          projectId: null,
          currentPage: 1,
          totalPages: getPageCount(data),
          error: null,
        });
      } catch {
        set({ error: 'Failed to load demo data' });
      }
    }
  },

  loadSources: async () => {
    try {
      const sources = await listSources();
      set({ sources });
    } catch {
      set({ sources: [] });
    }
  },

  uploadAndProcess: async (file: File) => {
    set({
      view: 'workspace',
      appState: 'processing',
      agents: defaultAgents.map(a => ({ ...a })),
      corrections: [],
      editCount: 0,
      error: null,
      projectData: null,
    });
    try {
      const { project_id } = await uploadFile(file);
      set({ projectId: project_id });
      await runProject(project_id);
      set({ sseActive: true });
    } catch (e) {
      set({ appState: 'error', error: String(e) });
    }
  },

  processFromSource: async (sourcePath: string) => {
    set({
      view: 'workspace',
      appState: 'processing',
      agents: defaultAgents.map(a => ({ ...a })),
      corrections: [],
      editCount: 0,
      error: null,
      projectData: null,
    });
    try {
      const { project_id } = await createFromSource(sourcePath);
      set({ projectId: project_id });
      await runProject(project_id);
      set({ sseActive: true });
    } catch (e) {
      set({ appState: 'error', error: String(e) });
    }
  },

  fetchResults: async (projectId: string) => {
    try {
      const data = await getResults(projectId);
      // Deep copy the original pipeline data before any edits
      const originalCopy = JSON.parse(JSON.stringify(data)) as ProjectData;

      // Compute diffs if we have a pre-reprocess snapshot
      const { preReprocessData } = get();
      let diffs: Record<string, Record<string, number>> = {};
      if (preReprocessData) {
        for (const fixture of data.fixtures) {
          const oldFixture = preReprocessData.fixtures.find((f) => f.code === fixture.code);
          if (!oldFixture) continue;
          for (const plan of data.lighting_plans) {
            const oldCount = oldFixture.counts_per_plan[plan] ?? 0;
            const newCount = fixture.counts_per_plan[plan] ?? 0;
            if (oldCount !== newCount) {
              if (!diffs[fixture.code]) diffs[fixture.code] = {};
              diffs[fixture.code][plan] = oldCount;
            }
          }
        }
      }

      set({
        projectData: data,
        originalProjectData: originalCopy,
        appState: 'complete',
        sseActive: false,
        totalPages: getPageCount(data),
        currentPage: 1,
        reprocessDiffs: diffs,
        preReprocessData: null,
        highlight: { ...emptyHighlight },
      });
      // Load any existing feedback for this project
      get().loadFeedback(projectId);
    } catch (e) {
      set({ appState: 'error', error: `Failed to load results: ${e}` });
    }
  },

  downloadExcel: () => {
    const { projectId, projectData, originalProjectData } = get();
    if (projectId && projectData) {
      // If user has made corrections, POST corrected data for on-the-fly Excel
      const summary = computeCorrectionSummary(originalProjectData, projectData);
      if (summary.totalDiffs > 0) {
        downloadCorrectedExcel(projectId, projectData.fixtures, projectData.keynotes)
          .then((blob) => {
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${projectData.project_name}_inventory.xlsx`;
            a.click();
            URL.revokeObjectURL(url);
          })
          .catch((e) => console.error('Failed to download corrected Excel:', e));
      } else {
        window.open(getExcelDownloadUrl(projectId), '_blank');
      }
    } else if (projectData) {
      // Client-side CSV fallback for demo mode
      const plans = projectData.lighting_plans;
      let csv = 'Type,' + plans.join(',') + ',Total\n';
      for (const f of projectData.fixtures) {
        const counts = plans.map((p) => f.counts_per_plan[p] ?? 0);
        csv += `${f.code},${counts.join(',')},${f.total}\n`;
      }
      const blob = new Blob([csv], { type: 'text/csv' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${projectData.project_name}_inventory.csv`;
      a.click();
      URL.revokeObjectURL(url);
    }
  },

  saveEdits: async () => {
    const { projectId, corrections } = get();
    if (!projectId || corrections.length === 0) return;
    try {
      await saveCorrections(projectId, corrections);
    } catch {
      // Corrections remain in local state
    }
  },

  // Feedback actions
  addFixtureFeedback: async (item: FixtureFeedback) => {
    const { projectId, projectData } = get();
    if (!projectId) return;

    try {
      const resp = await submitFeedback(projectId, item);

      // Optimistically add fixture row with zero counts if action is "add"
      if (item.action === 'add' && projectData) {
        const exists = projectData.fixtures.some(f => f.code === item.fixture_code);
        if (!exists) {
          const zeroCounts: Record<string, number> = {};
          for (const plan of projectData.lighting_plans) {
            zeroCounts[plan] = 0;
          }
          const newFixture = {
            code: item.fixture_code,
            description: item.fixture_data?.description ?? '',
            fixture_style: item.fixture_data?.fixture_style ?? '',
            voltage: item.fixture_data?.voltage ?? '',
            mounting: item.fixture_data?.mounting ?? '',
            lumens: item.fixture_data?.lumens ?? '',
            cct: item.fixture_data?.cct ?? '',
            dimming: item.fixture_data?.dimming ?? '',
            max_va: item.fixture_data?.max_va ?? '',
            counts_per_plan: zeroCounts,
            total: 0,
          };
          set((s) => ({
            projectData: s.projectData ? {
              ...s.projectData,
              fixtures: [...s.projectData.fixtures, newFixture],
              summary: {
                ...s.projectData.summary,
                total_fixture_types: s.projectData.summary.total_fixture_types + 1,
              },
            } : null,
            feedbackItems: resp.corrections ?? [...s.feedbackItems, item],
            feedbackCount: resp.correction_count ?? s.feedbackCount + 1,
          }));
          return;
        }
      }

      // For remove action, remove from local fixtures
      if (item.action === 'remove' && projectData) {
        set((s) => ({
          projectData: s.projectData ? {
            ...s.projectData,
            fixtures: s.projectData.fixtures.filter(f => f.code !== item.fixture_code),
            summary: {
              ...s.projectData.summary,
              total_fixture_types: Math.max(0, s.projectData.summary.total_fixture_types - 1),
              total_fixtures: s.projectData.summary.total_fixtures -
                (s.projectData.fixtures.find(f => f.code === item.fixture_code)?.total ?? 0),
            },
          } : null,
          feedbackItems: resp.corrections ?? [...s.feedbackItems, item],
          feedbackCount: resp.correction_count ?? s.feedbackCount + 1,
        }));
        return;
      }

      set({
        feedbackItems: resp.corrections ?? [...get().feedbackItems, item],
        feedbackCount: resp.correction_count ?? get().feedbackCount + 1,
      });
    } catch (e) {
      console.error('Failed to submit feedback:', e);
    }
  },

  removeFixtureFeedback: async (code: string, reason: string, detail: string) => {
    const item: FixtureFeedback = {
      action: 'remove',
      fixture_code: code,
      reason: reason as FixtureFeedback['reason'],
      reason_detail: detail,
    };
    await get().addFixtureFeedback(item);
  },

  reprocessWithFeedback: async () => {
    const { projectId } = get();
    if (!projectId) return;

    // Save snapshot for diff tracking
    get().savePreReprocessSnapshot();

    try {
      set({
        appState: 'processing',
        agents: [
          { id: 1, name: 'Search Agent', description: 'Load, discover, classify pages', status: 'pending', stats: {} },
          { id: 2, name: 'Schedule Agent', description: 'Extract fixture specs from schedule', status: 'pending', stats: {} },
          { id: 3, name: 'Count Agent', description: 'Count fixtures on plans', status: 'pending', stats: {} },
          { id: 4, name: 'Keynote Agent', description: 'Extract and count keynotes', status: 'pending', stats: {} },
          { id: 5, name: 'QA Agent', description: 'Validate and generate output', status: 'pending', stats: {} },
        ],
        error: null,
      });

      await reprocessProject(projectId);
      set({ sseActive: true });
    } catch (e) {
      set({ appState: 'error', error: `Reprocessing failed: ${e}` });
    }
  },

  loadFeedback: async (projectId: string) => {
    try {
      const resp = await getFeedback(projectId);
      set({
        feedbackItems: resp.corrections ?? [],
        feedbackCount: resp.correction_count ?? 0,
      });
    } catch {
      // No feedback yet -- that's fine
      set({ feedbackItems: [], feedbackCount: 0 });
    }
  },

  getCorrectionSummary: () => {
    const { originalProjectData, projectData } = get();
    return computeCorrectionSummary(originalProjectData, projectData);
  },

  reset: () => set({
    appState: 'empty',
    projectData: null,
    originalProjectData: null,
    agents: defaultAgents.map(a => ({ ...a })),
    activeTab: 'lighting',
    corrections: [],
    editCount: 0,
    projectId: null,
    currentPage: 1,
    totalPages: 0,
    sseActive: false,
    error: null,
    highlight: { ...emptyHighlight },
    savedRejections: {},
    savedAdditions: {},
    fixItOpen: false,
    chatOpen: false,
    feedbackItems: [],
    feedbackCount: 0,
    preReprocessData: null,
    reprocessDiffs: {},
  }),
}));
