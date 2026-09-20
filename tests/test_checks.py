from __future__ import annotations

import httpx
import pytest

from docfriction.checks import (
    BlockedHostError,
    check_links,
    find_placeholders,
    ip_literal,
    is_public_address,
    link_client,
    resolve_host,
    static_findings,
)
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
    assert untagged[0].detail.startswith("1 code block has no language tag")
    both = static_findings(make_segment(blocks=(CodeBlock("", "a"), CodeBlock("", "b"))))
    assert both[0].detail.startswith("2 code blocks have no language tag")
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

    with link_client(transport=httpx.MockTransport(handler), resolver=public) as client:
        findings = check_links(
            (
                "https://a.dev/ok",
                "https://a.dev/head-forbidden",
                "https://a.dev/gone",
                "https://a.dev/boom",
            ),
            client,
        )
    assert [f.check for f in findings] == ["dead_link", "dead_link"]
    assert "HTTP 404" in findings[0].detail
    assert "ConnectError" in findings[1].detail


def public(_host: str) -> tuple[str, ...]:
    return ("93.184.216.34",)


def test_check_links_with_no_urls_makes_no_requests():
    with link_client(resolver=public) as client:
        assert check_links((), client) == ()


def test_links_to_private_hosts_are_blocked_including_after_a_redirect():
    def resolver(host: str) -> tuple[str, ...]:
        return ("10.0.0.5",) if host == "intranet" else ("93.184.216.34",)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/bounce":
            return httpx.Response(302, headers={"location": "http://intranet/admin"})
        return httpx.Response(200)

    with link_client(transport=httpx.MockTransport(handler), resolver=resolver) as client:
        findings = check_links(
            (
                "http://169.254.169.254/latest/meta-data",
                "http://intranet/x",
                "https://a.dev/bounce",
                "ftp://a.dev/f",
            ),
            client,
        )
    assert [f.check for f in findings] == ["blocked_link"] * 4
    assert "private or internal" in findings[0].detail
    assert "unsupported scheme" in findings[3].detail


def test_private_hosts_can_be_allowed_explicitly():
    with link_client(
        transport=httpx.MockTransport(lambda _r: httpx.Response(200)),
        resolver=lambda _h: ("127.0.0.1",),
        allow_private_hosts=True,
    ) as client:
        assert check_links(("http://localhost:8000/docs",), client) == ()


@pytest.mark.parametrize(
    "address, public_expected",
    [
        ("8.8.8.8", True),
        ("2606:4700::1111", True),
        ("10.1.2.3", False),
        ("127.0.0.1", False),
        ("169.254.169.254", False),
        ("::1", False),
        ("0.0.0.0", False),
        ("224.0.0.1", False),
    ],
)
def test_is_public_address(address, public_expected):
    assert is_public_address(address) is public_expected


def test_ip_literals_are_checked_without_consulting_the_resolver():
    assert ip_literal("192.168.1.1") == ("192.168.1.1",)
    assert ip_literal("[::1]") == ("::1",)
    assert ip_literal("example.com") == ()


def test_resolve_host_rejects_unknown_names():
    with pytest.raises(BlockedHostError, match="does not resolve"):
        resolve_host("definitely-not-a-real-host.invalid")
