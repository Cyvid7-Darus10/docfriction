from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from docfriction.fetch import FetchError, load_document

HTML = """<!doctype html><html><head><title>Widget Docs</title></head><body>
<nav><a href="/">Home</a></nav>
<main>
<h1>Install</h1>
<p>Run this:</p>
<pre><code class="language-bash">npm install widget</code></pre>
<h2>Next</h2><p>Go to <a href="https://x.dev/next">next</a>.</p>
</main>
<footer>footer junk</footer>
</body></html>"""


def transport(handler):
    return httpx.MockTransport(handler)


def test_html_url_is_converted_to_markdown_with_main_content_only():
    doc = load_document(
        "https://docs.example.com/install",
        transport=transport(
            lambda _r: httpx.Response(200, text=HTML, headers={"content-type": "text/html"})
        ),
    )
    assert doc.title == "Install"
    assert "# Install" in doc.markdown
    assert "```bash\nnpm install widget\n```" in doc.markdown
    assert "footer junk" not in doc.markdown
    assert "Home" not in doc.markdown
    assert "[next](https://x.dev/next)" in doc.markdown


def test_markdown_url_is_used_verbatim():
    doc = load_document(
        "https://docs.example.com/page.md",
        transport=transport(
            lambda _r: httpx.Response(
                200, text="# Hi\n\ntext", headers={"content-type": "text/markdown"}
            )
        ),
    )
    assert doc.markdown == "# Hi\n\ntext"
    assert doc.title == "Hi"


def test_html_without_content_type_is_detected_by_sniffing():
    doc = load_document(
        "https://d.example/x", transport=transport(lambda _r: httpx.Response(200, text=HTML))
    )
    assert "# Install" in doc.markdown


@pytest.mark.parametrize(
    "response, message",
    [
        (lambda _r: httpx.Response(500), "failed to fetch"),
        (lambda _r: httpx.Response(200, text="   "), "empty body"),
    ],
)
def test_fetch_errors_are_wrapped(response, message):
    with pytest.raises(FetchError, match=message):
        load_document("https://d.example/x", transport=transport(response))


def test_local_markdown_and_html_files(tmp_path: Path):
    md = tmp_path / "guide.md"
    md.write_text("# Guide\n\nhello", encoding="utf-8")
    doc = load_document(str(md))
    assert doc.title == "Guide" and doc.source == str(md)

    html = tmp_path / "page.html"
    html.write_text(HTML, encoding="utf-8")
    assert "# Install" in load_document(str(html)).markdown

    untitled = tmp_path / "notes.md"
    untitled.write_text("no heading here", encoding="utf-8")
    assert load_document(str(untitled)).title == "notes.md"


def test_missing_file_is_an_error(tmp_path: Path):
    with pytest.raises(FetchError, match="neither a URL nor an existing file"):
        load_document(str(tmp_path / "nope.md"))
