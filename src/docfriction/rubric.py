"""The friction rubric: the typed questions docfriction asks Jev about every step.

Wording follows TypeSafe's guidance for Jev: judgments live in `instructions`,
answers live in `criteria`, levels describe concrete situations rather than
degrees, choices include a no-match option, and state fields are referenced with
backticked paths. Independent questions are batched into one call per step
(speculative fan-out) and interpreted in code afterwards.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .checks import find_placeholders
from .jev import choice, noul, score
from .models import Segment
from .segment import TRUNCATION_MARKER

NO_FRICTION = "no_friction"
PREVIOUS_SUMMARY_CHARS = 800

FRICTION_TYPES: Mapping[str, str] = {
    NO_FRICTION: (
        "A reader can follow this section as written without pausing or looking anything up"
    ),
    "missing_prerequisite": (
        "The step needs a tool, account, permission, file, or value that neither this section "
        "nor the earlier context tells the reader how to obtain"
    ),
    "undefined_term": (
        "A product-specific term, acronym, or name is used as if the reader already knows it, "
        "and it is not explained here or in the earlier context"
    ),
    "ambiguous_instruction": (
        "The reader is told to do something but not clearly where, how, or with which values"
    ),
    "code_prose_mismatch": (
        "The prose describes something different from what the code sample actually does, "
        "names, or requires"
    ),
    "missing_expected_result": (
        "The reader performs an action but is not told what success looks like, so they cannot "
        "tell whether it worked"
    ),
    "broken_sequence": (
        "The section assumes a state or step that the earlier context did not establish, so "
        "following the page in order fails here"
    ),
    "inconsistent_details": (
        "Version numbers, names, URLs, flags, or options in this section conflict with each "
        "other or with the earlier context"
    ),
}

SEVERITY_LEVELS: tuple[str, ...] = (
    "The reader continues without noticing any problem",
    "The reader pauses, re-reads, or makes a small guess, then continues",
    "The reader has to leave the page and search elsewhere before they can continue",
    "The reader cannot complete this step as written",
)

IS_ACTIONABLE = "is_actionable"

# Positively phrased yes/no checks: a LOW probability is the friction signal.
POSITIVE_NOULS: Mapping[str, str] = {
    "prerequisites_stated": (
        "Every tool, account, file, or value the reader needs for this section is named in "
        "`section_text` or `previous_section_summary`"
    ),
    "expected_result_shown": (
        "`section_text` tells the reader what they should see or get after performing the "
        "actions in this section"
    ),
    "terms_defined": (
        "Every product-specific term or acronym in `section_text` is explained there or in "
        "`previous_section_summary`"
    ),
}

CODE_NOULS: Mapping[str, str] = {
    "code_matches_prose": (
        "The `code_blocks` do exactly what `section_text` says they do, using the same names, "
        "flags, and values"
    ),
}

PLACEHOLDER_NOUL = (
    "placeholders_explained",
    "For every placeholder value listed in `placeholders`, `section_text` says where the "
    "reader gets the real value",
)

# Checks that only make sense when the section asks the reader to do something.
ACTIONABLE_ONLY: frozenset[str] = frozenset({"prerequisites_stated", "expected_result_shown"})

NOUL_FAILURE_DETAIL: Mapping[str, str] = {
    "prerequisites_stated": "Something the reader needs for this step is not named here or earlier",
    "expected_result_shown": "The reader is not told what success looks like after this step",
    "terms_defined": "A product-specific term is used without being explained",
    "code_matches_prose": "The code sample does not match what the prose says it does",
    "placeholders_explained": "A placeholder in the code is never explained in the text",
}


def build_state(segment: Segment, previous: Segment | None, page_title: str) -> dict[str, Any]:
    state: dict[str, Any] = {
        "page_title": page_title,
        "section_path": segment.title,
        "previous_section_summary": _summary(previous),
        "section_text": segment.prose or "(no prose, only code)",
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
    questions: dict[str, dict[str, Any]] = {
        "friction_type": choice(
            "What is the main thing that would slow down a developer following "
            "`section_text` as the next step after `previous_section_summary`?",
            FRICTION_TYPES,
        ),
        "severity": score(
            "What happens to a developer who follows `section_text` exactly as written?",
            SEVERITY_LEVELS,
        ),
        IS_ACTIONABLE: noul(
            "`section_text` asks the reader to run, install, open, create, or configure something"
        ),
        **{key: noul(text) for key, text in POSITIVE_NOULS.items()},
    }
    if segment.has_code:
        questions.update({key: noul(text) for key, text in CODE_NOULS.items()})
    if find_placeholders(segment):
        key, text = PLACEHOLDER_NOUL
        questions[key] = noul(text)
    return questions


def _summary(previous: Segment | None) -> str:
    if previous is None:
        return "(this is the first section of the page)"
    text = previous.prose or "(code only)"
    if len(text) > PREVIOUS_SUMMARY_CHARS:
        text = text[:PREVIOUS_SUMMARY_CHARS].rstrip() + TRUNCATION_MARKER
    return f"{previous.title}: {text}"
