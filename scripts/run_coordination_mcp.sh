#!/usr/bin/env bash
set -euo pipefail
cd /04_Project-Codex-RAG
set -a
. .loci/claude-code.env
set +a
exec .venv/bin/python -m rag.coordination_mcp
