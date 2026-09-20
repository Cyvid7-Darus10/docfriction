from __future__ import annotations

import httpx
from conftest import (
    SAMPLE_MARKDOWN,
    choice_answer,
    clean_answers,
    jev_response,
    noul_answer,
    score_answer,
)

from docfriction.evaluate import (
    EvaluateOptions,
    Thresholds,
    evaluate_document,
    interpret_answers,
    sentiment_for,
)
from docfriction.jev import parse_result
from docfriction.models import Document, Segment
from docfriction.rubric import NO_FRICTION, build_questions, build_state
from docfriction.segment import segment_markdown


def answers_from(raw: dict):
    return parse_result(jev_response(raw)).answers


def test_sentiment_bands():
    assert sentiment_for(None) == "unknown"
    assert sentiment_for(0.2) == "smooth"
    assert sentiment_for(1.0) == "pause"
    assert sentiment_for(2.0) == "frustrated"
    assert sentiment_for(2.9) == "blocked"


def test_clean_answers_yield_no_findings():
    questions = build_questions(segment_markdown(SAMPLE_MARKDOWN)[1])
    severity, findings = interpret_answers(answers_from(clean_answers(questions)), Thresholds())
    assert severity == 0.2
    assert findings == ()


def test_friction_choice_becomes_finding_and_low_confidence_needs_review():
    confident = answers_from({"friction_type": choice_answer("missing_prerequisite", 0.8, 0.7)})
    _, findings = interpret_answers(confident, Thresholds())
    assert findings[0].check == "missing_prerequisite"
    assert findings[0].probability == 0.8
    assert findings[0].needs_review is False

    shaky = answers_from({"friction_type": choice_answer("undefined_term", 0.55, 0.2)})
    _, findings = interpret_answers(shaky, Thresholds())
    assert findings[0].needs_review is True

    weak = answers_from({"friction_type": choice_answer("undefined_term", 0.3)})
    assert interpret_answers(weak, Thresholds())[1] == ()
    none = answers_from({"friction_type": choice_answer(NO_FRICTION, 0.9)})
    assert interpret_answers(none, Thresholds())[1] == ()


def test_positive_nouls_fail_low_and_review_in_the_middle():
    raw = {
        "terms_defined": noul_answer(0.1),
        "code_matches_prose": noul_answer(0.5),
        "placeholders_explained": noul_answer(0.9),
    }
    _, findings = interpret_answers(answers_from(raw), Thresholds())
    by_check = {f.check: f for f in findings}
    assert by_check["terms_defined"].needs_review is False
    assert by_check["code_matches_prose"].needs_review is True
    assert "placeholders_explained" not in by_check


def test_actionable_only_checks_are_skipped_for_reference_sections():
    raw = {
        "is_actionable": noul_answer(0.1),
        "prerequisites_stated": noul_answer(0.1),
        "expected_result_shown": noul_answer(0.1),
        "terms_defined": noul_answer(0.1),
    }
    _, findings = interpret_answers(answers_from(raw), Thresholds())
    assert [f.check for f in findings] == ["terms_defined"]

    raw["is_actionable"] = noul_answer(0.9)
    _, findings = interpret_answers(answers_from(raw), Thresholds())
    assert {f.check for f in findings} == {
        "prerequisites_stated",
        "expected_result_shown",
        "terms_defined",
    }


def test_build_state_and_questions_follow_the_rubric():
    segments = segment_markdown(SAMPLE_MARKDOWN)
    state = build_state(segments[2], segments[1], "Quickstart")
    assert state["section_path"] == "Quickstart > Configure"
    assert state["previous_section_summary"].startswith("Quickstart > Install:")
    long_previous = Segment(0, ("Long",), "word " * 400)
    assert build_state(segments[2], long_previous, "Q")["previous_section_summary"].endswith(
        "[... section truncated by docfriction ...]"
    )
    assert state["placeholders"] == ["<project-id>", "YOUR_API_KEY"]
    assert state["code_blocks"][0]["language"] == "unspecified"
    questions = build_questions(segments[2])
    assert {
        "friction_type",
        "severity",
        "is_actionable",
        "code_matches_prose",
        "placeholders_explained",
    } <= set(questions)
    assert questions["friction_type"]["criteria"][NO_FRICTION]
    assert len(questions["severity"]["criteria"]) == 4

    first = build_state(segments[0], None, "Quickstart")
    assert "first section" in first["previous_section_summary"]
    assert "code_blocks" not in first
    assert "code_matches_prose" not in build_questions(segments[0])


def test_evaluate_document_end_to_end_with_mocked_jev_and_links(make_client, monkeypatch):
    def handler(_request: httpx.Request, body: dict) -> httpx.Response:
        answers = clean_answers(body["questions"])
        if body["state"]["section_path"] == "Quickstart > Configure":
            answers["friction_type"] = choice_answer("missing_prerequisite", 0.81, 0.7)
            answers["severity"] = score_answer(2.4)
            answers["placeholders_explained"] = noul_answer(0.15, 0.8)
        return httpx.Response(200, json=jev_response(answers, input_tokens=250))

    def link_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    document = Document(source="sample.md", title="Quickstart", markdown=SAMPLE_MARKDOWN)
    monkeypatch.setattr("docfriction.checks.resolve_host", lambda _host: ("93.184.216.34",))
    with make_client(handler) as client:
        log = evaluate_document(
            document,
            client,
            EvaluateOptions(check_links=True, concurrency=2),
            link_transport=httpx.MockTransport(link_handler),
        )

    assert log.model == "jev-1.13.0"
    assert log.input_tokens == 1000
    assert log.output_tokens == 48
    assert [s.sentiment for s in log.steps] == ["smooth", "smooth", "blocked", "smooth"]
    configure = log.steps[2]
    assert {f.check for f in configure.confirmed_findings} == {
        "missing_prerequisite",
        "placeholders_explained",
        "untagged_code_block",
        "dead_link",
    }
    assert log.max_severity == 2.4
    # Intro and Verify are one-liners, so the static stub_section check flags them too.
    assert [s.segment.index for s in log.friction_steps] == [0, 2, 3]


def test_max_sections_limits_work(clean_client):
    document = Document(source="s", title="Quickstart", markdown=SAMPLE_MARKDOWN)
    log = evaluate_document(document, clean_client, EvaluateOptions(max_sections=2))
    assert len(log.steps) == 2
