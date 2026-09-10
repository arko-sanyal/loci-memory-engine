# loci-memory-engine

A local, offline RAG (retrieval-augmented generation) pipeline over your own documents, built on
Ollama — plus **LOCI**, a heat-tiered memory engine growing underneath it that adds
category-adaptive retrieval, decaying entity/fact memory, and (eventually) goals, thoughts, and
forecasting on top of plain document chunk search.

Everything runs locally: embeddings and generation go through [Ollama](https://ollama.com), and
storage is one SQLite file (`sqlite-vec` for dense vector search + `FTS5` for lexical search,
fused via Reciprocal Rank Fusion) plus the LOCI heat/fact tables. No cloud calls, no API keys.

## What it does today

- **`rag ingest`** — chunk your documents (`.pdf`, `.txt`, `.md`) and embed them into the store.
- **`rag query`** — ask a question; the pipeline classifies the query into one of four categories
  (information extraction, knowledge update, multi-session reasoning, temporal reasoning — per
  [CARD](https://github.com/arko-sanyal/loci-card-papers/blob/master/papers/04_Category-Adaptive-Recall-Depth-CARD.pdf)),
  retrieves at a category-appropriate depth, and answers using only the retrieved context.
- **`loci-engine/`** — a growing heat-tiered memory core (`isymprev`/`qsymprev` schema, a
  decay/reinforcement/tiering heat law, and a `LociEngine` facade) that CARD's ranking and the
  ingestion path will progressively wire into as it's built out — see
  [`loci-engine/INDEX.md`](loci-engine/INDEX.md) for exactly what's built vs. planned right now.

## Install

Requires Python 3.11+ and [Ollama](https://ollama.com) running locally with two models pulled:

```bash
ollama pull nomic-embed-text
ollama pull llama3.2
ollama serve   # if not already running

python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

## Usage

```bash
# put .pdf/.txt/.md files in ./data (or point --data-dir elsewhere)
python -m rag ingest --data-dir ./data

python -m rag query "What does paper 05 say about goal-conditioned decay?"
python -m rag query "What changed recently?" --top-k 3   # override the category-adaptive depth
```

Both commands print a clear error (not a stack trace) if Ollama isn't reachable, or if the data
directory is missing/empty.

## Configuration

All environment-overridable, in `rag/config.py`:

| Variable | Default | Meaning |
|---|---|---|
| `RAG_OLLAMA_HOST` | `http://127.0.0.1:11434` | Ollama server URL |
| `RAG_EMBEDDING_MODEL` | `nomic-embed-text` | Embedding model |
| `RAG_LLM_MODEL` | `llama3.2` | Generation model |
| `RAG_CHROMA_DB_PATH` | `./chroma_db` | SQLite file backing the chunk store (name is historical — it's `sqlite-vec`+`FTS5` now, not Chroma) |
| `RAG_DATA_DIR` | `./data` | Where `ingest` reads documents from |
| `RAG_CHUNK_SIZE` / `RAG_CHUNK_OVERLAP` | `500` / `50` | Chunking parameters |
| `RAG_LOCI_DB_PATH` | — | Path for the LOCI heat/fact store (see `loci-engine/INDEX.md` for current knobs) |

## Running the tests

```bash
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q
```

Tests that need a live Ollama connection skip automatically when one isn't reachable; everything
else runs offline.

## Project structure

```
rag/                  the RAG pipeline: ingest, chunk, embed, query, CARD categorization, CLI
loci-engine/           the LOCI memory engine package (loci_engine/), its module index, and schema
docs/superpowers/      the design spec and implementation plans this was built from
data/                  default document ingestion directory (gitignored contents)
tests/                 pytest suite, mirrors the module layout above
```

## Related repos

This project used to bundle two things that don't actually depend on it — they've moved out so
each piece can be used, versioned, and documented on its own:

- **[loci-coordination-bus](https://github.com/arko-sanyal/loci-coordination-bus)** — the secure,
  local-first coordination bus (event log + task board + MCP server) used when multiple coding
  agents work on this repo at once. Install it as a dependency rather than expecting it inline.
- **[loci-card-papers](https://github.com/arko-sanyal/loci-card-papers)** — the nine LOCI/CARD
  research papers this engine implements, with a one-paragraph summary of what each contributes.

## Documentation

- [`docs/superpowers/specs/2026-09-10-loci-memory-engine-design.md`](docs/superpowers/specs/2026-09-10-loci-memory-engine-design.md) —
  the full design spec: schema, heat laws, read/write paths, interfaces, and what's deferred.
- [`loci-engine/INDEX.md`](loci-engine/INDEX.md) — a living module-by-module status table (which
  paper each module implements, what's done, what's planned).
- [`docs/STATUS-*.md`](docs) — dated status logs from past work sessions.
