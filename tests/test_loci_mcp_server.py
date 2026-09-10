import pytest

from loci_engine import LociEngine, mcp_server as loci_mcp


@pytest.fixture
def engine(tmp_path, monkeypatch):
    eng = LociEngine(str(tmp_path / "loci.db"))
    monkeypatch.setattr(loci_mcp, "_engine", eng)
    yield eng
    eng.close()


def test_remember_then_recall_via_mcp_tools(engine):
    stored = loci_mcp.loci_remember("battery_capacity", gist="how much charge it holds")
    assert stored["status"] == "stored"

    recalled = loci_mcp.loci_recall("battery_capacity")
    assert recalled["entity"] == "battery_capacity"
    assert recalled["gist"] == "how much charge it holds"


def test_recall_of_unknown_entity_returns_none_via_mcp(engine):
    assert loci_mcp.loci_recall("nonexistent") is None


def test_add_fact_and_get_facts_via_mcp_tools(engine):
    loci_mcp.loci_remember("server_config")

    loci_mcp.loci_add_fact("server_config", "port", "8766", unit="tcp", source="measured")
    facts = loci_mcp.loci_get_facts("server_config")

    assert len(facts) == 1
    assert facts[0]["value"] == "8766"


def test_add_chunk_then_query_via_mcp_tools(engine):
    embedding = [1.0, 0.0, 0.0] + [0.0] * 765
    stored = loci_mcp.loci_add_chunk("c1", embedding, "the sky is blue")
    assert stored["status"] == "stored"

    results = loci_mcp.loci_query(embedding, top_k=3)
    assert any(r["id"] == "c1" for r in results)


def test_mcp_tool_discovery():
    import asyncio

    assert loci_mcp.mcp is not None
    tools = asyncio.run(loci_mcp.mcp.list_tools())
    names = {tool.name for tool in tools}
    assert {
        "loci_remember",
        "loci_recall",
        "loci_add_fact",
        "loci_get_facts",
        "loci_add_chunk",
        "loci_query",
    }.issubset(names)
