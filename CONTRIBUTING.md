# Contributing to docfriction

docfriction does one thing: turn a docs page into a friction log using Jev
plus deterministic checks. Bug reports on real pages, new checks, and better
rubric wording are the most useful contributions.

## Set up

```bash
git clone https://github.com/Cyvid7-Darus10/docfriction
cd docfriction
uv sync --all-groups
uv run pre-commit install   # optional but recommended
```

You do not need a TypeSafe API key to develop. The whole test suite runs
against a mocked HTTP transport, and `docfriction <page> --dry-run` exercises
fetching and segmentation without calling Jev.

## Run the checks

```bash
uv run pytest --cov=docfriction        # tests, coverage gate is 80%
uv run ruff check src tests            # lint
uv run ruff format src tests           # format
uv run mypy src                        # strict type check
```

CI runs the same four commands on Python 3.10, 3.12 and 3.13.

## Where things live

| Path | What |
|---|---|
| `src/docfriction/fetch.py` | URL / file loading, HTML to Markdown |
| `src/docfriction/segment.py` | Markdown to heading-level steps |
| `src/docfriction/rubric.py` | Every question we ask Jev, and the failure text per check |
| `src/docfriction/checks.py` | Deterministic checks (links, placeholders, stubs) |
| `src/docfriction/jev.py` | Thin HTTP client for `POST /v1/systemone` |
| `src/docfriction/evaluate.py` | Orchestration and thresholds |
| `src/docfriction/report.py` | Markdown and JSON rendering |
| `src/docfriction/cli.py` | argparse entry point |

## Changing the rubric

Changes to `rubric.py` get the closest review, because a badly worded
question quietly changes every report. Follow TypeSafe's guidance for Jev,
which the existing questions do:

- Put the judgment in `instructions` and the possible answers in `criteria`.
- Score levels describe concrete situations, not degrees ("the reader has to
  leave the page", not "moderately confusing").
- Choices include a no-match option.
- Reference state fields with backticks, e.g. `` `section_text` ``.
- Phrase yes/no checks positively; a low probability is the signal.
- Anything Jev is bad at (counting, comparing, following links) belongs in
  `checks.py`, not in a question.

Add a test in `tests/test_evaluate.py` for any new check, and a line in
`NOUL_FAILURE_DETAIL` so the report can explain it.

## Pull requests

- One logical change per PR. Keep refactors separate from behaviour changes.
- Use conventional commit messages: `feat:`, `fix:`, `docs:`, `test:`,
  `refactor:`, `chore:`, `ci:`.
- Add or update tests. New code should not lower coverage.
- Update `CHANGELOG.md` under "Unreleased".
- Explain *why* in the PR description; the diff shows what.

## Reporting bugs

Use the bug report issue template. If the bug is about a specific docs page,
include the URL and the output of `docfriction <url> --dry-run`, which never
sends anything to Jev.

## Security

Please do not open public issues for security problems. See
[SECURITY.md](SECURITY.md).

## Code of conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md).
