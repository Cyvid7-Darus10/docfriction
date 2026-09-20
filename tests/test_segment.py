from __future__ import annotations

from conftest import SAMPLE_MARKDOWN

from docfriction.segment import (
    MAX_PROSE_CHARS,
    TRUNCATION_MARKER,
    document_title,
    extract_links,
    segment_markdown,
)


def test_sections_follow_heading_hierarchy():
    segments = segment_markdown(SAMPLE_MARKDOWN)
    assert [s.heading_path for s in segments] == [
        ("Quickstart",),
        ("Quickstart", "Install"),
        ("Quickstart", "Configure"),
        ("Quickstart", "Configure", "Verify"),
    ]
    assert [s.index for s in segments] == [0, 1, 2, 3]


def test_code_fences_are_captured_with_language_and_kept_out_of_prose():
    install, configure = segment_markdown(SAMPLE_MARKDOWN)[1:3]
    assert install.code_blocks[0].language == "bash"
    assert install.code_blocks[0].content == "npm install -g widget-cli"
    assert "npm install" not in install.prose
    assert configure.code_blocks[0].language == ""
    assert "widget sync --project <project-id>" in configure.code_blocks[0].content


def test_headings_inside_fences_do_not_split_sections():
    markdown = "# A\n\n```md\n# not a heading\n```\n\ntext"
    segments = segment_markdown(markdown)
    assert len(segments) == 1
    assert segments[0].code_blocks[0].content == "# not a heading"
    assert segments[0].prose == "text"


def test_unclosed_fence_is_still_captured():
    segments = segment_markdown("# A\n\n```sh\necho hi\n")
    assert segments[0].code_blocks[0].content == "echo hi"


def test_empty_sections_are_skipped_and_sibling_headings_replace_each_other():
    segments = segment_markdown("# A\n\n## B\n\n## C\n\nhello\n")
    assert [s.heading_path for s in segments] == [("A", "C")]


def test_links_are_extracted_and_deduplicated():
    prose = "See [docs](https://x.dev/a) and https://x.dev/a. Also https://y.dev/b, ok"
    assert extract_links(prose) == ("https://x.dev/a", "https://y.dev/b")


def test_long_prose_is_truncated_with_marker():
    segments = segment_markdown("# A\n\n" + "word " * (MAX_PROSE_CHARS // 2))
    assert segments[0].prose.endswith(TRUNCATION_MARKER)
    assert len(segments[0].prose) <= MAX_PROSE_CHARS + len(TRUNCATION_MARKER)


def test_document_title_uses_first_h1():
    assert document_title(SAMPLE_MARKDOWN) == "Quickstart"
    assert document_title("## only h2\ntext") is None


def test_segment_title_for_page_start_without_headings():
    segments = segment_markdown("just some text")
    assert segments[0].title == "(page start)"
