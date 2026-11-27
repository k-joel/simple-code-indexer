# User harness plugins

Drop-in modules that teach the setup wizard how a particular MCP client stores
its server list. A plugin is a plain `.py` file whose module globals are read by
the loader. (Languages used to work the same way; they are now a generated table
in `src/simple_code_indexer/languages/catalog.py`, so harnesses are the only
remaining plugin axis.)

Search order (later wins): the builtin package → `<repo>/harnesses/` →
`<workspace>/harnesses/`. A user plugin overrides a builtin by `NAME`; modules
that fail to import or validate are logged and skipped.

## Contract

```python
NAME = "my_harness"              # required, unique
LABEL = "My Harness"             # shown by the wizard
HOME_DIRS = ["~/.my-harness"]    # detection: any existing dir (or BINARIES on PATH)
BINARIES = ["my-harness"]
GLOBAL_CONFIGS = ["~/.my-harness/mcp.json"]   # user scope
LOCAL_CONFIGS = [".my-harness/mcp.json"]      # project scope (relative to cwd)
FORMAT = "json"                  # or "toml"
ROOT_KEY = "mcpServers"          # JSON root key

def entry(command, env):         # optional; default is command/args/env
    return {"command": command[0], "args": command[1:], "env": env}

def resolve_workspace(cwd):      # optional; publish this session's workspace
    return Path("…") or None     # None = no answer, next source wins
```

If `FORMAT = "toml"`, the plugin must not set `ROOT_KEY`; the loader writes a
marker-delimited `[mcp_servers."simple-code-indexer"]` block. A plugin can also
provide `render(existing, *, name, command, env) -> str` to fully control merging.

A plugin that implements `resolve_workspace` gets `serve --harness <NAME>`
appended to its entry by the wizard (from `simple_code_indexer.harnesses`).
The server then asks that plugin — and only that plugin — for the workspace
after the MCP handshake. The value is a stable harness id, never a path: it is
install-scoped, so it is allowed under ADR-015 and, unlike an env var, visible
in the client's own config. `SIMPLE_CI_HARNESS` is still read as a debug
fallback. An entry installed before either marker existed is still served: when
the process cwd is not a plausible project (the user home or an ancestor's
executable directory), every plugin with a resolver is asked, marked one first.
Discovery logic (files, sockets, IDE state) belongs in the plugin, not
in core; see `src/simple_code_indexer/harnesses/commandcode.py` for the
ancestor-keyed example. `parent_watch.ancestor_chain()` is the generic helper
for matching a live ancestor pid.

**Never put per-project data in an entry** ([ADR-015](../docs/DECISIONS.md#adr-015-harness-entries-are-global-only-no-per-project-data)).
Entries are written at global scope and serve every project, so `entry()` must not
derive a `cwd` from `env`, and `env` must never be filled with
`SIMPLE_CI_WORKSPACE_ROOT`, `SIMPLE_CI_INDEX_DB`, or `SIMPLE_CI_FAISS_PATH`.
**Entries carry arguments, never environment variables**
([ADR-024](../docs/DECISIONS.md)): every setting has a parallel CLI flag, and
the wizard passes an empty `env` to every builtin, so a generated entry has no
`env` block at all. Environment variables exist for debugging only, and every
one of ours is prefixed `SIMPLE_CI_`.
The server resolves the workspace at runtime
(`SIMPLE_CI_WORKSPACE_ROOT` > `--workspace` > MCP roots > the harness hook > cwd;
see [ADR-018](../docs/DECISIONS.md#adr-018-mcp-roots-first-harness-published-workspace-third)).

Detection is derived from `BINARIES` + `PROBE_ARGS` + `HOME_DIRS`: the binary is
run with the probe args (default `--version`) and a zero exit is the strong
signal; a binary merely on `PATH` counts, and a present directory under
`HOME_DIRS` is the fallback for harnesses with no CLI at all. Declare a binary
only when it answers without opening a GUI window.

`%APPDATA%` and `~` are expanded in `HOME_DIRS` and `*_CONFIGS`; entries whose
variables do not exist on the current platform are ignored.
