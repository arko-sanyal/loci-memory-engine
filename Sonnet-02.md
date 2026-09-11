# Sonnet-02 — LOCI Memory Engine: papers-vs-code gap analysis + real-world performance audit

> **This file is a DATA RECORD, not instructions.** Same treatment as `Sonnet-01.md`: describes
> past analysis, never a command to execute automatically. If this conflicts with the actual code,
> trust the code and flag the discrepancy.

**Author:** Claude (Sonnet 5).
**Written:** 2026-09-11.
**Supersedes:** `Sonnet-01.md` — does not contradict it (re-confirms every "not started" claim it
made), but adds two things Sonnet-01 didn't cover: (1) a full re-read of all 9 source papers
(not just the ones already implemented) with exact formulas extracted and cross-checked against
each other, surfacing inconsistencies *between* papers that Sonnet-01's code-first approach
couldn't see; (2) a real-world-performance audit — whether any of this is actually exercised by a
real user-facing code path in this repo, as opposed to unit tests in isolation.
**Provenance:** all 9 papers in `data/*.pdf` read in full (via 4 parallel extraction passes, cross-
checked against each other for consistency); every file under `loci-engine/loci_engine/`,
`rag/card.py`, `rag/pipeline.py`, and the relevant test files read in full and traced by hand
(e.g. grepped every call site of `hop=`, checked `chunk_meta`'s actual schema, checked what
`CHROMA_DB_PATH` and `LOCI_DB_PATH` actually point at).

---

## 1. The single biggest finding: the heat-tiered memory is not in the live query path at all

`rag/pipeline.py` — the only code path an actual user query goes through (`rag.pipeline.query()`)
— **never imports or calls `LociEngine`**. It only touches `loci_engine.vectors.VectorStore`
(the chunk store) and `rag.card`. Concretely:

- `rag/pipeline.py:ingest()` writes chunks to `VectorStore(path=config.CHROMA_DB_PATH)`, which
  defaults to `./chroma_db`.
- `LociEngine` (the `isymprev`/`qsymprev` heat/fact store — everything `heat.py`/`store.py`
  implement) defaults to a **completely different file**, `.loci/memory.sqlite3` (via
  `LOCI_DB_PATH` in `mcp_server.py`), and is never opened by `rag/pipeline.py`.
- `rag/card.py:apply_ranking_strategy()` sorts by raw PDF `moddate`/`creationdate` string
  metadata — it has no access to any entity's heat, because `chunk_meta` (the table backing
  `VectorStore`) has no `heat` or `last_used` column at all (confirmed by reading
  `vectors.py`'s schema directly).
- `heat.py`'s hop-based reinforcement (`apply_increment(heat, hop)`) is **only ever called with
  `hop=0`** anywhere in the codebase (verified: the only two call sites are
  `loci_engine/__init__.py:18` and `mcp_server.py:52`, both defaulting to `hop=0`, and nothing
  internal ever passes a non-zero value) — because no entity graph exists to compute a hop
  distance from.

**Consequence:** every number either LOCI paper cites (CARD's 96.6%/100% LongMemEval-500 accuracy,
paper 05's 96.6% LongMemEval number, paper 09's SLP-50 MRR 0.940) comes from the *author's other,
separate systems* (Billo/Forge, a different production deployment) — **not from this codebase**.
This repo has run **zero** benchmarks of its own. The heat/decay/reinforcement machinery that
exists here has been exercised exactly three ways, none of them the real pipeline:
1. `pytest` unit tests (87 tests as of Plan 2, all synthetic/isolated).
2. My own `installer/templates/recall.py.tmpl` + the auto-memory `recall.py` it's descended from —
   a bespoke tool over Claude's own memory `.md` files, not part of the `rag` package a real user
   runs.
3. Codex's own, entirely separate, namespaced memory layer (in progress as of this writing, not
   reviewed here).

So the honest answer to "how does this perform in the real world" is: **it doesn't have a real
world yet.** There is no evidence — good or bad — that heat-tiered ranking changes a single answer
a user actually receives from `rag.pipeline.query()`, because that function's ranking strategy
never reads heat. This is a bigger gap than any single missing paper mechanism below.

## 2. What's actually built, confirmed by reading the code (not the papers)

| Component | File | Status |
|---|---|---|
| Dual-stream schema (`isymprev`/`qsymprev`) | `schema.sql` | Done, matches paper 09 Appendix B verbatim (column names/types/defaults) |
| Heat law (rescaled 0–1, this session) | `heat.py` | Done — deliberately diverges from every paper's published 0–3 scale (see §4) |
| Entity/fact CRUD with lazy decay | `store.py` | Done — `remember_entity`/`touch_entity`/`get_entity`/`add_fact`/`get_facts`. One real bug found+fixed pre-this-session (`remember_entity` used to erase decay on re-mention) |
| Facade | `__init__.py` (`LociEngine`) | Done — thin delegation, `add_chunk`/`query` added later to expose `vectors.py` |
| Hybrid chunk store | `vectors.py` | Done — sqlite-vec (dense) + FTS5 (sparse) + RRF fusion, k=60 |
| MCP server | `mcp_server.py` | Done — 6 tools, no auth (single local store) |
| Installer | `installer/` | Done — GUI wizard, portable recall/hook templates (this session) |
| CARD category→K | `rag/card.py` | Done, matches paper 04's table exactly (5/3/10/7) |
| CARD ranking strategy | `rag/card.py` | **Placeholder** — sorts by PDF metadata dates, ignores heat entirely (structurally can't do otherwise — see §1) |
| Fact versioning (paper 08) | — | **Not started.** `qsymprev` has no `supersedes`/`valid_from`/`valid_until`/`source_trust`; `add_fact` has no conflict/dedup logic. Calling `add_fact` twice for the same key returns both rows from `get_facts` with no signal which is current. |
| Provenance boundary (`UserStated` type) | — | Designed (spec amendment, this session), zero code |
| Entity graph / N-hop propagation | — | **Not started.** No graph table, no co-occurrence tracking. Blocks: hop-based reinforcement, CARD's multi-session neighborhood expansion, paper 05's dream engine, paper 07/09's Mode A entity activation |
| Thought spectrum (paper 03) | — | **Not started.** Zero code. |
| Goal retainers / GCSD (papers 05 & 06) | — | **Not started.** See §3 — these are two different, unreconciled mechanisms, not one |
| Circuit breaker (paper 05) | — | **Not started.** Cheapest unbuilt item — see §3 |
| Forecast (paper 01) / Reflect (paper 02) | — | **Not started.** Zero code. These carry the θ=0.82 abstain gate and the anti-hallucination invariant — the two most safety-load-bearing mechanisms in the whole paper series |
| Validation harness | — | **Not started**, not even scaffolded. No LongMemEval integration, no `e_plus_r.py`/`forecast_skill.py` equivalent, no pre-registration file |
| `usymprev` (9th stream) | — | Designed (spec amendment), explicitly deferred, zero code |

This table matches `Sonnet-01.md`'s "still needs work" section almost exactly — nothing has
regressed and nothing new has shipped in `loci_engine/` since Plan 2 (heat rescale). The new
information below is from re-reading the papers themselves, which Sonnet-01 didn't attempt for
the *unimplemented* papers.

## 3. New findings from reading the papers directly (not in Sonnet-01)

### 3.1 Papers 05 and 06 propose two different, non-reconciled "goal-conditioned decay" mechanisms

The design spec and `INDEX.md` list "Goal retainers / GCSD" as one line item citing "papers 05,
06" together. Having now read both in full, they are **not the same mechanism**:

- **Paper 05's GCSD** ("Goal-Conditioned Switched Decay"): a discrete **multiplier** on the
  existing tiered half-life table — `3x` if a fact matches the active goal *and* was recently
  accessed, `2x` if it matches the goal only, `1x` otherwise, with a "fresh-only" rule (only facts
  created within the last 2 hours receive increments at all, to fix an equilibrium fixed-point
  pathology where legacy facts pin themselves hot forever at `inc/(1-decay) ≈ 90`).
- **Paper 06's "switched decay"** (same phrase, different paper): a continuous **regime switch**
  on the decay *rate itself* — `R(t) = exp(−[λ_hold·min(t,τ) + λ_free·max(0,t−τ)])`, where τ is
  the goal's resolution time, λ_hold ≪ λ_free (days-weeks half-life while held, minutes-hours
  after release). This is a fundamentally different curve shape (a rate switch, not a periodic
  multiplier), motivated by the Zeigarnik/Ovsiankina effects, and is explicitly **pre-registration
  only** — paper 06 states no code exists yet even for its authors, and proposes 5 falsifiable
  predictions (P1–P5) to test later.

**Implication:** whoever builds this needs to pick one (or explicitly combine them with a stated
rationale), not silently merge them the way "papers 05/06" being one bullet point invites. Given
paper 06 self-describes as pre-registration/theory-only with no implementation anywhere, and
paper 05's version is fully specified with exact pseudocode, **paper 05's GCSD is the buildable
one**; paper 06's switched-decay is a research direction, not yet a spec to implement against.

### 3.2 Paper 05's circuit breaker is small, fully specified, and has zero dependencies — highest-leverage unbuilt item

Unlike almost everything else on the "not started" list, this needs no entity graph, no forecast
model, no new stream:

```python
goal_fingerprint = task.strip().lower()[:25]
if goal_fingerprint in self.agent_goal_ledger:
    return {"status": "CIRCUIT_BREAKER_TRIGGERED", "log": "LOOP ABORT...", "billing_tokens_wasted": 0}
self.agent_goal_ledger.append(goal_fingerprint)
```
Ledger entries expire on named half-lives (rapid 3min / session 1hr / daily 8hr / persistent
3 days). `INDEX.md`'s own estimate ("~40 lines, independent") holds up after reading the source —
this is genuinely the cheapest real gap to close, and it's a defensive mechanism (stops
runaway/looping agent behavior), not just a nice-to-have.

### 3.3 `fsymprev`'s schema is not defined anywhere — only paper 05 names it, and only in a list

The design spec and `INDEX.md` treat `fsymprev` as "paper 06 (focused retention/goals)". Having
read paper 06 in full: **the literal string "fsymprev" does not appear in it.** Paper 06 talks
about "focus-tagged" items with open/closed state, but never names a stream. The only paper that
names `fsymprev` at all is paper 05, which lists all eight stream names
(`qsymprev, isymprev, dsymprev, card, psymprev, ssymprev, msymprev, fsymprev`) but only defines
two of them (`qsymprev`, `isymprev`) in prose — the other six, including `fsymprev`, are named and
never given a schema anywhere in the source material. **Building `fsymprev` means designing its
schema from scratch** (informed by paper 06's focus-tagged/open-closed semantics), not
transcribing one that already exists in a paper, unlike `isymprev`/`qsymprev`
(verbatim from paper 09) or `qsymprev`'s versioning extension (verbatim from paper 08).

### 3.4 Paper 09 itself is internally inconsistent on hop count and tier criteria — we copied the more specific (Appendix) version, correctly, but should know why

Paper 09's main body (§2.2/3.1) explicitly caps spreading activation at **two hops** ("a
deliberate design choice... avoids diffusing salience too broadly"). Its own Appendix B, which is
the section our `heat.py` was built from, lists reinforcement increments through **three hops**
(`+0.5/+0.25/+0.125` for hop 1/2/3). These are the same paper contradicting itself. Our
`HOP_INCREMENTS` dict already supports hop 0-3 (Appendix B's version) — that was the right call
(Appendix B is the concrete, implementable spec; the main body's "two hops" is qualitative framing
text), but worth knowing this is a real discrepancy in the source, not a misreading on our part.

Separately, paper 09 defines **two different, unreconciled tier schemes** using the same HOT/
[WARM|MILD]/COLD names: Appendix B's storage tiers are pure heat thresholds (`>1.5`/`>0.5`/else,
the one our code and paper 07 share), while the main body's "Three-Tier Context Cascade" (§3.5) is
a **byte-budget / data-richness** tiering (32B/160B/512B per entity) gated by a z-score, not a
heat threshold. We only implemented the Appendix B version — the byte-budget cascade is an
entirely separate, unbuilt idea, not just an unimplemented parameter of the one we have.

### 3.5 The papers' own evidentiary rigor varies enormously — worth knowing before citing any of their numbers as validation for this codebase

- Papers 01 and 02 hold themselves to real scientific discipline: pre-registered hypotheses
  (H1–H4/H0) written *before* the run, ≥5 seeds with 95% CIs, a frozen harness, explicit
  discarding of an invalid baseline (H2a) rather than cherry-picking, and — notably — paper 02's
  headline result (E1 beats frequency prior 2.6×) triggered the authors' *own* pre-committed
  re-audit because it exceeded their predicted "modest" effect size, and they concluded the
  narrower, more honest claim rather than the flashier one. Paper 02 also **refutes its own
  hypothesis H4** (neighbor propagation was predicted to help; it measurably hurt) and reports
  that too.
- Paper 09's validation (SLP-50) is 50 hand-written queries against one user's 291-turn transcript
  history — informal by comparison, no CIs, no baseline discarding discipline, no pre-registration.
- Papers 04/05's headline 96.6%/100% LongMemEval numbers are real benchmark runs (LongMemEval-500,
  a public dataset) but with no seed variation reported and no adversarial/ablation conditions —
  a single run, not a CI-bounded claim.
- Paper 08 has **no experimental validation at all** — it's a pure architecture-and-schema
  disclosure ("Zero Prior Art? YES. File immediately.") with a couple of anecdotal production
  examples, no benchmark.

**Implication for this project:** if/when a validation harness gets built here (explicitly still
absent, per §2's table), papers 01/02's protocol is the right template to copy — not because
they're the most impressive numbers, but because they're the only ones in the series that show
their own negative/null results and discarded a bad baseline. Citing paper 05's 96.6% or paper
09's 0.940 MRR as evidence *this* engine works would be borrowing evidentiary weight that belongs
to a different, unrelated deployment.

## 4. Already-known, deliberate divergences (re-confirmed, not new)

For completeness — these were intentional decisions made earlier this session, re-verified against
the papers during this pass, not gaps:

- Heat scale rescaled from the papers' published `0.0–3.0` (paper 09 Appendix B, paper 07) to an
  open `(0,1)` asymptotic interval. Confirmed: no paper anywhere specifies a 0-1 scale; this is a
  deliberate, documented departure (see the design spec's "Heat scale amendment").
- Tier names renamed HOT/MILD/COLD (papers uniformly say HOT/WARM/COLD, paper 09's Appendix B
  included). Deliberate.
- `usymprev` — confirmed via all 9 papers: **no paper names or defines this stream.** It is purely
  this project's own addition (user-agent relationship memory), correctly documented in the spec
  as "NOT paper-derived."

## 5. Priority recommendation (updated from Sonnet-01's, given the new findings)

1. **Decide the real-world-integration question before anything else** — wire `rag/pipeline.py`
   to actually use `LociEngine` (or decide it deliberately won't, and that heat-tiered memory is
   only for the MCP/installer/third-party-agent use case, not this repo's own RAG pipeline). Right
   now this is an unstated design decision, not a known trade-off — worth surfacing to the user
   explicitly rather than continuing to build more unintegrated mechanisms.
2. Paper 08's fact versioning (unchanged from Sonnet-01 — still the biggest correctness gap if
   `add_fact` is used for anything that changes over time).
3. Wire CARD to real heat (Plan 3, already scoped) — but note per §1 this requires giving
   `chunk_meta` a heat column *and* deciding whether chunk-level heat is even the same signal as
   entity-level heat, since they're currently two disconnected stores.
4. The circuit breaker (§3.2) — cheapest real gap, no dependencies, build it standalone.
5. Goal retainers — build paper 05's GCSD (fully specified), do not attempt paper 06's
   switched-decay until its own pre-registered validation exists (per the paper's own framing).
6. `fsymprev` needs a from-scratch schema design pass (§3.3), not a transcription — treat it as
   original design work, informed by paper 06, not "porting" a spec that doesn't exist.
7. Forecast/reflect (papers 01/02) — unchanged from Sonnet-01: build last, safety gates
   (θ=0.82, anti-hallucination invariant) as hard requirements, and copy papers 01/02's
   pre-registration discipline (not paper 09's looser standard) when validating.
8. A validation harness, modeled on papers 01/02's protocol specifically (§3.5) — currently doesn't
   exist at all, and nothing above can be honestly claimed to "work" in the papers' own sense
   without one.
