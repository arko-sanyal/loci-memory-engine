# LOCI Engine installer

A small Electron GUI that wraps this project's existing install path
(`.venv/bin/pip install -e '.[mcp]'`, the README's "Connect LOCI to your own
agent" section) into a wizard, and additionally wires up the PostCompact
recall hook (see `docs/superpowers/...` / the Claude Code auto-memory
project files for why that hook exists).

It does three real things, each a genuine action against the machine it
runs on - nothing here is a mock:

1. **Detects the environment**: finds a `python3`/`python`, checks whether
   `loci_engine` and `ollama` are already importable, and probes
   `localhost:11434` for a running Ollama with `nomic-embed-text` pulled.
2. **Installs `loci_engine`**: `pip install --user` from the bundled,
   dependency-minimal copy of the package in `resources/loci_engine_pkg/`
   (a standalone `pyproject.toml`, not this repo's monorepo one - see the
   note in that directory's `pyproject.toml` for why it only depends on
   `sqlite-vec`, not the whole `rag`/`trading_agent` tree).
3. **Wires the PostCompact hook**: writes `recall.py` and
   `postcompact_hook.py` (from `templates/*.tmpl`, self-contained - they
   depend only on `loci_engine` + `ollama`, not this project's `rag`
   package) into the chosen Claude Code auto-memory directory, then
   read-and-merges a `hooks.PostCompact` entry into that project's
   `.claude/settings.local.json` (never overwrites the file wholesale) and
   confirms that file is gitignored there.

## Scope, honestly stated

v1 targets Claude Code specifically (the PostCompact hook is a Claude Code
concept) and assumes the target machine already has Python 3.11+ and,
separately, Ollama running with `nomic-embed-text` pulled for the recall
tool's embeddings - the wizard's detection step tells you which of those
are missing rather than installing them for you.

## Building

```bash
npm install
npm run start    # run the wizard unpacked, for development
npm run dist      # produce a distributable via electron-builder
```

`npm run dist` needs to run on the target OS (or under Wine for a Windows
build from Linux) since `electron-builder` packages native binaries per
platform. From WSL2 with no Wine installed, build the Windows target with
the host's native Node instead, e.g. via `powershell.exe`:

```bash
powershell.exe -Command "cd <windows-path-to-this-folder>; npm install; npm run dist"
```
