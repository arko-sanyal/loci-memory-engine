# LOCI Heat Rescale (0–3 → 0–1 asymptotic) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rescale `loci_engine`'s heat law from the published 0–3 range to an open (0, 1) asymptotic interval, and rename the middle tier from WARM to MILD, without changing any other behavior.

**Architecture:** `heat.py` is the single source of truth for the decay/reinforcement/tier functions; `store.py` and `vectors.py` call it but contain no heat math of their own. This plan changes only `heat.py`'s constants and formulas (and the tests that pin them), and updates the two call sites' docstrings/comments that quote old values. No schema change, no new columns — `isymprev.heat`/`qsymprev.heat` already store a bare `REAL`, indifferent to what range that real number lives in.

**Tech Stack:** Python 3.11+, pytest, sqlite3 (unchanged).

**Spec:** `docs/superpowers/specs/2026-09-10-loci-memory-engine-design.md` — see the "Heat scale amendment" section (authoritative, supersedes the same document's earlier 0–3 references) and the "Symbol + expansion" section's tier bullets (already updated to not hardcode old numbers).

## Global Constraints

- Heat lives in the open interval `(0, 1)` — never exactly `0`, never exactly `1`. Exactly `1.0` is reserved for a non-decaying ethics/governance tier that is out of scope for this plan and every other plan until explicitly built.
- Base heat on entity creation: `0.333`.
- Reinforcement: `heat_new = heat + (1 - heat) * k`, with `k = 0.5` (direct/hop=0), `0.25` (hop=1), `0.125` (hop=2), `0.0625` (hop=3).
- Decay: `heat_new = heat * 0.95` per day elapsed — unchanged in form from the current law.
- Tiers: `HOT` if `heat > 0.5`, `MILD` if `heat > 0.167`, else `COLD`. "WARM" is renamed to "MILD" everywhere (code, tests, docs) — this is a deliberate, documented divergence from the papers' published "WARM," already recorded in the spec amendment; do not add a "WARM" alias for backward compatibility, there are no external consumers yet.
- No behavior in `store.py`, `vectors.py`, `db.py`, or `mcp_server.py` changes in this plan beyond what naturally follows from `heat.py`'s new formulas — do not touch fact versioning, CARD, or symbol/expansion here; those are Plan 3.

---

### Task 1: Rewrite `heat.py`'s constants and formulas

**Files:**
- Modify: `loci-engine/loci_engine/heat.py` (full rewrite, currently 23 lines)
- Test: `tests/test_heat.py` (full rewrite, currently 39 lines)

**Interfaces:**
- Consumes: nothing (this is the base module).
- Produces: `decay(heat: float, days_elapsed: float) -> float`, `apply_increment(heat: float, hop: int) -> float`, `tier(heat: float) -> str` — same three function names and signatures as today, so `store.py` needs no changes. `HEAT_MIN`, `HEAT_MAX`, `DECAY_RATE_PER_DAY` stay as names but change value; `HOP_INCREMENTS` changes from an additive-amount dict to a reinforcement-fraction dict (same dict shape: `{0: ..., 1: ..., 2: ..., 3: ...}`, same lookup pattern in `apply_increment`).

- [ ] **Step 1: Write the failing tests**

Replace the entire contents of `tests/test_heat.py`:

```python
import pytest

from loci_engine.heat import HEAT_MAX, HEAT_MIN, apply_increment, decay, tier


def test_decay_applies_0_95_per_day():
    assert decay(0.5, days_elapsed=1) == pytest.approx(0.5 * 0.95)
    assert decay(0.5, days_elapsed=2) == pytest.approx(0.5 * 0.95 ** 2)


def test_decay_with_zero_elapsed_time_is_a_no_op():
    assert decay(0.5, days_elapsed=0) == pytest.approx(0.5)


def test_decay_never_reaches_exactly_zero():
    # 100 days of decay from a tiny heat is still a positive number, not 0 -
    # decay is multiplicative, so it can approach but never touch HEAT_MIN.
    result = decay(0.001, days_elapsed=100)
    assert result > HEAT_MIN
    assert result == pytest.approx(0.001 * 0.95 ** 100)


def test_direct_access_closes_half_the_gap_to_one():
    # k=0.5 for hop=0: heat_new = heat + (1 - heat) * 0.5
    assert apply_increment(0.333, hop=0) == pytest.approx(0.333 + (1 - 0.333) * 0.5)


def test_hop_increments_use_the_reinforcement_fractions():
    # k=0.25/0.125/0.0625 for hop=1/2/3, same gap-closing formula
    assert apply_increment(0.333, hop=1) == pytest.approx(0.333 + (1 - 0.333) * 0.25)
    assert apply_increment(0.333, hop=2) == pytest.approx(0.333 + (1 - 0.333) * 0.125)
    assert apply_increment(0.333, hop=3) == pytest.approx(0.333 + (1 - 0.333) * 0.0625)


def test_increment_never_reaches_exactly_one_no_matter_how_many_times_applied():
    heat = 0.333
    for _ in range(50):
        heat = apply_increment(heat, hop=0)
    assert heat < HEAT_MAX
    assert heat == pytest.approx(1.0, abs=1e-6)  # asymptotically close, never equal


def test_decay_clamps_to_heat_min_floor():
    # decay() must never return a value at or below 0 even given a
    # pathologically large days_elapsed - the max() floor is a safety net,
    # not something normal use should ever hit given multiplicative decay.
    assert decay(0.5, days_elapsed=1_000_000) >= HEAT_MIN


def test_tier_thresholds():
    assert tier(0.6) == "HOT"
    assert tier(0.5) == "MILD"    # boundary is exclusive per the spec (heat > 0.5)
    assert tier(0.2) == "MILD"
    assert tier(0.167) == "COLD"  # boundary is exclusive (heat > 0.167)
    assert tier(0.0) == "COLD"


def test_heat_max_is_one_not_three():
    assert HEAT_MAX == 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_heat.py -v`
Expected: FAIL — `heat.py` still has the old 0–3 constants and additive increments, so `test_heat_max_is_one_not_three`, `test_tier_thresholds`, and the reinforcement-formula tests all fail.

- [ ] **Step 3: Rewrite `heat.py`**

Replace the entire contents of `loci-engine/loci_engine/heat.py`:

```python
HEAT_MIN = 0.0
HEAT_MAX = 1.0
DECAY_RATE_PER_DAY = 0.95
HOP_INCREMENTS = {0: 0.5, 1: 0.25, 2: 0.125, 3: 0.0625}


def decay(heat: float, days_elapsed: float) -> float:
    decayed = heat * (DECAY_RATE_PER_DAY ** days_elapsed)
    return max(HEAT_MIN, decayed)


def apply_increment(heat: float, hop: int) -> float:
    k = HOP_INCREMENTS[hop]
    return heat + (1.0 - heat) * k


def tier(heat: float) -> str:
    if heat > 0.5:
        return "HOT"
    if heat > 0.167:
        return "MILD"
    return "COLD"
```

Note `apply_increment` no longer needs `min(HEAT_MAX, ...)` — the gap-closing
formula `heat + (1 - heat) * k` mathematically cannot exceed 1.0 for any
`heat < 1.0` and `0 <= k <= 1`, which is exactly the asymptotic guarantee the
spec requires. Do not add the clamp back; it would be redundant, and its
presence would wrongly suggest the formula needs a safety net it doesn't.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_heat.py -v`
Expected: PASS — all 9 tests green.

- [ ] **Step 5: Commit**

```bash
git add loci-engine/loci_engine/heat.py tests/test_heat.py
git commit -m "Rescale heat law from 0-3 to 0-1 asymptotic, rename WARM to MILD

Reinforcement changes from a flat additive increment (clamped at a hard
ceiling) to a gap-closing formula (heat + (1-heat)*k) that mathematically
can never reach exactly 1.0, matching the design amendment's requirement
that only a separate, non-decaying ethics tier (deferred) ever equals 1.0.
Decay stays multiplicative (unchanged in form), which already guarantees
it can't reach exactly 0.0 either. Diverges deliberately from the papers'
published 0-3 range and WARM naming - see the spec's 'Heat scale amendment'
section for the full rationale.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: Update call-site comments and existing tests that quote old heat values

**Files:**
- Modify: `loci-engine/loci_engine/store.py:44-51` (the `get_entity` docstring-adjacent comment, if any references old tier names — check by reading, there are none inline today, but the module has no stale comments to fix; this task's real work is in the test files below)
- Modify: `tests/test_store.py:33-35` (comment + assertion referencing "WARM")
- Modify: `tests/test_loci_engine_facade.py` (heat-value assertions computed against the old law)
- Modify: `loci-engine/INDEX.md` (the `heat.py` row's "Notes" column)

**Interfaces:**
- Consumes: `loci_engine.heat`'s new `tier()`/`apply_increment()` behavior from Task 1.
- Produces: nothing new — this task only brings existing tests and docs in line with Task 1's already-shipped change, so it has no downstream consumers.

- [ ] **Step 1: Update `tests/test_store.py`'s WARM reference**

In `tests/test_store.py`, change:

```python
def test_get_entity_surfaces_heat_tier(conn):
    remember_entity(conn, "battery_capacity", now=1000.0)

    entity = get_entity(conn, "battery_capacity", now=1000.0)

    # freshly-remembered entity sits at heat 1.0, which is WARM
    # (HOT if heat > 1.5, WARM if heat > 0.5, else COLD).
    assert entity["tier"] == "WARM"
```

to:

```python
def test_get_entity_surfaces_heat_tier(conn):
    remember_entity(conn, "battery_capacity", now=1000.0)

    entity = get_entity(conn, "battery_capacity", now=1000.0)

    # freshly-remembered entity sits at base heat 0.333, which is MILD
    # (HOT if heat > 0.5, MILD if heat > 0.167, else COLD).
    assert entity["tier"] == "MILD"
```

Also update `remember_entity`'s base heat in `loci-engine/loci_engine/store.py`
— it currently hardcodes `1.0` in the `INSERT` statement (line 22:
`VALUES (?, ?, ?, 1.0, 1.0, 0, ?)`, first `1.0` is `heat`, second is
`confidence`). Change the heat literal only:

```python
        "INSERT INTO isymprev (entity, gist, expanded, heat, confidence, uses, last_used) "
        "VALUES (?, ?, ?, 0.333, 1.0, 0, ?)",
```

(`confidence`'s `1.0` is unrelated to the heat rescale and stays as-is —
confidence is a separate `[0, 1]`-ranged field already, per `schema.sql`'s
`confidence REAL DEFAULT 1.0`.)

- [ ] **Step 2: Update the other heat-value assertions this base-heat change affects**

`tests/test_store.py`'s `test_remember_entity_creates_row_with_base_heat`
currently asserts `entity["heat"] == pytest.approx(1.0)` — change to
`pytest.approx(0.333)`.

`test_remember_entity_is_idempotent_and_does_not_reset_heat` currently does:
```python
    remember_entity(conn, "battery_capacity", now=1000.0)
    touch_entity(conn, "battery_capacity", hop=0, now=1000.0)  # heat -> 2.0
    remember_entity(conn, "battery_capacity", now=2000.0)  # re-mention, no explicit touch
    entity = get_entity(conn, "battery_capacity", now=2000.0)
    assert entity["heat"] == pytest.approx(2.0, abs=2e-3)
```
Change the comment and expected value to match the new base heat and
gap-closing formula: after `remember_entity` (heat=0.333) then one
`touch_entity(hop=0)` (heat = 0.333 + (1-0.333)*0.5 = 0.6665), decayed by the
~1000-second gap to the second `remember_entity` call:
```python
    remember_entity(conn, "battery_capacity", now=1000.0)
    touch_entity(conn, "battery_capacity", hop=0, now=1000.0)  # heat -> 0.6665
    remember_entity(conn, "battery_capacity", now=2000.0)  # re-mention, no explicit touch
    entity = get_entity(conn, "battery_capacity", now=2000.0)
    # remember_entity must not reset last_used, so the ~1000s gap since the
    # touch still decays normally; only touch_entity should ever reset the
    # decay clock. The real decay over 1000 seconds from 0.6665 is tiny
    # (~0.6656), so abs=2e-3 comfortably covers it while still catching
    # gross regressions (e.g. heat reset to 0.333, or jumping to 1.0).
    assert entity["heat"] == pytest.approx(0.6665, abs=2e-3)
```

`test_touch_entity_applies_decay_then_increment` currently asserts
`new_heat == pytest.approx(1.95)` after one day's decay from base heat 1.0
then a direct-access increment. With the new law: `decay(0.333, 1 day) =
0.333 * 0.95 = 0.31635`, then `apply_increment(0.31635, hop=0) = 0.31635 +
(1 - 0.31635) * 0.5 = 0.658175`:
```python
def test_touch_entity_applies_decay_then_increment(conn):
    remember_entity(conn, "battery_capacity", now=0.0)

    one_day_later = 86400.0
    new_heat = touch_entity(conn, "battery_capacity", hop=0, now=one_day_later)

    # decay(0.333, 1 day) = 0.31635, then +direct-access gap-closing (k=0.5)
    # = 0.31635 + (1 - 0.31635) * 0.5 = 0.658175
    assert new_heat == pytest.approx(0.658175)
```

`test_get_entity_applies_decay_without_mutating_storage` currently asserts
`peeked["heat"] == pytest.approx(0.95)` after one day's decay from base 1.0.
Change to decay from the new base: `0.333 * 0.95 = 0.31635`:
```python
def test_get_entity_applies_decay_without_mutating_storage(conn):
    remember_entity(conn, "battery_capacity", now=0.0)

    peeked = get_entity(conn, "battery_capacity", now=86400.0)
    assert peeked["heat"] == pytest.approx(0.31635)

    raw_row = conn.execute(
        "SELECT heat FROM isymprev WHERE entity = 'battery_capacity'"
    ).fetchone()
    assert raw_row[0] == pytest.approx(0.333)
```

- [ ] **Step 3: Update `tests/test_loci_engine_facade.py`'s heat-value assertions**

This file (from the earlier MCP-server work) has three assertions computed
against the old law:

```python
def test_remember_then_recall_returns_touched_entity(engine):
    engine.remember("battery_capacity", gist="how much charge it holds")

    result = engine.recall("battery_capacity")

    assert result["entity"] == "battery_capacity"
    assert result["gist"] == "how much charge it holds"
    assert result["heat"] == pytest.approx(2.0)  # base 1.0 + direct-access +1.0
```

Change to reflect base heat 0.333, one `recall()` (which calls
`touch_entity(hop=0)` internally per the facade): `0.333 + (1-0.333)*0.5 =
0.6665`:

```python
def test_remember_then_recall_returns_touched_entity(engine):
    engine.remember("battery_capacity", gist="how much charge it holds")

    result = engine.recall("battery_capacity")

    assert result["entity"] == "battery_capacity"
    assert result["gist"] == "how much charge it holds"
    assert result["heat"] == pytest.approx(0.6665)  # base 0.333, closes half the gap to 1.0
```

```python
def test_recall_increments_heat_on_repeated_access(engine):
    engine.remember("battery_capacity")

    engine.recall("battery_capacity")
    second = engine.recall("battery_capacity")

    assert second["heat"] == pytest.approx(3.0)  # clamped at HEAT_MAX

    # A third recall would push an *unclamped* heat to 1.0+1.0+1.0+1.0 = 4.0,
    # which is indistinguishable from the correctly-clamped 3.0 after only two
    # recalls above. Asserting here too makes this test actually discriminate
    # a missing clamp.
    third = engine.recall("battery_capacity")
    assert third["heat"] == pytest.approx(3.0)  # still clamped at HEAT_MAX
```

Change to test the asymptotic property instead of a hard clamp (there is no
longer a `min(HEAT_MAX, ...)` clamp to test — Task 1 removed it as redundant
— so this test now verifies the formula's own mathematical guarantee holds
across repeated recalls):

```python
def test_recall_increments_heat_asymptotically_toward_one(engine):
    engine.remember("battery_capacity")

    first = engine.recall("battery_capacity")["heat"]
    second = engine.recall("battery_capacity")["heat"]
    third = engine.recall("battery_capacity")["heat"]

    # each recall closes half the remaining gap to 1.0, so heat keeps
    # increasing but can never reach or exceed 1.0, no matter how many times
    # this loop runs.
    assert first < second < third < 1.0
```

- [ ] **Step 4: Run the full suite to verify nothing else broke**

Run: `.venv/bin/pytest -q`
Expected: All tests pass. If any other test file has a hardcoded heat number
computed against the old law that this task didn't anticipate, fix it the
same way (recompute against the new base/formula) rather than changing the
production code to match a stale test expectation.

- [ ] **Step 5: Update `loci-engine/INDEX.md`**

Find the `heat.py` row and update its Notes column to describe the new law
instead of the old one:

```
| `loci_engine/heat.py` | 09 (Appendix B, rescaled) | Done | Heat lives in an open (0,1) interval, asymptotically approached (`heat + (1-heat)*k` reinforcement, multiplicative decay) - never exactly 0 or 1. This deliberately diverges from paper 09 Appendix B's published 0-3 range; see `docs/superpowers/specs/2026-09-10-loci-memory-engine-design.md`'s "Heat scale amendment" for the rationale. Tiers renamed HOT/MILD/COLD (was HOT/WARM/COLD in the papers). Direct-access hop=0 wired into the facade; 1/2/3-hop neighbor propagation needs an entity graph - deferred to the next plan. Paper 05's per-tier half-life model and paper 06's GCSD switch remain a separate, richer heat law for a later plan - do not conflate the two. |
```

- [ ] **Step 6: Commit**

```bash
git add tests/test_store.py tests/test_loci_engine_facade.py loci-engine/loci_engine/store.py loci-engine/INDEX.md
git commit -m "Update tests and INDEX.md for the 0-1 heat rescale

Recomputes every hardcoded heat-value assertion against the new base heat
(0.333) and gap-closing reinforcement formula from Task 1, and replaces
the hard-clamp test with one that verifies the asymptotic guarantee holds
across repeated recalls instead.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Self-Review Notes

**Spec coverage:** The "Heat scale amendment" section's every concrete number (base 0.333, k=0.5/0.25/0.125/0.0625, decay 0.95/day unchanged, tiers 0.5/0.167) is implemented in Task 1 and exercised by its tests. The "Symbol + expansion" section's tier bullets were already left threshold-free in the spec commit, so no plan task needs to touch that prose.

**Not in this plan, deliberately:** `usymprev`, fact versioning, the provenance boundary, CARD wiring, and the symbol/expansion read-path rule (HOT→expanded, MILD/COLD→gist) are all Plan 3 — this plan only fixes the numbers underneath them so Plan 3 builds on correct heat semantics from the start.
