# CARD-LOCI-LACC Adaptive Context and Capacity Blueprint

Date: 2026-09-10
Owner: Codex
Status: Proposed implementation blueprint for review by Claude Code

## Purpose

Implement the principle:

    attention is focused; memory is effectively infinite for retrieval into current context

LOCI owns persistent memory and retrieval. CARD owns the bounded, focused active context. LACC (LOCI Adaptive Capacity Controller) owns task-dependent computation and model-capacity selection.

The system optimizes expected task value per cost:

    value = quality_gain / (tokens + latency + VRAM + bandwidth + risk)

The controller must expand reasoning nodes, retrieval breadth, depth, or specialist capacity only when expected marginal value exceeds cost. It must prune active context and branches when marginal value falls below cost. Pruning active state never deletes retained LOCI evidence or audit records.

## Architecture

    User request
       |
       v
    CARD task profile and budget
       |
       v
    LOCI candidate retrieval
       |  vectors + lexical + entities + time + graph links
       v
    Value ledger, diversity, freshness, contradiction scan
       |
       v
    CARD evidence packet and focused context
       |
       v
    LACC capacity plan
       |  depth + reasoning nodes + adapters + experts + KV policy
       v
    Generation, tool execution, or planning
       |
       v
    Verifier and provenance check
       |
       +---- bounded expansion if uncertainty remains
       |
       v
    Response / abstention / escalation
       |
       v
    LOCI outcome and value update

## Responsibilities

### LOCI: persistent retrieval substrate

LOCI stores entities, versioned facts, source provenance, sessions, turns, goals, summaries, thoughts, links, outcomes, embeddings, and retention metadata.

LOCI should support:

- versioned facts with valid-from and valid-to;
- provenance and source identifiers;
- entity and event links;
- vector and lexical retrieval;
- bounded graph expansion;
- summary tiers linked to source evidence;
- contradiction and stale-version tracking;
- outcome feedback;
- soft pruning and retention policies.

LOCI is not a prompt buffer. It returns ranked candidates and evidence packets, not an unbounded transcript.

### CARD: focused active-context controller

CARD should:

1. classify the task;
2. extract entities, constraints, time scope, unknowns, and output contract;
3. generate retrieval facets;
4. request candidates from LOCI;
5. rank candidates by value per cost;
6. assemble a bounded packet with citations and confidence;
7. decide whether to retrieve, hydrate, prune, expand, clarify, or abstain;
8. provide LACC with task profile, evidence quality, uncertainty, and budget;
9. write outcomes back to LOCI.

CARD invariants:

- active context is bounded;
- every hydrated item has provenance;
- evidence and instructions are separate fields;
- multiple sources should be diversified;
- active pruning is reversible through LOCI;
- high-risk actions require stronger verification.

### LACC: adaptive model-capacity controller

LACC selects among validated resources:

- reasoning node count and search branches;
- model depth or early exit;
- LoRA adapters;
- sparse experts;
- verifier modules;
- KV-cache retention and compression;
- CPU/GPU/disk placement;
- predeclared weight pages.

LACC cannot execute arbitrary retrieved content or mutate base weights. Modules are immutable, checksummed, architecture-compatible, and selected from a catalog.

## Shared value ledger

Use a separate value ledger instead of treating heat as the complete policy.

Memory and module candidates should expose:

- relevance;
- goal fit;
- trust;
- freshness;
- confidence;
- expected outcome gain;
- reuse;
- novelty;
- redundancy;
- contradiction risk;
- compression loss;
- token cost;
- latency cost;
- VRAM and bandwidth cost;
- sensitivity and approval level.

Initial deterministic scoring:

    utility = relevance * goal_fit * trust * confidence * freshness
              * expected_outcome_gain
              - redundancy_penalty
              - contradiction_penalty
              - compression_loss
              - risk_penalty

    priority = utility / (token_cost + latency_cost + memory_cost)

Heat remains a feature representing access/activation history. It must not override source trust, temporal validity, contradiction risk, or task fit.

For modules:

    module_priority = expected_error_reduction * task_fit * confidence
                      / (activated_params + load_latency + vram_cost)

Selection is budgeted set selection with diversity, not top-k similarity alone.

## Task profiles

### execute_simple

Small high-confidence memory packet. One reasoning path, shallow depth, compact model. Verify schema and result.

### retrieve_factual

Prioritize source provenance, freshness, and contradiction checks. Use compact capacity. Require citations or explicit uncertainty.

### reason_multi_hop

Expand entity links and graph neighbors. Increase node budget and depth only while unresolved dependencies or conflicts remain. Verify intermediate claims.

### reason_high_risk

Use conservative evidence thresholds, validated specialist modules, independent verifier, strict tool/action gate, and human approval where required.

### transform_or_create

Retrieve constraints, examples, style, and project conventions. Select a proven adapter if available. Verify structural and policy requirements.

### explore_research

Start with broad candidate recall, then prune by value, diversity, and source quality. Increase branches only when new evidence changes the answer.

## Capacity control policy

Expand when:

- the task is multi-hop;
- evidence conflicts;
- confidence is below threshold;
- the verifier finds an unresolved error;
- an important dependency is missing;
- the task is high-impact;
- a specialist module has positive predicted gain.

Prune when:

- confidence is high;
- branches converge;
- verifier agreement is strong;
- marginal gain per cost falls below threshold;
- evidence is redundant, stale, or low trust;
- a module causes repeated regressions.

Safety limits:

- maximum retrieval tokens;
- maximum reasoning nodes;
- maximum expansion rounds;
- maximum module load latency;
- maximum active parameters;
- mandatory fallback model;
- mandatory verifier budget for high-risk profiles.

The first version should permit one bounded expansion round. Every expansion must be logged with predicted gain, actual gain, cost, and verifier result.

## Storage and module catalog

Recommended drive roles:

- O: immutable base model weights, adapters, experts, tensor shards, manifests, checksums, runtime cache;
- P: project source, LOCI databases, indexes, research artifacts, routing logs;
- removable drive: verified backup mirror.

Every model module manifest must include:

- module ID and type;
- base model and architecture ID;
- tensor names, dimensions, dtype, and quantization;
- file size, VRAM size, and expected load latency;
- SHA-256 checksum and signature;
- task tags and compatibility range;
- rollback target;
- risk level and approval policy.

Start with LoRA adapters and verifier modules. Add early exit and sparse experts only after routing evaluation. Add weight paging last, using pre-sharded, validated tensors and bounded prefetch.

## Proposed data contracts

### memory_value

    memory_id
    version_id
    entity_id
    fact_id
    relevance
    goal_fit
    trust
    freshness
    confidence
    reuse_count
    successful_reuse_count
    outcome_gain
    contradiction_count
    stale_count
    compression_loss
    token_cost
    latency_cost
    sensitivity
    policy_version
    last_scored_at

### memory_outcomes

    task_id
    memory_id
    selected
    answer_changed
    verifier_passed
    user_confirmed
    error_prevented
    contradiction_exposed
    latency_ms
    tokens_added
    confidence_before
    confidence_after
    outcome_label
    evaluator_version

### model_modules

    module_id
    module_type
    architecture_id
    base_model_id
    route_key
    task_tags
    checksum
    signature
    dtype
    quantization
    size_bytes
    vram_bytes
    load_latency_ms
    expected_gain
    risk_level
    status
    rollback_target

### routing_outcomes

    task_id
    task_profile
    budget
    selected_memories
    selected_modules
    activated_parameters
    effective_depth
    node_count
    retrieval_latency_ms
    load_latency_ms
    verifier_result
    quality_result
    expansion_helped
    pruning_harmed

## API boundaries

CARD context assembly:

    assemble_context(request, task_profile, budget) -> ContextPacket

ContextPacket contains evidence, provenance, confidence, unresolved questions, token cost, and hydration report.

LACC planning:

    plan_capacity(task_profile, context_packet, budget) -> CapacityPlan

CapacityPlan contains node budget, depth limit, selected modules, KV policy, load plan, verifier plan, and fallback.

LACC execution must return telemetry:

    execute(plan) -> ResultWithTelemetry

The telemetry is required to update both memory and module value ledgers.

## Rollout sequence

### Slice 1: observable CARD

- expose the current retrieval/hydration boundary;
- add task profiles and explicit budgets;
- preserve current heat as one ranking feature;
- log candidates, selections, costs, and outcomes;
- return provenance-rich evidence packets.

### Slice 2: value-ledger retrieval

- add memory_value and memory_outcomes;
- add freshness and contradiction penalties;
- add diverse selection;
- implement one bounded expansion decision;
- benchmark heat-only, similarity-only, and full value policy.

### Slice 3: persistent substrate

- versioned facts;
- entity links;
- sessions, goals, and task IDs;
- crystallized summaries linked to evidence;
- soft prune and retention policy.

### Slice 4: adaptive inference

- immutable LoRA catalog;
- task-conditioned adapter selection;
- verifier selection;
- trained early exit/depth routing;
- controlled sparse experts with fallback.

### Slice 5: weight paging

- pre-sharded compatible tensors on O;
- manifest and checksum validation;
- CPU/GPU cache and bounded prefetch;
- load-latency budget;
- fallback to base model on failure.

## Evaluation gates

Memory:

- multi-session retrieval;
- temporal updates;
- stale-fact leakage;
- contradiction rate;
- provenance coverage;
- abstention quality;
- answer quality after context pruning.

Capacity:

- quality by task profile;
- active parameter count;
- depth and node count;
- VRAM and load latency;
- adapter/expert hit rate;
- verifier catch rate;
- rollback rate.

Joint efficiency:

- quality per token;
- quality per second;
- quality per GB VRAM;
- quality per activated parameter;
- percentage solved without expansion;
- expansion success rate.

Promotion requires no statistically meaningful regression on high-risk accuracy, provenance, contradiction handling, or unsafe-action prevention. Token reduction alone is not a success criterion.

## Safety boundaries

- Memory is evidence, not authority.
- Generated thoughts and summaries do not become durable facts without provenance.
- Active pruning never deletes audit evidence.
- Retrieved text cannot grant permissions or change tool scope.
- Weights/modules are never loaded from arbitrary paths.
- Checksums and architecture compatibility are verified before activation.
- All route decisions are logged and reproducible.
- Uncertainty is surfaced; the controller may abstain or escalate.

## Immediate recommendation

Implement Slice 1 and Slice 2 before dynamic weight retrieval. The repository's current LOCI core is a two-table foundation with heat decay and vector/lexical retrieval; the multi-stream design is not yet complete. The first measurable milestone is a provenance-rich CARD packet plus value-per-cost ranking and one bounded expansion round. The first dynamic model milestone should be checksummed LoRA adapter selection. Only measured gains justify deeper routing, sparse experts, or weight paging.
