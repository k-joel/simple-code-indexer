# Architectural & Refactoring Debt

Ongoing tracker for structural anti-patterns, code duplication, abstraction leaks, and AI-generated code smells discovered while traversing, expanding, or refactoring the codebase — by humans or by LLM sessions.

**Rules of this file**
- **Every architectural smell, high-coupling bottleneck, code duplication, or structural anti-pattern flagged during a session must be added here.** Functional bugs and defects belong in `docs/ISSUES.md`.
- **Once the refactoring is completed and merged, delete its entry from this doc.** Do not mark it done and leave it: this file must only ever contain open architectural items.
- Keep entries short: structural symptom, affected components (`file:line`), why it creates technical friction, and the proposed refactoring strategy. Add new entries with the next free `ARCH-n` id.