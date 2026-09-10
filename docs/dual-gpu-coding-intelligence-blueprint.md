# Blueprint: High-Performing Coding Intelligence on Arc B70 + RTX 5060 Ti

**Status: Phase 0 and Phase 2 Option A validated end-to-end on this machine** (2026-09-10). Built
from four research passes (see "Research trail" at the end) that measured this exact machine
rather than guessing from generic dual-GPU advice. See "Implementation log" below for what's
actually running vs. still to do.

## Implementation log

- **Phase 0 confirmed:** Intel's NEO/compute-runtime + Level Zero loader installed in this WSL2
  guest (`intel-opencl-icd`, `libze-intel-gpu1`, `libze1`/`libze-dev` from Ubuntu, IGC from
  `intel/intel-graphics-compiler`, all pinned to release `26.31.39395.13`). `clinfo` and `sycl-ls`
  both enumerate the Arc Pro B70 (`Intel(R) Graphics [0xe223]`, ~31.2GB) directly — the corrected
  research was right, no Windows-native server needed.
- **Phase 2 Option A confirmed:** llama.cpp built from source with `-DGGML_SYCL=ON` against the
  Intel oneAPI DPC++ compiler (`icx`/`icpx`, installed via Intel's oneAPI apt repo — packages
  `intel-oneapi-compiler-dpcpp-cpp` + `intel-oneapi-mkl-devel`). `llama-server` runs against the
  B70 and serves real completions over its OpenAI-compatible endpoint.
- **A real, non-obvious bug found and fixed along the way — record this precisely, it will bite
  again on a fresh setup:** `llama-server` segfaults on this hardware/driver combo, both during
  model load and during actual generation, inside `ur_command_list_manager::isGraphCaptureActive`
  in Intel's **Level Zero v2** unified-runtime adapter (`libur_adapter_level_zero_v2.so.0`) — a
  null-pointer dereference reached via SYCL's queue-submission path (`sycl::handler::finalize()` /
  `queue_impl::isNativeRecording()`), hit by both llama.cpp's own `mul_mat` reorder optimization
  and internally by oneMKL's SYCL BLAS `sgemm`. **Disabling `GGML_SYCL_GRAPH` at build time is not
  sufficient by itself** — the crash still occurs during generation via oneMKL's own call path,
  independent of that build flag. **The fix that actually works:** force the older, stable Level
  Zero v1 adapter at runtime with `SYCL_UR_USE_LEVEL_ZERO_V2=0` (both adapter `.so`s ship
  side-by-side in the oneAPI install; the v2 one is the default and is what crashes). With that
  set, model load dropped from ~27s to ~2s (the v2 adapter's failing sysman queries were adding
  real overhead, not just noise) and a real chat completion returned correctly. **Always export
  `SYCL_UR_USE_LEVEL_ZERO_V2=0` before starting the expand-lane server** — this is not optional.
- Also confirmed empirically: Intel's Level Zero sysman free-memory query fails on this setup
  (`zesInit failed ... Sysman free-memory query may be unavailable`) — this is the exact,
  previously-flagged-as-uncertain caveat from the third research pass, now confirmed to occur here
  specifically, and harmless once a device is targeted explicitly (`--device SYCL0`) rather than
  relying on automatic free-memory-based placement.
- **Still to do:** pick and pull the actual target models (candidates identified from Ollama's
  live library: `qwen2.5-coder:14b-instruct` class for the compact lane, `qwen3-coder:30b`
  — a 30B-A3B MoE, architecturally the coder-specialized sibling of the model class already
  benchmarked at 54.7 tok/s — for the expand lane); convert/fetch as GGUF for the expand lane
  specifically, since `llama-server` needs a raw GGUF file, not Ollama's blob store; wire
  `rag/llm.py`/`rag/embeddings.py` to the new per-role config (`rag/config.py` already has
  `COMPACT_*`/`EXPAND_*`/`EMBEDDING_*`, added and tested); standardize the client on an
  OpenAI-compatible interface so one implementation serves both `llama-server` and Ollama; add the
  CARD-based routing policy; SQLite WAL mode fix; raise `.wslconfig` memory/swap before loading the
  30B-class model (this WSL2 instance currently has only ~15GB RAM / 4GB swap — well short of the
  "host RAM ≈ model size during load" risk flagged in research for a ~20GB Q4 file).

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
| Visible from WSL2 today? | **Yes** — CUDA, working, this is what `rag/llm.py` already talks to | **Likely yes, via a different path than tested** — see correction below |
| Best proven backend | Ollama / CUDA (already installed) | llama.cpp with the SYCL backend — **probably runnable from inside this same WSL2**, not Windows-native |
| Best measured throughput | (not yet benchmarked for a coding model — do this in Phase 1) | Qwen 3.6-35B-A3B MoE, Q4_K_M: **54.7 tok/s** decode, 615 tok/s prefill, single card (measured on native Linux; WSL2 delta unknown, see below) |

> **Correction (superseding the original §1/§3 conclusion):** the original finding "WSL2 can't see
> the B70" was tested through Ollama's device discovery, which has no SYCL backend at all — it
> only probes CUDA and Vulkan, so it could never have found the Arc regardless of what was
> installed. That test didn't prove what it was taken to prove. A follow-up research pass sourced
> against Intel's own `compute-runtime` WSL documentation (Battlemage listed "Production quality,
> WSL: Yes" in the official per-platform support matrix) and a real Arc Pro B70 running vLLM under
> WSL2 at ~70 tok/s in a public Microsoft/WSL issue thread. **Intel Arc under WSL2 goes through
> Level Zero/SYCL via WDDM paravirtualization through `/dev/dxg`** — a device this machine already
> has — not through `/dev/dri` (irrelevant on WSL2) and not through Vulkan (genuinely absent: no
> `dzn` ICD ships in Ubuntu's WSL mesa package, confirmed from Ubuntu's own packaging rules). The
> missing piece was simply that **the Intel NEO/oneAPI runtime was never installed inside this WSL2
> guest.** Phase 2 below is rewritten around this — do not act on the old "must run on Windows"
> conclusion.
>
> Real caveats that come with this correction, specific to this exact machine:
> - **CUDA + Intel runtime coexistence is a known collision risk**, not theoretical here since this
>   machine already runs CUDA for the 5060 Ti: CUDA's OpenCL libraries on `LD_LIBRARY_PATH` can
>   cause Intel's SYCL tooling to load NVIDIA's OpenCL runtime instead and segfault. Needs explicit
>   `ONEAPI_DEVICE_SELECTOR` / `OCL_ICD_VENDORS` isolation before trusting `sycl-ls` output.
> - An **open, unresolved** SYCL process-teardown hang exists (process becomes unkillable, needs
>   `wsl --shutdown`) — observed on an Intel iGPU, **not confirmed either way on discrete
>   Battlemage**. Treat as a real risk to watch for, not a confirmed blocker.
> - WSL2's default VM memory/swap (50%/25% of Windows total RAM) can cause out-of-memory during
>   model load for a 32GB-class model, independent of available VRAM — raise `.wslconfig`'s
>   `memory`/`swap` before attempting to load a large model.
> - No reliable sourced WSL2-vs-native-Linux performance delta was found for this path — treat the
>   throughput numbers above as a native-Linux ceiling, not a WSL2 guarantee.
> - Vulkan is confirmed absent from WSL2 either way — if the SYCL-in-WSL2 path doesn't pan out, the
>   fallback is still Windows-native (Phase 2's original Option B, kept below), not Vulkan-in-WSL2.

**Action item before anything else:** try the WSL2-native path first (Phase 0 below) — it's the
cheaper thing to attempt and, if it works, removes an entire cross-machine networking phase from
this blueprint. Only fall back to a Windows-native server if it doesn't pan out.

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

1. **Try the WSL2-native SYCL path first** (this is the corrected recommendation — see the
   correction note in §1). Inside this WSL2 guest: install Intel's NEO/compute-runtime packages
   per [`intel/compute-runtime`'s `WSL.md`](https://github.com/intel/compute-runtime/blob/master/documentation/WSL.md)
   (the guest-side `.deb`s: `intel-opencl-icd`, `libze-intel-gpu1`, gmmlib, IGC — from the NEO
   GitHub releases, matched to the Windows host's Arc driver version), then run `sycl-ls` and/or
   `clinfo`. If the B70 is enumerated, the WSL2-native path is viable — proceed with Phase 2's
   Option A. If it isn't, or if you hit the CUDA/OpenCL-ICD collision (see §1's caveats — isolate
   with `ONEAPI_DEVICE_SELECTOR`/`OCL_ICD_VENDORS` before concluding it's absent, don't let a
   collision masquerade as "not found"), fall back to Phase 2's Option B (Windows-native).
2. **Do not attempt to unify both GPUs into one Vulkan process.** This was investigated
   specifically: Ubuntu's WSL2 Mesa package ships no `dzn` (Vulkan-on-D3D12) driver at all — it
   would have to be self-built from source with `-Dvulkan-drivers=microsoft-experimental`, its
   own build option name and a Mesa-emitted non-conformance warning both signal it's genuinely
   experimental, and — the decisive reason to skip it — the NVIDIA card would lose its
   `cooperative_matrix` tensor-core acceleration entirely under dzn (`matrix cores: none`,
   confirmed from source), on top of a measured ~30% translation-tax vs. native Vulkan even on the
   Intel side. Real capability (enumerating both GPUs in one process is mechanically confirmed
   possible via dxcore adapter enumeration), wrong trade for this hardware. SYCL for the Arc + CUDA
   for the 5060 Ti, as two independent lanes, beats this in every dimension that matters here.
3. Confirm the B70 shows up in Windows Device Manager / Intel Arc Control regardless of which path
   you end up on — needed either way, and it's the fastest way to rule out "not physically
   installed" before debugging software.
4. Optional, later: a native Linux boot would let both lanes share one OS trivially and matches
   every published B70 benchmark's actual test environment — not required to start, since Phase 0
   step 1 achieves the "one OS" benefit from inside WSL2 already, if it works.

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

### Phase 2 — Expand lane

**Option A — WSL2-native SYCL (try this first, per Phase 0 step 1).** Build llama.cpp with the
SYCL backend against the oneAPI DPC++ toolchain, run `llama-server` inside this same WSL2 guest,
reachable at `localhost:<port>` from everything else in the repo — no cross-machine networking,
no Windows Firewall rule, no `.wslconfig` networking mode needed. This is the path behind every
fast number cited in §1 (54.7 tok/s etc., measured on native Linux — treat as this option's
ceiling, not a guarantee, since no sourced WSL2-vs-native delta exists yet for this exact setup).
Before relying on it: raise `.wslconfig`'s `memory`/`swap` (WSL2 defaults to 50%/25% of Windows
RAM, which can OOM a 32GB-class model load independent of available VRAM), and isolate the
OpenCL/Level-Zero environment from CUDA's ICDs (`ONEAPI_DEVICE_SELECTOR`, `OCL_ICD_VENDORS`) given
this machine runs both stacks side by side. Watch for (not necessarily hit): a known, open,
unconfirmed-on-discrete-GPU SYCL process-teardown hang that can require `wsl --shutdown` to clear.

**Option B — Windows-native (fallback if Option A doesn't pan out).** Two sub-choices, real
tradeoff:
   - **Ollama + Vulkan on Windows** — fastest to stand up (Ollama's Windows build already ships
     Vulkan support), but measured ~2.2× slower decode than SYCL on this exact card family. Good
     for validating the architecture end-to-end quickly.
   - **llama.cpp built with the SYCL backend, run via `llama-server`, natively on Windows** —
     same ~2× throughput advantage as Option A, at the cost of the cross-machine networking this
     blueprint was originally built around (expose the Windows-side server on the host's
     LAN/WSL-visible IP, not just `127.0.0.1`; add a Windows Firewall inbound rule; confirm
     reachability from WSL2 with a plain `curl` before wiring project code to it).
   Recommendation if you land here: stand up Ollama+Vulkan first to validate the whole pipeline
   end-to-end, then swap to llama.cpp SYCL once the architecture is proven.

Regardless of A or B:

- **Pick the model.** For a coding-focused expand lane, look specifically for a coder-tuned
  model in the 30-35B MoE class (matching the model size the 54.7 tok/s number was measured
  against) or a dense 27-32B coder model if no suitable MoE coder variant exists — verify against
  current benchmarks at build time, same caveat as Phase 1. Benchmark it with the same method
  used for the compact lane so the two numbers are comparable.
- **If you want more than one expand-lane model available**, front `llama-server` with
  [`llama-swap`](https://github.com/mostlygeek/llama-swap) — it gives an OpenAI-compatible
  endpoint with on-demand model swapping, which is the proven pattern for this exact card.

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
- **Do not** try to unify both GPUs into one Vulkan process via a self-built Mesa `dzn` driver,
  even though it's mechanically possible (one ICD can enumerate both an Intel and an NVIDIA D3D12
  adapter in WSL2, confirmed from Mesa's dxcore adapter-enumeration source). It's explicitly
  experimental/non-conformant per Mesa's own build option and startup warning, costs the NVIDIA
  card its cooperative-matrix tensor-core path entirely, and loses ~30% vs. native Vulkan even on
  the Intel side. Two lanes on their native backends (SYCL for Arc, CUDA for the 5060 Ti) beats
  this outright.
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
  llama.cpp source code, official Arc Pro B70 / RTX 5060 Ti spec sheets). This pass's own
  Vulkan-visibility test (via Ollama's device discovery) was later found to be a false negative —
  see the correction below.
- Third pass: dedicated investigation of Intel Arc compute (Level Zero/SYCL, IPEX-LLM, OpenVINO)
  specifically inside WSL2, sourced against Intel's `compute-runtime` WSL documentation, its NEO
  release notes' per-platform WSL support matrix, and a real Arc Pro B70 running vLLM under WSL2
  in a public Microsoft/WSL issue thread. Established that the second pass's "WSL2 can't see the
  B70" conclusion was a false negative from testing exclusively through Ollama, which has no SYCL
  backend at all — this correction is folded into §1 and Phase 0/2 above.
- Fourth pass: dedicated investigation of Vulkan specifically inside WSL2 (Mesa's `dzn` driver),
  confirming it's mechanically capable of exposing both GPUs to one process but is unshipped by
  default, self-build-only, explicitly experimental, and costs the NVIDIA card its tensor-core
  path — folded into Phase 0 step 2 and §4 above as an explicit "don't build this" with reasoning.
