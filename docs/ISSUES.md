# Issues

Ongoing issue tracker for open bugs, defects, and gaps found while working on
this repository — by humans or by LLM sessions.

<!--
ISSUES.md MAINTENANCE GUIDE (FOR AGENTS & CONTRIBUTORS)

PURPOSE & SCOPE
- Role: Single local-markdown tracker of currently OPEN bugs, defects, and
  actionable codebase, test, tooling, or documentation gaps.
- Audience: Humans and LLM agents working in this repository.
- Not for: Operational gotchas or non-defect notes (put those in NOTES.md),
  feature brainstorms/specs, or an archive of resolved issues.

UPDATE TRIGGERS
- Add an entry whenever a bug, defect, or gap is flagged during a session —
  however small, and even if only mentioned in passing in a summary.
- Update an existing entry in place if its cause or fix changes while open.
- Delete an entry immediately once its fix is completed and verified.
- Check this file before ending a session if any defect was found or fixed.

INCLUSION / EXCLUSION CRITERIA
- Include: Verified or directly observed defects, failing checks, and gaps.
- Exclude:
  - Operational gotchas and non-defect tips (move to NOTES.md).
  - Fixed or obsolete issues (delete rather than marking done).
  - Unverified guesses (inspect relevant files before recording).

STRUCTURE & FORMATTING
- Top-level sections: `# Issues`, short preamble, this guide, then `## Open`.
- Always keep `## Open` present, even when empty (leave no entries beneath it).
  Never create a `## Closed` or `## Resolved` section.
- ID scheme: `ISS-<n>` using the next free positive integer (`max open n + 1`,
  or `1` if none exist). Never reuse an ID referenced in open work.
- Entry order: Ascending `ISS-<n>` under `## Open`.
- Required fields per entry (exact order, four bullets):
  - `Symptom`: Observable error, failing command, or broken behavior.
  - `Where flagged`: `YYYY-MM-DD, <session or task context>`.
  - `Cause`: Backticked `path/to/file:line` and concise root cause
    (write `Unknown (not yet inspected)` only if uninvestigated).
  - `Suggested fix`: Concrete command, code change, or doc update.
- Formatting: Use ISO dates (`YYYY-MM-DD`) and backticks for file paths,
  line references (`file:line`), commands, and symbols.

QUALITY & STYLE RULES
- Be brief, factual, and direct; keep each bullet to 1–2 short sentences.
- Inspect `docs/ISSUES.md` and the affected files before editing. Never guess
  `file:line` locations, symptoms, or fixes.
- Make surgical edits only: preserve unrelated open entries verbatim.

LIFECYCLE & WORKFLOW
- Read first: Check existing `## Open` entries to avoid duplicates and compute
  the next `ISS-<n>`.
- Reference & link: Refer to entries by `ISS-<n>` in commits or PRs (do not
  use GitHub `#<n>` syntax).
- Close by deleting: Local-markdown entries do NOT auto-close on PR merge.
  Delete the entire `### ISS-<n>` heading and its bullets once fixed (either
  in the fixing commit/PR or manually afterward).
- Verify: Re-read the diff after editing to confirm schema compliance and
  that no unrelated lines changed.

ANTI-PATTERNS
- Marking an entry done, struck through, or moved to `## Closed` instead of
  deleting it.
- Logging operational gotchas or workarounds here instead of `NOTES.md`.
- Assuming GitHub tracker behavior (`#<n>` references or PR auto-closing).
- Omitting required bullets, writing long narratives, or guessing `file:line`.
- Reordering or reformatting existing open entries without cause.

EXAMPLE LAYOUT (4-SPACE INDENTED)
    ## Open

    ### ISS-<n>: <short, specific summary>

    - **Symptom**: `<command or action>` fails with `<brief observed error>`.
    - **Where flagged**: YYYY-MM-DD, <task or check where discovered>.
    - **Cause**: `<path/to/file>:<line>` <concise explanation of defect>.
    - **Suggested fix**: <exact command or minimal change>, then re-run
      `<verification command>`.
-->

---

## Open

### ISS-12: `ruff format --check` fails on two committed files

- **Symptom**: `uv run ruff format --check .` reports `2 files would be reformatted`.
- **Where flagged**: 2026-11-15, while running the quality gate before adding `docs/RUNBOOK.md`.
- **Cause**: `src/simple_code_indexer/setup_wizard/__init__.py:1337` and
  `tests/test_setup_wizard.py:1124`, `:1170`, `:1213` are committed without `ruff format`.
- **Suggested fix**: run
  `uv run ruff format src/simple_code_indexer/setup_wizard/__init__.py tests/test_setup_wizard.py`,
  then re-run `uv run ruff format --check .` and the quality gate.

