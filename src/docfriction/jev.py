"""Thin client for the TypeSafe System One HTTP API, which serves the Jev model.

The API is small enough (one endpoint, three question types) that a direct httpx
client is easier to test and audit than wrapping the official SDK. The request and
response shapes follow https://docs.typesafe.ai/api.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import httpx

from ._version import __version__
from .models import ANSWER_TYPES, Answer, AnswerType, JevResult

DEFAULT_BASE_URL = "https://api.typesafe.ai"
SYSTEM_ONE_PATH = "/v1/systemone"
DEFAULT_MODEL = "jev-latest"
API_KEY_ENV = "TYPESAFE_API_KEY"
BASE_URL_ENV = "TYPESAFE_BASE_URL"
# https://docs.typesafe.ai/models: input is metered, output tokens are free.
PRICE_PER_MILLION_INPUT_TOKENS_USD = 0.042
RETRYABLE_STATUSES = frozenset({429, 529})
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 0.5
USER_AGENT = f"docfriction/{__version__} (+https://github.com/Cyvid7-Darus10/docfriction)"

JsonState = str | Mapping[str, Any] | Sequence[Any]
Instructions = str | Mapping[str, Any] | Sequence[Any]
Criterion = str | Mapping[str, Any] | Sequence[Any] | None


class JevError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class MissingApiKeyError(JevError):
    pass


def noul(
    instructions: Instructions, criteria: Mapping[str, Criterion] | None = None
) -> dict[str, Any]:
    question: dict[str, Any] = {"type": "noul", "instructions": instructions}
    return {**question, "criteria": dict(criteria)} if criteria else question


def choice(instructions: Instructions, criteria: Mapping[str, Criterion]) -> dict[str, Any]:
    return {"type": "choice", "instructions": instructions, "criteria": dict(criteria)}


def score(instructions: Instructions, levels: Sequence[Criterion]) -> dict[str, Any]:
    return {"type": "score", "instructions": instructions, "criteria": list(levels)}


def estimated_cost_usd(input_tokens: int) -> float:
    return input_tokens / 1_000_000 * PRICE_PER_MILLION_INPUT_TOKENS_USD


def parse_result(payload: Mapping[str, Any]) -> JevResult:
    raw_answers = payload.get("answers")
    if not isinstance(raw_answers, Mapping):
        raise JevError("Jev response has no 'answers' object")
    answers = {key: _parse_answer(key, raw) for key, raw in raw_answers.items()}
    usage = payload.get("usage") or {}
    return JevResult(
        model=str(payload.get("model", "")),
        answers=answers,
        input_tokens=int(usage.get("input_tokens", 0)),
        output_tokens=int(usage.get("output_tokens", 0)),
    )


def _parse_answer(key: str, raw: Mapping[str, Any]) -> Answer:
    kind = _answer_type(key, raw.get("type"))
    try:
        if kind == "noul":
            value: str | float = float(raw["noul"])
        elif kind == "choice":
            value = str(raw["choice"])
        else:
            value = float(raw["score"])
    except (KeyError, TypeError, ValueError) as exc:
        raise JevError(f"malformed {kind} answer for question {key!r}: {exc}") from exc
    confidence = raw.get("confidence")
    return Answer(
        type=kind,
        value=value,
        confidence=float(confidence) if confidence is not None else None,
        probabilities={str(k): float(v) for k, v in (raw.get("probabilities") or {}).items()},
        legend={str(k): str(v) for k, v in (raw.get("legend") or {}).items()},
    )


def _answer_type(key: str, kind: object) -> AnswerType:
    for known in ANSWER_TYPES:
        if kind == known:
            return known
    raise JevError(f"unknown answer type {kind!r} for question {key!r}")


def validate_answers(
    answers: Mapping[str, Answer], questions: Mapping[str, Mapping[str, Any]]
) -> None:
    """Reject answers that do not fit the questions asked. Page content flows into the
    state, so a choice outside the offered criteria must never reach a report."""
    for key, answer in answers.items():
        question = questions.get(key)
        if question is None:
            raise JevError(f"Jev answered a question that was not asked: {key!r}")
        if answer.type != question.get("type"):
            raise JevError(f"Jev answered {key!r} with type {answer.type!r}")
        if answer.type == "choice" and answer.value not in question.get("criteria", {}):
            raise JevError(f"Jev chose {answer.value!r} for {key!r}, which was not offered")


class JevClient:
    """Synchronous Jev client with exponential backoff on 429 and 529."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        model: str = DEFAULT_MODEL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        key = api_key or os.environ.get(API_KEY_ENV)
        if not key:
            raise MissingApiKeyError(
                f"{API_KEY_ENV} is not set. Get a key at https://typesafe.ai and export it, "
                "or pass api_key= when constructing JevClient."
            )
        self._model = model
        self._max_retries = max_retries
        self._sleep = sleep
        self._client = httpx.Client(
            base_url=base_url or os.environ.get(BASE_URL_ENV) or DEFAULT_BASE_URL,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
            timeout=timeout,
            transport=transport,
        )

    @property
    def model(self) -> str:
        return self._model

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> JevClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def evaluate(self, state: JsonState, questions: Mapping[str, Mapping[str, Any]]) -> JevResult:
        """Evaluate one state against a batch of questions in a single round trip."""
        body = {"model": self._model, "state": state, "questions": dict(questions)}
        response = self._post_with_retries(body)
        if response.status_code != 200:
            raise JevError(_describe_http_error(response), status=response.status_code)
        try:
            payload = response.json()
        except ValueError as exc:
            raise JevError("Jev returned a non-JSON body") from exc
        result = parse_result(payload)
        validate_answers(result.answers, questions)
        return result

    def _post_with_retries(self, body: Mapping[str, Any]) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            if attempt:
                self._sleep(BACKOFF_BASE_SECONDS * 2 ** (attempt - 1))
            try:
                response = self._client.post(SYSTEM_ONE_PATH, json=body)
            except httpx.HTTPError as exc:
                last_error = exc
                continue
            if response.status_code not in RETRYABLE_STATUSES:
                return response
            last_error = JevError(f"Jev returned HTTP {response.status_code}", response.status_code)
        raise JevError(
            f"Jev did not answer after {self._max_retries + 1} attempts ({last_error}). "
            "Wait a minute and retry, or lower --concurrency."
        )


def _describe_http_error(response: httpx.Response) -> str:
    status = response.status_code
    if status == 401:
        return f"Jev rejected the API key (HTTP 401). Check {API_KEY_ENV}."
    if status == 422:
        return f"Jev rejected the request (HTTP 422): {response.text[:200]}"
    return f"Jev returned HTTP {status}: {response.text[:200]}"
