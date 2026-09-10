import pytest

from loci_engine.heat import HEAT_MAX, HEAT_MIN, apply_increment, decay, tier


def test_decay_applies_0_95_per_day():
    assert decay(0.5, days_elapsed=1) == pytest.approx(0.5 * 0.95)
    assert decay(0.5, days_elapsed=2) == pytest.approx(0.5 * 0.95 ** 2)


def test_decay_with_zero_elapsed_time_is_a_no_op():
    assert decay(0.5, days_elapsed=0) == pytest.approx(0.5)


def test_decay_never_reaches_exactly_zero():
    # 100 days of decay from a tiny heat is still a positive number, not 0 -
    # decay is multiplicative, so it can approach but never touch HEAT_MIN.
    result = decay(0.001, days_elapsed=100)
    assert result > HEAT_MIN
    assert result == pytest.approx(0.001 * 0.95 ** 100)


def test_direct_access_closes_half_the_gap_to_one():
    # k=0.5 for hop=0: heat_new = heat + (1 - heat) * 0.5
    assert apply_increment(0.333, hop=0) == pytest.approx(0.333 + (1 - 0.333) * 0.5)


def test_hop_increments_use_the_reinforcement_fractions():
    # k=0.25/0.125/0.0625 for hop=1/2/3, same gap-closing formula
    assert apply_increment(0.333, hop=1) == pytest.approx(0.333 + (1 - 0.333) * 0.25)
    assert apply_increment(0.333, hop=2) == pytest.approx(0.333 + (1 - 0.333) * 0.125)
    assert apply_increment(0.333, hop=3) == pytest.approx(0.333 + (1 - 0.333) * 0.0625)


def test_increment_never_reaches_exactly_one_no_matter_how_many_times_applied():
    heat = 0.333
    for _ in range(50):
        heat = apply_increment(heat, hop=0)
    assert heat < HEAT_MAX
    assert heat == pytest.approx(1.0, abs=1e-6)  # asymptotically close, never equal


def test_decay_clamps_to_heat_min_floor():
    # decay() must never return a value at or below 0 even given a
    # pathologically large days_elapsed - the max() floor is a safety net,
    # not something normal use should ever hit given multiplicative decay.
    assert decay(0.5, days_elapsed=1_000_000) >= HEAT_MIN


def test_tier_thresholds():
    assert tier(0.6) == "HOT"
    assert tier(0.5) == "MILD"    # boundary is exclusive per the spec (heat > 0.5)
    assert tier(0.2) == "MILD"
    assert tier(0.167) == "COLD"  # boundary is exclusive (heat > 0.167)
    assert tier(0.0) == "COLD"


def test_heat_max_is_one_not_three():
    assert HEAT_MAX == 1.0
