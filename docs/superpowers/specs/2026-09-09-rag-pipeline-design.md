# RAG Pipeline — Design Spec

Date: 2026-09-09
Status: Approved for implementation planning

## Purpose

A local, fully offline Retrieval-Augmented Generation pipeline over the user's
own documents (PDFs, markdown, text files). Goal is learning/experimentation:
understand how each RAG stage works, keep the stack simple, iterate freely.

## Constraints & context

- Environment: Python 3.14.4, Ollama binary already installed (daemon not
  running by default — must be started with `ollama serve`).
- No production requirements (no auth, no multi-user, no deployment target).
- Prefer minimal dependencies over flexibility/abstraction (YAGNI).

## Chosen approach

**Ollama for everything.** Both the LLM (generation) and the embedding model
run through Ollama's local API. This avoids pulling in heavy ML dependencies
(torch, sentence-transformers) since Ollama already handles model execution.

Rejected alternatives:
- *Ollama LLM + sentence-transformers embeddings*: more embedding model
  choice, but adds a multi-GB torch dependency for no clear benefit here.
- *Pluggable provider abstraction* (swappable Ollama/Claude API/OpenAI
  backends via config): premature — no second backend is needed yet, and it
  adds abstraction overhead the project doesn't currently justify.

Models: `nomic-embed-text` for embeddings, a small instruction-tuned chat
model (e.g. `llama3.2` or `qwen2.5`) for generation — exact model pulled
during implementation/setup, user can swap via config.

## Architecture

Two entry points sharing one persisted vector store:

```
Ingest:  local docs → load → chunk → embed (Ollama) → store (Chroma, persisted to disk)
Query:   question → embed (Ollama) → similarity search (Chroma) → top-k chunks →
         prompt assembly → generate (Ollama LLM) → answer (+ cited sources)
```

Each stage is a small, independently testable module. No plugin/interface
abstraction — plain function/class boundaries are enough for swapping pieces
later if ever needed.

## Components

| Module | Responsibility | Depends on |
|---|---|---|
| `loader.py` | Read files from a `data/` directory (`.txt`, `.md`, `.pdf`) into raw text + source metadata | `pypdf` |
| `chunker.py` | Split text into overlapping chunks (fixed size + overlap, e.g. 500 chars / 50 overlap), pure logic, no I/O | none |
| `embeddings.py` | Wrap Ollama's embedding endpoint (`nomic-embed-text`) — text(s) → vectors | `ollama` client |
| `vectorstore.py` | Wrap a persisted Chroma collection — add chunks, similarity-search by query vector | `chromadb` |
| `llm.py` | Wrap Ollama's chat/generate endpoint — prompt (question + context) → answer | `ollama` client |
| `pipeline.py` | Orchestrate `ingest(data_dir)` and `query(question, top_k)` using the above | all of the above |
| `cli.py` | Thin command-line entry point: `python -m rag ingest`, `python -m rag query "..."` | `pipeline.py` |
| `config.py` | Model names, chunk size, top_k, data dir, db path — defaults overridable via env vars | none |

## Data flow

- **Ingest**: `pipeline.ingest()` walks `data/`, loads each file, chunks it
  (tagging each chunk with source filename + chunk index), embeds all chunks
  in a batch, and upserts into the Chroma collection keyed by a hash of
  source+chunk-index — re-running ingest on unchanged files is idempotent,
  not duplicated.
- **Query**: `pipeline.query()` embeds the question, retrieves top-k chunks
  from Chroma, assembles a prompt (system instruction + numbered context
  chunks + question), and calls the LLM. Returns the answer plus which
  sources were used, for traceability.

## Error handling

Fail fast with clear messages at the two likely failure points:
- Ollama not reachable (connection error) → tell the user to run
  `ollama serve` and pull the required models.
- `data/` directory missing or empty on ingest → clear message, no crash
  with a stack trace.

No retries or fallback logic beyond that — this is a learning project, not a
production service.

## Testing

- Unit tests for `chunker.py` (pure logic) and `loader.py` (small fixture
  files) — no Ollama required, run anywhere.
- Integration-style tests for `embeddings.py`, `llm.py`, `vectorstore.py`
  that are automatically skipped if Ollama isn't reachable, so the suite
  still runs in offline/CI-less conditions.

## Out of scope (for this iteration)

- Web/API content ingestion (local files only for now).
- Pluggable/swappable LLM or embedding backends.
- Any server/API layer — CLI usage only.
- Multi-user, auth, deployment concerns.
