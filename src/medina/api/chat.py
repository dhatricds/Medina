"""Chat engine — conversational interface for corrections, questions, and params.

Extends the Fix It LLM interpretation with multi-turn conversation, intent
detection, and memory-aware context building.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from medina.api.feedback import CorrectionReason, TARGET_ALL
from medina.api.fix_it import FixItAction, FixItInterpretation, _build_context
from medina.config import get_config

logger = logging.getLogger(__name__)


class ChatMessage(BaseModel):
    """A single chat message."""
    role: str  # "user", "assistant", "system"
    content: str
    intent: str | None = None  # "question", "correction", "param_change", "general"
    actions: list[FixItAction] | None = None  # For correction intent
    suggestions: list[str] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    """Response from the chat engine."""
    message: ChatMessage
    needs_confirmation: bool = False  # If True, actions need user OK before applying
    highlight: dict | None = None  # {"fixture_code": "B2", "plan": "E601-L1"}


# ── Intent detection ─────────────────────────────────────────────────

INTENT_KEYWORDS = {
    "correction": [
        "should be", "is wrong", "incorrect", "fix ", "fix it", "change to",
        "correct ", "not right", "missing", "remove", "add fixture",
        "count should", "actually", "overcounted", "undercounted",
        "too many", "too few", "reprocess", "recount", "re-run",
        "redo", "run again", "process only", "only process",
        "not a lighting", "not lighting", "is a lighting",
        "is lighting", "demolition", "skip page", "skip these",
        "don't process", "do not process", "ignore page",
        "we have to process", "need to process",
        "subplan", "sub-plan", "sub plan", "viewport",
        "find inventory", "find fixture", "find the inventory",
        "embedded plan", "embedded lighting",
        "process this", "count this", "count these", "count the",
        "this is a", "this page is", "this page has",
        "schedule is on", "schedule on page", "schedule on this",
        "has a schedule", "has schedule", "has fixtures",
        "look at", "check this", "check page",
        "combo page", "combo", "both schedule and",
        "reclassify", "classify as", "mark as",
        "split this", "split page", "has two", "has multiple",
        "is not a", "is not lighting", "not a schedule",
        "these are", "those are", "that is",
        "highlight", "show me where", "show position", "show marker",
        "locate", "find on plan", "where is fixture", "where are",
        "toggle is wrong", "markers are wrong", "positions are wrong",
        "inventory is right", "inventory is wrong", "count is right",
        "count is wrong", "toggle is right",
        "not showing", "not displayed", "doesn't show", "does not show",
        "can't see", "cannot see", "not visible", "not appearing",
        "left panel", "leftpanel", "pdf viewer", "selected fixture",
        "show the", "display the", "show fixture", "show inventory",
    ],
    "param_change": [
        "tolerance", "threshold", "dpi", "increase", "decrease", "set",
        "parameter", "font size", "sensitivity", "keynote max",
        "vision counting", "render",
    ],
    "question": [
        "why", "how many", "what is", "explain", "which", "where",
        "tell me", "show me", "can you", "did you", "?",
    ],
}


def _detect_intent(text: str) -> str:
    """Detect user intent from message text. Returns intent string."""
    lower = text.lower().strip()

    # Score each intent
    scores: dict[str, int] = {"correction": 0, "param_change": 0, "question": 0}
    for intent, keywords in INTENT_KEYWORDS.items():
        for kw in keywords:
            if kw in lower:
                scores[intent] += 1

    # Correction beats question (user might phrase correction as question)
    if scores["correction"] >= 2:
        return "correction"
    if scores["param_change"] >= 2:
        return "param_change"
    if scores["question"] >= 1 and scores["correction"] == 0:
        return "question"
    if scores["correction"] >= 1:
        return "correction"
    if scores["param_change"] >= 1:
        return "param_change"

    # Fallback: if user mentions a page/sheet code and uses imperative
    # language, treat as correction (they're likely giving an instruction
    # about that page).
    if re.search(r"\b[Ee]\d+\.?\d*\b|\bpage\s+\d+\b|\bpg\s*\d+\b", lower):
        return "correction"

    return "general"


# ── Page reference detection + rendering ─────────────────────────────

# Matches "page 4", "pg 5", "page4", or sheet codes like "E1.11", "E601"
_PAGE_REF_RE = re.compile(
    r"""(?:page\s*|pg\s*)(\d+)          # "page 4", "pg5"
    |   \b(E[\d]+(?:\.[\d]+)?[A-Za-z]?) # "E1.11", "E601", "E301"
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _extract_page_references(
    text: str, project_data: dict,
) -> list[dict]:
    """Find page numbers/sheet codes mentioned in user text.

    Returns list of {"page_number": int, "pdf_page_index": int,
    "sheet_code": str, "source_path": str} for each referenced page.
    """
    pages = project_data.get("pages", [])
    refs: list[dict] = []
    seen: set[int] = set()

    for m in _PAGE_REF_RE.finditer(text):
        page_num_str = m.group(1)
        sheet_code_str = m.group(2)

        for pg in pages:
            pg_num = pg.get("page_number")
            pg_code = pg.get("sheet_code") or ""
            matched = False
            if page_num_str and pg_num == int(page_num_str):
                matched = True
            elif sheet_code_str and pg_code.upper() == sheet_code_str.upper():
                matched = True
            if matched and pg_num not in seen:
                seen.add(pg_num)
                refs.append(pg)
                break

    return refs


def _render_referenced_pages(
    refs: list[dict], max_pages: int = 2, dpi: int = 150,
) -> list[dict]:
    """Render referenced pages to base64 images for the VLM call.

    Returns list of Anthropic image content blocks.
    """
    from medina.pdf.renderer import render_page_to_image

    image_blocks: list[dict] = []
    for ref in refs[:max_pages]:
        source_path = ref.get("source_path", "")
        pdf_page_index = ref.get("pdf_page_index", 0)
        if not source_path:
            continue
        try:
            png_bytes = render_page_to_image(source_path, pdf_page_index, dpi=dpi)
            b64 = base64.standard_b64encode(png_bytes).decode("ascii")
            page_label = ref.get("sheet_code") or f"page {ref.get('page_number', '?')}"
            image_blocks.append({
                "type": "text",
                "text": f"[Image of {page_label}]",
            })
            image_blocks.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": b64,
                },
            })
            logger.info("Rendered %s for chat VLM (%d KB)", page_label, len(png_bytes) // 1024)
        except Exception as e:
            logger.warning("Failed to render page for chat: %s", e)

    return image_blocks


# ── System prompt ─────────────────────────────────────────────────────

CHAT_SYSTEM_PROMPT = """\
You are Medina, an AI assistant built into a web application for electrical \
construction drawing analysis. You help contractors review and correct \
lighting fixture inventory extractions from PDF blueprints.

THE APPLICATION has three panels:
- LEFT: PDF viewer showing blueprint pages (zoom, navigate)
- CENTER: Agent pipeline status (5 agents: Search, Schedule, Count, Keynote, QA)
- RIGHT: Fixture table and Keynote table with editable counts, plus this chat panel

ONLY REFERENCE FEATURES THAT ACTUALLY EXIST in this app. \
Do NOT mention features like "keynote layers", "blueprint viewer layers", \
"zoom to keynote", "filter panels", "annotation tools", "highlight modes", \
or any features not listed above.

YOUR CAPABILITIES:
1. Answer questions using the project data provided below
2. Return JSON actions to correct counts, add/remove fixtures, reclassify pages, split pages
3. Return JSON highlight instructions to show fixture/keynote positions on the PDF
4. Return JSON param_changes to adjust pipeline settings

UI / DISPLAY ISSUES:
- When the user says the left panel is "not showing" fixtures, positions aren't visible, \
or the selected fixture isn't highlighted: return a highlight JSON for the fixture/keynote \
they're trying to see. This will navigate the PDF viewer and display marker overlays.
- If the user mentions a specific fixture code, highlight that code.
- If the user says "selected fixture" without specifying which one, ask which fixture code \
and plan they want to see.
- NEVER say "I don't have access to UI state" or "I cannot control the frontend." \
You CAN control what the left panel shows by returning highlight JSON.

CRITICAL: When the user TELLS you something about the project (e.g., "this page is a \
lighting plan", "there are subplans here", "the schedule is on page 3", "process only \
these pages", "count the fixtures on E103"), ALWAYS act on it by returning the \
appropriate JSON action. The user is the expert — they know what's on their drawings. \
NEVER dismiss user instructions with "I don't have that information." \
Only say that when the user ASKS a question about data you genuinely don't have.

RULES:
- Be concise. Contractors are busy. 1-3 sentences max.
- When answering questions, reference the project data below.
- NEVER invent fixture codes, page numbers, or counts not in the context.
- If page images are attached, LOOK at them to identify content.
- When the user gives instructions or feedback, ALWAYS generate appropriate JSON actions.

HIGHLIGHTING / SHOWING POSITIONS:
- When user says "highlight", "show me", "where is", "locate", "find on plan", \
"show positions", "show the markers" — return a highlight JSON.
- This opens the PDF viewer to the plan page and shows marker overlays on each \
detected position. Users can click markers to toggle them (accept/reject).
- For fixtures: ```json\n{"highlight": {"fixture_code": "B2", "plan": "E601-L1"}}\n```
- For keynotes: ```json\n{"highlight": {"keynote_number": "3", "plan": "E200"}}\n```
- Omit "plan" if user didn't specify — it will highlight on the first available plan.
- You can highlight multiple items by returning multiple highlight objects.

COUNTING ISSUES (fixture or keynote count wrong/missed):
- Do NOT guess counts. Return a highlight JSON so user can verify visually.
- After highlighting, the user can click markers to reject false positives or \
add missed positions. The count auto-updates based on accepted markers.

MARKER / TOGGLE ISSUES:
- "toggle is wrong" / "markers are wrong" / "positions are wrong" = the highlighted \
marker boxes on the plan are in incorrect positions (false detections).
- "inventory is right but toggle is wrong" = the count in the table is correct \
but the marker positions shown on the PDF don't match real fixture locations. \
Return a highlight JSON so the user can click to reject wrong markers and add correct ones.
- "inventory is wrong but toggle is right" / "count is wrong" = the markers are \
in the right spots but the count doesn't match. Return a highlight JSON — after \
the user adjusts markers, the count will update.
- ALWAYS return a highlight JSON for these requests so the user can visually verify.

STRUCTURAL CORRECTIONS (page not processed, wrong classification, which pages to include):
- Return JSON actions block. Use fixture_code = page number or sheet code.
- When user says "only process X, Y, Z" or "process only X, Y, Z": reclassify ALL other \
lighting plan pages as "other". Generate one reclassify_page action per page to EXCLUDE. \
Keep the named pages as lighting_plan. Example: if lighting_plans are [E101,E102,E103,E104] \
and user says "only process E103, E104", return actions to reclassify E101 and E102 as "other".
- When user says a page IS a lighting plan, reclassify it as lighting_plan.
- When user says a page is NOT a lighting plan, reclassify it as "other".
- Examples:
  - Page as lighting plan: ```json\n{"actions": [{"action": "reclassify_page", "fixture_code": "4", "fixture_data": {"page_type": "lighting_plan"}, "reason": "other"}]}\n```
  - Page as schedule: ```json\n{"actions": [{"action": "reclassify_page", "fixture_code": "E501", "fixture_data": {"page_type": "schedule"}, "reason": "other"}]}\n```
  - Exclude pages: ```json\n{"actions": [{"action": "reclassify_page", "fixture_code": "E101", "fixture_data": {"page_type": "other"}, "reason": "other"}, {"action": "reclassify_page", "fixture_code": "E102", "fixture_data": {"page_type": "other"}, "reason": "other"}]}\n```
  - Split multi-viewport page: ```json\n{"actions": [{"action": "split_page", "fixture_code": "E601", "fixture_data": {"viewports": [{"label": "L1"}, {"label": "MEZ"}]}, "reason": "other"}]}\n```
- SUBPLANS / VIEWPORTS: When user mentions "subplans", "sub-plans", "viewports", "find inventory \
in subplans", or "embedded lighting plans": LOOK at the attached page image. Identify lighting \
plan viewports by their title labels (e.g., "MAIN LEVEL LIGHTING PLAN - AREA 'B'"). \
Return a split_page action with the lighting viewport labels. If the page is currently classified \
as "schedule" or "other", ALSO include a reclassify_page action to change it to "lighting_plan" \
so the schedule table is still extracted AND fixture counting runs on the subplans. Example for \
a combo page with 2 lighting viewports:
```json
{"actions": [{"action": "reclassify_page", "fixture_code": "E1.11", "fixture_data": {"page_type": "lighting_plan"}, "reason": "other"}, {"action": "split_page", "fixture_code": "E1.11", "fixture_data": {"viewports": [{"label": "AB"}, {"label": "AC"}]}, "reason": "other"}]}
```
- IMPORTANT: Always identify the viewport labels from the page image. Labels like "AREA B" → "AB", \
"AREA C" → "AC", "LEVEL 1" → "L1", "MEZZANINE" → "MEZ".

PARAMETER CHANGES:
```json
{"param_changes": [{"key": "font_size_tolerance_multi", "value": 0.6, "scope": "project_id"}]}
```

Available parameters: font_size_tolerance_multi (1.01-3.0), font_size_tolerance_single (1.01-2.0), \
isolation_distance (5-50), dedup_distance (20-200), legend_col_x_frac (0.5-1.0), \
title_block_frac (0.5-1.0), schedule_render_dpi (72-400), keynote_max_number (5-99), \
max_plausible_keynote_count (3-50), qa_confidence_threshold (0.5-1.0), \
use_vision_counting (bool), render_dpi (72-600).

Action types: count_override, keynote_count_override (fixture_code="KN-{number}"), \
add, remove, update_spec, reclassify_page, split_page.

Reason values: missed_embedded_schedule, wrong_fixture_code, extra_fixture, \
missing_fixture, vlm_misread, wrong_bounding_box, manual_count_edit, other.
"""


# ── Context building ──────────────────────────────────────────────────

def _build_chat_context(
    project_data: dict,
    chat_history: list[dict],
    memory_context: dict | None = None,
) -> str:
    """Build full context string for the chat LLM."""
    parts: list[str] = []

    # Project inventory context (reuse fix_it's builder)
    parts.append(_build_context(project_data))

    # Recent chat messages
    if chat_history:
        parts.append("\nRecent conversation:")
        for msg in chat_history[-10:]:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            # Truncate long messages
            if len(content) > 200:
                content = content[:200] + "..."
            parts.append(f"  {role}: {content}")

    # Memory context (from DB/ChromaDB)
    if memory_context:
        past = memory_context.get("past_corrections", [])
        if past:
            parts.append(f"\nPast corrections for this source: {len(past)} learnings stored")
        similar = memory_context.get("similar_corrections", [])
        if similar:
            parts.append("Similar corrections from other projects:")
            for s in similar[:3]:
                parts.append(f"  - {s.get('document', '')[:100]}")
        patterns = memory_context.get("global_patterns", [])
        if patterns:
            parts.append(f"Global patterns detected: {len(patterns)}")

    return "\n".join(parts)


# ── Suggestion generator ─────────────────────────────────────────────

def generate_suggestions(project_data: dict) -> list[str]:
    """Auto-generate suggestion chips based on project results."""
    suggestions: list[str] = []

    # Proactive guidance when no plans or fixtures found
    lighting_plans = project_data.get("lighting_plans", [])
    fixtures = project_data.get("fixtures", [])
    pages = project_data.get("pages", [])

    if not lighting_plans and pages:
        page_list = ", ".join(
            p.get("sheet_code") or f"pg{p.get('page_number', '?')}"
            for p in pages[:10]
        )
        suggestions.append(
            f"No lighting plans found. Pages: {page_list} — which should I process?"
        )

    if not fixtures and lighting_plans:
        suggestions.append(
            "No fixture types extracted. Does any page have a schedule table?"
        )

    # Zero-count fixtures
    for f in fixtures:
        if f.get("total", 0) == 0:
            suggestions.append(
                f"Fixture {f['code']} has 0 count — should it be removed?"
            )

    qa = project_data.get("qa_report", {})
    if qa:
        warnings = qa.get("warnings", [])
        for w in warnings[:3]:
            suggestions.append(f"QA flag: {w[:80]}")

        confidence = qa.get("overall_confidence", 1.0)
        if confidence < 0.95:
            suggestions.append(
                f"Overall confidence is {confidence:.0%} — review flagged items?"
            )

    return suggestions[:5]


# ── Main chat function ────────────────────────────────────────────────

# ── Reprocess shortcut detection ──────────────────────────────────────
# Ordered by specificity — first match wins.  Each entry:
#   (keywords, target_agents, label, use_vision)
_REPROCESS_SHORTCUTS: list[tuple[list[str], frozenset[int], str, bool]] = [
    (["recount keynote", "keynotes missing", "missing keynote"],
     frozenset({4, 5}), "keynotes", True),
    (["recount fixture", "recount the fixture", "fixture count", "count again"],
     frozenset({3, 5}), "fixture counts", True),
    (["missing schedule", "schedule table"],
     TARGET_ALL, "with schedule re-extraction", False),
    (["missing plan", "missing page", "missing blueprint", "missing lighting"],
     TARGET_ALL, "with page re-classification", False),
    # Catch-all: "reprocess", "rerun", "redo", "run again"
    (["reprocess", "rerun", "re-run", "redo", "run again", "try again", "process again"],
     TARGET_ALL, "everything", True),
    # Generic "recount" without specifying fixture/keynote → count agent
    (["recount"],
     frozenset({3, 5}), "fixture counts", True),
]


def _detect_reprocess_shortcut(
    text: str,
) -> tuple[frozenset[int], str, bool] | None:
    """Scan text for reprocess keywords. Returns (target, label, use_vision) or None."""
    lower = text.lower()
    for keywords, target, label, vision in _REPROCESS_SHORTCUTS:
        if any(kw in lower for kw in keywords):
            return target, label, vision
    return None


async def process_chat_message(
    user_text: str,
    project_data: dict,
    project_id: str = "",
    source_key: str = "",
) -> ChatResponse:
    """Process a user chat message and return a response.

    Detects intent, builds context, calls LLM, and routes the response.
    """
    config = get_config()

    # ── Direct reprocess shortcut ─────────────────────────────────
    # When user clearly wants a reprocess/recount, skip LLM entirely
    # for reliability and trigger the pipeline directly on confirm.
    shortcut = _detect_reprocess_shortcut(user_text)
    if shortcut is not None:
        target, label, use_vision = shortcut
        # Build a user-friendly summary of what will be reprocessed
        fixtures = project_data.get("fixtures", [])
        plans = project_data.get("lighting_plans", [])
        keynotes = project_data.get("keynotes", [])
        summary_parts = []
        if fixtures:
            summary_parts.append(f"{len(fixtures)} fixture types")
        if keynotes:
            summary_parts.append(f"{len(keynotes)} keynotes")
        if plans:
            summary_parts.append(f"across {len(plans)} plan(s)")
        summary = ", ".join(summary_parts) if summary_parts else "this project"

        vision_note = " using vision verification" if use_vision else ""

        # Save user message to DB
        try:
            from medina.db import repositories as repo
            repo.add_chat_message(project_id, "user", user_text, intent="correction")
        except Exception:
            pass

        reprocess_action = FixItAction(
            action="reprocess",
            fixture_code="*",
            reason="other",
            reason_detail=f"User requested reprocess: {label}",
            fixture_data={"target": sorted(target), "use_vision": use_vision},
        )
        return ChatResponse(
            message=ChatMessage(
                role="assistant",
                content=f"I'll recount {label}{vision_note} ({summary}). Confirm below to start.",
                intent="correction",
                actions=[reprocess_action],
            ),
            needs_confirmation=True,
        )

    # Detect intent
    intent = _detect_intent(user_text)

    # Get chat history from DB
    chat_history: list[dict] = []
    try:
        from medina.db import repositories as repo
        chat_history = repo.get_recent_chat(project_id, n=10)
    except Exception:
        pass

    # Get memory context
    memory_context: dict | None = None
    try:
        from medina.planning.memory_retrieval import get_planning_context
        memory_context = get_planning_context("chat", source_key, project_id)
    except Exception:
        pass

    # Save user message to DB
    try:
        from medina.db import repositories as repo
        repo.add_chat_message(project_id, "user", user_text, intent=intent)
    except Exception:
        pass

    # Save to ChromaDB for future retrieval
    try:
        from medina.db.vector_store import add_document, QA_INTERACTIONS_COLLECTION
        add_document(
            QA_INTERACTIONS_COLLECTION,
            f"chat_{project_id}_{len(chat_history)}",
            user_text,
            {"project_id": project_id, "role": "user", "intent": intent},
        )
    except Exception:
        pass

    # Build context
    context = _build_chat_context(project_data, chat_history, memory_context)

    if not config.has_vlm_key:
        return ChatResponse(
            message=ChatMessage(
                role="assistant",
                content="API key not configured. Cannot process chat messages.",
                intent="general",
            )
        )

    # Detect page references — if the user mentions a page, render it
    # so the LLM can actually see what's on it.
    page_refs = _extract_page_references(user_text, project_data)
    image_blocks_bytes: list[bytes] = []
    image_labels: list[str] = []
    if page_refs and intent in ("correction", "general"):
        from medina.pdf.renderer import render_page_to_image
        for ref in page_refs[:2]:
            source_path = ref.get("source_path", "")
            pdf_page_index = ref.get("pdf_page_index", 0)
            if not source_path:
                continue
            try:
                png_bytes = render_page_to_image(source_path, pdf_page_index, dpi=150)
                image_blocks_bytes.append(png_bytes)
                page_label = ref.get("sheet_code") or f"page {ref.get('page_number', '?')}"
                image_labels.append(page_label)
                logger.info("Rendered %s for chat VLM (%d KB)", page_label, len(png_bytes) // 1024)
            except Exception as e:
                logger.warning("Failed to render page for chat: %s", e)

    # Build the prompt with context and page image labels
    full_prompt = f"System instructions:\n{CHAT_SYSTEM_PROMPT}\n\n"

    # Add chat history
    for msg in chat_history[-6:]:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        full_prompt += f"{role}: {content}\n"

    full_prompt += f"\nProject context:\n{context}\n\nUser message:\n{user_text}"

    if image_labels:
        full_prompt += f"\n\n[Page images attached: {', '.join(image_labels)}]"

    try:
        from medina.vlm_client import get_vlm_client
        vlm = get_vlm_client(config)

        text = vlm.vision_query(
            images=image_blocks_bytes,
            prompt=full_prompt,
            max_tokens=1024,
        )

        # Parse response for structured actions
        actions = None
        needs_confirmation = False
        param_changes = None
        highlight = None

        json_str = ""
        if "```json" in text:
            try:
                json_start = text.index("```json") + 7
                json_end = text.index("```", json_start)
                json_str = text[json_start:json_end].strip()
                # LLM may return multiple JSON objects separated by
                # newlines (one per item).  Parse only the first.
                try:
                    parsed = json.loads(json_str)
                except json.JSONDecodeError:
                    # Try first line only (handles multi-object blocks)
                    first_line = json_str.split("\n")[0].strip()
                    if first_line:
                        parsed = json.loads(first_line)
                    else:
                        raise

                if "highlight" in parsed:
                    # Highlight instruction — immediate, no confirmation
                    highlight = parsed["highlight"]
                    intent = "correction"
                elif "actions" in parsed:
                    # Correction actions — LLM may omit fields that
                    # FixItAction requires, so fill in sensible defaults.
                    raw_actions = parsed["actions"]
                    validated: list[FixItAction] = []
                    for a in raw_actions:
                        if not isinstance(a, dict):
                            continue
                        # LLM may use "type" instead of "action"
                        if "action" not in a and "type" in a:
                            a["action"] = a.pop("type")
                        # LLM may use page/page_code/sheet_code instead of fixture_code.
                        # Check for EMPTY as well as missing — LLM sometimes
                        # includes "fixture_code": "" alongside "page": 4.
                        if not a.get("fixture_code"):
                            a["fixture_code"] = str(
                                a.pop("page", None)
                                or a.pop("page_code", None)
                                or a.pop("sheet_code", None)
                                or a.pop("code", None)
                                or ""
                            )
                        if "reason" not in a:
                            a["reason"] = CorrectionReason.OTHER.value
                        # Ensure fixture_data has the right fields for
                        # reclassify_page / split_page actions.  LLM often
                        # puts page_type / viewports at the top level.
                        action_type = a.get("action", "")
                        if "fixture_data" not in a:
                            a["fixture_data"] = {}
                        if action_type == "reclassify_page":
                            pt = (a.pop("page_type", None)
                                  or a["fixture_data"].get("page_type")
                                  or "lighting_plan")
                            a["fixture_data"]["page_type"] = pt
                        elif action_type == "split_page":
                            vp = (a.pop("viewports", None)
                                  or a["fixture_data"].get("viewports")
                                  or [])
                            a["fixture_data"]["viewports"] = vp
                            # split_page also needs page_type
                            if "page_type" not in a["fixture_data"]:
                                a["fixture_data"]["page_type"] = "lighting_plan"
                        validated.append(FixItAction.model_validate(a))
                    if validated:
                        actions = validated
                        needs_confirmation = True
                        intent = "correction"
                elif "param_changes" in parsed:
                    param_changes = parsed["param_changes"]
                    intent = "param_change"
            except (ValueError, json.JSONDecodeError) as exc:
                logger.warning("Chat JSON parse error: %s — raw JSON: %s", exc, json_str[:300])

        # Clean the text (remove JSON blocks for display)
        display_text = text
        if "```json" in display_text:
            parts = display_text.split("```json")
            cleaned = [parts[0]]
            for part in parts[1:]:
                if "```" in part:
                    after_json = part.split("```", 1)[1]
                    cleaned.append(after_json)
                else:
                    cleaned.append(part)
            display_text = "".join(cleaned).strip()

        # If LLM returned only a JSON block, provide a user-friendly message
        if not display_text:
            if highlight:
                code = highlight.get("fixture_code") or highlight.get("keynote_number", "")
                plan = highlight.get("plan", "")
                plan_msg = f" on {plan}" if plan else ""
                display_text = f"Highlighting {code}{plan_msg} on the blueprint. Toggle markers to correct the count."
            elif actions:
                summaries = [f"{a.action} {a.fixture_code}" for a in actions]
                display_text = f"I'll {', '.join(summaries)}. Please confirm below."
            else:
                display_text = text  # Fall back to raw text

        # Handle param changes
        if param_changes:
            try:
                from medina.runtime_params import validate_param
                from medina.db import repositories as repo
                applied = []
                for pc in param_changes:
                    key = pc["key"]
                    value = validate_param(key, pc["value"])
                    scope = pc.get("scope", "project_id")
                    scope_key = project_id if scope == "project_id" else source_key
                    repo.set_param(key, value, scope=scope, scope_key=scope_key)
                    applied.append(f"{key}={value}")
                if applied:
                    display_text += f"\n\nApplied: {', '.join(applied)}"
            except Exception as e:
                display_text += f"\n\nFailed to apply params: {e}"

        # Build response message
        msg = ChatMessage(
            role="assistant",
            content=display_text,
            intent=intent,
            actions=actions,
        )

        # Save assistant response to DB
        try:
            from medina.db import repositories as repo
            repo.add_chat_message(
                project_id, "assistant", display_text, intent=intent,
            )
        except Exception:
            pass

        return ChatResponse(
            message=msg,
            needs_confirmation=needs_confirmation,
            highlight=highlight,
        )

    except Exception as e:
        logger.exception("Chat processing failed: %s", e)
        error_msg = ChatMessage(
            role="assistant",
            content=f"Sorry, I encountered an error: {e}",
            intent="general",
        )
        return ChatResponse(message=error_msg)
