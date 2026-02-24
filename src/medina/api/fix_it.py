"""LLM-powered interpretation of natural language corrections.

Takes a user's plain-English description of what needs fixing and returns
structured FixItAction objects that map to the existing feedback system.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from medina.api.feedback import CorrectionReason
from medina.config import get_config

logger = logging.getLogger(__name__)


class FixItAction(BaseModel):
    """A single structured correction action derived from user text."""
    action: str  # "add", "remove", "count_override", "update_spec", "reclassify_page", "split_page"
    fixture_code: str
    reason: str = CorrectionReason.OTHER.value
    reason_detail: str = ""
    fixture_data: dict[str, Any] = Field(default_factory=dict)
    spec_patches: dict[str, str] = Field(default_factory=dict)
    confidence: float = 1.0


class FixItInterpretation(BaseModel):
    """Result of interpreting a user's natural language correction."""
    actions: list[FixItAction] = Field(default_factory=list)
    explanation: str = ""
    clarification: str = ""


def _build_context(project_data: dict) -> str:
    """Build a concise context string from project data for the LLM."""
    lines: list[str] = []

    # Page listing so LLM knows all available pages
    pages = project_data.get("pages", [])
    if pages:
        lines.append("All pages in this document:")
        for p in pages:
            code = p.get("sheet_code") or "?"
            desc = p.get("description") or ""
            ptype = p.get("type") or p.get("page_type") or "?"
            lines.append(f"  Page {p.get('page_number', '?')} ({code}): {ptype} — {desc}")
        lines.append("")

    plans = project_data.get("lighting_plans", [])
    lines.append(f"Lighting plans: {', '.join(plans) if plans else 'none'}")

    schedule_pages = project_data.get("schedule_pages", [])
    lines.append(f"Schedule pages: {', '.join(schedule_pages) if schedule_pages else 'none'}")

    fixtures = project_data.get("fixtures", [])
    if fixtures:
        lines.append("\nCurrent fixture inventory:")
        for f in fixtures:
            counts = f.get("counts_per_plan", {})
            count_parts = [f"{p}={c}" for p, c in counts.items()]
            total = f.get("total", 0)
            desc = f.get("description", "")
            sched = f.get("schedule_page", "")
            sched_str = f" | schedule_page={sched}" if sched else ""
            lines.append(
                f"  {f['code']}: {desc} | counts: {', '.join(count_parts)} | total={total}{sched_str}"
            )

    keynotes = project_data.get("keynotes", [])
    if keynotes:
        lines.append("\nKeynotes:")
        for k in keynotes:
            counts = k.get("counts_per_plan", {})
            count_parts = [f"{p}={c}" for p, c in counts.items()]
            lines.append(
                f"  #{k['keynote_number']}: {k.get('keynote_text', '')[:80]} | "
                f"counts: {', '.join(count_parts)}"
            )

    return "\n".join(lines)


SYSTEM_PROMPT = """\
You are an electrical construction drawing expert helping interpret user \
corrections to a lighting fixture inventory extraction pipeline.

Given the current fixture inventory, page listing, and the user's natural \
language description of what needs fixing, return a JSON object with \
structured correction actions.

Rules:
- Each action must reference an existing fixture code OR define a new one.
- For count corrections, specify the plan sheet code and the corrected count.
- For adding a fixture, provide at minimum the code and a description.
- For removing a fixture, specify the code and why.
- For spec updates, specify which fields to change.
- For page reclassification, the user may refer to a page by sheet code \
(e.g., "E601") or page number (e.g., "page 5"). Use fixture_code to hold \
the sheet code or page number as a string. The page_type in fixture_data \
must be one of: lighting_plan, schedule, demolition_plan, power_plan, \
symbols_legend, detail, cover, site_plan, fire_alarm, riser, other.
- IMPORTANT: When the user says a page "has lighting plan", "is a lighting \
plan", "has enlarged lighting", "should be processed", or similar — this \
means reclassify that page as lighting_plan. When they say a page "has \
schedule" — reclassify as schedule. Do NOT ask for clarification on these.
- If the user's input is truly ambiguous, set "clarification" to a question.
- Set confidence 0.0-1.0 based on how unambiguous the user's intent is.

Action types:
- "count_override": correct a fixture count on a specific plan
- "keynote_count_override": correct a keynote count on a specific plan. Use \
fixture_code = "KN-{number}" (e.g., "KN-5"). In fixture_data include \
{"keynote_number": "5", "sheet": "E601-L1", "corrected": 3}.
- "add": add a missing fixture type
- "remove": remove a wrongly extracted fixture
- "update_spec": change spec fields (description, voltage, mounting, schedule_page, etc.)
- "reclassify_page": change how a page is classified (e.g., treat a page \
currently classified as "detail" or "other" as "lighting_plan" or "schedule")
- "split_page": split a multi-viewport page into separate sub-plans. Use \
when the user says a page has multiple lighting plans (e.g., "E601 has Level 1 \
and Mezzanine lighting plans"). fixture_code = sheet code. fixture_data should \
contain {"viewports": []} (empty list triggers auto-detection of viewport \
boundaries). If the user specifies explicit viewport names/labels, include them \
as {"viewports": [{"label": "L1", "title": "Level 1"}, {"label": "MEZ", \
"title": "Mezzanine"}]} — bbox will be auto-detected.

Reason values: missed_embedded_schedule, wrong_fixture_code, extra_fixture, \
missing_fixture, vlm_misread, wrong_bounding_box, manual_count_edit, other

Return ONLY valid JSON matching this schema:
{
  "actions": [
    {
      "action": "count_override|keynote_count_override|add|remove|update_spec|reclassify_page|split_page",
      "fixture_code": "A1 or E601 or 5 (page number for reclassify/split)",
      "reason": "<reason_value>",
      "reason_detail": "human-readable explanation",
      "fixture_data": {"page_type": "lighting_plan for reclassify_page", "viewports": "[] for split_page"},
      "spec_patches": {},
      "confidence": 0.95
    }
  ],
  "explanation": "Summary of what will be changed",
  "clarification": ""
}"""


async def interpret_fix_it(
    user_text: str,
    project_data: dict,
) -> FixItInterpretation:
    """Call Claude API to interpret natural language correction.

    Args:
        user_text: The contractor's plain-English correction description.
        project_data: Current project result data (fixtures, plans, keynotes).

    Returns:
        Structured interpretation with actions, explanation, and optional
        clarification question.
    """
    import anthropic

    config = get_config()
    if not config.anthropic_api_key:
        logger.warning("No API key configured — returning empty interpretation")
        return FixItInterpretation(
            explanation="Cannot interpret: no API key configured.",
        )

    context = _build_context(project_data)

    client = anthropic.Anthropic(api_key=config.anthropic_api_key)

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Current inventory context:\n{context}\n\n"
                        f"User correction:\n{user_text}"
                    ),
                },
            ],
        )

        # Extract text content
        text = ""
        for block in response.content:
            if hasattr(block, "text"):
                text += block.text

        # Parse JSON from response — handle markdown code fences
        text = text.strip()
        if text.startswith("```"):
            # Strip ```json ... ``` wrapper
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        parsed = json.loads(text)
        return FixItInterpretation.model_validate(parsed)

    except json.JSONDecodeError as e:
        logger.warning("Failed to parse LLM response as JSON: %s", e)
        return FixItInterpretation(
            explanation=f"Could not parse LLM response: {e}",
            clarification="Please try rephrasing your correction more specifically.",
        )
    except Exception as e:
        logger.exception("Fix-it interpretation failed: %s", e)
        return FixItInterpretation(
            explanation=f"Interpretation error: {e}",
        )
