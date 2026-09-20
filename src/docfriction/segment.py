"""Split a Markdown document into walkthrough steps, one per heading section."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from .models import CodeBlock, Segment

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
FENCE_RE = re.compile(r"^(```+|~~~+)\s*([\w+.#-]*)")
LINK_RE = re.compile(r"\[[^\]]*\]\((https?://[^)\s]+)\)")
BARE_URL_RE = re.compile(r"(?<![(\[<])\bhttps?://[^\s)\]>\"'`]+")
BLANK_RUN_RE = re.compile(r"\n{3,}")
MAX_PROSE_CHARS = 6000
TRUNCATION_MARKER = "\n[... section truncated by docfriction ...]"


@dataclass(frozen=True)
class _Cursor:
    """Parser state carried across lines; every step returns a new cursor."""

    path: tuple[tuple[int, str], ...] = ()
    prose: tuple[str, ...] = ()
    code: tuple[CodeBlock, ...] = ()
    fence: str | None = None
    fence_language: str = ""
    fence_lines: tuple[str, ...] = ()
    segments: tuple[Segment, ...] = ()


def segment_markdown(markdown: str) -> tuple[Segment, ...]:
    cursor = _Cursor()
    for line in markdown.splitlines():
        cursor = _step(cursor, line)
    cursor = _close_fence(cursor) if cursor.fence else cursor
    return _flush(cursor).segments


def document_title(markdown: str) -> str | None:
    for line in markdown.splitlines():
        match = HEADING_RE.match(line)
        if match and len(match.group(1)) == 1:
            return match.group(2).strip()
    return None


def _step(cursor: _Cursor, line: str) -> _Cursor:
    if cursor.fence:
        if line.strip().startswith(cursor.fence):
            return _close_fence(cursor)
        return replace(cursor, fence_lines=(*cursor.fence_lines, line))
    fence = FENCE_RE.match(line.strip())
    if fence:
        return replace(cursor, fence=fence.group(1)[:3], fence_language=fence.group(2).lower())
    heading = HEADING_RE.match(line)
    if heading:
        flushed = _flush(cursor)
        level, title = len(heading.group(1)), heading.group(2).strip()
        kept = tuple(entry for entry in flushed.path if entry[0] < level)
        return replace(flushed, path=(*kept, (level, title)), prose=(), code=())
    return replace(cursor, prose=(*cursor.prose, line))


def _close_fence(cursor: _Cursor) -> _Cursor:
    block = CodeBlock(language=cursor.fence_language, content="\n".join(cursor.fence_lines))
    return replace(
        cursor, code=(*cursor.code, block), fence=None, fence_language="", fence_lines=()
    )


def _flush(cursor: _Cursor) -> _Cursor:
    prose = BLANK_RUN_RE.sub("\n\n", "\n".join(cursor.prose)).strip()
    if not prose and not cursor.code:
        return cursor
    segment = Segment(
        index=len(cursor.segments),
        heading_path=tuple(title for _, title in cursor.path),
        prose=_truncate(prose),
        code_blocks=cursor.code,
        links=extract_links(prose),
    )
    return replace(cursor, segments=(*cursor.segments, segment), prose=(), code=())


def _truncate(prose: str) -> str:
    if len(prose) <= MAX_PROSE_CHARS:
        return prose
    return prose[:MAX_PROSE_CHARS].rstrip() + TRUNCATION_MARKER


def extract_links(text: str) -> tuple[str, ...]:
    found = [*LINK_RE.findall(text), *BARE_URL_RE.findall(text)]
    return tuple(dict.fromkeys(url.rstrip(".,;:") for url in found))
