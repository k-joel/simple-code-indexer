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

### ISS-1 — `test_watcher_indexes_file_on_save` flakes on "no such table: symbols"
- **Symptom:** the full suite occasionally fails with
  `sqlite3.OperationalError: no such table: symbols`; the test passes in isolation.
- **Where flagged:** 2026-11-06, full `pytest` run while implementing the GPU compose work.
- **Cause:** `tests/test_watcher.py:119` (`_symbol_in_index`) opens a read-only
  connection before the writer thread has created the schema.
- **Fix:** create the schema in the test fixture/`_settings` setup, or catch
  `sqlite3.OperationalError` in the polling predicate and retry.

