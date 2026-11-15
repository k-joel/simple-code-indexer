# Issues

Ongoing issue tracker for bugs, defects and gaps found while working on this
repo — by humans or by LLM sessions.

**Rules of this file**
- **Every issue, bug or defect flagged during a session — however small, and even
  if only mentioned in passing in a summary — must be added here.**
- **Once an issue is fixed, delete its entry from this doc.** Do not mark it done
  and leave it: this file must only ever contain open issues. Operational gotchas 
  that are not defects belong in `NOTES.md`.
- Keep entries short: symptom, where it was flagged, cause (`file:line`),
  suggested fix. Add new issues with the next free `ISS-n` id.

## Open

### ISS-12: `ruff format --check` fails on two committed files

- **Symptom**: `uv run ruff format --check .` reports `2 files would be reformatted`.
- **Where flagged**: 2026-11-15, while running the quality gate before adding `docs/RUNBOOK.md`.
- **Cause**: `src/simple_code_indexer/setup_wizard/__init__.py:1337` and
  `tests/test_setup_wizard.py:1124`, `:1170`, `:1213` are committed without `ruff format`.
- **Suggested fix**: run
  `uv run ruff format src/simple_code_indexer/setup_wizard/__init__.py tests/test_setup_wizard.py`,
  then re-run `uv run ruff format --check .` and the quality gate.

