"""The friction rubric: the typed questions docfriction asks Jev about every step.

Grounding:

- Question shape follows TypeSafe's guidance for Jev (https://docs.typesafe.ai):
  one judgment per question, answers in `criteria`, score levels that describe
  situations rather than degrees, a no-match option on every choice, structured
  `what` / `not_for` / `examples` where options could be confused, and yes/no
  questions phrased so that a high probability means yes. Independent questions
  are batched into one call per step (speculative fan-out) and filtered in code.
- The friction taxonomy adapts Uddin & Robillard, "How API Documentation Fails"
  (IEEE Software 32(4), 2015): the content problems incompleteness, ambiguity,
  unexplained examples, inconsistency and incorrectness, and the presentation
  problems fragmentation and tangling. Obsoleteness is left out because Jev has
  no way to know which version is current.
- Severity mirrors the green / yellow / red scale used in DevRel friction logs:
  delightful, frustrating, and "would have given up if this weren't my job".
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .checks import find_placeholders
from .jev import choice, noul, score
from .models import Segment
from .segment import TRUNCATION_MARKER

NO_FRICTION = "no_friction"
OTHER_FRICTION = "other"
IS_ACTIONABLE = "is_actionable"
PREVIOUS_TEXT_CHARS = 800
PREVIOUS_CODE_CHARS = 300
DEFAULT_PERSONA = (
    "A developer new to this product, following the page from top to bottom with no "
    "other page open, who wants to finish the task the page describes"
)


@dataclass(frozen=True)
class FrictionType:
    """One option of the friction_type choice, with the boundaries TypeSafe recommends."""

    key: str
    what: str
    not_for: str
    examples: tuple[str, ...]
    detail: str

    def criteria(self) -> dict[str, Any]:
        return {"what": self.what, "not_for": self.not_for, "examples": list(self.examples)}


@dataclass(frozen=True)
class Check:
    """A yes/no question phrased so that a LOW probability is the friction signal."""

    key: str
    statement: str
    when_true: str
    when_false: str
    detail: str
    actionable_only: bool = False
    needs_code: bool = False
    needs_placeholders: bool = False

    def applies(self, segment: Segment, placeholders: tuple[str, ...]) -> bool:
        if self.needs_code and not segment.has_code:
            return False
        return not self.needs_placeholders or bool(placeholders)

    def question(self) -> dict[str, Any]:
        return noul(self.statement, {"true": self.when_true, "false": self.when_false})


@dataclass(frozen=True)
class StepContext:
    """What the reader has seen before this step, and what comes right after it."""

    previous: Segment | None = None
    next_title: str | None = None
    earlier_titles: tuple[str, ...] = ()
    persona: str = DEFAULT_PERSONA


FRICTION_TYPES: tuple[FrictionType, ...] = (
    FrictionType(
        NO_FRICTION,
        what="The reader can follow the section as written without pausing or leaving the page",
        not_for="Sections with any of the problems below, however small",
        examples=(
            "Install the CLI with `npm install -g widget-cli`. You should see `added 12 packages`.",
        ),
        detail="",
    ),
    FrictionType(
        "missing_prerequisite",
        what="An action needs a tool, account, permission, file, or value that nothing so far "
        "has told the reader to obtain",
        not_for="A name the reader does not understand (undefined_term), or an action that "
        "assumes an earlier step was done (broken_sequence)",
        examples=("Run `widget sync` with your API key, but no section says how to get a key",),
        detail="The step needs something the reader was never told to obtain",
    ),
    FrictionType(
        "undefined_term",
        what="A name specific to this product or its API is used as if the reader already knows it",
        not_for="Common industry terms such as HTTP, JSON, environment variable, or repository",
        examples=("Attach the Noul to the flow, when neither Noul nor flow has been introduced",),
        detail="A product-specific term is used without being explained",
    ),
    FrictionType(
        "ambiguous_instruction",
        what="The reader is told to do something but not where, how, or with which values",
        not_for="A clear instruction that needs something missing (missing_prerequisite)",
        examples=("Update the config to enable it, without naming the file or the setting",),
        detail="The instruction does not say where, how, or with which values",
    ),
    FrictionType(
        "unexplained_example",
        what="A code sample is shown with no explanation of what it does or which parts the "
        "reader is meant to change",
        not_for="Code whose explanation is wrong (code_prose_mismatch)",
        examples=("A thirty-line snippet under a heading with no surrounding text",),
        detail="The code sample is not explained",
    ),
    FrictionType(
        "code_prose_mismatch",
        what="The prose describes a different action, name, flag, or value than the code "
        "sample uses",
        not_for="Code that is merely unexplained (unexplained_example)",
        examples=("The text says pass --project but the command uses --workspace",),
        detail="The code sample does not match what the prose says it does",
    ),
    FrictionType(
        "missing_expected_result",
        what="The reader performs an action and nothing says what success looks like",
        not_for="Sections that only explain concepts and ask for no action",
        examples=("Run `widget deploy`, then the section ends",),
        detail="The reader is not told what success looks like after this step",
    ),
    FrictionType(
        "broken_sequence",
        what="The section assumes an earlier action or state that the page has not "
        "established by this point",
        not_for="A missing tool or credential (missing_prerequisite)",
        examples=("Open the dashboard you created earlier, when no earlier section created one",),
        detail="The step assumes something an earlier section never set up",
    ),
    FrictionType(
        "inconsistent_details",
        what="Names, versions, URLs, flags, or values in this section contradict each other "
        "or the earlier context",
        not_for="Prose and code disagreeing inside one sample (code_prose_mismatch)",
        examples=("The intro says Python 3.10, the command uses python3.8",),
        detail="Details in this section contradict each other or an earlier section",
    ),
    FrictionType(
        "fragmented_step",
        what="To finish this step the reader must go to another page for information that "
        "belongs here",
        not_for="Links offered as optional further reading",
        examples=("See the configuration guide for the required fields, with no fields listed",),
        detail="Finishing this step requires information that lives on another page",
    ),
    FrictionType(
        "tangled_section",
        what="The instruction the reader needs is buried in unrelated background, options, "
        "or caveats",
        not_for="Short sections that are merely terse",
        examples=("Three paragraphs of architecture history before the one command to run",),
        detail="The instruction is buried in unrelated material",
    ),
    FrictionType(
        OTHER_FRICTION,
        what="Something else slows the reader and none of the options above describes it",
        not_for="Anything that fits another option",
        examples=(),
        detail="Something slows the reader that the rubric has no category for; read the section",
    ),
)

FRICTION_BY_KEY: Mapping[str, FrictionType] = {kind.key: kind for kind in FRICTION_TYPES}

SEVERITY_LEVELS: tuple[str, ...] = (
    "The reader continues without noticing any problem",
    "The reader pauses, re-reads, or makes a small guess, then continues",
    "The reader has to leave the page and search elsewhere before they can continue",
    "The reader cannot complete this step as written and would give up if it were not their job",
)

CHECKS: tuple[Check, ...] = (
    Check(
        IS_ACTIONABLE,
        statement="`section_text` asks `reader` to run, install, open, create, or configure "
        "something",
        when_true="At least one instruction the reader carries out",
        when_false="Only explanation, reference tables, or background",
        detail="",
    ),
    Check(
        "prerequisites_stated",
        statement="Everything the actions in `section_text` need has been named in "
        "`section_text`, `previous_section`, or `earlier_section_titles`",
        when_true="Each tool, account, file, or value is named, or the actions need nothing "
        "beyond what earlier sections set up",
        when_false="An action uses something the reader was never told to obtain",
        detail="Something the reader needs for this step is not named here or earlier",
        actionable_only=True,
    ),
    Check(
        "expected_result_shown",
        statement="The reader can tell whether the actions in `section_text` worked",
        when_true="Expected output or state is described, or `next_section_title` is a step "
        "that checks it",
        when_false="The actions are given and nothing describes the outcome",
        detail="The reader is not told what success looks like after this step",
        actionable_only=True,
    ),
    Check(
        "terms_defined",
        statement="Every product-specific name in `section_text` is introduced there, in "
        "`previous_section`, or in `earlier_section_titles`",
        when_true="Product names are explained where first used, or only common industry "
        "terms appear",
        when_false="A name specific to this product or its API appears with no explanation "
        "anywhere so far",
        detail="A product-specific term is used without being explained",
    ),
    Check(
        "code_matches_prose",
        statement="The `code_blocks` perform the action that `section_text` describes",
        when_true="Running the code does what the prose says it does",
        when_false="The code does something different from, or less than, what the prose says",
        detail="The code sample does not do what the prose says it does",
        needs_code=True,
    ),
    Check(
        "code_names_match_prose",
        statement="Every name, flag, path, or value that `section_text` mentions appears in "
        "`code_blocks` spelled the same way",
        when_true="Identifiers in prose and code agree, or the prose mentions none",
        when_false="The prose mentions an identifier that the code spells differently or lacks",
        detail="A name, flag, or value in the prose does not match the code",
        needs_code=True,
    ),
    Check(
        "placeholders_explained",
        statement="For every placeholder in `placeholders`, `section_text` says where the "
        "reader gets the real value",
        when_true="Each placeholder is tied to a source: a settings page, an earlier step, "
        "or a command's output",
        when_false="At least one placeholder is never mentioned in the text",
        detail="A placeholder in the code is never explained in the text",
        needs_placeholders=True,
    ),
)

CHECKS_BY_KEY: Mapping[str, Check] = {check.key: check for check in CHECKS}


def build_state(segment: Segment, context: StepContext, page_title: str) -> dict[str, Any]:
    state: dict[str, Any] = {
        "reader": context.persona,
        "page_title": page_title,
        "section_path": segment.title,
        "earlier_section_titles": list(context.earlier_titles),
        "previous_section": _previous(context.previous),
        "section_text": segment.prose or "(no prose, only code)",
        "next_section_title": context.next_title or "(this is the last section)",
    }
    if segment.has_code:
        state["code_blocks"] = [
            {"language": block.language or "unspecified", "code": block.content}
            for block in segment.code_blocks
        ]
    placeholders = find_placeholders(segment)
    if placeholders:
        state["placeholders"] = list(placeholders)
    return state


def build_questions(segment: Segment) -> dict[str, dict[str, Any]]:
    placeholders = find_placeholders(segment)
    questions: dict[str, dict[str, Any]] = {
        "friction_type": choice(
            {
                "question": "Which option best describes the first thing that slows `reader` "
                "down when following `section_text`, given `previous_section` and "
                "`earlier_section_titles`?",
                "focus": "Whether the reader can complete the section, not its writing style",
            },
            {kind.key: kind.criteria() for kind in FRICTION_TYPES},
        ),
        "severity": score(
            {
                "question": "What happens to `reader` when they follow `section_text` exactly "
                "as written?",
                "context": "The reader has seen `previous_section` and `earlier_section_titles` "
                "and nothing else",
            },
            SEVERITY_LEVELS,
        ),
    }
    for check in CHECKS:
        if check.applies(segment, placeholders):
            questions[check.key] = check.question()
    return questions


def _previous(previous: Segment | None) -> dict[str, str] | str:
    if previous is None:
        return "(this is the first section of the page)"
    text = _clip(previous.prose or "(no prose)", PREVIOUS_TEXT_CHARS)
    summary = {"title": previous.title, "text": text}
    if previous.has_code:
        summary["code"] = _clip(previous.code_blocks[0].content, PREVIOUS_CODE_CHARS)
    return summary


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + TRUNCATION_MARKER
