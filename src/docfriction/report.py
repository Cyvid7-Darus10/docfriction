"""Render a FrictionLog as a human-readable friction log (Markdown) or as JSON."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from .jev import estimated_cost_usd
from .models import Finding, FrictionLog, StepLog

SENTIMENT_ICONS = {
    "smooth": "😀",
    "hesitant": "😐",
    "frustrated": "😠",
    "blocked": "🛑",
    "unknown": "❔",
}
MAX_SEVERITY = 3.0


def render_markdown(log: FrictionLog) -> str:
    lines = [
        f"# Friction log: {log.title}",
        "",
        f"Source: {log.source}  ",
        f"Generated: {log.generated_at} by docfriction, model `{log.model}`  ",
        f"Steps: {len(log.steps)} · steps with friction: {len(log.friction_steps)} · "
        f"max severity: {log.max_severity:.1f}/{MAX_SEVERITY:.0f} · "
        f"Jev tokens: {log.input_tokens:,} in, {log.output_tokens:,} out "
        f"(about ${estimated_cost_usd(log.input_tokens):.4f}; output is free)",
        "",
        "## Summary",
        "",
        "| # | Step | Sentiment | Severity | Friction |",
        "|---|------|-----------|----------|----------|",
        *(_summary_row(step) for step in log.steps),
        "",
        "## Walkthrough",
        "",
        *(line for step in log.steps for line in _step_section(step)),
    ]
    return "\n".join(lines).rstrip() + "\n"


def render_json(log: FrictionLog) -> str:
    payload = {
        "source": log.source,
        "title": log.title,
        "model": log.model,
        "generated_at": log.generated_at,
        "summary": {
            "steps": len(log.steps),
            "friction_steps": len(log.friction_steps),
            "max_severity": log.max_severity,
            "input_tokens": log.input_tokens,
            "output_tokens": log.output_tokens,
            "estimated_cost_usd": estimated_cost_usd(log.input_tokens),
        },
        "steps": [_step_payload(step) for step in log.steps],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def _summary_row(step: StepLog) -> str:
    icon = SENTIMENT_ICONS.get(step.sentiment, "❔")
    severity = "–" if step.severity is None else f"{step.severity:.1f}"
    friction = ", ".join(_short(finding) for finding in step.confirmed_findings) or "–"
    return (
        f"| {step.segment.index + 1} | {step.segment.title} | {icon} {step.sentiment} "
        f"| {severity} | {friction} |"
    )


def _step_section(step: StepLog) -> tuple[str, ...]:
    icon = SENTIMENT_ICONS.get(step.sentiment, "❔")
    severity = "n/a" if step.severity is None else f"{step.severity:.1f}/{MAX_SEVERITY:.0f}"
    header = (
        f"### {step.segment.index + 1}. {step.segment.title} {icon} {step.sentiment} "
        f"(severity {severity})"
    )
    if not step.findings:
        return (header, "", "- ✅ No friction detected", "")
    body = [
        *(
            f"- ⚠️ **{finding.check}** {_evidence(finding)} {finding.detail}"
            for finding in step.confirmed_findings
        ),
        *(
            f"- 🔍 Needs review: **{finding.check}** {_evidence(finding)} {finding.detail}"
            for finding in step.review_findings
        ),
    ]
    return (header, "", *body, "")


def _short(finding: Finding) -> str:
    if finding.probability is None:
        return finding.check
    return f"{finding.check} ({finding.probability:.2f})"


def _evidence(finding: Finding) -> str:
    parts = []
    if finding.probability is not None:
        parts.append(f"p={finding.probability:.2f}")
    if finding.confidence is not None:
        parts.append(f"confidence={finding.confidence:.2f}")
    parts.append(finding.source)
    return f"({', '.join(parts)})"


def _step_payload(step: StepLog) -> dict[str, Any]:
    return {
        "index": step.segment.index + 1,
        "title": step.segment.title,
        "heading_path": list(step.segment.heading_path),
        "sentiment": step.sentiment,
        "severity": step.severity,
        "input_tokens": step.input_tokens,
        "output_tokens": step.output_tokens,
        "findings": [asdict(finding) for finding in step.findings],
    }
