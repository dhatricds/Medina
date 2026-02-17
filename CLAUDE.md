# CLAUDE.md - Medina: Lighting Fixture Inventory Extraction System

## Project Overview

Medina is a Python-based system that automatically extracts lighting fixture inventory data from electrical construction drawing PDFs. It processes engineering plans to produce a structured inventory spreadsheet containing fixture types, specifications, and counts.

**Primary goal:** Given a set of electrical construction PDF drawings, produce an Excel/JSON inventory listing every lighting fixture type with its full specifications and total count across all plan pages.

## Problem Domain

Electrical construction drawings follow a standard structure:
- **Cover / Symbols / Abbreviations page** (e.g., E000, E0, CS): Defines all electrical symbols AND contains a **sheet index** (drawing list) that maps every sheet code to its description. This is the primary discovery mechanism for identifying which pages are lighting plans, schedules, demolition, etc.
- **Demolition plans** (e.g., E100-E102): Show existing items to remove
- **Lighting plans** (e.g., E200, E1A, E1B, E301, E302): Floor plans with fixture symbols and labels. A project may have **multiple lighting plan pages** (e.g., Johanna Fire has 4: E1A, E1B, E2A, E2B).
- **Power plans** (e.g., E300): Electrical power layout
- **Schedule pages** (e.g., E600, E7A-E7D, E501): Tables listing fixture specifications
- **Detail/compliance pages** (e.g., E8A, E8B): Construction details

### Sheet Index Discovery Strategy

The **first step** after loading pages is to find and parse the sheet index from the legend/abbreviations/cover page. This index tells the system exactly which pages to look at:

| Project | Index Location | Lighting Plans Found | Schedules Found |
|---------|---------------|---------------------|-----------------|
| 24031_15_Elec.pdf | Page 1 (E000) title block table | E200 | E600 |
| Elk River Gym | `001---CS COVER SHEET.pdf` | E1.11r, E1.11z | (none listed) |
| Johanna Fire | `077---E0 ELECTRICAL TITLE SHEET.pdf` | E1A, E1B, E2A, E2B | E7A-E7D |
| Waterville | `078---E001 ELECTRICAL COVERSHEET.pdf` | E301, E302 | E501 |

The system must locate the schedule tables, extract fixture data, then scan **each** lighting plan page independently to count how many of each fixture type appear on **each plan**, producing a per-plan breakdown plus a summarized total.

## Input Formats

### 1. Single Multi-Page PDF
A single PDF file containing all electrical sheets. Schedule pages are typically near the end.
Example: `24031_15_Elec.pdf` (9 pages, E000 through E600).

### 2. Folder of Individual PDFs
Each page is a separate PDF file. Naming convention:
```
[NUMBER]---[SHEET-CODE] [DESCRIPTION].pdf
```
Examples:
- `007---E1.11R GYM LIGHTING PLAN - ROGERS.pdf`
- `089---E7A ELECTRICAL SCHEDULES.pdf`

Schedule pages in folders often have "SCHEDULE" in the filename.

### Data Location
All input data is in `data/`:
```
data/
├── 24031_15_Elec.pdf                              # Single multi-page PDF
├── Electrical_DENTAL HYGIENE LAB EXPANSION plans.pdf
├── DENIS DENIS-2025-*.pdf                          # Multiple standalone PDFs
├── Extracted from 1. Anoka Dispensary Drawings.pdf
├── Elk River Gym prints/                           # Folder: 12 individual PDFs
├── Johanna Fire ELEC prints only/                  # Folder: 19 PDFs + 1 PNG
└── Waterville Fire station prints/                 # Folder: 18 individual PDFs
```

## Output Format

The system produces **two output formats**: an Excel workbook for download/review and a JSON file for frontend display. Both contain the same data.

### Excel Workbook Output

The workbook contains **two sheets**:

#### Sheet 1: "Fixture Inventory" (`LightingInventory` table)

The fixture table has **dynamic columns** — the number of columns depends on how many lighting plan pages are found in the project. Fixed spec columns come first, then one count column per lighting plan, then a total.

**Fixed columns (always present):**

| Column         | Description                                    | Example Value              |
|----------------|------------------------------------------------|----------------------------|
| `code`         | Fixture type identifier from schedule          | `A1`, `B6`, `D7`          |
| `description`  | Human-readable fixture description             | `2x4 LED lensed troffer`  |
| `fixture_style`| Fixture style (often uppercase of description) | `2X4 LED LENSED TROFFER`  |
| `voltage`      | Operating voltage                              | `120/277`                  |
| `mounting`     | Mounting type                                  | `LAY-IN GRID`, `RECESSED` |
| `lumens`       | Light output specification                     | `5000 LUM MIN`             |
| `cct`          | Correlated color temperature                   | `4000K`                    |
| `dimming`      | Dimming capability                             | `DIMMING 0-10V`            |
| `max_va`       | Maximum volt-amperes                           | `50 VA`                    |

**Dynamic count columns (one per lighting plan + total):**

| Column                | Description                              | Example Value |
|-----------------------|------------------------------------------|---------------|
| `{plan_sheet_code}`   | Count of this fixture on that plan page  | `12`          |
| ...                   | (one column per lighting plan found)     |               |
| `total`               | Sum of all plan columns                  | `46`          |

**Example with 4 lighting plans (Johanna Fire project):**
```
code | description       | ...specs... | E1A | E1B | E2A | E2B | total
A1   | LED troffer       | ...         |  8  |  6  |  5  |  3  |  22
B2   | round downlight   | ...         |  2  |  0  |  1  |  4  |   7
E3   | exit sign         | ...         |  1  |  2  |  1  |  1  |   5
```

**Example with 1 lighting plan (24031_15_Elec.pdf):**
```
code | description       | ...specs... | E200 | total
A1   | LED troffer       | ...         |  46  |  46
B6   | volumetric troffer| ...         |  26  |  26
```

**Below the fixture table** (separated by 2 empty rows), a **Key Notes Summary** section provides a compact view of keynote counts.

#### Sheet 2: "Key Notes Inventory" (`KeyNotesInventory` table)

Tracks how many times each keynote number appears across the lighting plans:

| Column              | Description                                  | Example Value                    |
|---------------------|----------------------------------------------|----------------------------------|
| `keynote_number`    | The keynote identifier                       | `1`, `2`, `3`                    |
| `keynote_text`      | Full text of the keynote                     | `CONNECT TO EXISTING CIRCUIT`    |
| `{plan_sheet_code}` | Count of this keynote on that plan (per plan)| `5`                              |
| ...                 | (one column per lighting plan found)         |                                  |
| `total`             | Sum of all plan columns                      | `12`                             |

**Example:**
```
keynote_number | keynote_text                    | E1A | E1B | E2A | E2B | total
1              | CONNECT TO EXISTING CIRCUIT     |  3  |  2  |  0  |  0  |   5
2              | PROVIDE RECEPTACLE FOR SYSTEM   |  1  |  1  |  1  |  1  |   4
3              | BASE BID: NO DEMOLITION...      |  0  |  0  |  1  |  0  |   1
```

### JSON Output (for frontend)

A structured JSON file for web frontend display, with the same data organized for easy rendering:

```json
{
  "project_name": "24031_15_Elec",
  "sheet_index": [
    {"sheet_code": "E000", "description": "ELECTRICAL SYMBOLS AND ABBREVIATIONS", "type": "symbols_legend"},
    {"sheet_code": "E200", "description": "LIGHTING PLAN - PARTIAL LOWER LEVEL", "type": "lighting_plan"},
    {"sheet_code": "E600", "description": "LIGHT FIXTURE AND ELECTRICAL SCHEDULES", "type": "schedule"}
  ],
  "lighting_plans": ["E200"],
  "schedule_pages": ["E600"],
  "fixtures": [
    {
      "code": "A1",
      "description": "2x4 LED lensed troffer",
      "fixture_style": "2X4 LED LENSED TROFFER",
      "voltage": "120/277",
      "mounting": "LAY-IN GRID",
      "lumens": "5000 LUM MIN",
      "cct": "4000K",
      "dimming": "DIMMING 0-10V",
      "max_va": "50 VA",
      "counts_per_plan": {"E200": 46},
      "total": 46
    }
  ],
  "keynotes": [
    {
      "keynote_number": "1",
      "keynote_text": "CONNECT TO EXISTING CIRCUIT.",
      "counts_per_plan": {"E200": 3},
      "total": 3,
      "fixture_references": ["A1"]
    }
  ],
  "summary": {
    "total_fixture_types": 13,
    "total_fixtures": 125,
    "total_lighting_plans": 1,
    "total_keynotes": 5
  },
  "qa_report": {
    "overall_confidence": 0.972,
    "passed": true,
    "threshold": 0.95,
    "stage_scores": {
      "sheet_index": 1.0,
      "schedule_extraction": 0.98,
      "fixture_counting": 0.955,
      "keynote_extraction": 0.96
    },
    "warnings": [
      "Fixture D7: found only 1 time — verify wet-location fixture count",
      "Fixture code E3: possible ambiguity with room label"
    ],
    "recommendations": [
      "Consider running --use-vision for E200 to cross-check text counts"
    ]
  }
}
```

The frontend can display this JSON directly and offer an "Export to Excel" button that triggers the Excel generation.

Reference output: `sample/lighting_inventory.xlsx`

## Architecture

### Technology Stack
- **Language:** Python 3.11+
- **Package management:** `uv` with `pyproject.toml`
- **PDF text extraction:** `pdfplumber` (primary), `PyMuPDF`/`fitz` (rendering)
- **Table extraction:** `pdfplumber` layout-based table detection
- **Vision analysis:** Anthropic Claude API (claude-sonnet) for plan page analysis
- **OCR fallback:** `pytesseract` + Tesseract for scanned/image-only PDFs
- **Data models:** `pydantic` v2
- **Excel output:** `openpyxl`
- **CLI:** `click`
- **Testing:** `pytest`

### Pipeline Architecture

The system follows a sequential pipeline with seven stages:

```
INPUT (PDF or Folder)
    │
    ▼
┌─────────────────────┐
│  Stage 1: LOAD      │  Load PDF pages, normalize to unified page list
│  pdf/loader.py      │  Handle both single-PDF and folder-of-PDFs input
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  Stage 2: DISCOVER   │  Parse legend/cover page for sheet index table
│  pdf/sheet_index.py  │  Extract sheet code → description → inferred type
│                      │  Pre-identify lighting plans and schedule pages
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  Stage 3: CLASSIFY   │  Classify each page by type using:
│  pdf/classifier.py   │  1) Sheet index hints (primary, from Stage 2)
│                      │  2) Title block content (bottom-right crop)
│                      │  3) Sheet code prefix rules (fallback)
│                      │  4) Content keyword scan (deepest fallback)
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  Stage 4: SCHEDULE   │  Find luminaire schedule tables on schedule pages
│  schedule/           │  Extract fixture records (code + all spec columns)
│    detector.py       │  IGNORE: panel/motor/equipment schedules
│    extractor.py      │  VLM fallback for image-based/rasterized schedules
│    parser.py         │
│    vlm_extractor.py  │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  Stage 5: COUNT      │  Scan EACH lighting plan page independently
│  plans/              │  Count fixtures PER PLAN (not aggregated)
│    text_counter.py   │  Count keynotes via geometric shape detection
│    vision_counter.py │  VLM fallback when geometric detection finds zeros
│    keynotes.py       │  Build per-plan breakdown: {sheet_code: {code: count}}
│  vision_keynote_     │
│    counter.py        │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  Stage 6: QA         │  Verify extraction results — confidence must be > 95%
│  qa/                 │  Cross-check text vs vision counts
│    validator.py      │  Validate schedule completeness
│    confidence.py     │  Flag low-confidence items for review
│    report.py         │  Generate QA report with per-stage scores
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  Stage 7: OUTPUT     │  Merge schedule data with per-plan counts
│  output/             │  Generate multi-sheet Excel workbook
│    excel.py          │  Generate JSON for frontend display
│    json_out.py       │  Sheet 1: Fixture Inventory (per-plan + total)
│                      │  Sheet 2: Key Notes Inventory (per-plan + total)
│                      │  Sheet 3: QA Report (confidence scores + flags)
└─────────────────────┘
```

### Directory Structure

```
Medina/
├── CLAUDE.md                    # This file
├── plan.md                      # Development plan and phases
├── README.md
├── pyproject.toml
├── .python-version
├── .gitignore
├── .env.example                 # Template for API keys
├── run_server.py                # FastAPI backend launcher (handles PYTHONPATH)
├── data/                        # Input PDFs (gitignored)
├── requirements/                # Business requirements
├── sample/                      # Reference input/output
│   ├── 24031_15_Elec.pdf
│   └── lighting_inventory.xlsx
├── demo_data/                   # Demo JSON files for frontend
│   ├── hcmc_inventory.json
│   └── anoka_inventory.json
├── frontend/                    # React + Tailwind web UI (Vite + TypeScript)
│   ├── vite.config.ts           # Vite 5 config, proxy /api → localhost:8000
│   ├── tailwind.config.js       # Tailwind v3 with custom Medina colors
│   ├── postcss.config.js
│   ├── index.html
│   ├── public/demo/             # Static demo JSON (hcmc.json, anoka.json)
│   └── src/
│       ├── App.tsx              # Root — useAgentProgress, panel layout
│       ├── main.tsx
│       ├── index.css            # Tailwind directives
│       ├── types/index.ts       # TS interfaces matching pipeline JSON
│       ├── store/projectStore.ts # Zustand store (state, actions, SSE)
│       ├── api/client.ts        # Fetch wrapper for all API endpoints
│       ├── hooks/
│       │   ├── useAgentProgress.ts  # SSE subscription for agent events
│       │   └── useTableEdits.ts     # Track cell corrections
│       └── components/
│           ├── layout/          # TopBar, BottomBar, ThreePanel
│           ├── pdf/             # UploadZone, PdfViewer
│           ├── agents/          # AgentPipeline, AgentCard
│           ├── tables/          # TabContainer, FixtureTable, KeynoteTable, EditableCell
│           ├── qa/              # WarningModal
│           └── upload/          # SourcePicker
├── src/
│   └── medina/
│       ├── __init__.py
│       ├── cli.py               # Click CLI entry point
│       ├── config.py            # Settings via pydantic-settings
│       ├── exceptions.py        # Custom exceptions (VisionAPIError, etc.)
│       ├── models.py            # All Pydantic data models
│       ├── pipeline.py          # Orchestrates all stages
│       ├── pdf/
│       │   ├── __init__.py
│       │   ├── loader.py        # PDF/folder loading + addendum deduplication
│       │   ├── sheet_index.py   # Parse sheet index from legend/cover page
│       │   ├── classifier.py    # Page type classification
│       │   └── renderer.py      # Page-to-image conversion
│       ├── schedule/
│       │   ├── __init__.py
│       │   ├── detector.py      # Locate schedule pages and tables
│       │   ├── extractor.py     # Raw table cell extraction
│       │   ├── parser.py        # Map raw cells to FixtureRecord models
│       │   └── vlm_extractor.py # VLM fallback for image-based schedules
│       ├── plans/
│       │   ├── __init__.py
│       │   ├── text_counter.py  # Fixture counting + schedule table & crossref filtering
│       │   ├── vision_counter.py# Fixture counting via Claude vision API
│       │   ├── keynotes.py      # Key notes extraction + geometric shape detection
│       │   └── vision_keynote_counter.py  # VLM fallback for keynote counting
│       ├── qa/
│       │   ├── __init__.py
│       │   ├── validator.py     # Cross-check and validate extraction results
│       │   ├── confidence.py    # Compute per-item and overall confidence scores
│       │   └── report.py        # Generate QA report
│       ├── output/
│       │   ├── __init__.py
│       │   ├── excel.py         # Excel workbook generation
│       │   └── json_out.py      # JSON output generation
│       ├── api/                 # FastAPI web backend
│       │   ├── __init__.py
│       │   ├── main.py          # FastAPI app, CORS, router registration
│       │   ├── models.py        # Request/response Pydantic schemas
│       │   ├── projects.py      # In-memory ProjectState store
│       │   ├── orchestrator_wrapper.py  # Wraps agent runs with SSE events
│       │   └── routes/
│       │       ├── sources.py   # GET /api/sources (list data/ folder)
│       │       ├── upload.py    # POST /api/upload (single/multi-file)
│       │       ├── processing.py # POST /run, GET /status (SSE), POST /from-source
│       │       ├── results.py   # GET /api/projects/{id}/results
│       │       ├── pages.py     # GET /api/projects/{id}/page/{n} (PNG)
│       │       ├── export.py    # GET /api/projects/{id}/export/excel
│       │       ├── corrections.py # PATCH /api/projects/{id}/corrections
│       │       └── demo.py      # GET /api/demo/{name}
│       └── team/                # Expert Contractor Agent Team
│           ├── __init__.py
│           ├── orchestrator.py  # Team workflow coordinator (parallel count+keynote)
│           ├── run_search.py    # Agent 1: Load, discover, classify (Stages 1-3)
│           ├── run_schedule.py  # Agent 2: Schedule extraction (Stage 4)
│           ├── run_count.py     # Agent 3: Fixture counting per plan (Stage 5a)
│           ├── run_keynote.py   # Agent 4: Keynote extraction + counting (Stage 5b)
│           └── run_qa.py        # Agent 5: QA review + output generation (Stages 6-7)
├── tests/
│   ├── conftest.py
│   ├── test_loader.py
│   ├── test_classifier.py
│   ├── test_schedule_extractor.py
│   ├── test_text_counter.py
│   ├── test_pipeline.py
│   └── fixtures/                # Small test PDFs
├── notebooks/                   # Jupyter exploration notebooks
└── output/                      # Generated results (gitignored)
```

## Expert Contractor Agent Team Architecture

The pipeline can be run as a team of 5 specialized agents that mirror how a real electrical contractor works through construction drawings for estimation. Located in `src/medina/team/`.

### Agent Roles

| # | Agent | Role | Stages | Modules Used |
|---|-------|------|--------|-------------|
| 1 | **search-agent** (Page Navigator) | Opens drawings, finds sheet index, classifies all pages | 1-3 (Load, Discover, Classify) | `pdf/loader.py`, `pdf/sheet_index.py`, `pdf/classifier.py` |
| 2 | **schedule-agent** (Schedule Reader) | Reads luminaire schedule table, creates fixture inventory with specs | 4 (Schedule) | `schedule/parser.py`, `schedule/extractor.py`, `schedule/vlm_extractor.py` |
| 3 | **count-agent** (Plan Counter) | Goes through each plan page counting fixture symbols | 5a (Fixture Counting) | `plans/text_counter.py`, `plans/vision_counter.py` |
| 4 | **keynote-agent** (Keynote Analyzer) | Reads keynotes, counts geometric callout symbols | 5b (Keynote Extraction) | `plans/keynotes.py`, `plans/vision_keynote_counter.py` |
| 5 | **qa-agent** (Senior Reviewer) | Reviews all work, validates, generates final output | 6-7 (QA, Output) | `qa/confidence.py`, `qa/validator.py`, `output/excel.py`, `output/json_out.py` |

### Execution Flow

```
search-agent (LOAD → DISCOVER → CLASSIFY)
    │
    ▼
schedule-agent (SCHEDULE EXTRACTION)
    │
    ├──── count-agent (FIXTURE COUNTING)     ─┐
    │                                          ├── parallel
    └──── keynote-agent (KEYNOTE ANALYSIS)   ─┘
            │
            ▼
qa-agent (QA REVIEW + OUTPUT)
```

**Key parallelization:** count-agent and keynote-agent run in parallel via `ThreadPoolExecutor` since they both only need plan pages and fixture codes but don't depend on each other.

### Data Flow Between Agents

Intermediate results are saved as JSON to a shared work directory (`output/team_work_{project}/`):

| File | Producer | Consumer | Contents |
|------|----------|----------|----------|
| `search_result.json` | search-agent | schedule, count, keynote | Pages, sheet index, plan/schedule codes |
| `schedule_result.json` | schedule-agent | count, keynote, qa | Fixture records, fixture codes |
| `count_result.json` | count-agent | qa | Per-plan fixture counts |
| `keynote_result.json` | keynote-agent | qa | Keynotes with per-plan counts |

### CLI Usage

```bash
# Run the team orchestrator
uv run python -m medina.team.orchestrator data/24031_15_Elec.pdf --output output/hcmc

# Run via CLI
python -m medina team data/24031_15_Elec.pdf -o output/hcmc

# Run individual stages
uv run python -m medina.team.run_search data/24031_15_Elec.pdf output/work_dir
uv run python -m medina.team.run_schedule data/24031_15_Elec.pdf output/work_dir
uv run python -m medina.team.run_count data/24031_15_Elec.pdf output/work_dir
uv run python -m medina.team.run_keynote data/24031_15_Elec.pdf output/work_dir
uv run python -m medina.team.run_qa data/24031_15_Elec.pdf output/work_dir output/inventory
```

### Team Validation Results

| Project | Fixtures | Keynotes | QA | Time |
|---------|----------|----------|-----|------|
| HCMC (24031_15_Elec) | 13 types, 125 total | #1=6, #2=1, #3=1 | 98.0% PASS | ~85s |
| Anoka Dispensary | 10 types, 59 total | #1=4, #2=1 | 97.0% PASS | ~43s |

## Core Data Models

Defined in `src/medina/models.py`:

```python
class PageType(str, Enum):
    SYMBOLS_LEGEND = "symbols_legend"
    LIGHTING_PLAN = "lighting_plan"
    DEMOLITION_PLAN = "demolition_plan"
    POWER_PLAN = "power_plan"
    SCHEDULE = "schedule"
    DETAIL = "detail"
    COVER = "cover"
    SITE_PLAN = "site_plan"
    FIRE_ALARM = "fire_alarm"
    RISER = "riser"
    OTHER = "other"

class SheetIndexEntry(BaseModel):
    """A single entry from the sheet index found on the legend/cover page."""
    sheet_code: str              # e.g., "E200", "E1A", "E7A"
    description: str             # e.g., "LIGHTING PLAN - PARTIAL LOWER LEVEL"
    inferred_type: PageType | None = None  # Inferred from description keywords

class PageInfo(BaseModel):
    page_number: int
    sheet_code: str | None
    sheet_title: str | None
    page_type: PageType
    source_path: Path
    pdf_page_index: int

class FixtureRecord(BaseModel):
    """A single fixture type extracted from a luminaire schedule.
    Counts are tracked per lighting plan page, not as a single aggregate."""
    code: str
    description: str
    fixture_style: str
    voltage: str
    mounting: str
    lumens: str
    cct: str
    dimming: str
    max_va: str
    counts_per_plan: dict[str, int] = {}   # {sheet_code: count} e.g. {"E1A": 8, "E1B": 6}
    total: int = 0                          # Sum of all plan counts

class KeyNote(BaseModel):
    """A key note extracted from plan pages.
    Counts track how many times this keynote appears on each plan page."""
    number: int | str
    text: str
    counts_per_plan: dict[str, int] = {}   # {sheet_code: count} e.g. {"E1A": 3, "E1B": 2}
    total: int = 0                          # Sum of all plan counts
    fixture_references: list[str] = []      # Fixture codes referenced by this keynote

class ConfidenceFlag(str, Enum):
    """Reasons why a QA check may lower confidence."""
    TEXT_VISION_MISMATCH = "text_vision_mismatch"       # Text and vision counts disagree
    LOW_TEXT_QUALITY = "low_text_quality"                # PDF text layer is sparse/garbled
    MISSING_SCHEDULE_COLUMNS = "missing_schedule_cols"  # Expected columns not found
    FIXTURE_NOT_ON_ANY_PLAN = "fixture_not_on_plan"     # Schedule fixture found 0 times
    AMBIGUOUS_CODE_MATCH = "ambiguous_code_match"       # Fixture code could match other text
    KEYNOTE_PARSE_UNCERTAIN = "keynote_parse_uncertain" # Keynote format not standard
    SHEET_INDEX_INCOMPLETE = "sheet_index_incomplete"    # Index missing expected entries

class QAItemResult(BaseModel):
    """QA result for a single fixture or keynote."""
    item_code: str                     # Fixture code or keynote number
    confidence: float                  # 0.0 to 1.0
    flags: list[ConfidenceFlag] = []   # Reasons for reduced confidence
    text_count: int | None = None      # Count from text extraction
    vision_count: int | None = None    # Count from vision (if run)
    notes: str = ""                    # Human-readable QA note

class QAReport(BaseModel):
    """Overall QA report for the entire extraction."""
    overall_confidence: float          # 0.0 to 1.0 — must be > 0.95 to pass
    passed: bool                       # True if overall_confidence > threshold
    threshold: float = 0.95            # Configurable confidence threshold
    stage_scores: dict[str, float]     # Per-stage confidence: {"schedule": 0.98, "counting": 0.92, ...}
    fixture_results: list[QAItemResult]
    keynote_results: list[QAItemResult]
    warnings: list[str]                # Human-readable warnings
    recommendations: list[str]         # Suggested actions if confidence is low

class ExtractionResult(BaseModel):
    """Complete result of processing a document set."""
    source: str
    sheet_index: list[SheetIndexEntry]      # Parsed from legend/cover page
    pages: list[PageInfo]
    fixtures: list[FixtureRecord]
    keynotes: list[KeyNote]
    schedule_pages: list[str]               # Sheet codes of schedule pages found
    plan_pages: list[str]                   # Ordered list of lighting plan sheet codes
    qa_report: QAReport | None = None       # QA verification results
```

## Technical Approach

### Stage 2: Sheet Index Discovery (`pdf/sheet_index.py`)

Parse the legend/abbreviations/cover page to extract the drawing list:

**Where to find the sheet index:**
- Single PDF: Page 1 (typically E000 or cover) — look for a table or structured list
- Folder input: First file (cover sheet, e.g., `001---CS COVER SHEET.pdf`) or symbols page (e.g., `004---E000`)

**Sheet index format varies by project:**
- **Table with lines** (most common) — Extract using `pdfplumber.extract_tables()`
- **Plain text list** — Parse "CODE DESCRIPTION" lines using regex
- **Two-column layout** — "SHEET NAME | SHEET NUMBER" or "NUMBER | DESCRIPTION"

**Parsing approach:**
```python
def parse_sheet_index(page) -> list[SheetIndexEntry]:
    # 1. Try table extraction first
    tables = page.extract_tables(...)
    if tables:
        return parse_table_index(tables)
    # 2. Fall back to text-based parsing
    text = page.extract_text()
    return parse_text_index(text)
```

**Infer page types from descriptions:**
```
"LIGHTING PLAN" in description    → LIGHTING_PLAN
"SCHEDULE" in description         → SCHEDULE
"DEMO" in description             → DEMOLITION_PLAN
"SYMBOL" or "ABBREVIATION"        → SYMBOLS_LEGEND
"POWER" in description            → POWER_PLAN
```

### Stage 3: Page Classification (`pdf/classifier.py`)

Classify each page using **four sources in priority order**:

**Priority 1: Sheet index hints** (from Stage 2, when available):
- Match page's sheet code against the index entries
- Use the `inferred_type` from the index as the classification

**Priority 2: Title block content** (most reliable self-description):
- Crop the bottom-right ~25% of the page (title block area)
- Collapse newlines to spaces (handles multi-line titles like "ELECTRICAL SITE\nPLAN" -> "electrical site plan")
- Check against keywords in strict priority order:
  1. demolition, demo plan -> DEMOLITION_PLAN
  2. site plan, site layout, photometric -> SITE_PLAN
  3. lighting plan, lighting layout -> LIGHTING_PLAN
  4. luminaire/fixture/lighting schedule -> SCHEDULE
  5. electrical symbols, abbreviation, legend -> SYMBOLS_LEGEND
  6. power plan/layout -> POWER_PLAN
  7. fire alarm -> FIRE_ALARM
  8. riser diagram/riser -> RISER
  9. detail -> DETAIL
  10. cover sheet, title sheet -> COVER
- **Critical:** Site plan keywords must be checked BEFORE lighting plan to avoid misclassifying "PHOTOMETRIC SITE PLAN" as a lighting plan.

**Priority 3: Sheet code prefix mapping** (fallback):
```
E0xx                     -> SYMBOLS_LEGEND
CS                       -> COVER
E1xx (default LIGHTING)  -> LIGHTING_PLAN (disambiguate: "demo" -> DEMOLITION)
E2xx (default LIGHTING)  -> LIGHTING_PLAN (disambiguate: "power"/"signal"/"demo")
E3xx                     -> POWER_PLAN (disambiguate: "lighting")
E4xx                     -> POWER_PLAN
E5xx, E6xx, E7xx         -> SCHEDULE
E8xx                     -> DETAIL
```

**Priority 4: Full-page content keyword scan** (deepest fallback):
- Removes cross-reference text (e.g., "SEE SHEET FOR SCHEDULE") to prevent misclassification of lighting plans that reference schedule pages.

**Schedule detection keywords:**
```
INCLUDE: "Luminaire Schedule", "Light Fixture Schedule",
         "Lighting Schedule", "Fixture Schedule"

EXCLUDE: "Panel Schedule", "Motor Schedule", "Equipment Schedule",
         "Floorbox/Poke Thru Schedule"
```

### Stage 4: Schedule Table Extraction

**Primary:** `pdfplumber` table extraction with line-based detection:
```python
tables = page.extract_tables(table_settings={
    "vertical_strategy": "lines",
    "horizontal_strategy": "lines",
    "snap_tolerance": 5,
    "join_tolerance": 5,
})
```

**Column header variations to handle:**
- code: "TYPE", "FIXTURE TYPE", "FIXTURE", "SYMBOL", "TAG"
- description: "DESCRIPTION", "FIXTURE DESCRIPTION"
- voltage: "VOLTAGE", "VOLTS", "V"
- mounting: "MOUNTING", "MOUNT", "MTG"
- lumens: "LUMENS", "LUM", "LIGHT OUTPUT"
- cct: "CCT", "COLOR TEMP", "COLOR TEMPERATURE"
- dimming: "DIMMING", "DIM", "BALLAST DRIVER"
- max_va: "MAX VA", "VA", "WATTS", "WATTAGE"

**Fallback — VLM schedule extraction (`schedule/vlm_extractor.py`):**
- Triggered when pdfplumber finds no fixtures but schedule pages exist (any page type — not just image-based)
- Renders the schedule page at 150 DPI (must stay under 5MB base64 API limit)
- Sends to Claude Vision API with structured prompt to extract fixture table data
- Post-processes VLM results: `_looks_like_panel_schedule()` rejects entries with mostly numeric codes (>60%, >5 entries)
- Used for scanned/image-only PDFs and pages with non-standard table formats

### Stage 5: Fixture & Key Note Counting (Per-Plan)

Each lighting plan page is processed **independently**. Results are stored as `{sheet_code: {fixture_code: count}}` — never aggregated during counting. Totals are computed only at the output stage.

**Primary — text-based counting (`text_counter.py`):**
- Extract all text elements with positions via `pdfplumber`
- Match against known fixture codes from schedule
- Return `dict[str, int]` for each plan page (fixture_code → count on this page)
- **Exclude zones:** title block (rightmost ~25%), border area, notes sections

**Fallback — vision-based counting (`vision_counter.py`):**
- Render page at 300 DPI via `PyMuPDF`
- Send to Claude Vision with structured prompt listing fixture codes to find
- Parse JSON response with per-code counts for this single page

**Key notes extraction & counting (`keynotes.py`):**
- Look for "KEY NOTES:" / "KEYED NOTES:" section in right portion of each plan page
- Extract numbered items and their text
- **Primary counting: Geometric shape detection** — uses pdfplumber line geometry to detect numbers enclosed by diamond/hexagon shapes:
  1. Extract all standalone number characters with positions and font heights
  2. For each candidate number, check if surrounding line endpoints form a geometric enclosure in all 4 quadrants (TR, BR, BL, TL) within an inner_r=2 to outer_r=10 pixel radius
  3. Two-step filtering: first find the modal `font_h` from high-confidence candidates (4/4 quadrants), then count all candidates with >= 3 quadrants AND matching `font_h`
  4. This eliminates false positives from circuit numbers, room numbers, and dimensions
- **Fallback: text-only counting** — regex-based pattern matching when no lines are present on the page
- **VLM fallback (`plans/vision_keynote_counter.py`)** — only triggered when geometric detection finds ALL ZERO counts for a plan page. Sends two cropped images (legend area + drawing area) to Claude Vision API
- Return `dict[str, int]` per plan (keynote_number → count on this page)
- Parse for fixture code references within keynote text

**Validated keynote counting accuracy:**
| Project | Ground Truth | Pipeline Result | Match |
|---------|-------------|-----------------|-------|
| HCMC    | #1=6, #2=1, #3=1 | #1=6, #2=1, #3=1 | Exact |
| Anoka   | #1=4, #2=1 | #1=4, #2=1 | Exact |

**Aggregation (in `pipeline.py`):**
```python
# After counting all plans independently:
for fixture in fixtures:
    fixture.counts_per_plan = {
        plan_code: plan_counts.get(fixture.code, 0)
        for plan_code, plan_counts in all_plan_counts.items()
    }
    fixture.total = sum(fixture.counts_per_plan.values())

# Same for keynotes:
for keynote in keynotes:
    keynote.counts_per_plan = {
        plan_code: plan_keynote_counts.get(keynote.number, 0)
        for plan_code, plan_keynote_counts in all_keynote_counts.items()
    }
    keynote.total = sum(keynote.counts_per_plan.values())
```

### Stage 6: QA Verification (`qa/`)

Every extraction run goes through a QA stage that computes confidence scores and flags issues. The pipeline **only produces final output if overall confidence exceeds 95%** (configurable). If confidence is below threshold, the system outputs a QA report with warnings and recommendations instead of (or alongside) the inventory.

**Validator (`qa/validator.py`):**

Runs cross-checks on the extracted data:

| Check | What it validates | Confidence impact |
|-------|-------------------|-------------------|
| **Schedule completeness** | All expected columns found? Any empty rows? | -5% per missing column |
| **Text vs vision agreement** | If both methods ran, do counts match? | -10% per fixture with >20% disagreement |
| **Zero-count fixtures** | Any schedule fixtures found 0 times on all plans? | -3% per zero-count (may be valid for alternates) |
| **Fixture code ambiguity** | Could a code match non-fixture text (e.g., room "E3")? | -5% per ambiguous code |
| **Keynote consistency** | Same keynotes found on all plans where expected? | -2% per inconsistency |
| **Sheet index coverage** | Did we find all pages listed in the sheet index? | -5% if pages missing |
| **Total sanity check** | Are per-plan counts plausible (not 0 everywhere, not absurdly high)? | -10% if suspicious |

**Confidence scorer (`qa/confidence.py`):**

```python
def compute_confidence(result: ExtractionResult) -> QAReport:
    """Compute per-item and overall confidence scores.

    Overall confidence = weighted average of stage scores:
      - schedule_extraction: 30% weight
      - fixture_counting: 40% weight
      - keynote_extraction: 15% weight
      - sheet_index: 15% weight

    Each stage starts at 1.0 and deductions are applied per check.
    """
```

**QA report (`qa/report.py`):**

Generates a human-readable report:
```
═══════════════════════════════════════════
  MEDINA QA REPORT — 24031_15_Elec.pdf
═══════════════════════════════════════════
  Overall Confidence: 97.2%  ✅ PASSED (threshold: 95%)

  Stage Scores:
    Sheet Index Discovery:  100.0%  ✅
    Schedule Extraction:     98.0%  ✅
    Fixture Counting:        95.5%  ✅
    Keynote Extraction:      96.0%  ✅

  Flags:
    ⚠ Fixture D7: found only 1 time — verify wet-location fixture count
    ⚠ Fixture code E3: possible ambiguity with room label "E3"

  Recommendations:
    - Consider running --use-vision for E200 to cross-check text counts
═══════════════════════════════════════════
```

**When confidence < 95%:**
- Pipeline logs a WARNING with the QA report
- Output files are still generated but include a "⚠ LOW CONFIDENCE" marker
- JSON output includes `qa_report.passed = false`
- Excel gets a **Sheet 3: "QA Report"** with the full confidence breakdown
- CLI returns exit code 1 (non-zero) to signal QA failure

**When confidence ≥ 95%:**
- Pipeline logs INFO with confidence score
- Output files generated normally
- JSON includes `qa_report.passed = true`
- Excel Sheet 3 still included for transparency

### Stage 7: Output

**Excel output (`excel.py`):**
- **Sheet 1 "Fixture Inventory"**: Named table `LightingInventory`, style `TableStyleMedium9`
  - Dynamic columns: 9 fixed spec columns + N plan count columns + 1 total column
  - Plan column headers use sheet codes (e.g., "E200", "E1A", "E2B")
  - After the table: 2 empty rows, then a compact "Key Notes Summary" section
- **Sheet 2 "Key Notes Inventory"**: Named table `KeyNotesInventory`
  - Columns: keynote_number, keynote_text, {plan columns}, total
  - Same per-plan structure as the fixture table
- **Sheet 3 "QA Report"**: Named table `QAReport`
  - Overall confidence score and pass/fail status
  - Per-stage confidence scores
  - Per-fixture and per-keynote confidence with flags
  - Warnings and recommendations
  - Color-coded: green (≥95%), yellow (80-95%), red (<80%)
- Column widths auto-sized. Row stripes enabled.

**JSON output (`json_out.py`):**
- Structured JSON file containing: `sheet_index`, `lighting_plans`, `schedule_pages`, `fixtures` (with `counts_per_plan`), `keynotes` (with `counts_per_plan`), `summary` totals, and `qa_report` (with confidence scores, flags, and pass/fail)
- Designed for frontend consumption — can be rendered directly in a web UI
- Frontend can display QA confidence as a badge/indicator and highlight flagged items
- Frontend can offer "Export to Excel" button that triggers the Excel generation

## Key Conventions

### Code Style
- Python 3.11+ with full type annotations
- `from __future__ import annotations` in all modules
- Pydantic v2 models (use `model_validate`, not `parse_obj`)
- `pathlib.Path` for all file paths
- `logging` module — one logger per module: `logger = logging.getLogger(__name__)`
- Google-style docstrings
- Max line length: 100 characters

### Error Handling
- Never silently swallow exceptions
- Log warnings for non-critical issues
- `ValueError` for invalid input
- `RuntimeError` for processing failures
- Custom exceptions in `src/medina/exceptions.py`

### Configuration
`pydantic-settings` based config with `MEDINA_` env prefix:
- `anthropic_api_key`, `vision_model`, `render_dpi`
- `use_vision_counting` (default False — text-based first)
- `schedule_include` / `schedule_exclude` keyword lists
- `output_format` ("excel", "json", "both")
- `qa_confidence_threshold` (default 0.95 — minimum confidence to pass QA)
- `qa_fail_action` ("warn", "error", "both") — what to do when QA fails

### Naming Conventions
- Files: `snake_case.py`
- Classes: `PascalCase`
- Functions: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Tests: `test_<module>_<scenario>()`

## CLI Usage

```bash
# Process a single PDF
python -m medina process data/24031_15_Elec.pdf -o output/inventory.xlsx

# Process a folder of PDFs
python -m medina process "data/Elk River Gym prints/" -o output/elk_river.xlsx

# Process with vision-based counting
python -m medina process data/24031_15_Elec.pdf --use-vision -o output/inventory.xlsx

# Output as JSON
python -m medina process data/24031_15_Elec.pdf --format json -o output/inventory.json

# Classify pages only (diagnostic)
python -m medina classify data/24031_15_Elec.pdf

# Extract schedule only (diagnostic)
python -m medina schedule data/24031_15_Elec.pdf
```

## Testing

### Test Data
- `sample/24031_15_Elec.pdf` — primary integration test reference
- `sample/lighting_inventory.xlsx` — expected output (ground truth)
- `tests/fixtures/` — small synthetic PDFs for unit tests

### Running Tests
```bash
pytest tests/ -m "not slow"              # Fast tests only
pytest tests/ -m "not requires_api_key"  # Without vision tests
MEDINA_ANTHROPIC_API_KEY=sk-... pytest   # Full suite
```

## Important File Paths

| Path | Purpose |
|------|---------|
| `sample/24031_15_Elec.pdf` | Primary development reference PDF |
| `sample/lighting_inventory.xlsx` | Expected output format (ground truth) |
| `requirements/Requirement_Unnderstanding.docx` | Business requirements |
| `data/` | All input PDFs (gitignored) |
| `src/medina/models.py` | Core data models — build first |
| `src/medina/pipeline.py` | Main orchestration |

## Implementation Status

### Completed and Validated
- **Stage 1 (LOAD)**: Single PDF and folder-of-PDFs loading working. Folder loader deduplicates by title-block sheet code (keeps latest revision, e.g., ADDM1 replaces original).
- **Stage 2 (DISCOVER)**: Sheet index discovery from tables and text
- **Stage 3 (CLASSIFY)**: 4-priority classification chain with title block analysis
- **Stage 4 (SCHEDULE)**: pdfplumber table extraction + VLM fallback for any schedule page where pdfplumber finds 0 fixtures. Combo pages supported (schedule tables embedded in plan pages). Parser maps "LUMINAIRE TYPE" → description, "LUMEN/WATTS" → lumens. Panel schedule tables detected and rejected via keyword matching ("PANEL A/B", "circuit description"), regex header detection, and post-parse numeric code validation.
- **Stage 5 (COUNT)**: Text-based fixture counting with schedule table exclusion (combo pages) and cross-reference filtering (fixture codes matching sheet codes). Geometric keynote counting with "KEYED SHEET NOTES" pattern support. Validated exact match on HCMC and Anoka keynotes.
- **Stage 6 (QA)**: Confidence scoring with per-stage breakdown
- **Stage 7 (OUTPUT)**: Excel and JSON generation with dynamic columns
- **Web UI**: React + Tailwind frontend with FastAPI backend. 3-panel layout (PDF viewer | Agent pipeline | Editable tables). Demo mode, library source picker, file upload, SSE agent progress, editable cells.

### Validated Projects
| Project | Type | Plans | Schedules | Fixtures | Keynotes | QA | Notes |
|---------|------|-------|-----------|----------|----------|-----|-------|
| HCMC (24031_15_Elec.pdf) | Single PDF | E200 | E600 | 13 types | #1=6,#2=1,#3=1 | 98% Pass | 9/13 fixture counts match GT, 4 off by 1-2 |
| Anoka Dispensary | Single PDF | E301 | E901 | 10 types | #1=4,#2=1 | 97% Pass | 6/10 fixture counts match, short codes overcount |
| Dental Hygiene Lab | Single PDF | - | - | 0 (garbled text) | - | 97.8% Pass (vacuous) | Needs OCR/VLM fallback |
| DENIS 12E2 | Single PDF | E1.1, E1.2 | E4.1, E4.2 | 5 types (A6,B1,D6,E1,F4) | - | - | E0.0 misclassification fixed |

#### HCMC Fixture Count Detail (after char-level fix)
| Code | Pipeline | Ground Truth | Delta |
|------|----------|-------------|-------|
| A1 | 48 | 48 | Match |
| A6 | 14 | 14 | Match |
| B1 | 4 | 4 | Match |
| B6 | 26 | 25 | +1 |
| C4 | 1 | 1 | Match |
| D6 | 8 | N/A | Extra type in schedule |
| D7 | 1 | 1 | Match |
| E3 | 4 | 4 | Match |
| E4 | 3 | 3 | Match |
| L5 | 3 | 3 | Match |
| U2 | 2 | 2 | Match |
| U3 | 7 | 7 | Match |
| U4 | 4 | 4 | Match |

**11/12 exact matches** (was 9/12 before char-level fix). Remaining: B6 +1.

#### Anoka Fixture Count Detail (after legend-column exclusion fix)
| Code | Pipeline | Ground Truth | Delta |
|------|----------|-------------|-------|
| A | 15 | 14 | +1 |
| B | 10 | 10 | Match |
| C | 2 | 2 | Match |
| D | 9 | 10 | -1 |
| D1 | 1 | 1 | Match |
| EG | 1 | 1 | Match |
| EX | 4 | 4 | Match |
| F | 7 | 7 | Match |
| W1 | 4 | 4 | Match |
| W2 | 2 | 2 | Match |

**8/10 exact matches** (was 7/10 before legend-column fix). C fixed by removing PE stamp match "PHILIP C. HAIGHT". A closer by 1 (stamp text "I AM A DULY"). Remaining diffs are short-code ambiguity (BUG-003).

### Known Issues Found by Validation
- **Variable shadowing bug (FIXED)**: `plan_codes` in `pipeline.py` was being overwritten by fixture cross-referencing. Renamed to `found_plan_codes`.
- **Dental Hygiene Lab**: Uses custom font encoding (character substitution cipher). Text extraction produces garbled output (ASCII ratio 27-36%). Requires full OCR/VLM pipeline fallback.
- **Parser column patterns (FIXED)**: Added `"fixture id"` (code), `"mounting style"` (mounting), `"rated lumen"`/`"lumen output"` (lumens), `"input watts"` (max_va), `"luminaire type"` (description), `"lumen/watts"` (lumens) to handle various schedule header styles. Removed ambiguous `"type"` from lumens patterns to prevent "LUMINAIRE TYPE" column mismap.
- **Combo pages (FIXED)**: Schedule tables embedded in lighting plan pages (e.g., Elk River) now detected by `_find_schedule_table_bbox()` — picks the table with the most luminaire keywords (≥3 matches in header row) and excludes it from fixture counting.
- **Sheet code cross-references (FIXED)**: Fixture codes that match plan sheet codes (e.g., E1A is both a fixture type and a sheet code in Johanna Fire) now filtered by checking preceding words for cross-reference indicators ("SEE", "SHEET", "REFER", "PLAN", etc.).
- **Folder addendum deduplication (FIXED)**: Folder loader now reads title-block sheet codes and deduplicates — when multiple files have the same sheet code (e.g., original + ADDM1 addendum), only the latest revision (highest file number) is kept.
- **Keynote header variations (FIXED)**: Added "KEYED SHEET NOTES" / "KEYED SHEET NOTE" patterns to keynotes.py header detection (Elk River uses this label).
- **Legend column text overcounting (FIXED)**: Fixture codes referenced in KEY NOTES text descriptions (e.g., "TYPE 'AL1'") and engineer certification stamps (e.g., "PHILIP C. HAIGHT") were counted as fixtures. Fixed by adding a legend column exclusion zone at rightmost 15% of page width (`_LEGEND_COL_X_FRAC = 0.85`).
- **Short fixture code overcounting**: Single/two-char codes (A, B, C, D, E3, E4) match room labels and circuit identifiers on plan pages. Vision-based counting would improve accuracy for short codes.
- **A1 undercounting (FIXED)**: Was caused by `extract_words()` splitting "A1" into "A"+"1". Fixed by switching to character-level counting.
- **E3 overcounting (FIXED)**: Grid line label "E3" (21.6pt) was counted as fixture. Fixed by modal font-size filtering.
- **No sheet index for some PDFs**: Anoka has no discoverable sheet index, lowering the confidence score for that stage to 85%.
- **DENIS 11CD — 0 schedule pages**: Sheet index lists E500 as schedule but classifier can't match any page to that code (pages show as `?` / `other`). Image-based PDFs need VLM page classification fallback.
- **Panel schedule extraction (FIXED)**: Parser was accepting panel schedule circuit entries (numeric codes 1,3,5,7...) as fixture codes. Fixed with keyword detection ("PANEL A/B", "circuit description"), regex panel header matching, and `_looks_like_panel_schedule()` post-parse validation. Also applied to VLM extractor output.
- **Title block crop too wide (FIXED)**: Crop area `(0.55, 0.80)` captured sheet index listings above the title block on E0.0 pages, causing misclassification. Tightened to `(0.55, 0.85)`.
- **Symbols/legend keyword priority (FIXED)**: In `_TITLE_KEYWORDS`, symbols/legend keywords now checked before schedule keywords to prevent symbols pages from being classified as schedule.
- **VLM schedule fallback too restrictive (FIXED)**: Was gated by `has_image_based_content` / `has_minimal_text`. Now triggers for any schedule page when pdfplumber finds 0 fixtures.
- **Per-page keynote merging bug (FIXED)**: `extract_all_keynotes()` merged keynotes by number across pages, losing per-page text when different pages had different keynotes with same numbers. Now keeps per-page keynotes separate.

### In Progress (Agent Team Validation)
- **Elk River Gym** (folder input, 2 plans after dedup) — schedule on combo page, 2 fixture types (G18, G22), 3 keynotes. Testing cross-ref filtering.
- **Johanna Fire** (folder, 4 lighting plans) — 28 fixture types, fixture codes overlap with sheet codes (E1A, E1B, E2A, E2B). Testing cross-reference filtering.
- **Waterville Fire** (folder input) — testing in progress
- **DENIS PDFs** (8 standalone PDFs, image-based schedules) — VLM prompt improved for fixture code accuracy. Panel schedule rejection and VLM fallback fixes applied.

### Key Technical Decisions
1. **Geometric shape detection over VLM for keynotes**: After extensive testing (7+ VLM prompt iterations), pdfplumber line geometry proved far more reliable than Claude Vision for counting small diamond-enclosed numbers. VLM is inconsistent (0 to 24 for same image across runs). Geometric detection gives exact match.
2. **Title block before prefix rules**: Title block content is the page's own self-description, making it more reliable than code prefixes which are ambiguous (E2xx could be lighting, power, or site plan).
3. **VLM as fallback only**: VLM keynote counting only triggers when text-based geometric detection finds all zeros for a plan page. Prevents VLM from overriding correct text-based counts.
4. **DPI limits for API calls**: Schedule VLM uses 150 DPI max (stays under 5MB base64 limit). Keynote VLM uses 200 DPI. Fixture vision counter uses 150 DPI (8000px API limit).
5. **Schedule table exclusion by keyword scoring**: On combo pages, `find_tables()` returns many tables (line grids, notes boxes, etc.). Only the table whose header row has the most luminaire keywords (≥3 of: MARK, LUMINAIRE, FIXTURE, LAMP, LUMEN, VOLTAGE, MOUNTING, WATT) is excluded. Checking only row 0 (not data rows) prevents false matches from notes sections that mention fixtures.
6. **Cross-reference filtering for sheet-code fixtures**: When a fixture code matches a plan sheet code (e.g., E1A), per-word matching checks preceding words for cross-reference indicators. Concatenated-text matching is disabled for these codes since context can't be checked in a flat string.
7. **Folder dedup by title-block sheet code**: Filename-based sheet codes are unreliable for addenda (e.g., `ADDM1` gets parsed as the code). The loader always reads the title-block sheet code and deduplicates by it, keeping the last file (highest sort order = latest revision).
8. **Smart agent skipping**: The API orchestrator wrapper skips count and keynote agents when there's nothing to process. If no lighting plans found → skip both. If plans exist but no fixture codes → skip count, still run keynotes. Empty result JSON files are written so the QA agent can still read them.

## Known Challenges

1. **Sheet index format variability** — SOLVED: Multiple parsing strategies (table extraction, text-based regex, two-column layout) with graceful fallback.
2. **Table variability** — SOLVED: Flexible column mapper with fuzzy matching. VLM fallback for image-based tables.
3. **Fixture symbol recognition** — SOLVED: Spatial filtering excludes title block (rightmost ~25%), border areas, and notes sections.
4. **Key notes parsing** — SOLVED: Geometric shape detection (diamond/hexagon enclosure) with font_h modal filtering. "KEY NOTES:", "KEYED NOTES:", and "KEYED SHEET NOTES" header patterns supported.
5. **Dynamic column generation** — SOLVED: Excel and JSON handle variable numbers of plan columns.
6. **Scanned vs vector PDFs** — PARTIALLY SOLVED: VLM fallback for image-based schedules. OCR fallback available via pytesseract.
7. **Cross-document context** — SOLVED: Sheet index from cover page ties together fixture codes across separate plan/schedule PDFs in folder input.
8. **QA confidence calibration** — IN PROGRESS: Being tuned against real projects via agent team validation.
9. **DENIS fixture code accuracy** — IN PROGRESS: VLM schedule extraction may misread codes (e.g., "A1" vs "AL1"). VLM prompt improved with explicit multi-letter prefix guidance. Testing in progress.
10. **VLM counting unreliability** — DOCUMENTED: Claude Vision API produces inconsistent results for counting small symbols on engineering drawings. Mitigated by using geometric detection as primary method.
11. **Custom font encoding** — OPEN: Some PDFs (e.g., Dental Hygiene Lab) use character substitution ciphers that produce garbled text from pdfplumber/PyMuPDF. Need automatic detection (low ASCII letter ratio) and full OCR/VLM fallback for entire pipeline, not just schedule extraction.
12. **Fixture text-counting overcounting** — PARTIALLY SOLVED: Schedule table exclusion for combo pages and cross-reference filtering for sheet-code fixtures. Short code overcounting (Anoka: A=17 vs GT 14) still open — needs tighter spatial filtering or vision fallback.
13. **Combo page schedule extraction** — SOLVED: `run_schedule.py` checks plan pages for embedded schedule tables. `text_counter.py` detects and excludes luminaire schedule table bounding boxes from fixture counting.
14. **Folder addendum deduplication** — SOLVED: `loader.py` reads title-block sheet codes and keeps only the latest revision when multiple files share the same sheet code.

## Dependencies

```toml
[project]
name = "medina"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "pdfplumber>=0.10",
    "PyMuPDF>=1.23",
    "openpyxl>=3.1",
    "pydantic>=2.5",
    "pydantic-settings>=2.1",
    "click>=8.1",
    "anthropic>=0.40",
    "Pillow>=10.0",
    "pytesseract>=0.3",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.4",
    "pytest-cov>=4.1",
    "ruff>=0.1",
    "jupyter>=1.0",
    "ipykernel>=6.0",
]
api = [
    "fastapi>=0.108",
    "uvicorn[standard]>=0.25",
    "python-multipart>=0.0.6",
    "sse-starlette>=1.8",
]

[project.scripts]
medina = "medina.cli:main"
```

## Web UI

### Running the Servers
```bash
# Terminal 1 — Backend (FastAPI on port 8000)
cd Medina && uv run python run_server.py

# Terminal 2 — Frontend (Vite on port 3000)
cd Medina/frontend && npx vite --host 127.0.0.1 --port 3000
```

Open http://127.0.0.1:3000 in browser.

### UI States
| State | Left Panel | Center Panel | Right Panel |
|-------|-----------|-------------|-------------|
| `empty` | Upload zone + demo links + library picker | Agents greyed/pending | "Upload to begin" |
| `demo` | Upload zone (no PDF) | All agents green | Tables with data |
| `processing` | File list or first page | Agents animate 1→5 | Progress messages |
| `complete` | PDF viewer + nav | All agents green + stats | Full tables |
| `error` | PDF viewer | Failed agent red | Error message |

### Key Frontend Decisions
- **Vite 5** (not 7) for Node 18 compatibility
- **Tailwind v3** via PostCSS (not v4 which requires Vite 6+)
- **Zustand** for global state (lightweight, no boilerplate)
- **SSE** (Server-Sent Events) for real-time agent progress
- Vite proxy `/api` → `http://127.0.0.1:8000` (explicit IPv4 to avoid IPv6 issues)
- `run_server.py` adds `src/` to PYTHONPATH before starting uvicorn (workaround for editable install .pth issues with paths containing spaces)

### PDF Viewer Features
- **Zoom controls**: Toolbar buttons for zoom in (+), zoom out (-), and reset (shows current %). Range: 25%–400% in 25% steps.
- **Ctrl+Scroll zoom**: Hold Ctrl (or Cmd on Mac) and scroll to zoom in/out on the PDF page.
- **Scrollable at zoom**: When zoomed past 100%, the container scrolls to pan around the page.
- Page navigation arrows for prev/next page with sheet code label.

### No-Results Messaging
- When processing completes but **no schedules AND no lighting plans** are found, the right panel shows an informative warning with possible reasons (wrong PDF type, classification failure, unrecognized schedule format, scanned/image-only PDF).
- When **no schedules** are found but lighting plans exist, a separate message explains that fixture types cannot be determined without a schedule page.
- These replace the empty table view that would otherwise show zero rows.

### Keynote Table Layout
- Keynotes are displayed as **separate tables per plan page**, not one combined table.
- Each plan gets its own section header (e.g., "E2.2 — 4 keynotes") followed by a 3-column table: #, Key Note text, Count.
- Only keynotes with count > 0 on a given plan appear in that plan's table.
- Plans with no keynotes show "No keynotes found on this plan."
