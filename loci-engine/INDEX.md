# LOCI Engine — Module Index

This file is a **living document**. Every task that adds, removes, or changes behavior in
`loci-engine/` must update the relevant row(s) below in the same commit. See
`agent_instructions.md` for the standing rule that enforces this.

Design spec: `docs/superpowers/specs/2026-09-10-loci-memory-engine-design.md`
Build plans: `docs/superpowers/plans/2026-09-10-loci-engine-memory-core.md` (this is Plan 1 of N)

| Module | Paper(s) | Status | Notes |
|---|---|---|---|
| `loci_engine/vectors.py` | 09 (SLP store concept) | Done | sqlite-vec (dense) + FTS5 (sparse) + RRF, single SQLite file. Replaces `rag/loci.py` (Chroma). `chunk_meta` now carries `heat`/`last_used` (Plan 3 Task 3) — every `query()` hit decays-then-increments a chunk's heat using the same `heat.py` functions that govern `isymprev`, one heat law for both entities and chunks. |
| `loci_engine/schema.sql` | 09 (Appendix B) | Done | Applied via `db.open_db()`, idempotent (`CREATE TABLE IF NOT EXISTS`). |
| `loci_engine/heat.py` | 09 (Appendix B, rescaled) | Done | Heat lives in an open (0,1) interval, asymptotically approached (`heat + (1-heat)*k` reinforcement, multiplicative decay) — never exactly 0 or 1; deliberately diverges from paper 09 Appendix B's published 0–3 range, see `docs/superpowers/specs/2026-09-10-loci-memory-engine-design.md`'s "Heat scale amendment". Tiers renamed HOT/MILD/COLD (papers say HOT/WARM/COLD). Direct-access hop=0 wired into the facade; 1/2/3-hop neighbor propagation needs an entity graph — deferred to a later plan. Paper 05's per-tier half-life model (critical/high/decision/normal) and paper 06's GCSD switch are a separate, richer heat law for a later plan — do not conflate the two. |
| `loci_engine/store.py` | 09 | Done | `remember_entity`/`touch_entity`/`get_entity`/`add_fact`/`get_facts`/`get_fact_history`. `get_entity` is a non-mutating decay peek; only `touch_entity` persists a new heat value. `get_entity`'s `expanded` field is now heat-gated (Plan 3 Task 4, symbol+expansion pattern): only surfaced when the entity's current tier is `HOT`, `None` for MILD/COLD regardless of what's stored — `gist` (the cheap symbol) is always returned. |
| `loci_engine/__init__.py` (`LociEngine` facade) | 09 | Done | `remember`/`recall`/`add_fact`/`get_facts`/`add_chunk`/`query`. The last two were added to expose `vectors.py`'s hybrid retrieval through the facade, which previously only wrapped `store.py`. |
| `loci_engine/mcp_server.py` | — (packaging, not a paper mechanism) | Done | MCP server exposing the facade's 6 methods as tools (`loci_remember`/`loci_recall`/`loci_add_fact`/`loci_get_facts`/`loci_add_chunk`/`loci_query`) for third-party agent integration. No auth scheme — single local store, unlike `loci-coordination-bus`. See root `README.md`'s "Connect LOCI to your own agent" section. |
| `loci_engine/provenance.py` | 08 (source-trust provenance) | Done | `UserStated` type + `resolve_trust()` — the ONLY path to full (1.0) trust; closes a real memory-poisoning vulnerability (a plain string claiming `source="user_stated"` used to be trusted at face value). Fail-closed default (`system_derived`, 0.5) for anything not an actual `UserStated` instance. Not cryptographically unforgeable (Python has no private constructors) — enforced by convention + the fail-closed default, documented loudly in the module docstring. |
| Thoughts spectrum | 03 | Not started | Plan 3 |
| Goal retainers / GCSD | 05, 06 | Not started | Plan 3 |
| Entity graph / spreading activation (1/2/3-hop) | 07, 09 | Not started | Plan 3 |
| CARD integration with `loci_engine` heat | 04 | Done | `docs/superpowers/plans/2026-09-10-loci-versioning-provenance-card.md` Task 3 — `rag/card.py`'s `knowledge_update` strategy now sorts by real chunk heat (recency as tie-break); `multi_session_reasoning`'s graph-hop expansion is still not implemented (no entity graph exists) — that category still only gets the deeper K. |
| Fact versioning + provenance boundary | 08 | Done | Same plan, Tasks 1-2. `loci_engine/provenance.py` (`UserStated`, `resolve_trust`) plus `qsymprev`'s `supersedes`/`valid_from`/`valid_until`/`source_trust` columns and the asymmetric conflict gate (`GATE_LOWER=0.8`/`GATE_HIGHER=1.2`) in `store.py`. `add_fact` now returns `{"accepted", "fact_id", "reason"}` instead of a bare id. `get_facts` is current-version-only by default; `get_fact_history` returns the full chain. |
| `forecast.py` (r+e forecasting, mood) | 01 | Not started | Plan 4 — θ-gate (0.82), mood law, crisis/venting split all specified, not yet built |
| `reflect.py` (e+r reflection-on-action) | 02 | Not started | Plan 4 — behavioral-surprise update, anti-hallucination invariant specified, not yet built |
| Pre-registered validation harness (LongMemEval-style, H1-H4/H0) | 01, 02 | Deferred (design spec §1) | Separate from building the mechanisms themselves |

**Plan 1 (memory core) complete as of this row.** `rag/card.py` does not yet consume
`loci_engine`'s heat/fact store — it still ranks by raw metadata dates. Wiring CARD's ranking to
real heat, and wiring document ingestion to populate `isymprev`/`qsymprev`, is Plan 2.
