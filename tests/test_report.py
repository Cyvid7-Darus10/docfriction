from __future__ import annotations

import json

from docfriction.models import CodeBlock, Finding, FrictionLog, Segment, StepLog
from docfriction.report import render_json, render_markdown


def sample_log() -> FrictionLog:
    seg_a = Segment(0, ("Quickstart",), "welcome")
    seg_b = Segment(1, ("Quickstart", "Configure"), "set key", (CodeBlock("", "x=1"),))
    steps = (
        StepLog(seg_a, 0.2, "smooth", (), 100, 10, "jev-1.13.0"),
        StepLog(
            seg_b,
            2.4,
            "blocked",
            (
                Finding("missing_prerequisite", "jev", "needs a key", 0.81, 0.7),
                Finding("code_matches_prose", "jev", "mismatch", 0.5, 0.3, needs_review=True),
                Finding("dead_link", "static", "https://x returned HTTP 404"),
            ),
            200,
            20,
            "jev-1.13.0",
        ),
    )
    return FrictionLog("sample.md", "Quickstart", "jev-1.13.0", "2026-09-20T00:00:00+00:00", steps)


def test_markdown_report_has_summary_table_and_walkthrough():
    text = render_markdown(sample_log())
    assert text.startswith("# Friction log: Quickstart\n")
    assert "Steps: 2 · steps with friction: 1 · max severity: 2.4/3" in text
    assert "Jev tokens: 300 in, 30 out (about $0.0000; output is free)" in text
    assert "| 1 | Quickstart | 😀 smooth | 0.2 | – |" in text
    assert (
        "| 2 | Quickstart > Configure | 🛑 blocked | 2.4 | missing_prerequisite (0.81), dead_link |"
        in text
    )
    assert "### 1. Quickstart 😀 smooth (severity 0.2/3)" in text
    assert "- ✅ No friction detected" in text
    assert "- ⚠️ **missing_prerequisite** (p=0.81, confidence=0.70, jev) needs a key" in text
    assert "- ⚠️ **dead_link** (static) https://x returned HTTP 404" in text
    assert (
        "- 🔍 Needs review: **code_matches_prose** (p=0.50, confidence=0.30, jev) mismatch" in text
    )


def test_json_report_round_trips():
    payload = json.loads(render_json(sample_log()))
    assert payload["summary"] == {
        "steps": 2,
        "friction_steps": 1,
        "max_severity": 2.4,
        "input_tokens": 300,
        "output_tokens": 30,
        "estimated_cost_usd": 300 / 1_000_000 * 0.042,
    }
    assert payload["steps"][1]["heading_path"] == ["Quickstart", "Configure"]
    assert payload["steps"][1]["findings"][1]["needs_review"] is True
