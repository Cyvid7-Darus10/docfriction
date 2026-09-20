from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

import httpx
import pytest

from docfriction.jev import JevClient

SAMPLE_MARKDOWN = """# Quickstart

Welcome to the Widget API.

## Install

Install the CLI with npm.

```bash
npm install -g widget-cli
```

## Configure

Set your key and run the sync command. See https://example.com/keys for details.

```
export WIDGET_KEY=YOUR_API_KEY
widget sync --project <project-id>
```

### Verify

Run `widget status`.
"""


def noul_answer(probability: float, confidence: float | None = None) -> dict[str, Any]:
    return {"type": "noul", "noul": probability, "confidence": confidence}


def choice_answer(label: str, probability: float, confidence: float = 0.8) -> dict[str, Any]:
    return {
        "type": "choice",
        "choice": label,
        "probabilities": {label: probability, "no_friction": round(1 - probability, 2)},
        "confidence": confidence,
    }


def score_answer(value: float, confidence: float = 0.7) -> dict[str, Any]:
    return {
        "type": "score",
        "score": value,
        "confidence": confidence,
        "probabilities": {"0": 0.1, "1": 0.2, "2": 0.4, "3": 0.3},
        "legend": {"0": "a", "1": "b", "2": "c", "3": "d"},
    }


def clean_answers(questions: Mapping[str, Any]) -> dict[str, Any]:
    """A 'no friction' answer set covering every question in the request."""
    answers: dict[str, Any] = {}
    for key, question in questions.items():
        kind = question["type"]
        if kind == "noul":
            answers[key] = noul_answer(0.95, 0.9)
        elif kind == "choice":
            answers[key] = choice_answer("no_friction", 0.9)
        else:
            answers[key] = score_answer(0.2)
    return answers


def jev_response(answers: Mapping[str, Any], input_tokens: int = 300) -> dict[str, Any]:
    return {
        "model": "jev-1.13.0",
        "answers": dict(answers),
        "usage": {"input_tokens": input_tokens, "output_tokens": 12},
    }


@pytest.fixture
def api_key(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    return "test-key"


@pytest.fixture
def make_client(api_key: str) -> Callable[..., JevClient]:
    """Build a JevClient whose HTTP layer is a handler over the decoded request body."""

    def factory(
        handler: Callable[[httpx.Request, dict[str, Any]], httpx.Response], **kwargs: Any
    ) -> JevClient:
        def transport_handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content.decode()) if request.content else {}
            return handler(request, body)

        return JevClient(
            transport=httpx.MockTransport(transport_handler), sleep=lambda _: None, **kwargs
        )

    return factory


@pytest.fixture
def clean_client(make_client: Callable[..., JevClient]) -> JevClient:
    return make_client(
        lambda _req, body: httpx.Response(200, json=jev_response(clean_answers(body["questions"])))
    )
