import { create } from 'zustand';
import type { ProjectData, AgentInfo, AppState, Correction } from '../types';
import {
  loadDemoData,
  uploadFile,
  createFromSource,
  runProject,
  getResults,
  saveCorrections,
  listSources,
  getExcelDownloadUrl,
} from '../api/client';
import type { SourceItem } from '../api/client';

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

interface ProjectStore {
  appState: AppState;
  projectData: ProjectData | null;
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
}

export const useProjectStore = create<ProjectStore>((set, get) => ({
  appState: 'empty',
  projectData: null,
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
  setProjectId: (id) => set({ projectId: id }),
  setCurrentPage: (page) => set({ currentPage: page }),
  setTotalPages: (pages) => set({ totalPages: pages }),
  setSseActive: (active) => set({ sseActive: active }),

  loadDemo: async (name: string) => {
    try {
      // Try backend API first
      const data = await loadDemoData(name);
      set({
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
      set({
        projectData: data,
        appState: 'complete',
        sseActive: false,
        totalPages: getPageCount(data),
        currentPage: 1,
      });
    } catch (e) {
      set({ appState: 'error', error: `Failed to load results: ${e}` });
    }
  },

  downloadExcel: () => {
    const { projectId, projectData } = get();
    if (projectId) {
      window.open(getExcelDownloadUrl(projectId), '_blank');
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

  reset: () => set({
    appState: 'empty',
    projectData: null,
    agents: defaultAgents.map(a => ({ ...a })),
    activeTab: 'lighting',
    corrections: [],
    editCount: 0,
    projectId: null,
    currentPage: 1,
    totalPages: 0,
    sseActive: false,
    error: null,
  }),
}));
