"""Walk a document step by step, ask Jev about each step, and assemble a friction log."""

from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from .checks import check_links, static_findings
from .jev import JevClient
from .models import JEV_SOURCE, Answer, Document, Finding, FrictionLog, Segment, StepLog
from .rubric import (
    ACTIONABLE_ONLY,
    FRICTION_TYPES,
    IS_ACTIONABLE,
    NO_FRICTION,
    NOUL_FAILURE_DETAIL,
    build_questions,
    build_state,
)
from .segment import segment_markdown

SENTIMENT_BANDS: tuple[tuple[str, float], ...] = (
    ("smooth", 0.75),
    ("pause", 1.5),
    ("frustrated", 2.25),
)
BLOCKED = "blocked"
UNKNOWN_SENTIMENT = "unknown"


@dataclass(frozen=True)
class Thresholds:
    """Where probabilities turn into findings. Tune per docs set; these are starting points."""

    friction_min_probability: float = 0.5
    noul_fail_below: float = 0.4
    noul_review_below: float = 0.6
    actionable_min: float = 0.5
    low_confidence: float = 0.4


@dataclass(frozen=True)
class EvaluateOptions:
    thresholds: Thresholds = field(default_factory=Thresholds)
    check_links: bool = False
    max_sections: int | None = None
    concurrency: int = 4


def evaluate_document(
    document: Document,
    client: JevClient,
    options: EvaluateOptions | None = None,
    *,
    link_transport: httpx.BaseTransport | None = None,
) -> FrictionLog:
    opts = options or EvaluateOptions()
    segments = segment_markdown(document.markdown)[: opts.max_sections]

    def run(index: int) -> StepLog:
        previous = segments[index - 1] if index else None
        return evaluate_segment(
            segments[index],
            previous,
            document.title,
            client,
            opts,
            link_transport=link_transport,
        )

    with ThreadPoolExecutor(max_workers=max(1, opts.concurrency)) as pool:
        steps = tuple(pool.map(run, range(len(segments))))
    return FrictionLog(
        source=document.source,
        title=document.title,
        model=_model_name(steps, client.model),
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        steps=steps,
    )


def evaluate_segment(
    segment: Segment,
    previous: Segment | None,
    page_title: str,
    client: JevClient,
    options: EvaluateOptions,
    *,
    link_transport: httpx.BaseTransport | None = None,
) -> StepLog:
    result = client.evaluate(build_state(segment, previous, page_title), build_questions(segment))
    severity, jev_findings = interpret_answers(result.answers, options.thresholds)
    links = check_links(segment.links, transport=link_transport) if options.check_links else ()
    return StepLog(
        segment=segment,
        severity=severity,
        sentiment=sentiment_for(severity),
        findings=(*jev_findings, *static_findings(segment), *links),
        input_tokens=result.input_tokens,
        model=result.model,
    )


def interpret_answers(
    answers: Mapping[str, Answer], thresholds: Thresholds
) -> tuple[float | None, tuple[Finding, ...]]:
    severity_answer = answers.get("severity")
    severity = float(severity_answer.value) if severity_answer else None
    actionable = answers.get(IS_ACTIONABLE)
    is_actionable = actionable is None or float(actionable.value) >= thresholds.actionable_min
    findings = [
        *_friction_type_findings(answers.get("friction_type"), thresholds),
        *(
            finding
            for key, answer in answers.items()
            if answer.type == "noul" and key in NOUL_FAILURE_DETAIL
            if is_actionable or key not in ACTIONABLE_ONLY
            for finding in _noul_findings(key, answer, thresholds)
        ),
    ]
    return severity, tuple(findings)


def sentiment_for(severity: float | None) -> str:
    if severity is None:
        return UNKNOWN_SENTIMENT
    for name, upper in SENTIMENT_BANDS:
        if severity < upper:
            return name
    return BLOCKED


def _friction_type_findings(answer: Answer | None, thresholds: Thresholds) -> tuple[Finding, ...]:
    if answer is None or answer.value == NO_FRICTION:
        return ()
    probability = answer.probability or 0.0
    if probability < thresholds.friction_min_probability:
        return ()
    confidence = answer.confidence
    return (
        Finding(
            check=str(answer.value),
            source=JEV_SOURCE,
            detail=FRICTION_TYPES.get(str(answer.value), str(answer.value)),
            probability=probability,
            confidence=confidence,
            needs_review=confidence is not None and confidence < thresholds.low_confidence,
        ),
    )


def _noul_findings(key: str, answer: Answer, thresholds: Thresholds) -> tuple[Finding, ...]:
    probability = float(answer.value)
    if probability >= thresholds.noul_review_below:
        return ()
    return (
        Finding(
            check=key,
            source=JEV_SOURCE,
            detail=NOUL_FAILURE_DETAIL[key],
            probability=probability,
            confidence=answer.confidence,
            needs_review=probability >= thresholds.noul_fail_below,
        ),
    )


def _model_name(steps: tuple[StepLog, ...], fallback: str) -> str:
    """Prefer the resolved model id from the API (e.g. jev-1.13.0) over the alias."""
    return next((step.model for step in steps if step.model), fallback)
