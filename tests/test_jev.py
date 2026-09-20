from __future__ import annotations

import httpx
import pytest
from conftest import choice_answer, jev_response, noul_answer, score_answer

from docfriction.jev import (
    JevClient,
    JevError,
    MissingApiKeyError,
    choice,
    estimated_cost_usd,
    noul,
    parse_result,
    score,
)


def test_question_helpers_produce_documented_shapes():
    assert noul("q") == {"type": "noul", "instructions": "q"}
    assert noul("q", {"true": "t", "false": "f"})["criteria"] == {"true": "t", "false": "f"}
    assert choice("q", {"a": "A", "b": None}) == {
        "type": "choice",
        "instructions": "q",
        "criteria": {"a": "A", "b": None},
    }
    assert score("q", ("lo", "hi")) == {
        "type": "score",
        "instructions": "q",
        "criteria": ["lo", "hi"],
    }


def test_missing_key_raises(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(MissingApiKeyError):
        JevClient()


def test_evaluate_sends_documented_request_and_parses_answers(make_client):
    seen: dict = {}

    def handler(request: httpx.Request, body: dict) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = body
        return httpx.Response(
            200,
            json=jev_response(
                {
                    "yn": noul_answer(0.82, 0.6),
                    "pick": choice_answer("b", 0.7),
                    "rate": score_answer(1.4),
                }
            ),
        )

    questions = {
        "yn": noul("q"),
        "pick": choice("q", {"a": "A", "b": "B", "no_friction": "none"}),
        "rate": score("q", ("a", "b", "c", "d")),
    }
    with make_client(handler, model="jev-1.13.0") as client:
        result = client.evaluate({"text": "hi"}, questions)

    assert seen["url"] == "https://api.typesafe.ai/v1/systemone"
    assert seen["auth"] == "Bearer test-key"
    assert seen["body"] == {"model": "jev-1.13.0", "state": {"text": "hi"}, "questions": questions}
    assert result.model == "jev-1.13.0"
    assert result.input_tokens == 300
    assert result.answers["yn"].value == 0.82
    assert result.answers["yn"].probability == 0.82
    assert result.answers["pick"].value == "b"
    assert result.answers["pick"].probability == 0.7
    assert result.answers["rate"].value == 1.4
    assert result.answers["rate"].probability is None
    assert result.answers["rate"].legend["3"] == "d"


def test_retries_on_rate_limit_then_succeeds(make_client):
    attempts: list[int] = []

    def handler(_request: httpx.Request, _body: dict) -> httpx.Response:
        attempts.append(1)
        if len(attempts) < 3:
            return httpx.Response(429, json={"error": "slow down"})
        return httpx.Response(200, json=jev_response({"yn": noul_answer(0.5)}))

    with make_client(handler) as client:
        assert client.evaluate("s", {"yn": noul("q")}).answers["yn"].value == 0.5
    assert len(attempts) == 3


def test_gives_up_after_max_retries(make_client):
    def handler(_request: httpx.Request, _body: dict) -> httpx.Response:
        return httpx.Response(529)

    with (
        make_client(handler, max_retries=1) as client,
        pytest.raises(JevError, match="after 2 attempts"),
    ):
        client.evaluate("s", {"yn": noul("q")})


def test_transport_errors_are_retried_then_raised(make_client):
    def handler(_request: httpx.Request, _body: dict) -> httpx.Response:
        raise httpx.ConnectError("down")

    with make_client(handler, max_retries=1) as client, pytest.raises(JevError, match="down"):
        client.evaluate("s", {"yn": noul("q")})


def test_non_retryable_http_error_surfaces_status(make_client):
    def handler(_request: httpx.Request, _body: dict) -> httpx.Response:
        return httpx.Response(401, text="bad key")

    with make_client(handler) as client, pytest.raises(JevError) as info:
        client.evaluate("s", {"yn": noul("q")})
    assert info.value.status == 401
    assert "Check TYPESAFE_API_KEY" in str(info.value)


def test_non_json_body_is_an_error(make_client):
    def handler(_request: httpx.Request, _body: dict) -> httpx.Response:
        return httpx.Response(200, text="<html>")

    with make_client(handler) as client, pytest.raises(JevError, match="non-JSON"):
        client.evaluate("s", {"yn": noul("q")})


@pytest.mark.parametrize(
    "payload, message",
    [
        ({"model": "x"}, "no 'answers'"),
        ({"answers": {"q": {"type": "mystery"}}}, "unknown answer type"),
        ({"answers": {"q": {"type": "noul"}}}, "malformed noul"),
    ],
)
def test_parse_result_rejects_malformed_payloads(payload, message):
    with pytest.raises(JevError, match=message):
        parse_result(payload)


def test_estimated_cost_uses_published_input_price():
    assert estimated_cost_usd(1_000_000) == pytest.approx(0.042)


@pytest.mark.parametrize(
    "answers, message",
    [
        ({"yn": noul_answer(0.5), "extra": noul_answer(0.5)}, "not asked"),
        ({"yn": choice_answer("a", 0.9)}, "with type 'choice'"),
        ({"pick": choice_answer("<script>", 0.9)}, "was not offered"),
    ],
)
def test_answers_that_do_not_fit_the_questions_are_rejected(make_client, answers, message):
    def handler(_request: httpx.Request, _body: dict) -> httpx.Response:
        return httpx.Response(200, json=jev_response(answers))

    questions = {"yn": noul("q"), "pick": choice("q", {"a": "A", "b": "B"})}
    with make_client(handler) as client, pytest.raises(JevError, match=message):
        client.evaluate("s", questions)
