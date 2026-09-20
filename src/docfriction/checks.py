"""Deterministic checks that need no model. Jev is weak at counting and pattern
matching, so anything a regex or an HTTP request can answer is done here."""

from __future__ import annotations

import re

import httpx

from ._version import __version__
from .models import STATIC_SOURCE, Finding, Segment

PLACEHOLDER_RE = re.compile(
    r"YOUR_[A-Z0-9_]+"
    r"|\{\{[^}]+\}\}"
    r"|\bREPLACE[_ -]?ME\b"
    r"|\bCHANGE[_ -]?ME\b"
    r"|\bxxx+\b"
    r"|\bTODO\b"
)
ANGLE_PLACEHOLDER_RE = re.compile(r"<[A-Za-z][\w-]*(?:[_-][\w-]+)*>")
MARKUP_LANGUAGES = frozenset({"html", "xml", "jsx", "tsx", "vue", "svelte", "xhtml", "svg"})
MIN_PROSE_CHARS = 40
DEAD_LINK_RETRY_STATUSES = frozenset({400, 403, 405})
DEFAULT_LINK_TIMEOUT_SECONDS = 10.0
USER_AGENT = f"docfriction/{__version__} (+https://github.com/Cyvid7-Darus10/docfriction)"


def find_placeholders(segment: Segment) -> tuple[str, ...]:
    found: list[str] = []
    for block in segment.code_blocks:
        found.extend(PLACEHOLDER_RE.findall(block.content))
        if block.language not in MARKUP_LANGUAGES:
            found.extend(ANGLE_PLACEHOLDER_RE.findall(block.content))
    return tuple(sorted(set(found)))


def static_findings(segment: Segment) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    untagged = sum(1 for block in segment.code_blocks if not block.language)
    if untagged:
        findings.append(
            Finding(
                check="untagged_code_block",
                source=STATIC_SOURCE,
                detail=f"{untagged} code block(s) have no language tag, so readers cannot "
                "tell shell from config or output",
            )
        )
    if not segment.has_code and len(segment.prose) < MIN_PROSE_CHARS:
        findings.append(
            Finding(
                check="stub_section",
                source=STATIC_SOURCE,
                detail="The heading has almost no content under it",
            )
        )
    return tuple(findings)


def check_links(
    urls: tuple[str, ...],
    *,
    transport: httpx.BaseTransport | None = None,
    timeout: float = DEFAULT_LINK_TIMEOUT_SECONDS,
) -> tuple[Finding, ...]:
    if not urls:
        return ()
    with httpx.Client(
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
        transport=transport,
    ) as client:
        results = (_check_link(client, url) for url in urls)
        return tuple(finding for finding in results if finding is not None)


def _check_link(client: httpx.Client, url: str) -> Finding | None:
    try:
        response = client.head(url)
        if response.status_code in DEAD_LINK_RETRY_STATUSES:
            response = client.get(url)
    except httpx.HTTPError as exc:
        return _dead_link(f"{url} could not be reached ({type(exc).__name__})")
    if response.status_code >= 400:
        return _dead_link(f"{url} returned HTTP {response.status_code}")
    return None


def _dead_link(detail: str) -> Finding:
    return Finding(check="dead_link", source=STATIC_SOURCE, detail=detail)
