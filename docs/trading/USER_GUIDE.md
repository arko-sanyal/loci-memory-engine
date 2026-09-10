# Trading System User Guide

## Purpose

This guide explains what each proposed role does, what it may access, and how a signal moves through the system. The design is meant to keep prediction separate from permission to place orders.

## Roles

| Role | Purpose | Allowed authority |
| --- | --- | --- |
| **SPOT** | Collects market data, order-book updates, funding rates, and other approved inputs; normalizes them into a common format. | Read-only; may publish market-data events. |
| **HYDRA** | Produces multi-horizon forecasts, quantiles, confidence, regime classification, and drift indicators. | Read-only inference; cannot propose or execute an order. |
| **FORGE** | Converts forecasts and strategy rules into a structured trade proposal with entry, invalidation, target, size, and expiry. | Proposal-only; cannot access exchange keys. |
| **AURA** | Shadow-boxes proposals against live order-book data, estimating queue position, latency, fees, slippage, and counterfactual results. | Simulation-only; cannot use live capital. |
| **ARC** | Applies deterministic portfolio and trade-risk rules, including drawdown, leverage, VaR/CVaR, liquidity, and slippage limits. | Gatekeeper and veto; cannot invent a proposal or bypass policy. |
| **KERNEL** | Receives only approved verdicts and routes orders to an exchange using restricted credentials and the required execution policy. | The only live-order authority; credentials stay isolated here. |
| **ARGUS** | Monitors health, audit events, signatures, policy violations, prompt/data anomalies, and emergency conditions. | Supervisory override; may quarantine or stop execution. |

## Normal event flow

```text
SPOT market data
        |
        v
HYDRA forecast --> FORGE proposal
                          |
                          +--> AURA shadow report
                          |          |
                          +----------v
                               ARC risk verdict
                                      |
                                      v
                              KERNEL live route
                                      |
                                      v
                              Exchange / audit trail

ARGUS observes every stage and can trigger the emergency stop.
```

## Message rules

Every event should have a unique identifier, source identity, event time, schema version, correlation identifier, and integrity protection. Consumers must validate schemas, reject unknown or malformed authority fields, enforce replay windows, and deduplicate by event ID.

Use separate subjects/streams for market data, forecasts, proposals, shadow fills, risk verdicts, execution reports, and security telemetry. Keep market-data retention bounded; retain proposals, verdicts, orders, and audit evidence durably.

The existing coordination bus uses authenticated HMAC envelopes and SQLite-backed persistence for agent coordination. It can coordinate work between Codex and Claude Code, but it must not be treated as a substitute for a trading event broker without additional throughput, ordering, and recovery testing.

## Operating modes

1. **Research** - historical data and model development; no exchange credentials.
2. **Shadow** - live market data and simulated fills; no live orders.
3. **Paper** - exchange sandbox/testnet only; verify order lifecycle and reconciliation.
4. **Canary** - explicitly enabled, tightly capped live capital with manual approval and a short observation window.
5. **Live** - only after independent review, passing gates, tested recovery, and an operator-controlled activation.

Default mode should be Research or Shadow. A language model must never directly receive unrestricted exchange API keys.

## Minimum safety gates

- API keys are isolated in KERNEL, withdrawal-disabled, IP-restricted, and least-privilege.
- ARC rejects trades that violate configured risk, leverage, drawdown, liquidity, or slippage policies.
- Execution requires a valid, fresh, signed ARC verdict bound to the exact proposal and approved quantity.
- Duplicate, stale, unsigned, replayed, or out-of-order authority messages are rejected.
- Kill-switch commands use an authenticated durable control path, acknowledgements, and a fail-closed local fallback. Redis Pub/Sub alone is not sufficient for emergency safety.
- Heartbeats, order acknowledgements, balances, fills, and cancellations are reconciled and audited.
- All policy thresholds are configuration subject to review; blueprint example values are not automatically approved limits.

## Known feasibility limits

The blueprint is appropriate for multi-minute and swing horizons, not sub-millisecond high-frequency trading. The stated inter-agent latency must be benchmarked in the actual deployment. "Exactly once" should be implemented as at-least-once delivery plus durable consumer-side idempotency, because a broker alone cannot guarantee end-to-end exactly-once business effects.

## Safe implementation sequence

1. Define versioned schemas and policy configuration.
2. Build SPOT, HYDRA, and FORGE in research mode.
3. Add AURA and compare shadow results with deterministic replay tests.
4. Add ARC with property tests, failure injection, and audit trails.
5. Implement KERNEL against a sandbox/testnet only.
6. Exercise ARGUS, recovery, replay, kill-switch, and credential-isolation tests.
7. Review paper-trading evidence before any canary activation.

No step above grants live trading authority by itself.
