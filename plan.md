# Medina Development Plan

## Phase 1: Project Setup
- [ ] Initialize git repository
- [ ] Create `pyproject.toml` with all dependencies
- [ ] Create `.gitignore` (exclude `data/`, `output/`, `.env`, etc.)
- [ ] Create `.env.example` with `MEDINA_ANTHROPIC_API_KEY=`
- [ ] Create directory structure: `src/medina/`, `tests/`, `notebooks/`, `output/`
- [ ] Create all `__init__.py` files
- [ ] Install dependencies with `uv`

## Phase 2: Core Data Models & Config
- [ ] `src/medina/models.py` — PageType, SheetIndexEntry, PageInfo, FixtureRecord (with `counts_per_plan`), KeyNote (with `counts_per_plan`), ConfidenceFlag, QAItemResult, QAReport, ExtractionResult (with `sheet_index` and `qa_report`)
- [ ] `src/medina/config.py` — MedinaConfig with pydantic-settings (include `qa_confidence_threshold`)
- [ ] `src/medina/exceptions.py` — Custom exception classes

## Phase 3: PDF Loading (Stage 1)
- [ ] `src/medina/pdf/loader.py` — Single PDF loading (pdfplumber)
- [ ] `src/medina/pdf/loader.py` — Folder loading with filename parsing
- [ ] `src/medina/pdf/loader.py` — Unified `load()` function that auto-detects input type
- [ ] `tests/test_loader.py` — Unit tests for both input types
- [ ] Validate with `sample/24031_15_Elec.pdf` and `data/Elk River Gym prints/`

## Phase 4: Sheet Index Discovery (Stage 2)
- [ ] `src/medina/pdf/sheet_index.py` — Parse cover/legend page for sheet index
- [ ] Support multiple index formats: table with lines, plain text list, two-column layout
- [ ] Extract `sheet_code` → `description` pairs
- [ ] Infer page types from description keywords ("LIGHTING PLAN" → LIGHTING_PLAN, etc.)
- [ ] Return `list[SheetIndexEntry]` with inferred types
- [ ] `tests/test_sheet_index.py` — Test against all 4 project types:
  - 24031_15_Elec.pdf (page 1 table)
  - Elk River Gym (cover sheet)
  - Johanna Fire (title sheet with "ELECTRICAL DRAWING INDEX")
  - Waterville (coversheet with two-column layout)
- [ ] Validate: correctly identifies all lighting plans and schedule pages from index

## Phase 5: Page Classification (Stage 3)
- [ ] `src/medina/pdf/classifier.py` — Use sheet index hints as **primary** classification source
- [ ] `src/medina/pdf/classifier.py` — Sheet code prefix rules (fallback when no index)
- [ ] `src/medina/pdf/classifier.py` — Filename-based classification for folder input
- [ ] `src/medina/pdf/classifier.py` — Content keyword-based classification (deepest fallback)
- [ ] `tests/test_classifier.py` — Tests for each classification method and priority order
- [ ] Validate: schedule pages correctly identified, lighting plans distinguished from demo plans

## Phase 6: Schedule Extraction (Stage 4)
- [ ] `src/medina/schedule/detector.py` — Find luminaire schedule tables (include/exclude keywords)
- [ ] `src/medina/schedule/extractor.py` — Table extraction with pdfplumber
- [ ] `src/medina/schedule/parser.py` — Column header mapping (fuzzy match)
- [ ] `src/medina/schedule/parser.py` — Handle merged header cells
- [ ] `tests/test_schedule_extractor.py` — Test with sample PDF E600 page
- [ ] Validate: extracted fixture records match `sample/lighting_inventory.xlsx` spec columns

## Phase 7: Fixture Counting — Per-Plan (Stage 5a)
- [ ] `src/medina/plans/text_counter.py` — Text element extraction with positions
- [ ] `src/medina/plans/text_counter.py` — Fixture code matching logic
- [ ] `src/medina/plans/text_counter.py` — Title block / notes exclusion zones
- [ ] Return `dict[str, int]` per plan page (fixture_code → count on THIS page)
- [ ] Process each lighting plan independently — never aggregate during counting
- [ ] `tests/test_text_counter.py` — Test against known per-plan fixture counts
- [ ] Validate: per-plan counts sum to correct totals

## Phase 8: Key Notes Extraction & Counting — Per-Plan (Stage 5b)
- [ ] `src/medina/plans/keynotes.py` — Locate "KEY NOTES:" section on each plan page
- [ ] `src/medina/plans/keynotes.py` — Parse numbered items and their text
- [ ] `src/medina/plans/keynotes.py` — Count how many times each keynote # appears per plan
- [ ] `src/medina/plans/keynotes.py` — Extract fixture code references within keynote text
- [ ] Return `dict[str, int]` per plan (keynote_number → count on this page)
- [ ] `tests/test_keynotes.py` — Test keynote parsing and per-plan counting

## Phase 9: QA Verification (Stage 6) — NEW
- [ ] `src/medina/qa/validator.py` — Cross-check extraction results
  - [ ] Schedule completeness check (all expected columns found?)
  - [ ] Text vs vision count agreement (when both methods run)
  - [ ] Zero-count fixture detection (schedule fixture found 0 times?)
  - [ ] Fixture code ambiguity check (could code match non-fixture text?)
  - [ ] Keynote consistency check across plans
  - [ ] Sheet index coverage check (all listed pages found?)
  - [ ] Total sanity check (counts plausible?)
- [ ] `src/medina/qa/confidence.py` — Compute confidence scores
  - [ ] Per-item confidence (per fixture, per keynote)
  - [ ] Per-stage confidence (schedule: 30%, counting: 40%, keynotes: 15%, sheet_index: 15%)
  - [ ] Overall weighted confidence score
  - [ ] Flag items below confidence threshold
- [ ] `src/medina/qa/report.py` — Generate QA report
  - [ ] Human-readable text report for CLI output
  - [ ] Structured data for Excel Sheet 3 and JSON `qa_report`
  - [ ] Pass/fail determination (default threshold: 95%)
  - [ ] Warnings and recommendations
- [ ] `tests/test_qa.py` — Test confidence scoring and validation checks
  - [ ] Test that perfect data → 100% confidence
  - [ ] Test that missing columns reduce confidence correctly
  - [ ] Test that text/vision mismatches flag properly
  - [ ] Test threshold pass/fail logic
- [ ] Validate: QA report catches known issues in sample data

## Phase 10: Output Generation (Stage 7)
- [ ] `src/medina/output/excel.py` — **Sheet 1: "Fixture Inventory"**
  - [ ] Dynamic columns: 9 fixed spec columns + N plan count columns + 1 total column
  - [ ] Plan column headers use sheet codes (e.g., "E200", "E1A", "E2B")
  - [ ] Named table `LightingInventory`, style `TableStyleMedium9`
  - [ ] Below table: 2 empty rows + compact "Key Notes Summary" section
- [ ] `src/medina/output/excel.py` — **Sheet 2: "Key Notes Inventory"**
  - [ ] Columns: keynote_number, keynote_text, {plan columns}, total
  - [ ] Named table `KeyNotesInventory`, same per-plan structure
- [ ] `src/medina/output/excel.py` — **Sheet 3: "QA Report"**
  - [ ] Overall confidence score, pass/fail, threshold
  - [ ] Per-stage scores table
  - [ ] Per-item confidence with flags
  - [ ] Color-coded: green (≥95%), yellow (80-95%), red (<80%)
- [ ] `src/medina/output/json_out.py` — **JSON for frontend**
  - [ ] Structured JSON with: sheet_index, lighting_plans, fixtures, keynotes, summary, qa_report
  - [ ] Designed for web UI rendering + "Export to Excel" button
  - [ ] Frontend can show QA confidence badge and highlight flagged items
- [ ] Validate: generated outputs consistent across Excel and JSON

## Phase 11: Pipeline & CLI
- [ ] `src/medina/pipeline.py` — Wire all 7 stages together
- [ ] `src/medina/pipeline.py` — Aggregation logic: compute totals from per-plan counts
- [ ] `src/medina/pipeline.py` — Run QA verification before output generation
- [ ] `src/medina/pipeline.py` — If QA fails (<95%), log warning + mark output as low-confidence
- [ ] `src/medina/cli.py` — Click commands: `process`, `classify`, `schedule`, `index`, `qa`
- [ ] `src/medina/cli.py` — `--qa-threshold` flag to override default 95%
- [ ] `tests/test_pipeline.py` — End-to-end test with sample PDF
- [ ] Validate: `python -m medina process sample/24031_15_Elec.pdf -o output/test.xlsx`
- [ ] Validate: `python -m medina process sample/24031_15_Elec.pdf --format json -o output/test.json`
- [ ] Validate: QA report included in both Excel and JSON output

## Phase 12: Vision Enhancement
- [ ] `src/medina/pdf/renderer.py` — Page-to-image at 300 DPI via PyMuPDF
- [ ] `src/medina/plans/vision_counter.py` — Claude Vision API for per-plan fixture counting
- [ ] `src/medina/schedule/extractor.py` — Add vision fallback for table extraction
- [ ] Update pipeline to support `--use-vision` flag
- [ ] Compare vision counts vs text counts — feed disagreements into QA as confidence flags
- [ ] Validate: QA text_vision_mismatch flag triggers correctly when counts differ

## Phase 13: Multi-Project Validation
- [ ] Test with `data/Elk River Gym prints/` (folder, 2 lighting plans: E1.11r, E1.11z)
  - [ ] Verify: 2 plan count columns + total in output
  - [ ] Verify: QA confidence > 95%
- [ ] Test with `data/Johanna Fire ELEC prints only/` (folder, 4 plans: E1A, E1B, E2A, E2B)
  - [ ] Verify: 4 plan count columns + total in output
  - [ ] Verify: keynotes counted separately per plan
  - [ ] Verify: QA confidence > 95%
- [ ] Test with `data/Waterville Fire station prints/` (folder, 2 plans: E301, E302)
  - [ ] Verify: panel schedules (E521) correctly excluded from luminaire extraction
  - [ ] Verify: QA confidence > 95%
- [ ] Test with `data/Electrical_DENTAL HYGIENE LAB EXPANSION plans.pdf` (single PDF)
- [ ] Test with DENIS standalone PDFs
- [ ] Fix edge cases discovered during validation
- [ ] Document per-project results, accuracy metrics, and QA confidence scores
- [ ] Tune QA weights and deduction amounts based on validation results

## Phase 14: Frontend Prep & Hardening
- [ ] Ensure JSON output structure is stable for frontend consumption
- [ ] Ensure QA report data is frontend-friendly (confidence badges, flag tooltips)
- [ ] Add progress reporting (logging + optional progress bar)
- [ ] Handle error cases gracefully (no schedule found, empty plans, corrupt PDFs)
- [ ] Add `--verbose` and `--debug` CLI flags
- [ ] Create `README.md` with usage instructions
- [ ] Final test pass on all data/ inputs — all must achieve > 95% QA confidence

---

## Team Structure for Implementation

When coding begins, use agent teams:
- **Team Lead** — orchestrates tasks, reviews integration
- **PDF Pipeline Agent** — Phases 3-5 (loading + sheet index discovery + classification)
- **Schedule Agent** — Phase 6 (schedule detection + extraction)
- **Counting Agent** — Phases 7-8 (per-plan fixture counting + per-plan keynote counting)
- **QA Agent** — Phase 9 (validation, confidence scoring, report generation)
- **Output Agent** — Phase 10 (multi-sheet Excel + JSON generation)

Agents can work in parallel on independent phases. Dependencies:
```
Phase 3 (loader) → Phase 4 (sheet index) → Phase 5 (classifier)
Phase 5 → Phase 6 (schedule extraction)
Phase 5 → Phase 7 (per-plan fixture counting) + Phase 8 (per-plan keynote counting)
Phases 6 + 7 + 8 → Phase 9 (QA verification)
Phase 9 → Phase 10 (output generation)
Phase 10 → Phase 11 (pipeline & CLI integration)
```

The QA Agent works AFTER extraction/counting is complete and BEFORE output generation.
If QA fails, the Output Agent still generates files but marks them as low-confidence.

## Success Criteria

1. Processing `sample/24031_15_Elec.pdf` produces output with per-plan columns (E200 + total)
2. All 3 folder-based projects in `data/` process without errors
3. Per-plan fixture counts sum correctly to the total column
4. Keynotes inventory table correctly counts occurrences per plan
5. Johanna Fire produces 4 plan count columns + total (E1A, E1B, E2A, E2B)
6. JSON output contains same data as Excel, structured for frontend
7. Processing time < 60 seconds per project (excluding vision API calls)
8. Clear error messages when schedules not found, no sheet index found, or pages unclassifiable
9. Sheet index correctly discovered from legend/cover page for all 4 test projects
10. **QA confidence > 95% for all test projects** (primary quality gate)
11. QA report correctly flags known issues (ambiguous codes, zero-count fixtures, etc.)
12. Low-confidence outputs are clearly marked in both Excel and JSON
