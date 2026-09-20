"""Immutable data types shared across docfriction."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

JEV_SOURCE = "jev"
STATIC_SOURCE = "static"

AnswerType = Literal["noul", "choice", "score"]
ANSWER_TYPES: tuple[AnswerType, ...] = ("noul", "choice", "score")


@dataclass(frozen=True)
class CodeBlock:
    language: str
    content: str


@dataclass(frozen=True)
class Segment:
    """One walkthrough step: the prose and code under a single heading."""

    index: int
    heading_path: tuple[str, ...]
    prose: str
    code_blocks: tuple[CodeBlock, ...] = ()
    links: tuple[str, ...] = ()

    @property
    def title(self) -> str:
        return " > ".join(self.heading_path) if self.heading_path else "(page start)"

    @property
    def has_code(self) -> bool:
        return bool(self.code_blocks)


@dataclass(frozen=True)
class Document:
    source: str
    title: str
    markdown: str


@dataclass(frozen=True)
class Answer:
    """One typed Jev answer, normalised across the noul, choice and score primitives."""

    type: AnswerType
    value: str | float
    confidence: float | None
    probabilities: Mapping[str, float] = field(default_factory=dict)
    legend: Mapping[str, str] = field(default_factory=dict)

    @property
    def probability(self) -> float | None:
        """Probability behind the returned value; scores have none (they are a weighted mean)."""
        if self.type == "noul":
            return float(self.value)
        if self.type == "choice":
            return self.probabilities.get(str(self.value))
        return None


@dataclass(frozen=True)
class JevResult:
    model: str
    answers: Mapping[str, Answer]
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class Finding:
    """A single friction point on a step, from Jev or from a deterministic check."""

    check: str
    source: str
    detail: str
    probability: float | None = None
    confidence: float | None = None
    needs_review: bool = False


@dataclass(frozen=True)
class StepLog:
    segment: Segment
    severity: float | None
    sentiment: str
    findings: tuple[Finding, ...]
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""

    @property
    def confirmed_findings(self) -> tuple[Finding, ...]:
        return tuple(finding for finding in self.findings if not finding.needs_review)

    @property
    def review_findings(self) -> tuple[Finding, ...]:
        return tuple(finding for finding in self.findings if finding.needs_review)


@dataclass(frozen=True)
class FrictionLog:
    source: str
    title: str
    model: str
    generated_at: str
    steps: tuple[StepLog, ...]

    @property
    def input_tokens(self) -> int:
        return sum(step.input_tokens for step in self.steps)

    @property
    def output_tokens(self) -> int:
        return sum(step.output_tokens for step in self.steps)

    @property
    def friction_steps(self) -> tuple[StepLog, ...]:
        return tuple(step for step in self.steps if step.confirmed_findings)

    @property
    def max_severity(self) -> float:
        severities = [step.severity for step in self.steps if step.severity is not None]
        return max(severities, default=0.0)
