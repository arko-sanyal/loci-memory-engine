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
    assert result["heat"] == pytest.approx(2.0)  # base 1.0 + direct-access +1.0


def test_recall_of_unknown_entity_returns_none(engine):
    assert engine.recall("nonexistent") is None


def test_recall_increments_heat_on_repeated_access(engine):
    engine.remember("battery_capacity")

    engine.recall("battery_capacity")
    second = engine.recall("battery_capacity")

    assert second["heat"] == pytest.approx(3.0)  # clamped at HEAT_MAX

    # A third recall would push an *unclamped* heat to 1.0+1.0+1.0+1.0 = 4.0,
    # which is indistinguishable from the correctly-clamped 3.0 after only two
    # recalls above. Asserting here too makes this test actually discriminate
    # a missing clamp.
    third = engine.recall("battery_capacity")
    assert third["heat"] == pytest.approx(3.0)  # still clamped at HEAT_MAX


def test_add_fact_and_get_facts_via_facade(engine):
    engine.remember("server_config")

    engine.add_fact("server_config", "port", "8766", unit="tcp", source="measured")
    facts = engine.get_facts("server_config")

    assert len(facts) == 1
    assert facts[0]["value"] == "8766"
