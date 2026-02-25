"""Chat engine — conversational interface for corrections, questions, and params.

Extends the Fix It LLM interpretation with multi-turn conversation, intent
detection, and memory-aware context building.
"""
from __future__ import annotations

import base64
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
        "should be", "is wrong", "incorrect", "fix", "change", "correct",
        "not right", "missing", "remove", "add fixture", "count should",
        "actually", "overcounted", "undercounted", "too many", "too few",
        "reprocess", "recount", "re-run", "redo", "run again",
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
You are Medina, an AI assistant for electrical construction drawing analysis. \
You help contractors review and correct lighting fixture inventory extractions.

You can:
1. **Answer questions** about the current project — fixtures, counts, pages, keynotes
2. **Make corrections** — fix counts, add/remove fixtures, reclassify pages, update specs
3. **Adjust parameters** — change pipeline settings like font tolerance, DPI, etc.
4. **Explain** why certain decisions were made during extraction

Context about the current project is provided below. Use it to give accurate, \
specific answers.

IMPORTANT: When the user mentions a specific page, you may receive an IMAGE of that \
page. LOOK at the image carefully to understand what is on it — identify lighting \
fixtures, schedule tables, keynotes, viewports, and page types. Use what you SEE \
to make accurate corrections. If the page contains a lighting plan with fixture \
symbols, classify it as lighting_plan. If it has multiple lighting viewports \
(e.g., Level 1 and Mezzanine side by side), use split_page. If it has both a \
plan and an embedded schedule table, classify as lighting_plan (schedule auto-detected).

When the user reports a COUNTING issue (fixture or keynote count wrong/missed/not properly counted):
- If the user provides a SPECIFIC corrected count (e.g., "B2 should be 25", "there are 3 not 5"):
  Return a count_override action so the system can reprocess:
  For fixtures: ```json
  {"actions": [{"action": "count_override", "fixture_code": "B2", "fixture_data": {"sheet": "E601-L1", "corrected": 25}, "reason": "manual_count_edit"}]}
  ```
  For keynotes: ```json
  {"actions": [{"action": "keynote_count_override", "fixture_code": "KN-3", "fixture_data": {"keynote_number": "3", "sheet": "E601-MEZ", "corrected": 5}, "reason": "manual_count_edit"}]}
  ```
- If the user just says something is wrong WITHOUT giving a specific count:
  Return a highlight instruction to show detected positions on the blueprint, AND a recount action:
  For fixtures: ```json
  {"highlight": {"fixture_code": "B2", "plan": "E601-L1"}, "recount": true}
  ```
  For keynotes: ```json
  {"highlight": {"keynote_number": "3", "plan": "E601-MEZ"}, "recount": true}
  ```
  Omit "plan" if user didn't specify — system shows first plan with count > 0
- Examples:
  - "B2 should be 25 on E601-L1" → count_override action with corrected=25
  - "keynote 5 count is 3 not 5" → keynote_count_override action with corrected=3
  - "B2 was not properly counted" → highlight with recount=true
  - "keynote 5 is wrong on E200" → highlight with recount=true

When the user wants a STRUCTURAL CORRECTION (page not processed, wrong type):
- Return a JSON block with structured actions. Wrap in ```json ... ```
- Use fixture_code = page number (e.g., "4") or sheet code (e.g., "E501")
- ALWAYS include fixture_data with page_type
- If the page has BOTH a plan AND embedded schedule table, classify as lighting_plan \
(the system auto-detects embedded schedule tables)
- If the page has MULTIPLE lighting viewports, use split_page action instead
- JSON examples:
  - "page 4 has a lighting plan":
    ```json
    {"actions": [{"action": "reclassify_page", "fixture_code": "4", "fixture_data": {"page_type": "lighting_plan"}, "reason": "other"}]}
    ```
  - "E501 has a schedule table":
    ```json
    {"actions": [{"action": "reclassify_page", "fixture_code": "E501", "fixture_data": {"page_type": "schedule"}, "reason": "other"}]}
    ```
  - "E601 has Level 1 and Mezzanine plans":
    ```json
    {"actions": [{"action": "split_page", "fixture_code": "E601", "fixture_data": {"viewports": [{"label": "L1"}, {"label": "MEZ"}]}, "reason": "other"}]}
    ```

When NO PLANS were found and the user identifies pages to process:
- Return multiple reclassify_page actions for all mentioned pages
- Use page numbers as fixture_code values (e.g., "3", "4")
- Ask which pages are plans and which are schedules if unclear

When the user asks a QUESTION, answer directly from the project data and context.

When the user wants a PARAMETER CHANGE, return a JSON block:
```json
{"param_changes": [{"key": "font_size_tolerance_multi", "value": 0.6, "scope": "project_id"}]}
```

For general conversation, respond naturally and helpfully.

IMPORTANT: Be concise. Contractors are busy. Get to the point quickly.

Available runtime parameters:
- font_size_tolerance_multi (float, 1.01-3.0, default 1.5)
- font_size_tolerance_single (float, 1.01-2.0, default 1.15)
- isolation_distance (float, 5-50, default 15pt)
- dedup_distance (float, 20-200, default 70pt)
- legend_col_x_frac (float, 0.5-1.0, default 0.85)
- title_block_frac (float, 0.5-1.0, default 0.80)
- schedule_render_dpi (int, 72-400, default 200)
- keynote_max_number (int, 5-99, default 20)
- max_plausible_keynote_count (int, 3-50, default 10)
- qa_confidence_threshold (float, 0.5-1.0, default 0.95)
- use_vision_counting (bool, default false)
- render_dpi (int, 72-600, default 300)

Reason values for corrections: missed_embedded_schedule, wrong_fixture_code, \
extra_fixture, missing_fixture, vlm_misread, wrong_bounding_box, manual_count_edit, other

Action types for corrections: count_override, keynote_count_override \
(use fixture_code="KN-{number}", fixture_data={keynote_number, sheet, corrected}), \
add, remove, update_spec (for spec fields like description, voltage, mounting, \
schedule_page, etc.), reclassify_page, split_page
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
    import anthropic

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

    # For simple questions that can be answered from data directly
    if intent == "question" and not config.anthropic_api_key:
        return ChatResponse(
            message=ChatMessage(
                role="assistant",
                content="I can see the project data but need an API key for detailed answers.",
                intent="question",
            )
        )

    if not config.anthropic_api_key:
        return ChatResponse(
            message=ChatMessage(
                role="assistant",
                content="API key not configured. Cannot process chat messages.",
                intent="general",
            )
        )

    # Call Claude
    client = anthropic.Anthropic(api_key=config.anthropic_api_key)

    messages = []
    # Add chat history for context
    for msg in chat_history[-6:]:
        messages.append({
            "role": msg["role"],
            "content": msg["content"],
        })
    # Detect page references — if the user mentions a page, render it
    # so the LLM can actually see what's on it.
    page_refs = _extract_page_references(user_text, project_data)
    image_blocks: list[dict] = []
    if page_refs and intent in ("correction", "general"):
        image_blocks = _render_referenced_pages(page_refs, max_pages=2, dpi=150)

    # Add current message — include page images if available
    if image_blocks:
        user_content: list[dict] = [
            {"type": "text", "text": f"Project context:\n{context}\n\nUser message:\n{user_text}"},
        ] + image_blocks
        messages.append({"role": "user", "content": user_content})
    else:
        messages.append({
            "role": "user",
            "content": f"Project context:\n{context}\n\nUser message:\n{user_text}",
        })

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=CHAT_SYSTEM_PROMPT,
            messages=messages,
        )

        # Extract text
        text = ""
        for block in response.content:
            if hasattr(block, "text"):
                text += block.text

        # Parse response for structured actions
        actions = None
        needs_confirmation = False
        param_changes = None
        highlight = None

        if "```json" in text:
            try:
                json_start = text.index("```json") + 7
                json_end = text.index("```", json_start)
                json_str = text[json_start:json_end].strip()
                parsed = json.loads(json_str)

                if "highlight" in parsed:
                    # Highlight instruction — show positions on PDF
                    highlight = parsed["highlight"]
                    intent = "correction"
                    # If LLM also set "recount": true, build a recount
                    # action so the frontend shows a confirm button.
                    if parsed.get("recount"):
                        code = (highlight.get("fixture_code")
                                or highlight.get("keynote_number") or "")
                        plan = highlight.get("plan") or ""
                        is_keynote = "keynote_number" in highlight
                        recount_target = frozenset({4, 5}) if is_keynote else frozenset({3, 5})
                        recount_label = f"keynote {code}" if is_keynote else f"fixture {code}"
                        actions = [FixItAction(
                            action="reprocess",
                            fixture_code=code,
                            reason="other",
                            reason_detail=f"Recount {recount_label}" + (f" on {plan}" if plan else ""),
                            fixture_data={"target": sorted(recount_target), "use_vision": True},
                        )]
                        needs_confirmation = True
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
            if highlight and actions:
                code = highlight.get("fixture_code") or highlight.get("keynote_number", "")
                plan = highlight.get("plan", "")
                plan_msg = f" on {plan}" if plan else ""
                display_text = (
                    f"Highlighting {code}{plan_msg} on the blueprint. "
                    "Review the markers, then confirm below to recount with vision."
                )
            elif highlight:
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
