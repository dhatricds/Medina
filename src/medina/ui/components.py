"""Reusable UI components for the PlanScan interface."""

from __future__ import annotations

import streamlit as st

from medina.ui.language import (
    APP_NAME,
    APP_TAGLINE,
    DEMO_BANNER,
    LANDING_FEATURES,
    LANDING_HEADLINE,
    METRIC_FIXTURE_TYPES,
    METRIC_KEY_NOTES,
    METRIC_LIGHTING_PLANS,
    METRIC_TOTAL_FIXTURES,
    PROGRESS_STEPS,
    QA_NEEDS_REVIEW,
    QA_REVIEW,
    QA_VERIFIED,
)
from medina.models import ExtractionResult


def render_header(
    project_name: str | None = None,
    confidence: float | None = None,
) -> None:
    """Render the PlanScan header with optional project name and confidence badge."""
    cols = st.columns([3, 1]) if confidence is not None else [st.container()]

    with cols[0]:
        if project_name:
            st.markdown(
                f'<p class="planscan-title">{APP_NAME}</p>'
                f'<p class="planscan-tagline">Project: {project_name}</p>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<p class="planscan-title">{APP_NAME}</p>'
                f'<p class="planscan-tagline">{APP_TAGLINE}</p>',
                unsafe_allow_html=True,
            )

    if confidence is not None:
        with cols[1]:
            render_confidence_badge(confidence)


def render_confidence_badge(confidence: float) -> None:
    """Render a colored confidence badge."""
    pct = f"{confidence:.0%}"
    if confidence >= 0.95:
        css_class = "confidence-green"
        label = QA_VERIFIED
    elif confidence >= 0.80:
        css_class = "confidence-yellow"
        label = QA_REVIEW
    else:
        css_class = "confidence-red"
        label = QA_NEEDS_REVIEW

    st.markdown(
        f'<div style="text-align: right; padding-top: 12px;">'
        f'<span class="confidence-badge {css_class}">{pct} {label}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )


def render_demo_banner() -> None:
    """Render the demo mode banner."""
    st.markdown(
        f'<div class="demo-banner">{DEMO_BANNER}</div>',
        unsafe_allow_html=True,
    )


def render_summary_metrics(result: ExtractionResult) -> None:
    """Render the 4 summary metric cards."""
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric(METRIC_FIXTURE_TYPES, len(result.fixtures))
    with c2:
        total = sum(f.total for f in result.fixtures)
        st.metric(METRIC_TOTAL_FIXTURES, total)
    with c3:
        st.metric(METRIC_LIGHTING_PLANS, len(result.plan_pages))
    with c4:
        st.metric(METRIC_KEY_NOTES, len(result.keynotes))


def render_landing_page() -> None:
    """Render the landing page when no data is loaded."""
    st.markdown("")
    st.markdown(f"#### {LANDING_HEADLINE}")
    st.markdown("")

    st.markdown("**What you get:**")
    cols = st.columns(len(LANDING_FEATURES))
    for i, (title, desc) in enumerate(LANDING_FEATURES):
        with cols[i]:
            st.markdown(
                f'<div class="feature-card">'
                f"<h4>{title}</h4>"
                f"<p>{desc}</p>"
                f"</div>",
                unsafe_allow_html=True,
            )


def render_progress(current_step: int) -> None:
    """Render the 5-step progress display.

    Args:
        current_step: 0-indexed step that is currently active.
            Steps < current_step are done, steps > are pending.
    """
    for i, (label, _detail) in enumerate(PROGRESS_STEPS):
        if i < current_step:
            num_class = "step-done"
            label_class = "step-label-done"
            icon = "&#10003;"  # checkmark
        elif i == current_step:
            num_class = "step-active"
            label_class = "step-label-active"
            icon = str(i + 1)
        else:
            num_class = "step-pending"
            label_class = "step-label-pending"
            icon = str(i + 1)

        st.markdown(
            f'<div class="progress-step">'
            f'<div class="step-number {num_class}">{icon}</div>'
            f'<span class="step-label {label_class}">{label}</span>'
            f"</div>",
            unsafe_allow_html=True,
        )
