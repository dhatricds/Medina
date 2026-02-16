"""Generate human-readable QA reports."""

from __future__ import annotations

import logging

from medina.models import QAReport

logger = logging.getLogger(__name__)


def format_qa_report(report: QAReport, project_name: str = "") -> str:
    """Generate a human-readable QA report string."""
    lines: list[str] = []
    sep = "=" * 55

    lines.append(sep)
    title = f"  MEDINA QA REPORT"
    if project_name:
        title += f" — {project_name}"
    lines.append(title)
    lines.append(sep)

    status = "PASSED" if report.passed else "FAILED"
    icon = "+" if report.passed else "X"
    lines.append(
        f"  Overall Confidence: {report.overall_confidence:.1%}  "
        f"[{icon}] {status} (threshold: {report.threshold:.0%})"
    )
    lines.append("")

    lines.append("  Stage Scores:")
    stage_labels = {
        "sheet_index": "Sheet Index Discovery",
        "schedule_extraction": "Schedule Extraction",
        "fixture_counting": "Fixture Counting",
        "keynote_extraction": "Keynote Extraction",
    }
    for key, label in stage_labels.items():
        score = report.stage_scores.get(key, 0.0)
        icon = "+" if score >= 0.95 else ("~" if score >= 0.80 else "X")
        lines.append(f"    {label:.<30s} {score:>6.1%}  [{icon}]")
    lines.append("")

    if report.warnings:
        lines.append("  Warnings:")
        for w in report.warnings:
            lines.append(f"    ! {w}")
        lines.append("")

    if report.recommendations:
        lines.append("  Recommendations:")
        for r in report.recommendations:
            lines.append(f"    - {r}")
        lines.append("")

    fixture_flags = [
        r for r in report.fixture_results if r.flags
    ]
    if fixture_flags:
        lines.append("  Flagged Fixtures:")
        for r in fixture_flags[:10]:
            flags_str = ", ".join(f.value for f in r.flags)
            lines.append(
                f"    {r.item_code}: {r.confidence:.0%} [{flags_str}]"
                f" — {r.notes}" if r.notes else ""
            )
        if len(fixture_flags) > 10:
            lines.append(f"    ... and {len(fixture_flags) - 10} more")
        lines.append("")

    lines.append(sep)
    return "\n".join(lines)
