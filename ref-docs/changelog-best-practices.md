# Changelog Best Practices

A practical guide to maintaining a `CHANGELOG.md`, based on the [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/) convention and the [Openchangelog guide to CHANGELOG.md](https://openchangelog.com/blog/changelog-md).

---

## Table of Contents

1. [What a changelog is (and isn't)](#1-what-a-changelog-is-and-isnt)
2. [Why keep one](#2-why-keep-one)
3. [Guiding principles](#3-guiding-principles)
4. [File name and location](#4-file-name-and-location)
5. [Structure and format](#5-structure-and-format)
6. [Types of changes](#6-types-of-changes)
7. [Writing good entries](#7-writing-good-entries)
8. [Use an `Unreleased` section](#8-use-an-unreleased-section)
9. [Breaking changes and deprecations](#9-breaking-changes-and-deprecations)
10. [Dates and versions](#10-dates-and-versions)
11. [Yanked releases](#11-yanked-releases)
12. [Rewriting a changelog](#12-rewriting-a-changelog)
13. [Anti-patterns to avoid](#13-anti-patterns-to-avoid)
14. [Changelog vs. GitHub Releases](#14-changelog-vs-github-releases)
15. [Release-day workflow](#15-release-day-workflow)
16. [Quick checklist](#16-quick-checklist)
17. [Complete template](#17-complete-template)

---

## 1. What a changelog is (and isn't)

A changelog is a curated, chronologically ordered list of **notable** changes for each version of a project. It usually lives as a Markdown file in the repository root.

It is **not** a copy of your git history. A commit documents one step in the evolution of the code; a changelog entry documents a meaningful difference that users will care about, often spanning several commits.

## 2. Why keep one

- **Transparency for users and contributors.** They can see exactly what changed between releases without digging through the code.
- **Trust.** Regular, well-documented updates signal that the project is alive and cared for, which encourages adoption and contribution.
- **Easier version management.** When something breaks, you can quickly pinpoint when a change landed.
- **Less support load.** Support and customer-success teams can answer "what changed?" questions by pointing to one place.

### Who benefits

| Audience | How they use it |
| --- | --- |
| End users / consumers | Decide whether and when to upgrade; understand what's new |
| Developers | Troubleshoot regressions and track recent modifications |
| Project / product managers | Track progress and milestones with a transparent record |
| Support and customer success | Quickly answer questions about fixes and updates |
| External contributors | Stay current on how the project is evolving |

## 3. Guiding principles

1. **Write for humans, not machines.** Clarity beats machine-friendliness.
2. **Have an entry for every version.** No gaps in the history.
3. **Group like changes together.** Use consistent categories.
4. **Make versions and sections linkable.** Readers should be able to jump to or share a specific release.
5. **Put the latest version first.** Reverse chronological order.
6. **Show the release date** for every version.
7. **State whether you follow [Semantic Versioning](https://semver.org/).**
8. **Know your audience.** Tone and level of detail should differ for a developer-facing library versus a product used by non-technical customers.

## 4. File name and location

- Name the file **`CHANGELOG.md`** and put it in the repository root.
- Alternatives such as `HISTORY`, `NEWS`, `RELEASES`, or `UPDATES.md` exist, but `CHANGELOG.md` is the most widely recognized name. A predictable name makes it easy for people (and tools) to find notable changes.
- Note that no single changelog format is formally standardized. The GNU changelog and NEWS-file guidelines exist, but Keep a Changelog is the most widely adopted convention, so follow it unless you have a strong reason not to.

## 5. Structure and format

Use a consistent format so readers can scan the file quickly and spot what matters to them.

- Start with a short header explaining what the file is and which conventions you follow (Keep a Changelog, SemVer).
- Put an `## [Unreleased]` section at the top.
- Give each release its own `## [version] - YYYY-MM-DD` heading.
- Under each release, group entries beneath `### Type` subheadings.
- Use bullet lists; keep each entry to a line or two.
- Link each version heading to a diff/comparison URL via reference-style links at the bottom of the file.
- **Omit empty sections.** Missing categories are understood to mean "nothing notable here", and empty headings only add noise.

```markdown
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.2.0] - 2026-03-15

### Added

- New filter option in the product list.

### Fixed

- Login timeout on mobile devices.

[unreleased]: https://github.com/your-org/your-repo/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/your-org/your-repo/compare/v1.1.0...v1.2.0
```

## 6. Types of changes

Group every entry under one of these six categories:

| Category | Use it for |
| --- | --- |
| `Added` | New features |
| `Changed` | Changes to existing functionality |
| `Deprecated` | Features that will be removed soon |
| `Removed` | Features that have now been removed |
| `Fixed` | Bug fixes |
| `Security` | Vulnerability fixes and security-relevant changes |

Grouping lets readers go straight to what they care about: people hunting for new features read `Added`, while people checking whether their bug is resolved read `Fixed`.

## 7. Writing good entries

- **Describe the user-visible impact**, not the implementation. "Fixed login timeouts on mobile" beats "Refactored session handler".
- **Be specific.** Name the feature, endpoint, flag, or setting involved.
- **Keep it concise**, one line where possible.
- **Be consistent in tense and style.** Pick a convention (for example, past tense or imperative) and stick to it. End each entry the same way, such as with a period.
- **Link to the details.** Reference the related issue, pull request, or commit so readers can dig deeper, which is especially useful for open-source projects where contributors follow progress and discussion.
- **Credit contributors** where it fits your project's culture.
- **Skip trivia.** Whitespace fixes, internal refactors, and CI tweaks rarely belong. But whatever *is* important must be included (see [Inconsistent changes](#inconsistent-changes)).

```markdown
### Fixed

- Login failures caused by a bug in the authentication flow. ([#456](https://github.com/your-org/your-repo/issues/456))
```

## 8. Use an `Unreleased` section

Keep an `## [Unreleased]` section at the very top of the file and add entries to it as changes land, not at release time.

This serves two purposes:

1. **Visibility.** People can see what is coming in the next release.
2. **Less release-day work.** At release time you rename the section into a new version heading (adding the date) and create a fresh empty `Unreleased` section.

It also encourages note-keeping throughout development rather than reconstructing history from memory later.

```markdown
## [Unreleased]

### Added

- User profile customization options.
```

## 9. Breaking changes and deprecations

Upgrading should never contain surprises. When something will break, it should be painfully obvious.

- **Always list deprecations, removals, and breaking changes.** If you do nothing else, do this.
- **Deprecate before you remove.** Users should be able to upgrade to a version that lists the deprecation, fix their code, and then move to the version where the removal actually happens.
- **Highlight breaking changes visibly** and tell users what to do about them: give the replacement, the migration path, and the deadline if there is one.
- **Pair breaking changes with a major version bump** if you follow SemVer.

```markdown
### Removed

- **BREAKING:** Support for the legacy `/old-endpoint` API. Migrate to `/new-endpoint` before 2.0.0.
```

## 10. Dates and versions

- **Use ISO 8601 dates: `YYYY-MM-DD`** (for example, `2026-03-15`). The order runs largest to smallest unit, and, unlike regional formats that swap day and month, it can't be misread.
- **Include both version number and release date** for every release.
- **Follow Semantic Versioning** (`MAJOR.MINOR.PATCH`) so the version number itself signals the kind of change to expect, and say so in the file header.
- **Order releases newest first.**

## 11. Yanked releases

A yanked release is a version pulled because of a serious bug or security problem. Don't hide these. Keep them in the changelog and mark them with a loud `[YANKED]` tag:

```markdown
## [0.0.5] - 2014-12-13 [YANKED]
```

The tag is deliberately conspicuous so people notice it, and the brackets make it easy to parse programmatically.

## 12. Rewriting a changelog

Changelogs are living documents, and improving one is fine. Legitimate reasons include:

- Adding releases that were missed.
- Correcting an entry, especially adding a breaking change you forgot to mention.
- Fixing errors and broken links.

Treat rewrites as corrections, not as a way to quietly erase history.

## 13. Anti-patterns to avoid

### Dumping commit logs

Commit logs are full of noise: merge commits, cryptic titles, docs-only changes, and work-in-progress steps. A changelog should communicate noteworthy differences clearly to end users. Don't paste `git log` output into it.

### Ignoring deprecations

Failing to flag upcoming removals leaves users no safe upgrade path. See [section 9](#9-breaking-changes-and-deprecations).

### Confusing dates

Regional formats like `03/04/26` are ambiguous. Use `YYYY-MM-DD` everywhere.

### Inconsistent changes

A changelog that records only some changes can be as dangerous as having none, because readers will assume it is the single source of truth. Trivial changes may be skipped, but every important change must be recorded. A good changelog is a *consistently updated* changelog.

### Other pitfalls worth avoiding

- **Skipped versions.** Every release needs an entry.
- **Unclear audience.** Writing deep internal jargon for a non-technical readership (or the reverse).
- **Mixed formats.** Switching heading styles, category names, or date formats between releases.
- **Vague entries** such as "various improvements" or "bug fixes".

## 14. Changelog vs. GitHub Releases

GitHub Releases turn git tags into rich release notes and are a fine complement, but they don't replace a changelog file:

- They produce a **non-portable** record that is only visible in the context of GitHub.
- They are less discoverable than conventional root-level files like `README` and `CONTRIBUTING`.
- Their interface has historically not offered links to the commit log between releases.

A good approach is to keep `CHANGELOG.md` as the source of truth and reuse its content for your GitHub release notes.

## 15. Release-day workflow

1. Confirm that `Unreleased` captures everything notable since the last release.
2. Choose the next version number according to SemVer.
3. Rename `## [Unreleased]` to `## [X.Y.Z] - YYYY-MM-DD`.
4. Add a new, empty `## [Unreleased]` section above it.
5. Update the comparison links at the bottom of the file.
6. Review wording, make sure breaking changes and deprecations are prominent, and verify links.
7. Tag the release and publish it (optionally copying the section into GitHub Releases).

**Tip:** make "update the changelog" part of your pull request template or definition of done so entries are written alongside the change rather than after the fact.

## 16. Quick checklist

- [ ] File is named `CHANGELOG.md` and sits in the repo root
- [ ] Header states the format and versioning scheme used
- [ ] `Unreleased` section exists at the top
- [ ] Newest release comes first
- [ ] Every release has a version and an ISO 8601 date
- [ ] Changes are grouped under `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`
- [ ] Empty sections are omitted
- [ ] Entries describe user impact and are concise and consistent
- [ ] Entries link to issues, PRs, or commits where useful
- [ ] Deprecations, removals, and breaking changes are clearly called out
- [ ] Yanked releases are marked `[YANKED]`
- [ ] Version headings link to comparison URLs
- [ ] No raw commit-log dumps

## 17. Complete template

Copy this as a starting point:

```markdown
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- 

## [1.0.0] - YYYY-MM-DD

### Added

- Initial release.

[unreleased]: https://github.com/your-org/your-repo/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/your-org/your-repo/releases/tag/v1.0.0
```

---

## Sources

- [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/)
- [Everything you need to know about CHANGELOG.md, Openchangelog](https://openchangelog.com/blog/changelog-md)
