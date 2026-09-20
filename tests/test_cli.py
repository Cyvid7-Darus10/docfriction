from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from conftest import SAMPLE_MARKDOWN, clean_answers, jev_response, score_answer

from docfriction import cli


@pytest.fixture
def sample_file(tmp_path: Path) -> Path:
    path = tmp_path / "sample.md"
    path.write_text(SAMPLE_MARKDOWN, encoding="utf-8")
    return path


def test_dry_run_lists_steps_without_a_key(sample_file: Path, capsys, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert cli.main([str(sample_file), "--dry-run", "--max-sections", "2"]) == 0
    out = capsys.readouterr().out
    assert "Quickstart: 2 steps" in out
    assert "2. Quickstart > Install (25 chars, 1 code block)" in out


def test_missing_key_is_reported(sample_file: Path, capsys, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert cli.main([str(sample_file)]) == 1
    assert "TYPESAFE_API_KEY" in capsys.readouterr().err


def test_missing_source_is_reported(capsys):
    assert cli.main(["/nope/none.md"]) == 1
    assert "is not a URL or an existing file" in capsys.readouterr().err


def test_full_run_writes_report_and_honours_fail_threshold(
    sample_file: Path, tmp_path: Path, capsys, api_key, monkeypatch
):
    def handler(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content.decode())
        answers = clean_answers(body["questions"])
        answers["severity"] = score_answer(2.5)
        return httpx.Response(200, json=jev_response(answers))

    real_client = cli.JevClient

    def patched(**kwargs):
        return real_client(transport=httpx.MockTransport(handler), sleep=lambda _: None, **kwargs)

    monkeypatch.setattr(cli, "JevClient", patched)
    out = tmp_path / "log.json"
    code = cli.main(
        [str(sample_file), "--format", "json", "--out", str(out), "--fail-on-severity", "2"]
    )
    assert code == 2
    assert '"max_severity": 2.5' in out.read_text()
    assert "severity 2.50 at step 1 (Quickstart) is at or above 2.0" in capsys.readouterr().err

    assert cli.main([str(sample_file)]) == 0
    assert "# Friction log: Quickstart" in capsys.readouterr().out


def test_jev_errors_are_reported(sample_file: Path, capsys, api_key, monkeypatch):
    real_client = cli.JevClient

    def patched(**kwargs):
        return real_client(
            transport=httpx.MockTransport(lambda _r: httpx.Response(401, text="nope")),
            sleep=lambda _: None,
            **kwargs,
        )

    monkeypatch.setattr(cli, "JevClient", patched)
    assert cli.main([str(sample_file)]) == 1
    assert "rejected the API key (HTTP 401)" in capsys.readouterr().err
