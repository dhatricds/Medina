"""Contractor-friendly terminology for the PlanScan UI."""

from __future__ import annotations

# App branding
APP_NAME = "PlanScan"
APP_TAGLINE = "Lighting Fixture Takeoff"
APP_DESCRIPTION = "Automated lighting fixture counts from your electrical drawings"

# Sidebar labels
SIDEBAR_TITLE = "PlanScan"
SIDEBAR_SUBTITLE = "Lighting Fixture Takeoff"
SIDEBAR_HOW_TO_USE = "How to Use"
SIDEBAR_SETTINGS = "Settings"

# Input modes
INPUT_DEMO = "Try a Demo"
INPUT_UPLOAD = "Upload PDF"
INPUT_LIBRARY = "Select from Library"

# Settings
SETTING_ENHANCED_SCAN = "Enhanced scanning (uses AI vision)"
SETTING_ENHANCED_HELP = (
    "Uses AI vision to identify fixture symbols on plan pages. "
    "More accurate for complex drawings. Requires API key."
)
SETTING_ENHANCED_DISABLED = "Enter API key above to enable enhanced scanning."
SETTING_QUALITY_THRESHOLD = "Quality threshold"
SETTING_QUALITY_HELP = "Minimum confidence score to pass quality check"
SETTING_API_KEY = "API Key (for enhanced scanning)"
SETTING_API_KEY_HELP = "Required for enhanced scanning. Set once and it persists."

# Action buttons
BTN_START_TAKEOFF = "Start Takeoff"
BTN_DOWNLOAD_EXCEL = "Download Excel"
BTN_DOWNLOAD_JSON = "Download JSON"

# Progress steps
PROGRESS_STEPS = [
    ("Opening Drawings", "Loading and preparing your PDF pages..."),
    ("Finding Drawing Index", "Locating the sheet index and classifying pages..."),
    ("Reading Fixture Schedule", "Extracting fixture types and specifications..."),
    ("Counting Fixtures on Plans", "Scanning each lighting plan for fixture counts..."),
    ("Quality Check", "Verifying results and computing confidence scores..."),
]

# Map pipeline stages to step indices
STAGE_TO_STEP = {
    "LOAD": 0,
    "DISCOVER": 1,
    "CLASSIFY": 1,
    "SCHEDULE": 2,
    "COUNT": 3,
    "QA": 4,
    "DONE": 4,
}

# Tab labels
TAB_FIXTURES = "Fixture Schedule"
TAB_KEYNOTES = "Key Notes"
TAB_DRAWING_INDEX = "Drawing Index"
TAB_QC = "Quality Check"

# Section headers
SECTION_SUMMARY = "Takeoff Summary"
SECTION_DOWNLOAD = "Download Your Takeoff"
SECTION_FEEDBACK = "Report an Issue"

# Metric labels
METRIC_FIXTURE_TYPES = "Fixture Types"
METRIC_TOTAL_FIXTURES = "Total Fixtures"
METRIC_LIGHTING_PLANS = "Lighting Plans"
METRIC_KEY_NOTES = "Key Notes"

# QA / confidence labels
QA_VERIFIED = "Verified"
QA_REVIEW = "Review Recommended"
QA_NEEDS_REVIEW = "Needs Review"

# QA stage labels (contractor-friendly)
QA_STAGE_LABELS = {
    "sheet_index": "Drawing Index",
    "schedule_extraction": "Schedule Reading",
    "fixture_counting": "Fixture Counting",
    "keynote_extraction": "Keynote Detection",
}

# Feedback
FEEDBACK_TITLE = "Report an Issue"
FEEDBACK_DESCRIPTION = (
    "Found something that doesn't look right? Let us know "
    "so we can improve the results."
)
FEEDBACK_TYPES = [
    "Fixture count incorrect",
    "Missing fixture type",
    "Wrong fixture specs",
    "Keynote issue",
    "Page classification wrong",
    "General feedback",
]
FEEDBACK_SEVERITY = ["Minor", "Moderate", "Major"]
FEEDBACK_SUCCESS = "Issue reported. Thank you for helping us improve!"

# Landing page
LANDING_HEADLINE = "Upload your electrical drawings PDF, or try a demo to see PlanScan in action."
LANDING_FEATURES = [
    ("Fixture Schedule", "Complete specs extracted from your schedule pages"),
    ("Per-Plan Counts", "Fixture counts broken down by each lighting plan"),
    ("Quality Check", "Automated verification with confidence scoring"),
]

# Demo mode
DEMO_BANNER = "You're viewing demo results. Upload your own PDF to run a real takeoff."
DEMO_PROJECTS = {
    "HCMC Histology Lab": "hcmc_inventory.json",
    "Anoka Dispensary": "anoka_inventory.json",
}
