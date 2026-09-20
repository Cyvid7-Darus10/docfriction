# docfriction

Automated friction logs for online documentation, scored section by section with
[TypeSafe Jev](https://typesafe.ai).

A friction log is what a developer advocate writes when they walk through a
quickstart as a new user: every step, what they expected, where they got stuck,
and how much it hurt. It is one of the highest-signal docs QA practices we have,
and one of the least scalable, because a human has to do the walking.

docfriction does the walking. It fetches a docs page, splits it into steps (one
per heading), and asks Jev a fixed rubric of typed questions about each step:
what kind of friction is here, how badly would it stop a reader, are the
prerequisites stated, does the code match the prose, are the placeholders
explained. Jev answers with calibrated probabilities in about 100 ms per step
for a fraction of a cent, so you can run it on every page, on every pull
request, and gate on the result.

```text
$ docfriction https://docs.example.com/quickstart --check-links

# Friction log: Quickstart
Steps: 9 · steps with friction: 2 · max severity: 2.4/3 · Jev input tokens: 4,120 (about $0.0002)

| # | Step                         | Sentiment     | Severity | Friction                                  |
|---|------------------------------|---------------|----------|-------------------------------------------|
| 1 | Quickstart                   | 😀 smooth     | 0.2      | –                                         |
| 2 | Quickstart > Install         | 😀 smooth     | 0.3      | –                                         |
| 3 | Quickstart > Configure       | 🛑 blocked    | 2.4      | missing_prerequisite (0.81), dead_link    |
| 4 | Quickstart > First request   | 😐 pause      | 1.1      | –                                         |
...
```

See [examples/sample-friction-log.md](examples/sample-friction-log.md) for a full
report and [docs/research.md](docs/research.md) for the notes on Jev that led to
this design.

## Why Jev

Jev is a "System One" model: it does not generate text. You give it a state and
a set of typed questions (yes/no, pick one, rate on a scale) and it returns one
typed answer per question with a probability distribution and a confidence
number. That shape happens to be exactly what a friction log needs:

| Friction-log question a human answers | Jev primitive docfriction uses |
|---|---|
| "What went wrong here?" | `Choice` over eight friction types plus `no_friction` |
| "How bad was it?" | `Score` over four situations, from "continued without noticing" to "cannot complete the step" |
| "Did they tell me what I needed first?" | `Noul` (yes/no) `prerequisites_stated` |
| "Do I know if it worked?" | `Noul` `expected_result_shown` |
| "Does the code do what the text says?" | `Noul` `code_matches_prose` |
| "Where do I get `YOUR_API_KEY`?" | `Noul` `placeholders_explained`, only asked when a regex finds placeholders |

Because the answers are typed and calibrated, the output is machine-gradable:
thresholds turn probabilities into findings, low-confidence answers are marked
"needs review" instead of being reported as facts, and CI can fail on severity.

What Jev cannot do (count, compare versions, follow links, generate prose) is
done by deterministic checks in [`checks.py`](src/docfriction/checks.py): dead
links, untagged code blocks, stub sections, placeholder detection.

## Install

```bash
uv tool install docfriction        # or: pipx install docfriction
export TYPESAFE_API_KEY=...         # from https://typesafe.ai
```

From source:

```bash
git clone https://github.com/Cyvid7-Darus10/docfriction
cd docfriction && uv sync
uv run docfriction --help
```

## Usage

```bash
# A live docs page, Markdown report to stdout
docfriction https://docs.example.com/quickstart

# A local file, JSON report to disk, also check every external link
docfriction docs/quickstart.md --format json --out friction.json --check-links

# See how the page will be split into steps without spending any tokens
docfriction https://docs.example.com/quickstart --dry-run

# CI gate: exit 2 if any step scores 2.5 or higher on the 0-3 severity scale
docfriction docs/quickstart.md --fail-on-severity 2.5
```

Options:

| Flag | Meaning |
|---|---|
| `-f, --format md\|json` | Report format (default `md`) |
| `-o, --out FILE` | Write the report to a file instead of stdout |
| `--check-links` | HEAD every external link in each section and report 4xx/5xx |
| `--max-sections N` | Only evaluate the first N sections |
| `--concurrency N` | Parallel Jev calls (default 4) |
| `--model ID` | Pin a Jev version, e.g. `jev-1.13.0` (default `jev-latest`) |
| `--fail-on-severity N` | Exit 2 when any step's severity is at least N |
| `--dry-run` | Print the detected steps and exit; no API key needed |

Exit codes: `0` ok, `1` fetch or API error, `2` severity threshold exceeded.

A ready-made GitHub Actions workflow that runs on changed docs pages is in
[examples/github-action.yml](examples/github-action.yml).

## How it works

1. **Fetch.** URLs are fetched with an `Accept` header that prefers Markdown
   (many docs sites serve it). HTML is reduced to its `<main>`/`<article>`
   content and converted to Markdown with fenced, language-tagged code blocks.
2. **Segment.** The Markdown is split at headings. Each segment keeps its full
   heading path, prose, code blocks, and links. Code fences never split a
   section. Sections longer than 6,000 characters are truncated so the Jev
   state stays small; Jev degrades on large irrelevant context.
3. **Build state.** Each step is evaluated as the reader would meet it: with a
   summary of the previous section as context, the section text, the code
   blocks, and any placeholders the regex found.
4. **Ask Jev once per step.** All rubric questions are batched into a single
   request (speculative fan-out). Questions that only make sense for
   actionable steps are still asked, and only applied when `is_actionable`
   comes back likely.
5. **Interpret.** Probabilities become findings via `Thresholds` (defaults in
   [`evaluate.py`](src/docfriction/evaluate.py)). A positive check below 0.4
   is a finding, between 0.4 and 0.6 is "needs review". A friction type is
   reported when its probability is at least 0.5 and marked for review when
   Jev's confidence is under 0.4.
6. **Report.** Markdown that reads like a human friction log (summary table,
   then a walkthrough with sentiment per step), or JSON for tooling.

Sentiment bands map the 0-3 severity score to the emoji a human would put in
the margin: 😀 smooth (< 0.75), 😐 pause (< 1.5), 😠 frustrated (< 2.25),
🛑 blocked.

## Library use

```python
from docfriction import EvaluateOptions, JevClient, evaluate_document, load_document, render_markdown

document = load_document("https://docs.example.com/quickstart")
with JevClient() as client:
    log = evaluate_document(document, client, EvaluateOptions(check_links=True))
print(render_markdown(log))
for step in log.friction_steps:
    print(step.segment.title, step.severity, [f.check for f in step.confirmed_findings])
```

## Tuning the rubric

Everything Jev is asked lives in [`rubric.py`](src/docfriction/rubric.py). The
wording follows TypeSafe's guidance: judgments in `instructions`, answers in
`criteria`, score levels that describe situations rather than degrees, a
`no_friction` option so the choice is never forced, and backticked references
to state fields. If your docs have a house style (say, every step must end with
expected output), add a `Noul` for it and a line in `NOUL_FAILURE_DETAIL`.

Thresholds are deliberately conservative starting points. Run docfriction on a
few pages you know well, compare its findings with your own, and adjust
`Thresholds` before wiring it into CI.

## Limits and honesty

- Jev returns probabilities, not explanations. docfriction tells you *which*
  rubric item fired and *how likely* Jev thinks it is; a human still decides
  what to change. Low-confidence answers are labelled "needs review" for that
  reason.
- Jev reads literally and is not robust to adversarial content. Do not treat a
  clean log on a page you do not control as a security signal.
- One heading is treated as one step. Pages that put a whole tutorial under a
  single heading get one coarse evaluation; pages with many tiny headings get
  many stub findings. `--dry-run` shows the split before you spend tokens.
- The report has not been validated against human friction logs at scale yet.
  Treat it as a tireless first reviewer, not a verdict.

## Development

```bash
uv sync --all-groups
uv run pytest --cov=docfriction     # 48 tests, coverage gate 80% in CI
uv run ruff check src tests && uv run ruff format src tests
```

The Jev client is a thin `httpx` wrapper over the documented
`POST /v1/systemone` endpoint with retries on 429/529. All tests run against
`httpx.MockTransport`; no network or key is needed.

## License

MIT. Authored by Cyrus David Pastelero.
