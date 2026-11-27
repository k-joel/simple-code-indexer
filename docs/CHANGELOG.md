# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<!--
CHANGELOG.md MAINTENANCE GUIDE (FOR AGENTS & CONTRIBUTORS)

PURPOSE & SCOPE
- Curated, reverse-chronological record of notable, user-visible changes per version.
- Audience: human end users, operators, and developers evaluating upgrades or diagnosing
  regressions—not a git commit dump or internal engineering diary.
- Portable source of truth: reuse release sections from this file for GitHub Releases.

UPDATE TRIGGERS
- Update `## [Unreleased]` in the same task/session whenever you add a user-visible feature,
  change existing behavior/API/CLI/config/defaults, deprecate or remove functionality, fix a
  user-facing bug, or patch a security vulnerability.
- Update on release: promote `## [Unreleased]` to a versioned section and open a new
  `## [Unreleased]` section above it.
- Update post-release only to mark a pulled release `[YANKED]`, record a missed release or
  breaking change, or fix typos/broken links.
- Before ending a session that altered user-facing behavior, verify `## [Unreleased]`
  captures every qualifying change.

INCLUSION / EXCLUSION CRITERIA
- Include: Every notable user-visible change (features, behavior changes, deprecations,
  removals, bug fixes, security fixes). Consistency is mandatory—an incomplete changelog
  misleads users relying on it as the source of truth.
- Exclude: Whitespace/formatting edits, pure internal refactors with no behavior change, merge
  commits, work-in-progress steps, routine CI tweaks, and raw `git log` entries.

STRUCTURE & FORMATTING
- Section order: `## [Unreleased]` at the top, followed by releases newest-first
  (`## [X.Y.Z] - YYYY-MM-DD`). Never skip a released version.
- Dates & Versions: Strict ISO 8601 dates (`YYYY-MM-DD`) and SemVer (`MAJOR.MINOR.PATCH`:
  breaking / backward-compatible feature / backward-compatible fix). Append `[YANKED]` to
  pulled releases (`## [X.Y.Z] - YYYY-MM-DD [YANKED]`).
- Categories: Under `## [Unreleased]` and each release, group bullets strictly under these
  six `###` headings in order, omitting any empty category:
    - `Added`      (new features)
    - `Changed`    (changes to existing functionality)
    - `Deprecated` (soon-to-be-removed features)
    - `Removed`    (now-removed features)
    - `Fixed`      (bug fixes)
    - `Security`   (vulnerability fixes and security-relevant changes)
- Reference links: Keep reference-style links at the bottom of the file so every heading
  links to its comparison diff or tag (`[unreleased]` -> `vLATEST...HEAD`, `[X.Y.Z]` ->
  `vPREV...vX.Y.Z`, initial `[X.Y.Z]` -> `releases/tag/vX.Y.Z`).

QUALITY & STYLE RULES
- Describe user-visible impact, not internal implementation; name the specific feature,
  endpoint, flag, setting, or behavior affected.
- Keep bullets concise (1-2 lines), match audience tone, maintain consistent tense across
  entries, and end every bullet with a period.
- Evidence rule: Document only changes actually implemented and verified in the code/diff;
  never record speculative, planned, or unverified work.
- Link to the relevant issue, PR, commit, or ADR where helpful (and credit contributors if
  appropriate).
- Good: `- Login timeout on mobile caused by premature token expiry. ([#456](https://github.com/org/repo/issues/456))`
- Bad:  `- Refactored session handler.` or `- Various bug fixes and improvements.`

LIFECYCLE & WORKFLOW
- Ongoing edits: Add entries to `## [Unreleased]` as changes land, not only at release time.
- Deprecations & Breaking Changes: Deprecate in an earlier release before removing so users
  have a safe upgrade path. Prefix breaking changes and removals with `**BREAKING:**`, state
  the replacement, migration path, and deadline, and pair with a `MAJOR` version bump.
- Release-day workflow:
  1. Confirm `## [Unreleased]` captures all notable changes since the last release.
  2. Choose next `X.Y.Z` per SemVer.
  3. Rename `## [Unreleased]` to `## [X.Y.Z] - YYYY-MM-DD`.
  4. Insert a fresh empty `## [Unreleased]` section directly above it.
  5. Update bottom reference links (`[unreleased]` -> `vX.Y.Z...HEAD`; add `[X.Y.Z]`).
  6. Review wording, `**BREAKING:**` prominence, and links before tagging.
- Yanks & Corrections: Never silently delete a pulled release—keep it and append `[YANKED]`.
  Only rewrite past releases to add missed releases/breaking changes, fix typos, or repair
  broken links; never erase history.

ANTI-PATTERNS
- Dumping `git log` / raw commit messages or vague bullets ("bug fixes", "improvements").
- Ambiguous regional dates (`03/04/26`), empty `###` headings, skipped versions, or mixed
  formatting/tenses across releases.
- Silent breaking changes/removals without deprecation notice or migration instructions.
- Silently deleting yanked releases or selectively omitting notable changes.

EXAMPLE LAYOUT (4-SPACE INDENTED)

    ## [Unreleased]

    ### Added

    - User profile export in JSON format via `/v2/export`. ([#489](https://github.com/org/repo/pull/489))

    ## [2.0.0] - 2026-03-15

    ### Removed

    - **BREAKING:** Legacy `/v1/export` endpoint. Migrate to `/v2/export`.

    ### Fixed

    - Login timeout on mobile devices during token refresh. ([#456](https://github.com/org/repo/issues/456))

    ## [1.0.1] - 2026-02-01 [YANKED]

    ### Security

    - Patched token validation bypass in OAuth callback.

    [unreleased]: https://github.com/org/repo/compare/v2.0.0...HEAD
    [2.0.0]: https://github.com/org/repo/compare/v1.0.1...v2.0.0
    [1.0.1]: https://github.com/org/repo/compare/v1.0.0...v1.0.1
    [1.0.0]: https://github.com/org/repo/releases/tag/v1.0.0
-->

---

## [Unreleased]

### Added

- **Harness entries can now be installed per project, not just globally** (ADR-022). `setup` asks
  for a scope after the harness selection: `global` (the default, and mandatory when run from the
  home directory) or `project`, which writes the client's own project config — `.mcp.json`,
  `.cursor/mcp.json`, `opencode.json`, `.vscode/mcp.json`, `.codex/config.toml`, and so on — and pins
  it with `serve --workspace <dir>`. Global entries stay workspace-free, as before.
- `serve --workspace <dir>` sets the workspace explicitly, beating MCP roots and the
  harness-published workspace and losing only to `WORKSPACE_ROOT`; `get_status.workspace_source`
  reports `arg`. It is also treated as an opt-in for the implausible-directory refusal, like
  `WORKSPACE_ROOT`.
- `setup --harness-scope {global,project}` and `--gitignore` / `--no-gitignore` skip the two new
  prompts, so a project install can be scripted.
- A project install offers to add its config file and `.simple-ci/` to `.gitignore` (only inside a
  git repository, and never duplicating an entry that already covers them).
- **Entries are written by each client's own `mcp add` when it has one** — `cmdc mcp add-json`,
  `claude mcp add`, `gemini mcp add`, `opencode mcp add`, `pi mcp add`, `codex mcp add`, and
  `cursor --add-mcp` — falling back to the wizard's config merge when the CLI is absent, does not
  support the scope, or fails. All per-client flag knowledge lives in that client's `harnesses/*.py`
  plugin. On Windows the ladder runs the path `shutil.which` resolved and routes `.cmd`/`.bat` shims
  through `cmd /c`, so shim-based clients (Cursor, VS Code, npm CLIs) actually run instead of
  silently falling back.
- Cursor: its CLI is used for the global scope and the wizard records the file it really writes,
  `%APPDATA%\Cursor\User\settings.json` under `mcp.servers` (verified on 3.31.15, which has no
  `mcp remove` and rejects `--mcp-workspace`). That settings file is deliberately kept out of the
  merge targets, because merging `mcpServers` into it would corrupt Cursor's editor settings.
- Zed: `BINARIES`/`CLI_BINARIES` are now empty because `zed` on `PATH` is commonly authzed's SpiceDB
  CLI, not the editor; detection relies on the config directory. Its Windows settings location
  (`%APPDATA%\Zed\settings.json`) now wins over the XDG path when no file exists yet.
- `enabled: true` is now written for Pi and Codex (Codex through a new `ENABLED` plugin flag, since
  its marker-block TOML writer bypasses `entry()`), matching Goose/MiMo/Command Code. Clients that
  do not document the key — OpenCode, VS Code, Cursor, Zed, Gemini CLI, Claude Code, Claude Desktop,
  Windsurf — still get none.
- MiMoCode's project config now prefers an existing `.mimocode/mimocode.jsonc`, and OpenCode's
  project config also considers `.opencode/opencode.json(c)`; Windsurf/Devin gets its gitignored
  `.devin/mcp_config.local.json` as a fallback.
- `setup.harnesses` records `scope` and `workspace` per entry, so `--install-only` repoints the same
  file with the same pin and a deselected harness is removed from the scope it was written in.

### Changed

- `setup` asks the periodic-sweep question (and its interval) as part of the global settings,
  directly after the embedding model and vector store, instead of after the harness selection.
  The prompt order is now: embedding model → vector store → sweep → harness entries
  (global or project) → `.gitignore` (project scope only).
- **`symbol_lookup` now works for 167 of the 322 indexable languages, up from 29** (ADR-020).
  Symbol maps are derived at catalog-generation time from each grammar's own tags query
  (`get_tags_query`), which names the real declaration node types; grammars that ship no tags query
  fall back to a shape heuristic over their node kinds, and a hand-verified map covers the ones
  neither reaches. Zig, Nim, Terraform, Nix, V, Odin, Gleam, CSS, SQL, Proto, Verilog, Haskell, R,
  Elixir, Clojure, and the rest now resolve a real name instead of indexing no symbols.
- `LanguageSpec.symbol_nodes` values accept a `<kind>@<field>` form, which requires the node to have
  that field. It exists for grammars that reuse one node type for a declaration and a look-alike —
  Haskell's `function` is both a definition (`name:`) and a type arrow (`result:`).
- New extractors for grammars whose declarations the generic walker cannot reach: `extract_hcl`
  (block labels — `resource "aws_instance" "web"` becomes `aws_instance.web`), `extract_cmake`
  (`function()`/`macro()` names live in `argument_list`), `extract_sexpr_definitions` (Lisp forms
  selected by head symbol), `extract_elixir` (a `call` whose target is a `def*` keyword), and
  `extract_r_assignment` (`name <- function(...)`, named through the enclosing assignment).
- `catalog.SYMBOL_GAPS` lists the languages that genuinely cannot resolve a symbol, and
  `get_status.languages_without_symbol_maps` reports its size.
- The pack's `process(symbols=True)` extractor is now enabled alongside `structure`; it sees
  declarations the structure pass misses (Go `type` specs, Lua globals).
- **`symbol_lookup` now resolves declarations inside embedded blocks** for Vue, Svelte, Astro, Heex,
  Blade, and Templ (ADR-021). Each host's own injections query is run, the captured region is parsed
  with the embedded grammar, and its symbols are reported at their line in the host file — so a
  function in a `<script setup lang="ts">` block, a `def` in a Heex `<% %>` directive, or a `function`
  in a Blade `@php` block is now findable. Typed script blocks are parsed as TypeScript, so
  `interface`, `enum`, and generic declarations are indexed rather than dropped.
- Twig and Jinja templates now resolve `{% macro %}` and `{% block %}` names, and Templ resolves its
  `templ`, `script`, and `css` declarations. Symbol-mapped languages go 167 → 174 and
  `catalog.SYMBOL_GAPS` 155 → 148.

### Changed

- **A symbol-map upgrade now re-parses the index once without re-embedding.** `catalog.VERSION`
  drives a destructive reconcile, so it cannot be used for a map change; `SYMBOL_MAP_VERSION` stamps
  `meta.symbol_map_version` instead and `indexer.backfill_symbols` rewrites only the `symbols` table.
  Chunking, embeddings, and the vector store are untouched, so an upgrade costs one parse per file.
- Grammar prefetch is now a fixed 44-language set in `catalog.PREFETCH` rather than "every
  symbol-mapped grammar". With a map for most of the catalog the old rule would have downloaded the
  whole pack on first run; a language outside the set still extracts symbols and loads its grammar
  on first index.
- The Make-style `signature` for a node with no `body` field now stops at the declaration line
  instead of returning the whole node, so Zig's `FnProto` and similar no longer include the body.

### Fixed

- `--install-only` can no longer repoint a harness entry at an interpreter that does not exist.
  The repin read the recorded harnesses from `~/.simple-ci/config.yaml` directly instead of
  honouring `SIMPLE_CI_CONFIG`, so a run under a redirected (or fake) `uv tool dir` wrote that
  path into real client configs; the entry then failed to spawn with no visible error. The record
  is now read through the documented config resolution, and a missing
  `<tool-env>/Scripts/pythonw.exe` is reported as a failure with the entries left untouched.
- `uvx simple-code-indexer uninstall` on Windows no longer fails with
  `Access is denied (os error 5)` while deleting the tool environment it is itself executing from.
  It now detects the self-hosted case, removes everything else (entries, config, compose services,
  model cache), leaves the environment intact, and prints `uv tool uninstall simple-code-indexer`
  to run once the process exits; POSIX still removes the environment in-process.
- `uvx simple-code-indexer setup` no longer fails with `Access is denied (os error 5)` or
  `being used by another process (os error 32)` on Windows. uvx runs the setup from inside the
  tool environment it was about to reinstall, and Windows will not let uv overwrite the
  `simple-code-indexer.exe` / `python.exe` that are executing. A run that is itself serving from
  that environment now skips the reinstall when the receipt already matches (an editable link to
  the same checkout, or the pinned version) and otherwise reports the `uv tool install` command
  to run from outside. Reinstalls from outside no longer pass `--force`, which also failed
  whenever a harness's reader was live; they replace the package in place and still flip
  editable↔wheel in the one environment the harness entries point at.
- `symbol_lookup` no longer returns a language keyword as a symbol name. Grammars that declare
  through a nested node (protobuf's `message`), a selector list (CSS `rule_set`), or a head symbol
  (Clojure `defn`) resolved to the keyword itself before.
- Setup and the harness loader no longer adopt a source checkout they are not running from. A
  `site-packages` install nested inside some other project that happens to hold a
  `src/simple_code_indexer/` tree made the wizard link that project and the loader read its
  `harnesses/` drop-ins; both now require the tree that contains the running module.
- `docs/`-adjacent process guidance for the ACP end-to-end run now says the harness identity is
  asserted from `harness lookup: chain=…` / `reader session … harness=<image>(<pid>)` in
  `reader.log`, instead of the `parent watchdog: watching …` line, which only ever reaches stderr
  (`references/acp-test-process.md` §7.1). It also documents stopping `opencode-cli serve --service`
  before the run, because a freshly written global entry is picked up by that always-on process and
  makes `get_status.sessions` read 2.

### Changed (install model)

- **The project is now published to PyPI and installed with `uv tool install`** (ADR-019).
  `uvx simple-code-indexer setup` installs a version-pinned environment; harness entries launch
  its interpreter directly instead of a copy of the git working tree. This removes the
  self-updating `run_server.py` launcher (`git pull` + `uv sync` on every start) and the
  `%APPDATA%/simple-code-indexer` install copy.
- **The legacy install-copy machinery is gone entirely**: `install_root`, `target_root`,
  `legacy_install_root`, `setup.install_root`, `--install-dir`, and the wizard's migrate/delete
  path for a pre-PyPI copy. A copy from the old installer is left alone; delete it yourself.
- **`setup.py` is deleted.** Its only remaining job was passing `--repo-root`, so the wizard now
  finds a source checkout itself (a parent holding this package's own `src/` tree) and
  `simple-code-indexer install` replaces the bootstrap, including installing `uv` when missing.
- **One console command with subcommands**: `setup`, `install`, `serve`, `uninstall`, `status`,
  `version`. A bare invocation still starts the MCP server, so existing harness entries keep
  working. `--no-git-pull` and the `SIMPLE_CI_GIT_PULL` pin are
  gone, as is `--install-dir`. `python -m simple_code_indexer` now works.
- **`checkout` install mode is removed; an editable `uv tool install` replaces it.** The
  default from a source checkout is now an editable install (`uv tool install --editable
  <checkout>`), so edits are live without reinstalling, and `--wheel` builds and installs a real
  wheel for prod validation. Both land in the *same* uv tool environment, so an install never
  rewrites a harness entry — you can switch back and forth freely. `--install-mode`,
  `--no-install`, and `setup.install_mode` (now `setup.install_kind`) are gone, as is the
  `uv run --project` entry form; the setup summary and `status.install_kind` show which flavour
  is live. **Existing entries written by a `--install-mode checkout` setup still point at
  `<repo>/.venv`** — re-run `simple-code-indexer setup` (or `install`) once to repoint them.
- Package metadata modernised for PyPI: SPDX `license = "Apache-2.0"` + `license-files`
  (PEP 639), project URLs, keywords, classifiers.
- `requirements.txt` removed: it was unused and had drifted (missing `sqlite-vec`).

### Added

- **`references/acp-test-process.md` and `references/mcp-test-process.md` now document the uv install
  model**: tool environment via `uv tool dir`, the `<tool-env>/Scripts/pythonw.exe -m
  simple_code_indexer serve` entry, editable vs wheel flavours from `uv-receipt.toml`, and
  `simple-code-indexer install` instead of the deleted `setup.py --install-only` copy flow.
- `.github/workflows/ci.yml`: lint/format/typecheck/test on Ubuntu and Windows, plus a `dist`
  job that builds the wheel and asserts the packaged templates and console script work.
- **Local installs work before the first publish**: a source checkout is installed by path
  (`uv tool install <checkout>`), so `python setup.py`
  needs no PyPI entry. Only a wheel install pins `simple-code-indexer==<version>`
  (`install.install_spec`).
- `.github/workflows/release.yml`: tag-driven publishing through PyPI Trusted Publishing (OIDC,
  no stored token), with a manual TestPyPI rehearsal path and a GitHub release.
- `tools/release.py`: version bump, CHANGELOG cut, tag, push, and the `--verify-tag` /
  `--check-pypi` guards the workflow runs.
- `simple_code_indexer/cli.py` and `simple_code_indexer/__main__.py`.
- **sqlite-vec is the new default vector store** (ADR-017). Vectors live in a `vec_chunks`
  table inside the existing `index.db`, so a file update and its vectors commit in one
  transaction and there is no second file to keep in sync. `vector_store: faiss` and
  `vector_store: qdrant` remain selectable; FAISS stays fully supported as the second option.
- `sqlite_vec.chunk_size` (default `64`), `sqlite_vec.mmap_size` (default `1 GiB`), and
  `sqlite_vec.cache_size` (default `-256 MiB`), overridable with `SQLITE_VEC_CHUNK_SIZE`,
  `SQLITE_VEC_MMAP_SIZE`, and `SQLITE_VEC_CACHE_SIZE`.
- The setup wizard offers sqlite-vec first, FAISS second, and Qdrant third, and probes whether
  the interpreter can load the extension before selecting it (`--vector-store sqlite-vec`).
- `get_status.vector_index` reports `<index.db>#vec_chunks` for the default backend;
  `vector_index_age_s` is derived from the newest successful embedding.
- Language coverage goes from 36 to 322 indexable languages (ADR-016). Every language in
  `tree-sitter-language-pack` is declared in one generated table,
  `src/simple_code_indexer/languages/catalog.py`, which replaces the 38 `builtin/*.py` modules
  and the `importlib` loader. Zig, Nim, Svelte, Vue, Astro, Solidity, Terraform, Nix, Kotlin,
  Dart, and the rest now get a real language id, chunk/lexical/semantic search, and (where a
  grammar exposes it) symbols, instead of `language="text"` and regex symbols.
- `tools/gen_language_catalog.py` regenerates that table from the pack's published language
  table; `--check` fails on drift, so a pack upgrade is a reviewable diff.
- `symbol_lookup` reports `coverage` (`none`/`partial`/`full`), `languages_indexed`,
  `languages_with_symbols`, and a `hint` when a language produced no symbols. A missing symbol
  is now distinguishable from a language that cannot resolve symbols.
- Unmapped languages get one attempt through the pack's own `process()` analysis before falling
  back to the generic node walk (`SYMBOL_FALLBACK=0` disables it).
- `get_status` reports `languages_loaded`, `languages_with_symbol_maps`, `languages_indexed`,
  and `data_formats_excluded`.
- `tests/acp_probe.py` drives an ACP harness (OpenCode by default, Command Code accepted) over
  stdio and asserts the full pipeline end to end — session creation, `cwd`-inferred workspace,
  watcher pickup, all three MCP tools, sqlite/get_status agreement, and clean shutdown — without
  a human in the loop. The MCP server is injected per ACP session; OpenCode 2.2.5 also starts its
  configured entry first, so a checkout-only run masks that entry with a byte-exact backup and
  restores it afterwards. Standard library only.
- [references/acp-test-process.md](../references/acp-test-process.md) documents that automated run,
  and [references/opencode-acp-mode.md](../references/opencode-acp-mode.md) documents ACP mode itself
  (transport, editor setup, MCP injection, permissions, troubleshooting).
- The workspace can come from the client's MCP `roots/list`, from a harness plugin, or from cwd
  (ADR-018). `roots/list` is probed once after the handshake (`SIMPLE_CI_ROOTS_TIMEOUT_S`, default
  `1`, `0` disables; skipped for `WORKSPACE_ROOT`, clients without `roots`, and connections without
  a back-channel). `get_status.workspace_source` reports which source won (`env`, `roots`,
  `harness:<name>`, `cwd`).
- Harness plugins may implement `resolve_workspace(cwd)` and mark their entry with the stable
  `SIMPLE_CI_HARNESS=<NAME>` env value; the server then asks only that plugin for the workspace.
  `harnesses/commandcode.py` uses it to read `~/.commandcode/ide/*.json` and match the publishing
  window's extension-host pid against its live ancestors. The marker is install-scoped, not a path
  (ADR-015 still holds) and optional at runtime: an entry without it falls back to asking every
  resolver when cwd is implausible. Re-run `python setup.py --harnesses commandcode` to add it to
  an existing install (the fast path).

### Changed

- **BREAKING:** the default `vector_store` is now `sqlite-vec`. A workspace whose config does
  not set `vector_store` explicitly is rebound on first start, which invalidates the old index
  and re-embeds it once (vectors are never migrated). Configs that say `vector_store: faiss` or
  `vector_store: qdrant` keep their backend. Delete a stale `.simple-ci/vectors.faiss` after
  switching away from FAISS.
- `vector_store.py` is now a backend registry instead of a branch-per-function router; every
  backend module implements the same `STORE_CONTRACT`, so `get_status`, search, and indexing
  behaviour is identical across backends.
- Language ids are now the tree-sitter grammar names: `c_sharp` → `csharp`, `.tsx` → `tsx`,
  `.zsh` → `zsh`, `.fish` → `fish`. `catalog.VERSION` drives a targeted startup reconcile that
  drops rows whose stored language changed or whose path is no longer allowed, and the sweep
  re-indexes them — no schema change and no full re-embed.
- Grammar prefetch now loads only the symbol-mapped grammars (~29) instead of every grammar, so
  adding ~370 languages cannot trigger a download storm at startup.
- The Make extractor actually resolves rule targets now: `targets` is a named child of `rule`,
  not a tree-sitter field, so the previous lookup always returned nothing.
- README header reworked: title tagline, a flat-square badge row (Python 3.12+, platforms,
  license, last commit), and a new Development section with the lint/typecheck/test commands.
- The ACP end-to-end procedure now targets the checkout under test
  (`tests/acp_probe.py $repo --install $repo`) instead of the `%APPDATA%` install, verifies the
  writer daemon's command line, and rebuilds a deleted index via `PROBE_WAIT_INDEX` before any
  retrieval check. OpenCode's configured MCP entry is masked for checkout-only runs and restored
  afterwards; the procedure is verified with both `faiss` and `sqlite-vec`. See
  [references/acp-test-process.md](../references/acp-test-process.md).
- The server now resolves the workspace and starts the writer/reader **after** the MCP handshake
  (`notifications/initialized`, with the first `tools/*` call as a fallback), because `roots/list`
  is only legal on an initialized session. The startup banner and the file log therefore begin
  once the workspace is known; lines logged earlier (for example `parent watchdog: watching …`)
  go to stderr only. A server that never receives a handshake never opens an index.
- The sidecar writer daemon now runs as a single process on Windows:
  `sidecar.client._daemon_command` launches `sys._base_executable` with the reader's resolved
  `sys.path` instead of the venv's `pythonw.exe` redirector, which kept a second Python process
  alive for the daemon's whole lifetime. One workspace costs one fewer Python process; readers
  (owned by the harness) and the per-consumer MCP clients are unchanged (ISS-016).

### Removed

- **The `plugins/` drop-in folder and the `builtin/` module-per-language layout.** Language
  support is a generated table; extending it means editing the generator. The `NAME`-based
  override and extension-stealing rules are gone with it.
- `get_status.plugins_loaded` (replaced by `languages_loaded`).

### Fixed

- `tests/acp_probe.py` no longer passes on ambient harness config. OpenCode 2.2.5 ignores the
  server the probe injects on `session/new`, so a passing run only ever proved that the
  *configured* `simple-code-indexer` entry launched; with that entry missing it reported a
  misleading 10/23 and the now-removed masking step broke the run outright. The probe reads the
  configured entry through the harness plugin registry (global scope first, then the workspace)
  and exits 1 before spawning the agent unless it launches the target tool environment with
  `-m simple_code_indexer serve`, so a stale or absent entry fails fast with the
  `setup --harnesses` remedy. `HarnessSpec` now exposes `root_key`, and `tests/test_acp_probe.py`
  covers the preflight (ISS-017).
- `simple-code-indexer install` no longer fails with `error: Executable already exists:
  simple-code-indexer.exe` when a tool environment was removed but its entrypoint shim survived.
  The shim counts as an existing install, so `uv tool install` is given `--force` (ISS-016).
- The parent watchdog now recognizes an exited-but-unreaped harness on Linux. A killed
  harness that its parent has not yet reaped is a zombie, and `kill(pid, 0)` still succeeds
  for it, so the server could outlive its harness indefinitely; liveness now also reads the
  `/proc/<pid>/stat` state and treats `Z`/`X` as dead.
- Shutdown no longer leaves the `service-probe` thread running. The writer runtime owns the
  thread, signals it through the shared stop event, and joins it; `embed_texts` aborts its
  retries and backoff on that signal, so probe requests and log records cannot outlive the
  runtime.
- Data formats can no longer reach the index. `catalog.DATA_FORMATS` entries are not registered,
  so detection returns `None` for `.md`, `.txt`, `.json`, `.yaml`, `.toml`, `.xml`, `.csv`,
  `.ini`, `.rst`, and the rest. `.txt` matters most: it maps to `vimdoc`, so a registered `.txt`
  would have parsed `requirements.txt` and `LICENSE.txt` as Vim documentation. `CMakeLists.txt`
  still resolves to `cmake` because filename matching runs first.
- The Command Code VS Code extension no longer indexes the editor installation directory. Its
  stdio children inherit `C:\Program Files\Microsoft VS Code` as cwd; the server now asks the
  client's MCP roots, then the Command Code plugin (which matches the per-window
  `~/.commandcode/ide/*.json` entry by live ancestry), and only then falls back to cwd (ISS-014).
- The parent watchdog arms when a harness spawns the server through a shell (`shell: true` on
  Windows inserts `cmd.exe` between the extension host and our interpreter). A shell is now
  transparent while everything below it is our own launch plumbing; a terminal-launched server
  still has no harness to watch (ISS-015).
- Workspace discovery no longer requires the installed entry to carry the `SIMPLE_CI_HARNESS`
  marker. `run_server.py` updates the code but not `~/.commandcode/mcp.json`, so an install that
  had not re-run setup kept resolving to the editor's installation directory and silently indexed
  nothing. When the cwd is implausible — the user home or a live ancestor's executable directory
  (`parent_watch.ancestor_install_dirs`) — every plugin with a resolver is asked; a plausible cwd
  is never overridden, so a terminal launch still indexes where it was started. If nothing
  publishes a workspace, `load_settings` raises a `ConfigError` naming the directory and the
  remedy instead of building an empty index where it cannot even write the log.

- `docs/RUNBOOK.md`: numbered operator procedures (`RUN-001` upward) for service probes, the
  quality gate, live MCP verification, index rebuilds, sidecar shutdown, and log reading. The
  file header carries the maintenance contract and the evidence rules for new entries.
- Per-workspace sidecar writer daemon (ADR-014). Every harness still spawns its own
  stdio MCP server, but those servers are now **readers**: one detached daemon owns
  `index.db`, `vectors.faiss`, the Qdrant collection, the watcher, the writer thread,
  the sweep timer, and the managed Docker services. Multiple harnesses in one workspace
  all get working tools. The daemon exits after the last registered session plus
  `idle_grace_s` (default 60 s) and is respawned by the next session.
- `mode` (`sidecar` by default, or `embedded`), `idle_grace_s`, and `heartbeat_s` in
  `config.yaml`; `SIMPLE_CI_MODE`, `IDLE_GRACE_S`, and `HEARTBEAT_S` override them.
  `mode: embedded` restores the old single-process writer.
- `get_status` now reports `role` (`reader`/`writer`), `index_ready`, `writer_pid`,
  `writer_ok`, `writer_heartbeat_age_s`, `writer_log_file`, `daemon_endpoint`,
  `sessions`, `harnesses`, and `vector_index_age_s`.
- The sidecar daemon logs to `<workspace>/.simple-ci/log/writer.log` and reader sessions
  to `reader.log`; `mode: embedded` uses `embed.log`. All three use the same
  `log.max_bytes` / `log.backups` rotation. `reader.log` is shared by readers, so its
  rotation is best-effort.
- Harness plugins for **Goose** and **Pi**. Goose is written to its YAML
  `%APPDATA%\Block\goose\config\config.yaml` (or `~/.config/goose/config.yaml`) under
  `extensions.<name>` with `type: stdio`, `cmd`, `args`, `envs`; Pi is written to
  `~/.pi/agent/mcp.json` (or `.pi/mcp.json`) under `mcpServers` with `exposure: direct` so the
  three tools are declared to the model. Harness plugins can now use `FORMAT = "yaml"` in
  addition to JSON and TOML.
- OpenCode entries now set `codemode: false`, so the three tools are exposed directly instead
  of through Code Mode.
- Sidecar lifecycle logging: the daemon logs each client hello (`sidecar client connected`), each
  `REGISTER`/disconnect with the live session and harness list, the configured idle grace and
  heartbeat, and `sidecar stopped`; readers log their session id, workspace, harness process,
  registration, unregistration, and close. `reader.log` remains shared by every reader in the
  workspace.
- `setup.py` asks whether to run a periodic reconciliation sweep (default: no) and accepts
  `--sweep-seconds N` for non-interactive runs. `get_status` reports the configured interval as
  `sweep_seconds` (0 = sweeps off).
- `setup.py --no-git-pull` (debug): write `SIMPLE_CI_GIT_PULL=0` into the harness
  entries so the installed launcher skips its `git pull`, for testing the installed
  snapshot. With `--install-only` it also rewrites the entries already recorded in
  `setup.harnesses`.
- `setup.py --install-only`: copy this checkout to the per-user install directory and exit,
  without prompts, config, services, harness entries, or an environment sync of the copy.
  `--install-dir` and `--dry-run` are honored.
- `references/mcp-test-process.md`: a repeatable end-to-end MCP integration test that installs
  from scratch, hands the live session to a secondary harness agent, and verifies indexing,
  retrieval and shutdown.
- Harness lifecycle watchdog: the server now exits when a process in its launch chain
  disappears (uv's venv trampoline and uv launcher included), so a harness that keeps the stdio
  pipe open can no longer leave the server sweeping after the harness dies.
  `SIMPLE_CI_PARENT_WATCH=0` disables it. Verified end-to-end against OpenCode 2.2.5: closing the
  desktop UI stopped the server in ~2 s even though `opencode-cli serve --service` stayed alive
  and the stdin pipe never closed.
- `get_status` now reports `vectors_indexed` and `pending_embeddings`, and semantic
  `search_code` responses include `ready`, `pending_embeddings`, and a `message` while vectors
  are still being written. A semantic query fired during indexing now says the index is warming
  up instead of silently returning `hits: []`.

### Changed

- Documentation: `docs/ARCH.md` is now the live architecture overview — topology, data flow,
  domain/data model, component design, and testing — replacing the retired technical-design
  document.
  Individual decisions stay in `docs/DECISIONS.md` and structural debt in
  `docs/ARCH_ISSUES.md`. The domain glossary moved to `docs/GLOSSARY.md`, and all references
  were updated.
- Architecture decision records are consolidated into a single
  [docs/DECISIONS.md](DECISIONS.md), compressed to Context / Decision / Consequences. The
  `docs/adr/` folder is gone; the superseded all-in-one-process entry was folded into the
  sidecar decision and the rest renumbered 001–014.
- Runtime logs are split by role: `embed.log` (`mode: embedded`), `writer.log` (sidecar
  daemon), and `reader.log` (sidecar MCP readers), all with the same rotation settings.
  The old `sci.log*` files are no longer written or rotated; delete them by hand.
- The default runtime is now the sidecar topology: the MCP server is a read-only query
  process, and one daemon per workspace performs all indexing. Closing one harness no
  longer affects another, and the index stays fresh while any session is attached.
  Set `SIMPLE_CI_MODE=embedded` (or `mode: embedded`) to keep the old all-in-one process.
- Readers reload the published FAISS file when its mtime/size changes and validate (but
  never create) the Qdrant collection. A reader that starts before the index exists
  returns empty results with `ready: false` instead of crashing.
- The periodic reconciliation sweep is now opt-in and **off by default** (`sweep_seconds: 0`).
  The file watcher is the primary index path; the startup reconcile still runs once at server
  start. When enabled, the interval doubles while the workspace is idle — no watcher events or
  an empty sweep — up to 10 minutes, and resets on activity. With sweeps off, a dormant timer
  temporarily runs them only while chunks are waiting for embeddings, stopping again once none
  are pending, so a transient embedding outage still heals without a full walk every minute.
- Chunks are now 30-line windows with 15-line overlap instead of 80-line blocks. The
  embedding model mean-pools each input, so focused windows retrieve markedly better:
  on the 42-query benchmark R@1 rose 0.667 → 0.786, R@5 0.952 → 1.000, R@10 0.976 → 1.000,
  and nDCG@10 0.746 → 0.870. The chunker profile is part of the vector identity, so the
  first start after upgrading automatically re-embeds the workspace.
- Semantic search de-duplicates overlapping chunks: it over-fetches vector hits and drops
  any hit whose line range overlaps a higher-ranked chunk from the same file, so the
  overlapping windows do not crowd the top-10 with near-duplicates.
- Harness entries launch the installed copy through
  `uv run --project <install> --no-sync python <install>/run_server.py` instead of
  hardcoding the copy's `.venv\Scripts\python.exe`. `--project` preserves the caller's
  cwd, so workspace inference is unchanged.
- README rewritten as a user-facing document: identity, differentiation, status, and quick
  start first; operator procedures (probes, index rebuilds, log reading, diagnosis) now live
  only in `docs/RUNBOOK.md`. Stale claims fixed: the harness list now shows all 13 builtins
  (Goose and Pi were missing), the retrieval benchmark set is 42 queries (not 40), and the
  clone command uses the real repository URL.

### Fixed

- Harness entries no longer contain per-project paths. The OpenCode, Goose, and Pi plugins used to
  turn a `WORKSPACE_ROOT` value into an entry `cwd`, and debugging sessions hand-pinned
  `WORKSPACE_ROOT` into global entries — so one project's absolute path became the workspace for
  every project opened afterwards. Entries are now install-scoped only ([ADR-015](DECISIONS.md#adr-015-harness-entries-are-global-only-no-per-project-data));
  the workspace comes from the harness spawn cwd as before.
- Windows no longer opens stray console windows when a harness starts the MCP server. Recent
  harness entries launched `uv.exe`, and the sidecar daemon was spawned with `DETACHED_PROCESS`;
  both left console-subsystem children to allocate a visible window that stayed for the life of
  the process. On Windows the entry now runs the venv's windowless `pythonw.exe` directly, the
  daemon uses `CREATE_NO_WINDOW`, and `run_server.py`/Docker child processes are spawned with the
  same flag. A reader also waits for the daemon it just started instead of spawning duplicates
  during a slow startup, which was the source of the extra windows that flashed and closed.
- **ISS-11:** a second harness in the same workspace no longer exits with
  `another simple-code-indexer already owns …`. Its MCP server runs as a reader, attaches
  to the workspace daemon (or spawns it), and keeps all tools available when another
  harness closes.
- Shutdown now flushes the vector store while the workspace writer lease is still held, and
  finalization is idempotent. A server starting immediately after another exits can no longer
  race the old process's FAISS write and dirty-flag clear, which could silently drop vectors.
  A failure during startup after the lease is acquired also releases the lease.
- The lifecycle watchdog now watches only the harness process that owns the stdio session,
  skipping the `uv` launcher and venv `python.exe` trampoline. A reused
  `opencode-cli serve --service` — started by an earlier UI and shared by the next one — *is*
  the harness, so the server no longer depends on a UI ancestor that may be missing: it exits
  with the service instead of outliving it. `SIMPLE_CI_PARENT_WATCH=0` still disables the
  watchdog.
- `symbol_lookup` with an empty or whitespace-only `symbol` returns no matches instead of
  treating it as a wildcard and returning every indexed symbol.
- The watcher no longer logs events from ignored directories or its own log file, so an idle
  server no longer grows the active log file in a self-triggering loop. Ignored paths (including
  the active log file) are dropped before any event logging.
- The watcher and `index_one_file` now honor ignored **directories** for nested paths: every
  ancestor directory is checked before the path itself, so a deeper `.gitignore` negation
  (`!keep.py`) cannot re-include a file under a root-ignored tree such as `artifacts/`.
- Semantic search now finds the ignored-directory pruning logic: the query
  "how does the indexer avoid walking into virtualenv and cache directories" returns
  `indexer.py:106-135` (the `os.walk`/`dirnames[:]` loop) at rank 1. The 80-line chunk
  that mixed the whole function with unrelated code scored 0.68 against the query, while
  focused windows score 0.80; the query is now part of `tests/retrieval_queries.json`
  (`q42-walk-pruning`).
- The file watcher now uses a single recursive watch on the workspace root instead of one
  watchdog watch (and thread/handle) per directory, so large workspaces with thousands of
  `bin/`/`obj/` directories no longer exhaust threads and memory.
- The indexer and watcher honor workspace `.gitignore` files (root and nested), so ignored
  files are no longer indexed or watched. `get_status` reports the last sweep's
  `ignored_dirs` and `ignored_files`.
- Embedding requests no longer stall ~1 s each on Windows: the client rewrites loopback
  URLs to `127.0.0.1` instead of letting `localhost` resolve to the dead `::1` address
  first. The wizard probes and the managed-service readiness probe use the same helper.
- The llama.cpp compose template now sets `LLAMA_ARG_BATCH` / `LLAMA_ARG_UBATCH` (this
  build ignores the old `_SIZE` names), so the intended 2048 physical batch is applied
  instead of silently falling back to 512 and rejecting longer inputs.
- `tests/mcp_probe.py` and `tests/live_watch_probe.py` no longer hang when the server fills its
  stderr pipe: the child's stderr is drained on a thread, and `PROBE_TIMEOUT` (default 180 s)
  bounds the run so a stall fails instead of blocking forever.
- Embedding requests are split into batches of at most 16 inputs with at most two in flight per
  process, and retries use full-jitter exponential backoff. A bulk reindex in one workspace no
  longer starves another workspace's request on the shared embedding endpoint; N open
  workspaces still multiply the load.
- `tests/retrieval_bench.py` no longer deletes the live workspace index: a new `--local-path DIR`
  writes `index.db` and `vectors.faiss` into `DIR` instead of `<workspace>/.simple-ci`, and a
  `--reset` that would still hit the live index prints a warning naming the file.
  `tests/bench_matrix.py` gives every run its own scratch folder under
  `artifacts/bench/<timestamp>/local/`.
- Qdrant benchmark runs are isolated too: with `--local-path DIR`, the collection is derived
  from `DIR` instead of the workspace, so `--reset` can no longer delete the collection a live
  MCP server is using. Each `bench_matrix.py` run already has its own scratch folder, so it
  also gets its own collection.
- Concurrent readers can no longer spawn duplicate sidecar daemons. The reader that wins
  `daemon.spawn.lock` publishes `daemon.spawn.json` with the child pid before releasing it, so
  peers wait for that daemon instead of launching a second one; stale claims (dead pid or older
  than 10 minutes) are ignored. A duplicate spawned just before a forced stop could previously
  win the freed writer lease and outlive the cleanup that killed the published daemon.

### Removed

- The Cline builtin harness. The desktop client did not keep or read the wizard's settings
  file, so `setup.py` no longer offers `--harnesses cline`; use OpenCode or another harness.

