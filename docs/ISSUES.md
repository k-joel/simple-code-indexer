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

### ISS-005: `Scope.LOCAL_ALIAS` keeps a pre-ADR-022 scope spelling alive

- **Symptom**: `Scope.LOCAL_ALIAS = "local"` exists only as a compatibility name; nothing in `src/`
  reads it, and `tests/acp_probe.py:187` is the last caller that passes the string `"local"`.
- **Where flagged**: 2026-11-27, sweep for deprecated surface after removing the bare env vars.
- **Cause**: `src/simple_code_indexer/harnesses/__init__.py:104` (constant) and `:228` (the
  `candidates` docstring claiming the alias is honoured). `candidates` at `:231` treats anything
  that is not `Scope.GLOBAL` as project scope, so the alias is not a separate code path — it is a
  dead name plus a promise the function does not specifically keep.
- **Suggested fix**: drop `LOCAL_ALIAS`, change `tests/acp_probe.py:187` to
  `spec.candidates(Scope.PROJECT, …)`, and simplify the `candidates` docstring to name only
  `global`/`project`; then re-run `uv run pytest tests/test_harnesses.py tests/test_acp_probe.py`.

### ISS-006: `env.flag_default` is unused, and `RUNTIME_ENV` is a deprecated read path

- **Symptom**: `simple_code_indexer/env.py:42` `flag_default()` has no caller, and
  `harnesses.RUNTIME_ENV` (`SIMPLE_CI_HARNESS`) is read at
  `harnesses/__init__.py:346` although `--harness` replaced it (ADR-024) — the fallback survives
  only so pre-ADR-024 entries keep resolving.
- **Where flagged**: 2026-11-27, sweep for deprecated surface after removing the bare env vars.
- **Cause**: `flag_default` was added with the env seam and never used; the `RUNTIME_ENV` read is
  the deliberate compatibility path described in ADR-024, and four tests in
  `tests/test_harnesses.py` (`:790`, `:806`, `:828`, `:858`) exercise it.
- **Suggested fix**: delete `flag_default`. Decide `RUNTIME_ENV` explicitly: either keep it and say
  so in ADR-024's consequences as a permanent debug surface, or delete the read together with those
  four tests once no pre-ADR-024 entry is expected to exist.

### ISS-007: Re-added Cline plugin contradicts the removal note, and its path is unverified

- **Symptom**: `harnesses/cline.py` ships a Cline entry again, while `docs/NOTES.md:164` still says
  the Cline builtin was deleted on 2026-11-08 because `~/.cline/data/settings/cline_mcp_settings.json`
  vanished after the Cline desktop app restarted and Cline never listed the server.
- **Where flagged**: 2026-11-27, re-adding Hermes/OpenClaw/Kilo/Cline and sweeping for deprecated
  surface.
- **Cause**: `src/simple_code_indexer/harnesses/cline.py` was rewritten against the docs
  (`docs.cline.bot/cli/cli-reference`), not against a live Cline build; the added
  `cli_add`/`cli_remove` (`cline mcp add/remove`) and the four `GLOBAL_CONFIGS` paths have never
  been exercised end to end, and the NOTES removal rationale was not retracted.
- **Suggested fix**: verify on a current Cline build that `cline mcp add <name> --yes -- <command>`
  survives a restart and appears in the UI; then replace the NOTES:164 bullet with the verified
  lifecycle (or drop the plugin again if it does not hold).

### ISS-008: `SIMPLE_CI_HARNESS` is documented in entry-format references that the wizard no longer writes

- **Symptom**: `references/mcp-test-process.md:46`, `references/acp-test-process.md:38` and
  `references/opencode-acp-mode.md:282` describe `SIMPLE_CI_GIT_PULL` as deleted by ADR-019 but say
  nothing about `SIMPLE_CI_HARNESS` no longer being written, so a reader following those references
  hand-writes the old env marker into an entry.
- **Where flagged**: 2026-11-27, sweep for deprecated surface after removing the bare env vars.
- **Cause**: those three `references/` files predate ADR-024, which moved the marker to
  `serve --harness <NAME>`; they are not covered by the harness README that was updated.
- **Suggested fix**: add one line to each reference's entry-format section naming
  `serve --harness <NAME>` as the current marker (and `SIMPLE_CI_HARNESS` as debug-only), then grep
  `references/` for `SIMPLE_CI_HARNESS` to confirm none describe it as required.

### ISS-009: The wizard still migrates a project-local `config.yaml` (ADR-011 leftovers)

- **Symptom**: every `setup` run can print `Found a legacy project config: …
  .simple-ci/config.yaml` and offer to merge it into the global file — a prompt for a file the
  server has not read since ADR-011 made config global-only.
- **Where flagged**: 2026-11-27, sweep for legacy migration code to retire.
- **Cause**: `src/simple_code_indexer/setup_wizard/__init__.py:406` `_step_migrate_local_config`
  (called at `:224`), which depends on `configfile.merge_configs`
  (`src/simple_code_indexer/configfile.py:72`) — a public wrapper whose only caller is that step
  (`setup_wizard/__init__.py:432`). Covered by `tests/test_setup_wizard.py:1098`.
- **Suggested fix**: delete `_step_migrate_local_config` and its call in `run()`, plus the
  `merge_configs` wrapper (keep `_deep_merge`, still used by `load_layered_config`) and the
  `docs/ARCH.md:1296` / `NOTES.md:139` / `GLOSSARY.md:192` migration mentions; drop the test.

### ISS-010: The `qdrant:` section still selects the Qdrant backend implicitly

- **Symptom**: a config with a non-empty `qdrant:` block and no `vector_store` key silently resolves
  to the Qdrant backend, so a leftover block from the pre-ADR-017 era changes which store is used
  with no explicit setting anywhere.
- **Where flagged**: 2026-11-27, sweep for legacy migration code to retire.
- **Cause**: `src/simple_code_indexer/config.py:346` (`return "qdrant" if qdrant else "sqlite-vec"`
  in `_vector_store`, docstring at `:335`), mirrored for the wizard's display by
  `_vector_store_from_raw`. Three tests pin the behaviour: `tests/test_config.py:427`, `:438`, `:443`.
- **Suggested fix**: default to `sqlite-vec` unconditionally when neither `SIMPLE_CI_VECTOR_STORE`
  nor `vector_store` is set, delete the three tests, and update the ARCH §6.4 table note.

### ISS-011: A pre-`vector_backend` database is still inferred to be Qdrant-bound

- **Symptom**: an index DB with no `vector_backend` meta row but with Qdrant keys present is treated
  as Qdrant-bound, so such a DB can be accepted as "unchanged" instead of being invalidated and
  re-embedded.
- **Where flagged**: 2026-11-27, sweep for legacy migration code to retire.
- **Cause**: `src/simple_code_indexer/db.py:481-487` infers `stored_backend = "qdrant"` from the
  presence of `_QDRANT_URL_KEY`/`_COLLECTION_KEY`, and `:490` then backfills the explicit binding —
  a compatibility path that only matters for DBs written before `vector_backend` existed (docstring
  at `:473-474`).
- **Suggested fix**: drop the inference so a missing `vector_backend` counts as "different" and
  invalidates (the existing rule already handles a real mismatch), then delete the note in
  `tests/test_db.py:330` and re-run `uv run pytest tests/test_db.py`.

### ISS-012: A pre-0.1 `~/.simple-ci/models` rename runs on every setup, though nothing released before 0.1

- **Symptom**: `setup` can print `Found …\.simple-ci\models. Move it to …\.simple-ci\model?` and
  `os.replace` the directory — a migration for a layout that only ever existed in this checkout's
  own development history.
- **Where flagged**: 2026-11-27, sweep for legacy migration code to retire.
- **Cause**: `src/simple_code_indexer/setup_wizard/__init__.py:391` `_step_migrate_global_assets`
  (called at `:223`), whose docstring says it renames the "pre-0.1" directory. `pyproject.toml` is
  `version = "0.1.0"` and `docs/CHANGELOG.md` has no released section, so no published version ever
  wrote `models/`; covered by `tests/test_setup_wizard.py:1782`.
- **Suggested fix**: delete the step and its call, then re-run `uv run pytest tests/test_setup_wizard.py`
  and confirm no fixture depends on the moved directory. Keep the step only if a 0.1.0 wheel is
  published before this is resolved.
