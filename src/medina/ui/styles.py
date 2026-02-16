"""Custom CSS styles for the PlanScan UI."""

from __future__ import annotations

PLANSCAN_CSS = """
<style>
/* === Hide Streamlit defaults === */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header {visibility: hidden;}

/* === Dark navy sidebar === */
section[data-testid="stSidebar"] {
    background-color: #1A1A2E;
    color: #E0E0E0;
}
/* Force all text inside sidebar to light color */
section[data-testid="stSidebar"] .stMarkdown,
section[data-testid="stSidebar"] .stMarkdown p,
section[data-testid="stSidebar"] .stMarkdown h1,
section[data-testid="stSidebar"] .stMarkdown h2,
section[data-testid="stSidebar"] .stMarkdown h3,
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] span,
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] div {
    color: #E0E0E0 !important;
}
/* Radio button options (Streamlit 1.54+) */
section[data-testid="stSidebar"] [data-testid="stRadio"] label,
section[data-testid="stSidebar"] [data-testid="stRadio"] label span,
section[data-testid="stSidebar"] [data-testid="stRadio"] label p,
section[data-testid="stSidebar"] [data-testid="stRadio"] label div,
section[data-testid="stSidebar"] [data-testid="stRadio"] div[role="radiogroup"] label,
section[data-testid="stSidebar"] [role="radiogroup"] label {
    color: #E0E0E0 !important;
}
/* Checkbox labels */
section[data-testid="stSidebar"] [data-testid="stCheckbox"] label,
section[data-testid="stSidebar"] [data-testid="stCheckbox"] label span,
section[data-testid="stSidebar"] [data-testid="stCheckbox"] label p {
    color: #E0E0E0 !important;
}
/* Select box text */
section[data-testid="stSidebar"] [data-testid="stSelectbox"] label,
section[data-testid="stSidebar"] [data-testid="stSelectbox"] span,
section[data-testid="stSidebar"] [data-baseweb="select"] span {
    color: #E0E0E0 !important;
}
/* Slider labels */
section[data-testid="stSidebar"] [data-testid="stSlider"] label,
section[data-testid="stSidebar"] [data-testid="stSlider"] span {
    color: #E0E0E0 !important;
}
/* Text input labels */
section[data-testid="stSidebar"] [data-testid="stTextInput"] label,
section[data-testid="stSidebar"] [data-testid="stTextInput"] span {
    color: #E0E0E0 !important;
}
/* File uploader labels */
section[data-testid="stSidebar"] [data-testid="stFileUploader"] label,
section[data-testid="stSidebar"] [data-testid="stFileUploader"] span,
section[data-testid="stSidebar"] [data-testid="stFileUploader"] p {
    color: #E0E0E0 !important;
}
/* Info/warning boxes in sidebar */
section[data-testid="stSidebar"] [data-testid="stAlert"] p {
    color: inherit !important;
}
section[data-testid="stSidebar"] .stDivider,
section[data-testid="stSidebar"] hr {
    border-color: rgba(255, 255, 255, 0.15) !important;
}

/* === Metric cards === */
div[data-testid="stMetric"] {
    background-color: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 8px;
    padding: 16px 20px;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
}
div[data-testid="stMetric"] label {
    color: #64748B !important;
    font-size: 0.85rem !important;
    font-weight: 500 !important;
    text-transform: uppercase;
    letter-spacing: 0.03em;
}
div[data-testid="stMetric"] div[data-testid="stMetricValue"] {
    color: #1A1A2E !important;
    font-size: 2rem !important;
    font-weight: 700 !important;
}

/* === Confidence badge === */
.confidence-badge {
    display: inline-block;
    padding: 4px 14px;
    border-radius: 20px;
    font-weight: 600;
    font-size: 0.9rem;
    letter-spacing: 0.02em;
}
.confidence-green {
    background-color: #DCFCE7;
    color: #166534;
    border: 1px solid #BBF7D0;
}
.confidence-yellow {
    background-color: #FEF9C3;
    color: #854D0E;
    border: 1px solid #FDE68A;
}
.confidence-red {
    background-color: #FEE2E2;
    color: #991B1B;
    border: 1px solid #FECACA;
}

/* === Demo banner === */
.demo-banner {
    background: linear-gradient(135deg, #EFF6FF 0%, #DBEAFE 100%);
    border: 1px solid #93C5FD;
    border-radius: 8px;
    padding: 12px 20px;
    margin-bottom: 20px;
    color: #1E40AF;
    font-size: 0.9rem;
}

/* === Header area === */
.planscan-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 8px;
}
.planscan-title {
    font-size: 1.8rem;
    font-weight: 700;
    color: #1A1A2E;
    margin: 0;
}
.planscan-tagline {
    font-size: 1rem;
    color: #64748B;
    margin: 0;
}

/* === Progress steps === */
.progress-step {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 8px 0;
}
.step-number {
    width: 28px;
    height: 28px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 600;
    font-size: 0.85rem;
    flex-shrink: 0;
}
.step-done {
    background-color: #166534;
    color: white;
}
.step-active {
    background-color: #1B6AC9;
    color: white;
    animation: pulse 1.5s infinite;
}
.step-pending {
    background-color: #E2E8F0;
    color: #94A3B8;
}
.step-label {
    font-weight: 500;
    font-size: 0.95rem;
}
.step-label-done {
    color: #166534;
}
.step-label-active {
    color: #1B6AC9;
}
.step-label-pending {
    color: #94A3B8;
}

@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.6; }
}

/* === Tab styling === */
.stTabs [data-baseweb="tab-list"] {
    gap: 8px;
}
.stTabs [data-baseweb="tab"] {
    padding: 10px 20px;
    font-weight: 500;
}

/* === Download section === */
.download-section {
    background-color: #F8FAFC;
    border: 1px solid #E2E8F0;
    border-radius: 8px;
    padding: 20px;
    margin: 16px 0;
}

/* === Landing feature cards === */
.feature-card {
    background-color: #F8FAFC;
    border: 1px solid #E2E8F0;
    border-radius: 8px;
    padding: 20px;
    text-align: center;
    height: 100%;
}
.feature-card h4 {
    color: #1B6AC9;
    margin-bottom: 8px;
}
.feature-card p {
    color: #64748B;
    font-size: 0.9rem;
}
</style>
"""
