from __future__ import annotations

from conftest import SAMPLE_MARKDOWN

from docfriction.models import CodeBlock
from docfriction.segment import (
    MAX_PROSE_CHARS,
    TRUNCATION_MARKER,
    clean_heading,
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


def test_longer_fence_can_contain_a_shorter_fence():
    markdown = "# A\n\n````md\nSome text\n```\nnested\n```\nmore\n````\n\nafter"
    segments = segment_markdown(markdown)
    assert len(segments) == 1
    assert len(segments[0].code_blocks) == 1
    assert segments[0].code_blocks[0].content == "Some text\n```\nnested\n```\nmore"
    assert segments[0].prose == "after"


def test_tilde_fences_do_not_close_backtick_fences():
    segments = segment_markdown("# A\n\n```\nx\n~~~\ny\n```\n")
    assert segments[0].code_blocks[0].content == "x\n~~~\ny"


def test_setext_headings_are_recognised():
    markdown = "Title\n=====\n\nintro\n\nSection\n-------\n\nbody\n\n---\n\nafter rule"
    segments = segment_markdown(markdown)
    assert [s.heading_path for s in segments] == [("Title",), ("Title", "Section")]
    assert segments[0].prose == "intro"
    assert "=====" not in segments[0].prose
    assert segments[1].prose == "body\n\n---\n\nafter rule"
    assert document_title(markdown) == "Title"


def test_table_rows_and_list_items_are_not_setext_headings():
    markdown = "# A\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n- item\n---\n"
    segments = segment_markdown(markdown)
    assert [s.heading_path for s in segments] == [("A",)]


def test_indented_code_blocks_become_code():
    markdown = "# A\n\nHere is code:\n\n    def f():\n        return 1\n\nmore text\n"
    segments = segment_markdown(markdown)
    assert segments[0].code_blocks == (CodeBlock("", "def f():\n    return 1"),)
    assert segments[0].prose == "Here is code:\n\nmore text"


def test_indented_list_continuations_stay_prose():
    markdown = "# A\n\n- item one\n\n    - nested item\n\nend\n"
    segments = segment_markdown(markdown)
    assert segments[0].code_blocks == ()
    assert "nested item" in segments[0].prose


def test_front_matter_and_html_comments_are_dropped():
    markdown = "---\ntitle: Foo\ndraft: true\n---\n\n# Real\n\n<!-- internal: remove -->\ntext\n"
    segments = segment_markdown(markdown)
    assert [s.heading_path for s in segments] == [("Real",)]
    assert segments[0].prose == "text"
    assert document_title(markdown) == "Real"


def test_headings_are_cleaned_of_anchor_links_code_marks_and_escapes():
    raw = '`argparse` — Parser[¶](#module-argparse "Link to this heading") formatter\\_class'
    assert clean_heading(raw) == "argparse — Parser formatter_class"
    segments = segment_markdown("## " + raw + "\n\nbody")
    assert segments[0].heading_path == ("argparse — Parser formatter_class",)
