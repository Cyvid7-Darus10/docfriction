"""Split a Markdown document into walkthrough steps, one per heading section.

Handles ATX (`# Title`) and setext (`Title\\n=====`) headings, fenced code blocks
(with CommonMark's rule that a closing fence is at least as long as the opening
one), indented code blocks, YAML front matter, and HTML comments.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from .models import CodeBlock, Segment

ATX_HEADING_RE = re.compile(r"^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
SETEXT_UNDERLINE_RE = re.compile(r"^ {0,3}(=+|-+)\s*$")
FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})\s*([\w+.#-]*)")
INDENTED_CODE_RE = re.compile(r"^(?: {4}|\t)(.*)$")
LIST_MARKER_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")
FRONT_MATTER_RE = re.compile(r"\A---[ \t]*\n.*?\n---[ \t]*\n", re.DOTALL)
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
LINK_RE = re.compile(r"\[[^\]]*\]\((https?://[^)\s]+)\)")
BARE_URL_RE = re.compile(r"(?<![(\[<])\bhttps?://[^\s)\]>\"'`]+")
MARKDOWN_LINK_TEXT_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
BLANK_RUN_RE = re.compile(r"\n{3,}")
MAX_PROSE_CHARS = 6000
TRUNCATION_MARKER = "\n[... section truncated by docfriction ...]"
HEADING_NOISE = ("¶", "🔗", "#️⃣")


@dataclass(frozen=True)
class _Cursor:
    """Parser state carried across lines; every step returns a new cursor."""

    path: tuple[tuple[int, str], ...] = ()
    prose: tuple[str, ...] = ()
    code: tuple[CodeBlock, ...] = ()
    fence: str | None = None
    fence_language: str = ""
    fence_lines: tuple[str, ...] = ()
    indented: tuple[str, ...] = ()
    skip_underline: bool = False
    segments: tuple[Segment, ...] = ()


def segment_markdown(markdown: str) -> tuple[Segment, ...]:
    cursor = _Cursor()
    lines = FRONT_MATTER_RE.sub("", markdown, count=1).splitlines()
    for index, line in enumerate(lines):
        following = lines[index + 1] if index + 1 < len(lines) else None
        cursor = _step(cursor, line, following)
    cursor = _close_fence(cursor) if cursor.fence else _close_indented(cursor)
    return _flush(cursor).segments


def document_title(markdown: str) -> str | None:
    lines = FRONT_MATTER_RE.sub("", markdown, count=1).splitlines()
    for index, line in enumerate(lines):
        atx = ATX_HEADING_RE.match(line)
        if atx and len(atx.group(1)) == 1:
            return clean_heading(atx.group(2))
        following = lines[index + 1] if index + 1 < len(lines) else None
        if following is not None and _is_setext(line, following) and following.strip()[0] == "=":
            return clean_heading(line)
    return None


def clean_heading(raw: str) -> str:
    """Strip anchor links, inline code marks, and Markdown escapes from a heading."""
    text = MARKDOWN_LINK_TEXT_RE.sub(r"\1", raw)
    text = text.replace("`", "")
    text = re.sub(r"\\([\\`*_{}\[\]()#+\-.!|])", r"\1", text)
    for noise in HEADING_NOISE:
        text = text.replace(noise, "")
    return text.strip().strip("#").strip()


def _step(cursor: _Cursor, line: str, following: str | None) -> _Cursor:
    if cursor.skip_underline:
        return replace(cursor, skip_underline=False)
    if cursor.fence:
        return _fence_line(cursor, line)
    if cursor.indented:
        if INDENTED_CODE_RE.match(line) or not line.strip():
            return replace(cursor, indented=(*cursor.indented, line))
        cursor = _close_indented(cursor)
    fence = FENCE_RE.match(line)
    if fence:
        return replace(cursor, fence=fence.group(1), fence_language=fence.group(2).lower())
    atx = ATX_HEADING_RE.match(line)
    if atx:
        return _open_heading(cursor, len(atx.group(1)), atx.group(2))
    if following is not None and _is_setext(line, following):
        level = 1 if following.strip()[0] == "=" else 2
        return replace(_open_heading(cursor, level, line), skip_underline=True)
    if _starts_indented_code(cursor, line):
        return replace(cursor, indented=(line,))
    return replace(cursor, prose=(*cursor.prose, line))


def _is_setext(line: str, underline: str) -> bool:
    if not line.strip() or "|" in line or ATX_HEADING_RE.match(line) or FENCE_RE.match(line):
        return False
    if LIST_MARKER_RE.match(line) or INDENTED_CODE_RE.match(line):
        return False
    return bool(SETEXT_UNDERLINE_RE.match(underline))


def _starts_indented_code(cursor: _Cursor, line: str) -> bool:
    if not INDENTED_CODE_RE.match(line) or LIST_MARKER_RE.match(line):
        return False
    return not cursor.prose or not cursor.prose[-1].strip()


def _fence_line(cursor: _Cursor, line: str) -> _Cursor:
    closing = FENCE_RE.match(line)
    if (
        closing
        and cursor.fence is not None
        and closing.group(1)[0] == cursor.fence[0]
        and len(closing.group(1)) >= len(cursor.fence)
        and not closing.group(2)
    ):
        return _close_fence(cursor)
    return replace(cursor, fence_lines=(*cursor.fence_lines, line))


def _open_heading(cursor: _Cursor, level: int, raw_title: str) -> _Cursor:
    flushed = _flush(cursor)
    kept = tuple(entry for entry in flushed.path if entry[0] < level)
    return replace(flushed, path=(*kept, (level, clean_heading(raw_title))), prose=(), code=())


def _close_fence(cursor: _Cursor) -> _Cursor:
    block = CodeBlock(language=cursor.fence_language, content="\n".join(cursor.fence_lines))
    return replace(
        cursor, code=(*cursor.code, block), fence=None, fence_language="", fence_lines=()
    )


def _close_indented(cursor: _Cursor) -> _Cursor:
    if not cursor.indented:
        return cursor
    stripped = [
        INDENTED_CODE_RE.sub(r"\1", line) if line.strip() else "" for line in cursor.indented
    ]
    block = CodeBlock(language="", content="\n".join(stripped).strip("\n"))
    return replace(cursor, code=(*cursor.code, block), indented=())


def _flush(cursor: _Cursor) -> _Cursor:
    cursor = _close_indented(cursor)
    raw = HTML_COMMENT_RE.sub("", "\n".join(cursor.prose))
    prose = BLANK_RUN_RE.sub("\n\n", raw).strip()
    if not prose and not cursor.code:
        return replace(cursor, prose=(), code=())
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
