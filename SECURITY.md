# Security policy

## Supported versions

Only the latest release on the `main` branch receives fixes.

## Reporting a vulnerability

Please report security issues privately through
[GitHub's private vulnerability reporting](https://github.com/Cyvid7-Darus10/docfriction/security/advisories/new)
or by email to cyrus@pastelero.ph. Do not open a public issue.

You can expect an acknowledgement within a few days and a fix or a public
advisory once one is ready.

## What docfriction does with your data

- The text of each documentation section (prose, code blocks, detected
  placeholders, a summary of the previous section) is sent to the TypeSafe
  API at `https://api.typesafe.ai` so Jev can evaluate it. Do not run it on
  pages you are not allowed to share with a third party.
- Your API key is read from `TYPESAFE_API_KEY` and sent only in the
  `Authorization` header to that host (or to `TYPESAFE_BASE_URL` if you set
  it). It is never written to reports or logs.
- With `--check-links`, docfriction issues HEAD requests to every external
  URL found in the page, so the page author controls what gets requested.
  URLs whose host resolves to a private, loopback, link-local, multicast or
  reserved address are reported as `blocked_link` and never requested, and the
  same check runs on every redirect hop. `--allow-private-links` turns that
  off. The check resolves DNS once before the request, so a host that changes
  its answer between lookups (DNS rebinding) is not fully covered.
- Fetched pages are read up to 5 MB; larger responses are rejected.
- Jev answers are validated against the questions that were asked. A choice
  outside the offered options is treated as an API error rather than written
  into the report.
- Page content is untrusted input to Jev. Jev is not hardened against prompt
  injection, so a page can influence its own friction score. docfriction is a
  quality tool, not a security control.
