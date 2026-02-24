"""Rule-based COVE verification for each pipeline agent.

Each verify function receives the agent's output dict (as written to
the intermediate JSON files) and returns a CoveResult describing whether
the output looks plausible.  These are fast, deterministic checks — no
API calls.  When confidence drops below 0.7 the caller should escalate
to the LLM verifier in ``llm_verifier.py``.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
#  Severity levels for reported issues
# ---------------------------------------------------------------------------
SEVERITY_ERROR = "error"       # Hard failure — likely wrong data
SEVERITY_WARNING = "warning"   # Suspicious but may be valid
SEVERITY_INFO = "info"         # Informational observation


# ---------------------------------------------------------------------------
#  CoveResult data class
# ---------------------------------------------------------------------------
@dataclass
class CoveResult:
    """Outcome of a single COVE verification pass.

    Attributes:
        passed: True when no blocking issues were found.
        confidence: 0.0–1.0 score; starts at 1.0, deductions applied per issue.
        issues: List of dicts ``{check, message, severity}``.
        corrections: Suggested auto-corrections the orchestrator may apply.
        reasoning: Human-readable summary of the verification logic.
    """

    passed: bool = True
    confidence: float = 1.0
    issues: list[dict[str, Any]] = field(default_factory=list)
    corrections: list[dict[str, Any]] = field(default_factory=list)
    reasoning: str = ""

    # Convenience helpers -------------------------------------------------

    def _add_issue(
        self,
        check: str,
        message: str,
        severity: str = SEVERITY_WARNING,
        deduction: float = 0.0,
    ) -> None:
        """Record an issue and reduce confidence."""
        self.issues.append({
            "check": check,
            "message": message,
            "severity": severity,
        })
        self.confidence = max(0.0, self.confidence - deduction)
        if severity == SEVERITY_ERROR:
            self.passed = False

    def _add_correction(
        self,
        action: str,
        target: str = "",
        detail: str = "",
        data: dict[str, Any] | None = None,
    ) -> None:
        """Suggest an auto-correction for the orchestrator."""
        self.corrections.append({
            "action": action,
            "target": target,
            "detail": detail,
            **({"data": data} if data else {}),
        })

    def _persist(self, project_id: str, agent_name: str) -> None:
        """Persist the result to SQLite and ChromaDB (best-effort)."""
        # --- SQLite ---
        try:
            from medina.db import repositories as repo
            repo.save_cove_result(
                project_id=project_id,
                agent_id=_AGENT_IDS.get(agent_name, 0),
                agent_name=agent_name,
                passed=self.passed,
                confidence=self.confidence,
                issues=self.issues,
                reasoning=self.reasoning,
            )
        except Exception as exc:
            logger.debug("COVE DB save skipped: %s", exc)

        # --- ChromaDB ---
        if self.issues:
            try:
                from medina.db.vector_store import (
                    add_document,
                    COVE_FINDINGS_COLLECTION,
                )
                doc_text = "; ".join(
                    f"[{i['severity']}] {i['check']}: {i['message']}"
                    for i in self.issues
                )
                doc_id = f"cove_{project_id}_{agent_name}"
                add_document(
                    COVE_FINDINGS_COLLECTION,
                    doc_id=doc_id,
                    text=doc_text,
                    metadata={
                        "project_id": project_id,
                        "agent": agent_name,
                        "confidence": self.confidence,
                        "passed": self.passed,
                    },
                )
            except Exception as exc:
                logger.debug("COVE ChromaDB save skipped: %s", exc)


# Map agent names to sequential IDs matching the team pipeline order.
_AGENT_IDS: dict[str, int] = {
    "search": 1,
    "schedule": 2,
    "count": 3,
    "keynote": 4,
    "qa": 5,
}

# Header words that should never appear as fixture codes — kept in sync
# with ``run_schedule._HEADER_WORDS``.
_HEADER_WORDS = frozenset({
    "SCHEDULE", "SCHEDULES", "LUMINAIRE", "FIXTURE", "FIXTURES",
    "LIGHTING", "TYPE", "DESCRIPTION", "MARK", "SYMBOL", "CATALOG",
    "MOUNTING", "VOLTAGE", "DIMMING", "WATTS", "WATTAGE",
})

# Known electrical page types (from models.PageType values).
_VALID_PAGE_TYPES = frozenset({
    "symbols_legend", "lighting_plan", "demolition_plan", "power_plan",
    "schedule", "detail", "cover", "site_plan", "fire_alarm", "riser",
    "other",
})

# Maximum plausible fixture count on a single plan page.  Anything above
# this almost certainly indicates a counting bug (room labels, etc.).
_MAX_PLAUSIBLE_COUNT = 500

# Maximum plausible keynote count per plan.  Mirrors run_keynote constant.
_MAX_PLAUSIBLE_KEYNOTE_COUNT = 10

# Fixture code length limits.
_MIN_CODE_LEN = 1
_MAX_CODE_LEN = 6

# Fixture type count limits.
_MIN_FIXTURE_TYPES = 1
_MAX_FIXTURE_TYPES = 50


# ═══════════════════════════════════════════════════════════════════════════
#  1. SEARCH AGENT VERIFICATION
# ═══════════════════════════════════════════════════════════════════════════

def verify_search(search_result: dict, project_id: str = "") -> CoveResult:
    """Verify the Search Agent output (Stages 1-3).

    Checks:
        - At least one page loaded.
        - Sheet index found (informational if missing).
        - At least one lighting plan page classified.
        - At least one schedule page classified.
        - No invalid page types in the output.
        - No duplicate sheet codes among pages of the same type.
    """
    result = CoveResult(reasoning="Search agent verification (load/discover/classify)")
    pages = search_result.get("pages", [])
    sheet_index = search_result.get("sheet_index", [])
    plan_codes = search_result.get("plan_codes", [])
    schedule_codes = search_result.get("schedule_codes", [])

    # --- Check: pages loaded ---
    if not pages:
        result._add_issue(
            "no_pages",
            "No pages were loaded from the source document.",
            severity=SEVERITY_ERROR,
            deduction=1.0,
        )
        return _finalize(result, project_id, "search")

    # --- Check: sheet index ---
    if not sheet_index:
        result._add_issue(
            "no_sheet_index",
            "No sheet index found on legend/cover page. "
            "Classification relies on title block and prefix rules.",
            severity=SEVERITY_WARNING,
            deduction=0.10,
        )

    # --- Check: at least 1 lighting plan ---
    if not plan_codes:
        result._add_issue(
            "no_lighting_plans",
            "No lighting plan pages identified. "
            "Fixture counting will be skipped.",
            severity=SEVERITY_WARNING,
            deduction=0.20,
        )

    # --- Check: at least 1 schedule ---
    if not schedule_codes:
        result._add_issue(
            "no_schedules",
            "No schedule pages identified. "
            "Fixture spec extraction will be skipped.",
            severity=SEVERITY_WARNING,
            deduction=0.20,
        )

    # --- Check: valid page types ---
    invalid_types: list[str] = []
    for page in pages:
        ptype = page.get("page_type", "")
        if ptype and ptype not in _VALID_PAGE_TYPES:
            invalid_types.append(ptype)
    if invalid_types:
        result._add_issue(
            "invalid_page_types",
            f"Pages with unrecognized types: {invalid_types}",
            severity=SEVERITY_ERROR,
            deduction=0.15,
        )

    # --- Check: potential misclassifications (lighting vs demolition) ---
    # Pages whose sheet code suggests demolition (E1xx range) but classified
    # as lighting plan — a common misclassification.
    for page in pages:
        ptype = page.get("page_type", "")
        code = (page.get("sheet_code") or "").upper()
        title = (page.get("sheet_title") or "").lower()
        if ptype == "lighting_plan" and ("demo" in title or "demolition" in title):
            result._add_issue(
                "possible_misclassification",
                f"Page {code} classified as lighting_plan but title "
                f"contains demolition keywords: '{title}'",
                severity=SEVERITY_WARNING,
                deduction=0.10,
            )
            result._add_correction(
                action="reclassify_page",
                target=code,
                detail="demolition_plan",
            )

    # --- Check: duplicate sheet codes within the same type ---
    type_codes: dict[str, list[str]] = {}
    for page in pages:
        ptype = page.get("page_type", "")
        code = page.get("sheet_code") or ""
        if code:
            type_codes.setdefault(ptype, []).append(code)
    for ptype, codes in type_codes.items():
        dupes = [c for c in codes if codes.count(c) > 1]
        if dupes:
            result._add_issue(
                "duplicate_sheet_codes",
                f"Duplicate sheet codes in {ptype}: {sorted(set(dupes))}",
                severity=SEVERITY_WARNING,
                deduction=0.05,
            )

    return _finalize(result, project_id, "search")


# ═══════════════════════════════════════════════════════════════════════════
#  2. SCHEDULE AGENT VERIFICATION
# ═══════════════════════════════════════════════════════════════════════════

def verify_schedule(
    schedule_result: dict,
    search_result: dict,
    project_id: str = "",
) -> CoveResult:
    """Verify the Schedule Agent output (Stage 4).

    Checks:
        - Valid fixture codes (not header words, length 1-6).
        - No duplicate fixture codes.
        - Spec fields not all empty for every fixture.
        - Fixture count within plausible range (1-50).
        - Codes are alphanumeric (no punctuation junk).
    """
    result = CoveResult(reasoning="Schedule agent verification (fixture extraction)")
    fixtures = schedule_result.get("fixtures", [])
    fixture_codes = schedule_result.get("fixture_codes", [])
    schedule_codes = search_result.get("schedule_codes", [])

    # --- If no schedule pages existed, zero fixtures is expected ---
    if not schedule_codes:
        if fixtures:
            result._add_issue(
                "fixtures_without_schedule",
                f"Found {len(fixtures)} fixtures but no schedule pages "
                f"were identified. May be from combo pages.",
                severity=SEVERITY_INFO,
                deduction=0.0,
            )
        result.reasoning += " (no schedule pages — skip most checks)"
        return _finalize(result, project_id, "schedule")

    # --- Check: at least one fixture extracted ---
    if not fixtures:
        result._add_issue(
            "no_fixtures",
            "No fixtures extracted from schedule pages. "
            "VLM fallback may have failed or schedule format is unrecognized.",
            severity=SEVERITY_ERROR,
            deduction=0.40,
        )
        return _finalize(result, project_id, "schedule")

    # --- Check: plausible number of fixture types ---
    num_types = len(fixtures)
    if num_types > _MAX_FIXTURE_TYPES:
        result._add_issue(
            "too_many_fixture_types",
            f"Extracted {num_types} fixture types (max expected "
            f"{_MAX_FIXTURE_TYPES}). May include panel schedule entries.",
            severity=SEVERITY_WARNING,
            deduction=0.15,
        )
    # Very low count is suspicious only if schedule pages existed.
    if num_types < _MIN_FIXTURE_TYPES and schedule_codes:
        result._add_issue(
            "too_few_fixture_types",
            f"Only {num_types} fixture type(s) extracted from "
            f"{len(schedule_codes)} schedule page(s).",
            severity=SEVERITY_WARNING,
            deduction=0.10,
        )

    # --- Check: per-fixture validations ---
    seen_codes: set[str] = set()
    all_specs_empty_count = 0
    _SPEC_FIELDS = (
        "description", "fixture_style", "voltage", "mounting",
        "lumens", "cct", "dimming", "max_va",
    )

    for fx in fixtures:
        code = fx.get("code", "").strip()

        # Code is a header word
        if code.upper() in _HEADER_WORDS:
            result._add_issue(
                "header_word_as_code",
                f"Fixture code '{code}' is a table header word.",
                severity=SEVERITY_ERROR,
                deduction=0.10,
            )
            result._add_correction(
                action="remove",
                target=code,
                detail="Table header word mistakenly parsed as fixture code.",
            )

        # Code length
        if len(code) < _MIN_CODE_LEN or len(code) > _MAX_CODE_LEN:
            result._add_issue(
                "code_length_invalid",
                f"Fixture code '{code}' length {len(code)} outside "
                f"expected range [{_MIN_CODE_LEN}, {_MAX_CODE_LEN}].",
                severity=SEVERITY_WARNING,
                deduction=0.05,
            )

        # Code is purely alpha and > 3 chars (likely header text)
        if code.isalpha() and len(code) > 3:
            result._add_issue(
                "pure_alpha_long_code",
                f"Fixture code '{code}' is a pure-alpha string > 3 chars "
                f"— likely a table header or description fragment.",
                severity=SEVERITY_ERROR,
                deduction=0.10,
            )
            result._add_correction(
                action="remove",
                target=code,
                detail="Pure-alpha code longer than 3 characters.",
            )

        # Code contains non-alphanumeric characters (allow hyphens/dots)
        if code and not re.match(r'^[A-Za-z0-9.\-/]+$', code):
            result._add_issue(
                "code_invalid_chars",
                f"Fixture code '{code}' contains unexpected characters.",
                severity=SEVERITY_WARNING,
                deduction=0.05,
            )

        # Duplicate codes
        code_upper = code.upper()
        if code_upper in seen_codes:
            result._add_issue(
                "duplicate_code",
                f"Duplicate fixture code: '{code}'.",
                severity=SEVERITY_WARNING,
                deduction=0.05,
            )
        seen_codes.add(code_upper)

        # All spec fields empty
        specs_present = any(
            fx.get(fld, "").strip() for fld in _SPEC_FIELDS
        )
        if not specs_present:
            all_specs_empty_count += 1

    # Too many fixtures with all empty specs
    if fixtures and all_specs_empty_count == len(fixtures):
        result._add_issue(
            "all_specs_empty",
            "Every fixture has empty spec fields (description, voltage, "
            "etc.). Schedule parsing likely failed to map columns.",
            severity=SEVERITY_ERROR,
            deduction=0.25,
        )
    elif fixtures and all_specs_empty_count > len(fixtures) / 2:
        result._add_issue(
            "many_specs_empty",
            f"{all_specs_empty_count}/{len(fixtures)} fixtures have "
            f"entirely empty specs.",
            severity=SEVERITY_WARNING,
            deduction=0.15,
        )

    return _finalize(result, project_id, "schedule")


# ═══════════════════════════════════════════════════════════════════════════
#  3. COUNT AGENT VERIFICATION
# ═══════════════════════════════════════════════════════════════════════════

def verify_counts(
    count_result: dict,
    schedule_result: dict,
    project_id: str = "",
) -> CoveResult:
    """Verify the Count Agent output (Stage 5a).

    Checks:
        - No single count exceeds _MAX_PLAUSIBLE_COUNT.
        - Not all zeros when fixture codes exist and plan pages were found.
        - Short codes (1-char) not suspiciously high vs multi-char codes.
        - No negative counts.
    """
    result = CoveResult(reasoning="Count agent verification (fixture counting)")
    all_plan_counts = count_result.get("all_plan_counts", {})
    fixture_codes = schedule_result.get("fixture_codes", [])

    # --- If no fixture codes, empty counts are expected ---
    if not fixture_codes:
        if all_plan_counts:
            result._add_issue(
                "counts_without_codes",
                "Fixture counts present but no fixture codes were extracted.",
                severity=SEVERITY_WARNING,
                deduction=0.10,
            )
        result.reasoning += " (no fixture codes — skip most checks)"
        return _finalize(result, project_id, "count")

    # --- If no plan pages were processed, empty counts are expected ---
    if not all_plan_counts:
        result._add_issue(
            "no_plan_counts",
            f"No plan counts produced despite {len(fixture_codes)} "
            f"fixture codes. Lighting plans may not have been found.",
            severity=SEVERITY_WARNING,
            deduction=0.20,
        )
        return _finalize(result, project_id, "count")

    # --- Per-plan checks ---
    grand_total = 0
    short_code_totals: dict[str, int] = {}
    multi_code_totals: dict[str, int] = {}

    for plan_code, counts in all_plan_counts.items():
        plan_total = 0
        for code, count in counts.items():
            # Negative counts
            if count < 0:
                result._add_issue(
                    "negative_count",
                    f"Negative count for {code} on {plan_code}: {count}.",
                    severity=SEVERITY_ERROR,
                    deduction=0.10,
                )

            # Exceeds max plausible
            if count > _MAX_PLAUSIBLE_COUNT:
                result._add_issue(
                    "count_exceeds_max",
                    f"Fixture {code} on {plan_code} has count {count} "
                    f"(max plausible={_MAX_PLAUSIBLE_COUNT}). "
                    f"Likely a counting bug (room labels, etc.).",
                    severity=SEVERITY_ERROR,
                    deduction=0.15,
                )
                result._add_correction(
                    action="flag_for_vlm_recount",
                    target=code,
                    detail=f"Suspiciously high count {count} on {plan_code}.",
                    data={"plan_code": plan_code, "current_count": count},
                )

            plan_total += max(0, count)

            # Track short vs multi-char
            if len(code) <= 1:
                short_code_totals[code] = (
                    short_code_totals.get(code, 0) + count
                )
            else:
                multi_code_totals[code] = (
                    multi_code_totals.get(code, 0) + count
                )

        grand_total += plan_total

    # --- Check: all zeros across all plans ---
    if grand_total == 0 and fixture_codes:
        result._add_issue(
            "all_counts_zero",
            "All fixture counts are zero across all plans. "
            "Text extraction may have failed; VLM recount recommended.",
            severity=SEVERITY_ERROR,
            deduction=0.30,
        )
        result._add_correction(
            action="trigger_vlm_recount",
            target="all",
            detail="All counts zero — suggest full VLM recount.",
        )

    # --- Check: short codes suspiciously high ---
    # When 1-char codes exist, compare their average count to multi-char
    # codes.  Short codes matching room labels often produce counts 5-10x
    # higher than real fixtures.
    if short_code_totals and multi_code_totals:
        avg_short = sum(short_code_totals.values()) / len(short_code_totals)
        avg_multi = sum(multi_code_totals.values()) / len(multi_code_totals)
        if avg_multi > 0 and avg_short > avg_multi * 5:
            over_codes = [
                f"{c}={t}" for c, t in sorted(short_code_totals.items())
                if t > avg_multi * 3
            ]
            result._add_issue(
                "short_code_suspiciously_high",
                f"Short fixture codes have avg count {avg_short:.0f} vs "
                f"multi-char avg {avg_multi:.0f} ({avg_short / avg_multi:.1f}x). "
                f"Likely room-label false positives: {over_codes}",
                severity=SEVERITY_WARNING,
                deduction=0.10,
            )
            for code in short_code_totals:
                if short_code_totals[code] > avg_multi * 3:
                    result._add_correction(
                        action="flag_for_vlm_recount",
                        target=code,
                        detail=(
                            f"Short code '{code}' total "
                            f"{short_code_totals[code]} is suspiciously high."
                        ),
                    )

    return _finalize(result, project_id, "count")


# ═══════════════════════════════════════════════════════════════════════════
#  4. KEYNOTE AGENT VERIFICATION
# ═══════════════════════════════════════════════════════════════════════════

def verify_keynotes(
    keynote_result: dict,
    project_id: str = "",
) -> CoveResult:
    """Verify the Keynote Agent output (Stage 5b).

    Checks:
        - Keynote numbers are sequential (1, 2, 3...) or at least
          within a plausible range.
        - All per-plan counts <= _MAX_PLAUSIBLE_KEYNOTE_COUNT.
        - Keynote text is non-empty.
        - No duplicate keynote numbers.
    """
    result = CoveResult(reasoning="Keynote agent verification (keynote extraction)")
    keynotes = keynote_result.get("keynotes", [])
    all_keynote_counts = keynote_result.get("all_keynote_counts", {})

    # --- Empty keynotes is valid (some projects have none) ---
    if not keynotes:
        result._add_issue(
            "no_keynotes",
            "No keynotes extracted. This may be normal if the project "
            "has no keynoted items.",
            severity=SEVERITY_INFO,
            deduction=0.0,
        )
        return _finalize(result, project_id, "keynote")

    # --- Per-keynote checks ---
    seen_numbers: set[str] = set()
    numbers_int: list[int] = []

    for kn in keynotes:
        kn_num = str(kn.get("number", "")).strip()

        # Duplicate numbers
        if kn_num in seen_numbers:
            result._add_issue(
                "duplicate_keynote_number",
                f"Duplicate keynote number: #{kn_num}.",
                severity=SEVERITY_WARNING,
                deduction=0.05,
            )
        seen_numbers.add(kn_num)

        # Try to parse as integer for sequentiality check
        try:
            kn_int = int(kn_num)
            numbers_int.append(kn_int)
        except (ValueError, TypeError):
            pass

        # Empty text
        kn_text = (kn.get("text") or "").strip()
        if not kn_text:
            result._add_issue(
                "empty_keynote_text",
                f"Keynote #{kn_num} has empty text.",
                severity=SEVERITY_WARNING,
                deduction=0.05,
            )

        # Per-plan counts exceeding threshold
        counts_per_plan = kn.get("counts_per_plan", {})
        for plan_code, count in counts_per_plan.items():
            if count > _MAX_PLAUSIBLE_KEYNOTE_COUNT:
                result._add_issue(
                    "keynote_count_too_high",
                    f"Keynote #{kn_num} on {plan_code} has count {count} "
                    f"(max plausible={_MAX_PLAUSIBLE_KEYNOTE_COUNT}). "
                    f"Likely false positives from dense line geometry.",
                    severity=SEVERITY_WARNING,
                    deduction=0.10,
                )
                result._add_correction(
                    action="flag_for_vlm_keynote_recount",
                    target=kn_num,
                    detail=f"Count {count} on {plan_code} exceeds threshold.",
                    data={"plan_code": plan_code, "current_count": count},
                )

    # --- Check: sequentiality ---
    # Keynotes should typically be numbered 1, 2, 3... (possibly with gaps).
    # Large jumps (e.g., #1, #2, #47) indicate parsing errors.
    if numbers_int:
        numbers_sorted = sorted(numbers_int)
        max_num = numbers_sorted[-1]
        # If the maximum number is much larger than the count of keynotes,
        # there may be spurious entries from address text, note numbers, etc.
        if max_num > len(numbers_int) * 3 and max_num > 20:
            result._add_issue(
                "non_sequential_keynotes",
                f"Keynote numbers range up to {max_num} but only "
                f"{len(numbers_int)} keynotes found. "
                f"May include false positives from note/address text.",
                severity=SEVERITY_WARNING,
                deduction=0.10,
            )

        # Any number > 20 is suspicious per the max keynote number limit
        # defined in keynotes.py.
        over_20 = [n for n in numbers_sorted if n > 20]
        if over_20:
            result._add_issue(
                "keynote_number_too_high",
                f"Keynote numbers > 20 detected: {over_20}. "
                f"These are likely false positives.",
                severity=SEVERITY_WARNING,
                deduction=0.05 * len(over_20),
            )
            for n in over_20:
                result._add_correction(
                    action="remove_keynote",
                    target=str(n),
                    detail=f"Keynote #{n} exceeds max plausible number (20).",
                )

    # --- Check: all_keynote_counts consistency ---
    # Verify that counts in the per-plan dict don't exceed the threshold.
    for plan_code, plan_kn_counts in all_keynote_counts.items():
        for kn_num_str, count in plan_kn_counts.items():
            if isinstance(count, (int, float)) and count > _MAX_PLAUSIBLE_KEYNOTE_COUNT:
                # Only flag if not already flagged via the keynote objects
                already_flagged = any(
                    i["check"] == "keynote_count_too_high"
                    and kn_num_str in i["message"]
                    and plan_code in i["message"]
                    for i in result.issues
                )
                if not already_flagged:
                    result._add_issue(
                        "keynote_count_too_high",
                        f"Keynote #{kn_num_str} on {plan_code} has "
                        f"count {count} in all_keynote_counts.",
                        severity=SEVERITY_WARNING,
                        deduction=0.10,
                    )

    return _finalize(result, project_id, "keynote")


# ═══════════════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _finalize(
    result: CoveResult,
    project_id: str,
    agent_name: str,
) -> CoveResult:
    """Clamp confidence and persist the result."""
    result.confidence = max(0.0, min(1.0, result.confidence))
    result.passed = result.passed and result.confidence >= 0.5

    # Build a short reasoning suffix with the score.
    n_errors = sum(
        1 for i in result.issues if i["severity"] == SEVERITY_ERROR
    )
    n_warnings = sum(
        1 for i in result.issues if i["severity"] == SEVERITY_WARNING
    )
    result.reasoning += (
        f" | confidence={result.confidence:.2f}, "
        f"passed={result.passed}, "
        f"errors={n_errors}, warnings={n_warnings}"
    )

    if project_id:
        result._persist(project_id, agent_name)

    logger.info(
        "COVE [%s]: confidence=%.2f passed=%s issues=%d corrections=%d",
        agent_name,
        result.confidence,
        result.passed,
        len(result.issues),
        len(result.corrections),
    )

    return result
