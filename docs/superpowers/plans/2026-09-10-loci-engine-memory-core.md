# LOCI Engine — Memory Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the first working, tested slice of the LOCI memory engine — a root-level
`loci-engine/` package with a unified sqlite-vec+FTS5 chunk store (replacing Chroma), the
dual-stream SQLite schema (paper 09 Appendix B), heat decay/reinforcement, and a thin store +
facade.

**Architecture:** A new top-level package `loci-engine/loci_engine/` (directory literally named
`loci-engine` per user instruction; the importable Python package inside it is `loci_engine`,
since hyphens are not legal in Python identifiers — this mirrors the naming of the author's
existing private repo `arkosanyal/loci-engine`). `rag/pipeline.py` and `rag/card.py` become
**consumers** of `loci_engine` instead of owning memory logic. Chunk retrieval moves from Chroma
to a single-SQLite-file `sqlite-vec` (dense ANN) + `FTS5` (sparse BM25) store fused via Reciprocal
Rank Fusion (RRF) — this is a straight replacement, not an incremental migration, since the two
storage models aren't interchangeable at the code level.

**Tech Stack:** Python 3.11+, stdlib `sqlite3` with the `sqlite-vec` loadable extension, stdlib
`FTS5` (confirmed compiled into this environment's SQLite 3.46.1 via
`pragma compile_options` → `ENABLE_FTS5`), `pytest`.

**Spec:** `docs/superpowers/specs/2026-09-10-loci-memory-engine-design.md` (papers index, revised
2026-09-10 to un-defer papers 01/02 and adopt sqlite-vec+FTS5 — see that file's header). This plan
implements a subset of that spec's §3 repository layout: the chunk-retrieval store (`vectors.py`)
and the heat/fact core (`schema.sql`, `heat.py`, `store.py`, facade). Forecasting/reflection/mood
(`forecast.py`, `reflect.py`), thoughts, goals, and CARD-on-real-heat are later plans — see
"What this plan deliberately does not do" at the end.

## Global Constraints

- Directory name at repo root: `loci-engine` (hyphen, matches `arkosanyal/loci-engine`). Python
  package inside it: `loci_engine` (underscore) — e.g. `loci-engine/loci_engine/__init__.py`.
- Embedding dimension: 768 (`nomic-embed-text`, this repo's existing embedding model — see
  `rag/config.py:4`). The `vec0` virtual table is created with a fixed `float[768]` column.
- RRF fusion constant: `k = 60` (standard RRF default; also recorded as
  `RAG_LOCI_RRF_K` in the spec's §10 config table for later plans to reuse).
- Heat range for `isymprev` entities: **[0.0, 3.0]** inclusive (paper 09 Appendix B.1).
- Passive decay: `heat *= 0.95` per elapsed day (paper 09 Appendix B.1), applied lazily at read
  time (no background job in this plan — a later plan's `materialize sweep` may add one).
- Heat increments (paper 09 Appendix B.1): direct access `+1.0` (and resets the decay clock),
  1-hop neighbor `+0.5`, 2-hop `+0.25`, 3-hop `+0.125`. This plan implements the increment
  function generically over `hop: int`; graph-neighbor propagation (walking the entity graph to
  apply 1/2/3-hop increments to *other* entities) is out of scope for this plan — no entity graph
  exists yet. Only direct access (`hop=0`) is wired into the facade here.
- Storage tier derived from heat (paper 09 Appendix B.1): HOT if `heat > 1.5`, WARM if
  `heat > 0.5`, else COLD. This plan only computes the tier label; it does not implement the
  physical HOT/WARM/COLD placement — the design spec explicitly defers that (§1: "hardware tiers
  are derived labels only").
- `isymprev` schema (paper 09 Appendix B.1, verbatim):
  ```sql
  CREATE TABLE isymprev (
    entity TEXT PRIMARY KEY,
    gist TEXT,                    -- one-line narrative summary
    heat REAL DEFAULT 1.0,        -- 0.0-3.0, decays 0.95x/day
    confidence REAL DEFAULT 1.0,
    uses INTEGER DEFAULT 0,
    last_used REAL,               -- unix timestamp
    expanded TEXT                 -- full description if available
  );
  ```
- `qsymprev` schema (paper 09 Appendix B.2, verbatim):
  ```sql
  CREATE TABLE qsymprev (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity TEXT NOT NULL,         -- foreign key to isymprev.entity
    key TEXT NOT NULL,            -- "port", "MRR", "serial", "height"
    value TEXT NOT NULL,          -- exact value: "8766", "0.933", "6ft"
    unit TEXT,                    -- "tcp", "score", "feet", "date"
    ts REAL,                      -- when this fact was recorded
    heat REAL DEFAULT 1.0,        -- inherits from parent isymprev entity
    confidence REAL DEFAULT 1.0,
    source TEXT                   -- provenance: "measured", "paper", "user"
  );
  CREATE INDEX idx_qsymprev_entity ON qsymprev(entity);
  CREATE INDEX idx_qsymprev_key ON qsymprev(key);
  ```
- Every task that touches `loci-engine/` must update `loci-engine/INDEX.md` in the same commit
  (Task 1 establishes this file; `agent_instructions.md` already carries the standing rule).

---

### Task 1: Scaffold `loci-engine/` with the sqlite-vec+FTS5 chunk store

**Files:**
- Create: `loci-engine/loci_engine/__init__.py`
- Create: `loci-engine/loci_engine/vectors.py`
- Create: `loci-engine/INDEX.md`
- Modify: `pyproject.toml` (register the new package, swap `chromadb` for `sqlite-vec`)
- Modify: `rag/pipeline.py:9,33,42` (import `VectorStore` from `loci_engine.vectors` instead of
  `LociEngine` from `rag.loci`)
- Delete: `rag/loci.py`
- Test: `tests/test_vectors.py` (renamed from `tests/test_loci.py`, rewritten for the new store)
- Modify: `tests/test_pipeline.py:72` (import updated)

**Interfaces:**
- Produces: `loci_engine.vectors.VectorStore(path: str)` with
  `.add(ids: list[str], embeddings: list[list[float]], texts: list[str], metadatas: list[dict]) -> None`
  and `.query(embedding: list[float], top_k: int = 5) -> list[dict]` — each result dict has
  `id`, `text`, `metadata`, `distance` (dense cosine-ish distance if the id came from the vec0
  list, else `None` if it was fused in from the FTS5-only side), same shape the old Chroma-backed
  class returned so `rag/pipeline.py` and `rag/card.py` need no further changes this task.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_vectors.py`:

```python
import json

from loci_engine.vectors import VectorStore


def test_add_then_query_returns_closest_dense_match_first(tmp_path):
    store = VectorStore(str(tmp_path / "loci.db"))
    store.add(
        ids=["a", "b"],
        embeddings=[[1.0] + [0.0] * 767, [0.0, 1.0] + [0.0] * 766],
        texts=["points right", "points up"],
        metadatas=[{"source": "a.txt"}, {"source": "b.txt"}],
    )

    results = store.query(embedding=[0.9, 0.1] + [0.0] * 766, top_k=1)

    assert results[0]["id"] == "a"
    assert results[0]["text"] == "points right"
    assert results[0]["metadata"] == {"source": "a.txt"}


def test_add_with_same_id_updates_instead_of_duplicating(tmp_path):
    store = VectorStore(str(tmp_path / "loci.db"))
    store.add(
        ids=["a"],
        embeddings=[[1.0] + [0.0] * 767],
        texts=["original text"],
        metadatas=[{"source": "a.txt"}],
    )

    store.add(
        ids=["a"],
        embeddings=[[1.0] + [0.0] * 767],
        texts=["updated text"],
        metadatas=[{"source": "a.txt"}],
    )

    results = store.query(embedding=[1.0] + [0.0] * 767, top_k=10)

    assert len(results) == 1
    assert results[0]["text"] == "updated text"


def test_fts5_lexical_match_surfaces_a_result_with_no_dense_neighbor(tmp_path):
    store = VectorStore(str(tmp_path / "loci.db"))
    # "lexical" embedding is orthogonal/far from the query embedding on purpose:
    # only the BM25 side should be able to find it.
    store.add(
        ids=["lexical"],
        embeddings=[[0.0, 0.0, 1.0] + [0.0] * 765],
        texts=["the quick brown fox jumps over the lazy dog"],
        metadatas=[{"source": "fox.txt"}],
    )

    results = store.query(
        embedding=[1.0] + [0.0] * 767,  # nowhere near the stored embedding
        top_k=5,
        query_text="quick brown fox",
    )

    assert any(r["id"] == "lexical" for r in results)


def test_query_without_query_text_still_works_dense_only(tmp_path):
    store = VectorStore(str(tmp_path / "loci.db"))
    store.add(
        ids=["a"],
        embeddings=[[1.0] + [0.0] * 767],
        texts=["points right"],
        metadatas=[{"source": "a.txt"}],
    )

    results = store.query(embedding=[1.0] + [0.0] * 767, top_k=5)

    assert results[0]["id"] == "a"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_vectors.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'loci_engine'`

- [ ] **Step 3: Write the implementation**

Create `loci-engine/loci_engine/__init__.py` (empty for now — populated by Task 5):

```python
```

Create `loci-engine/loci_engine/vectors.py`:

```python
import json
import sqlite3
import struct

EMBEDDING_DIM = 768
RRF_K = 60


def _to_blob(vector: list[float]) -> bytes:
    return struct.pack(f"{len(vector)}f", *vector)


class VectorStore:
    def __init__(self, path: str):
        self._conn = sqlite3.connect(path)
        self._conn.enable_load_extension(True)
        import sqlite_vec

        sqlite_vec.load(self._conn)
        self._conn.enable_load_extension(False)
        self._conn.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS chunk_meta (
                chunk_id TEXT PRIMARY KEY,
                rowid_map INTEGER UNIQUE,
                text TEXT NOT NULL,
                metadata TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
                embedding float[{EMBEDDING_DIM}]
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS fts_chunks USING fts5(
                chunk_id UNINDEXED, text
            );
            """
        )
        self._conn.commit()

    def add(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        texts: list[str],
        metadatas: list[dict],
    ) -> None:
        for chunk_id, embedding, text, metadata in zip(ids, embeddings, texts, metadatas):
            existing = self._conn.execute(
                "SELECT rowid_map FROM chunk_meta WHERE chunk_id = ?", (chunk_id,)
            ).fetchone()
            if existing is not None:
                row_id = existing[0]
                self._conn.execute(
                    "UPDATE chunk_meta SET text = ?, metadata = ? WHERE chunk_id = ?",
                    (text, json.dumps(metadata), chunk_id),
                )
                self._conn.execute(
                    "UPDATE vec_chunks SET embedding = ? WHERE rowid = ?",
                    (_to_blob(embedding), row_id),
                )
                self._conn.execute(
                    "UPDATE fts_chunks SET text = ? WHERE chunk_id = ?", (text, chunk_id)
                )
            else:
                cursor = self._conn.execute(
                    "INSERT INTO chunk_meta (chunk_id, text, metadata) VALUES (?, ?, ?)",
                    (chunk_id, text, json.dumps(metadata)),
                )
                row_id = cursor.lastrowid
                self._conn.execute(
                    "UPDATE chunk_meta SET rowid_map = ? WHERE chunk_id = ?",
                    (row_id, chunk_id),
                )
                self._conn.execute(
                    "INSERT INTO vec_chunks (rowid, embedding) VALUES (?, ?)",
                    (row_id, _to_blob(embedding)),
                )
                self._conn.execute(
                    "INSERT INTO fts_chunks (chunk_id, text) VALUES (?, ?)", (chunk_id, text)
                )
        self._conn.commit()

    def query(
        self,
        embedding: list[float],
        top_k: int = 5,
        query_text: str | None = None,
    ) -> list[dict]:
        fetch_k = max(top_k * 4, top_k)
        dense_rows = self._conn.execute(
            """
            SELECT chunk_meta.chunk_id, vec_chunks.distance
            FROM vec_chunks
            JOIN chunk_meta ON chunk_meta.rowid_map = vec_chunks.rowid
            WHERE embedding MATCH ? AND k = ?
            ORDER BY distance
            """,
            (_to_blob(embedding), fetch_k),
        ).fetchall()
        dense_rank = {chunk_id: rank for rank, (chunk_id, _) in enumerate(dense_rows)}
        dense_distance = {chunk_id: distance for chunk_id, distance in dense_rows}

        sparse_rank: dict[str, int] = {}
        if query_text:
            sparse_rows = self._conn.execute(
                """
                SELECT chunk_id FROM fts_chunks
                WHERE fts_chunks MATCH ? ORDER BY bm25(fts_chunks) LIMIT ?
                """,
                (query_text, fetch_k),
            ).fetchall()
            sparse_rank = {chunk_id: rank for rank, (chunk_id,) in enumerate(sparse_rows)}

        all_ids = set(dense_rank) | set(sparse_rank)
        scored = [
            (
                chunk_id,
                (1.0 / (RRF_K + dense_rank[chunk_id] + 1) if chunk_id in dense_rank else 0.0)
                + (1.0 / (RRF_K + sparse_rank[chunk_id] + 1) if chunk_id in sparse_rank else 0.0),
            )
            for chunk_id in all_ids
        ]
        scored.sort(key=lambda pair: pair[1], reverse=True)

        results = []
        for chunk_id, _ in scored[:top_k]:
            row = self._conn.execute(
                "SELECT text, metadata FROM chunk_meta WHERE chunk_id = ?", (chunk_id,)
            ).fetchone()
            text, metadata_json = row
            results.append(
                {
                    "id": chunk_id,
                    "text": text,
                    "metadata": json.loads(metadata_json),
                    "distance": dense_distance.get(chunk_id),
                }
            )
        return results
```

Delete `rag/loci.py`.

- [ ] **Step 4: Register the package and swap the dependency**

In `pyproject.toml`, change:

```toml
    "chromadb>=1.5.9",
```
to:
```toml
    "sqlite-vec>=0.1.9",
```

And change:
```toml
[tool.setuptools.packages.find]
include = ["rag*"]
```
to:
```toml
[tool.setuptools.packages.find]
include = ["rag*", "loci_engine*"]
```

Run: `pip install -e .` (or `uv pip install -e .`, matching however this repo's `.venv` was set
up) so the new package is importable and `chromadb` is removed from the environment (leave it
installed if other code still imports it directly — check with
`grep -rn "chromadb\|from rag.loci\|from rag import loci" --include=*.py .` before removing it
from the environment; the import removal in `pyproject.toml` is what matters for the dependency
declaration).

- [ ] **Step 5: Repoint the pipeline**

In `rag/pipeline.py`, change:
```python
from rag.loci import LociEngine
```
to:
```python
from loci_engine.vectors import VectorStore
```
And update both call sites (`ingest` and `query`) from `LociEngine(path=config.CHROMA_DB_PATH)` to
`VectorStore(path=config.CHROMA_DB_PATH)` — the config key name stays for now (renaming it is a
separate, cosmetic follow-up not worth coupling to this task). In `query()`, also pass
`query_text=question` to `VectorStore.query(...)` so CARD's categories benefit from the FTS5 side
of the fusion, not just dense ANN.

In `tests/test_pipeline.py`, change:
```python
    from rag.loci import LociEngine

    engine = LociEngine(path=config.CHROMA_DB_PATH)
```
to:
```python
    from loci_engine.vectors import VectorStore

    engine = VectorStore(path=config.CHROMA_DB_PATH)
```

- [ ] **Step 6: Run the full suite**

Run: `pytest -q`
Expected: `35 passed` (same count as before — this task replaces the storage engine behind the
same public shape, so no test's assertions about `pipeline.ingest`/`pipeline.query` behavior
should need to change).

- [ ] **Step 7: Create the living index**

Create `loci-engine/INDEX.md`:

```markdown
# LOCI Engine — Module Index

This file is a **living document**. Every task that adds, removes, or changes behavior in
`loci-engine/` must update the relevant row(s) below in the same commit. See
`agent_instructions.md` for the standing rule that enforces this.

Design spec: `docs/superpowers/specs/2026-09-10-loci-memory-engine-design.md`
Build plans: `docs/superpowers/plans/2026-09-10-loci-engine-memory-core.md` (this is Plan 1 of N)

| Module | Paper(s) | Status | Notes |
|---|---|---|---|
| `loci_engine/vectors.py` | 09 (SLP store concept) | Done | sqlite-vec (dense) + FTS5 (sparse) + RRF, single SQLite file. Replaces `rag/loci.py` (Chroma). |
| `loci_engine/schema.sql` | 09 (Appendix B) | Planned (Task 2) | `isymprev` + `qsymprev` tables |
| `loci_engine/heat.py` | 09 (Appendix B), 05 | Planned (Task 3) | Decay 0.95x/day, hop increments, HOT/WARM/COLD tiers |
| `loci_engine/store.py` | 09 | Planned (Task 4) | SQLite CRUD over `isymprev`/`qsymprev` |
| `loci_engine/__init__.py` (`LociEngine` facade) | 09 | Planned (Task 5) | `remember`/`recall`/`add_fact`/`get_facts` |
| Thoughts spectrum | 03 | Not started | Plan 3 |
| Goal retainers / GCSD | 05, 06 | Not started | Plan 3 |
| Entity graph / spreading activation (1/2/3-hop) | 07, 09 | Not started | Plan 3 |
| CARD integration with `loci_engine` heat | 04 | Not started | Plan 2 — `rag/card.py` still ranks by raw metadata dates, not real heat |
| `forecast.py` (r+e forecasting, mood) | 01 | Not started | Plan 4 — θ-gate (0.82), mood law, crisis/venting split all specified, not yet built |
| `reflect.py` (e+r reflection-on-action) | 02 | Not started | Plan 4 — behavioral-surprise update, anti-hallucination invariant specified, not yet built |
| Pre-registered validation harness (LongMemEval-style, H1-H4/H0) | 01, 02 | Deferred (design spec §1) | Separate from building the mechanisms themselves |
```

- [ ] **Step 8: Commit**

```bash
git add loci-engine/ pyproject.toml rag/pipeline.py \
  tests/test_vectors.py tests/test_pipeline.py
git rm rag/loci.py tests/test_loci.py
git commit -m "$(cat <<'EOF'
Scaffold loci-engine/ package with sqlite-vec+FTS5 chunk store

Replaces the Chroma-backed rag/loci.py with a single-SQLite-file
dense (sqlite-vec) + sparse (FTS5) store fused via RRF, per the
revised design spec. No change to rag/pipeline.py's public shape.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `schema.sql` — dual-stream tables

**Files:**
- Create: `loci-engine/loci_engine/schema.sql`
- Create: `loci-engine/loci_engine/db.py` (schema application helper — small enough to fold into
  this task rather than spin out a separate one)
- Test: `tests/test_loci_db.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `loci_engine.db.open_db(path: str) -> sqlite3.Connection` — a connection with the
  schema already applied (idempotent: safe to call against an existing db file).

- [ ] **Step 1: Write the failing test**

Create `tests/test_loci_db.py`:

```python
from loci_engine.db import open_db


def test_open_db_creates_isymprev_and_qsymprev_tables(tmp_path):
    conn = open_db(str(tmp_path / "loci.db"))

    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }

    assert "isymprev" in tables
    assert "qsymprev" in tables


def test_open_db_is_idempotent(tmp_path):
    db_path = str(tmp_path / "loci.db")

    open_db(db_path).close()
    conn = open_db(db_path)  # must not raise "table already exists"

    conn.execute(
        "INSERT INTO isymprev (entity, heat, confidence, uses, last_used) "
        "VALUES ('e1', 1.0, 1.0, 0, 0.0)"
    )
    conn.commit()
    row = conn.execute("SELECT entity FROM isymprev WHERE entity = 'e1'").fetchone()

    assert row == ("e1",)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_loci_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'loci_engine.db'`

- [ ] **Step 3: Write the schema and the open helper**

Create `loci-engine/loci_engine/schema.sql`:

```sql
CREATE TABLE IF NOT EXISTS isymprev (
    entity TEXT PRIMARY KEY,
    gist TEXT,
    heat REAL DEFAULT 1.0,
    confidence REAL DEFAULT 1.0,
    uses INTEGER DEFAULT 0,
    last_used REAL,
    expanded TEXT
);

CREATE TABLE IF NOT EXISTS qsymprev (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    unit TEXT,
    ts REAL,
    heat REAL DEFAULT 1.0,
    confidence REAL DEFAULT 1.0,
    source TEXT
);

CREATE INDEX IF NOT EXISTS idx_qsymprev_entity ON qsymprev(entity);
CREATE INDEX IF NOT EXISTS idx_qsymprev_key ON qsymprev(key);
```

Create `loci-engine/loci_engine/db.py`:

```python
import sqlite3
from importlib import resources


def open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    schema = resources.files("loci_engine").joinpath("schema.sql").read_text()
    conn.executescript(schema)
    conn.commit()
    return conn
```

Add this to `pyproject.toml` so setuptools includes `schema.sql` in the editable install:

```toml
[tool.setuptools.package-data]
loci_engine = ["schema.sql"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_loci_db.py -v`
Expected: `2 passed`

- [ ] **Step 5: Update the index**

In `loci-engine/INDEX.md`, change the `loci_engine/schema.sql` row's Status from
`Planned (Task 2)` to `Done`, Notes: "Applied via `db.open_db()`, idempotent
(`CREATE TABLE IF NOT EXISTS`)."

- [ ] **Step 6: Commit**

```bash
git add loci-engine/loci_engine/schema.sql loci-engine/loci_engine/db.py \
  loci-engine/INDEX.md pyproject.toml tests/test_loci_db.py
git commit -m "$(cat <<'EOF'
Add loci_engine dual-stream schema (isymprev/qsymprev) per paper 09 Appendix B

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `heat.py` — decay, reinforcement, tiering

**Files:**
- Create: `loci-engine/loci_engine/heat.py`
- Test: `tests/test_heat.py`

**Interfaces:**
- Consumes: nothing new (pure functions over floats/timestamps).
- Produces:
  - `loci_engine.heat.decay(heat: float, days_elapsed: float) -> float`
  - `loci_engine.heat.apply_increment(heat: float, hop: int) -> float`
  - `loci_engine.heat.tier(heat: float) -> str` (returns `"HOT"`, `"WARM"`, or `"COLD"`)
  - `loci_engine.heat.HEAT_MIN = 0.0`, `loci_engine.heat.HEAT_MAX = 3.0`
  - `loci_engine.heat.HOP_INCREMENTS = {0: 1.0, 1: 0.5, 2: 0.25, 3: 0.125}`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_heat.py`:

```python
import pytest

from loci_engine.heat import HEAT_MAX, HEAT_MIN, apply_increment, decay, tier


def test_decay_applies_0_95_per_day():
    assert decay(1.0, days_elapsed=1) == pytest.approx(0.95)
    assert decay(1.0, days_elapsed=2) == pytest.approx(0.95 ** 2)


def test_decay_with_zero_elapsed_time_is_a_no_op():
    assert decay(2.0, days_elapsed=0) == pytest.approx(2.0)


def test_direct_access_increments_by_one():
    assert apply_increment(1.0, hop=0) == pytest.approx(2.0)


def test_hop_increments_match_paper_09_appendix_b():
    assert apply_increment(1.0, hop=1) == pytest.approx(1.5)
    assert apply_increment(1.0, hop=2) == pytest.approx(1.25)
    assert apply_increment(1.0, hop=3) == pytest.approx(1.125)


def test_increment_clamps_to_heat_max():
    assert apply_increment(2.9, hop=0) == pytest.approx(HEAT_MAX)


def test_decay_clamps_to_heat_min():
    assert decay(0.001, days_elapsed=100) >= HEAT_MIN


def test_tier_thresholds():
    assert tier(1.6) == "HOT"
    assert tier(1.5) == "WARM"  # boundary is exclusive per paper 09 (heat > 1.5)
    assert tier(0.6) == "WARM"
    assert tier(0.5) == "COLD"  # boundary is exclusive (heat > 0.5)
    assert tier(0.0) == "COLD"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_heat.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'loci_engine.heat'`

- [ ] **Step 3: Write the implementation**

Create `loci-engine/loci_engine/heat.py`:

```python
HEAT_MIN = 0.0
HEAT_MAX = 3.0
DECAY_RATE_PER_DAY = 0.95
HOP_INCREMENTS = {0: 1.0, 1: 0.5, 2: 0.25, 3: 0.125}


def decay(heat: float, days_elapsed: float) -> float:
    decayed = heat * (DECAY_RATE_PER_DAY ** days_elapsed)
    return max(HEAT_MIN, decayed)


def apply_increment(heat: float, hop: int) -> float:
    incremented = heat + HOP_INCREMENTS[hop]
    return min(HEAT_MAX, incremented)


def tier(heat: float) -> str:
    if heat > 1.5:
        return "HOT"
    if heat > 0.5:
        return "WARM"
    return "COLD"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_heat.py -v`
Expected: `7 passed`

- [ ] **Step 5: Update the index**

In `loci-engine/INDEX.md`, change the `loci_engine/heat.py` row's Status to `Done`, Notes:
"Implements paper 09 Appendix B.1's decay/increment/tier law only (direct-access hop=0 wired
into the facade; 1/2/3-hop neighbor propagation needs an entity graph — deferred to Plan 3).
Paper 05's per-tier half-life model (critical/high/decision/normal) and paper 06's GCSD switch
are a separate, richer heat law for a later plan — do not conflate the two."

- [ ] **Step 6: Commit**

```bash
git add loci-engine/loci_engine/heat.py loci-engine/INDEX.md tests/test_heat.py
git commit -m "$(cat <<'EOF'
Add loci_engine heat law: decay/increment/tier per paper 09 Appendix B

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: `store.py` — SQLite CRUD over the dual streams

**Files:**
- Create: `loci-engine/loci_engine/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `loci_engine.db.open_db` (Task 2), `loci_engine.heat.decay` / `apply_increment`
  (Task 3).
- Produces:
  - `loci_engine.store.remember_entity(conn, entity: str, gist: str | None = None, expanded: str | None = None, now: float | None = None) -> None`
  - `loci_engine.store.touch_entity(conn, entity: str, hop: int = 0, now: float | None = None) -> float` (applies decay since `last_used`, then the hop increment; returns the new heat; raises `KeyError` if the entity doesn't exist)
  - `loci_engine.store.get_entity(conn, entity: str, now: float | None = None) -> dict | None` (returns current decayed heat without mutating storage — a read-only "peek")
  - `loci_engine.store.add_fact(conn, entity: str, key: str, value: str, unit: str | None = None, source: str | None = None, now: float | None = None) -> int` (returns the new `qsymprev.id`; raises `KeyError` if `entity` isn't in `isymprev` yet)
  - `loci_engine.store.get_facts(conn, entity: str, key: str | None = None) -> list[dict]`

All `now` parameters default to `time.time()` when `None` — exposed as a parameter (not a hidden
call) so tests can pin timestamps instead of sleeping.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_store.py`:

```python
import pytest

from loci_engine.db import open_db
from loci_engine.store import (
    add_fact,
    get_entity,
    get_facts,
    remember_entity,
    touch_entity,
)


@pytest.fixture
def conn(tmp_path):
    return open_db(str(tmp_path / "loci.db"))


def test_remember_entity_creates_row_with_base_heat(conn):
    remember_entity(conn, "battery_capacity", gist="how much charge it holds", now=1000.0)

    entity = get_entity(conn, "battery_capacity", now=1000.0)

    assert entity["entity"] == "battery_capacity"
    assert entity["gist"] == "how much charge it holds"
    assert entity["heat"] == pytest.approx(1.0)


def test_remember_entity_is_idempotent_and_does_not_reset_heat(conn):
    remember_entity(conn, "battery_capacity", now=1000.0)
    touch_entity(conn, "battery_capacity", hop=0, now=1000.0)  # heat -> 2.0

    remember_entity(conn, "battery_capacity", now=2000.0)  # re-mention, no explicit touch

    entity = get_entity(conn, "battery_capacity", now=2000.0)
    assert entity["heat"] == pytest.approx(2.0)


def test_touch_entity_applies_decay_then_increment(conn):
    remember_entity(conn, "battery_capacity", now=0.0)

    one_day_later = 86400.0
    new_heat = touch_entity(conn, "battery_capacity", hop=0, now=one_day_later)

    # decay(1.0, 1 day) = 0.95, then +1.0 direct-access increment = 1.95
    assert new_heat == pytest.approx(1.95)


def test_touch_entity_raises_for_unknown_entity(conn):
    with pytest.raises(KeyError):
        touch_entity(conn, "does_not_exist", now=1000.0)


def test_get_entity_returns_none_for_unknown_entity(conn):
    assert get_entity(conn, "does_not_exist", now=1000.0) is None


def test_get_entity_applies_decay_without_mutating_storage(conn):
    remember_entity(conn, "battery_capacity", now=0.0)

    peeked = get_entity(conn, "battery_capacity", now=86400.0)
    assert peeked["heat"] == pytest.approx(0.95)

    raw_row = conn.execute(
        "SELECT heat FROM isymprev WHERE entity = 'battery_capacity'"
    ).fetchone()
    assert raw_row[0] == pytest.approx(1.0)


def test_add_fact_requires_existing_entity(conn):
    with pytest.raises(KeyError):
        add_fact(conn, "does_not_exist", "port", "8766", now=1000.0)


def test_add_fact_and_get_facts_roundtrip(conn):
    remember_entity(conn, "server_config", now=1000.0)

    fact_id = add_fact(
        conn, "server_config", "port", "8766", unit="tcp", source="measured", now=1000.0
    )

    facts = get_facts(conn, "server_config")
    assert len(facts) == 1
    assert facts[0]["id"] == fact_id
    assert facts[0]["key"] == "port"
    assert facts[0]["value"] == "8766"
    assert facts[0]["unit"] == "tcp"
    assert facts[0]["source"] == "measured"


def test_get_facts_filters_by_key(conn):
    remember_entity(conn, "server_config", now=1000.0)
    add_fact(conn, "server_config", "port", "8766", now=1000.0)
    add_fact(conn, "server_config", "region", "us-east", now=1000.0)

    facts = get_facts(conn, "server_config", key="port")

    assert len(facts) == 1
    assert facts[0]["key"] == "port"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'loci_engine.store'`

- [ ] **Step 3: Write the implementation**

Create `loci-engine/loci_engine/store.py`:

```python
import time

from loci_engine.heat import apply_increment, decay


def _decayed_heat(row_heat: float, last_used: float, now: float) -> float:
    days_elapsed = max(0.0, (now - last_used) / 86400.0)
    return decay(row_heat, days_elapsed)


def remember_entity(
    conn,
    entity: str,
    gist: str | None = None,
    expanded: str | None = None,
    now: float | None = None,
) -> None:
    now = time.time() if now is None else now
    conn.execute(
        """
        INSERT INTO isymprev (entity, gist, expanded, heat, confidence, uses, last_used)
        VALUES (?, ?, ?, 1.0, 1.0, 0, ?)
        ON CONFLICT(entity) DO UPDATE SET
            gist = COALESCE(excluded.gist, isymprev.gist),
            expanded = COALESCE(excluded.expanded, isymprev.expanded)
        """,
        (entity, gist, expanded, now),
    )
    conn.commit()


def get_entity(conn, entity: str, now: float | None = None) -> dict | None:
    now = time.time() if now is None else now
    row = conn.execute(
        "SELECT entity, gist, heat, confidence, uses, last_used, expanded "
        "FROM isymprev WHERE entity = ?",
        (entity,),
    ).fetchone()
    if row is None:
        return None
    entity_, gist, heat, confidence, uses, last_used, expanded = row
    return {
        "entity": entity_,
        "gist": gist,
        "heat": _decayed_heat(heat, last_used, now),
        "confidence": confidence,
        "uses": uses,
        "last_used": last_used,
        "expanded": expanded,
    }


def touch_entity(conn, entity: str, hop: int = 0, now: float | None = None) -> float:
    now = time.time() if now is None else now
    row = conn.execute(
        "SELECT heat, last_used FROM isymprev WHERE entity = ?", (entity,)
    ).fetchone()
    if row is None:
        raise KeyError(entity)
    heat, last_used = row
    decayed = _decayed_heat(heat, last_used, now)
    new_heat = apply_increment(decayed, hop)
    conn.execute(
        "UPDATE isymprev SET heat = ?, uses = uses + 1, last_used = ? WHERE entity = ?",
        (new_heat, now, entity),
    )
    conn.commit()
    return new_heat


def add_fact(
    conn,
    entity: str,
    key: str,
    value: str,
    unit: str | None = None,
    source: str | None = None,
    now: float | None = None,
) -> int:
    now = time.time() if now is None else now
    parent = get_entity(conn, entity, now=now)
    if parent is None:
        raise KeyError(entity)
    cursor = conn.execute(
        "INSERT INTO qsymprev (entity, key, value, unit, ts, heat, confidence, source) "
        "VALUES (?, ?, ?, ?, ?, ?, 1.0, ?)",
        (entity, key, value, unit, now, parent["heat"], source),
    )
    conn.commit()
    return cursor.lastrowid


def get_facts(conn, entity: str, key: str | None = None) -> list[dict]:
    if key is None:
        rows = conn.execute(
            "SELECT id, entity, key, value, unit, ts, heat, confidence, source "
            "FROM qsymprev WHERE entity = ?",
            (entity,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, entity, key, value, unit, ts, heat, confidence, source "
            "FROM qsymprev WHERE entity = ? AND key = ?",
            (entity, key),
        ).fetchall()
    return [
        {
            "id": r[0],
            "entity": r[1],
            "key": r[2],
            "value": r[3],
            "unit": r[4],
            "ts": r[5],
            "heat": r[6],
            "confidence": r[7],
            "source": r[8],
        }
        for r in rows
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_store.py -v`
Expected: `9 passed`

- [ ] **Step 5: Update the index**

In `loci-engine/INDEX.md`, change the `loci_engine/store.py` row's Status to `Done`, Notes:
"`remember_entity`/`touch_entity`/`get_entity`/`add_fact`/`get_facts`. `get_entity` is a
non-mutating decay peek; only `touch_entity` persists a new heat value."

- [ ] **Step 6: Commit**

```bash
git add loci-engine/loci_engine/store.py loci-engine/INDEX.md tests/test_store.py
git commit -m "$(cat <<'EOF'
Add loci_engine store: CRUD over isymprev/qsymprev with lazy heat decay

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: `LociEngine` facade

**Files:**
- Modify: `loci-engine/loci_engine/__init__.py`
- Test: `tests/test_loci_engine_facade.py`

**Interfaces:**
- Consumes: `loci_engine.db.open_db`, everything in `loci_engine.store`.
- Produces: `loci_engine.LociEngine`, the package's public entry point:
  - `LociEngine(path: str)` — opens (and initializes, if needed) the SQLite db at `path`.
  - `.remember(entity: str, gist: str | None = None, expanded: str | None = None) -> None`
  - `.recall(entity: str, hop: int = 0) -> dict | None` — touches the entity (applies decay +
    increment, persists it) and returns the resulting record, or `None` if unknown.
  - `.add_fact(entity: str, key: str, value: str, unit: str | None = None, source: str | None = None) -> int`
  - `.get_facts(entity: str, key: str | None = None) -> list[dict]`
  - `.close() -> None`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_loci_engine_facade.py`:

```python
import pytest

from loci_engine import LociEngine


@pytest.fixture
def engine(tmp_path):
    return LociEngine(str(tmp_path / "loci.db"))


def test_remember_then_recall_returns_touched_entity(engine):
    engine.remember("battery_capacity", gist="how much charge it holds")

    result = engine.recall("battery_capacity")

    assert result["entity"] == "battery_capacity"
    assert result["gist"] == "how much charge it holds"
    assert result["heat"] == pytest.approx(2.0)  # base 1.0 + direct-access +1.0


def test_recall_of_unknown_entity_returns_none(engine):
    assert engine.recall("nonexistent") is None


def test_recall_increments_heat_on_repeated_access(engine):
    engine.remember("battery_capacity")

    engine.recall("battery_capacity")
    second = engine.recall("battery_capacity")

    assert second["heat"] == pytest.approx(3.0)  # clamped at HEAT_MAX


def test_add_fact_and_get_facts_via_facade(engine):
    engine.remember("server_config")

    engine.add_fact("server_config", "port", "8766", unit="tcp", source="measured")
    facts = engine.get_facts("server_config")

    assert len(facts) == 1
    assert facts[0]["value"] == "8766"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_loci_engine_facade.py -v`
Expected: FAIL with `ImportError: cannot import name 'LociEngine' from 'loci_engine'`

- [ ] **Step 3: Write the implementation**

Replace the contents of `loci-engine/loci_engine/__init__.py`:

```python
from loci_engine import store
from loci_engine.db import open_db


class LociEngine:
    def __init__(self, path: str):
        self._conn = open_db(path)

    def remember(
        self, entity: str, gist: str | None = None, expanded: str | None = None
    ) -> None:
        store.remember_entity(self._conn, entity, gist=gist, expanded=expanded)

    def recall(self, entity: str, hop: int = 0) -> dict | None:
        try:
            store.touch_entity(self._conn, entity, hop=hop)
        except KeyError:
            return None
        return store.get_entity(self._conn, entity)

    def add_fact(
        self,
        entity: str,
        key: str,
        value: str,
        unit: str | None = None,
        source: str | None = None,
    ) -> int:
        return store.add_fact(self._conn, entity, key, value, unit=unit, source=source)

    def get_facts(self, entity: str, key: str | None = None) -> list[dict]:
        return store.get_facts(self._conn, entity, key=key)

    def close(self) -> None:
        self._conn.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_loci_engine_facade.py -v`
Expected: `4 passed`

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`
Expected: all prior tests still pass, nothing broken.

- [ ] **Step 6: Update the index**

In `loci-engine/INDEX.md`, change the `loci_engine/__init__.py (LociEngine facade)` row's Status
to `Done`. Add a closing note under the table:

```markdown
**Plan 1 (memory core) complete as of this row.** `rag/card.py` does not yet consume
`loci_engine`'s heat/fact store — it still ranks by raw metadata dates. Wiring CARD's ranking to
real heat, and wiring document ingestion to populate `isymprev`/`qsymprev`, is Plan 2.
```

- [ ] **Step 7: Commit**

```bash
git add loci-engine/loci_engine/__init__.py loci-engine/INDEX.md \
  tests/test_loci_engine_facade.py
git commit -m "$(cat <<'EOF'
Add LociEngine facade: remember/recall/add_fact/get_facts

Completes Plan 1 (memory core): the sqlite-vec+FTS5 chunk store, the
isymprev/qsymprev schema, heat law, store, and facade are wired
end-to-end and tested. rag/card.py's ranking is not yet migrated to
consume real heat - that's Plan 2.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## What this plan deliberately does not do

- Does not touch `rag/card.py`'s ranking logic or `rag/pipeline.py`'s document-ingestion path
  beyond swapping the storage backend — CARD still ranks by raw metadata dates, not real
  `loci_engine` heat. Wiring that, and wiring `pipeline.ingest` to call
  `LociEngine.remember`/`add_fact` for extracted entities, is **Plan 2**.
- Does not implement the thought spectrum (paper 03), goal retainers/GCSD (papers 05/06 beyond
  the base heat law), or the entity co-occurrence graph / 1/2/3-hop spreading activation
  (papers 07/09 beyond direct-access). That's **Plan 3**.
- Does not implement forecasting (`forecast.py`, paper 01) or reflection-on-action (`reflect.py`,
  paper 02) — both are now in scope per the revised spec (not deferred), but they are a distinct
  subsystem with real safety gates (θ-gate abstain at confidence 0.82, bounded 6h-half-life mood,
  the anti-hallucination invariant) that deserves its own plan and its own test suite rather than
  being folded into schema/heat/store work. That's **Plan 4**. The MCP server, the
  `preview_query`/`process_turn` two-call contract, and the CLI subcommands are also later plans.
- Does not implement paper 05's tiered half-life heat law (critical/high/durable_instruction/
  decision/card/normal) or GCSD's switched decay — this plan's `heat.py` only implements paper
  09 Appendix B's simpler decay/increment/tier law, which is what `schema.sql`'s `isymprev` table
  actually needs. Do not merge the two laws without a deliberate follow-up design decision.
- Does not build the pre-registered, held-out, non-circular validation experiment papers 01/02
  specify for measuring their own effect sizes (LongMemEval-style corpus, H1-H4/H0 hypotheses,
  ≥5-seed confidence intervals) — that validation methodology is explicitly deferred in the spec's
  §1, separately from the mechanisms it would validate.
