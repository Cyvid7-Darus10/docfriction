"""Walk a document step by step, ask Jev about each step, and assemble a friction log."""

from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from .checks import check_links, link_client, static_findings
from .jev import JevClient
from .models import JEV_SOURCE, Answer, Document, Finding, FrictionLog, Segment, StepLog
from .rubric import (
    CHECKS_BY_KEY,
    DEFAULT_PERSONA,
    FRICTION_BY_KEY,
    IS_ACTIONABLE,
    NO_FRICTION,
    StepContext,
    build_questions,
    build_state,
)
from .segment import segment_markdown

# Reader states, all adjectives, in the order a friction log's margin marks escalate.
SENTIMENT_BANDS: tuple[tuple[str, float], ...] = (
    ("smooth", 0.75),
    ("hesitant", 1.5),
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
    allow_private_links: bool = False
    max_sections: int | None = None
    concurrency: int = 4
    persona: str = DEFAULT_PERSONA


def evaluate_document(
    document: Document,
    client: JevClient,
    options: EvaluateOptions | None = None,
    *,
    link_transport: httpx.BaseTransport | None = None,
) -> FrictionLog:
    opts = options or EvaluateOptions()
    segments = segment_markdown(document.markdown)[: opts.max_sections]
    links = (
        link_client(transport=link_transport, allow_private_hosts=opts.allow_private_links)
        if opts.check_links
        else None
    )

    def run(index: int) -> StepLog:
        context = StepContext(
            previous=segments[index - 1] if index else None,
            next_title=segments[index + 1].title if index + 1 < len(segments) else None,
            earlier_titles=tuple(segment.title for segment in segments[:index]),
            persona=opts.persona,
        )
        return evaluate_segment(segments[index], context, document.title, client, opts, links)

    try:
        with ThreadPoolExecutor(max_workers=max(1, opts.concurrency)) as pool:
            steps = tuple(pool.map(run, range(len(segments))))
    finally:
        if links is not None:
            links.close()
    return FrictionLog(
        source=document.source,
        title=document.title,
        model=_model_name(steps, client.model),
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        steps=steps,
    )


def evaluate_segment(
    segment: Segment,
    context: StepContext,
    page_title: str,
    client: JevClient,
    options: EvaluateOptions,
    links: httpx.Client | None = None,
) -> StepLog:
    result = client.evaluate(build_state(segment, context, page_title), build_questions(segment))
    severity, jev_findings = interpret_answers(result.answers, options.thresholds)
    link_findings = check_links(segment.links, links) if links is not None else ()
    return StepLog(
        segment=segment,
        severity=severity,
        sentiment=sentiment_for(severity),
        findings=(*jev_findings, *static_findings(segment), *link_findings),
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
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
            if answer.type == "noul" and key in CHECKS_BY_KEY and key != IS_ACTIONABLE
            if is_actionable or not CHECKS_BY_KEY[key].actionable_only
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
            detail=FRICTION_BY_KEY[str(answer.value)].detail,
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
            detail=CHECKS_BY_KEY[key].detail,
            probability=probability,
            confidence=answer.confidence,
            needs_review=probability >= thresholds.noul_fail_below,
        ),
    )


def _model_name(steps: tuple[StepLog, ...], fallback: str) -> str:
    """Prefer the resolved model id from the API (e.g. jev-1.13.0) over the alias."""
    return next((step.model for step in steps if step.model), fallback)
