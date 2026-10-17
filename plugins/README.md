# Language plugins

Drop a `lang_name.py` in this folder (or in `$WORKSPACE_ROOT/plugins/` inside the
container) to index a new language. Builtin plugins live in
`src/simple_code_indexer/builtin/` and use the same contract. A user plugin
overrides a builtin when `NAME` matches, and steals any extension/filename it
claims. Changes need a server restart (no hot reload).

```python
# plugins/zig.py
NAME = "zig"              # language id stored in the index (FileRecord.language)
GRAMMAR = "zig"           # tree_sitter_language_pack.get_parser name
EXTENSIONS = [".zig"]     # dotted suffixes, matched case-insensitively
FILENAMES = ["ZigBuild"]  # exact basenames (Dockerfile-style); optional
SYMBOL_NODES = {          # tree-sitter node type → symbol kind (optional)
    "function_declaration": "function",
    "struct_declaration": "struct",
}

# Optional specialized extractor (replaces the generic name-field walker):
# def extract(root, source): -> list[Symbol]
```

Rules:

- Required: `NAME`, `GRAMMAR`, and at least one of `EXTENSIONS`/`FILENAMES`.
- Bare tokens in `EXTENSIONS` (no leading `.`) are treated as filenames.
- Bad plugins (syntax errors, missing fields) are logged and skipped — the
  server never crashes on one.
- Builtin collisions: `.h` → `cpp`, `.m` → `objc`.
