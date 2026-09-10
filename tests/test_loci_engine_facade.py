import pytest

from loci_engine import LociEngine


@pytest.fixture
def engine(tmp_path):
    return LociEngine(str(tmp_path / "loci.db"))


def test_remember_then_recall_returns_touched_entity(engine):
    engine.remember("battery_capacity", gist="how much charge it holds")

    result = engine.recall("battery_capacity")

    assert result["entity"] == "battery_capacity"
    assert result["gist"] == "how much charge it holds"
    assert result["heat"] == pytest.approx(0.6665)  # base 0.333, closes half the gap to 1.0


def test_recall_of_unknown_entity_returns_none(engine):
    assert engine.recall("nonexistent") is None


def test_recall_increments_heat_asymptotically_toward_one(engine):
    engine.remember("battery_capacity")

    first = engine.recall("battery_capacity")["heat"]
    second = engine.recall("battery_capacity")["heat"]
    third = engine.recall("battery_capacity")["heat"]

    # each recall closes half the remaining gap to 1.0, so heat keeps
    # increasing but can never reach or exceed 1.0, no matter how many times
    # this loop runs.
    assert first < second < third < 1.0


def test_add_fact_and_get_facts_via_facade(engine):
    engine.remember("server_config")

    engine.add_fact("server_config", "port", "8766", unit="tcp", source="measured")
    facts = engine.get_facts("server_config")

    assert len(facts) == 1
    assert facts[0]["value"] == "8766"


def test_add_chunk_then_query_finds_it_by_embedding(engine):
    embedding = [1.0, 0.0, 0.0] + [0.0] * 765
    engine.add_chunk("c1", embedding, "the sky is blue", metadata={"source": "notes.txt"})

    results = engine.query(embedding, top_k=3)

    assert any(r["id"] == "c1" for r in results)


def test_query_with_query_text_uses_hybrid_lexical_match(engine):
    embedding_far = [0.0, 1.0, 0.0] + [0.0] * 765
    engine.add_chunk("c2", embedding_far, "battery capacity is 4000mAh")

    unrelated_query_embedding = [0.0, 0.0, 1.0] + [0.0] * 765
    results = engine.query(unrelated_query_embedding, top_k=3, query_text="battery capacity")

    assert any(r["id"] == "c2" for r in results)
