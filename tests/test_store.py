import pytest

from loci_engine.db import open_db
from loci_engine.store import (
    add_fact,
    get_entity,
    get_facts,
    remember_entity,
    touch_entity,
)


@pytest.fixture
def conn(tmp_path):
    return open_db(str(tmp_path / "loci.db"))


def test_remember_entity_creates_row_with_base_heat(conn):
    remember_entity(conn, "battery_capacity", gist="how much charge it holds", now=1000.0)

    entity = get_entity(conn, "battery_capacity", now=1000.0)

    assert entity["entity"] == "battery_capacity"
    assert entity["gist"] == "how much charge it holds"
    assert entity["heat"] == pytest.approx(1.0)


def test_remember_entity_is_idempotent_and_does_not_reset_heat(conn):
    remember_entity(conn, "battery_capacity", now=1000.0)
    touch_entity(conn, "battery_capacity", hop=0, now=1000.0)  # heat -> 2.0

    remember_entity(conn, "battery_capacity", now=2000.0)  # re-mention, no explicit touch

    entity = get_entity(conn, "battery_capacity", now=2000.0)
    assert entity["heat"] == pytest.approx(2.0)


def test_touch_entity_applies_decay_then_increment(conn):
    remember_entity(conn, "battery_capacity", now=0.0)

    one_day_later = 86400.0
    new_heat = touch_entity(conn, "battery_capacity", hop=0, now=one_day_later)

    # decay(1.0, 1 day) = 0.95, then +1.0 direct-access increment = 1.95
    assert new_heat == pytest.approx(1.95)


def test_touch_entity_raises_for_unknown_entity(conn):
    with pytest.raises(KeyError):
        touch_entity(conn, "does_not_exist", now=1000.0)


def test_get_entity_returns_none_for_unknown_entity(conn):
    assert get_entity(conn, "does_not_exist", now=1000.0) is None


def test_get_entity_applies_decay_without_mutating_storage(conn):
    remember_entity(conn, "battery_capacity", now=0.0)

    peeked = get_entity(conn, "battery_capacity", now=86400.0)
    assert peeked["heat"] == pytest.approx(0.95)

    raw_row = conn.execute(
        "SELECT heat FROM isymprev WHERE entity = 'battery_capacity'"
    ).fetchone()
    assert raw_row[0] == pytest.approx(1.0)


def test_add_fact_requires_existing_entity(conn):
    with pytest.raises(KeyError):
        add_fact(conn, "does_not_exist", "port", "8766", now=1000.0)


def test_add_fact_and_get_facts_roundtrip(conn):
    remember_entity(conn, "server_config", now=1000.0)

    fact_id = add_fact(
        conn, "server_config", "port", "8766", unit="tcp", source="measured", now=1000.0
    )

    facts = get_facts(conn, "server_config")
    assert len(facts) == 1
    assert facts[0]["id"] == fact_id
    assert facts[0]["key"] == "port"
    assert facts[0]["value"] == "8766"
    assert facts[0]["unit"] == "tcp"
    assert facts[0]["source"] == "measured"


def test_get_facts_filters_by_key(conn):
    remember_entity(conn, "server_config", now=1000.0)
    add_fact(conn, "server_config", "port", "8766", now=1000.0)
    add_fact(conn, "server_config", "region", "us-east", now=1000.0)

    facts = get_facts(conn, "server_config", key="port")

    assert len(facts) == 1
    assert facts[0]["key"] == "port"
