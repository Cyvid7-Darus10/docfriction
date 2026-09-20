"""Command-line entry point: docfriction <url-or-file> [options]."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ._version import __version__
from .evaluate import EvaluateOptions, evaluate_document
from .fetch import FetchError, load_document
from .jev import DEFAULT_MODEL, JevClient, JevError
from .report import render_json, render_markdown
from .segment import segment_markdown

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_THRESHOLD = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="docfriction",
        description="Write a friction log for a documentation page, scored step by step with Jev.",
    )
    parser.add_argument("source", help="URL of a docs page, or a local .md/.html file")
    parser.add_argument("-o", "--out", type=Path, help="write the report here instead of stdout")
    parser.add_argument("-f", "--format", choices=("md", "json"), default="md")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Jev model id (default: jev-latest)")
    parser.add_argument("--check-links", action="store_true", help="also HEAD every external link")
    parser.add_argument(
        "--allow-private-links",
        action="store_true",
        help="let --check-links request private, loopback, and link-local addresses",
    )
    parser.add_argument("--max-sections", type=int, help="only evaluate the first N sections")
    parser.add_argument("--concurrency", type=int, default=4, help="parallel Jev calls")
    parser.add_argument(
        "--fail-on-severity",
        type=float,
        metavar="N",
        help="exit 2 if any step's severity is at least N on the 0-3 scale",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the detected steps and exit without calling Jev (no API key needed)",
    )
    parser.add_argument("--version", action="version", version=f"docfriction {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        document = load_document(args.source)
    except FetchError as exc:
        return _fail(str(exc))
    if args.dry_run:
        return _dry_run(document.markdown, document.title, args.max_sections)
    options = EvaluateOptions(
        check_links=args.check_links,
        allow_private_links=args.allow_private_links,
        max_sections=args.max_sections,
        concurrency=args.concurrency,
    )
    try:
        with JevClient(model=args.model) as client:
            log = evaluate_document(document, client, options)
    except JevError as exc:
        return _fail(str(exc))
    report = render_json(log) if args.format == "json" else render_markdown(log)
    _emit(report, args.out)
    if args.fail_on_severity is not None and log.max_severity >= args.fail_on_severity:
        print(
            f"docfriction: max severity {log.max_severity:.2f} >= {args.fail_on_severity}",
            file=sys.stderr,
        )
        return EXIT_THRESHOLD
    return EXIT_OK


def _dry_run(markdown: str, title: str, max_sections: int | None) -> int:
    segments = segment_markdown(markdown)[:max_sections]
    print(f"{title}: {len(segments)} step(s)")
    for segment in segments:
        code = f", {len(segment.code_blocks)} code block(s)" if segment.has_code else ""
        print(f"  {segment.index + 1}. {segment.title} ({len(segment.prose)} chars{code})")
    return EXIT_OK


def _emit(report: str, out: Path | None) -> None:
    if out is None:
        sys.stdout.write(report)
        return
    out.write_text(report, encoding="utf-8")
    print(f"docfriction: wrote {out}", file=sys.stderr)


def _fail(message: str) -> int:
    print(f"docfriction: {message}", file=sys.stderr)
    return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
