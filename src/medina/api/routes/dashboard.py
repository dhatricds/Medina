"""Dashboard CRUD routes for approved projects."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from medina.api.feedback import (
    FixtureFeedback,
    load_project_feedback,
)
from medina.api.learnings import save_learnings
from medina.api.models import ApproveRequest
from medina.api.projects import get_project
from medina.models import (
    ExtractionResult,
    FixtureRecord,
    KeyNote,
    QAReport,
)
from medina.output.excel import write_excel

logger = logging.getLogger(__name__)

DASHBOARD_DIR = Path(__file__).resolve().parents[4] / "output" / "dashboard"
FEEDBACK_DIR = Path(__file__).resolve().parents[4] / "output" / "feedback"

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _read_index() -> list[dict]:
    """Read the dashboard index file."""
    index_path = DASHBOARD_DIR / "index.json"
    if not index_path.exists():
        return []
    with open(index_path) as f:
        return json.load(f)


def _write_index(index: list[dict]) -> None:
    """Write the dashboard index file."""
    DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
    index_path = DASHBOARD_DIR / "index.json"
    with open(index_path, "w") as f:
        json.dump(index, f, indent=2)


def _compute_diffs(
    original: dict[str, Any],
    corrected_fixtures: list[dict] | None,
    corrected_keynotes: list[dict] | None,
) -> list[FixtureFeedback]:
    """Compare original pipeline output with corrected data from the frontend.

    Returns a list of FixtureFeedback entries representing the diffs.
    """
    diffs: list[FixtureFeedback] = []

    if corrected_fixtures is not None:
        orig_fixtures = {f["code"]: f for f in original.get("fixtures", [])}
        corr_fixtures = {f["code"]: f for f in corrected_fixtures}

        # Added fixture types
        for code in corr_fixtures:
            if code not in orig_fixtures:
                f = corr_fixtures[code]
                diffs.append(FixtureFeedback(
                    action="add",
                    fixture_code=code,
                    reason="missing_fixture",
                    reason_detail="Added at approval time",
                    fixture_data={
                        "description": f.get("description", ""),
                        "fixture_style": f.get("fixture_style", ""),
                        "voltage": f.get("voltage", ""),
                        "mounting": f.get("mounting", ""),
                        "lumens": f.get("lumens", ""),
                        "cct": f.get("cct", ""),
                        "dimming": f.get("dimming", ""),
                        "max_va": f.get("max_va", ""),
                    },
                ))

        # Removed fixture types
        for code in orig_fixtures:
            if code not in corr_fixtures:
                diffs.append(FixtureFeedback(
                    action="remove",
                    fixture_code=code,
                    reason="extra_fixture",
                    reason_detail="Removed at approval time",
                ))

        # Count and spec diffs for fixtures present in both
        for code in corr_fixtures:
            if code not in orig_fixtures:
                continue
            orig_f = orig_fixtures[code]
            corr_f = corr_fixtures[code]

            # Check counts_per_plan diffs
            orig_counts = orig_f.get("counts_per_plan", {})
            corr_counts = corr_f.get("counts_per_plan", {})
            all_plans = set(orig_counts) | set(corr_counts)
            for plan in all_plans:
                oc = orig_counts.get(plan, 0)
                cc = corr_counts.get(plan, 0)
                if oc != cc:
                    diffs.append(FixtureFeedback(
                        action="count_override",
                        fixture_code=code,
                        reason="manual_count_edit",
                        reason_detail=f"Approval-time edit: {oc} -> {cc} on {plan}",
                        fixture_data={"sheet": plan, "corrected": cc, "original": oc},
                    ))

            # Check spec field diffs
            spec_fields = [
                "description", "fixture_style", "voltage", "mounting",
                "lumens", "cct", "dimming", "max_va",
            ]
            patches = {}
            for field in spec_fields:
                ov = orig_f.get(field, "")
                cv = corr_f.get(field, "")
                if ov != cv:
                    patches[field] = cv
            if patches:
                diffs.append(FixtureFeedback(
                    action="update_spec",
                    fixture_code=code,
                    reason="other",
                    reason_detail="Spec edited at approval time",
                    spec_patches=patches,
                ))

    return diffs


def _json_to_extraction_result(data: dict[str, Any]) -> ExtractionResult:
    """Build a minimal ExtractionResult from corrected JSON data.

    This lets us reuse write_excel() to generate the dashboard Excel
    with user-corrected counts and specs.
    """
    fixtures = []
    for f in data.get("fixtures", []):
        fixtures.append(FixtureRecord(
            code=f.get("code", ""),
            description=f.get("description", ""),
            fixture_style=f.get("fixture_style", ""),
            voltage=f.get("voltage", ""),
            mounting=f.get("mounting", ""),
            lumens=f.get("lumens", ""),
            cct=f.get("cct", ""),
            dimming=f.get("dimming", ""),
            max_va=f.get("max_va", ""),
            counts_per_plan=f.get("counts_per_plan", {}),
            total=f.get("total", 0),
        ))

    keynotes = []
    for k in data.get("keynotes", []):
        keynotes.append(KeyNote(
            number=k.get("keynote_number", k.get("number", "")),
            text=k.get("keynote_text", k.get("text", "")),
            counts_per_plan=k.get("counts_per_plan", {}),
            total=k.get("total", 0),
            fixture_references=k.get("fixture_references", []),
        ))

    qa_report = None
    qa_data = data.get("qa_report")
    if qa_data:
        qa_report = QAReport(
            overall_confidence=qa_data.get("overall_confidence", 1.0),
            passed=qa_data.get("passed", True),
            threshold=qa_data.get("threshold", 0.95),
            stage_scores=qa_data.get("stage_scores", {}),
            warnings=qa_data.get("warnings", []),
            recommendations=qa_data.get("recommendations", []),
        )

    return ExtractionResult(
        source=data.get("project_name", ""),
        fixtures=fixtures,
        keynotes=keynotes,
        plan_pages=data.get("lighting_plans", []),
        schedule_pages=data.get("schedule_pages", []),
        qa_report=qa_report,
    )


def _recalc_summary(data: dict[str, Any]) -> dict[str, Any]:
    """Recalculate summary totals from fixtures and keynotes."""
    fixtures = data.get("fixtures", [])
    keynotes = data.get("keynotes", [])
    # Recalc per-fixture totals
    for f in fixtures:
        f["total"] = sum(f.get("counts_per_plan", {}).values())
    for k in keynotes:
        k["total"] = sum(k.get("counts_per_plan", {}).values())

    total_fixtures = sum(f["total"] for f in fixtures)
    summary = data.get("summary", {})
    summary["total_fixture_types"] = len(fixtures)
    summary["total_fixtures"] = total_fixtures
    summary["total_keynotes"] = len(keynotes)
    data["summary"] = summary
    return data


@router.get("")
async def list_dashboard_projects(request: Request):
    """List approved dashboard projects for the current tenant."""
    tenant_id = getattr(request.state, "tenant_id", "default")
    index = _read_index()
    return [e for e in index if e.get("tenant_id", "default") == tenant_id]


@router.get("/{dashboard_id}")
async def get_dashboard_project(dashboard_id: str, request: Request):
    """Get full project data for a dashboard entry."""
    tenant_id = getattr(request.state, "tenant_id", "default")
    # Verify ownership
    index = _read_index()
    entry = next((e for e in index if e["id"] == dashboard_id), None)
    if not entry or entry.get("tenant_id", "default") != tenant_id:
        raise HTTPException(status_code=404, detail="Dashboard project not found")

    project_path = DASHBOARD_DIR / f"{dashboard_id}.json"
    if not project_path.exists():
        raise HTTPException(status_code=404, detail="Dashboard project not found")
    with open(project_path) as f:
        return json.load(f)


@router.get("/{dashboard_id}/export/excel")
async def export_dashboard_excel(dashboard_id: str, request: Request):
    """Download the Excel file for a dashboard project."""
    tenant_id = getattr(request.state, "tenant_id", "default")
    xlsx_path = DASHBOARD_DIR / f"{dashboard_id}.xlsx"
    if not xlsx_path.exists():
        raise HTTPException(status_code=404, detail="Excel file not found")

    # Find project name for filename and verify ownership
    index = _read_index()
    name = dashboard_id
    for entry in index:
        if entry["id"] == dashboard_id:
            if entry.get("tenant_id", "default") != tenant_id:
                raise HTTPException(status_code=404, detail="Dashboard project not found")
            name = entry["name"]
            break

    filename = f"{name}_inventory.xlsx"
    return FileResponse(
        path=str(xlsx_path),
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.post("/approve/{project_id}")
async def approve_project(project_id: str, request: Request, body: ApproveRequest | None = None):
    """Approve a processed project and add it to the dashboard.

    If the frontend sends corrected fixtures/keynotes, the dashboard will
    store the corrected data and generate the Excel from it.  Diffs between
    original and corrected data are saved as learnings for future runs.
    """
    tenant_id = getattr(request.state, "tenant_id", "default")
    project = get_project(project_id, tenant_id=tenant_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if not project.result_data:
        # Try loading from disk
        if project.output_path:
            json_path = Path(f"{project.output_path}.json")
            if json_path.exists():
                with open(json_path) as f:
                    project.result_data = json.load(f)

    if not project.result_data:
        raise HTTPException(status_code=400, detail="Project has no results to approve")

    DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)

    # Determine whether corrections were sent
    has_corrections = (
        body is not None
        and (body.corrected_fixtures is not None or body.corrected_keynotes is not None)
    )

    # Build the data dict to save — start from original pipeline output
    save_data = json.loads(json.dumps(project.result_data))  # deep copy

    if has_corrections:
        # Compute diffs for learning
        diffs = _compute_diffs(
            project.result_data,
            body.corrected_fixtures,
            body.corrected_keynotes,
        )

        # Apply corrected fixtures/keynotes to save_data
        if body.corrected_fixtures is not None:
            save_data["fixtures"] = body.corrected_fixtures
        if body.corrected_keynotes is not None:
            save_data["keynotes"] = body.corrected_keynotes

        # Recalculate summary totals
        save_data = _recalc_summary(save_data)

        # Save diffs as learnings if any
        if diffs:
            # Merge with any existing session feedback
            existing_feedback = load_project_feedback(project_id)
            all_corrections = list(existing_feedback.corrections) if existing_feedback else []
            all_corrections.extend(diffs)

            save_learnings(project.source_path, all_corrections)
            logger.info(
                "Saved %d approval-time corrections as learnings for %s",
                len(diffs), project.source_path.name,
            )

            # Clean up project feedback file
            feedback_path = FEEDBACK_DIR / f"{project_id}.json"
            if feedback_path.exists():
                feedback_path.unlink()
    else:
        # No corrections — still promote any session feedback to learnings
        existing_feedback = load_project_feedback(project_id)
        if existing_feedback and existing_feedback.corrections:
            save_learnings(project.source_path, existing_feedback.corrections)
            feedback_path = FEEDBACK_DIR / f"{project_id}.json"
            if feedback_path.exists():
                feedback_path.unlink()

    # Generate a dashboard ID from project name
    project_name = save_data.get("project_name", project_id)
    dashboard_id = re.sub(r"[^a-zA-Z0-9_-]", "_", project_name)[:60]

    # Check for duplicates and make unique
    index = _read_index()
    existing_ids = {e["id"] for e in index}
    base_id = dashboard_id
    counter = 1
    while dashboard_id in existing_ids:
        dashboard_id = f"{base_id}_{counter}"
        counter += 1

    # Save project data JSON (with corrections applied)
    project_json_path = DASHBOARD_DIR / f"{dashboard_id}.json"
    with open(project_json_path, "w") as f:
        json.dump(save_data, f, indent=2)

    # Generate Excel from (possibly corrected) data
    xlsx_path = DASHBOARD_DIR / f"{dashboard_id}.xlsx"
    try:
        extraction_result = _json_to_extraction_result(save_data)
        write_excel(extraction_result, xlsx_path)
        logger.info("Generated dashboard Excel: %s", xlsx_path)
    except Exception as e:
        logger.warning("Failed to generate Excel for dashboard %s: %s", dashboard_id, e)
        # Fallback: copy pipeline Excel if available
        if project.output_path:
            xlsx_src = Path(f"{project.output_path}.xlsx")
            if xlsx_src.exists():
                import shutil
                shutil.copy2(xlsx_src, xlsx_path)

    # Build index entry
    summary = save_data.get("summary", {})
    qa = save_data.get("qa_report")
    now = datetime.now(timezone.utc).isoformat()

    # Copy positions file to dashboard if available
    if project.output_path:
        src_positions = Path(f"{project.output_path}_positions.json")
        if src_positions.exists():
            import shutil
            dst_positions = DASHBOARD_DIR / f"{dashboard_id}_positions.json"
            shutil.copy2(src_positions, dst_positions)
            logger.info("Copied positions file to dashboard: %s", dst_positions)

    entry = {
        "id": dashboard_id,
        "name": project_name,
        "tenant_id": tenant_id,
        "approved_at": now,
        "fixture_types": summary.get("total_fixture_types", 0),
        "total_fixtures": summary.get("total_fixtures", 0),
        "keynote_count": summary.get("total_keynotes", 0),
        "plan_count": summary.get("total_lighting_plans", 0),
        "qa_score": qa.get("overall_confidence") if qa else None,
        "qa_passed": qa.get("passed") if qa else None,
        "source_path": str(project.source_path),
        "output_path": str(project.output_path) if project.output_path else None,
    }
    index.append(entry)
    _write_index(index)

    logger.info("Project approved to dashboard: %s (%s)", project_name, dashboard_id)
    return entry


@router.delete("/{dashboard_id}")
async def delete_dashboard_project(dashboard_id: str, request: Request):
    """Remove a project from the dashboard."""
    tenant_id = getattr(request.state, "tenant_id", "default")
    index = _read_index()

    # Only allow deleting own tenant's projects
    entry = next((e for e in index if e["id"] == dashboard_id), None)
    if not entry or entry.get("tenant_id", "default") != tenant_id:
        raise HTTPException(status_code=404, detail="Dashboard project not found")

    new_index = [e for e in index if e["id"] != dashboard_id]

    _write_index(new_index)

    # Remove files
    for ext in (".json", ".xlsx"):
        file_path = DASHBOARD_DIR / f"{dashboard_id}{ext}"
        if file_path.exists():
            file_path.unlink()

    # Also remove positions file
    pos_path = DASHBOARD_DIR / f"{dashboard_id}_positions.json"
    if pos_path.exists():
        pos_path.unlink()

    return {"deleted": dashboard_id}


DATA_DIR = Path(__file__).resolve().parents[4] / "data"
TRAIN_DIR = Path(__file__).resolve().parents[4] / "train"
UPLOADS_DIR = Path(__file__).resolve().parents[4] / "uploads"


def _resolve_source_pdf(entry: dict, project_data: dict) -> Path | None:
    """Try multiple strategies to find the source PDF for a dashboard project.

    Priority:
    1. Explicit source_path in index entry
    2. source_path / source field in project JSON
    3. Fuzzy match by project_name in data/ and train/ directories
    """
    project_root = Path(__file__).resolve().parents[4]

    # Strategy 1 & 2: explicit paths
    for candidate_str in [
        entry.get("source_path", ""),
        project_data.get("source_path", ""),
        project_data.get("source", ""),
    ]:
        if not candidate_str:
            continue
        candidate = Path(candidate_str)
        if not candidate.is_absolute():
            candidate = project_root / candidate
        if candidate.exists():
            return candidate

    # Strategy 3: fuzzy match by project_name in data/ and train/
    project_name = project_data.get("project_name", entry.get("name", ""))
    if not project_name:
        return None

    # Normalize for matching: lowercase, remove parens content, strip
    norm_name = re.sub(r"\([\d]+\)", "", project_name).strip().lower()

    for search_dir in [DATA_DIR, TRAIN_DIR, UPLOADS_DIR]:
        if not search_dir.exists():
            continue
        for item in search_dir.iterdir():
            if item.suffix.lower() == ".pdf" or item.is_dir():
                item_norm = re.sub(r"\([\d]+\)", "", item.stem).strip().lower()
                # Also strip _inventory suffix from train files
                item_norm = item_norm.replace("_inventory", "")
                if item_norm == norm_name or norm_name in item_norm or item_norm in norm_name:
                    return item

    return None


@router.post("/{dashboard_id}/edit")
async def edit_dashboard_project(dashboard_id: str, request: Request):
    """Open an approved dashboard project for editing in the workspace.

    Creates an in-memory ProjectState so that page rendering, position
    lookup, feedback and reprocess APIs all work normally.  Returns
    a project_id the frontend can use with the standard workspace APIs.
    """
    tenant_id = getattr(request.state, "tenant_id", "default")
    index = _read_index()
    entry = next((e for e in index if e["id"] == dashboard_id), None)
    if not entry or entry.get("tenant_id", "default") != tenant_id:
        raise HTTPException(status_code=404, detail="Dashboard project not found")

    # Load the full project JSON
    project_json_path = DASHBOARD_DIR / f"{dashboard_id}.json"
    if not project_json_path.exists():
        raise HTTPException(status_code=404, detail="Dashboard project data not found")
    with open(project_json_path) as f:
        project_data = json.load(f)

    # Resolve source PDF path using multi-strategy resolver
    source_path = _resolve_source_pdf(entry, project_data)
    if not source_path:
        raise HTTPException(
            status_code=400,
            detail="Source PDF not found. The original file may have been moved or deleted.",
        )

    # Determine output_path: prefer dashboard positions file, fall back to original
    dashboard_positions = DASHBOARD_DIR / f"{dashboard_id}_positions.json"
    original_output = (
        entry.get("output_path")
        or project_data.get("output_path", "")
    )

    # Use dashboard directory as output base (positions file is here)
    output_base = str(DASHBOARD_DIR / dashboard_id)
    if not dashboard_positions.exists() and original_output:
        # Fall back to original output path if dashboard positions don't exist
        output_base = original_output

    # Build pages array and total_pages if missing (seed/older projects)
    if not project_data.get("pages") or not project_data.get("total_pages"):
        try:
            import fitz as pymupdf
            known_plans = set(project_data.get("lighting_plans", []))
            known_schedules = set(project_data.get("schedule_pages", []))
            all_known = known_plans | known_schedules
            _MIN_TITLE_FONT = 15.0
            _code_re = re.compile(
                r"\b([A-Z]\d{1,4}[A-Za-z]?(?:\.\d+[A-Za-z]?)?)\b"
            )

            if source_path.is_file() and source_path.suffix.lower() == ".pdf":
                doc = pymupdf.open(str(source_path))
                num_pages = len(doc)
                project_data["total_pages"] = num_pages
                if not project_data.get("pages"):
                    # Map known plan/schedule codes to pages via large-font matching
                    code_to_page: dict[str, int] = {}
                    for i in range(num_pages):
                        page = doc[i]
                        blocks = page.get_text("dict")["blocks"]
                        best_code = None
                        best_size = 0.0
                        for b in blocks:
                            if "lines" not in b:
                                continue
                            for line_obj in b["lines"]:
                                for span in line_obj["spans"]:
                                    if span["size"] < _MIN_TITLE_FONT:
                                        continue
                                    for m in _code_re.finditer(span["text"].strip()):
                                        code = m.group(1).upper()
                                        if code in all_known and span["size"] > best_size:
                                            best_code = code
                                            best_size = span["size"]
                        if best_code and best_code not in code_to_page:
                            code_to_page[best_code] = i + 1

                    pages_list = []
                    for i in range(num_pages):
                        page_num = i + 1
                        # Find which known code maps to this page
                        sheet_code = None
                        page_type = "other"
                        for code, pn in code_to_page.items():
                            if pn == page_num:
                                sheet_code = code
                                if code in known_plans:
                                    page_type = "lighting_plan"
                                elif code in known_schedules:
                                    page_type = "schedule"
                                break
                        pages_list.append({
                            "page_number": page_num,
                            "sheet_code": sheet_code or f"pg{page_num}",
                            "description": "",
                            "type": page_type,
                            "source_path": str(source_path),
                            "pdf_page_index": i,
                        })
                    project_data["pages"] = pages_list
                doc.close()
            elif source_path.is_dir():
                pdf_files = sorted(source_path.glob("*.pdf"))
                project_data["total_pages"] = len(pdf_files)
                if not project_data.get("pages"):
                    pages_list = []
                    for idx, pdf_file in enumerate(pdf_files):
                        fname = pdf_file.stem
                        sheet_code = None
                        m = re.match(r"\d+---(\S+)", fname)
                        if m:
                            sheet_code = m.group(1)
                        page_type = "other"
                        if sheet_code:
                            if sheet_code in known_plans:
                                page_type = "lighting_plan"
                            elif sheet_code in known_schedules:
                                page_type = "schedule"
                        pages_list.append({
                            "page_number": idx + 1,
                            "sheet_code": sheet_code or f"pg{idx + 1}",
                            "description": fname,
                            "type": page_type,
                            "source_path": str(pdf_file),
                            "pdf_page_index": 0,
                        })
                    project_data["pages"] = pages_list
        except Exception as e:
            logger.warning("Failed to build pages for dashboard edit: %s", e)

    # Create an in-memory project state
    from medina.api.projects import ProjectState, _projects
    import uuid

    project_id = uuid.uuid4().hex[:12]
    project = ProjectState(
        project_id=project_id,
        source_path=source_path,
        tenant_id=tenant_id,
        status="completed",
        result_data=project_data,
        output_path=output_base,
    )
    _projects[project_id] = project

    logger.info(
        "Opened dashboard project %s for editing as workspace project %s",
        dashboard_id, project_id,
    )

    return {
        "project_id": project_id,
        "dashboard_id": dashboard_id,
        "source": str(source_path),
    }
