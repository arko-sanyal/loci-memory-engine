# Blueprint: High-Performing Coding Intelligence on Arc B70 + RTX 5060 Ti

**Status:** Design blueprint, not yet implemented. Built directly from two research passes (see
"Research trail" at the end) that measured this exact machine rather than guessing from generic
dual-GPU advice.

**Verdict driving this whole document:** cross-vendor tensor parallelism (splitting one model's
layers across the Intel and NVIDIA cards to make it *faster*) is not achievable — this was
checked against vLLM, SGLang, IPEX-LLM, OpenVINO, and llama.cpp's actual source, and is a
structural limitation (no cross-vendor collective communication library exists), not a maturity
gap. The only thing worth building is **two independent model lanes**, each fast on its own
hardware, coordinated by this project's code. That turns out to be a *better* outcome for a coding
assistant than one big split model would have been anyway — see §2.

---

## 1. Confirmed hardware reality

| | RTX 5060 Ti | Arc Pro B70 |
|---|---|---|
| VRAM | 16 GB (measured: 15.9 GiB total / 14.8 GiB available via `nvidia-smi` in this WSL2) | 32 GB GDDR6, 608 GB/s |
| Visible from WSL2 today? | **Yes** — CUDA, working, this is what `rag/llm.py` already talks to | **No** — no `/dev/dri`, no matching Vulkan ICD; WSL2 genuinely cannot see it |
| Best proven backend | Ollama / CUDA (already installed) | llama.cpp with the SYCL backend, run **natively on Windows** (not WSL2) |
| Best measured throughput | (not yet benchmarked for a coding model — do this in Phase 1) | Qwen 3.6-35B-A3B MoE, Q4_K_M: **54.7 tok/s** decode, 615 tok/s prefill, single card |

**Action item before anything else:** confirm in Windows (Device Manager, or Intel's `xpu-smi` /
Arc Control) that the B70 is actually installed and recognized by the OS. WSL2's blindness to it
is expected either way (no `/dev/dri` device is passed through) and is not evidence the card is
missing — but it's also not evidence it's present. Verify this first; everything in Phase 2
assumes it's there.

## 2. Why "two lanes" is the right design, not a fallback

This isn't just the only option that works — it's arguably the better one for a coding assistant
specifically:

- A **compact, always-warm lane** on the 5060 Ti handles the high-frequency case: autocomplete-
  style completions, single-function generation, quick lookups against the LOCI memory store.
  Low latency matters more than raw capability here, and 16GB is plenty for a strong 7-14B coding
  model at Q4/Q5.
- An **expand lane** on the B70 handles the low-frequency, high-value case: multi-file reasoning,
  large refactors, anything that benefits from a much bigger model. 32GB fits a 35B-class MoE
  comfortably, and MoE is specifically the B70's strong point (54.7 tok/s vs. 20.4 tok/s for a
  27B *dense* model at the same quant — confirmed, not estimated).
- This is exactly the "compact/expand" Forge vision from earlier in this project, and it maps
  directly onto paper 09's own architecture: a cheap, always-on informational layer (here, the
  compact lane + LOCI's heat map, which needs no GPU either way) plus an expensive resource
  invoked only when the query actually calls for it.

One big split model, even if cross-vendor TP existed, would force every request through both
cards sequentially — worse latency for the common case, no benefit for the rare case. Two lanes
sized to their hardware is strictly better for this workload shape.

## 3. Phased build order

### Phase 0 — Verify, don't assume (do this before installing anything)

1. Confirm the B70 shows up in Windows Device Manager / `xpu-smi`.
2. Decide: stay on Windows+WSL2 (the architecture below), or consider a native Linux boot later.
   Every one of the B70's measured numbers above came from native Linux — if a Linux boot is ever
   on the table, it reopens the possibility of running both cards from one OS (still not one
   *process* — cross-vendor TP is still impossible there — but it simplifies networking between
   the two lanes to `localhost` instead of a WSL2↔Windows hop). Not required to start; worth
   knowing as a later option.

### Phase 1 — Compact lane (near-zero new work; it's already running)

Nothing about the CUDA/Ollama path on the 5060 Ti needs to change technically — it's already
proven in this exact WSL2. The work here is *choosing and validating the right model*, not
infrastructure:

1. Pick a coding-capable model that fits comfortably in ~14.8 GiB at a quant that keeps quality
   high — a 7-14B class instruction-tuned coding model (e.g., a Qwen2.5-Coder or equivalent
   current-generation coder model in that size class) at Q4_K_M/Q5_K_M. Verify the exact best
   current pick yourself at build time — coding-model leaderboards move fast, and no specific
   model name from either research pass was benchmarked for code quality, only raw throughput on
   unrelated model families. Don't skip this verification step.
2. Benchmark it on this machine the same way the research did (`llama-bench` or Ollama's own
   timing) so you have a real tokens/sec number to compare against the expand lane later.
3. Keep `nomic-embed-text` (or your current embedding model) co-located on the same Ollama
   instance — no reason to move it, and `rag/config.py:3` already points both roles at one host.

### Phase 2 — Expand lane (the real build work, on Windows, not WSL2)

1. **Pick the backend.** Two options, real tradeoff, don't default without deciding:
   - **Ollama + Vulkan on Windows** — fastest to stand up (Ollama's Windows build already ships
     Vulkan support), but measured ~2.2× slower decode than SYCL on this exact card family. Good
     for validating the architecture end-to-end quickly.
   - **llama.cpp built with the SYCL backend, run via `llama-server`** — the path behind every
     fast number in §1, requires installing Intel's oneAPI toolchain and building llama.cpp
     against it. More setup, ~2× the throughput. This is the one to end up on if the expand lane
     gets real use.
   Recommendation: stand up Ollama+Vulkan first to validate the whole pipeline (routing, LOCI
   integration, prompt format) works end-to-end, then swap the backend for llama.cpp SYCL once
   the architecture is proven — the swap only touches Phase 3's client code, not anything else.
2. **Pick the model.** For a coding-focused expand lane, look specifically for a coder-tuned
   model in the 30-35B MoE class (matching the model size the 54.7 tok/s number was measured
   against) or a dense 27-32B coder model if no suitable MoE coder variant exists — verify against
   current benchmarks at build time, same caveat as Phase 1. Benchmark it with the same method
   used for the compact lane so the two numbers are comparable.
3. **If you want more than one expand-lane model available**, front `llama-server` with
   [`llama-swap`](https://github.com/mostlygeek/llama-swap) — it gives an OpenAI-compatible
   endpoint with on-demand model swapping, which is the proven pattern for this exact card.
4. **Networking:** expose the Windows-side server on the host's LAN/WSL-visible IP (not just
   `127.0.0.1`), and add a Windows Firewall inbound rule for the port. Confirm reachability from
   inside WSL2 with a plain `curl` before wiring any project code to it.

### Phase 3 — Code changes in this repo

1. **`rag/config.py`** — replace the single global `OLLAMA_HOST` with per-role configuration:
   a compact-lane host+model, an expand-lane host+model, and an embedding host+model (compact and
   embedding can keep sharing a host). Each should be independently environment-overridable, same
   pattern as the existing config values.
2. **Client layer** — `llama-server` speaks an OpenAI-compatible API; Ollama speaks its own API
   (plus an OpenAI-compatible `/v1` surface). Standardizing both `rag/llm.py` and the expand-lane
   client on the OpenAI-compatible surface means one client implementation serves both lanes
   regardless of which backend Phase 2 lands on — do this rather than maintaining two separate
   client code paths.
3. **Routing policy** — a query needs to pick a lane before generation. `rag/card.py`'s existing
   category classifier is a real head start (it already classifies every query), but per the
   first research pass's own caution: **don't route on retrieval depth** (CARD's current axis) —
   LOCI's whole thesis is that good memory beats bigger models, so routing "deep retrieval →
   bigger model" would quietly undercut that. Route on *reasoning complexity* instead: multi-file
   scope, explicit refactor/synthesis requests, or an explicit escalation flag, with CARD's
   category as one input signal among others, not the deciding one. Treat the exact policy as
   something to tune empirically (A/B the two lanes on real coding tasks) rather than fixing it
   up front.
4. **SQLite WAL mode** — `loci_engine/db.py` and `loci_engine/vectors.py` both open SQLite with
   default settings (rollback journal), which blocks readers during writes. Harmless with one
   process; once compact and expand lanes both call `process_turn` concurrently, this becomes the
   actual bottleneck, ahead of anything GPU-related. Add `PRAGMA journal_mode=WAL` and a
   `busy_timeout` — cheap, no functional downside, do it regardless of how far the rest of this
   blueprint gets.
5. **`process_turn` stays synchronous today** — paper 09 specifies it should run asynchronously
   after generation completes ("adding no latency"); the current design spec defines it
   synchronously. Worth revisiting once two lanes are both writing memory concurrently, so a slow
   expand-lane turn doesn't stall the compact lane's next write. Not a blocker for Phase 1-2.

### Phase 4 — Validate

Run real coding tasks through both lanes, compare actual latency/quality against the Phase 1/2
benchmarks, and tune the routing policy based on where each lane actually wins — not on the
theoretical split. If the compact lane plus LOCI's memory handles more than expected of what you
assumed needed the expand lane, that's a genuine confirmation of the project's own thesis, not a
routing failure.

## 4. What NOT to build

- **Do not** pursue `OLLAMA_LLM_LIBRARY=vulkan` to unify both cards into one Ollama Vulkan group.
  It's the one lever that technically works, and it's a net loss: ~2.2× slower on the Arc side,
  10-18% slower on the 5060 Ti side (up to 6× on MoE prefill), plus a 20-40% PCIe penalty on this
  machine's gen-4 link under multi-GPU layer split — all to reach a model size class (>32GB) that
  isn't clearly better than what already fits on the B70 alone.
- **Do not** invest in IPEX-LLM — it's archived upstream (flagged "known security issues") and
  pinned to a stale Ollama version.
- **Do not** wait for cross-vendor tensor parallelism to mature. It's not a maturity gap; there is
  no cross-vendor collective communication library, and the open research on this (HetCCL,
  arXiv 2605.31000) is exactly that — research, not something to build a production plan around.

## 5. Open questions only Arko can resolve

1. Is the B70 confirmed installed and visible in Windows right now? (Phase 0, blocking.)
2. Ollama+Vulkan first for speed of setup, or go straight to llama.cpp SYCL for the real
   throughput number? (Changes how much Phase 2 setup work happens before first results.)
3. Is a native Linux boot realistically on the table later? Doesn't change the architecture, but
   would simplify Phase 2's networking step.

## Research trail

- First pass: general dual-GPU architecture for LOCI, assuming generic same-vendor NVIDIA
  hardware (2×3090 / 1×5090) — established the HOT-tier-needs-no-GPU finding and the two-lane
  concept, superseded on hardware specifics by the second pass.
- Second pass: hardware-corrected for the actual Intel Arc Pro B70 32GB + RTX 5060 Ti 16GB pair,
  including live measurement of this machine (`nvidia-smi`, `OLLAMA_DEBUG=1` device discovery),
  and the cross-vendor tensor-parallelism verdict in §2 of this document. All throughput numbers
  in this blueprint are sourced from that pass's citations (llama.cpp SYCL benchmarks, Ollama and
  llama.cpp source code, official Arc Pro B70 / RTX 5060 Ti spec sheets).
