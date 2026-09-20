# Research notes: Jev, and using it to friction-log documentation

Written 2026-09-20, the day after TypeSafe announced Jev publicly. Prices,
limits and model ids below will drift; https://docs.typesafe.ai is the primary
source.

## 1. What Jev is

Jev is TypeSafe AI's "System One" model. It doesn't generate text. It takes
one state and a set of typed questions and returns one calibrated answer per
question. TypeSafe describes it as "a smart `if` statement" you can put inside
ordinary code.

Three question primitives:

| Primitive | Answer | Notes |
|---|---|---|
| `noul` | probability 0-1 that the statement is true | "A Noul near 0.5 means similar probability for yes and no, not medium intensity." |
| `choice` | one option key, plus a probability per option and a confidence | up to 255 options; include a no-match option when nothing may fit |
| `score` | probability-weighted mean of level indices, plus per-level probabilities, a confidence, and a legend | 2-10 levels; levels must describe concrete situations, not degrees |

All questions in one request are evaluated independently, in parallel, against
the same state, and cannot see each other's answers.

### API

```
POST https://api.typesafe.ai/v1/systemone
Authorization: Bearer $TYPESAFE_API_KEY
```

```json
{
  "model": "jev-latest",
  "state": { "section_text": "...", "code_blocks": [ ... ] },
  "questions": {
    "severity": {
      "type": "score",
      "instructions": "What happens to a developer who follows `section_text` exactly as written?",
      "criteria": [
        "The reader continues without noticing any problem",
        "The reader pauses, re-reads, or makes a small guess, then continues",
        "The reader has to leave the page and search elsewhere before they can continue",
        "The reader cannot complete this step as written"
      ]
    },
    "prerequisites_stated": { "type": "noul", "instructions": "..." },
    "friction_type": { "type": "choice", "instructions": "...", "criteria": { "no_friction": "...", "...": "..." } }
  }
}
```

Response:

```json
{
  "model": "jev-1.13.0",
  "answers": {
    "severity": { "type": "score", "score": 1.43, "confidence": 0.35,
                  "probabilities": { "0": 0.0, "1": 0.57, "2": 0.43, "3": 0.0 },
                  "legend": { "0": "...", "1": "...", "2": "...", "3": "..." } },
    "prerequisites_stated": { "type": "noul", "noul": 0.18 },
    "friction_type": { "type": "choice", "choice": "missing_prerequisite",
                       "probabilities": { "missing_prerequisite": 0.81, "no_friction": 0.09 },
                       "confidence": 0.72 }
  },
  "usage": { "input_tokens": 332, "output_tokens": 18 }
}
```

State can be a string, an object, or an array of text. Objects are recommended
so fields have names; instructions reference them with backticked paths such as
`` `ticket.messages[0].text` ``. Text only: no images, audio, or video.

Errors: 401 bad key, 422 validation, 429 rate limit, 529 overloaded. Retry 429
and 529 with exponential backoff.

### Numbers that matter

| | |
|---|---|
| Input price | $0.042 per million tokens |
| Output price | free (answers are a few tokens anyway) |
| Latency | 70-500 ms end to end, most requests near 100 ms |
| Rate limits (early access) | 250k tokens/s, 1,200 requests/min |
| Context | ~32k tokens per question+state, ~64k total state budget |
| Model ids | `jev-latest` (stable alias), `jev-preview`, `jev-1.13.0` (pinnable) |

A 40-section quickstart at ~400 tokens per section is ~16k input tokens, under
a tenth of a cent, in a few seconds with four parallel calls.

### SDKs and distribution

- Python: `pip install typesafe-sdk` (`from typesafe_sdk import TypeSafeClient, Choice, Score, Noul`)
- JavaScript: `npm install @typesafe-ai/sdk` (`choice`, `noul`, `score`, `TypeSafeClient`)
- Vercel AI SDK 7.0.105+: `experimental_evaluate` with `@ai-sdk/typesafe-ai` (calls noul "boolean")
- Vercel AI Gateway model id `typesafe-ai/jev`; also on Cloudflare AI as `typesafe/jev`
- Agent skill for Claude Code / Cursor / Codex: `claude plugin marketplace add typesafe-ai/skills`

docfriction talks to the HTTP endpoint directly with `httpx`. The surface is one
endpoint and three question shapes; a 100-line client is easier to mock, audit,
and pin than an SDK dependency.

### Known weaknesses (from TypeSafe's own "jaggedness" page for jev-1.13)

1. Literal reading: says what you asked, not what you meant. Spell out boundary cases.
2. Math and numbers: unreliable counting and arithmetic. Compute in code, use named buckets.
3. Date and time comparison: treats dates as text.
4. Indirection: double negatives and multi-hop reasoning degrade accuracy.
5. Large irrelevant state: distractors hurt. Send only what the question needs.
6. Adversarial content: not hardened against prompt injection in state.
7. Contradictory instructions vs criteria: align the wording.
8. No structural invariants: complementary questions need not sum to 1.
9. Generation: it cannot write text. Use Choice over bounded options instead.

## 2. What friction logging is

A friction log is a first-person, chronological record of trying to accomplish
a task with a product, written by someone acting as the target user. The form
was popularised by Google's developer-relations teams and is now common across
DevRel and docs teams. A typical log has:

- the persona and the goal ("new backend developer, wants a first API call in 15 minutes")
- one entry per step, with a timestamp or step number
- a sentiment marker per step, usually a three-level scale (delighted / neutral / frustrated) or an emoji
- what the author expected versus what happened
- a severity or "would I have given up here?" judgment
- a summary of the top friction points, with owners

The value of a friction log is that it records where a reader stops, which
no style linter can tell you. The cost is that a human has to walk the page,
and the log goes stale as soon as the page changes.

Two related practices: **documentation testing** (running the commands in a
page in CI to prove they work) and **doc linting** (Vale, markdownlint) which
catch style and structure issues. Neither answers "would a reader get stuck
here?", which is the question friction logs exist for.

## 3. Why Jev fits the gap

Every judgment in a friction log has a bounded answer:

| Human judgment | Bounded form |
|---|---|
| What went wrong at this step? | choice over a fixed taxonomy of friction types |
| How much did it hurt? | score over "continued / paused / left the page / gave up" |
| Are prerequisites stated? Is the result shown? Does the code match? | yes/no |

Three things make Jev fit this better than a general LLM would:

1. **Calibration.** A 0.81 on `missing_prerequisite` is meant to be a
   probability, and the model returns a separate confidence. That lets a tool
   distinguish "this is friction" from "I am unsure", which is what makes an
   automated log trustworthy enough to gate CI on.
2. **Cost and speed.** At ~$0.0004 per step and ~100 ms, every page can be
   logged on every change. Human friction logs happen once per launch, if
   that.
3. **No generation.** The output is a table of typed verdicts, not a paragraph
   that has to be parsed. Structured-output error rate is zero by
   construction.

Jev doesn't replace the person who reads the page and decides what to
rewrite. The report says which rubric item fired and how likely; a writer
still has to look at the section.

## 4. Design decisions in docfriction, traced to the research

| Decision | Reason |
|---|---|
| One Jev call per section, all rubric questions batched | TypeSafe's speculative fan-out pattern: batching is cheaper and faster, and questions cannot see each other anyway |
| Each state includes a clipped `previous_section_summary` | Friction is usually about what an earlier step did or did not establish; but large irrelevant state degrades Jev, so the summary is capped at 800 chars |
| Sections truncated at 6,000 chars | ~32k token ceiling per question+state; keeps the state focused |
| `friction_type` choice includes `no_friction` | TypeSafe: "include a no-match outcome when nothing may fit" |
| Severity levels describe what the reader does, not adjectives | TypeSafe: "describe situations, not degrees" |
| Yes/no checks phrased positively; low probability is the signal | Avoids double negatives, which Jev handles poorly (indirection) |
| `is_actionable` asked alongside, and used to gate prerequisite/result checks in code | Speculative question interpreted in code, per the fan-out pattern |
| `placeholders_explained` only asked when a regex finds placeholders, and the placeholders are passed in state | Jev cannot count or pattern-match reliably; give it the list |
| Dead links, untagged code, stub sections checked in code | Jev cannot follow links or count |
| Middle-band probabilities become "needs review", not findings | Mirrors TypeSafe's self-consistency cookbooks: route uncertainty to a human |
| Client is a thin httpx wrapper with backoff on 429/529 | Documented retry guidance; trivially mockable in tests |
| `--model` flag to pin a version | `jev-latest` can move; CI gates should pin |

## 5. Open questions and next steps

- **Validation.** Compare docfriction's findings against a few human-written
  friction logs and measure precision/recall per rubric item. Thresholds are
  guesses until then.
- **Cross-page context.** Friction often comes from a prerequisite that lives
  on a different page. A crawl mode that carries a rolling summary across the
  docs tree would catch more.
- **Executable steps.** Combine with a browser or shell runner
  (`jev-agent-browser`, `agent-browser`) so "did the command actually work"
  is observed rather than judged.
- **Persona conditioning.** Add a `persona` field to state ("first-time
  user, no cloud experience") and see whether Jev's severities shift
  sensibly.
- **Trend tracking.** Store JSON reports per commit and chart severity over
  time per page.

## Sources

- TypeSafe docs: https://docs.typesafe.ai (quickstart, primitives, patterns, cookbooks, model jaggedness, API reference)
- TypeSafe agent skill: https://github.com/typesafe-ai/skills
- Cloudflare AI model page: https://developers.cloudflare.com/ai/models/typesafe/jev/
- Flavio Copes, "A deep dive into Jev": https://flaviocopes.com/jev/
- DataCamp, "System One models: Jev": https://www.datacamp.com/blog/system-one-models-jev
- MarkTechPost launch coverage (2026-09-19): https://www.marktechpost.com/2026/09/19/typesafe-ai-releases-jev/
- Community: https://github.com/fatwang2/awesome-jev-by-typesafe, https://github.com/forvela/jev-agent-browser
- Friction logging background: https://dev.to/codejs_1959/friction-log-the-first-fifteen-minutes-of-an-ai-coding-tool-4h27, https://weaveos.com/glossary/friction-log
