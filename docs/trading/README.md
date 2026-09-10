# Autonomous Multi-Agent Trading System

This folder documents the V2 blueprint retrieved from Google Drive and its relationship to the existing project.

## Documents

- [User guide](USER_GUIDE.md) - roles, permissions, event flow, operating modes, and safety checks.

## Blueprint source

[Autonomous Multi-Agent AI Trading System - Architecture Blueprint & Feasibility V2](https://docs.google.com/document/d/1QdOXCJNrkRnpzUdHI9LG4pE2u6gKWycYLbCJupyJlu8/edit)

The source blueprint proposes an event-driven architecture for multi-minute and swing-style strategies. It is not a production-readiness certification.

## Relationship to this repository

The existing SQLite/HMAC coordination bus is intended for secure agent task coordination and control-plane messages. It is not the high-frequency market-data bus described by the blueprint. A future trading data plane should use typed schemas and a broker such as NATS JetStream or Redis Streams, selected after latency and durability benchmarks.
