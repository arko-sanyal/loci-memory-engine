"""MCP service exposing the LOCI memory engine to any MCP-compatible agent.

Unlike the coordination bus (a multi-party, HMAC-authenticated message log), this is a
single local memory store for one agent's own use — no identity/authorization scheme is
needed here, only a database path.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    FastMCP = None  # type: ignore[assignment,misc]

from loci_engine import LociEngine

_engine: LociEngine | None = None


def _get_engine() -> LociEngine:
    global _engine
    if _engine is None:
        db_path = os.environ.get("LOCI_DB_PATH", ".loci/memory.sqlite3")
        if db_path != ":memory:":
            Path(db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        _engine = LociEngine(db_path)
    return _engine


mcp = FastMCP("loci-memory") if FastMCP is not None else None


def _register(fn):
    if mcp is not None:
        return mcp.tool()(fn)
    return fn


@_register
def loci_remember(entity: str, gist: str | None = None, expanded: str | None = None) -> dict[str, Any]:
    """Store or update an entity's gist/expanded detail. Does not touch its heat."""
    _get_engine().remember(entity, gist=gist, expanded=expanded)
    return {"entity": entity, "status": "stored"}


@_register
def loci_recall(entity: str, hop: int = 0) -> dict[str, Any] | None:
    """Recall an entity by exact name, incrementing its heat (direct access by default)."""
    return _get_engine().recall(entity, hop=hop)


@_register
def loci_add_fact(
    entity: str, key: str, value: str, unit: str | None = None, source: str | None = None
) -> dict[str, Any]:
    """Attach a versioned-in-name-only fact (key/value/unit) to an entity."""
    fact_id = _get_engine().add_fact(entity, key, value, unit=unit, source=source)
    return {"fact_id": fact_id, "entity": entity, "key": key}


@_register
def loci_get_facts(entity: str, key: str | None = None) -> list[dict[str, Any]]:
    """Return all recorded facts for an entity, optionally filtered by key."""
    return _get_engine().get_facts(entity, key=key)


@_register
def loci_add_chunk(
    chunk_id: str, embedding: list[float], text: str, metadata: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Add a text chunk with a precomputed embedding for later hybrid semantic search."""
    _get_engine().add_chunk(chunk_id, embedding, text, metadata=metadata)
    return {"chunk_id": chunk_id, "status": "stored"}


@_register
def loci_query(
    embedding: list[float], top_k: int = 5, query_text: str | None = None
) -> list[dict[str, Any]]:
    """Hybrid dense+lexical search over stored chunks. `embedding` must be precomputed
    by the caller (this engine does not itself call an embedding model)."""
    return _get_engine().query(embedding, top_k=top_k, query_text=query_text)


def main() -> None:
    if mcp is None:
        raise SystemExit("MCP SDK is not installed; install the loci-engine mcp extra first")
    _get_engine()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
