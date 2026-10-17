# Embed code chunks directly (no LLM summaries)

Upstream requires LLM chunk summaries before writing vectors. Without a summarizer, rebuilds fail (`_semantic_stage_error`) and semantic search is permanently `semantic_not_ready`. Our embedding model does not need summaries: we embed chunk text directly and skip the summarization pipeline entirely.

## Considered Options

- **Summary-first (upstream):** richer vectors in theory; every rebuild depends on a fast LLM. Rejected: no summarizer in this environment; chat endpoint is slow/unreliable for bulk jobs.
- **Direct chunk embedding (chosen):** write path stays local-first except one embeddings POST.
- **Defer semantic entirely:** would leave requirements 2–3 unexercised. Rejected.

## Consequences

- Config must **omit** any `summarization:` block and **omit** `OPENAI_API_KEY` (a dummy key enables real `api.openai.com` retries).
- Semantic results are raw-code similarity, not summary similarity — fine for code search.
- Vectors may lag lexical writes by a few seconds (enqueue after FTS upsert).
