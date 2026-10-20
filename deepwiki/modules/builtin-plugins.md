# Module: Builtin Language Plugins

## Responsibilities

- Declare the **languages the indexer understands**: their id, tree-sitter grammar, the
  file extensions and exact filenames they claim, optional symbol node maps and optional
  specialized extractors.
- Provide the **allowlist** the whole system filters on: a file is indexable only if a
  plugin claims its extension or its exact filename.
- Demonstrate the plugin contract that user drop-ins in `plugins/` follow.

## Key Files

| Path | Purpose |
|---|---|
| `src/simple_code_indexer/builtin/*.py` | 36 language plugins (plus `_c_family.py`, a shared helper) |
| `src/simple_code_indexer/registry.py` | The loader that turns these modules into `LanguageSpec`s |
| `src/simple_code_indexer/builtin/_c_family.py` | The shared C/C++ declarator-chain extractor |
| `plugins/README.md` | The user-plugin contract |

## Public Interfaces

Each plugin is a plain module whose globals the registry reads:

| Attribute | Required | Meaning |
|---|---|---|
| `NAME` | yes | Language id stored in `FileRecord.language` |
| `GRAMMAR` | yes | `tree_sitter_language_pack.get_parser` name |
| `EXTENSIONS` | one of | Dotted suffixes, matched case-insensitively |
| `FILENAMES` | one of | Exact basenames (Dockerfile-style) |
| `SYMBOL_NODES` | no | tree-sitter node type → symbol kind |
| `extract(root, source)` | no | Specialized extractor replacing the generic walker |

### The 36 builtin languages

| Plugin `NAME` | Grammar | Notable claims |
|---|---|---|
| `bash` | bash | `.sh`, `.bash` |
| `c` | c | `.c` |
| `cpp` | cpp | `.cpp .cc .cxx .c++ .hpp .h .hh .h++ .hxx` — owns `.h` |
| `c_sharp` | c_sharp | `.cs` — note the **plugin id**, not `csharp` |
| `cmake` | cmake | `CMakeLists.txt` |
| `css` | css | `.css` |
| `dart` | dart | `.dart` |
| `dockerfile` | dockerfile | `.dockerfile`, `Dockerfile` |
| `elixir` | elixir | `.ex`, `.exs` |
| `elm` | elm | `.elm` |
| `erlang` | erlang | `.erl`, `.hrl` |
| `fortran` | fortran | `.f90`, `.f95` |
| `go` | go | `.go` |
| `graphql` | graphql | `.graphql`, `.gql` |
| `haskell` | haskell | `.hs` |
| `html` | html | `.html`, `.htm` |
| `java` | java | `.java` |
| `javascript` | javascript | `.js`, `.jsx`, `.mjs`, `.cjs` |
| `julia` | julia | `.jl` |
| `kotlin` | kotlin | `.kt`, `.kts` |
| `lua` | lua | `.lua` |
| `make` | make | `Makefile` |
| `objc` | objc | `.m` — owns `.m` (so `matlab` is omitted) |
| `ocaml` | ocaml | `.ml`, `.mli` |
| `perl` | perl | `.pl`, `.pm` |
| `php` | php | `.php` |
| `python` | python | `.py`, `.pyi` |
| `r` | r | `.r`, `.R` |
| `ruby` | ruby | `.rb` |
| `rust` | rust | `.rs` |
| `scala` | scala | `.scala`, `.sc` |
| `scss` | scss | `.scss` |
| `sql` | sql | `.sql` |
| `swift` | swift | `.swift` |
| `typescript` | typescript | `.ts`, `.tsx`, `.mts`, `.cts` |
| `vim` | vim | `.vim`, `.vimrc` |

## Inputs and Outputs

| Type | Name | Location | Description |
| --- | --- | --- | --- |
| Input | Module globals | each plugin file | The declaration above |
| Output | `LanguageSpec` | `registry._spec_from_module` | The validated, frozen spec |
| Output | Allowlist entries | `registry._by_ext` / `_by_filename` | The read policy |
| Output | `Symbol` list | `extract(root, source)` | For the C/C++ family and any custom extractor |
| Output | Grammar | `parse._parser(spec.grammar)` | Lazily loaded tree-sitter parser |

## Configuration

- `PREFETCH_GRAMMARS=0` disables the background prefetch of every grammar.
- The plugin directories searched are `builtin/` → `<repo>/plugins/` → `<workspace>/plugins/`.

## Example Snippets

A filename-only plugin — `Path("Dockerfile").suffix` is empty, so the extension alone cannot
express it:

```python
"""Builtin Dockerfile plugin (filename match, not suffix)."""
NAME = "dockerfile"
GRAMMAR = "dockerfile"
EXTENSIONS = [".dockerfile"]
FILENAMES = ["Dockerfile"]
SYMBOL_NODES: dict[str, str] = {}
```

A plugin with a specialized extractor:

```python
"""Builtin C++ plugin (specialized declarator-chain extractor)."""
NAME = "cpp"
GRAMMAR = "cpp"
EXTENSIONS = [".cpp", ".cc", ".cxx", ".c++", ".hpp", ".h", ".hh", ".h++", ".hxx"]
FILENAMES: list[str] = []

def extract(root: Any, source: str) -> list[Symbol]:
    return extract_c_family(root, source)
```

The shared C/C++ extractor — descending the declarator chain to find the real name:

```python
def _function_name(node: Any, source: str) -> str | None:
    """Descend the declarator chain until a named identifier node."""
    current = node.child_by_field_name("declarator")
    if current is None:
        current = node.child_by_field_name("name")
    seen = 0
    while current is not None and seen < 10:
        if current.type in _CPP_NAME_NODES:
            return _text(current, source)
        nested = current.child_by_field_name("declarator")
        if nested is None:
            nested = current.child_by_field_name("name")
        if nested is None and current.named_child_count > 0:
            nested = current.named_children[0]
        current = nested
        seen += 1
    return None
```

The C-family prototype filter — `int x;` is not a function:

```python
if node.type in ("declaration", "field_declaration"):
    # Keep only real function prototypes/members, not `int x;`.
    declarator = _contains_function_declarator(node)
    if declarator is None:
        continue
```

## Edge Cases

- **Data and documentation formats are deliberately absent** — json, yaml, toml, xml, csv,
  markdown, plaintext, rst, latex and regex are not indexed. The original 47-entry registry
  ships as 36 plugins for that reason.
- **`.m` is owned by `objc`**, so `matlab` is omitted.
- **`.h` is owned by `cpp`** (the `_EXT_OWNERS` table), not `c`.
- **Exact-filename plugins** — `Dockerfile`, `CMakeLists.txt`, `Makefile`, `.vimrc` — need
  `FILENAMES`, because `Path(...).suffix` is empty or wrong for them.
- **A user plugin overrides a builtin by `NAME`** and steals its extensions; redeclare them or
  the builtin stops matching. This is a debug-log-only behaviour.
- **Grammars download on demand** — on a fresh machine only `cpp` and `python` are local.
- **No grammar available** → `parse.extract_symbols` falls back to the regex scan, so symbols
  are still extracted (with less fidelity).

## Diagrams

```mermaid
flowchart TB
    FILE[source file] --> EXT{suffix in allowlist?}
    FILE --> FN{exact filename in allowlist?}
    EXT -->|yes| SPEC[LanguageSpec]
    FN -->|yes| SPEC
    EXT -->|no| TEXT[not indexed\nlanguage = text]
    FN -->|no| TEXT
    SPEC --> GRAM[parse._parser(spec.grammar)]
    GRAM --> OK[extract_from_tree]
    OK --> CUSTOM{spec.extract?}
    CUSTOM -->|yes| PLUG[plugin extractor]
    CUSTOM -->|no| GEN[generic name-field walker]
    PLUG --> SYM[Symbol list]
    GEN --> SYM
```

## Tests

- `tests/test_registry.py` — the plugin contract, the allowlist and the collision rules.
- `tests/test_parse.py` — extraction through the registry for a real grammar.
- `tests/fixtures/widget_checksum.cpp` — the C++ fixture used by the acceptance path.

## Source References

- `src/simple_code_indexer/builtin/_c_family.py`
- `src/simple_code_indexer/builtin/cpp.py`
- `src/simple_code_indexer/builtin/dockerfile.py`
- `src/simple_code_indexer/builtin/python.py`
- `src/simple_code_indexer/builtin/make.py`
- `src/simple_code_indexer/builtin/cmake.py`
- `src/simple_code_indexer/registry.py`
- `src/simple_code_indexer/parse.py`
- `plugins/README.md`
- `tests/test_registry.py`
- `NOTES.md`