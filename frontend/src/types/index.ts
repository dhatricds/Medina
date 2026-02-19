export interface SheetIndexEntry {
  sheet_code: string;
  description: string;
  type: string;
}

export interface Fixture {
  code: string;
  description: string;
  fixture_style: string;
  voltage: string;
  mounting: string;
  lumens: string;
  cct: string;
  dimming: string;
  max_va: string;
  counts_per_plan: Record<string, number>;
  total: number;
}

export interface Keynote {
  keynote_number: string;
  keynote_text: string;
  counts_per_plan: Record<string, number>;
  total: number;
  fixture_references: string[];
}

export interface QAReport {
  overall_confidence: number;
  passed: boolean;
  threshold: number;
  stage_scores: Record<string, number>;
  warnings: string[];
  recommendations: string[];
}

export interface ProjectSummary {
  total_fixture_types: number;
  total_fixtures: number;
  total_lighting_plans: number;
  total_keynotes: number;
}

export interface PageEntry {
  page_number: number;
  sheet_code: string;
  description: string;
  type: string;
}

export interface ProjectData {
  project_name: string;
  total_pages?: number;
  pages?: PageEntry[];
  sheet_index: SheetIndexEntry[];
  lighting_plans: string[];
  schedule_pages: string[];
  fixtures: Fixture[];
  keynotes: Keynote[];
  summary: ProjectSummary;
  qa_report: QAReport | null;
}

export type AgentStatus = 'pending' | 'running' | 'completed' | 'error';

export interface AgentInfo {
  id: number;
  name: string;
  description: string;
  status: AgentStatus;
  stats: Record<string, string | number>;
  time?: number;
  flags?: string[];
}

export type AppState = 'empty' | 'demo' | 'files_selected' | 'processing' | 'complete' | 'error';

export interface Correction {
  type: 'lighting' | 'keynote';
  identifier: string;
  sheet: string;
  original: number;
  corrected: number;
}

export type CorrectionReason =
  | 'missed_embedded_schedule'
  | 'wrong_fixture_code'
  | 'extra_fixture'
  | 'missing_fixture'
  | 'vlm_misread'
  | 'wrong_bounding_box'
  | 'manual_count_edit'
  | 'other';

export interface FixtureFeedback {
  action: 'add' | 'remove' | 'update_spec' | 'count_override';
  fixture_code: string;
  reason: CorrectionReason;
  reason_detail: string;
  fixture_data?: Record<string, string | number>;
  spec_patches?: Record<string, string>;
}

export interface DashboardProject {
  id: string;
  name: string;
  approved_at: string;
  fixture_types: number;
  total_fixtures: number;
  keynote_count: number;
  plan_count: number;
  qa_score: number | null;
  qa_passed: boolean | null;
}

export interface FixturePosition {
  x0: number;
  top: number;
  x1: number;
  bottom: number;
  cx: number;
  cy: number;
}

export interface HighlightState {
  fixtureCode: string | null;
  keynoteNumber: string | null;
  targetSheetCode: string | null;
  positions: FixturePosition[];
  pageWidth: number;
  pageHeight: number;
  loading: boolean;
  /** Indices of positions the user flagged as incorrectly counted. */
  rejectedIndices: Set<number>;
  /** Plans where this item has count > 0 (for prev/next navigation). */
  availablePlans: string[];
  /** User-added marker positions (missed by pipeline). */
  addedPositions: FixturePosition[];
  /** Whether click-to-add mode is active. */
  addMode: boolean;
}

export type ViewMode = 'workspace' | 'dashboard' | 'dashboard_detail';
