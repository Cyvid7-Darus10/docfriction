"""docfriction: automated friction logs for online documentation, scored with TypeSafe Jev."""

from ._version import __version__
from .evaluate import EvaluateOptions, Thresholds, evaluate_document
from .fetch import FetchError, load_document
from .jev import JevClient, JevError, MissingApiKeyError
from .models import Document, Finding, FrictionLog, Segment, StepLog
from .report import render_json, render_markdown
from .segment import segment_markdown

__all__ = [
    "Document",
    "EvaluateOptions",
    "FetchError",
    "Finding",
    "FrictionLog",
    "JevClient",
    "JevError",
    "MissingApiKeyError",
    "Segment",
    "StepLog",
    "Thresholds",
    "__version__",
    "evaluate_document",
    "load_document",
    "render_json",
    "render_markdown",
    "segment_markdown",
]
