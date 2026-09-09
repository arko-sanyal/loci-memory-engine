# LOCI Memory Engine — Design Spec

Date: 2026-09-10
Status: Approved in brainstorming; awaiting user review of this document
Source outline: "Memory & Context Layer Setup: Technical Task Outline" (Arko Sanyal, Sept 2026)
Supersedes: `rag/loci.py` (thin Chroma wrapper) — the existing RAG pipeline spec (2026-09-09) remains valid for ingest/query behaviour.

## 1. Purpose and scope

Turn the current document-only RAG store into the LOCI memory core described by
the outline's Workstreams 2 and 3: a heat-tiered, goal-conditioned, versioned
memory over document chunks, extracted entities/facts, the system's own
thoughts, and goals, with Category-Adaptive Recall Depth as the read path and
compact session hydration as the output. Everything stays local and offline
(Ollama, SQLite, Chroma).

In scope (this spec, one implementation plan):

- Unified memory store: chunks + entities + versioned exact facts + thoughts + goals.
- Heat/decay with three eras, goal-conditioned switched decay (GCSD), thought
  spectrum with reflection-gated crystallization.
- Full CARD read path, TRS two-call contract (`preview_query` / `process_turn`),
  session hydration under a token budget, context-efficiency reporting.
- Dual-state goal retainers with lifecycle, ledger, and focused-retention
  circuit breaker.
- Python API, CLI subcommands, MCP server.
- Docs: papers index, schema reference, user guide.

Deferred to later specs (explicitly not built here):

- Workstream 1: sandboxed adaptation engine, e+r surprise loop, confidence
  gates, rollback telemetry (papers 01, 02).
- Paper 08 §5 interpersonal QoL gating; paper 06 ETHICS / BIGGER-PICTURE
  priority tiers and braiding.
- AXON OpenAI-compatible proxy (paper 07); ledger / U-Key / ARC Council sync;
  physical VRAM/RAM/NVMe placement (hardware tiers are derived labels only);
  LongMemEval benchmark harness; `loci_predictions` and `emotional_state` tables.

## 2. Papers index (what each paper contributes)

| # | Paper (TD Commons) | Mechanism taken | Module |
|---|---|---|---|
| 01 | Forecasting Affective State (Art. 11089) | none now — deferred | — |
| 02 | Reflection-on-Action e+r (Art. 11090) | none now — deferred | — |
| 03 | Fast-Decaying Thought Spectrum (Art. 11091) | thought law `h₀·e^(−λΔt)·(1+refs)`, λ = ln2/4h, prune < 0.05, lexical ≥2-token confirmation, crystallize-only promotion | `thoughts.py` |
| 04 | CARD (Art. 10856) | category → (K, strategy) table, 1-hop expansion, current-version filter, temporal ordering | `recall.py` |
| 05 | Heat-Decaying Goal-Conditioned Architecture (Art. 11666) | append-only facts, goal fingerprints, circuit-breaker ledger with half-life classes, session startup/teardown invariants | `goals.py`, `heat.py` |
| 06 | Focused Retention (Art. 11092) | switched decay `λ_hold` / `λ_free`, five-exit goal taxonomy, suspend ≠ close, consolidation on fulfilled/relinquished | `heat.py`, `goals.py` |
| 07 | LOCI ∞ Middleware (Art. 10806) | isymprev/qsymprev split, access +1.0 / hop +0.5 / +0.25, tier thresholds 1.5 / 0.5, Mode A / Mode B retrieval, "YOU" injection template | `heat.py`, `recall.py`, `extract.py` |
| 08 | Persistent Memory Engine (Art. 10843) | `supersedes` / `valid_from` / `valid_until` chain, `source_trust` 1.0 / 0.7 / 0.5, asymmetric conflict gate 0.8 / 1.2, temporal queries | `store.py`, `extract.py` |
| 09 | Thermal Reasoning Substrate (preprint) | Appendix-B SQL schema as base, two-call interface, two-hop spreading activation, heat range [0, 3] | `schema.sql`, `__init__.py` |

`docs/loci/INDEX.md` expands this table with every parameter name and default.

## 3. Repository organization

```
rag/loci/
  __init__.py     LociEngine facade (public API, §8)
  schema.sql      SQLite schema (§4), applied on first open, PRAGMA user_version
  store.py        SQLite access: records, facts, links, goals, ledger, sessions
  vectors.py      Chroma collection keyed by memory id (today's loci.py)
  heat.py         heat laws, eras, GCSD switch, propagation, materialize sweep
  extract.py      Extractor protocol; LLMExtractor (Ollama JSON), RuleExtractor
  thoughts.py     thought capture, dedup, reflect → crystallize → prune
  goals.py        goal retainers, fingerprints, lifecycle, circuit breaker
  recall.py       CARD categorize/strategies, Mode B lookup, budget filling,
                  hydration payload (absorbs rag/card.py)
rag/mcp_server.py MCP stdio server, thin adapter over the facade
rag/cli.py        existing ingest/query + new subcommands (§8)
rag/config.py     + RAG_LOCI_DB_PATH and the knobs in §10
docs/loci/
  INDEX.md        papers → mechanism → module → parameters
  SCHEMA.md       table/field reference and invariants
  USER-GUIDE.md   setup, CLI, MCP client config, tuning
```

`rag/card.py` is folded into `recall.py`; `rag/loci.py` is replaced by the
package. `ingest()` and `query()` keep their signatures and return shapes.

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

### Chroma collection `loci_vectors`

`id = memory.id`, embedding (nomic-embed-text), metadata `{kind, era}`. Only
fact-spectrum records are embedded. Hardware tier is derived at read time:
`hot` if heat > 1.5, `warm` if > 0.5, else `cold` — never stored.

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

SQLite commits first, then Chroma upsert; `reindex()` rebuilds Chroma from
SQLite.

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
3. Candidates: Chroma ANN top `4K` by cosine over the fact spectrum ∪ top `K`
   by heat among records whose `entity` appears in the query. Thoughts are
   never retrievable.
4. Score: `cosine × (1 + heat(t) / 3)`; weight configurable (design choice —
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

Python (`rag.loci.LociEngine`):

```
LociEngine(db_path=config.LOCI_DB_PATH, chroma_path=config.CHROMA_DB_PATH,
           extractor=None)          # None → LLMExtractor with RuleExtractor fallback
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

## 11. Error handling

- Ollama unreachable: embedding/generation raise the existing `ConnectionError`
  with the `ollama serve` hint; extraction and gists fall back to
  `RuleExtractor` / truncation with a logged warning so a turn is never lost.
- Schema: `PRAGMA user_version` checked on open; a newer version than the code
  knows refuses to open. Forward migrations are numbered SQL scripts applied in
  order.
- Store consistency: SQLite transaction commits before the Chroma upsert; a
  Chroma failure after commit is logged and repaired by `reindex()`.
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
