# Technical Debt Tracker

Canonical register of verified technical debt for this repository. Maintained autonomously by LLM agents and engineering contributors per the embedded specification below.

<!--
TECH_DEBT.md MAINTENANCE GUIDE (FOR AGENTS & CONTRIBUTORS)

PURPOSE & SCOPE
- Authoritative repo-local tracker for verified, actionable technical debt across code, security, architecture, dependencies, tests, performance, data, documentation, infrastructure, and process.
- Intended readers: autonomous coding/audit agents and engineers prioritizing, executing, or verifying debt paydown.
- NOT a product backlog, feature request list, functional user-bug tracker, ADR archive, sprint capacity planner, or refactoring tutorial.

UPDATE TRIGGERS
Update this file whenever ANY of the following occurs:
- Audit / Health Check: Asked to audit, inventory, assess code health, or rank what to refactor first (run applicable stack checks across scope and reconcile the full file).
- Debt Introduced: Before ending a session in which you add a workaround, TODO/FIXME/HACK, skipped test, suppressed lint/type check, pinned legacy dependency, or deferred design fix.
- Debt Discovered: Encountering qualifying, untracked debt in files read or modified during unrelated feature or bug work.
- Status / Scope Change: Starting, pausing, decomposing, re-scoping, reassigning, or moving/renaming files referenced by an active entry.
- Remediation Verified: After fixing debt AND confirming via re-scan/tests/build that the finding/metric dropped (never mark Done on code edits alone).
- Component Retirement: When deleting or replacing code referenced by active entries.

STACK DETECTION & AUDIT CHECKS
Inspect root manifests before scanning to select applicable checks:
- Node / TypeScript / React (`package.json`): outdated/unused deps (`npm outdated`, `depcheck`/`knip`), CVEs (`npm audit`), strict typecheck (`tsc`), zero-warning lint (`eslint`), circular deps (`madge`), initial bundle size.
- PHP / Laravel (`composer.json`): outdated/unused deps (`composer outdated`), CVEs (`composer audit`), static analysis (`phpstan`), complexity/mess (`phpmd`), layer boundaries (`deptrac`).
- Database / MySQL (when schema/migrations/DB exist): migration-vs-schema drift, `EXPLAIN` / full table scans, unindexed FKs, missing FK constraints.
- Other Stacks (`pyproject.toml`, `go.mod`, `Cargo.toml`, etc.): run equivalent repo-native linters, typecheckers, complexity/coverage tools, and vulnerability scanners.
- Cross-Stack (all repos): secret scans (`gitleaks`/`trufflehog`), test coverage/runtime reports, git log aging on `TODO`/`FIXME`/`HACK` (>6 months), build/CI warnings, `CODEOWNERS`.

INCLUSION / EXCLUSION CRITERIA
INCLUDE an entry ONLY when directly observed in repo files or tool output and matching at least one category threshold below.

Canonical Category Slugs (normalize synonyms: `design`→`architecture`, `deps`→`dependency`, `perf`→`performance`, `docs`→`documentation`, `infra`→`infrastructure`):
- `code`:
  Subcategories: `large_function`, `high_complexity`, `deep_nesting`, `long_parameter_list`, `god_class`, `duplicate_code`, `dead_code`, `magic_numbers`, `commented_code`, `poor_naming`, `inconsistent_patterns`, `empty_catch_blocks`, `generic_exceptions`, `missing_error_handling`, `data_clumps`.
  Thresholds: functions >50 lines (>20 simple ops); cyclomatic complexity >10; nesting >4 levels; >4 params; class >300 lines or >15 public methods; duplicated blocks >30 lines or >3 similar blocks; unreachable/unused exports/commented-out blocks; magic numbers/hardcoded business literals; empty/generic/missing error handling.
- `security`:
  Subcategories: `secrets_in_code`, `missing_input_validation`, `weak_auth_hashing`, `unbounded_sessions`, `missing_rate_limiting`, `missing_security_headers`, `missing_authorization`.
  Thresholds: committed secrets/API keys/credentials (source or git history); public endpoints lacking schema/DTO/FormRequest validation; MD5/SHA-1 password hashing (require bcrypt/argon2id); unbounded sessions or un-rate-limited auth endpoints; missing CSP/HSTS/X-Content-Type-Options/Referrer-Policy; missing authorization checks on protected routes.
- `architecture`:
  Subcategories: `monolithic_design`, `circular_dependencies`, `god_object`, `inappropriate_intimacy`, `abstraction_inversion`, `leaky_abstractions`, `shotgun_surgery`, `broken_hierarchy`, `performance_bottlenecks`, `resource_contention`, `single_point_failure`.
  Thresholds: circular module dependencies; reversed layer dependencies (e.g., repository→service→UI); shotgun surgery (1 change requires edits in 5+ files); framework types leaking across layer boundaries; monolithic bottlenecks or single points of failure.
- `dependency`:
  Subcategories: `outdated_dependencies`, `vulnerable_dependencies`, `deprecated_dependencies`, `version_conflicts`, `license_violations`, `license_unknown`, `unused_dependencies`, `oversized_dependencies`, `redundant_dependencies`.
  Thresholds: >2 major versions behind; unmaintained/abandoned (>24 months without release); HIGH/CRITICAL CVEs; unused declared packages; version conflicts; incompatible/unknown licenses; unpinned or heavy single-purpose deps.
- `test`:
  Subcategories: `low_coverage`, `missing_unit_tests`, `missing_integration_tests`, `missing_end_to_end_tests`, `flaky_tests`, `slow_tests`, `brittle_tests`, `disabled_tests`, `unclear_test_intent`, `missing_test_data`, `environment_dependencies`.
  Thresholds: critical-path coverage <80%; missing unit/integration tests for critical logic/workflows; flaky tests on main; skipped/disabled tests without linked issue or removal date; test suite >10 min without documented budget; tests lacking meaningful assertions or test-data strategy.
- `performance`:
  Subcategories: `n_plus_one_queries`, `missing_pagination`, `bundle_bloat`, `missing_caching`.
  Thresholds: N+1 queries on list endpoints; unbounded list queries (missing pagination); initial frontend bundle >200 KB gzip or missing route-level code splitting; uncached expensive read/aggregation paths.
- `data`:
  Subcategories: `schema_drift`, `missing_indexes`, `orphaned_records`.
  Thresholds: production/actual schema diverging from migrations; unindexed FKs or hot-query columns causing sequential scans; unenforced FKs or orphaned child records.
- `documentation`:
  Subcategories: `missing_api_docs`, `outdated_api_docs`, `missing_comments`, `outdated_comments`, `missing_architecture_docs`, `missing_deployment_docs`, `missing_onboarding_docs`, `missing_docstring`.
  Thresholds: README contradicting current setup/dev workflow; comments contradicting code; public APIs/exports lacking docblocks or type hints; missing ADRs/architecture/deployment/onboarding docs; docs stale >3-6 months.
- `infrastructure`:
  Subcategories: `eol_runtime`, `deprecated_framework_api`, `build_warnings`, `secrets_management`, `missing_monitoring`, `inadequate_logging`, `missing_alerting`, `poor_observability`, `manual_deployment`, `missing_pipeline`, `environment_drift`, `hardcoded_config`, `missing_dr_plan`.
  Thresholds: EOL/near-EOL runtimes; deprecated framework APIs; non-zero build/compile/lint warnings; secrets outside a secret manager (plain env/long-lived shared creds); missing structured logs, error tracking, p95 latency metrics, SLO alerts, CI/CD, IaC, or DR plan; dev/staging/prod drift.
- `process`:
  Subcategories: `aging_todo_fixme`, `unscheduled_deprecation`, `untracked_debt`, `missing_codeowners`, `lingering_feature_flags`.
  Thresholds: `TODO`/`FIXME`/`HACK` >6 months old without owner/ticket; `@deprecated` without removal date/replacement; missing/stale `CODEOWNERS`; feature flags at 100% rollout >6 weeks without removal plan; ad-hoc untracked workarounds.

EXCLUDE:
- Unverified suspicions without observed `file:line`, symbol, or tool output.
- Cosmetic formatting already enforced by auto-formatters.
- Product feature requests or functional user-facing bugs unrelated to code/design/ops health.
- Speculative future-proofing without measurable current velocity, quality, reliability, or security cost.
- Trivial <15-min cleanups safe to fix immediately inline (fix now instead of logging overhead).
- Duplicate entries for the same root cause (consolidate systemic occurrences under one ID listing affected paths).

SCORING, EFFORT & PRIORITY MODEL
Impact Tiers (calibrated to 1-10 severity across velocity, quality, productivity, business):
- `CRITICAL` (9-10): Active security vulns/secrets, prod-breaking/data-loss risk, compliance/legal violations, team blockers.
- `HIGH` (7-8): Major velocity slowdown, regular prod defects, customer-facing quality/perf risk, severe arch/test gaps.
- `MEDIUM` (4-6): Moderate maintenance friction, localized complexity/duplication, partial observability/doc gaps.
- `LOW` (1-3): Minor doc/style/cleanup issues with negligible risk.

Effort Sizes:
- `XS`: 1-4 hours | `S`: 0.5-2 days | `M`: 3-5 days | `L`: 1-2 weeks | `XL`: 3+ weeks.
- Rule: Any `L` or `XL` entry MUST be decomposed into `XS`-`M` child items before entering `Planned` or `In Progress`.

Deterministic Priority Matrix (Effort x Impact):
- `P0`: `CRITICAL` + `XS`/`S`/`M`
- `P1`: `CRITICAL` + `L`/`XL` (decompose first), OR `HIGH` + `XS`/`S`/`M`
- `P2`: `HIGH` + `L`/`XL` (decompose first), OR `MEDIUM` + `XS`/`S`/`M`
- `P3`: `MEDIUM` + `L`/`XL` (decompose first), OR `LOW` (any effort)

Optional Quantitative Scoring (for `P0`/`P1` or tie-breaking when real telemetry exists; NEVER fabricate inputs):
- `Interest Rate = Impact (1-10) x Encounters per Sprint`
- `Cost of Delay = Interest Rate x Sprints Delayed x Team Multiplier`
- `WSJF = (Business Value [1-10] + Time Criticality [1-10] + Risk Reduction [1-10]) / EffortWeight (XS=1, S=2, M=5, L=8, XL=13)`
- `Quadrant`: `Reckless-Deliberate` (highest urgency), `Prudent-Deliberate`, `Reckless-Inadvertent`, `Prudent-Inadvertent`.

STRUCTURE & FORMATTING
Keep these exact 4 top-level `##` headings in order. Never delete a required heading; if a section has no entries, write `_None._` (and omit empty table headers):
1) `## Summary`
   - Bullets: `**Last Updated:** YYYY-MM-DD`, `**Last Full Audit:** YYYY-MM-DD (or Pending) | **Stacks:** {detected} | **Audit Checks:** X PASS / Y FAIL / Z N/A (or Pending)`, `**Open Debt:** N total (P0: n, P1: n, P2: n, P3: n)`, `**Trend:** Baseline | Improving | Stable | Worsening (Resolved since last audit: N)`, `**Open by Category:**` (comma-separated non-zero `category: count` pairs, or `None`), `**Top 3 to Pay Down First:**` (numbered list `1.`-`3.` of highest-priority IDs with 1-line rationale, or `None`).
2) `## Active Debt Ledger`
   - Markdown table of ALL non-terminal items (`Status` not `Done` or `Won't Fix`).
   - Exact columns: `| ID | Priority | Status | Category | Subcategory | Item | Location | Effort | Impact | Updated |`
   - Strict sort order: (1) Priority `P0`→`P3`, (2) Effort ascending `XS`→`XL` (break ties by higher CoD/WSJF if recorded, then ID ascending).
3) `## Debt Details`
   - One `### DEBT-YYYY-NNN: Short Title` subsection per active ledger row, in exact ledger sort order.
   - Required bullets: `**Category / Subcategory:**`, `**Status / Priority:**`, `**Location:**`, `**Dates:**` (`Created YYYY-MM-DD | Updated YYYY-MM-DD`), `**Evidence:**`, `**Impact Rationale:**`, `**Remediation Target:**`.
   - Optional bullets (omit if empty): `**Scoring:**` (`Quadrant` / `CoD` / `WSJF` / `Risk` / `Skill`), `**Dependencies / Ref:**` (parent/child IDs, PR/issue/ADR links, owner, tags).
4) `## Resolved & Retired Log`
   - Append-only table preserving history, sorted newest `Closed` date first.
   - Exact columns: `| ID | Category | Item | Final Status | Resolution & Verification Evidence | Closed |`

Formatting Conventions:
- IDs: `DEBT-YYYY-NNN` (4-digit creation year + zero-padded sequence >=3 digits starting at `001`; e.g., `YYYY=2026`, `NNN=001`). Monotonic per year; NEVER reuse retired IDs.
- Dates: Strict ISO-8601 `YYYY-MM-DD`.
- Status Lifecycle: Active (`Identified`, `Analyzed`, `Prioritized`, `Planned`, `In Progress`, `Review`) → Terminal (`Done`, `Won't Fix`).
- Locations & Cross-links: Repo-relative paths with line ranges in backticks (e.g., `` `src/auth/login.ts:45-120` ``); cite only verified files, ADRs, or issue IDs.

QUALITY & STYLE RULES
- Tone & Brevity: Terse, objective, factual. Keep ledger `Item` titles <=70 chars; keep detail text to 1-3 crisp sentences.
- Evidence Mandate: Cite directly observed `file:line`, symbols, or command output. Never guess line numbers, CVEs, test timings, or coverage percentages.
- Targeted Update vs. Full Audit: When logging or closing individual items mid-task, update affected items, `Last Updated`, `Open Debt`, `Open by Category`, and `Top 3`; do NOT alter `Last Full Audit` or `Audit Checks` unless a full audit ran.
- Verification Loop: Before transitioning any item to `Done`, re-run the relevant scan/test/lint/audit command to verify the finding disappeared or metric dropped. Rework that leaves debt metrics unchanged is not debt paydown.

LIFECYCLE & WORKFLOW
- Add: Assign next unused `DEBT-YYYY-NNN`; set `Identified` (or `Analyzed`/`Prioritized` once scored); add row to `## Active Debt Ledger`, add block to `## Debt Details`, and update `## Summary`.
- Promote / Edit: Advance `Status` (`Identified`→`Analyzed`→`Prioritized`→`Planned`→`In Progress`→`Review`); bump `Updated`; keep Ledger, Details, and Summary synchronized.
- Decompose (`L`/`XL`): Create `XS`-`M` child `DEBT-YYYY-NNN` entries referencing the parent ID; retire the oversized parent to `## Resolved & Retired Log` as `Done` (`Decomposed into DEBT-YYYY-AAA, ...`) to avoid double-counting.
- Retire (`Done` / `Won't Fix`): Never delete entries. Remove from `## Active Debt Ledger` and `## Debt Details`, prepend row to `## Resolved & Retired Log` with `Final Status`, verification evidence or explicit rationale (e.g., `Accepted via ADR-012` / `Component deleted`), and `Closed` date; update `## Summary`.

ANTI-PATTERNS
- Logging speculative debt without inspecting code/output, or leaving stale `Location` paths after refactors.
- Marking debt `Done` without post-fix verification confirming reduction.
- Deleting closed items, erasing history, or reusing `DEBT-YYYY-NNN` IDs.
- Fabricating `Interest Rate` / `Cost of Delay` scores when encounter/sprint data is missing.
- Scheduling unsplit `L`/`XL` items into `Planned` or `In Progress`.
- Letting `## Summary` counts or `Top 3` drift out of sync with `## Active Debt Ledger`.
- Adding refactoring tutorials, sprint velocity ratios, or general feature/bug tasks to this file.

EXAMPLE LAYOUT (4-SPACE INDENTED)

    ## Summary

    - **Last Updated:** 2026-01-15
    - **Last Full Audit:** 2026-01-15 | **Stacks:** Node/TypeScript | **Audit Checks:** 40 PASS / 1 FAIL / 1 N/A
    - **Open Debt:** 1 total (P0: 1, P1: 0, P2: 0, P3: 0)
    - **Trend:** Improving (Resolved since last audit: 1)
    - **Open by Category:** security: 1
    - **Top 3 to Pay Down First:**
      1. `DEBT-YYYY-002` — Unvalidated public webhook endpoint (`P0`, `S` quick win eliminating auth bypass risk).

    ## Active Debt Ledger

    | ID | Priority | Status | Category | Subcategory | Item | Location | Effort | Impact | Updated |
    | :- | :- | :- | :- | :- | :- | :- | :- | :- | :- |
    | DEBT-YYYY-002 | P0 | Prioritized | security | missing_input_validation | Public billing webhook skips schema/signature check | `src/api/webhook.ts:18-64` | S | CRITICAL | 2026-01-15 |

    ## Debt Details

    ### DEBT-YYYY-002: Public billing webhook skips schema/signature check

    - **Category / Subcategory:** security / missing_input_validation
    - **Status / Priority:** Prioritized / P0 (Impact: CRITICAL, Effort: S)
    - **Location:** `src/api/webhook.ts:18-64`
    - **Dates:** Created 2026-01-10 | Updated 2026-01-15
    - **Evidence:** Route parses `req.body` directly without Zod schema or HMAC signature validation (`eslint`/manual audit).
    - **Impact Rationale:** Exposes billing state transitions to spoofed requests (9/10 security risk).
    - **Remediation Target:** Add HMAC verification middleware + strict DTO schema; verify with negative integration tests.
    - **Scoring:** Quadrant: Reckless-Deliberate | WSJF: 13.5 | Risk: low | Skill: mid
    - **Dependencies / Ref:** Tags: `security`, `api`

    ## Resolved & Retired Log

    | ID | Category | Item | Final Status | Resolution & Verification Evidence | Closed |
    | :- | :- | :- | :- | :- | :- |
    | DEBT-YYYY-001 | dependency | Upgrade lodash 4.17.15 (HIGH CVE) | Done | Upgraded to 4.17.21; `npm audit` reports 0 HIGH/CRITICAL vulns | 2026-01-14 |
-->

---

## Summary

- **Last Updated:** 2026-11-15
- **Last Full Audit:** Pending | **Stacks:** Python | **Audit Checks:** Pending
- **Open Debt:** 0 total (P0: 0, P1: 0, P2: 0, P3: 0)
- **Trend:** Baseline
- **Open by Category:** None
- **Top 3 to Pay Down First:** None

## Active Debt Ledger

_None._

## Debt Details

_None._

## Resolved & Retired Log

_None._