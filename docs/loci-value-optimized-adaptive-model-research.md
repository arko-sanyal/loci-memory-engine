# LOCI Value-Optimized Persistent Memory and Dynamic Neural Capacity

Date: 2026-09-10

Status: Research and implementation blueprint. No production model weights or inference code were changed by this document.

## Executive conclusion

The clarification "attention is focused, while memory is infinite for retrieval to current context" gives the architecture a useful separation of concerns:

- LOCI is the persistent retrieval substrate. It can grow beyond the model context window and should retain provenance, time, confidence, links, outcomes, and compressed representations.
- CARD is the focused active-context control plane. It decides what enters the current prompt, how much evidence is hydrated, how much reasoning is allowed, and when to expand or prune the working set.
- LACC, proposed here as the LOCI Adaptive Capacity Controller, is the model-capacity controller. It selects depth, reasoning branches, adapters, experts, KV-cache policy, and-only where safe-weight pages according to task value per cost.

The core optimization target is not "retrieve the most similar items" and not "activate the largest model." It is:

    maximize expected task value per token, latency, memory, energy, and risk

This makes memory selection and model-capacity selection instances of the same decision problem. A fact, summary, graph neighborhood, adapter, expert, layer, or weight shard should be activated when its expected marginal value exceeds its cost and risk.

Dynamic model capacity must not be implemented as arbitrary live mutation of the base model. The safe progression is:

1. instrument the existing LOCI and CARD boundaries;
2. add value and outcome ledgers;
3. make evidence hydration and pruning measurable;
4. add immutable, checksummed adapter/expert/module catalogs;
5. introduce early exit, sparse experts, and adapter selection;
6. add weight paging only for predeclared, validated modules with bounded latency and rollback.

## 1. Scope and repository audit

This report covers persistent memory, focused context, contextual value extraction, adaptive inference effort, sparse capacity, and model-weight retrieval.

The checked-in repository currently contains a smaller foundation than the long-term design:

- loci-engine/INDEX.md describes the planned eight-stream memory architecture and marks substantial portions as planned or not started.
- loci_engine/schema.sql currently provides the two-table core for entities and facts.
- loci_engine/heat.py provides bounded heat, decay, hop weighting, and HOT/WARM/COLD tiers.
- loci_engine/store.py supports entity upsert, decayed reads, touching entities, and fact insertion/listing.
- loci_engine/vectors.py provides a separate 768-dimensional sqlite-vec plus FTS5 retrieval path with reciprocal-rank fusion.
- The design specification proposes versioned facts, links, goals, sessions, thoughts, crystallization, pruning, forecasting, reflection, mood, and CARD hydration/context-efficiency, but those are not equivalent to a production-complete implementation.

Therefore, the recommendations below are deliberately staged. The first implementation target should be an observable value-ledger and CARD hydration loop, not a claim that infinite context or dynamic weight routing already exists.

## 2. Research synthesis

### 2.1 Persistent memory is externalized, updateable knowledge

Retrieval-Augmented Generation separates a parametric model from an updateable non-parametric memory. Lewis et al. show why this is important: external retrieval improves access to specific and changing knowledge without requiring full model retraining. RETRO similarly demonstrates that a language model can use a very large retrieval database to improve capability while reducing reliance on parameter count.

This supports the LOCI role. LOCI should be treated as an evidence and experience store, not as an oversized prompt. Retrieval must produce compact, attributable evidence packets rather than dumping all matching text into CARD.

Sources:

- Lewis et al., Retrieval-Augmented Generation: https://arxiv.org/abs/2005.11401
- Borgeaud et al., Improving Language Models by Retrieving From Trillions of Tokens: https://arxiv.org/abs/2112.04426

### 2.2 Infinite context is a systems property, not a single attention window

MemGPT frames long-lived agent context as virtual memory management: move information between fast and slow tiers according to demand. Infini-attention combines local attention with a compressive long-term memory so that the model can process long sequences with bounded memory and compute. StreamingLLM shows that attention sinks plus a recent-token window can stabilize streaming attention without retaining every token.

The practical conclusion is that "infinite memory" should mean an effectively unbounded external store plus bounded active hydration. The active context remains finite and focused. It is continuously rebuilt from LOCI using CARD policies.

Sources:

- Packer et al., MemGPT: https://arxiv.org/abs/2310.08560
- Munkhdalai et al., Leave No Context Behind: Efficient Infinite Context Transformers with Infini-attention: https://arxiv.org/abs/2404.07143
- Xiao et al., Efficient Streaming Language Models with Attention Sinks: https://arxiv.org/abs/2309.17453
- Dai et al., Transformer-XL: https://arxiv.org/abs/1901.02860
- Rae et al., Compressive Transformers: https://arxiv.org/abs/1911.05507

### 2.3 Similarity is insufficient; value needs time, goals, and outcomes

LongMemEval identifies sustained-interaction failures involving information extraction, multi-session reasoning, temporal reasoning, knowledge updates, and selective abstention. The benchmark reports a large accuracy drop as interaction history accumulates and recommends session decomposition, fact-augmented key expansion, and time-aware query expansion.

HippoRAG combines an LLM, a knowledge graph, and Personalized PageRank for multi-hop retrieval. This is a useful model for LOCI's links and spreading activation: a relevant fact can make an associated entity or event valuable even when lexical similarity is weak.

Sources:

- Wu et al., LongMemEval: https://arxiv.org/abs/2410.10813
- Gutiérrez et al., HippoRAG: https://arxiv.org/abs/2405.14831

The repository's existing heat mechanism is a useful starting signal, but heat alone is not value. Heat records access or activation history; value must additionally measure whether retrieval helped, whether it was trusted, whether it was stale or contradictory, and what it cost.

### 2.4 Adaptive model capacity already has several validated forms

Sparse Mixture-of-Experts routes each input through a subset of parameters. Switch Transformers demonstrate that activated compute can remain relatively constant while total parameter capacity increases. PEER extends the idea toward very large numbers of tiny experts selected through product-key retrieval.

Mixture-of-Depths routes only selected tokens through a layer under a fixed compute budget. LayerSkip trains models for early exit and self-speculative decoding. These results support task-dependent depth and node activation, but they require training or fine-tuning for stable routing. They do not justify loading arbitrary tensors at runtime without contracts.

Sources:

- Fedus et al., Switch Transformers: https://arxiv.org/abs/2101.03961
- He, Mixture of a Million Experts: https://arxiv.org/abs/2407.04153
- Raposo et al., Mixture-of-Depths: https://arxiv.org/abs/2404.02258
- Elhoushi et al., LayerSkip: https://arxiv.org/abs/2404.16710

LoRA and its extensions provide the safest first form of dynamic model specialization: a frozen base plus small low-rank deltas. ALoRA-style rank allocation supports the same value principle at a finer granularity by removing low-value ranks and reallocating capacity to useful modules.

Sources:

- Hu et al., LoRA: https://arxiv.org/abs/2106.09685
- Liu et al., ALoRA: https://arxiv.org/abs/2403.16187

### 2.5 Weight retrieval is related to, but different from, memory retrieval

A retrieved memory item is data interpreted by a stable model. A retrieved weight module changes the computation performed by the model. The latter has greater failure impact, compatibility constraints, and security risk.

FlexGen demonstrates tensor placement across GPU, CPU, and disk, along with quantization, as a systems strategy for running large models under constrained GPU memory. This is weight placement/offload, not semantic retrieval. A production LOCI/LACC design should distinguish:

- evidence retrieval: text, facts, vectors, summaries, graph links;
- state retrieval: KV cache, recurrent/compressive state, session summaries;
- behavior retrieval: adapters, experts, routers, tool policies;
- weight paging: validated tensor shards for a known architecture and version.

Sources:

- Sheng et al., FlexGen: https://arxiv.org/abs/2303.06865
- Liu et al., CacheGen: https://arxiv.org/abs/2310.07240

KV-cache selection is another focused-attention problem. H2O retains heavy-hitter and recent tokens; SnapKV learns attention-head-specific important positions from an observation window. These methods reinforce the CARD principle: retain the information expected to matter, with a recency or sink safeguard, under an explicit memory budget.

Sources:

- Zhang et al., H2O: https://arxiv.org/abs/2306.14048
- Li et al., SnapKV: https://arxiv.org/abs/2404.14469

## 3. Unified value model

LOCI and LACC should share a common value ledger. Every candidate memory item and every candidate model module receives a feature vector and an estimated marginal utility.

A candidate record should include:

- relevance to the current task and subtask;
- goal fit and dependency coverage;
- source trust and provenance completeness;
- freshness and temporal validity;
- confidence and agreement with other evidence;
- contradiction risk;
- estimated outcome gain from prior uses;
- novelty or redundancy;
- compression loss;
- token, VRAM, latency, energy, and bandwidth cost;
- sensitivity and required approval level.

A practical initial score is:

    utility = (relevance * goal_fit * trust * confidence
               * freshness * expected_outcome_gain)
              - redundancy_penalty
              - contradiction_penalty
              - compression_loss
              - risk_penalty

    priority = utility / (token_cost + latency_cost + memory_cost_weight)

The multiplicative terms prevent a highly similar but untrusted or stale item from dominating. The additive penalties make risk visible. All coefficients should be configurable by task profile and learned only from logged outcomes after evaluation.

For model modules, replace token cost with activated parameter count, load latency, VRAM, and expected error reduction:

    module_priority =
        expected_error_reduction * task_fit * confidence
        / (activated_params + load_latency + vram_cost)

The controller should select a set under constraints, not greedily activate everything. A knapsack or budgeted submodular approximation is appropriate for the first implementation. The system must also reserve a safety budget for verification and fallback.

## 4. CARD as the focused-attention controller

CARD should own the active context. The name can be interpreted operationally as Context Assembly, Retrieval, and Decision-or retained as the project's existing term.

CARD's responsibilities:

1. classify the request and determine task profile;
2. create query facets: entities, time, constraints, expected outputs, and unknowns;
3. ask LOCI for candidate memories, summaries, graph neighbors, and prior outcomes;
4. score candidates with value, confidence, freshness, and cost;
5. assemble a bounded evidence packet with provenance;
6. decide whether to retrieve more, prune, ask a clarification, or abstain;
7. select an inference-capacity plan through LACC;
8. run verification proportional to risk;
9. write outcomes back to LOCI.

The key invariant is:

    CARD may select what is active; LOCI may retain what is inactive.

Pruning from CARD is not deletion from LOCI. Low-priority content should be evicted from the active context, summarized, or left dormant, while audit evidence remains retained according to retention policy.

### Task profiles

Use explicit profiles rather than one global budget:

| Profile | Memory policy | Capacity policy | Verification |
| --- | --- | --- | --- |
| execute_simple | small high-confidence packet | shallow depth, one path | schema/result checks |
| retrieve_factual | provenance and freshness first | compact model | citation and contradiction check |
| reason_multi_hop | graph expansion and diverse evidence | deeper depth, more nodes | intermediate proof/checkpoints |
| reason_high_risk | conservative retrieval, explicit uncertainty | strongest validated modules | independent verifier and approval gate |
| transform_or_create | retrieve style, constraints, and examples | specialized adapter if proven | structural and policy checks |
| explore_research | broad candidate recall then pruning | adaptive branches | source coverage and abstention |

## 5. LACC: dynamic nodes, pruning, and model capacity

LACC should operate after CARD has assembled an initial evidence packet. It can increase or prune capacity according to uncertainty and task needs.

### Expand capacity when

- the task is multi-hop or the dependency graph is incomplete;
- evidence conflicts;
- confidence is below threshold;
- the output is high-impact;
- a verifier identifies an unresolved error;
- a tool result changes the plan;
- a specialist adapter or expert has high predicted value.

### Prune capacity when

- the task is simple and confidence is high;
- candidate branches converge;
- verifier agreement is strong;
- marginal improvement per cost falls below threshold;
- the active context contains redundant or stale material;
- a module repeatedly causes regressions for the task family.

Expansion must be bounded by a total budget and a maximum number of retries. Pruning should happen at several levels:

- evidence items from CARD;
- graph neighbors and speculative branches;
- reasoning nodes or search branches;
- KV tokens;
- model layers via trained early exit;
- experts or adapters via sparse routing;
- weight pages from CPU/disk cache after use.

A safe control cycle is:

    observe task -> estimate uncertainty
    -> choose retrieval budget and capacity budget
    -> execute
    -> verify
    -> expand once if expected value exceeds cost
    -> otherwise prune, answer, or abstain
    -> log outcome

"Dynamic node increase" should therefore mean controlled search/compute allocation, not uncontrolled self-replication.

## 6. Proposed data contracts

Add a value ledger rather than overloading the current heat field.

### memory_value

Suggested fields:

- memory_id, version_id, entity_id, fact_id;
- relevance, goal_fit, trust, freshness, confidence;
- reuse_count, successful_reuse_count, outcome_gain;
- contradiction_count, stale_count, compression_loss;
- token_cost, latency_cost, sensitivity;
- last_scored_at, policy_version, source_provenance.

### memory_outcomes

Suggested fields:

- task_id, memory_id, selected;
- answer_changed, verifier_passed, user_confirmed;
- error_prevented, contradiction_exposed, latency_ms;
- tokens_added, confidence_before, confidence_after;
- outcome_label and evaluator_version.

### model_modules

Suggested fields:

- module_id, module_type, architecture_id, base_model_id;
- route_key, task_tags, checksum, signature;
- dtype, quantization, size_bytes, vram_bytes;
- load_latency_ms, expected_gain, risk_level;
- status, owner, created_at, rollback_target.

Module types should initially be adapter, expert, early-exit policy, verifier, and tool policy. Weight shard should be added only after the catalog and integrity checks are proven.

### routing_outcomes

Log:

- task profile and budget;
- selected memories and modules;
- activated parameters and depth;
- retrieval/load latency;
- verifier result;
- user or benchmark outcome;
- whether expansion helped;
- whether pruning harmed quality.

## 7. Architecture flow

The proposed end-to-end flow is:

    Request
      -> CARD task classifier
      -> LOCI candidate retrieval
      -> value scoring and contradiction scan
      -> CARD evidence hydration
      -> LACC budget and module plan
      -> adapter/expert/depth/KV selection
      -> generation or tool execution
      -> verifier and provenance check
      -> optional bounded expansion
      -> response, abstention, or escalation
      -> LOCI outcome and value update

Storage layout can map to the user's drives:

- O: model artifacts, immutable base weights, adapters, expert shards, checksums, and runtime caches;
- P: active project files, research artifacts, databases, indexes, and operational logs;
- removable drive: verified backup mirror, including the project README and exported research artifacts.

The drive split is operational storage, not a substitute for module integrity. Each model artifact needs a manifest containing architecture, tensor names, dimensions, dtype, quantization, checksum, source, and compatibility range.

## 8. Implementation roadmap

### Phase 0: observability and contracts

- expose CARD retrieval and hydration boundaries;
- preserve current heat as one feature, not the final score;
- log candidate sets, selected items, costs, and outcomes;
- add task profiles and a budget object;
- add deterministic policy versions.

### Phase 1: finish the persistent substrate

- versioned facts with valid-from/valid-to;
- provenance and source references;
- entity links and bounded spreading activation;
- goals, sessions, turns, and task IDs;
- crystallized summaries with links to source evidence;
- soft pruning and retention policies;
- CARD hydration with token and evidence budgets.

### Phase 2: value optimization

- add memory_value and memory_outcomes;
- compute outcome gain from benchmark/user feedback;
- add contradiction and stale-evidence penalties;
- use diversity-aware selection;
- evaluate heat-only, similarity-only, and full value policies.

### Phase 3: focused state and attention

- add summary tiers;
- add KV-cache policies with recent-token and sink safeguards;
- add cache compression/offload where measurable;
- support partial rehydration rather than full-session replay.

### Phase 4: modular model capacity

- begin with immutable LoRA adapters and a catalog;
- add task-conditioned adapter selection;
- add trained early exit or depth routing;
- add sparse expert routing only with load-balance and fallback monitoring;
- add verifier module selection.

### Phase 5: validated weight paging

- pre-shard compatible tensors;
- store on O with checksums and manifests;
- maintain CPU/GPU cache with bounded prefetch;
- page only whitelisted modules;
- measure load latency and quality impact;
- fall back to the base model if a page is missing, invalid, or too slow.

## 9. Evaluation plan

Use a matrix that tests memory, capacity, and their interaction.

### Memory quality

- LongMemEval-style extraction;
- multi-session reasoning;
- temporal updates and corrections;
- contradiction detection;
- selective abstention;
- provenance coverage;
- stale-fact leakage;
- answer quality after active-context pruning.

### Capacity quality

- accuracy by task profile;
- activated parameter count;
- effective depth and node count;
- adapter/expert hit rate;
- module load latency;
- VRAM and disk bandwidth;
- energy where available;
- verifier catch rate;
- rollback rate.

### Joint efficiency

- quality per token;
- quality per second;
- quality per GB of VRAM;
- quality per activated parameter;
- retrieval plus load latency;
- context compression ratio;
- expansion success rate;
- percentage of tasks solved without expansion.

Required ablations:

1. similarity retrieval only;
2. heat plus similarity;
3. value ledger without dynamic capacity;
4. dynamic capacity without value-ledger memory;
5. full CARD plus LACC;
6. full system with weight paging.

Do not promote a policy because it reduces tokens alone. A reduction is a regression if it increases stale evidence, unsupported claims, verifier failures, or high-risk execution errors.

## 10. Safety and correctness boundaries

- Memory is evidence, not authority. The system must preserve source and confidence.
- A thought, summary, or model-generated claim must not become a durable fact without provenance and a promotion policy.
- Pruning from active context must not erase audit evidence.
- Every module and weight page must be checksummed and architecture-validated before activation.
- High-risk tasks require stronger evidence, independent verification, and possibly human approval.
- A route decision must be reversible and logged.
- Never let a model-generated route fetch arbitrary executable or tensor content from an untrusted path.
- Separate data-plane retrieval from control-plane policy.
- Treat user corrections as high-value updates but retain the previous version for audit.
- Any "infinite" claim must be qualified as bounded active context backed by effectively unbounded external storage.

## 11. Recommended first build

The highest-value first slice is:

1. Add a CARD context assembler API with task profile and token budget.
2. Add a memory candidate record containing provenance, heat, relevance, freshness, confidence, and cost.
3. Add memory_value and memory_outcomes tables.
4. Implement deterministic value-per-cost ranking with diversity and contradiction penalties.
5. Return an evidence packet with source IDs and a hydration report.
6. Add one expansion decision based on uncertainty and expected value.
7. Add benchmark fixtures for multi-session retrieval, stale updates, and multi-hop links.
8. Only after this is measured, add adapter selection from a checksummed catalog.

This produces a real testable system aligned with the user's statement: attention is focused, memory is persistent and retrievable, and computation expands only when the task justifies its cost.

## Sources

Primary research sources consulted:

1. RAG - https://arxiv.org/abs/2005.11401
2. RETRO - https://arxiv.org/abs/2112.04426
3. MemGPT - https://arxiv.org/abs/2310.08560
4. Infini-attention - https://arxiv.org/abs/2404.07143
5. StreamingLLM - https://arxiv.org/abs/2309.17453
6. Transformer-XL - https://arxiv.org/abs/1901.02860
7. Compressive Transformer - https://arxiv.org/abs/1911.05507
8. LongMemEval - https://arxiv.org/abs/2410.10813
9. HippoRAG - https://arxiv.org/abs/2405.14831
10. Switch Transformers - https://arxiv.org/abs/2101.03961
11. Mixture of a Million Experts / PEER - https://arxiv.org/abs/2407.04153
12. Mixture-of-Depths - https://arxiv.org/abs/2404.02258
13. LayerSkip - https://arxiv.org/abs/2404.16710
14. LoRA - https://arxiv.org/abs/2106.09685
15. ALoRA - https://arxiv.org/abs/2403.16187
16. FlexGen - https://arxiv.org/abs/2303.06865
17. H2O - https://arxiv.org/abs/2306.14048
18. SnapKV - https://arxiv.org/abs/2404.14469
19. CacheGen - https://arxiv.org/abs/2310.07240
20. Test-time compute scaling - https://arxiv.org/abs/2408.03314

## Limitations and verification evidence

This is a source-backed design synthesis, not a new benchmark or a claim that the current repository already implements the complete architecture. The cited papers report results under their own datasets, training procedures, hardware, and evaluation assumptions. Their gains should be reproduced on this project's tasks before adoption.

Local verification performed for this report:

- README.md, CLAUDE.md, agent_instructions.md, loci-engine/INDEX.md, docs/INDEX.md, the dated status notes, the LOCI design specification, schema.sql, heat.py, store.py, vectors.py, and package exports were inspected.
- The current implementation was compared against the design claims; the gap between the two-table core and the aspirational multi-stream design is explicitly called out above.
- No production code, model weights, or routing policy was modified.
