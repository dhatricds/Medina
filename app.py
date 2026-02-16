"""PlanScan — Lighting Fixture Takeoff from Electrical Construction Drawings."""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

import streamlit as st

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from medina.config import MedinaConfig
from medina.models import ExtractionResult
from medina.ui.styles import PLANSCAN_CSS
from medina.ui import language as L
from medina.ui.components import (
    render_confidence_badge,
    render_demo_banner,
    render_header,
    render_landing_page,
    render_progress,
    render_summary_metrics,
)
from medina.ui.demo import get_demo_project_names, load_demo_result

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Page Config ---
st.set_page_config(
    page_title=f"{L.APP_NAME} - {L.APP_TAGLINE}",
    page_icon=":zap:",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Inject custom CSS
st.markdown(PLANSCAN_CSS, unsafe_allow_html=True)

# --- Session State Init ---
if "result" not in st.session_state:
    st.session_state.result = None
if "feedback" not in st.session_state:
    st.session_state.feedback = []
if "processing" not in st.session_state:
    st.session_state.processing = False
if "progress_messages" not in st.session_state:
    st.session_state.progress_messages = []
if "is_demo" not in st.session_state:
    st.session_state.is_demo = False


# --- Helper Functions ---

def get_data_sources() -> list[Path]:
    """Get available data sources from the data/ folder."""
    data_dir = Path(__file__).parent / "data"
    sources: list[Path] = []
    if data_dir.exists():
        for item in sorted(data_dir.iterdir()):
            if item.is_dir():
                pdf_count = len(list(item.glob("*.pdf")))
                if pdf_count > 0:
                    sources.append(item)
            elif item.suffix.lower() == ".pdf":
                sources.append(item)
    return sources


def run_extraction(
    source: Path,
    use_vision: bool,
    qa_threshold: float,
    progress_placeholder,
) -> ExtractionResult:
    """Run the pipeline and return results with progress updates."""
    from medina.pipeline import run_pipeline

    config = MedinaConfig()
    config.qa_confidence_threshold = qa_threshold
    config.use_vision_counting = use_vision

    current_step = {"value": -1}

    def progress_cb(stage: str, msg: str) -> None:
        step_idx = L.STAGE_TO_STEP.get(stage, current_step["value"])
        if step_idx > current_step["value"]:
            current_step["value"] = step_idx
        st.session_state.progress_messages.append(f"[{stage}] {msg}")
        with progress_placeholder.container():
            render_progress(current_step["value"])
            st.caption(msg)

    return run_pipeline(
        source=source,
        config=config,
        use_vision=use_vision,
        progress_callback=progress_cb,
    )


# --- Sidebar ---

def render_sidebar() -> tuple[Path | None, bool, float, str]:
    """Render the sidebar. Returns (source, use_vision, qa_threshold, input_mode)."""
    st.sidebar.markdown(
        f"### {L.SIDEBAR_TITLE}\n**{L.SIDEBAR_SUBTITLE}**"
    )
    st.sidebar.divider()

    # Input mode selection
    input_mode = st.sidebar.radio(
        L.SIDEBAR_HOW_TO_USE,
        [L.INPUT_DEMO, L.INPUT_UPLOAD, L.INPUT_LIBRARY],
        captions=[
            "See sample results instantly",
            "Upload your own PDF file",
            "Pick from data/ folder",
        ],
    )

    source: Path | None = None

    if input_mode == L.INPUT_DEMO:
        demo_names = get_demo_project_names()
        if demo_names:
            selected_demo = st.sidebar.selectbox(
                "Select demo project:",
                demo_names,
            )
            if selected_demo:
                # Store demo selection in session state for main area
                st.session_state._demo_selection = selected_demo
        else:
            st.sidebar.warning("No demo data available")

    elif input_mode == L.INPUT_UPLOAD:
        uploaded = st.sidebar.file_uploader(
            "Upload PDF", type=["pdf"], accept_multiple_files=False,
        )
        if uploaded:
            tmp_dir = Path(tempfile.mkdtemp())
            tmp_path = tmp_dir / uploaded.name
            tmp_path.write_bytes(uploaded.read())
            source = tmp_path

    elif input_mode == L.INPUT_LIBRARY:
        sources = get_data_sources()
        if sources:
            source_names = [s.name for s in sources]
            selected = st.sidebar.selectbox(
                "Select project:",
                source_names,
            )
            if selected:
                idx = source_names.index(selected)
                source = sources[idx]
                if source.is_dir():
                    pdf_count = len(list(source.glob("*.pdf")))
                    st.sidebar.info(f"Folder with {pdf_count} PDFs")
                else:
                    st.sidebar.info("Single PDF file")
        else:
            st.sidebar.warning("No data found in data/ folder")

    st.sidebar.divider()

    # Settings
    st.sidebar.markdown(f"**{L.SIDEBAR_SETTINGS}**")

    # API key
    has_api_key = bool(os.environ.get("MEDINA_ANTHROPIC_API_KEY", ""))
    api_key_input = st.sidebar.text_input(
        L.SETTING_API_KEY,
        type="password",
        value=os.environ.get("MEDINA_ANTHROPIC_API_KEY", ""),
        help=L.SETTING_API_KEY_HELP,
    )
    if api_key_input:
        os.environ["MEDINA_ANTHROPIC_API_KEY"] = api_key_input
        has_api_key = True

    use_vision = st.sidebar.checkbox(
        L.SETTING_ENHANCED_SCAN,
        value=False,
        disabled=not has_api_key,
        help=(
            L.SETTING_ENHANCED_HELP if has_api_key
            else L.SETTING_ENHANCED_DISABLED
        ),
    )

    qa_threshold = st.sidebar.slider(
        L.SETTING_QUALITY_THRESHOLD,
        min_value=0.50,
        max_value=1.00,
        value=0.95,
        step=0.05,
        help=L.SETTING_QUALITY_HELP,
    )

    return source, use_vision, qa_threshold, input_mode


# --- Results Display ---

def render_fixtures(result: ExtractionResult) -> None:
    """Display the fixture schedule table."""
    if not result.fixtures:
        st.warning("No fixtures extracted")
        return

    rows = []
    for f in result.fixtures:
        row = {
            "Type": f.code,
            "Style": f.fixture_style or f.description[:40],
            "Voltage": f.voltage,
            "Mounting": f.mounting,
            "Lumens": f.lumens,
            "CCT": f.cct,
            "Dimming": f.dimming,
            "Max VA": f.max_va,
        }
        for plan_code in result.plan_pages:
            row[plan_code] = f.counts_per_plan.get(plan_code, 0)
        row["Total"] = f.total
        rows.append(row)

    st.dataframe(rows, use_container_width=True, hide_index=True)


def render_keynotes(result: ExtractionResult) -> None:
    """Display the keynotes inventory."""
    if not result.keynotes:
        st.info("No keynotes found")
        return

    rows = []
    for kn in result.keynotes:
        row = {
            "Note #": str(kn.number),
            "Text": kn.text,
        }
        for plan_code in result.plan_pages:
            row[plan_code] = kn.counts_per_plan.get(plan_code, 0)
        row["Total"] = kn.total
        rows.append(row)

    st.dataframe(rows, use_container_width=True, hide_index=True)


def render_drawing_index(result: ExtractionResult) -> None:
    """Display the discovered drawing index."""
    if not result.sheet_index:
        st.warning("No drawing index discovered")
        return

    rows = []
    for entry in result.sheet_index:
        ptype = entry.inferred_type.value if entry.inferred_type else "unknown"
        rows.append({
            "Sheet Code": entry.sheet_code,
            "Description": entry.description,
            "Type": ptype,
        })
    st.dataframe(rows, use_container_width=True, hide_index=True)


def render_quality_check(result: ExtractionResult) -> None:
    """Display the QA report with confidence scores."""
    if not result.qa_report:
        st.warning("No quality check data available")
        return

    qa = result.qa_report

    # Overall status
    col1, col2, col3 = st.columns(3)
    with col1:
        status = "PASSED" if qa.passed else "FAILED"
        color = "green" if qa.passed else "red"
        st.markdown(f"### :{color}[{status}]")
    with col2:
        st.metric("Overall Confidence", f"{qa.overall_confidence:.1%}")
    with col3:
        st.metric("Threshold", f"{qa.threshold:.0%}")

    # Stage scores
    st.markdown("**Stage Scores:**")
    cols = st.columns(len(L.QA_STAGE_LABELS))
    for i, (key, label) in enumerate(L.QA_STAGE_LABELS.items()):
        score = qa.stage_scores.get(key, 0.0)
        with cols[i]:
            st.metric(label, f"{score:.1%}")

    # Warnings
    if qa.warnings:
        st.markdown("**Warnings:**")
        for w in qa.warnings:
            st.warning(w)

    # Recommendations
    if qa.recommendations:
        st.markdown("**Recommendations:**")
        for r in qa.recommendations:
            st.info(r)


def render_download_section(result: ExtractionResult) -> None:
    """Render download buttons for output files."""
    st.markdown(f"#### {L.SECTION_DOWNLOAD}")

    col1, col2 = st.columns(2)

    with col1:
        from medina.output.excel import write_excel
        tmp_xlsx = Path(tempfile.mktemp(suffix=".xlsx"))
        write_excel(result, tmp_xlsx)
        xlsx_bytes = tmp_xlsx.read_bytes()
        tmp_xlsx.unlink(missing_ok=True)

        st.download_button(
            label=L.BTN_DOWNLOAD_EXCEL,
            data=xlsx_bytes,
            file_name=f"{result.source}_takeoff.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
        )

    with col2:
        from medina.output.json_out import build_json_output
        json_data = build_json_output(result)
        json_str = json.dumps(json_data, indent=2, ensure_ascii=False)

        st.download_button(
            label=L.BTN_DOWNLOAD_JSON,
            data=json_str,
            file_name=f"{result.source}_takeoff.json",
            mime="application/json",
        )


def render_feedback_section(result: ExtractionResult) -> None:
    """Render the feedback/issue reporting section."""
    st.divider()
    st.markdown(f"#### {L.FEEDBACK_TITLE}")
    st.markdown(L.FEEDBACK_DESCRIPTION)

    col_type, col_severity = st.columns(2)
    with col_type:
        feedback_type = st.selectbox("Issue type:", L.FEEDBACK_TYPES)
    with col_severity:
        severity = st.selectbox("Severity:", L.FEEDBACK_SEVERITY)

    # Fixture-specific fields
    selected_fixture = None
    affected_plan = None
    correct_count = None
    if feedback_type in (
        "Fixture count incorrect",
        "Missing fixture type",
        "Wrong fixture specs",
    ):
        fixture_codes = [f.code for f in result.fixtures] + ["(new fixture)"]
        selected_fixture = st.selectbox("Which fixture?", fixture_codes)

        if feedback_type == "Fixture count incorrect":
            col1, col2 = st.columns(2)
            with col1:
                plan_options = result.plan_pages + ["All plans"]
                affected_plan = st.selectbox("On which plan?", plan_options)
            with col2:
                correct_count = st.number_input(
                    "Correct count:", min_value=0, value=0,
                )

    # Optional contact
    contact = st.text_input(
        "Your name / company (optional, for follow-up):",
        placeholder="e.g., John Smith, ABC Electric",
    )

    details = st.text_area(
        "Additional details:",
        placeholder="Describe what's wrong and what the correct value should be...",
    )

    if st.button("Submit Issue", type="primary"):
        feedback_entry = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "type": feedback_type,
            "severity": severity,
            "details": details,
            "contact": contact,
            "source": result.source,
        }
        if selected_fixture:
            feedback_entry["fixture_code"] = selected_fixture
        if affected_plan:
            feedback_entry["affected_plan"] = affected_plan
        if correct_count is not None:
            feedback_entry["correct_count"] = correct_count

        st.session_state.feedback.append(feedback_entry)

        # Save to file
        feedback_dir = Path(__file__).parent / "output" / "feedback"
        feedback_dir.mkdir(parents=True, exist_ok=True)
        feedback_file = feedback_dir / f"feedback_{result.source}.json"

        existing = []
        if feedback_file.exists():
            existing = json.loads(feedback_file.read_text())
        existing.append(feedback_entry)
        feedback_file.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False)
        )

        st.success(L.FEEDBACK_SUCCESS)


# --- Main App ---

def main() -> None:
    """Main PlanScan application."""
    source, use_vision, qa_threshold, input_mode = render_sidebar()

    # --- Demo mode ---
    if input_mode == L.INPUT_DEMO:
        demo_selection = getattr(st.session_state, "_demo_selection", None)
        if demo_selection:
            result = load_demo_result(demo_selection)
            if result:
                st.session_state.result = result
                st.session_state.is_demo = True
            else:
                render_header()
                st.error("Could not load demo data.")
                return
        else:
            render_header()
            render_landing_page()
            return

    # --- Upload / Library mode ---
    elif input_mode in (L.INPUT_UPLOAD, L.INPUT_LIBRARY):
        if source is None:
            render_header()
            render_landing_page()
            return

        # Start Takeoff button
        if st.sidebar.button(
            L.BTN_START_TAKEOFF,
            type="primary",
            use_container_width=True,
        ):
            st.session_state.progress_messages = []
            st.session_state.result = None
            st.session_state.is_demo = False

            progress_placeholder = st.empty()
            with progress_placeholder.container():
                render_progress(0)

            try:
                result = run_extraction(
                    source, use_vision, qa_threshold, progress_placeholder,
                )
                st.session_state.result = result
                progress_placeholder.empty()
            except Exception as e:
                progress_placeholder.empty()
                st.error(f"Processing failed: {e}")
                logger.exception("Pipeline failed")
                return

    # --- Display results ---
    result = st.session_state.result
    if result is None:
        render_header()
        render_landing_page()
        return

    # Header with project name and confidence
    confidence = None
    if result.qa_report:
        confidence = result.qa_report.overall_confidence
    render_header(project_name=result.source, confidence=confidence)

    # Demo banner
    if st.session_state.is_demo:
        render_demo_banner()

    # Summary metrics
    render_summary_metrics(result)

    st.markdown("")

    # Tabs
    tab1, tab2, tab3, tab4 = st.tabs([
        L.TAB_FIXTURES,
        L.TAB_KEYNOTES,
        L.TAB_DRAWING_INDEX,
        L.TAB_QC,
    ])

    with tab1:
        render_fixtures(result)
    with tab2:
        render_keynotes(result)
    with tab3:
        render_drawing_index(result)
    with tab4:
        render_quality_check(result)

    # Download section
    st.divider()
    render_download_section(result)

    # Feedback section
    render_feedback_section(result)

    # Processing log (collapsed)
    if st.session_state.progress_messages:
        with st.expander("Processing Log", expanded=False):
            for msg in st.session_state.progress_messages:
                st.text(msg)


if __name__ == "__main__":
    main()
