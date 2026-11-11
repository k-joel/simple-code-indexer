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

- **ISS-10 — the server can outlive the desktop UI when the OpenCode background service is reused.**
  - Symptom: after the current UI (477760) died, server 396376, trampoline 335744 and uv 559948
    were still alive 1.5 h later; `sci.log` had no `parent process … is gone` / shutdown lines.
  - Where: Stage 4, 2026-11-10 23:14; watchdog list was
    `335744 (python.exe), 559948 (uv.exe), 427588 (opencode-cli.exe)`.
  - Cause: the service 427588 was started by the **previous** UI 489696 (now dead); the new UI
    reuses the service and is a **sibling**, so `parent_watch.ancestors()` stops at the missing
    parent and never sees the current UI.
  - Suggested fix: restart `opencode-cli serve --service` per UI session (or have the watchdog
    observe the service's current attached UI/client); document the reused-service case and the
    `taskkill`/`opencode service stop` cleanup. The watchdog is correct for a UI-started service
    (verified in the 14:45 run); this is the reuse topology.

