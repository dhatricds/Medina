import type { ProjectData, Correction, DashboardProject } from '../types';

const BASE = import.meta.env.VITE_API_URL ?? '';

export async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function patchJson<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
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
  const res = await fetch(`${BASE}/api/upload`, { method: 'POST', body: form });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
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

export function approveProject(projectId: string): Promise<DashboardProject> {
  return postJson(`/api/dashboard/approve/${projectId}`);
}

export function getDashboardProject(id: string): Promise<ProjectData> {
  return fetchJson(`/api/dashboard/${id}`);
}

export async function deleteDashboardProject(id: string): Promise<void> {
  const res = await fetch(`${BASE}/api/dashboard/${id}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
}

export function getDashboardExcelUrl(id: string): string {
  return `${BASE}/api/dashboard/${id}/export/excel`;
}

// --- SSE URL ---

export function getStatusStreamUrl(projectId: string): string {
  return `${BASE}/api/projects/${projectId}/status`;
}
