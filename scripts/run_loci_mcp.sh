#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
: "${LOCI_DB_PATH:=.loci/memory.sqlite3}"
export LOCI_DB_PATH
exec .venv/bin/python -m loci_engine.mcp_server
