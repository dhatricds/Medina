import type { ProjectData, Correction, DashboardProject, FixturePosition, FixtureFeedback, FixItAction, FixItInterpretation, ChatMsg, ChatResponse } from '../types';

const BASE = import.meta.env.VITE_API_URL ?? '';

/**
 * Handle 401 responses globally: clear auth state and reload to show login.
 */
function handle401(res: Response): void {
  if (res.status === 401) {
    // Dynamically import to avoid circular deps
    import('../store/authStore').then(({ useAuthStore }) => {
      const { isAuthenticated } = useAuthStore.getState();
      if (isAuthenticated) {
        useAuthStore.setState({ user: null, isAuthenticated: false, isLoading: false });
      }
    });
  }
}

export async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { credentials: 'include' });
  if (!res.ok) {
    handle401(res);
    throw new Error(`${res.status} ${res.statusText}`);
  }
  return res.json();
}

export async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    handle401(res);
    throw new Error(`${res.status} ${res.statusText}`);
  }
  return res.json();
}

export async function patchJson<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    handle401(res);
    throw new Error(`${res.status} ${res.statusText}`);
  }
  return res.json();
}

// --- Source listing ---

export interface SourceItem {
  name: string;
  path: string;
  type: 'file' | 'folder';
  size: number | null;
}

export function listSources(): Promise<SourceItem[]> {
  return fetchJson('/api/sources');
}

// --- Upload ---

export async function uploadFile(file: File): Promise<{ project_id: string; source: string }> {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(`${BASE}/api/upload`, { method: 'POST', credentials: 'include', body: form });
  if (!res.ok) {
    handle401(res);
    throw new Error(`${res.status} ${res.statusText}`);
  }
  return res.json();
}

// --- Projects ---

export function createFromSource(sourcePath: string): Promise<{ project_id: string; source: string }> {
  return postJson('/api/projects/from-source', { source_path: sourcePath });
}

export function runProject(projectId: string): Promise<{ project_id: string; status: string }> {
  return postJson(`/api/projects/${projectId}/run`);
}

export function getResults(projectId: string): Promise<ProjectData> {
  return fetchJson(`/api/projects/${projectId}/results`);
}

// --- Pages ---

export function getPageImageUrl(projectId: string, pageNumber: number, dpi = 150): string {
  return `${BASE}/api/projects/${projectId}/page/${pageNumber}?dpi=${dpi}`;
}

export function getPagePdfUrl(projectId: string, pageNumber: number): string {
  return `${BASE}/api/projects/${projectId}/page/${pageNumber}/pdf`;
}

export function getPdfUrl(projectId: string): string {
  return `${BASE}/api/projects/${projectId}/pdf`;
}

// --- Export ---

export function getExcelDownloadUrl(projectId: string): string {
  return `${BASE}/api/projects/${projectId}/export/excel`;
}

/** Download Excel with corrected data via POST (returns blob). */
export async function downloadCorrectedExcel(
  projectId: string,
  fixtures: unknown[],
  keynotes: unknown[],
): Promise<Blob> {
  const res = await fetch(`${BASE}/api/projects/${projectId}/export/excel`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ fixtures, keynotes }),
  });
  if (!res.ok) {
    handle401(res);
    throw new Error(`${res.status} ${res.statusText}`);
  }
  return res.blob();
}

// --- Corrections ---

export function saveCorrections(
  projectId: string,
  corrections: Correction[],
): Promise<{ saved: number; total: number }> {
  return patchJson(`/api/projects/${projectId}/corrections`, { corrections });
}

// --- Demo ---

export function loadDemoData(name: string): Promise<ProjectData> {
  return fetchJson(`/api/demo/${name}`);
}

// --- Dashboard ---

export function listDashboardProjects(): Promise<DashboardProject[]> {
  return fetchJson('/api/dashboard');
}

export function approveProject(
  projectId: string,
  body?: { corrected_fixtures?: unknown[]; corrected_keynotes?: unknown[] },
): Promise<DashboardProject> {
  return postJson(`/api/dashboard/approve/${projectId}`, body);
}

export function getDashboardProject(id: string): Promise<ProjectData> {
  return fetchJson(`/api/dashboard/${id}`);
}

export async function deleteDashboardProject(id: string): Promise<void> {
  const res = await fetch(`${BASE}/api/dashboard/${id}`, { method: 'DELETE', credentials: 'include' });
  if (!res.ok) {
    handle401(res);
    throw new Error(`${res.status} ${res.statusText}`);
  }
}

export function getDashboardExcelUrl(id: string): string {
  return `${BASE}/api/dashboard/${id}/export/excel`;
}

export function editDashboardProject(id: string): Promise<{ project_id: string; dashboard_id: string; source: string }> {
  return postJson(`/api/dashboard/${id}/edit`);
}

// --- Positions ---

export interface PagePositionsResponse {
  sheet_code?: string;
  page_width?: number;
  page_height?: number;
  fixture_positions?: Record<string, FixturePosition[]>;
  keynote_positions?: Record<string, FixturePosition[]>;
  positions?: null;
  reason?: string;
}

export function getPagePositions(projectId: string, pageNumber: number, sheetCode?: string): Promise<PagePositionsResponse> {
  const params = sheetCode ? `?sheet_code=${encodeURIComponent(sheetCode)}` : '';
  return fetchJson(`/api/projects/${projectId}/page/${pageNumber}/positions${params}`);
}

// --- Feedback ---

export function submitFeedback(
  projectId: string,
  correction: FixtureFeedback,
): Promise<{ project_id: string; correction_count: number; corrections: FixtureFeedback[] }> {
  return postJson(`/api/projects/${projectId}/feedback`, correction);
}

export function getFeedback(
  projectId: string,
): Promise<{ project_id: string; correction_count: number; corrections: FixtureFeedback[] }> {
  return fetchJson(`/api/projects/${projectId}/feedback`);
}

export async function removeFeedback(
  projectId: string,
  index: number,
): Promise<{ project_id: string; removed: FixtureFeedback; correction_count: number }> {
  const res = await fetch(`${BASE}/api/projects/${projectId}/feedback/${index}`, {
    method: 'DELETE',
    credentials: 'include',
  });
  if (!res.ok) {
    handle401(res);
    throw new Error(`${res.status} ${res.statusText}`);
  }
  return res.json();
}

export function reprocessProject(
  projectId: string,
): Promise<{ project_id: string; status: string }> {
  return postJson(`/api/projects/${projectId}/reprocess`);
}

// --- Fix It ---

export function interpretFixIt(projectId: string, text: string): Promise<FixItInterpretation> {
  return postJson(`/api/projects/${projectId}/fix-it/interpret`, { text });
}

export function confirmFixIt(projectId: string, actions: FixItAction[]): Promise<{ project_id: string; status: string; actions_applied: number }> {
  return postJson(`/api/projects/${projectId}/fix-it/confirm`, { actions });
}

// --- Chat ---

export function getChatHistory(projectId: string): Promise<{ messages: ChatMsg[] }> {
  return fetchJson(`/api/projects/${projectId}/chat/history`);
}

export function sendChatMessage(projectId: string, message: string): Promise<ChatResponse> {
  return postJson(`/api/projects/${projectId}/chat/message`, { message });
}

export function confirmChatActions(projectId: string, actions: FixItAction[]): Promise<{ project_id: string; status: string; actions_applied: number }> {
  return postJson(`/api/projects/${projectId}/chat/confirm`, { actions });
}

export function getChatSuggestions(projectId: string): Promise<{ suggestions: string[] }> {
  return fetchJson(`/api/projects/${projectId}/chat/suggestions`);
}

// --- SSE URL ---

export function getStatusStreamUrl(projectId: string): string {
  return `${BASE}/api/projects/${projectId}/status`;
}
