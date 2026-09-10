# Project Documentation Index

This index is the starting point for the Codex RAG and multi-agent trading work.

## Start here

- [Project README](../README.md) - project purpose, setup, and commands.
- [Agent instructions](../agent_instructions.md) - operating rules, coordination, storage, and safety constraints.
- [Current status](STATUS-2026-09-10.md) - latest project state.

## Memory and RAG

- [RAG pipeline design](superpowers/specs/2026-09-09-rag-pipeline-design.md)
- [LOCI memory engine design](superpowers/specs/2026-09-10-loci-memory-engine-design.md)
- [LOCI memory core implementation plan](superpowers/plans/2026-09-10-loci-engine-memory-core.md)

## Agent coordination

- [Coordination documentation](coordination/)
- [Coordination plans](superpowers/plans/)

## Trading system

- [Trading-system user guide](trading/USER_GUIDE.md)
- [Trading-system role and architecture index](trading/README.md)

## Operations

- [RAG unification status](STATUS-2026-09-10-rag-unification.md)
- `scripts/` - operational scripts, including coordination and project-backup helpers.

## Safety boundary

The trading blueprint is an architecture and feasibility document. It does not authorize live trading. Any move from research or shadow mode toward live execution requires explicit configuration, independent risk review, paper-trading evidence, and an operator-controlled activation gate.
