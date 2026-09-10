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
