"""Deterministic checks that need no model. Jev is weak at counting and pattern
matching, so anything a regex or an HTTP request can answer is done here."""

from __future__ import annotations

import ipaddress
import re
import socket
from collections.abc import Callable

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
ALLOWED_LINK_SCHEMES = frozenset({"http", "https"})
USER_AGENT = f"docfriction/{__version__} (+https://github.com/Cyvid7-Darus10/docfriction)"

Resolver = Callable[[str], tuple[str, ...]]


class BlockedHostError(httpx.RequestError):
    """Raised by the link client when a URL points at a private or internal address."""


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


def ip_literal(host: str) -> tuple[str, ...]:
    """The host itself if it is an IP address (IPv6 brackets stripped), else empty."""
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return ()
    return (host.strip("[]"),)


def resolve_host(host: str) -> tuple[str, ...]:
    """All addresses a hostname resolves to via DNS."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise BlockedHostError(f"{host} does not resolve") from exc
    return tuple(dict.fromkeys(str(info[4][0]) for info in infos))


def is_public_address(address: str) -> bool:
    parsed = ipaddress.ip_address(address)
    return not (
        parsed.is_private
        or parsed.is_loopback
        or parsed.is_link_local
        or parsed.is_multicast
        or parsed.is_reserved
        or parsed.is_unspecified
    )


def link_client(
    *,
    transport: httpx.BaseTransport | None = None,
    timeout: float = DEFAULT_LINK_TIMEOUT_SECONDS,
    allow_private_hosts: bool = False,
    resolver: Resolver = resolve_host,
) -> httpx.Client:
    """One shared client for link checks. The request hook runs on every redirect hop,
    so a public URL cannot bounce the checker into a private network."""

    def guard(request: httpx.Request) -> None:
        if request.url.scheme not in ALLOWED_LINK_SCHEMES:
            raise BlockedHostError(f"{request.url} uses an unsupported scheme")
        if allow_private_hosts:
            return
        host = request.url.host
        addresses = ip_literal(host) or resolver(host)
        if not all(is_public_address(address) for address in addresses):
            raise BlockedHostError(f"{request.url} points at a private or internal address")

    return httpx.Client(
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
        transport=transport,
        event_hooks={"request": [guard]},
    )


def check_links(urls: tuple[str, ...], client: httpx.Client) -> tuple[Finding, ...]:
    results = (_check_link(client, url) for url in urls)
    return tuple(finding for finding in results if finding is not None)


def _check_link(client: httpx.Client, url: str) -> Finding | None:
    try:
        response = client.head(url)
        if response.status_code in DEAD_LINK_RETRY_STATUSES:
            # Some hosts reject HEAD; fetch headers only, never the body.
            with client.stream("GET", url) as streamed:
                response = streamed
    except BlockedHostError as exc:
        return Finding(check="blocked_link", source=STATIC_SOURCE, detail=str(exc))
    except httpx.HTTPError as exc:
        return _dead_link(f"{url} could not be reached ({type(exc).__name__})")
    if response.status_code >= 400:
        return _dead_link(f"{url} returned HTTP {response.status_code}")
    return None


def _dead_link(detail: str) -> Finding:
    return Finding(check="dead_link", source=STATIC_SOURCE, detail=detail)
