# Module: Harness Plugins

## Responsibilities

- Teach the setup wizard **where each MCP client keeps its server list** and **how to merge
  an entry into it** without destroying anything the user wrote.
- Provide **detection** so the wizard can pre-select the harnesses actually installed on the
  machine.
- Support two config formats — **JSON/JSONC** and **TOML** — plus a full `render()` escape
  hatch for clients that need something else.
- Load plugins from three locations, later ones winning: builtin package → `<repo>/harnesses/`
  → `<workspace>/harnesses/`.
- Stay **fail-soft**: a plugin that fails to import or validate is logged and skipped.

## Key Files

| Path | Purpose |
|---|---|
| `src/simple_code_indexer/harnesses/__init__.py` | The loader, `HarnessSpec`, path expansion |
| `src/simple_code_indexer/harnesses/_json.py` | JSON / JSONC parse and upsert |
| `src/simple_code_indexer/harnesses/_toml.py` | Marker-block TOML merge |
| `src/simple_code_indexer/harnesses/*.py` | 13 builtin harness plugins |
| `harnesses/README.md` | The user-plugin contract |

## Public Interfaces

| Name | Kind | Description |
|---|---|---|
| `load_harnesses(*, user_dirs=None, include_builtin=True) -> list[HarnessSpec]` | function | Builds a fresh list |
| `get_harnesses() -> tuple[HarnessSpec, ...]` | function | The cached list |
| `reset_harnesses()` | function | Drops the cache (tests only) |
| `default_user_harness_dirs() -> list[Path]` | function | Repo `harnesses/` then workspace `harnesses/` |
| `HarnessSpec.detected(home=None) -> bool` | method | A home dir or a binary on `PATH` exists |
| `HarnessSpec.candidates(scope, workspace, home=None) -> list[Path]` | method | Candidate config paths for a scope |
| `HarnessSpec.entry` / `.render` | attributes | The merge functions |

### Plugin module contract

| Attribute | Required | Meaning |
|---|---|---|
| `NAME` | yes | Stable id; the file stem by convention |
| `LABEL` | no | Human label shown by the wizard |
| `HOME_DIRS` | no | Detection dirs, relative to home or absolute (`%VARS%` expand) |
| `BINARIES` | no | CLI names that also count as installed |
| `GLOBAL_CONFIGS` | one of | User-scope config files |
| `LOCAL_CONFIGS` | one of | Project-scope config files, relative to the workspace |
| `FORMAT` | no | `"json"` (default) or `"toml"` |
| `ROOT_KEY` | for JSON | The JSON root key (`mcpServers`, `servers`, `mcp`, …) |
| `entry(command, env)` | no | Builds the per-harness server entry |
| `render(existing, *, name, command, env)` | no | Full override for merging into existing text |

### Builtin harnesses

| Harness | Format | Global config | Project config | Root key |
|---|---|---|---|---|
| Claude Code | json | `~/.claude.json` | `.mcp.json` | `mcpServers` |
| Claude Desktop | json | `%APPDATA%/Claude/claude_desktop_config.json` | — | `mcpServers` |
| Codex CLI | toml | `~/.codex/config.toml` | `.codex/config.toml` | — |
| Gemini CLI | json | `~/.gemini/settings.json` | `.gemini/settings.json` | `mcpServers` |
| OpenCode | json | `~/.config/opencode/opencode.json(c)` | `opencode.json(c)` | `mcp` |
| Cursor | json | `~/.cursor/mcp.json` | `.cursor/mcp.json` | `mcpServers` |
| Windsurf | json | `~/.codeium/windsurf/mcp_config.json` | — | `mcpServers` |
| VS Code | json | `%APPDATA%/Code/User/mcp.json` | `.vscode/mcp.json` | `servers` |
| Zed | json | `~/.config/zed/settings.json` | `.zed/settings.json` | `context_servers` |
| Cline | json | VS Code globalStorage `cline_mcp_settings.json` | — | `mcpServers` |
| Command Code | json | `~/.commandcode/mcp.json` | `.mcp.json` | `mcpServers` |
| MiMoCode | json | `~/.mimocode/mimocode.json` | `.mimocode/mimocode.json` | `mcp` |
| Claude Desktop / others | — | see `harnesses/*.py` | — | — |

## Inputs and Outputs

| Type | Name | Location | Description |
| --- | --- | --- | --- |
| Input | Plugin modules | `harnesses/` dirs | Module globals describing one client |
| Input | Existing config text | the target file | Preserved by the merge helpers |
| Input | Home / workspace | `Path.home()`, cwd | Where the config paths are resolved |
| Output | `HarnessSpec` list | `load_harnesses()` | The wizard's model of every client |
| Output | Merged config text | `spec.render(existing, …)` | The file to write |
| Output | Backup file | `<name>.bak.<timestamp>` | The pre-write content |

## Configuration

- `WORKSPACE_ROOT` — decides where `<workspace>/harnesses/` is looked up.
- `~` and `%VAR%` are expanded in `HOME_DIRS` and `*_CONFIGS`; a path whose variable does not
  exist on the current platform is skipped.

## Example Snippets

The JSON merge — set one key, keep everything else:

```python
def upsert(existing: str, *, root_key: str, name: str, entry: dict[str, Any]) -> str:
    """Set `root_key[name] = entry` and re-serialize the whole document."""
    document = parse(existing)
    servers = document.setdefault(root_key, {})
    if not isinstance(servers, dict):
        raise ParseError(f"'{root_key}' must be an object")
    servers[name] = entry
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"
```

The TOML merge — own a marked block, never rewrite the file:

```python
_BEGIN = "# >>> simple-code-indexer >>>"
_END = "# <<< simple-code-indexer <<<"

def upsert(existing: str, *, name: str, command: list[str], env: dict[str, str]) -> str:
    block = _render(name, command, env)
    if _BEGIN in existing and _END in existing:
        before, _, rest = existing.partition(_BEGIN)
        _, _, after = rest.partition(_END)
        return before + block + after.lstrip("\r\n")
    body = existing.rstrip("\n")
    separator = "\n\n" if body else ""
    return body + separator + block
```

A JSON harness plugin in full:

```python
"""Builtin MiMoCode harness plugin (`mcp` key, local command array)."""
NAME = "mimo"
LABEL = "MiMoCode"
HOME_DIRS = [".mimocode"]
BINARIES = ["mimo"]
GLOBAL_CONFIGS = ["~/.mimocode/mimocode.json"]
LOCAL_CONFIGS = [".mimocode/mimocode.json"]
ROOT_KEY = "mcp"

def entry(command: list[str], env: dict[str, str]) -> dict[str, Any]:
    value: dict[str, Any] = {
        "type": "local",
        "command": command,
        "enabled": True,
    }
    if env:
        value["environment"] = env
    return value
```

Path expansion with an explicit home:

```python
def _expand(raw: str, base: Path, home: Path | None = None) -> Path | None:
    """Expand ~ and environment variables; None when a variable stays unresolved."""
    expanded = os.path.expandvars(raw)
    if _UNRESOLVED_VAR.search(expanded):
        return None
    if expanded == "~" or expanded.startswith(("~/", "~\\")):
        root = home or Path.home()
        expanded = str(root) + expanded[1:]
    path = Path(expanded)
    return path if path.is_absolute() else base / path
```

## Edge Cases

- **JSONC comments** — `_json.py` strips `//` and `/* */` to parse OpenCode `.jsonc` files,
  then writes **strict JSON**. The comments are lost on rewrite; the file is backed up first.
- **Unparseable JSON** → `write.install` refuses to write and the wizard prints the manual
  snippet instead.
- **TOML cannot be written** (`tomllib` is read-only) → the marker-block approach preserves
  user comments and ordering.
- **`ROOT_KEY` missing on a JSON plugin** → the plugin is rejected with a warning.
- **`FORMAT` other than `json`/`toml`** → the plugin is rejected.
- **A plugin with no config paths** → rejected.
- **A plugin that raises on import** → logged and skipped.
- **Platform-specific path** (e.g. `%APPDATA%` on Linux) → the variable stays unresolved and
  the candidate is dropped.
- **Detection** — a harness counts as installed when one of its home dirs exists **or** one of
  its binaries is on `PATH`. Command Code deliberately does not check the `cmd` binary: on
  Windows that is the shell, so every machine would look like it has Command Code.
- **Two harnesses pointing at the same file** → the second is skipped by the wizard.

## Diagrams

```mermaid
flowchart TB
    LOAD[load_harnesses] --> BUILTIN[load builtin harnesses/*.py]
    LOAD --> USER[load repo harnesses/ then workspace harnesses/]
    BUILTIN --> VALID[_spec_from_module]
    USER --> VALID
    VALID -->|invalid| SKIP[log + skip]
    VALID -->|valid| SPEC[HarnessSpec]
    SPEC --> DET{HarnessSpec.detected}
    DET -->|home dir or binary| PRE[pre-selected in the wizard]
    SPEC --> CANDS[HarnessSpec.candidates(scope)]
    CANDS --> EXIST{file exists?}
    EXIST -->|yes| TARGET[that file]
    EXIST -->|no| TARGET[first platform-supported candidate]
    TARGET --> RENDER{spec.format}
    RENDER -->|json| J[_json.upsert]
    RENDER -->|toml| T[_toml.upsert marker block]
    J --> WRITE[write.install\nbackup + validate + atomic write]
    T --> WRITE
```

## Tests

- `tests/test_harnesses.py` — the plugin contract, path expansion, the JSON and TOML merges,
  and the detection rules.

## Source References

- `src/simple_code_indexer/harnesses/__init__.py`
- `src/simple_code_indexer/harnesses/_json.py`
- `src/simple_code_indexer/harnesses/_toml.py`
- `src/simple_code_indexer/harnesses/mimo.py`
- `src/simple_code_indexer/harnesses/codex.py`
- `src/simple_code_indexer/harnesses/cursor.py`
- `src/simple_code_indexer/setup_wizard/__init__.py`
- `src/simple_code_indexer/setup_wizard/write.py`
- `harnesses/README.md`
- `tests/test_harnesses.py`
- `docs/adr/0009-setup-wizard-managed-services-config.md`