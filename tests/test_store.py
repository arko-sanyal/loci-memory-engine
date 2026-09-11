import pytest

from loci_engine.db import open_db
from loci_engine.provenance import UserStated
from loci_engine.store import (
    add_fact,
    get_entity,
    get_fact_history,
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
    assert entity["heat"] == pytest.approx(0.333)


def test_get_entity_surfaces_heat_tier(conn):
    remember_entity(conn, "battery_capacity", now=1000.0)

    entity = get_entity(conn, "battery_capacity", now=1000.0)

    # freshly-remembered entity sits at base heat 0.333, which is MILD
    # (HOT if heat > 0.5, MILD if heat > 0.167, else COLD).
    assert entity["tier"] == "MILD"


def test_remember_entity_is_idempotent_and_does_not_reset_heat(conn):
    remember_entity(conn, "battery_capacity", now=1000.0)
    touch_entity(conn, "battery_capacity", hop=0, now=1000.0)  # heat -> 0.6665

    remember_entity(conn, "battery_capacity", now=2000.0)  # re-mention, no explicit touch

    entity = get_entity(conn, "battery_capacity", now=2000.0)
    # remember_entity must not reset last_used, so the ~1000s gap since the
    # touch still decays normally; only touch_entity should ever reset the
    # decay clock. The real decay over 1000 seconds from 0.6665 is tiny
    # (~0.6656), so abs=2e-3 comfortably covers it while still catching
    # gross regressions (e.g. heat reset to 0.333, or jumping to 1.0).
    assert entity["heat"] == pytest.approx(0.6665, abs=2e-3)


def test_touch_entity_applies_decay_then_increment(conn):
    remember_entity(conn, "battery_capacity", now=0.0)

    one_day_later = 86400.0
    new_heat = touch_entity(conn, "battery_capacity", hop=0, now=one_day_later)

    # decay(0.333, 1 day) = 0.31635, then +direct-access gap-closing (k=0.5)
    # = 0.31635 + (1 - 0.31635) * 0.5 = 0.658175
    assert new_heat == pytest.approx(0.658175)


def test_touch_entity_raises_for_unknown_entity(conn):
    with pytest.raises(KeyError):
        touch_entity(conn, "does_not_exist", now=1000.0)


def test_get_entity_returns_none_for_unknown_entity(conn):
    assert get_entity(conn, "does_not_exist", now=1000.0) is None


def test_get_entity_applies_decay_without_mutating_storage(conn):
    remember_entity(conn, "battery_capacity", now=0.0)

    peeked = get_entity(conn, "battery_capacity", now=86400.0)
    assert peeked["heat"] == pytest.approx(0.31635)

    raw_row = conn.execute(
        "SELECT heat FROM isymprev WHERE entity = 'battery_capacity'"
    ).fetchone()
    assert raw_row[0] == pytest.approx(0.333)


def test_add_fact_requires_existing_entity(conn):
    with pytest.raises(KeyError):
        add_fact(conn, "does_not_exist", "port", "8766", now=1000.0)


def test_add_fact_and_get_facts_roundtrip(conn):
    remember_entity(conn, "server_config", now=1000.0)

    result = add_fact(
        conn, "server_config", "port", "8766", unit="tcp", source="measured", now=1000.0
    )

    facts = get_facts(conn, "server_config")
    assert len(facts) == 1
    assert facts[0]["id"] == result["fact_id"]
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


def test_add_fact_first_write_is_always_accepted(conn):
    remember_entity(conn, "server_config", now=1000.0)

    result = add_fact(conn, "server_config", "port", "8766", now=1000.0)

    assert result["accepted"] is True
    assert result["fact_id"] is not None


def test_add_fact_returns_current_version_only_by_default(conn):
    remember_entity(conn, "user_profile", now=1000.0)
    add_fact(conn, "user_profile", "address", "Dhaka", source=UserStated("Dhaka"), now=1000.0)

    facts = get_facts(conn, "user_profile", key="address")

    assert len(facts) == 1
    assert facts[0]["value"] == "Dhaka"
    assert facts[0]["valid_until"] is None


def test_higher_trust_challenger_overrides_lower_trust_incumbent(conn):
    remember_entity(conn, "user_profile", now=1000.0)
    # model_inferred incumbent (trust 0.7), heat at base 0.333 after remember_entity
    add_fact(conn, "user_profile", "address", "Old City", source="model_inferred", now=1000.0)

    # user_stated challenger (trust 1.0 >= 0.7) - easier gate (x0.8):
    # fires if new_confidence > incumbent_heat * 0.8 = 0.333 * 0.8 = 0.2664.
    # add_fact's default confidence is 1.0, well above that.
    result = add_fact(
        conn, "user_profile", "address", "Dhaka",
        source=UserStated("Dhaka"), now=2000.0,
    )

    assert result["accepted"] is True
    current = get_facts(conn, "user_profile", key="address")
    assert len(current) == 1
    assert current[0]["value"] == "Dhaka"

    history = get_fact_history(conn, "user_profile", "address")
    assert len(history) == 2
    assert history[0]["value"] == "Old City"
    assert history[0]["valid_until"] is not None
    assert history[1]["value"] == "Dhaka"
    assert history[1]["supersedes"] == "Old City"


def test_lower_trust_challenger_is_rejected_against_a_confident_incumbent(conn):
    remember_entity(conn, "user_profile", now=1000.0)
    # user_stated incumbent (trust 1.0). A fact's own heat is set once from
    # its parent entity's heat at write time (0.333, the base heat) and is
    # NOT re-synced by later touch_entity calls on the parent - a fact's
    # confidence reflects its own history, not incidental entity-level
    # activity on an unrelated key - so the gate math below uses 0.333.
    add_fact(conn, "user_profile", "home_city", "Dhaka", source=UserStated("Dhaka"), now=1000.0)

    # system_derived challenger (trust 0.5 < 1.0) - harder gate (x1.2):
    # fires if new_confidence > incumbent_heat * 1.2 = 0.333 * 1.2 = 0.3996.
    # 0.3 is comfortably below that, so this exercises the rejection path.
    result = add_fact(
        conn, "user_profile", "home_city", "Somewhere else",
        source="system_derived", confidence=0.3, now=2000.0,
    )

    assert result["accepted"] is False
    assert result["fact_id"] is None
    current = get_facts(conn, "user_profile", key="home_city")
    assert current[0]["value"] == "Dhaka"  # untouched


def test_get_fact_history_orders_by_valid_from(conn):
    remember_entity(conn, "e", now=1000.0)
    add_fact(conn, "e", "k", "v1", source=UserStated("v1"), now=1000.0)
    add_fact(conn, "e", "k", "v2", source=UserStated("v2"), now=2000.0)
    add_fact(conn, "e", "k", "v3", source=UserStated("v3"), now=3000.0)

    history = get_fact_history(conn, "e", "k")

    assert [h["value"] for h in history] == ["v1", "v2", "v3"]
    assert history[-1]["valid_until"] is None
