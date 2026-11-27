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
- ID scheme: `ISS-NNN` using the next free positive integer (`max open n + 1`,
  or `1` if none exist). Never reuse an ID referenced in open work.
- Entry order: Ascending `ISS-NNN` under `## Open`.
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
  the next `ISS-NNN`.
- Reference & link: Refer to entries by `ISS-NNN` in commits or PRs (do not
  use GitHub `#<n>` syntax).
- Close by deleting: Local-markdown entries do NOT auto-close on PR merge.
  Delete the entire `### ISS-NNN` heading and its bullets once fixed (either
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

    ### ISS-NNN: <short, specific summary>

    - **Symptom**: `<command or action>` fails with `<brief observed error>`.
    - **Where flagged**: YYYY-MM-DD, <task or check where discovered>.
    - **Cause**: `<path/to/file>:<line>` <concise explanation of defect>.
    - **Suggested fix**: <exact command or minimal change>, then re-run
      `<verification command>`.
-->

---

## Open

### ISS-003: `test_daemon_registers_then_exits_after_grace` is timing-flaky in a full run

- **Symptom**: `uv run pytest` occasionally fails that one test (its `_wait_until` for the ready
  file or the lease release times out at 20 s) while `pytest tests/test_sidecar_daemon.py` passes
  every time — observed twice on 2026-11-27, both under a full-suite run.
- **Where flagged**: 2026-11-27, full-suite gates while changing harness detection and env vars.
- **Cause**: `tests/test_sidecar_daemon.py:147` budgets 20 s for a spawned daemon to take the lease,
  start its runtime and exit after a 1 s grace; under full-suite load the spawn plus interpreter
  start consumes most of that window, so the deadline is too tight rather than the daemon misbehaving.
- **Suggested fix**: raise the two `_wait_until` timeouts (and the `_start` deadline) or drive them
  from a shared constant, then run the full suite a few times in a row to confirm.

### ISS-004: OpenClaw's shipped CLI has no MCP support, so its plugin can only merge

- **Symptom**: `openclaw mcp status` fails with "unknown command 'mcp'", and
  `openclaw config set mcp.servers.<name> <json> --strict-json` writes the value and then exits 1
  with `<root>: Unrecognized key: "mcp"` — `mcpServers` and `servers` are rejected the same way.
  The wizard therefore reports `openclaw could not add the server` and falls back to the merge.
- **Where flagged**: 2026-11-27, adding the OpenClaw harness plugin and running a real setup.
- **Cause**: the installed build (`openclaw` 2026.2.26, `bc50708`) predates the MCP surface the docs
  describe (`docs.openclaw.ai/cli/mcp`, `…/gateway/config-extensions`); its config schema accepts no
  MCP key at all, so `harnesses/openclaw.py` deliberately declares no `cli_add` and the merge writes
  a block this build will not load.
- **Suggested fix**: re-check on a release that ships `openclaw mcp`; if the config schema then
  accepts `mcp.servers`, add `cli_add`/`cli_remove` (`openclaw mcp set <name> <json>` /
  `openclaw mcp unset <name>`) to `harnesses/openclaw.py`, extend
  `tests/test_harnesses.py::test_cli_adapters_build_the_documented_argv`, and re-run
  `simple-code-indexer setup --harnesses openclaw`.
