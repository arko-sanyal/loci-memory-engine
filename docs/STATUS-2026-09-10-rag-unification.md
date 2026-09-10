# RAG Pipeline Unification — Status Update
**Date:** 2026-09-10
**Session:** Drive maintenance & RAG pipeline unification
**Status:** ✅ COMPLETE

---

## Background

Two independent RAG pipelines existed side by side, both touched on 2026-09-09:

1. **This repo** (`/04_Project-Codex-RAG`) — local RAG over 9 published LOCI/CARD
   papers, using Ollama (`nomic-embed-text` + `llama3.2`) and Chroma.
2. **`rag-cli`** (`Codex/create-a-x20` on a removable archive drive) — a separate,
   provider-neutral RAG CLI (Typer, pluggable Ollama/OpenAI-compatible providers).

## Which one works

Determined by running each, not by inspection:

| | This repo (`rag`) | `rag-cli` |
|---|---|---|
| Tests | **35/35 passing** | Never ran |
| Environment | Live `.venv`, functional | 3 separate venv attempts, all broken |

`rag-cli`'s environment was broken because it lived on a FAT32-formatted USB
drive (bridged into WSL over drvfs/9p): `venv` needs to symlink `bin/python3`
and `lib64 -> lib`, and FAT32 cannot hold symlinks. Confirmed directly —
`work/rag-cli/.venv/bin/python3` was a 0-byte file, not an interpreter. A live
probe (`python3 -m venv` run directly on the FAT32 drive) reproduced the exact
failure: `Operation not permitted: 'lib' -> 'lib64'`. Not a code defect in
`rag-cli` — a filesystem limitation everything on that drive was silently
hitting (it also explains unrelated broken installs found on the same drive,
e.g. a video-reasoning agent's vendored dependencies).

## Resolution

- **This repo (`rag`) is the single canonical RAG pipeline.** No functional
  changes were made here as part of this exercise — the unification was a
  decision, not a merge, since `rag-cli` never had a working baseline to merge
  from.
- The archive drive holding `rag-cli` was backed up (SHA-256 verified,
  zero mismatches), reformatted to NTFS to fix the root cause for any future
  work there, and restored. `rag-cli`'s source is preserved on that drive for
  reference but is not built on further as part of this project.
- No dependencies, APIs, or behavior in this repo changed.
