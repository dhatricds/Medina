"""Click CLI entry point for Medina."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click

from medina.config import get_config


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.option("--debug", is_flag=True, help="Debug logging")
def main(verbose: bool, debug: bool) -> None:
    """Medina: Lighting Fixture Inventory Extraction."""
    level = logging.DEBUG if debug else (
        logging.INFO if verbose else logging.WARNING
    )
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


@main.command()
@click.argument("source", type=click.Path(exists=True))
@click.option(
    "-o", "--output", "output_path",
    default="output/inventory",
    help="Output file path (without extension)",
)
@click.option(
    "--format", "output_format",
    type=click.Choice(["excel", "json", "both"]),
    default="both",
    help="Output format",
)
@click.option(
    "--use-vision", is_flag=True,
    help="Use Claude Vision API for counting",
)
@click.option(
    "--qa-threshold", type=float, default=None,
    help="Override QA confidence threshold (0.0-1.0)",
)
def process(
    source: str,
    output_path: str,
    output_format: str,
    use_vision: bool,
    qa_threshold: float | None,
) -> None:
    """Process a PDF or folder to extract lighting fixture inventory."""
    config = get_config()
    if qa_threshold is not None:
        config.qa_confidence_threshold = qa_threshold

    from medina.pipeline import run_and_save

    click.echo(f"Processing: {source}")
    result = run_and_save(
        source=source,
        output_path=output_path,
        output_format=output_format,
        config=config,
        use_vision=use_vision,
    )

    click.echo(f"\nExtracted {len(result.fixtures)} fixture types")
    click.echo(
        f"Found {len(result.plan_pages)} lighting plans: "
        f"{', '.join(result.plan_pages)}"
    )
    if result.qa_report:
        status = "PASSED" if result.qa_report.passed else "FAILED"
        click.echo(
            f"QA: {result.qa_report.overall_confidence:.1%} — {status}"
        )
        if not result.qa_report.passed:
            sys.exit(1)


@main.command()
@click.argument("source", type=click.Path(exists=True))
def classify(source: str) -> None:
    """Classify pages in a PDF or folder (diagnostic)."""
    from medina.pdf.loader import load
    from medina.pdf.sheet_index import discover_sheet_index
    from medina.pdf.classifier import classify_pages

    pages, pdf_pages = load(source)
    sheet_index = discover_sheet_index(pages, pdf_pages)
    pages = classify_pages(pages, pdf_pages, sheet_index)

    click.echo(f"\nSheet Index ({len(sheet_index)} entries):")
    for entry in sheet_index:
        t = entry.inferred_type.value if entry.inferred_type else "?"
        click.echo(f"  {entry.sheet_code:.<12s} {entry.description} [{t}]")

    click.echo(f"\nPage Classification ({len(pages)} pages):")
    for p in pages:
        code = p.sheet_code or f"page-{p.page_number}"
        click.echo(f"  {code:.<12s} {p.page_type.value}")


@main.command()
@click.argument("source", type=click.Path(exists=True))
@click.option(
    "-o", "--output", "output_path",
    default="output/inventory",
    help="Output file path (without extension)",
)
@click.option(
    "--use-vision", is_flag=True,
    help="Use Claude Vision API for counting",
)
@click.option(
    "--work-dir", default=None,
    help="Working directory for intermediate files",
)
def team(
    source: str,
    output_path: str,
    use_vision: bool,
    work_dir: str | None,
) -> None:
    """Run the Expert Contractor Agent Team workflow."""
    from medina.team.orchestrator import run_team

    result = run_team(source, output_path, use_vision, work_dir)
    if not result["qa_passed"]:
        sys.exit(1)


@main.command()
@click.argument("source", type=click.Path(exists=True))
def schedule(source: str) -> None:
    """Extract schedule tables only (diagnostic)."""
    from medina.pdf.loader import load
    from medina.pdf.sheet_index import discover_sheet_index
    from medina.pdf.classifier import classify_pages
    from medina.schedule.parser import parse_all_schedules
    from medina.models import PageType

    pages, pdf_pages = load(source)
    sheet_index = discover_sheet_index(pages, pdf_pages)
    pages = classify_pages(pages, pdf_pages, sheet_index)

    sched_pages = [p for p in pages if p.page_type == PageType.SCHEDULE]
    fixtures = parse_all_schedules(sched_pages, pdf_pages)

    click.echo(f"\nSchedule pages: {[p.sheet_code for p in sched_pages]}")
    click.echo(f"Fixtures extracted: {len(fixtures)}\n")
    for f in fixtures:
        click.echo(
            f"  {f.code:.<6s} {f.description[:50]:<50s} "
            f"{f.voltage:<10s} {f.mounting}"
        )


if __name__ == "__main__":
    main()
