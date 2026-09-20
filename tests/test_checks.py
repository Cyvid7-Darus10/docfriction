from __future__ import annotations

import httpx

from docfriction.checks import check_links, find_placeholders, static_findings
from docfriction.models import CodeBlock, Segment


def make_segment(prose: str = "x" * 50, blocks: tuple[CodeBlock, ...] = ()) -> Segment:
    return Segment(index=0, heading_path=("A",), prose=prose, code_blocks=blocks)


def test_find_placeholders_across_styles():
    block = CodeBlock("bash", "export K=YOUR_API_KEY\nid=<project-id> {{tenant}} REPLACE_ME")
    assert find_placeholders(make_segment(blocks=(block,))) == (
        "<project-id>",
        "REPLACE_ME",
        "YOUR_API_KEY",
        "{{tenant}}",
    )


def test_angle_brackets_are_not_placeholders_in_markup():
    block = CodeBlock("html", "<div><span>hi</span></div>")
    assert find_placeholders(make_segment(blocks=(block,))) == ()


def test_static_findings_flag_untagged_code_and_stub_sections():
    untagged = static_findings(make_segment(blocks=(CodeBlock("", "ls"), CodeBlock("sh", "ls"))))
    assert [f.check for f in untagged] == ["untagged_code_block"]
    assert "1 code block(s)" in untagged[0].detail
    assert [f.check for f in static_findings(make_segment(prose="tiny"))] == ["stub_section"]
    assert static_findings(make_segment()) == ()


def test_check_links_reports_dead_and_unreachable_links():
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/ok"):
            return httpx.Response(200)
        if url.endswith("/head-forbidden"):
            return httpx.Response(200 if request.method == "GET" else 405)
        if url.endswith("/boom"):
            raise httpx.ConnectError("no route")
        return httpx.Response(404)

    findings = check_links(
        (
            "https://a.dev/ok",
            "https://a.dev/head-forbidden",
            "https://a.dev/gone",
            "https://a.dev/boom",
        ),
        transport=httpx.MockTransport(handler),
    )
    assert [f.check for f in findings] == ["dead_link", "dead_link"]
    assert "HTTP 404" in findings[0].detail
    assert "ConnectError" in findings[1].detail


def test_check_links_with_no_urls_makes_no_requests():
    assert check_links(()) == ()
