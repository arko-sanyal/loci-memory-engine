# Interaction Monitor — Asynchronous Provenance Checking & Injection Prevention

**Status:** approved design, not yet implemented (see the companion implementation plan once written).

## Problem

The provenance boundary shipped this session (`loci_engine/provenance.py`'s `UserStated` type,
`resolve_trust`, the fail-closed default) closes memory poisoning for **explicit** writes — a
human or a deliberate code path calls `add_fact` and asserts where a value came from. It has
nothing to say about a fundamentally different write path: an automated extraction pipeline that
watches the raw interaction stream — keystrokes as the user types, message content, behavioral
outcomes — and writes memory on its own, with no moment where anything explicitly asserts
provenance.

This class of mechanism is real and specified across the papers this project implements from,
even though none of it is built yet in `loci_engine/` (confirmed — `add_fact` is only ever called
explicitly today, nothing does unsupervised extraction):

- **Papers 07/09** — a real-time typing-stream capture: as the user types, partial input is
  debounced (~150ms) and scanned for known entities, which activates/reinforces their heat and
  pre-fetches likely-relevant facts before the message is even sent.
- **Paper 01** — mood is inferred automatically from the gap between predicted and actual
  behavior (reconstruction error), never from an explicit "I'm frustrated" statement.
- **Paper 02** — reflection-on-action: the system predicts what the user will need next, watches
  what actually happens, and treats the mismatch itself as a training signal that updates memory
  about the user's habits. No human ever confirms these updates.
- **Paper 03** — the system's own reasoning trace is captured into a separate memory spectrum
  automatically, every turn.

All four are the same shape: **memory derived from watching, not told directly.** That is a much
larger attack surface for exactly the memory-poisoning pattern the provenance boundary was built
to close, precisely because there is no human-in-the-loop moment to catch a bad extraction before
it lands. This spec defines the monitor that governs that whole class of writes — not one paper's
named mechanism specifically, but the general contract any of them must satisfy.

## Scope

**In scope:** the extraction-ledger contract, the trust ceiling for automated writes, the
async audit algorithm, and the quarantine mechanism it acts through.

**Explicitly out of scope:**
- Building the actual extraction mechanisms (typing-stream capture, reflection-on-action, mood
  inference, thought capture) — those are separate, later work (papers 01/02/03/07/09,
  Plan 4 and beyond per `Sonnet-02.md`'s priority ordering). This spec defines the contract they
  must comply with, not the mechanisms themselves.
- Re-auditing today's explicit `add_fact` writes — those already have real provenance via
  `UserStated`/`resolve_trust`; adding a second audit layer over working code is out of scope here
  (confirmed with the user).
- Content-pattern/keyword scanning (e.g. the coordination bus's `FORBIDDEN` list) — this monitor
  checks structural provenance consistency only, not message content.
- Real-time blocking of a write in progress — this is a post-write, asynchronous audit by design
  (the extraction pipelines it governs are built to get faster with use; a synchronous gate on
  every write would fight that property).

## Why this can be built now, even though nothing calls it yet

The ledger, trust ceiling, and audit algorithm are independently testable against synthetic
extraction-ledger rows — they don't need a real extractor to exist. Building this now means that
whenever `forecast.py`/`reflect.py` (Plan 4) or a typing-stream capture mechanism eventually get
built, they inherit a working safety contract from day one instead of having it bolted on
afterward. **This is a stated prerequisite for Plan 4** — whoever builds papers 01/02's mechanisms
must wire in extraction-ledger writes as part of that same work, not as a follow-up.

## The extraction ledger

Every write an automated extraction pipeline makes must be accompanied by an append-only ledger
entry recording *how* it was produced — the same "authority from provenance, not self-report"
principle as `UserStated`, one layer down for the automated case:

```sql
CREATE TABLE IF NOT EXISTS extraction_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_table TEXT NOT NULL,      -- 'isymprev' or 'qsymprev' - which table the write landed in
    memory_ref TEXT NOT NULL,        -- entity name (isymprev) or fact id (qsymprev), as text
    extraction_path TEXT NOT NULL,   -- which mechanism produced this - see EXTRACTION_PATHS below
    session_id TEXT NOT NULL,
    turn_id TEXT,
    raw_signal_ref TEXT,             -- pointer/hash back to the raw input span this was derived
                                      -- from, for audit - never the raw content itself, just a
                                      -- reference, to avoid duplicating potentially sensitive text
    claimed_trust REAL NOT NULL,     -- the source_trust the extractor assigned at write time
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_extraction_ledger_memory ON extraction_ledger(memory_table, memory_ref);
```

Named extraction paths (the enum `extraction_path` must be one of):

```python
EXTRACTION_PATHS = frozenset({
    "typing_stream_capture",   # papers 07/09 - real-time debounced entity extraction
    "reflection_on_action",    # paper 02 - behavioral-surprise-driven update
    "mood_inference",          # paper 01 - reconstruction-error-driven mood estimate
    "thought_capture",         # paper 03 - automatic reasoning-trace capture
})
```

A ledger entry naming anything outside this set is itself a validation failure (fail-closed —
see below), the same way `UserStated`/`resolve_trust` refuses to be talked into trusting an
unrecognized string.

**Marking a memory as automated at the point of writing it**: in addition to the ledger entry, the
extractor must write the memory's own `source` field (the same column `add_fact`/`remember_entity`
already have) as `f"extracted:{extraction_path}"` — e.g. `"extracted:reflection_on_action"`. This
gives the monitor a concrete signal on the memory row itself, independent of the ledger, so the
fail-closed sweep (below) can find memories that *claim* to be automated but have no ledger entry
to back that claim up — the ledger and the source-field marker are two independent things that
must agree, which is the whole point (a real attack would need to fake both, in two different
tables, consistently).

## Trust ceiling for automated writes

No automated extraction path may ever produce `user_stated` (1.0) trust, even when it extracts
from genuine live user behavior — it is always an *inference about* the user, never the user's
own direct assertion. This closes a specific future loophole: an extractor author reasoning "well
this really did come from the user" and granting full trust anyway.

```python
MAX_AUTOMATED_TRUST = 0.7  # == TRUST_WEIGHTS["model_inferred"] in provenance.py - never higher,
                            # regardless of which extraction_path produced the write
```

## The audit algorithm

Runs asynchronously (a periodic job, not on the write's critical path) over extraction-ledger
entries created since its last run:

```python
def audit_recent_extractions(conn, since: float) -> list[dict]:
    """Returns a list of quarantine actions taken, for the caller to log/notify on."""
    flagged = []

    for entry in _ledger_entries_since(conn, since):
        memory = _fetch_memory(conn, entry["memory_table"], entry["memory_ref"])

        if memory is None:
            flagged.append(_quarantine(
                conn, entry["memory_table"], entry["memory_ref"],
                reason="extraction ledger references a memory that no longer exists",
            ))
            continue

        if entry["extraction_path"] not in EXTRACTION_PATHS:
            flagged.append(_quarantine(
                conn, entry["memory_table"], entry["memory_ref"],
                reason=f"unrecognized extraction_path {entry['extraction_path']!r}",
            ))
            continue

        if entry["claimed_trust"] > MAX_AUTOMATED_TRUST:
            flagged.append(_quarantine(
                conn, entry["memory_table"], entry["memory_ref"],
                reason=f"claimed trust {entry['claimed_trust']} exceeds automated ceiling {MAX_AUTOMATED_TRUST}",
            ))
            continue

        if memory["source_trust"] != entry["claimed_trust"]:
            flagged.append(_quarantine(
                conn, entry["memory_table"], entry["memory_ref"],
                reason="memory's stored trust does not match its own extraction ledger entry",
            ))
            continue

    # Fail-closed sweep: any memory whose `source` column starts with "extracted:" (the
    # marker every automated write must carry - see "Marking a memory as automated" above)
    # but has NO corresponding extraction_ledger entry at all is quarantined by default -
    # absence of proof is treated as absence of legitimacy, not innocence.
    for memory in _memories_claiming_extraction_without_ledger(conn):
        flagged.append(_quarantine(
            conn, memory["table"], memory["ref"],
            reason="no extraction ledger entry found for a memory claiming automated extraction",
        ))

    return flagged
```

## Quarantine

```sql
CREATE TABLE IF NOT EXISTS memory_quarantine (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_table TEXT NOT NULL,
    memory_ref TEXT NOT NULL,
    reason TEXT NOT NULL,
    flagged_at REAL NOT NULL,
    resolved INTEGER DEFAULT 0,   -- 0 = open, 1 = resolved by human review
    resolution TEXT               -- human's decision once reviewed; NULL until then
);
CREATE INDEX IF NOT EXISTS idx_memory_quarantine_open ON memory_quarantine(resolved);
```

Quarantining a memory does **not** delete it — it stays available for audit. It does two things:
1. Inserts a row here.
2. Sets a `quarantined = 1` flag the read paths (`get_entity`, `get_facts`, CARD ranking) must
   check and exclude by default — the exact mechanism (a new column vs. a join against this
   table) is an implementation-plan decision, not fixed here.

**Notification**: quarantine actions must be surfaced somewhere the user actually sees them, not
just silently recorded. The concrete channel (a CLI command, a line in `recall.py`'s output, a
coordination-bus message) is an implementation-plan decision; the requirement is that `list_open_quarantine(conn)` exists as a queryable API regardless of which surface calls it.

## Fail-closed summary (every branch, one table)

| Condition | Outcome |
|---|---|
| Ledger entry references a memory that doesn't exist | Quarantine |
| Ledger entry names an unrecognized `extraction_path` | Quarantine |
| Ledger's `claimed_trust` exceeds `MAX_AUTOMATED_TRUST` (0.7) | Quarantine |
| Memory's stored trust doesn't match its own ledger entry | Quarantine |
| Memory claims automated extraction but has no ledger entry at all | Quarantine |
| Everything matches and trust is within ceiling | Clean, no action |

## Explicitly not designed here (future work, not placeholders — deliberately deferred)

- The actual extraction mechanisms (typing-stream capture, reflection-on-action, mood inference,
  thought capture) — separate future plans.
- The specific notification surface (CLI vs. `recall.py` integration vs. bus message).
- Whether/how a human resolves an open quarantine entry (a review UI, a CLI command) — the schema
  supports it (`resolved`/`resolution` columns) but the resolution workflow itself isn't designed
  here.
- Content-pattern/semantic injection detection — deliberately out of scope, see "Scope" above.
