"""Custom exceptions for Medina."""

from __future__ import annotations


class MedinaError(Exception):
    """Base exception for all Medina errors."""


class PDFLoadError(MedinaError):
    """Failed to load or parse a PDF file."""


class SheetIndexError(MedinaError):
    """Failed to discover or parse the sheet index."""


class ClassificationError(MedinaError):
    """Failed to classify a page type."""


class ScheduleExtractionError(MedinaError):
    """Failed to extract schedule table data."""


class FixtureCountError(MedinaError):
    """Failed to count fixtures on a plan page."""


class KeyNoteExtractionError(MedinaError):
    """Failed to extract key notes."""


class QAValidationError(MedinaError):
    """QA validation failed below confidence threshold."""


class OutputError(MedinaError):
    """Failed to generate output file."""


class VisionAPIError(MedinaError):
    """Failed to call the vision API."""
