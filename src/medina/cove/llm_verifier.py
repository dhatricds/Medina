"""LLM-powered deep verification for flagged agent outputs.

Called only when rule-based ``verifier.py`` confidence drops below 0.7,
indicating that the agent's output has structural problems that need
semantic analysis to resolve (e.g., is this really a panel schedule
misread, or are the fixture codes valid but unconventional?).

Uses Claude Sonnet for focused, low-cost analysis of the specific
flagged issues — NOT a full re-run of the agent.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from medina.cove.verifier import CoveResult, SEVERITY_WARNING, SEVERITY_ERROR

logger = logging.getLogger(__name__)

# The verification model — Sonnet for speed and cost efficiency.
_VERIFY_MODEL = "claude-sonnet-4-20250514"

# Maximum tokens for the verification response.
_MAX_TOKENS = 2048


# ═══════════════════════════════════════════════════════════════════════════
#  Prompt templates
# ═══════════════════════════════════════════════════════════════════════════

_SYSTEM_PROMPT = """\
You are a verification expert for an electrical construction drawing \
analysis pipeline.  You review the output of pipeline agents that extract \
fixture schedules, count lighting fixtures, and parse keynotes from \
electrical PDFs.

Your job is to analyze flagged issues from a rule-based verifier and \
determine:
1. Whether each issue is a real problem or a false alarm.
2. Whether the agent should be retried with corrections.
3. What specific corrections should be applied.

Respond with valid JSON only.  No markdown fences, no explanation outside \
the JSON.\
"""

_USER_PROMPT_TEMPLATE = """\
## Agent: {agent_name}

## Source: {source_path}

## Agent Output (summary)
```json
{agent_output_summary}
```

## Flagged Issues from Rule-Based Verifier
```json
{issues_json}
```

## Task
Analyze each flagged issue and respond with the following JSON structure:

{{
  "overall_assessment": "pass" | "retry" | "fail",
  "confidence": <float 0.0-1.0>,
  "reasoning": "<brief explanation>",
  "issue_verdicts": [
    {{
      "check": "<issue check name>",
      "verdict": "real_problem" | "false_alarm" | "needs_investigation",
      "explanation": "<why>",
      "correction": {{
        "action": "<action type or null>",
        "target": "<target code/page or null>",
        "detail": "<specifics>"
      }} | null
    }}
  ],
  "retry_recommended": <boolean>,
  "corrections_to_apply": [
    {{
      "action": "<action type>",
      "target": "<target>",
      "detail": "<specifics>",
      "data": {{}} | null
    }}
  ]
}}

Rules:
- "pass": The output is acceptable despite the flagged issues.
- "retry": The agent should be re-run with the suggested corrections.
- "fail": The output has fundamental problems that corrections cannot fix.
- Only recommend retry when you are confident it would produce better \
results.
- For fixture code issues, consider that real codes can be 1-6 chars, \
alphanumeric, and may include dots or hyphens (e.g., "A1", "WL1E", \
"G18", "AL1").
- For count issues, remember that single-character codes often match \
room labels and circuit identifiers, producing inflated counts.
- Keynotes are typically numbered 1-20, with diamond or hexagon shapes.\
"""


# ═══════════════════════════════════════════════════════════════════════════
#  Main entry point
# ═══════════════════════════════════════════════════════════════════════════

async def llm_verify(
    agent_name: str,
    agent_output: dict,
    issues: list[dict],
    source_path: str,
    project_id: str = "",
) -> CoveResult:
    """Run LLM-powered deep verification on a flagged agent output.

    Args:
        agent_name: Name of the agent whose output is being verified
            (e.g., "search", "schedule", "count", "keynote").
        agent_output: The agent's full output dict.
        issues: List of issue dicts from the rule-based verifier.
        source_path: Path to the source PDF (for context).
        project_id: Optional project ID for persistence.

    Returns:
        A CoveResult with the LLM's assessment merged in.
    """
    from medina.config import get_config

    config = get_config()
    if not config.anthropic_api_key:
        logger.warning(
            "COVE LLM verification skipped — no API key configured."
        )
        return CoveResult(
            passed=False,
            confidence=0.0,
            issues=issues,
            reasoning=(
                f"LLM verification skipped for {agent_name}: no API key."
            ),
        )

    # Build a compact summary of the agent output to stay within token limits.
    output_summary = _summarize_agent_output(agent_name, agent_output)

    prompt = _USER_PROMPT_TEMPLATE.format(
        agent_name=agent_name,
        source_path=source_path,
        agent_output_summary=json.dumps(output_summary, indent=2),
        issues_json=json.dumps(issues, indent=2),
    )

    try:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key)
        response = await client.messages.create(
            model=_VERIFY_MODEL,
            max_tokens=_MAX_TOKENS,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        response_text = response.content[0].text.strip()
        llm_result = _parse_llm_response(response_text)

    except Exception as exc:
        logger.warning(
            "COVE LLM verification failed for %s: %s", agent_name, exc,
        )
        return CoveResult(
            passed=False,
            confidence=0.3,
            issues=issues,
            reasoning=(
                f"LLM verification failed for {agent_name}: {exc}"
            ),
        )

    # --- Build CoveResult from LLM response ---
    result = _build_cove_result(llm_result, issues, agent_name)

    # --- Persist ---
    if project_id:
        result._persist(project_id, agent_name)

    logger.info(
        "COVE LLM [%s]: assessment=%s confidence=%.2f retry=%s "
        "corrections=%d",
        agent_name,
        llm_result.get("overall_assessment", "unknown"),
        result.confidence,
        llm_result.get("retry_recommended", False),
        len(result.corrections),
    )

    return result


# ═══════════════════════════════════════════════════════════════════════════
#  Internal helpers
# ═══════════════════════════════════════════════════════════════════════════

def _summarize_agent_output(
    agent_name: str,
    agent_output: dict,
) -> dict[str, Any]:
    """Create a compact summary of agent output for the LLM prompt.

    Avoids sending huge position data or full page lists — just the
    key fields the LLM needs to assess quality.
    """
    if agent_name == "search":
        pages = agent_output.get("pages", [])
        return {
            "total_pages": len(pages),
            "sheet_index_count": len(agent_output.get("sheet_index", [])),
            "plan_codes": agent_output.get("plan_codes", []),
            "schedule_codes": agent_output.get("schedule_codes", []),
            "page_types": _count_by_key(pages, "page_type"),
            "pages_sample": [
                {
                    "page_number": p.get("page_number"),
                    "sheet_code": p.get("sheet_code"),
                    "page_type": p.get("page_type"),
                    "sheet_title": p.get("sheet_title"),
                }
                for p in pages[:20]  # Cap to first 20 pages
            ],
        }

    if agent_name == "schedule":
        fixtures = agent_output.get("fixtures", [])
        return {
            "fixture_count": len(fixtures),
            "fixture_codes": agent_output.get("fixture_codes", []),
            "fixtures": [
                {
                    "code": f.get("code"),
                    "description": (f.get("description") or "")[:80],
                    "voltage": f.get("voltage"),
                    "mounting": f.get("mounting"),
                }
                for f in fixtures
            ],
        }

    if agent_name == "count":
        all_plan_counts = agent_output.get("all_plan_counts", {})
        return {
            "plans_counted": list(all_plan_counts.keys()),
            "counts": {
                plan: {
                    code: count
                    for code, count in sorted(counts.items())
                    if count > 0
                }
                for plan, counts in all_plan_counts.items()
            },
        }

    if agent_name == "keynote":
        keynotes = agent_output.get("keynotes", [])
        return {
            "keynote_count": len(keynotes),
            "keynotes": [
                {
                    "number": kn.get("number"),
                    "text": (kn.get("text") or "")[:100],
                    "counts_per_plan": kn.get("counts_per_plan", {}),
                    "total": kn.get("total", 0),
                }
                for kn in keynotes
            ],
        }

    # Fallback: return the whole thing (truncated keys)
    return {k: v for k, v in list(agent_output.items())[:10]}


def _count_by_key(items: list[dict], key: str) -> dict[str, int]:
    """Count occurrences of each value for a given key."""
    counts: dict[str, int] = {}
    for item in items:
        val = str(item.get(key, "unknown"))
        counts[val] = counts.get(val, 0) + 1
    return counts


def _parse_llm_response(text: str) -> dict[str, Any]:
    """Parse the LLM's JSON response, handling common formatting issues."""
    # Strip markdown fences if the model included them despite instructions.
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # Remove opening fence (with optional language tag)
        first_newline = cleaned.index("\n") if "\n" in cleaned else 3
        cleaned = cleaned[first_newline + 1:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse LLM verification response: %s", exc)
        return {
            "overall_assessment": "fail",
            "confidence": 0.3,
            "reasoning": f"Could not parse LLM response: {text[:200]}",
            "issue_verdicts": [],
            "retry_recommended": False,
            "corrections_to_apply": [],
        }


def _build_cove_result(
    llm_result: dict,
    original_issues: list[dict],
    agent_name: str,
) -> CoveResult:
    """Convert the LLM's JSON assessment into a CoveResult."""
    assessment = llm_result.get("overall_assessment", "fail")
    confidence = float(llm_result.get("confidence", 0.5))
    reasoning = llm_result.get("reasoning", "")
    retry = llm_result.get("retry_recommended", False)

    passed = assessment in ("pass",)
    # If the LLM says "retry", we still mark as not passed — the caller
    # should retry the agent and then re-verify.
    if assessment == "retry":
        passed = False

    result = CoveResult(
        passed=passed,
        confidence=max(0.0, min(1.0, confidence)),
        reasoning=f"LLM verification ({agent_name}): {reasoning}",
    )

    # --- Merge issue verdicts ---
    verdicts = llm_result.get("issue_verdicts", [])
    verdict_map = {v.get("check", ""): v for v in verdicts}

    for issue in original_issues:
        check = issue.get("check", "")
        verdict = verdict_map.get(check)
        if verdict:
            v_type = verdict.get("verdict", "needs_investigation")
            if v_type == "false_alarm":
                # Downgrade to info — not a real problem
                result.issues.append({
                    **issue,
                    "severity": "info",
                    "llm_verdict": "false_alarm",
                    "llm_explanation": verdict.get("explanation", ""),
                })
            elif v_type == "real_problem":
                result.issues.append({
                    **issue,
                    "llm_verdict": "real_problem",
                    "llm_explanation": verdict.get("explanation", ""),
                })
                # Add the LLM's suggested correction if present
                correction = verdict.get("correction")
                if correction and correction.get("action"):
                    result.corrections.append(correction)
            else:
                result.issues.append({
                    **issue,
                    "llm_verdict": "needs_investigation",
                    "llm_explanation": verdict.get("explanation", ""),
                })
        else:
            # Issue not addressed by LLM — keep as-is
            result.issues.append(issue)

    # --- Add LLM-suggested corrections ---
    for corr in llm_result.get("corrections_to_apply", []):
        if corr.get("action"):
            # Avoid duplicates from verdict-level corrections
            already_added = any(
                c.get("action") == corr["action"]
                and c.get("target") == corr.get("target")
                for c in result.corrections
            )
            if not already_added:
                result.corrections.append(corr)

    return result
