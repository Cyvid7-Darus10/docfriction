> Illustrative output. This report was produced by running docfriction against
> `tests/conftest.py`'s sample page with a simulated Jev response (the same
> fixture the test suite uses), so the numbers show the report shape, not a real
> Jev verdict. Run `docfriction <url>` with a `TYPESAFE_API_KEY` for the real thing.

# Friction log: Quickstart

Source: sample.md  
Generated: 2026-09-20T09:12:41+00:00 by docfriction, model `jev-1.13.0`  
Steps: 4 · steps with friction: 3 · max severity: 2.4/3 · Jev input tokens: 1,000 (about $0.0000)

## Summary

| # | Step | Sentiment | Severity | Friction |
|---|------|-----------|----------|----------|
| 1 | Quickstart | 😀 smooth | 0.2 | stub_section |
| 2 | Quickstart > Install | 😀 smooth | 0.2 | – |
| 3 | Quickstart > Configure | 🛑 blocked | 2.4 | missing_prerequisite (0.81), placeholders_explained (0.15), untagged_code_block, dead_link |
| 4 | Quickstart > Configure > Verify | 😀 smooth | 0.2 | stub_section |

## Walkthrough

### 1. Quickstart 😀 smooth (severity 0.2/3)

- ⚠️ **stub_section** (static) The heading has almost no content under it

### 2. Quickstart > Install 😀 smooth (severity 0.2/3)

- ✅ No friction detected

### 3. Quickstart > Configure 🛑 blocked (severity 2.4/3)

- ⚠️ **missing_prerequisite** (p=0.81, confidence=0.70, jev) The step needs a tool, account, permission, file, or value that neither this section nor the earlier context tells the reader how to obtain
- ⚠️ **placeholders_explained** (p=0.15, confidence=0.80, jev) A placeholder in the code is never explained in the text
- ⚠️ **untagged_code_block** (static) 1 code block(s) have no language tag, so readers cannot tell shell from config or output
- ⚠️ **dead_link** (static) https://example.com/keys returned HTTP 404

### 4. Quickstart > Configure > Verify 😀 smooth (severity 0.2/3)

- ⚠️ **stub_section** (static) The heading has almost no content under it
