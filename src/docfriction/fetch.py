"""Load a documentation page from a URL or a local file and normalise it to Markdown."""

from __future__ import annotations

from pathlib import Path

import httpx
from bs4 import BeautifulSoup, Tag
from markdownify import markdownify

from ._version import __version__
from .models import Document
from .segment import document_title

CONTENT_SELECTORS = ("main", "article", "[role=main]", "#content", ".content", ".markdown-body")
STRIP_TAGS = ("script", "style", "nav", "header", "footer", "aside", "noscript", "svg", "form")
HTML_SUFFIXES = frozenset({".html", ".htm"})
LANGUAGE_CLASS_PREFIXES = ("language-", "lang-")
USER_AGENT = f"docfriction/{__version__} (+https://github.com/Cyvid7-Darus10/docfriction)"
ACCEPT = "text/markdown, text/html;q=0.9, text/plain;q=0.8, */*;q=0.1"
DEFAULT_TIMEOUT_SECONDS = 20.0


class FetchError(Exception):
    pass


def load_document(
    source: str,
    *,
    transport: httpx.BaseTransport | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> Document:
    if source.startswith(("http://", "https://")):
        return _fetch_url(source, transport=transport, timeout=timeout)
    path = Path(source)
    if not path.is_file():
        raise FetchError(f"source is neither a URL nor an existing file: {source}")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise FetchError(f"failed to read {source}: {exc}") from exc
    if path.suffix.lower() in HTML_SUFFIXES:
        return _from_html(source, text, fallback_title=path.name)
    return Document(source=source, title=document_title(text) or path.name, markdown=text)


def _fetch_url(url: str, *, transport: httpx.BaseTransport | None, timeout: float) -> Document:
    headers = {"User-Agent": USER_AGENT, "Accept": ACCEPT}
    try:
        with httpx.Client(
            follow_redirects=True, headers=headers, timeout=timeout, transport=transport
        ) as client:
            response = client.get(url)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise FetchError(f"failed to fetch {url}: {exc}") from exc
    body = response.text
    if not body.strip():
        raise FetchError(f"{url} returned an empty body")
    if _looks_like_html(response.headers.get("content-type", ""), body):
        return _from_html(url, body, fallback_title=url)
    return Document(source=url, title=document_title(body) or url, markdown=body)


def _looks_like_html(content_type: str, body: str) -> bool:
    head = body.lstrip()[:20].lower()
    return "html" in content_type or head.startswith(("<!doctype", "<html"))


def _from_html(source: str, html: str, *, fallback_title: str) -> Document:
    soup = BeautifulSoup(html, "html.parser")
    page_title = soup.title.get_text(strip=True) if soup.title else ""
    for tag in soup(STRIP_TAGS):
        tag.decompose()
    root = _content_root(soup)
    markdown = markdownify(
        str(root), heading_style="ATX", bullets="-", code_language_callback=_code_language
    ).strip()
    if not markdown:
        raise FetchError(f"no readable content found in {source}")
    title = document_title(markdown) or page_title or fallback_title
    return Document(source=source, title=title, markdown=markdown)


def _content_root(soup: BeautifulSoup) -> Tag | BeautifulSoup:
    for selector in CONTENT_SELECTORS:
        found = soup.select_one(selector)
        if found is not None and found.get_text(strip=True):
            return found
    return soup.body or soup


def _code_language(element: Tag) -> str:
    classes = list(element.get("class") or [])
    inner = element.find("code")
    if isinstance(inner, Tag):
        classes.extend(inner.get("class") or [])
    for css_class in classes:
        for prefix in LANGUAGE_CLASS_PREFIXES:
            if css_class.startswith(prefix):
                return css_class[len(prefix) :]
    return ""
