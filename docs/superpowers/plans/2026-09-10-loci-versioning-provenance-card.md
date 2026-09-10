# LOCI Fact Versioning, Provenance Boundary, CARD Wiring, and Symbol Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `qsymprev` real versioning and source-trust conflict resolution (paper 08), close the memory-poisoning vulnerability found this session with a provenance type boundary, wire `rag/card.py`'s ranking to real heat instead of raw metadata dates, and make `isymprev`'s existing `gist`/`expanded` columns actually governed by heat tier.

**Architecture:** Four independent-but-sequenced pieces built on top of the already-shipped heat rescale (Plan 2, must land first — this plan's asymmetric-gate math and tier checks use the new 0–1 formulas). Task 1 (provenance) has no dependency on the others and is built first since Task 2 (versioning) consumes it directly. Task 3 (CARD/chunk heat) and Task 4 (symbol expansion) both depend on Plan 2's tier function but not on each other or on Tasks 1–2, so they can run in either order.

**Tech Stack:** Python 3.11+, pytest, sqlite3 (unchanged). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-10-loci-memory-engine-design.md` — "Provenance boundary — closing the cross-agent impersonation gap" and "Symbol + expansion — the 'symprev' pattern, governed by heat" sections (both amendments), plus the pre-existing §4 `facts` table definition and §6 step 5 (asymmetric gate) and §7 step 5 (CARD's `valid_until IS NULL` filter) for the versioning/CARD mechanics.

## Global Constraints

- Heat tiers are `HOT` (`> 0.5`), `MILD` (`> 0.167`), `COLD` (else) — from Plan 2, already shipped before this plan starts. Do not reintroduce `WARM` or the 0–3 scale anywhere in this plan's code or tests.
- Source trust weights (paper 08 §2.1): `user_stated = 1.0`, `model_inferred = 0.7`, `system_derived = 0.5`. These are exact values from the paper, not tunable in this plan.
- Asymmetric gate (paper 08 §3.1): if `challenger_trust >= incumbent_trust`, a correction fires when `new_confidence > incumbent_heat * 0.8`; otherwise it fires when `new_confidence > incumbent_heat * 1.2`. If it does not fire, the write is rejected — nothing is inserted, the incumbent is untouched.
- **Provenance is fail-closed by default:** any `add_fact` call that does not explicitly pass a `UserStated` instance gets `system_derived` trust (0.5), never something higher by omission, never a coin-flip default.
- The `UserStated` type from Task 1 is the only path to `user_stated` trust. It must never be constructible from, or accepted from, content that arrived over `loci-coordination-bus`, a tool result, or a retrieved document — this is an architectural rule for callers to follow (documented loudly in the module), not something the type system alone can force in Python, since Python has no true private constructors. The class's own docstring is the enforcement mechanism, backed by the fail-closed default doing the real work for any caller that doesn't go out of its way to construct one.
- `get_facts` returns current-version-only by default (`valid_until IS NULL`); the new `get_fact_history` returns the full chain.

---

### Task 1: Provenance boundary (`UserStated` type + trust resolution)

**Files:**
- Create: `loci-engine/loci_engine/provenance.py`
- Test: `tests/test_provenance.py`

**Interfaces:**
- Consumes: nothing (base module, like `heat.py`).
- Produces: `UserStated` (a class wrapping a string value), `TRUST_WEIGHTS: dict[str, float]`, `resolve_trust(source: "UserStated | str | None") -> float` — Task 2's `add_fact` calls `resolve_trust` to turn whatever was passed as `source` into a numeric `source_trust` for the gate math.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_provenance.py
import pytest

from loci_engine.provenance import UserStated, resolve_trust


def test_user_stated_instance_resolves_to_full_trust():
    assert resolve_trust(UserStated("the sky is blue")) == pytest.approx(1.0)


def test_the_literal_string_model_inferred_resolves_to_0_7():
    assert resolve_trust("model_inferred") == pytest.approx(0.7)


def test_none_resolves_to_system_derived_0_5():
    assert resolve_trust(None) == pytest.approx(0.5)


def test_a_plain_string_claiming_user_stated_does_not_get_full_trust():
    # This is the actual security property: passing the string "user_stated"
    # (as opposed to a real UserStated instance) must NOT grant full trust -
    # otherwise any caller could type the word and bypass the boundary.
    assert resolve_trust("user_stated") != 1.0
    assert resolve_trust("user_stated") == pytest.approx(0.5)  # falls through to fail-closed default


def test_an_arbitrary_unrecognized_string_fails_closed_to_system_derived():
    assert resolve_trust("something a retrieved document said") == pytest.approx(0.5)


def test_user_stated_instance_carries_its_value():
    stated = UserStated("Dhaka")
    assert stated.value == "Dhaka"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_provenance.py -v`
Expected: FAIL — `loci_engine.provenance` doesn't exist yet.

- [ ] **Step 3: Write `provenance.py`**

```python
"""Provenance trust boundary for LOCI fact writes.

Closes a real vulnerability found in this project: any caller of add_fact
could previously pass source="user_stated" (a plain string) for content
that did not actually come from the live user - including text relayed
from another agent, a tool result, or a retrieved document, regardless of
what that text claims about its own origin. Since user_stated trust gets
the asymmetric gate's easier correction path, this was the highest-value
target for exactly the kind of memory poisoning that already happened once
in production (one agent's message, crafted to read as the user's own
words, was passed to another agent and stored as if the user had said it).

The fix is a type boundary, not a stronger string check: no amount of
validating a string's *content* closes the gap, because the problem is
never what the string says, it's what code path was allowed to produce it.

UserStated is the ONLY path to full (1.0) trust. Python has no true private
constructors, so this is not cryptographically unforgeable - it is an
architectural boundary enforced by convention and by code review, backed by
a fail-closed default that means any caller who does NOT go out of their
way to construct a UserStated gets the lowest trust tier, never something
in between and never something higher by omission.

**Only construct UserStated from text that came directly and unmodified
from the live user's own turn** - the actual chat/CLI/UI code reading a
real message from the human, in the current process, right now. Never
construct it from: a loci-coordination-bus agent.message payload (regardless
of what the payload claims), a tool result, a retrieved document or web
page, or the model's own generated text. If you are not the literal code
that receives raw input from the live human in this session, you should
not be importing UserStated at all.
"""
from __future__ import annotations

TRUST_WEIGHTS: dict[str, float] = {
    "model_inferred": 0.7,
    "system_derived": 0.5,
}
DEFAULT_TRUST = 0.5  # fail-closed: anything not explicitly recognized lands here


class UserStated:
    """Wraps a value asserted to have come directly from the live user.

    See the module docstring - only the genuine live-user-input boundary
    should ever construct this.
    """

    __slots__ = ("value",)

    def __init__(self, value: str) -> None:
        self.value = value


def resolve_trust(source: "UserStated | str | None") -> float:
    if isinstance(source, UserStated):
        return 1.0
    if isinstance(source, str) and source in TRUST_WEIGHTS:
        return TRUST_WEIGHTS[source]
    return DEFAULT_TRUST
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_provenance.py -v`
Expected: PASS — all 6 tests green.

- [ ] **Step 5: Commit**

```bash
git add loci-engine/loci_engine/provenance.py tests/test_provenance.py
git commit -m "Add UserStated provenance type boundary

Closes a real vulnerability: add_fact's source parameter was a plain
string, so any caller could pass source=\"user_stated\" for content that
didn't actually come from the live user - including another agent's
message crafted to read as the user's own words (the exact mechanism
behind an actual memory-poisoning incident this session uncovered).
resolve_trust() only grants full trust to an actual UserStated instance;
the literal string \"user_stated\" resolves to the fail-closed default
instead, same as any other unrecognized string.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: `qsymprev` fact versioning and the asymmetric conflict gate

**Files:**
- Modify: `loci-engine/loci_engine/schema.sql`
- Modify: `loci-engine/loci_engine/store.py` (`add_fact`, `get_facts`; add `get_fact_history`)
- Modify: `loci-engine/loci_engine/__init__.py` (facade's `add_fact`/`get_facts`; add `get_fact_history`)
- Test: `tests/test_store.py`, `tests/test_loci_engine_facade.py`

**Interfaces:**
- Consumes: `loci_engine.provenance.resolve_trust` and `UserStated` from Task 1; `loci_engine.heat` (unchanged from Plan 2, just used for the incumbent's decayed heat).
- Produces: `add_fact(conn, entity, key, value, *, unit=None, source=None, now=None) -> dict` — **return type changes** from `int` (a bare fact id) to a dict `{"accepted": bool, "fact_id": int | None, "reason": str | None}`, since a rejected write is now a real, non-exceptional outcome callers must be able to see. `get_facts(conn, entity, key=None) -> list[dict]` — same signature, now filters to `valid_until IS NULL`. `get_fact_history(conn, entity, key) -> list[dict]` — new, returns the full chain ordered by `valid_from`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_store.py` (keep the existing tests from Plan 2; these are additions):

```python
from loci_engine.provenance import UserStated
from loci_engine.store import get_fact_history


def test_add_fact_first_write_is_always_accepted(conn):
    remember_entity(conn, "server_config", now=1000.0)

    result = add_fact(conn, "server_config", "port", "8766", now=1000.0)

    assert result["accepted"] is True
    assert result["fact_id"] is not None


def test_add_fact_returns_current_version_only_by_default(conn):
    remember_entity(conn, "user_profile", now=1000.0)
    add_fact(conn, "user_profile", "address", "Dhaka", source=UserStated("Dhaka"), now=1000.0)

    facts = get_facts(conn, "user_profile", key="address")

    assert len(facts) == 1
    assert facts[0]["value"] == "Dhaka"
    assert facts[0]["valid_until"] is None


def test_higher_trust_challenger_overrides_lower_trust_incumbent(conn):
    remember_entity(conn, "user_profile", now=1000.0)
    # model_inferred incumbent (trust 0.7), heat at base 0.333 after remember_entity
    add_fact(conn, "user_profile", "address", "Old City", source="model_inferred", now=1000.0)

    # user_stated challenger (trust 1.0 >= 0.7) - easier gate (x0.8):
    # fires if new_confidence > incumbent_heat * 0.8 = 0.333 * 0.8 = 0.2664.
    # add_fact's default confidence is 1.0, well above that.
    result = add_fact(
        conn, "user_profile", "address", "Dhaka",
        source=UserStated("Dhaka"), now=2000.0,
    )

    assert result["accepted"] is True
    current = get_facts(conn, "user_profile", key="address")
    assert len(current) == 1
    assert current[0]["value"] == "Dhaka"

    history = get_fact_history(conn, "user_profile", "address")
    assert len(history) == 2
    assert history[0]["value"] == "Old City"
    assert history[0]["valid_until"] is not None
    assert history[1]["value"] == "Dhaka"
    assert history[1]["supersedes"] == "Old City"


def test_lower_trust_challenger_is_rejected_against_a_confident_incumbent(conn):
    remember_entity(conn, "user_profile", now=1000.0)
    # user_stated incumbent (trust 1.0), touched to raise its heat well above
    # base so the harder gate (x1.2) is a real bar to clear.
    add_fact(conn, "user_profile", "home_city", "Dhaka", source=UserStated("Dhaka"), now=1000.0)
    touch_entity(conn, "user_profile", hop=0, now=1000.0)  # heat -> 0.6665

    # system_derived challenger (trust 0.5 < 1.0) - harder gate (x1.2):
    # fires if new_confidence > incumbent_heat * 1.2 = 0.6665 * 1.2 = 0.7998.
    # add_fact's default confidence is 1.0 - this specific case would still
    # fire at default confidence, so this test passes an explicit low
    # confidence to actually exercise the rejection path.
    result = add_fact(
        conn, "user_profile", "home_city", "Somewhere else",
        source="system_derived", confidence=0.5, now=2000.0,
    )

    assert result["accepted"] is False
    assert result["fact_id"] is None
    current = get_facts(conn, "user_profile", key="home_city")
    assert current[0]["value"] == "Dhaka"  # untouched


def test_get_fact_history_orders_by_valid_from(conn):
    remember_entity(conn, "e", now=1000.0)
    add_fact(conn, "e", "k", "v1", source=UserStated("v1"), now=1000.0)
    add_fact(conn, "e", "k", "v2", source=UserStated("v2"), now=2000.0)
    add_fact(conn, "e", "k", "v3", source=UserStated("v3"), now=3000.0)

    history = get_fact_history(conn, "e", "k")

    assert [h["value"] for h in history] == ["v1", "v2", "v3"]
    assert history[-1]["valid_until"] is None
```

Add to `tests/test_loci_engine_facade.py`:

```python
def test_facade_add_fact_returns_a_result_dict_not_a_bare_id(engine):
    engine.remember("server_config")

    result = engine.add_fact("server_config", "port", "8766")

    assert result["accepted"] is True
    assert isinstance(result["fact_id"], int)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_store.py tests/test_loci_engine_facade.py -v`
Expected: FAIL — `schema.sql` has no versioning columns, `add_fact` still returns a bare int, `get_fact_history` doesn't exist.

- [ ] **Step 3: Add versioning columns to `schema.sql`**

In `loci-engine/loci_engine/schema.sql`, change the `qsymprev` table definition from:

```sql
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
```

to:

```sql
CREATE TABLE IF NOT EXISTS qsymprev (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    unit TEXT,
    ts REAL,
    heat REAL DEFAULT 0.333,
    confidence REAL DEFAULT 1.0,
    source TEXT,
    source_trust REAL DEFAULT 0.5,
    supersedes TEXT,
    valid_from REAL,
    valid_until REAL
);
```

(The `heat` column's default changes from `1.0` to `0.333` for consistency
with Plan 2's new base heat, even though `add_fact` always passes an
explicit value taken from the parent entity and never relies on this
column default in practice.)

- [ ] **Step 4: Rewrite `add_fact`, `get_facts`, and add `get_fact_history` in `store.py`**

Replace `add_fact` and `get_facts` in `loci-engine/loci_engine/store.py`:

```python
from loci_engine.provenance import resolve_trust

GATE_LOWER = 0.8
GATE_HIGHER = 1.2


def add_fact(
    conn,
    entity: str,
    key: str,
    value: str,
    unit: str | None = None,
    source: "object | None" = None,
    confidence: float = 1.0,
    now: float | None = None,
) -> dict:
    now = time.time() if now is None else now
    parent = get_entity(conn, entity, now=now)
    if parent is None:
        raise KeyError(entity)

    challenger_trust = resolve_trust(source)
    source_label = source.value if hasattr(source, "value") else source

    incumbent = conn.execute(
        "SELECT id, value, heat, source_trust FROM qsymprev "
        "WHERE entity = ? AND key = ? AND valid_until IS NULL",
        (entity, key),
    ).fetchone()

    if incumbent is None:
        cursor = conn.execute(
            "INSERT INTO qsymprev "
            "(entity, key, value, unit, ts, heat, confidence, source, source_trust, "
            " supersedes, valid_from, valid_until) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL)",
            (entity, key, value, unit, now, parent["heat"], confidence,
             source_label, challenger_trust, now),
        )
        conn.commit()
        return {"accepted": True, "fact_id": cursor.lastrowid, "reason": None}

    incumbent_id, incumbent_value, incumbent_heat, incumbent_trust = incumbent
    multiplier = GATE_LOWER if challenger_trust >= incumbent_trust else GATE_HIGHER
    fires = confidence > incumbent_heat * multiplier
    if not fires:
        return {
            "accepted": False, "fact_id": None,
            "reason": (
                f"confidence {confidence} did not clear the gate "
                f"({incumbent_heat} * {multiplier} = {incumbent_heat * multiplier})"
            ),
        }

    conn.execute(
        "UPDATE qsymprev SET valid_until = ? WHERE id = ?", (now, incumbent_id)
    )
    cursor = conn.execute(
        "INSERT INTO qsymprev "
        "(entity, key, value, unit, ts, heat, confidence, source, source_trust, "
        " supersedes, valid_from, valid_until) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
        (entity, key, value, unit, now, parent["heat"], confidence,
         source_label, challenger_trust, incumbent_value, now),
    )
    conn.commit()
    return {"accepted": True, "fact_id": cursor.lastrowid, "reason": None}


def get_facts(conn, entity: str, key: str | None = None) -> list[dict]:
    return _select_facts(conn, entity, key, current_only=True)


def get_fact_history(conn, entity: str, key: str) -> list[dict]:
    return _select_facts(conn, entity, key, current_only=False)


def _select_facts(conn, entity: str, key: str | None, current_only: bool) -> list[dict]:
    query = (
        "SELECT id, entity, key, value, unit, ts, heat, confidence, source, "
        "source_trust, supersedes, valid_from, valid_until FROM qsymprev "
        "WHERE entity = ?"
    )
    params: list = [entity]
    if key is not None:
        query += " AND key = ?"
        params.append(key)
    if current_only:
        query += " AND valid_until IS NULL"
    query += " ORDER BY valid_from"
    rows = conn.execute(query, params).fetchall()
    return [
        {
            "id": r[0], "entity": r[1], "key": r[2], "value": r[3], "unit": r[4],
            "ts": r[5], "heat": r[6], "confidence": r[7], "source": r[8],
            "source_trust": r[9], "supersedes": r[10], "valid_from": r[11],
            "valid_until": r[12],
        }
        for r in rows
    ]
```

Note `get_facts` with `key=None` (list all keys for an entity) now also
filters to `valid_until IS NULL` per-key — each key's current row, not one
arbitrary row for the whole entity. This matches "current version only by
default" for every key, not just the single-key case shown in the tests
above.

- [ ] **Step 5: Update the facade in `__init__.py`**

```python
    def add_fact(
        self,
        entity: str,
        key: str,
        value: str,
        unit: str | None = None,
        source=None,
        confidence: float = 1.0,
    ) -> dict:
        return store.add_fact(
            self._conn, entity, key, value, unit=unit, source=source, confidence=confidence
        )

    def get_fact_history(self, entity: str, key: str) -> list[dict]:
        return store.get_fact_history(self._conn, entity, key)
```

(`get_facts` on the facade already delegates to `store.get_facts` unchanged
— no edit needed there, its behavior changes automatically via Task 2's
`store.py` rewrite.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_store.py tests/test_loci_engine_facade.py -v`
Expected: PASS. Also run the full suite (`.venv/bin/pytest -q`) — the
existing `test_add_fact_and_get_facts_roundtrip` and
`test_get_facts_filters_by_key` tests from Plan 1 call `add_fact` and check
`facts[0]["id"]`/`facts[0]["key"]` etc. on the returned list from
`get_facts` (unaffected by the return-type change, which only affects
`add_fact`'s own return value) — if either fails, check whether it asserts
directly on `add_fact`'s return value; if so, update it to unwrap
`result["fact_id"]` the same way the new tests do.

- [ ] **Step 7: Commit**

```bash
git add loci-engine/loci_engine/schema.sql loci-engine/loci_engine/store.py loci-engine/loci_engine/__init__.py tests/test_store.py tests/test_loci_engine_facade.py
git commit -m "Add qsymprev fact versioning and the asymmetric conflict gate

Implements paper 08's supersedes/valid_from/valid_until chain and its
source-trust-differential conflict gate (easier x0.8 threshold when the
challenger's trust >= the incumbent's, harder x1.2 otherwise). add_fact
now returns a result dict instead of a bare fact id, since a rejected
write is a real outcome callers must be able to see, not an exception.
get_facts defaults to current-version-only; the new get_fact_history
returns the full chain for 'what did we believe as of time T' queries.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: Chunk heat in `vectors.py` and CARD wiring in `rag/card.py`

**Files:**
- Modify: `loci-engine/loci_engine/vectors.py` (`chunk_meta` schema, `add`/`query`)
- Modify: `rag/card.py` (`apply_ranking_strategy`)
- Test: `tests/test_vectors.py`, `tests/test_card.py`

**Interfaces:**
- Consumes: `loci_engine.heat.decay`/`apply_increment`/`tier` from Plan 2.
- Produces: `VectorStore.query(...)` results now include a `"heat"` key in each result dict (in addition to the existing `id`/`text`/`metadata`/`distance`); `apply_ranking_strategy` reads that key instead of `metadata["moddate"]`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_vectors.py`:

```python
def test_chunks_start_at_base_heat_and_touch_on_query(tmp_path):
    store = VectorStore(str(tmp_path / "loci.db"))
    embedding = [1.0, 0.0, 0.0] + [0.0] * 765
    store.add(["c1"], [embedding], ["the sky is blue"], [{}])

    results = store.query(embedding, top_k=1)

    assert results[0]["heat"] == pytest.approx(0.333 + (1 - 0.333) * 0.5)


def test_repeated_queries_increase_chunk_heat(tmp_path):
    store = VectorStore(str(tmp_path / "loci.db"))
    embedding = [1.0, 0.0, 0.0] + [0.0] * 765
    store.add(["c1"], [embedding], ["the sky is blue"], [{}])

    first = store.query(embedding, top_k=1)[0]["heat"]
    second = store.query(embedding, top_k=1)[0]["heat"]

    assert second > first
```

Rewrite `test_apply_ranking_strategy_orders_knowledge_update_by_recency_descending`
in `tests/test_card.py` to rank by heat instead of metadata dates:

```python
def test_apply_ranking_strategy_orders_knowledge_update_by_heat_descending():
    results = [
        {"text": "cold", "heat": 0.1},
        {"text": "hot", "heat": 0.6},
        {"text": "mild", "heat": 0.3},
    ]

    ordered = apply_ranking_strategy("knowledge_update", results)

    assert [r["text"] for r in ordered] == ["hot", "mild", "cold"]


def test_apply_ranking_strategy_knowledge_update_ties_break_by_recency():
    results = [
        {"text": "older", "heat": 0.5, "metadata": {"moddate": "2026-01-01"}},
        {"text": "newer", "heat": 0.5, "metadata": {"moddate": "2026-06-01"}},
    ]

    ordered = apply_ranking_strategy("knowledge_update", results)

    assert [r["text"] for r in ordered] == ["newer", "older"]
```

Delete `test_apply_ranking_strategy_tolerates_missing_date_metadata` (it
tested a raw-date fallback that no longer applies to `knowledge_update`
once heat is the primary key) and replace it with:

```python
def test_apply_ranking_strategy_knowledge_update_tolerates_missing_heat():
    results = [
        {"text": "no-heat", "metadata": {}},
        {"text": "has-heat", "heat": 0.4, "metadata": {}},
    ]

    ordered = apply_ranking_strategy("knowledge_update", results)

    assert len(ordered) == 2
```

Leave `test_apply_ranking_strategy_orders_temporal_reasoning_chronologically`
and `test_apply_ranking_strategy_leaves_other_categories_unchanged`
unchanged — `temporal_reasoning` still ranks by date per the CARD paper's
own table (heat-descending is specifically `knowledge_update`'s strategy,
per spec §7 step 5), and `information_extraction` doesn't sort at all.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_vectors.py tests/test_card.py -v`
Expected: FAIL — `chunk_meta` has no heat column, `query()` doesn't return
one, `apply_ranking_strategy` still reads `metadata["moddate"]`.

- [ ] **Step 3: Add heat columns to `chunk_meta` and touch them on query**

In `loci-engine/loci_engine/vectors.py`, change the `chunk_meta` table
definition:

```python
            CREATE TABLE IF NOT EXISTS chunk_meta (
                chunk_id TEXT PRIMARY KEY,
                rowid_map INTEGER UNIQUE,
                text TEXT NOT NULL,
                metadata TEXT NOT NULL,
                heat REAL DEFAULT 0.333,
                last_used REAL
            );
```

Import the heat functions at the top of the file:

```python
import time

from loci_engine.heat import apply_increment, decay
```

In `add()`, both the insert and update branches need `last_used` set on
first insert. Add to the `INSERT INTO chunk_meta` statement:

```python
                cursor = self._conn.execute(
                    "INSERT INTO chunk_meta (chunk_id, text, metadata, last_used) "
                    "VALUES (?, ?, ?, ?)",
                    (chunk_id, text, json.dumps(metadata), time.time()),
                )
```

(The `UPDATE chunk_meta SET text = ?, metadata = ?` branch for re-adding an
existing chunk_id does not need to touch `heat`/`last_used` — re-ingesting
the same chunk with new text is a content update, not an access.)

In `query()`, after computing `scored` and before building `results`, decay
and increment each returned chunk's heat and persist it, mirroring
`store.touch_entity`'s pattern:

```python
        now = time.time()
        results = []
        for chunk_id, _ in scored[:top_k]:
            row = self._conn.execute(
                "SELECT text, metadata, heat, last_used FROM chunk_meta WHERE chunk_id = ?",
                (chunk_id,),
            ).fetchone()
            text, metadata_json, heat, last_used = row
            days_elapsed = max(0.0, (now - (last_used or now)) / 86400.0)
            decayed = decay(heat, days_elapsed)
            new_heat = apply_increment(decayed, hop=0)
            self._conn.execute(
                "UPDATE chunk_meta SET heat = ?, last_used = ? WHERE chunk_id = ?",
                (new_heat, now, chunk_id),
            )
            results.append(
                {
                    "id": chunk_id,
                    "text": text,
                    "metadata": json.loads(metadata_json),
                    "distance": dense_distance.get(chunk_id),
                    "heat": new_heat,
                }
            )
        self._conn.commit()
        return results
```

This replaces the existing `results = []` / `for chunk_id, _ in scored[:top_k]:`
block in `query()` — the `SELECT`, the dict-building, and the trailing
`return results` all move into this new version; there is no separate old
block left behind.

- [ ] **Step 4: Wire `apply_ranking_strategy` to heat in `rag/card.py`**

Replace `apply_ranking_strategy`:

```python
def apply_ranking_strategy(category: str, results: list[dict]) -> list[dict]:
    if category == "knowledge_update":
        return sorted(
            results,
            key=lambda r: (
                r.get("heat", 0.0),
                r.get("metadata", {}).get("moddate")
                or r.get("metadata", {}).get("creationdate")
                or "",
            ),
            reverse=True,
        )
    if category == "temporal_reasoning":
        return sorted(
            results,
            key=lambda r: r["metadata"].get("creationdate")
            or r["metadata"].get("moddate")
            or "",
        )
    return results
```

Update the module docstring's second paragraph (currently describing
`knowledge_update` as ranking "by raw metadata dates, not by real heat") to:

```python
This module ranks knowledge_update results by real heat from
`loci_engine.vectors.VectorStore` (recency as a tie-break when heat is
equal or absent), and temporal_reasoning results by document metadata
dates - there is still no entity co-occurrence graph or fact versioning
consumed here beyond heat itself, so multi_session_reasoning still only
gets the deeper K without graph-hop expansion (tracked as a later plan).
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_vectors.py tests/test_card.py -v`
Expected: PASS. Then run the full suite: `.venv/bin/pytest -q`.

- [ ] **Step 6: Update `loci-engine/INDEX.md` and commit**

Update the `vectors.py` row's Notes to mention chunk heat, and add a note
to `rag/card.py`'s entry (if `INDEX.md` tracks it — it currently tracks only
`loci-engine/` modules; if `rag/card.py` isn't listed, skip this and instead
update the standalone "CARD integration with `loci_engine` heat | 04 | Not
started | Plan 2" row to say "Done" and reference this plan's actual file
name instead of "Plan 2", since `INDEX.md`'s prior plan numbering predates
this session's plan split).

```bash
git add loci-engine/loci_engine/vectors.py rag/card.py tests/test_vectors.py tests/test_card.py loci-engine/INDEX.md
git commit -m "Wire CARD's knowledge_update ranking to real chunk heat

chunk_meta gains heat/last_used columns, decayed and incremented on every
query() hit using the same heat.py functions already governing isymprev -
one heat law, not two. apply_ranking_strategy's knowledge_update strategy
now sorts by heat descending (recency as a tie-break), replacing the raw
moddate/creationdate sort that was a placeholder until real heat existed.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: Symbol/expansion read-path rule for `isymprev`

**Files:**
- Modify: `loci-engine/loci_engine/store.py` (`get_entity`)
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `loci_engine.heat.tier` (Plan 2).
- Produces: `get_entity(...)`'s returned dict's `"expanded"` key is now `None` unless the entity's tier is `HOT` — callers checking `entity["expanded"]` already handle `None` today (it was always optionally `None` when no expanded text had been stored), so this is a behavior narrowing, not a new type.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_store.py`:

```python
def test_get_entity_includes_expanded_when_hot(conn):
    remember_entity(conn, "e", expanded="a long detailed explanation", now=1000.0)
    touch_entity(conn, "e", hop=0, now=1000.0)  # 0.333 -> 0.6665, still MILD
    touch_entity(conn, "e", hop=0, now=1000.0)  # 0.6665 -> 0.83325, now HOT

    entity = get_entity(conn, "e", now=1000.0)

    assert entity["tier"] == "HOT"
    assert entity["expanded"] == "a long detailed explanation"


def test_get_entity_omits_expanded_when_not_hot(conn):
    remember_entity(conn, "e", expanded="a long detailed explanation", now=1000.0)
    # freshly remembered: heat 0.333, tier MILD

    entity = get_entity(conn, "e", now=1000.0)

    assert entity["tier"] == "MILD"
    assert entity["expanded"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_store.py -v`
Expected: FAIL — `get_entity` currently always returns the stored `expanded`
value regardless of tier.

- [ ] **Step 3: Gate `expanded` on tier in `get_entity`**

In `loci-engine/loci_engine/store.py`, change:

```python
    entity_, gist, heat, confidence, uses, last_used, expanded = row
    decayed_heat = _decayed_heat(heat, last_used, now)
    return {
        "entity": entity_,
        "gist": gist,
        "heat": decayed_heat,
        "tier": tier(decayed_heat),
        "confidence": confidence,
        "uses": uses,
        "last_used": last_used,
        "expanded": expanded,
    }
```

to:

```python
    entity_, gist, heat, confidence, uses, last_used, expanded = row
    decayed_heat = _decayed_heat(heat, last_used, now)
    current_tier = tier(decayed_heat)
    return {
        "entity": entity_,
        "gist": gist,
        "heat": decayed_heat,
        "tier": current_tier,
        "confidence": confidence,
        "uses": uses,
        "last_used": last_used,
        "expanded": expanded if current_tier == "HOT" else None,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_store.py -v`
Expected: PASS. Then run the full suite: `.venv/bin/pytest -q` — check
whether any existing test (e.g. from Plan 1 or the MCP-server work) asserts
`entity["expanded"]` at a tier other than HOT; if so, update that test's
expectation the same way Task 2/Step 6 of Plan 2 handled similar fallout,
rather than weakening this task's gate.

- [ ] **Step 5: Update `loci-engine/INDEX.md` and commit**

Update the `__init__.py`/facade row (or `store.py`'s row) to note that
`get_entity`'s `expanded` field is now heat-gated per the spec's "Symbol +
expansion" amendment.

```bash
git add loci-engine/loci_engine/store.py tests/test_store.py loci-engine/INDEX.md
git commit -m "Gate isymprev's expanded field on heat tier (HOT only)

Implements the spec's symbol+expansion pattern for isymprev: gist is
always returned (the cheap symbol), but expanded (the full content) is
only surfaced once an entity's heat crosses into HOT - MILD/COLD entities
return expanded=None regardless of what's stored, matching 'read the full
file only once its symbol signals relevance' rather than always paying
the cost of the full content.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Self-Review Notes

**Spec coverage:** Provenance boundary section → Task 1. `facts` table / §6 step 5 asymmetric gate / §7 step 5 CARD filter → Task 2 (versioning) and Task 3 (CARD ranking; note CARD's `valid_until IS NULL` filtering was already implicitly satisfied since Task 2's `get_facts` now does this by default — no separate CARD-side filtering code needed). Symbol+expansion section → Task 4 for `isymprev`; the section's guidance on `dsymprev`/`psymprev`/`ssymprev`/`usymprev` gaining their own `expanded` columns is explicitly out of scope here since none of those tables exist yet (they're the next sub-project, per the ordering agreed earlier).

**Not in this plan, deliberately:** `usymprev` (new stream), the entity co-occurrence graph / N-hop propagation, `dsymprev`/`psymprev`/`ssymprev`/`msymprev` (papers 01/02), the circuit breaker (paper 05 §5), and the thought spectrum (paper 03) are all future plans, per the explicitly agreed ordering. Nothing in this plan blocks starting any of them once this plan and Plan 2 are both merged.

**Type consistency check:** `add_fact`'s new `dict` return shape (`{"accepted", "fact_id", "reason"}`) is used consistently in Task 2's tests and the facade wrapper in Task 2/Step 5 — no later task in this plan calls `add_fact` and assumes the old bare-int return.
