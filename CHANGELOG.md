# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed

- Sentiment label `pause` is now `hesitant`, so all four reader states are
  adjectives. Reports and the JSON `sentiment` field change accordingly.
- Error messages say what to do next: a missing key points at typesafe.ai, a
  401 points at `TYPESAFE_API_KEY`, an oversized page suggests saving it
  locally, and the `--fail-on-severity` message names the failing step.
- Counts are pluralised properly ("1 code block has", "2 code blocks have").

## [0.1.0] - 2026-09-20

### Added

- `docfriction` CLI: fetch a docs page by URL or path, split it into
  heading-level steps, evaluate each step with a batched Jev rubric, and render
  a Markdown or JSON friction log.
- Rubric: friction type (choice), severity (score), and yes/no checks for
  prerequisites, expected result, terms, code/prose match, and placeholders.
- Deterministic checks: dead links (`--check-links`), untagged code blocks,
  stub sections, placeholder detection.
- `--fail-on-severity` CI gate, `--dry-run`, `--max-sections`, `--concurrency`,
  `--model`.
- Thin Jev HTTP client with exponential backoff on 429/529; answers are
  validated against the questions asked.
- Link checks refuse private, loopback and link-local addresses on every
  redirect hop unless `--allow-private-links` is set; fetched pages are capped
  at 5 MB.
- Segmenter handles setext headings, indented code blocks, nested fences of
  different lengths, YAML front matter and HTML comments, and strips anchor
  links and escapes from headings.
- Example GitHub Actions workflow and research notes on Jev.

[Unreleased]: https://github.com/Cyvid7-Darus10/docfriction/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Cyvid7-Darus10/docfriction/releases/tag/v0.1.0
