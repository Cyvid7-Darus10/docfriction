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
from docfriction.models import CodeBlock, Document, Segment
from docfriction.rubric import (
    CHECKS,
    FRICTION_TYPES,
    NO_FRICTION,
    OTHER_FRICTION,
    StepContext,
    build_questions,
    build_state,
)
from docfriction.segment import segment_markdown


def answers_from(raw: dict):
    return parse_result(jev_response(raw)).answers


def test_sentiment_bands():
    assert sentiment_for(None) == "unknown"
    assert sentiment_for(0.2) == "smooth"
    assert sentiment_for(1.0) == "hesitant"
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


def test_build_state_carries_reader_context():
    segments = segment_markdown(SAMPLE_MARKDOWN)
    context = StepContext(
        previous=segments[1],
        next_title=segments[3].title,
        earlier_titles=(segments[0].title, segments[1].title),
        persona="A data scientist who has never used a terminal",
    )
    state = build_state(segments[2], context, "Quickstart")
    assert state["reader"] == "A data scientist who has never used a terminal"
    assert state["section_path"] == "Quickstart > Configure"
    assert state["earlier_section_titles"] == ["Quickstart", "Quickstart > Install"]
    assert state["previous_section"] == {
        "title": "Quickstart > Install",
        "text": "Install the CLI with npm.",
        "code": "npm install -g widget-cli",
    }
    assert state["next_section_title"] == "Quickstart > Configure > Verify"
    assert state["placeholders"] == ["<project-id>", "YOUR_API_KEY"]
    assert state["code_blocks"][0]["language"] == "unspecified"

    first = build_state(segments[0], StepContext(), "Quickstart")
    assert "first section" in first["previous_section"]
    assert "last section" in first["next_section_title"]
    assert "code_blocks" not in first

    long_previous = Segment(0, ("Long",), "word " * 400, (CodeBlock("sh", "x" * 500),))
    clipped = build_state(segments[2], StepContext(previous=long_previous), "Q")
    assert clipped["previous_section"]["text"].endswith(
        "[... section truncated by docfriction ...]"
    )
    assert clipped["previous_section"]["code"].endswith(
        "[... section truncated by docfriction ...]"
    )


def test_build_questions_follow_typesafe_guidance():
    segments = segment_markdown(SAMPLE_MARKDOWN)
    questions = build_questions(segments[2])
    assert {
        "friction_type",
        "severity",
        "is_actionable",
        "prerequisites_stated",
        "expected_result_shown",
        "terms_defined",
        "code_matches_prose",
        "code_names_match_prose",
        "placeholders_explained",
    } == set(questions)
    criteria = questions["friction_type"]["criteria"]
    assert NO_FRICTION in criteria and OTHER_FRICTION in criteria
    for key, option in criteria.items():
        assert set(option) == {"what", "not_for", "examples"}, key
    assert questions["friction_type"]["instructions"]["focus"]
    assert len(questions["severity"]["criteria"]) == 4
    assert questions["prerequisites_stated"]["criteria"].keys() == {"true", "false"}

    concept_only = build_questions(segments[0])
    assert "code_matches_prose" not in concept_only
    assert "placeholders_explained" not in concept_only


def test_rubric_registry_is_consistent():
    assert len({kind.key for kind in FRICTION_TYPES}) == len(FRICTION_TYPES)
    assert len({check.key for check in CHECKS}) == len(CHECKS)
    for kind in FRICTION_TYPES:
        if kind.key not in (NO_FRICTION,):
            assert kind.detail, kind.key
    for check in CHECKS:
        if check.key != "is_actionable":
            assert check.detail, check.key


def test_other_friction_is_reported_with_a_readable_detail():
    _, findings = interpret_answers(
        answers_from({"friction_type": choice_answer(OTHER_FRICTION, 0.7)}), Thresholds()
    )
    assert findings[0].check == OTHER_FRICTION
    assert "no category" in findings[0].detail


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
