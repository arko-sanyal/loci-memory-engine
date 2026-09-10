# Heterogeneous layer-split pipelining: Arc Pro B70 + RTX 5060 Ti

Research pass, 2026-09-10. Scope: whether llama.cpp-style **pipeline / layer-split** (not
tensor-parallel collectives) can pool the two cards. Cross-vendor tensor parallelism is treated as
settled (not re-litigated).

Primary evidence is a local llama.cpp checkout at `/root/src/llama.cpp`, commit
`e5a8d439cef31f27fad6938233da10dae1ba5631` (2026-09-10, i.e. current master as of today). Source
line references below are to that commit.

---

## 1. Can one binary hold both CUDA and SYCL, and will layer-split use both?

### 1a. The build system does not exclude them — but one build tree probably still can't do it

`ggml/src/CMakeLists.txt:589-605` adds every backend through the same helper:

```cmake
ggml_add_backend(CUDA)
...
ggml_add_backend(SYCL)
```

and `ggml_add_backend` (line 428) is nothing but `if (GGML_<NAME>) add_subdirectory(...)`. **There
is no mutual-exclusion guard anywhere between `GGML_CUDA` and `GGML_SYCL`.** The historic "single
backend per build" behaviour is not enforced in CMake.

Upstream docs say so explicitly ([`docs/build.md:843`](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md)):

> In most cases, it is possible to build and use multiple backends at the same time. For example,
> you can build llama.cpp with both CUDA and Vulkan support by using the `-DGGML_CUDA=ON
> -DGGML_VULKAN=ON` options with CMake. At runtime, you can specify which backend devices to use
> with the `--device` option.

Note the example is CUDA+Vulkan, **not** CUDA+SYCL. That distinction matters, because SYCL is the
one backend with a hard toolchain requirement:

- `ggml/src/ggml-sycl/CMakeLists.txt:8-17` requires `-fsycl` support in `CMAKE_CXX_COMPILER` and
  wants `ONEAPI_ROOT` set (i.e. `icx`/`icpx`). `docs/backend/SYCL.md` build recipe is
  `-DGGML_SYCL=ON -DCMAKE_C_COMPILER=icx -DCMAKE_CXX_COMPILER=icpx`.
- `ggml/src/ggml-cuda/CMakeLists.txt` enables the `CUDA` language, so `.cu` files go through
  `nvcc`, which uses `CMAKE_CXX_COMPILER` as its **host** compiler. `nvcc` + `icpx` as host
  compiler is not a supported combination and is the concrete thing likely to break.

**I could not confirm that anyone has successfully configured a single build tree with
`-DGGML_CUDA=ON -DGGML_SYCL=ON`.** I searched llama.cpp issues via `gh search issues` for
"SYCL CUDA same time", "mixed vendor GPU", "Intel NVIDIA together", "Arc RTX together" — zero
relevant hits. Absence of reports, not evidence of impossibility.

### 1b. `GGML_BACKEND_DL` is the mechanism that actually sidesteps the compiler conflict

`ggml/src/ggml-backend-reg.cpp:574-599`:

```c
void ggml_backend_load_all_from_path(const char * dir_path) {
    ...
    ggml_backend_load_best("cuda",   silent, dir_path);
    ggml_backend_load_best("hip",    silent, dir_path);
    ...
    ggml_backend_load_best("sycl",   silent, dir_path);
    ggml_backend_load_best("vulkan", silent, dir_path);
```

Each backend is an independent `.so`/`.dll` discovered **by filename** (`libggml-cuda*.so`,
`libggml-sycl*.so`) in the executable dir / cwd / `GGML_BACKEND_DIR`, loaded via `dlopen`, and
accepted if it exports `ggml_backend_score() != 0` and reports
`reg->api_version == GGML_BACKEND_API_VERSION` (currently **2**, `ggml/src/ggml-backend-impl.h:11`).
`ggml_backend_load_best`/`load_backend` are called **independently per backend, with no exclusion
logic** (`ggml-backend-reg.cpp:220-261, 480-573`).

So the design intent is: build `libggml-cuda.so` in a gcc/nvcc tree, build `libggml-sycl.so` in an
icpx tree, drop both next to the binary alongside a shared `libggml-base.so`, and both register.
Requires `-DGGML_BACKEND_DL=ON -DBUILD_SHARED_LIBS=ON` (`ggml/src/CMakeLists.txt:188` makes
`GGML_BACKEND_DL` without `BUILD_SHARED_LIBS` a `FATAL_ERROR`).

Real-world evidence the DL split is what ships: llama.cpp issue
[#25017](https://github.com/ggml-org/llama.cpp/issues/25017) shows an official Windows SYCL build
logging

```
load_backend: loaded RPC backend from ...\ggml-rpc.dll
load_backend: loaded SYCL backend from ...\ggml-sycl.dll
load_backend: loaded CPU backend from ...\ggml-cpu-haswell.dll
```

— three separate modules in one process. But that release ships no `ggml-cuda.dll`.

**Explicitly unconfirmed:** I did not build anything (out of scope), and I found no report of
anyone dropping a separately-built `ggml-cuda.*` and `ggml-sycl.*` into one directory. "CMake
permits it" is not "it works." Named risks:

1. **Both modules must be at the same `GGML_BACKEND_API_VERSION` (2) and resolve the *same*
   `libggml-base.so`** — they link it `PRIVATE` and DL mode requires `BUILD_SHARED_LIBS=ON`.
2. **The runtime-collision risk this project has already hit becomes an in-process one.** This is
   the reason to rank the DL path *below* RPC. `ggml/src/ggml-sycl/CMakeLists.txt` does
   `find_package(MKL REQUIRED)` and links `MKL::MKL_SYCL::BLAS`, plus the Level Zero loader
   (`ze_loader`). In the DL layout, oneMKL, the Level Zero loader/UR adapters, and CUDA's runtime
   and OpenCL ICDs all live in **one address space under one `LD_LIBRARY_PATH`**. The blueprint's
   own §1 caveat already documents that CUDA's OpenCL libraries on `LD_LIBRARY_PATH` can make
   Intel's SYCL tooling load NVIDIA's OpenCL runtime and segfault, and this machine has *already
   reproduced* a null-deref crash in Intel's Level Zero v2 UR adapter requiring
   `SYCL_UR_USE_LEVEL_ZERO_V2=0`. The per-process isolation knobs the blueprint relies on
   (`ONEAPI_DEVICE_SELECTOR`, `OCL_ICD_VENDORS`, `SYCL_UR_USE_LEVEL_ZERO_V2`) are **process-wide**,
   so in the single-binary layout you cannot set them differently for the two backends. The RPC
   layout (§1e) keeps them in separate processes and is the only option that preserves that
   isolation — which is why §6 recommends starting there if this is ever revisited.

### 1c. A path that used to exist and has been *removed* — worth knowing

`docs/backend/SYCL.md`, News section, **2026.02**:

> Remove support for Nvidia & AMD GPU, because the oneAPI plugin for Nvidia & AMD GPU is
> unavailable: download/installation channels are out of work. User can't build up the software for
> Nvidia & AMD GPU.

Corroborated in source — `ggml/src/ggml-sycl/CMakeLists.txt:3-5`:

```cmake
if (NOT GGML_SYCL_TARGET MATCHES "^(INTEL)$")
    message(FATAL_ERROR "GGML_SYCL_TARGET: Invalid target, the supported options are [INTEL]")
endif()
```

So the "one SYCL backend drives both the Intel and the NVIDIA card via the Codeplay oneAPI-for-CUDA
plugin" route is **closed as of Feb 2026**. Don't chase it.

### 1d. If both backends do load, layer-split is fully vendor-agnostic — confirmed

Device enumeration (`src/llama.cpp:221-270`) iterates **all** registered devices and accepts
anything of type `GGML_BACKEND_DEVICE_TYPE_GPU`. There is **no filter by backend or vendor**. The
only rejection is a dedup: a device whose `props.device_id` matches one already in the list is
skipped ("already using device ... with the same id") — that exists so one physical GPU seen by two
backends isn't counted twice, and it would not affect an Arc + an RTX.

Layer assignment (`src/llama-model.cpp:1462-1506`) is equally agnostic:

- default split proportions come from each device's **free memory**
  (`ggml_backend_dev_memory`), or from `--tensor-split` if given;
- `get_layer_buft_list(il)` maps layer index → device via `std::upper_bound` over the normalized
  split points and returns `devices.at(layer_gpu).dev`.

Nothing in that path knows or cares that device 0 is CUDA and device 1 is SYCL.

`docs/multi-gpu.md` (upstream) documents the flags:

| flag | meaning |
|---|---|
| `-sm layer` (**default**) | "Pipeline parallelism. Each GPU holds a contiguous slice of layers. The KV cache for layer *l* lives on the GPU that owns layer *l*." |
| `-sm row` | **Deprecated** tensor-parallel path |
| `-sm tensor` | **EXPERIMENTAL** TP via a "meta device"; NCCL-accelerated; "Performance should be good for multiple NVIDIA GPUs using the CUDA backend, **no guarantees otherwise**" |
| `-ts 3,1` | split proportions, in `--device` order |
| `-dev`/`--list-devices` | pick devices by name (`CUDA0`, `SYCL0`, ...) |

So the intended invocation would literally be
`llama-server -m model.gguf -dev CUDA0,SYCL0 -ngl all -sm layer -ts 1,2`.

> **Scope note for a future session, so this isn't mistaken for an oversight:** a *new*
> tensor-parallel path, `-sm tensor`, exists as of this commit. It builds a synthetic
> `GGML_BACKEND_DEVICE_TYPE_META` device over several real devices
> (`ggml/src/ggml-backend-meta.cpp`, `src/llama.cpp:177-219`) and uses NCCL for reductions when
> available. It is *not* obviously gated on a cross-vendor collective library, so it is not
> self-evidently covered by the settled "cross-vendor TP is structurally impossible" finding.
> Upstream marks it EXPERIMENTAL, restricts it to an architecture allow-list that **excludes most
> MoE models** (DeepSeek2, OLMoE, Grok, Minimax-M2, Jamba, ... — i.e. likely the expand-lane model
> class), requires flash-attention and unquantized KV, disables `--fit`, and says performance is
> good "for multiple NVIDIA GPUs using the CUDA backend, **no guarantees otherwise**." **Not
> evaluated here** — this pass was scoped to layer-split pipelining, per the task.

**Answer to Q1:** the build system does not forbid it; one build tree is likely blocked by the
icpx/nvcc host-compiler conflict; `GGML_BACKEND_DL` with two separate build trees is the designed
way around that and is unverified-but-plausible; and *if* both modules register, `-ngl` / `-sm
layer` / `--tensor-split` will assign layers across a CUDA device and a SYCL device with no
vendor-specific code path in the way.

### 1e. The path that avoids the build problem entirely: the RPC backend

`tools/rpc/README.md` documents `ggml-rpc-server`, at protocol **v3.0.0**, still labelled
"proof-of-concept ... fragile and insecure. Never run the RPC server on an open network." Build
each server against its own backend:

```bash
cmake .. -DGGML_CUDA=ON -DGGML_RPC=ON      # tree 1, gcc/nvcc
cmake .. -DGGML_SYCL=ON -DGGML_RPC=ON \
         -DCMAKE_C_COMPILER=icx -DCMAKE_CXX_COMPILER=icpx   # tree 2, oneAPI
```

then `llama-server ... --rpc 127.0.0.1:50052,127.0.0.1:50053`. The README's own examples use
loopback (`127.0.0.1:50052`), so this works **on one machine** — no networking phase. RPC devices
enter the same device list as local GPUs (`src/llama.cpp:233-236` routes `reg name == "RPC"` into
`rpc_servers`, which is then prepended to the device list), so `-ngl`/`-ts`/`-sm layer` treat them
as ordinary devices. Two separate processes means the icpx/nvcc conflict never arises, and the
CUDA/oneAPI ICD environments stay isolated.

Cost: every boundary crossing is a TCP serialization instead of a PCIe copy — the same
host-staging cost class as §3 below, plus loopback syscall overhead.

**I could not confirm anyone has run an Intel SYCL rpc-server + NVIDIA CUDA client.** It is the
mechanism most likely to work, on design grounds, not on reported-success grounds.

---

## 2. Has anyone actually run Intel Arc + NVIDIA together in one llama.cpp process?

**I could not find a single documented case.** Searched: `gh search issues` on ggml-org/llama.cpp
for "SYCL CUDA same time", "mixed vendor GPU", "Intel NVIDIA together", "Arc RTX together",
"heterogeneous GPU"; plus web searches targeting r/LocalLLaMA, HN, and 2025-2026 blogs.

What I *did* find:

- **Mixed-vendor layer-split is real — but the documented instance is NVIDIA + AMD over Vulkan.**
  [grosan.co.uk, "Layer Split Model Parallelism on Hybrid AMD NVIDIA AI Servers using Vulkan and
  Llama CPP"](https://grosan.co.uk/layer-split-model-parallelism-on-hybrid-amd-nvidia-ai-servers-using-vulkan-and-llama-cpp/):
  one Tesla V100-PCIE-32GB + two Radeon AI PRO R9700 32GB on PCIe 3.0, single Vulkan backend,
  `--split-mode layer -ngl 99999 --main-gpu 2 -ctk q8_0 -ctv q8_0 --flash-attn on --kv-unified`.
  Qwen3.6-35B-A3B Q8: prompt processing **2904-3703 tok/s**, decode **61.7-63.9 tok/s**. The
  article's own conclusion: *"Layer split across vendors buys you capacity. It does not buy you
  speed."*
  **This path is unavailable on this machine** — prior research (blueprint §1, Phase 0 step 2)
  established that no Vulkan driver exists in this WSL2 guest and `dzn` would cost the NVIDIA card
  its cooperative-matrix path. So the one mixed-vendor mechanism with published numbers is the one
  already ruled out here.
- llama.cpp issue [#25017](https://github.com/ggml-org/llama.cpp/issues/25017) — Intel A770 + A750,
  **same vendor**, SYCL. Included for the DL-module evidence in §1b, not as cross-vendor evidence.
  (Its numbers — 27B Q6_K, `-sm tensor` pp512 87.94 / tg128 1.73 vs `-sm layer` pp512 49.28 /
  tg128 2.18 — are distorted by `--cpu-moe` and `--direct-io` and are not a usable proxy.)
- Several 2026 SEO-ish aggregator pages (localaiops.com, arsturn.com, spheron.network) assert
  "llama.cpp supports heterogeneous multi-GPU including Intel Arc". They cite no first-hand test and
  one (localaiops) returned HTTP 403 to fetch. **Treat as unsourced.**

**Verdict on Q2: no documented Arc-plus-NVIDIA-in-one-llama.cpp-process case exists that I could
find.** Doing it would be first-of-its-kind work, in a config nobody upstream tests.

---

## 3. What layer-split buys, and what the cross-device hop actually costs

### 3a. Yes, it genuinely pools VRAM for model weights and KV

`-sm layer` gives each GPU a contiguous slice of layers, weights allocated in that device's buffer
type. A model too big for either card alone does load. Upstream `docs/multi-gpu.md` states the case
plainly: *"The model doesn't fit in a single GPU's VRAM. By spreading the weights across two or
more GPUs the whole model can stay on accelerators."*

Practical ceiling here: ~14.8 GiB usable (5060 Ti, per the blueprint's own `nvidia-smi` measurement)
+ ~31.2 GiB (B70, per Phase 0 `sycl-ls`) ≈ **~46 GiB**, minus compute buffers and KV. Not 48.

### 3b. The prompt's cost model is inverted — say so plainly

**What crosses the boundary is one hidden-state activation, not weights.** Weights stay resident on
whichever card owns their layers. With two devices and `-sm layer` there is exactly **one** device
boundary in the layer stack per forward pass. Size = `n_embd × n_tokens × sizeof(dtype)`:

| model shape | per token (f32) | per token (f16) | per 512-token batch (f32) |
|---|---|---|---|
| 30B-A3B MoE class, `n_embd`=2048 | 8.00 KiB | 4.00 KiB | 4.00 MiB |
| 27B dense class, `n_embd`=4608 | 18.00 KiB | 9.00 KiB | 9.00 MiB |
| 32B dense class, `n_embd`=5120 | 20.00 KiB | 10.00 KiB | 10.00 MiB |

At even 200 tok/s decode that is **1.6-4 MB/s** across a PCIe 4.0 x16 link good for ~25 GB/s.
**Bandwidth is not the bottleneck and is not close to being the bottleneck.**

### 3c. The real costs are two different things

**(i) Cross-vendor copies drop off the async fast path, drain the source backend, and stage through
host RAM. This is a genuinely cross-vendor-specific penalty — same-vendor multi-GPU does not pay
it.** Confirmed in `ggml_backend_sched_compute_splits` (`ggml/src/ggml-backend.cpp`), which is the
code that actually moves data at a split boundary (note: *not* the standalone
`ggml_backend_tensor_copy_async` wrapper). Its cross-backend input path is:

```c
// try async copy, but if not possible, we can still use a sync copy without synchronizing the
// dst backend, since we handle the synchronization here with multiple copies and events
if (!split_backend->iface.cpy_tensor_async ||
    !split_backend->iface.cpy_tensor_async(input_backend, split_backend, input, input_cpy)) {
    ggml_backend_synchronize(input_backend);
    if (sched->events[split_backend_id][sched->cur_copy] != NULL) {
        ggml_backend_event_synchronize(sched->events[split_backend_id][sched->cur_copy]);
    } else {
        ggml_backend_synchronize(split_backend);
    }
    ggml_backend_tensor_copy(input, input_cpy);
}
```

Both backends' `cpy_tensor_async` reject a cross-vendor pair outright:

- CUDA (`ggml-cuda.cu`): `if (!ggml_backend_is_cuda(backend_src) || !ggml_backend_is_cuda(backend_dst)) return false;`
- SYCL (`ggml-sycl.cpp`): `bool is_cpy_supported = dst->buffer->buft == ggml_backend_sycl_buffer_type(...) && ggml_backend_buffer_is_sycl(src->buffer);`

So **CUDA↔CUDA takes the async fast path; CUDA↔SYCL always falls through.** The fallback then
(a) fully drains the **source** backend via `ggml_backend_synchronize(input_backend)` — the
destination is *not* fully drained in pipeline-parallel mode, it's handled by the copy-slot event,
per the code's own comment — and (b) runs `ggml_backend_tensor_copy`, which for two non-host,
non-peer buffers takes the branch logging *"warning: slow copy from ... to ..."* and does
`malloc(nbytes)` → device→host `tensor_get` → host→device `tensor_set` → `free`.

For 8-20 KiB the transfer time is trivial. The cost is the **source drain**: pipeline parallelism
exists precisely so GPU A can work on micro-batch *n+1* while GPU B works on *n*, and draining A at
every handoff is exactly what prevents that overlap.

**(ii) Decode is sequential — layer-split never gives you 2× tokens/sec.** During generation only
one GPU computes at a time; the other idles waiting for the handoff. llama.cpp maintainer `slaren`,
[discussion #11236](https://github.com/ggml-org/llama.cpp/discussions/11236):

> The default `-sm layer` only supports pipeline parallelism when evaluating large prompts. You
> would probably need to use a larger prompt to observe a significant improvement.

and the reporter's follow-up on 4× A10G:

> `-sm row` was very slow (x2-3), and **using a single GPU was still faster than utilizing multiple
> GPUs**, but using larger prompts indeed helped a lot.

Upstream `docs/multi-gpu.md` says the same: pipeline-parallel "requires many tokens to scale well"
and "maximizes batch throughput" — it is a *prefill* and *batch* optimization, not a decode one.
Expect combined decode ≈ roughly the weighted average of the two cards' individual speeds, never
the sum. The Vulkan hybrid article reaches the same conclusion independently ("buys you capacity...
not speed").

**(iii) The consequence: pipeline-parallel mode turns on but is undercut.** llama.cpp *does* enable
its scheduler's pipeline-parallel mode for a mixed CUDA+SYCL layer split — the gate at
`src/llama-context.cpp:428-455` requires `n_devices() > 1`, all layers offloaded,
`LLAMA_SPLIT_MODE_LAYER`, `offload_kqv`, no tensor overrides, and every device reporting
`props.caps.async && props.caps.events`. Both backends hard-code `async = true` and `events = true`
(`ggml_backend_sycl_device_get_props`; the CUDA equivalent). So the mode engages — but the
source-backend drain in §3c(i) removes most of the overlap it exists to create. **Prefill, the one
workload where `-sm layer` demonstrably helps, is therefore the part most degraded by going
cross-vendor.** This is a source-level inference; I have no measurement of the magnitude and could
not find one.

### 3d. Reconciling with the blueprint's "20-40% PCIe penalty"

`docs/dual-gpu-coding-intelligence-blueprint.md:255` states "a 20-40% PCIe penalty on this
machine's gen-4 link under multi-GPU layer split." **I could not find a source supporting a general
20-40% bandwidth penalty for `-sm layer`, and my source reading contradicts the bandwidth framing**
(§3b: the link carries single-digit MB/s). That figure sits inside the §4 bullet arguing against
`OLLAMA_LLM_LIBRARY=vulkan`, so it is most plausibly specific to that Ollama/Vulkan-unified context,
or to `-sm row`, or it is a restatement of "you don't get a speedup" as if it were a bandwidth cost.
Flagging it rather than silently overwriting it: the *conclusion* (layer-split doesn't buy speed) is
right; the *stated mechanism* (PCIe bandwidth) is wrong.

---

## 4. KV cache in a layer-split setup — confirmed, your understanding is correct

Both documented and verified in source.

`docs/multi-gpu.md`, `-sm layer` row: *"The KV cache for layer l lives on the GPU that owns layer l."*

`src/llama-kv-cache.cpp:214-225`:

```c
ggml_backend_buffer_type_t buft = ggml_backend_cpu_buffer_type();
...
    auto * dev = model.dev_layer(il);
    buft = ggml_backend_dev_buffer_type(dev);
...
ggml_context * ctx = ctx_for_buft(buft);
```

The per-layer K/V tensors take their buffer type directly from `model.dev_layer(il)` — the same
`dev_layer` array populated by the layer-assignment loop in §1d. There is no independent KV
placement policy.

**So: yes, KV placement is fully determined by layer placement. "Pooling the KV cache" is not a
separate capability — it is an automatic consequence of splitting layers, and it cannot be tuned
independently of `--tensor-split`.** (The one thing that *does* split KV separately from layers is
`-sm tensor`, which upstream describes as splitting "both weights *and* KV" via the meta device —
and that is the tensor-parallel path already ruled out.)

---

## 5. Other frameworks with a heterogeneous pipeline/layer-split mode

| Project | Heterogeneous layer-split? | Notes |
|---|---|---|
| **llama.cpp** | Yes, by design (§1) | The only realistic candidate. `-sm layer` + `GGML_BACKEND_DL` or RPC. |
| **koboldcpp** (LostRuins) | **No SYCL backend** | Fork's own [issue #656 "Add integration/CMake for SYCL backend"](https://github.com/LostRuins/koboldcpp/issues/656) is **still OPEN**; maintainer: *"Unfortunately I have no way to test it as I have not gotten SYCL to run on my device."* It ships CUDA / HIP / Vulkan and, as of ~v1.118.x (2026), RPC. So koboldcpp does **not** make this easier — it makes it impossible without Vulkan, which is absent here. Corrects the task's "might have made this easier" hypothesis. |
| **ExLlamaV2 / ExLlamaV3** | No | CUDA-only quantization engine. Ruled out on vendor grounds before pipeline questions arise. |
| **text-generation-webui** | No | Multi-backend *loader*, not a multi-backend *runtime*: it shells out to llama-cpp-python / ExLlama, which inherit single-backend prebuilt wheels. Adds nothing llama.cpp doesn't already have. |
| **llama-cpp-python** | Inherits llama.cpp | Would need a custom build with the same DL layout; no additional capability. |
| **MLC-LLM** | Not for this | TVM/Disco multi-GPU is tensor-parallel over a per-target compiled artifact; a model is compiled for *one* target (CUDA, Vulkan, ROCm). No documented mixed-target single-model pipeline. **I could not find any 2026 evidence of heterogeneous cross-vendor pipeline support.** |
| **vLLM / SGLang / IPEX-LLM / OpenVINO** | Ruled out already | TP-only, per prior research. IPEX-LLM additionally archived upstream. |
| **Research systems** (LLM-PQ arXiv 2403.01136, Hetis arXiv 2509.08309, HeterMoE arXiv 2504.03871) | Academic | Address heterogeneous *NVIDIA* clusters, not cross-vendor runtimes. Not deployable. |

**Nothing outside llama.cpp offers this.** The realistic option set is exactly: (a) one llama.cpp
process with two DL backend modules, (b) llama.cpp with a SYCL rpc-server + CUDA client, (c) Vulkan
— unavailable in this WSL2.

---

## 6. Bottom line

**Verdict: do not pursue heterogeneous layer-split pooling. Keep the two-independent-lanes
architecture.** And note the reasoning is *stronger* than the blueprint's, because it survives the
mechanism turning out to be possible — which, unlike cross-vendor tensor parallelism, it probably
is. Layer-split is not structurally blocked: llama.cpp's device enumeration and layer assignment
are genuinely vendor-agnostic, `GGML_BACKEND_DL` exists precisely so backends built by different
toolchains can coexist in one process, the RPC backend sidesteps the icpx/nvcc conflict entirely,
and the PCIe hop costs single-digit MB/s — nothing like the bandwidth catastrophe the question
assumed. It is still the wrong call, for four reasons that compound. **First, there is no VRAM
pressure to relieve**: the expand-lane target (`qwen3-coder:30b`, a 30B-A3B MoE at Q4_K_M, ~18-19 GB)
already fits in the B70's 31.2 GiB with room for context, so pooling to ~46 GiB only unlocks a
70B-dense tier this project has not established it wants — and at 4-bit on a card pair whose decode
would land near the *average* of the two, not the sum. **Second, pooling destroys the architecture's
actual value**: one model spanning both cards occupies both cards for every request, which
eliminates the always-warm compact lane — the low-latency, high-frequency path that blueprint §2
correctly identifies as the thing a coding assistant needs most. You would trade a working
two-lane system for one slower lane. **Third, layer-split provably buys capacity, not speed** —
maintainer-confirmed (`slaren`: `-sm layer` only pipelines on large prompts; a single GPU beat four
A10Gs at decode) and independently reproduced on the only published mixed-vendor layer-split
("buys you capacity. It does not buy you speed"), while cross-vendor specifically makes it worse,
since every boundary crossing falls off an async fast path that same-vendor pairs *do* get, into a
full drain of the source backend plus a `malloc` + device→host→device staging copy — undercutting
the one workload (prefill) where pipelining actually helps. **Fourth, the engineering cost is first-of-its-kind**: I found zero
documented cases of an Intel Arc and an NVIDIA GPU in a single llama.cpp process by any mechanism,
the one published mixed-vendor recipe runs on Vulkan (absent from this WSL2), koboldcpp's SYCL
integration issue is still open and unimplemented, and this machine already has a live SYCL bug
requiring `SYCL_UR_USE_LEVEL_ZERO_V2=0` — debugging an untested cross-vendor configuration on top of
that is a large, open-ended cost for a capability tier nobody has asked for. If the 70B-class
question ever becomes real, revisit it then, and start with the RPC path (`-DGGML_RPC=ON` in both
trees, loopback) rather than the single-binary DL path, because it isolates the two runtime
environments that this machine has already proven willing to collide.

---

### Confidence and limitations

- **High confidence (read from source at a known commit):** no CMake exclusion; DL loads cuda and
  sycl independently; device enumeration is vendor-agnostic; layer→device and KV→layer mapping;
  the scheduler's cross-vendor copy falls off the async path into a source drain + host-staged copy
  while same-vendor CUDA↔CUDA does not; SYCL's NVIDIA target removed.
- **Medium (documented upstream, not tested here):** `-sm layer` semantics and flags; RPC
  loopback usage; pipeline-parallel gate conditions.
- **Low / explicitly unconfirmed:** that a two-tree DL build of CUDA+SYCL actually loads and runs
  (no build performed, none reported); that a SYCL rpc-server + CUDA client works; the magnitude of
  the cross-vendor prefill-overlap loss; any Arc+NVIDIA benchmark number whatsoever.
- **Corrected from prior repo research:** the blueprint's "20-40% PCIe penalty ... under multi-GPU
  layer split" (line 255) is unsourced as a general layer-split claim and mis-attributes the cost to
  bandwidth. Conclusion unchanged; mechanism wrong.
- Note: `agent_instructions.md` says research artifacts belong in the documentation location with
  sources/scope/limitations. This was returned as a report rather than committed to `docs/`, per the
  task's instruction not to write report files; it can be committed as e.g.
  `docs/research-heterogeneous-layer-split.md` if wanted.
