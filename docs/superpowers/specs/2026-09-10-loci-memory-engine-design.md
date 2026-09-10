# LOCI Memory Engine — Design Spec

Date: 2026-09-10
Status: Approved in brainstorming; revised 2026-09-10 (root-level package, unified
sqlite-vec+FTS5 store, forecasting/reflection un-deferred) at the user's explicit
direction, superseding the original version's storage choice and Workstream-1 deferral.
Source outline: "Memory & Context Layer Setup: Technical Task Outline" (Arko Sanyal, Sept 2026)
Supersedes: `rag/loci.py` (thin Chroma wrapper) — the existing RAG pipeline spec (2026-09-09) remains valid for ingest/query behaviour.

## 1. Purpose and scope

Turn the current document-only RAG store into the LOCI memory core described by
the outline's Workstreams 1, 2, and 3: a heat-tiered, goal-conditioned, versioned
memory over document chunks, extracted entities/facts, the system's own
thoughts, goals, forecasts, and reflections, with Category-Adaptive Recall Depth
as the read path and compact session hydration as the output. Everything stays
local and offline (Ollama, SQLite — `sqlite-vec` for dense ANN + `FTS5` for
sparse lexical search, fused via RRF; no separate vector-store process).

In scope (this spec, phased across multiple implementation plans):

- Unified memory store, all eight paper-05 streams (p.4): `qsymprev` (exact
  facts), `isymprev` (informational/entities), `dsymprev` (forecast
  projection), `card` (CARD retrieval config, not a stored stream), `psymprev`
  (predictive/forecasting), `ssymprev` (reflection-on-action), `msymprev`
  (mood), `fsymprev` (focused retention/goals) — plus chunks and thoughts.
- Heat/decay with three eras, goal-conditioned switched decay (GCSD), thought
  spectrum with reflection-gated crystallization.
- Full CARD read path, TRS two-call contract (`preview_query` / `process_turn`),
  session hydration under a token budget, context-efficiency reporting.
- Dual-state goal retainers with lifecycle, ledger, and focused-retention
  circuit breaker.
- Forecasting (r+e, paper 01) and reflection-on-action (e+r, paper 02) as
  working code with their paper-specified safety gates intact and verbatim:
  the θ-gate (abstain below confidence 0.82), bounded mood with a 6-hour
  half-life that decays toward neutral and can never become a persistent
  foreground state, the behavioral-surprise update `e_{t+1} = 1 −
  sim(A_t, o_{t+1})` with `sim ∈ [0,1]`, and the anti-hallucination invariant —
  every update targets only externally-produced behavior `o_{t+1}`, never the
  model's own prior output. These are hard constraints from the papers, not
  configurable choices (paper 01 §7, paper 02 §6): the forecasting/reflection
  loop must serve a defended wellbeing objective, and objective-agnosticism
  pointed at engagement is the papers' own named failure mode.
- Python API, CLI subcommands, MCP server.
- Docs: papers index, schema reference, user guide.

Deferred to later specs (explicitly not built here):

- The papers' own pre-registered, held-out, non-circular experimental
  validation protocol (LongMemEval-style corpus, hypotheses H1-H4/H0 stated in
  advance, ≥5-seed confidence intervals) for papers 01/02 — the r+e/e+r
  mechanisms themselves are in scope and gated per above; proving their
  measured effect size against the papers' own benchmark methodology is a
  separate, later validation effort. Rollback telemetry for the forecast/
  reflect loops is deferred with it.
- Paper 08 §5 interpersonal QoL gating; paper 06 ETHICS / BIGGER-PICTURE
  priority tiers and braiding.
- AXON OpenAI-compatible proxy (paper 07); ledger / U-Key / ARC Council sync;
  physical VRAM/RAM/NVMe placement (hardware tiers are derived labels only);
  LongMemEval benchmark harness.

## 2. Papers index (what each paper contributes)

| # | Paper (TD Commons) | Mechanism taken | Module |
|---|---|---|---|
| 01 | Forecasting Affective State r+e (Art. 11089) | streams `psymprev`/`dsymprev` (forecast projection via ensemble simulation), mood law on `msymprev` (arousal ∝ error vs person's own 75th-percentile band, valence ∝ direction of miss, coherence ∝ deviation persistence/slope; bounded, 6h half-life decay to neutral), θ-gate abstain below confidence 0.82, crisis-vs-venting trajectory split (sustained/rising/high-coherence = crisis, spiky/declining/low-coherence = venting) | `forecast.py` |
| 02 | Reflection-on-Action e+r (Art. 11090) | `ssymprev` behavioral-surprise update: `e_{t+1} = 1 − sim(A_t, o_{t+1})`, `M_{t+1} = M_t ⊕ Δ(prev→o_{t+1}, weight=f(e_{t+1}))`, anti-hallucination invariant (target is always externally-produced `o_{t+1}`, never the model's own prior output) | `reflect.py` |
| 03 | Fast-Decaying Thought Spectrum (Art. 11091) | thought law `h₀·e^(−λΔt)·(1+refs)`, λ = ln2/4h, prune < 0.05, lexical ≥2-token confirmation, crystallize-only promotion | `thoughts.py` |
| 04 | CARD (Art. 10856) | category → (K, strategy) table, 1-hop expansion, current-version filter, temporal ordering | `recall.py` |
| 05 | Heat-Decaying Goal-Conditioned Architecture (Art. 11666) | append-only facts, goal fingerprints, circuit-breaker ledger with half-life classes, session startup/teardown invariants, **the eight-stream taxonomy** (`qsymprev`, `isymprev`, `dsymprev`, `card`, `psymprev`, `ssymprev`, `msymprev`, `fsymprev` — p.4) that this spec's schema is organized around | `goals.py`, `heat.py`, `schema.sql` |
| 06 | Focused Retention (Art. 11092) | switched decay `λ_hold` / `λ_free`, five-exit goal taxonomy, suspend ≠ close, consolidation on fulfilled/relinquished | `heat.py`, `goals.py` |
| 07 | LOCI ∞ Middleware (Art. 10806) | isymprev/qsymprev split, access +1.0 / hop +0.5 / +0.25, tier thresholds 1.5 / 0.5, Mode A / Mode B retrieval, "YOU" injection template | `heat.py`, `recall.py`, `extract.py` |
| 08 | Persistent Memory Engine (Art. 10843) | `supersedes` / `valid_from` / `valid_until` chain, `source_trust` 1.0 / 0.7 / 0.5, asymmetric conflict gate 0.8 / 1.2, temporal queries | `store.py`, `extract.py` |
| 09 | Thermal Reasoning Substrate (preprint) | Appendix-B SQL schema as base, two-call interface, two-hop spreading activation, heat range [0, 3] | `schema.sql`, `__init__.py` |

`loci-engine/INDEX.md` expands this table with every parameter name and default,
and is a living document — every task touching `loci-engine/` updates it in the
same commit (see `agent_instructions.md`).

## 3. Repository organization

```
loci-engine/                (repo root, not nested under rag/ — matches the
                              author's private repo name arkosanyal/loci-engine)
  INDEX.md          papers → mechanism → module → parameters (living document)
  SCHEMA.md         table/field reference and invariants
  USER-GUIDE.md     setup, CLI, MCP client config, tuning
  loci_engine/      the importable package (hyphens are illegal in Python
                    identifiers, hence loci-engine/loci_engine/, same pattern
                    as any PyPI package named foo-bar)
    __init__.py     LociEngine facade (public API, §8)
    schema.sql      SQLite schema (§4): all eight paper-05 streams, applied on
                    first open, PRAGMA user_version
    db.py           open_db(path): applies schema.sql idempotently
    store.py        SQLite access: records, facts, links, goals, ledger, sessions
    vectors.py      sqlite-vec (dense ANN, int8/float32 embeddings) + FTS5
                    (sparse BM25) over the fact spectrum, fused via Reciprocal
                    Rank Fusion (RRF) — single SQLite file, no separate
                    vector-store process (replaces today's Chroma-backed
                    rag/loci.py and the design's earlier Chroma choice)
    heat.py         heat laws, eras, GCSD switch, propagation, materialize sweep
    extract.py      Extractor protocol; LLMExtractor (Ollama JSON), RuleExtractor
    thoughts.py     thought capture, dedup, reflect → crystallize → prune
    goals.py        goal retainers, fingerprints, lifecycle, circuit breaker
    forecast.py     paper 01 r+e: psymprev/dsymprev forecast projection,
                    msymprev mood law, θ-gate (0.82), crisis/venting split
    reflect.py      paper 02 e+r: ssymprev behavioral-surprise update,
                    anti-hallucination invariant
    recall.py       CARD categorize/strategies, Mode B lookup, budget filling,
                    hydration payload (absorbs rag/card.py)
rag/mcp_server.py   MCP stdio server, thin adapter over the facade
rag/cli.py          existing ingest/query + new subcommands (§8)
rag/config.py       + RAG_LOCI_DB_PATH and the knobs in §10
```

`rag/card.py` is folded into `loci_engine/recall.py`; `rag/loci.py` is deleted
(there is no `vectors.py`-as-Chroma-shim step — the sqlite-vec+FTS5 store
lands directly). `ingest()` and `query()` keep their signatures and return
shapes. `pyproject.toml`'s `[tool.setuptools.packages.find]` gains
`loci_engine*` alongside `rag*`, and its `chromadb>=1.5.9` dependency is
removed and replaced with `sqlite-vec>=0.1.9` (FTS5 ships in stdlib
`sqlite3` when the interpreter's SQLite was built with
`SQLITE_ENABLE_FTS5`, confirmed present in this environment).

## 4. Index schema (SQLite is the system of record)

Base: TRS Appendix B `isymprev` / `qsymprev`, extended additively.

### `memory` — every record, any spectrum

| column | type | notes |
|---|---|---|
| `id` | TEXT PK | chunk: sha256(`source::page::start_index`) as today; else uuid4 |
| `kind` | TEXT | `chunk` \| `entity` \| `fact` \| `thought` \| `consolidation` |
| `spectrum` | TEXT | `fact` \| `thought` (thought only for `kind=thought`) |
| `text` | TEXT | chunk text, entity gist, thought text, consolidation text |
| `entity` | TEXT NULL | canonical entity name (entity, fact) |
| `content_hash` | TEXT | sha256 of normalized text; dedup key for thoughts and turns |
| `era` | TEXT | `near` \| `mid` \| `far` |
| `importance` | REAL | default 1.0 |
| `base_heat` | REAL | initial heat (1.0) |
| `heat` | REAL | heat as of `heat_updated_at`, clamped to [0, 3] |
| `heat_updated_at` | REAL | unix seconds |
| `refs` | INTEGER | recurrence count |
| `uses` | INTEGER | times returned by recall |
| `last_used` | REAL NULL | |
| `created_at` | REAL | |
| `source` | TEXT | file path or session id |
| `origin` | TEXT | `document` \| `user_explicit_statement` \| `model_context_inference` \| `behavioral_pattern` |
| `source_trust` | REAL | 0.9 / 1.0 / 0.7 / 0.5 respectively (0.9 for documents is this design's value; papers define only the other three) |
| `confidence` | REAL | default 1.0 |
| `goal_id` | TEXT NULL | GCSD binding (FK goals) |
| `crystallized` | INTEGER | 0/1, thoughts only |
| `crystallized_from` | TEXT NULL | thought id, consolidations only |
| `pinned` | INTEGER | 0/1; pinned records are `era=far` |
| `extracted` | INTEGER | 0/1, chunks only: entities/facts have been extracted |
| `metadata` | TEXT (JSON) | page, start_index, etc. |

Indexes: `(kind)`, `(entity)`, `(spectrum, heat)`, `(content_hash)`, `(goal_id)`.

### `facts` — versioned exact-fact chain (`qsymprev` + paper 08)

| column | type | notes |
|---|---|---|
| `id` | INTEGER PK | |
| `memory_id` | TEXT FK memory | the fact's memory row (heat, provenance live there) |
| `entity` | TEXT | |
| `key` | TEXT | |
| `value` | TEXT | exact string |
| `unit` | TEXT NULL | |
| `ts` | REAL | recording timestamp |
| `supersedes` | TEXT NULL | prior value (chain by value, per paper 08) |
| `valid_from` | REAL | |
| `valid_until` | REAL NULL | NULL = current |

Indexes: `(entity, key)`, `(entity, key) WHERE valid_until IS NULL` (unique).
Invariant: at most one current row per `(entity, key)`; rows are closed, never deleted.

### `entity_links` — co-occurrence graph

`a TEXT, b TEXT, weight REAL, updated_at REAL, PRIMARY KEY (a, b)` with `a < b`.
Feeds CARD 1-hop expansion and heat propagation.

### `goals`

| column | notes |
|---|---|
| `id` TEXT PK | uuid4 |
| `fingerprint` TEXT | sha256(normalized text + sorted constraints)[:16] |
| `text`, `constraints` (JSON) | |
| `layer` | `foreground` \| `background` |
| `state` | `open` \| `suspended` \| `fulfilled` \| `reclamped` \| `relinquished` \| `nullified` \| `abandoned` |
| `half_life_class` | `rapid` \| `session` \| `daily` \| `persistent` |
| `opened_at`, `resolved_at` (τ) | |
| `parent_id` | reclamp lineage |
| `consolidation_id` | FK memory, set on fulfilled/relinquished |

### `goal_ledger` — append-only

`id, goal_id, fingerprint, state_hash, event, at, expires_at`.
Events: `opened, step, tripped, suspended, resumed, resolved:<mode>, bound`.

### `sessions` / `turns`

`sessions(id, started_at, ended_at NULL, turn_count, hydration_tokens NULL)`;
`turns(id, session_id, role, text, content_hash, at)`.

### `psymprev` — predictive/forecasting (paper 01)

`entity TEXT, ts REAL, predicted_state TEXT (JSON), confidence REAL, realized_state TEXT NULL, PRIMARY KEY (entity, ts)`.
Written by `forecast.py`'s ensemble projection; `realized_state` backfilled
when the forecast window closes, feeding paper 02's surprise term.

### `ssymprev` — reflection-on-action (paper 02)

`id INTEGER PK, session_id TEXT, t INTEGER, anticipation_set TEXT (JSON), observed TEXT, surprise REAL, weight REAL, applied_at REAL`.
One row per turn's `e_{t+1} = 1 − sim(A_t, o_{t+1})` computation and the
resulting label-free update; append-only, the audit trail for the
anti-hallucination invariant (`observed` is always externally-produced).

### `msymprev` — mood (paper 01)

`session_id TEXT PK, arousal REAL, valence REAL, coherence REAL, updated_at REAL`.
Bounded `[-1, 1]` per axis, 6-hour half-life decay toward `(0, 0, 0)` applied
lazily at read time exactly like fact-spectrum heat; never a persistent
foreground state (paper 01 §7 constraint, enforced by the decay, not by policy).

### `dsymprev` — forecast projection (paper 01)

`entity TEXT, horizon_ts REAL, projected_value TEXT, ensemble_variance REAL, PRIMARY KEY (entity, horizon_ts)`.
The forward-projected estimate `forecast.py` produces from the current
`isymprev`/`qsymprev` state via ensemble simulation, gated behind the θ=0.82
confidence threshold before it is fed back into `recall`.

### `fsymprev` — focused retention (paper 06, backs `goals`)

Not a separate table: `goals` (below) and its `goal_ledger` are paper 05/06's
`fsymprev` stream. Listed here only so the eight-stream table in §2 has a
named home for each stream; see the `goals` section for the real schema.

### sqlite-vec + FTS5 index (dense + sparse, fused)

`vectors.py` maintains two structures over the fact spectrum in the same
SQLite file as `memory`:

- a `vec0` virtual table (via the `sqlite-vec` extension) keyed by
  `memory.id`, storing the `nomic-embed-text` embedding for dense ANN;
- an `fts5` virtual table keyed by `memory.id`, indexing `memory.text` for
  sparse BM25 lookup.

Only fact-spectrum records are indexed. A query embeds once, runs both a
`vec0` KNN and an `fts5` MATCH, and fuses the two ranked lists via Reciprocal
Rank Fusion (RRF): `score(id) = Σ 1 / (60 + rank_i(id))` over whichever lists
contain `id`. Hardware tier is derived at read time: `hot` if heat > 1.5,
`warm` if > 0.5, else `cold` — never stored.

## 5. Heat, decay, eras, GCSD

Fact spectrum: `heat(t) = heat · exp(−λ · Δt)` evaluated lazily from
`(heat, heat_updated_at)`, with every rate converted to per-second at load
(`λ = ln2 / half_life_seconds`, `λ_era = −ln(1 − α_per_day) / 86400`). `λ` is
chosen per record:

- unbound: `λ_era` with `λ = −ln(1 − α)`, α = 0.3/day (near), 0.01/day (mid), 0 (far);
- bound to an open or suspended goal: `λ_hold` (half-life 14 d);
- bound to a goal resolved at τ with mode ∈ {fulfilled, relinquished, nullified,
  abandoned}: `λ_hold` until τ, then `λ_free` (half-life 2 h) — paper 06's
  `R(t) = exp(−[λ_hold·min(t,τ) + λ_free·max(0,t−τ)])`; `reclamped` keeps `λ_hold`
  (binding moves to the honed goal);
- 1-hop neighbour of a bound record: geometric mean of `λ_era` and `λ_hold`
  (design choice for the outline's "graduated curves"; no paper specifies it).

Access: direct hit +1.0 (resets `heat_updated_at`), 1-hop +0.5, 2-hop +0.25
via `entity_links`; clamp to [0, 3]. The clamp replaces paper 05's
"fresh-only increment".

Era on write: turns → near; chunks, entities, facts → mid; crystallized
thoughts and session gists → mid; pinned → far. Promotion near→mid only via
crystallization; mid→far only via `pin`. No demotion, no deletion of
fact-spectrum rows.

Thought spectrum: `h(t) = h₀ · exp(−λ·Δt) · (1 + refs)`, `λ = ln2 / 4h`;
below 0.05 the row is deleted (the only deletable rows).

Sweep: no daemon. `maintain()` materializes heat, runs reflect → crystallize →
prune, and closes expired ledger entries.

## 6. Write path

Single SQLite connection: the `memory` row commits, then the `vec0`/`fts5`
upserts happen in the same transaction (one store, no cross-store consistency
window like the old Chroma-after-commit design had); `reindex()` rebuilds the
`vec0`/`fts5` index from `memory` if it ever drifts.

1. Documents — `ingest()` → chunks as `memory(kind=chunk, era=mid,
   origin=document, source_trust=0.9)`, idempotent by id. Chunks are not
   extracted at ingest; `maintain()` extracts chunks with `uses > 0` and
   `extracted = 0` (facts get `origin=document`), so heat decides which
   documents get structured.
2. Turns — `process_turn(session_id, role, text, reasoning=None)`: store turn
   (dedup by content_hash); `text` → extraction → entities + facts;
   `reasoning` → thought spectrum only (dedup → `refs += 1`).
3. Extraction — `Extractor` protocol: `LLMExtractor` (Ollama, JSON with
   `entities[{name, gist}]`, `facts[{entity, key, value, unit}]`) and
   `RuleExtractor` (regex `key: value`, number+unit). Identity resolution is
   normalized exact name match.
4. Entity write — upsert `kind=entity`: `refs += 1`, +1.0 heat with two-hop
   propagation; `entity_links.weight += 1` for each co-occurring pair in the turn.
5. Fact write — `origin` → `source_trust`. Existing current fact with a
   different value: if `trust_challenger ≥ trust_incumbent`, fire when
   `confidence > heat_incumbent × 0.8`, else when `> heat_incumbent × 1.2`.
   Fire → close old (`valid_until = now`), insert new (`valid_from = now`,
   `supersedes = old.value`). No fire → not written, reported in
   `TurnResult.rejected_conflicts`. Same value → `refs += 1`, +1.0 heat.
6. Crystallization (in `maintain()`) — for each live thought, find later
   fact-spectrum records with non-document origin sharing ≥ 2 content tokens;
   on match write `memory(kind=consolidation, era=mid,
   origin=model_context_inference, crystallized_from=<thought id>)`, set
   `crystallized=1`. Prune cold unconfirmed thoughts.
7. Session close — `session_end()` runs `maintain()` and writes one session
   gist (`kind=consolidation, era=mid`; LLM gist, or first 400 chars of the
   session when Ollama is unavailable).

## 7. Read path

`recall(query, k=None, category=None, at=None, touch=True) -> list[Record]`:

1. Categorize with the rule-based CARD heuristic (existing `card.py` logic).
2. Mode B: if the normalized query contains both a known entity name and one
   of that entity's fact keys, return the current fact for that `(entity, key)`
   at rank 0 with `exact=True` (or the version valid at `at=T`).
3. Candidates: `vec0` dense ANN top `4K` ∪ `fts5` sparse BM25 top `4K`, fused
   via RRF, over the fact spectrum ∪ top `K` by heat among records whose
   `entity` appears in the query. Thoughts are never retrievable.
4. Score: `rrf_score × (1 + heat(t) / 3)`; weight configurable (design choice —
   CARD ranks by heat alone).
5. Strategy per category (CARD): `information_extraction` K=5;
   `knowledge_update` K=3, facts filtered to `valid_until IS NULL`, recency
   tie-break; `multi_session_reasoning` K=10 + K highest-heat 1-hop neighbours;
   `temporal_reasoning` K=7 ordered by `valid_from`/`created_at` ascending,
   honoring `at=T` (`valid_from ≤ T < valid_until`).
6. Touch: +1.0 heat with propagation on returned records unless `touch=False`;
   `uses += 1`, `last_used = now`. Each `Record` carries derived `hw_tier`.

`preview_query(text, budget_tokens=560) -> str`: `recall(touch=False)` filled
into paper 07's template — `You remember the following from your memory:` +
context + `With this in mind:` — tokens estimated as `len(chars) / 4`.

`hydrate(session_id, budget_tokens=560) -> HydrationPayload`: fill order
(1) far-era pinned records, (2) open goals — background before foreground,
(3) top CARD facts by heat, (4) latest session gist. Records `hydration_tokens`
on the session. Fill order is the eviction order reversed: goal-locked items
are cut last.

`status()`: counts per kind/era/hw_tier, open and abandoned goals, last
hydration tokens, and Context Efficiency Ratio = source tokens of hydrated
records ÷ payload tokens.

`query()` = `recall(question)` → prompt → `generate`; returns
`{answer, sources, category, recall_depth}` as today.

## 8. Interfaces

Python (`loci_engine.LociEngine`):

```
LociEngine(db_path=config.RAG_LOCI_DB_PATH, extractor=None)
           # single SQLite file (memory + vec0 + fts5); None → LLMExtractor
           # with RuleExtractor fallback
remember(text, origin, source=None) -> str
recall(query, k=None, category=None, at=None, touch=True) -> list[Record]
preview_query(text, budget_tokens=560) -> str
process_turn(session_id, role, text, reasoning=None) -> TurnResult
session_start() -> str
session_end(session_id) -> SessionSummary
hydrate(session_id, budget_tokens=560) -> HydrationPayload
pin(record_id) / bind(record_id, goal_id)
goals.open(text, layer="foreground", half_life_class="session",
           parent=None, constraints=()) -> Goal
goals.resolve(goal_id, mode, note=None) -> Goal
goals.suspend(goal_id) / goals.resume(goal_id) / goals.list(state=None)
goals.check_step(goal_id, context_ids, last_action) -> StepVerdict
forecast.project(entity, horizon_ts) -> Forecast | None
           # None when confidence < θ=0.82 (abstain, per paper 01 §7)
reflect.update(session_id, t, anticipation_set, observed) -> ReflectionResult
           # target is always the externally-produced `observed`; never the
           # model's own prior output (paper 02's anti-hallucination invariant)
mood.current(session_id) -> MoodState
           # (arousal, valence, coherence), each decayed toward 0 at read time
maintain() -> MaintenanceReport
status() -> StatusReport
reindex() -> int
```

Result types are frozen dataclasses. Circuit-breaker trips and rejected
conflicts are returned values, never exceptions.

CLI (`python -m rag`): `ingest`, `query` unchanged; new `remember`, `recall`,
`session start|end`, `hydrate`, `goal open|resolve|suspend|resume|list`,
`maintain`, `status`, `reindex`; `--json` on every command.

MCP (`python -m rag.mcp_server`, stdio, `mcp>=2`): tools `loci_recall`,
`loci_remember`, `loci_process_turn`, `loci_hydrate`, `loci_goal_open`,
`loci_goal_resolve`, `loci_check_step`, `loci_status`; resource `loci://status`.
The server contains no logic beyond argument mapping.

## 9. Goals and circuit breaker

- `open` writes the goal and `opened` ledger event. While a foreground goal is
  open, records returned by `recall` with `goal_id IS NULL` are bound to it.
- `resolve(mode)`: `fulfilled` / `relinquished` require a consolidation (the
  `note`, or an LLM gist of bound records; first 400 chars of bound texts when
  Ollama is unavailable) written as `kind=consolidation` and linked via
  `consolidation_id`; `reclamped` opens a new goal with `parent_id` and rebinds
  the old goal's records to it; `nullified` / `abandoned` write nothing.
  `abandoned` goals are listed in `status()` as rumination risk.
- `suspend` / `resume` keep bindings and the hold rate.
- `check_step(goal_id, context_ids, last_action)`: `state_hash =
  sha256(fingerprint + sorted(context_ids) + last_action)`. If the same
  `(fingerprint, state_hash)` has occurred ≥ `CB_REPEAT_THRESHOLD` (2) times
  with `expires_at > now`, return `StepVerdict(status="CIRCUIT_BREAKER_TRIGGERED",
  diagnostic={...})`, log `tripped`, suspend the goal. Otherwise log `step` with
  `expires_at = now + half-life` (`rapid` 3 min, `session` 1 h, `daily` 8 h,
  `persistent` 3 d) and return `status="OK"`.

## 10. Configuration (env-overridable, in `rag/config.py`)

| key | default |
|---|---|
| `RAG_LOCI_DB_PATH` | `./loci.db` |
| `RAG_LOCI_ALPHA_NEAR` / `_MID` / `_FAR` | 0.3 / 0.01 / 0.0 per day |
| `RAG_LOCI_HOLD_HALF_LIFE_HOURS` / `_FREE_HALF_LIFE_HOURS` | 336 / 2 |
| `RAG_LOCI_THOUGHT_HALF_LIFE_HOURS` / `_THOUGHT_PRUNE` | 4 / 0.05 |
| `RAG_LOCI_HEAT_MAX` | 3.0 |
| `RAG_LOCI_TIER_HOT` / `_TIER_WARM` | 1.5 / 0.5 |
| `RAG_LOCI_HEAT_WEIGHT` | 1/3 (score blend) |
| `RAG_LOCI_GATE_LOWER` / `_GATE_HIGHER` | 0.8 / 1.2 |
| `RAG_LOCI_BUDGET_TOKENS` | 560 |
| `RAG_LOCI_CB_REPEAT_THRESHOLD` | 2 |
| `RAG_LOCI_RECALL_DEPTH_*` | 5 / 3 / 10 / 7 (CARD table) |
| `RAG_LOCI_FORECAST_THETA` | 0.82 (paper 01 §3.3 θ-gate, not configurable in spirit — exposed only for testing) |
| `RAG_LOCI_MOOD_HALF_LIFE_HOURS` | 6 (paper 01 §3.2) |
| `RAG_LOCI_RRF_K` | 60 (Reciprocal Rank Fusion constant) |

## 11. Error handling

- Ollama unreachable: embedding/generation raise the existing `ConnectionError`
  with the `ollama serve` hint; extraction and gists fall back to
  `RuleExtractor` / truncation with a logged warning so a turn is never lost.
- Schema: `PRAGMA user_version` checked on open; a newer version than the code
  knows refuses to open. Forward migrations are numbered SQL scripts applied in
  order.
- Store consistency: the `memory` row and its `vec0`/`fts5` upserts share one
  SQLite transaction; a partial write is rolled back, not repaired after the
  fact — the old Chroma-as-a-second-store failure mode does not exist here.
  `reindex()` remains available for drift (e.g. after a schema migration).
- Data errors (missing data dir, empty query) fail fast with a message, as today.

## 12. Testing

TDD per module; the whole suite runs without Ollama.

- Pure logic: fact/thought/GCSD heat laws (including the τ switch), clamp,
  fingerprints, state hashes, CARD categorize + strategies, budget filling
  order, circuit breaker (synthetic recursion loops trip at 100%; distinct
  states never trip).
- Store: `tmp_path` SQLite + Chroma with fixed embeddings and `RuleExtractor`;
  idempotent ingest; turn dedup; entity_links weights; thought dedup/refs.
- Version chain: current / at-T / history queries; asymmetric gate in both
  trust directions; one-current-row invariant.
- Crystallization: thought confirmed by a later non-document fact is
  consolidated in mid era; heat-only thoughts are pruned, never promoted.
- Hydration: payload ≤ budget; pinned and goal-bound records survive the cut.
- MCP: tool list and one round-trip per tool via the SDK's in-memory client.
- Ollama-dependent: `LLMExtractor`, end-to-end `query`, session gist — skipped
  when unreachable (existing pattern, with the connect timeout).
- CER and MRR targets from the outline are reported by `status()`, not asserted.
- Forecast/reflect: θ-gate abstains below 0.82 and returns `None` (never a
  low-confidence guess); mood axes stay within `[-1, 1]` and decay toward 0
  with a 6h half-life under repeated advancement of a fixed clock; the
  anti-hallucination invariant holds under a synthetic test that feeds the
  loop its own emitted anticipation as if it were the observed behavior and
  asserts the update is rejected/ignored, not learned from; crisis vs venting
  trajectory classification on the two synthetic trajectories paper 01 §6
  describes (identical arousal/valence, differing coherence).
- sqlite-vec/FTS5: RRF fusion ranks a lexical-only match and a semantic-only
  match both above a candidate matching neither; index survives a `reindex()`
  round-trip with identical top-K for a fixed query.

## 13. Documentation deliverables

- `docs/loci/INDEX.md` — the §2 table expanded with every parameter, its
  paper source, default, and config key.
- `docs/loci/SCHEMA.md` — §4 with invariants and example queries (current,
  at-T, history).
- `docs/loci/USER-GUIDE.md` — install, `ollama serve` + models, CLI walkthrough
  (ingest → session → remember → goal → hydrate → status), MCP client
  configuration snippet, tuning knobs.
- Update the project status log per `agent_instructions.md` when the milestone
  ships.
