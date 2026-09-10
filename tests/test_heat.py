import pytest

from loci_engine.heat import HEAT_MAX, HEAT_MIN, apply_increment, decay, tier


def test_decay_applies_0_95_per_day():
    assert decay(1.0, days_elapsed=1) == pytest.approx(0.95)
    assert decay(1.0, days_elapsed=2) == pytest.approx(0.95 ** 2)


def test_decay_with_zero_elapsed_time_is_a_no_op():
    assert decay(2.0, days_elapsed=0) == pytest.approx(2.0)


def test_direct_access_increments_by_one():
    assert apply_increment(1.0, hop=0) == pytest.approx(2.0)


def test_hop_increments_match_paper_09_appendix_b():
    assert apply_increment(1.0, hop=1) == pytest.approx(1.5)
    assert apply_increment(1.0, hop=2) == pytest.approx(1.25)
    assert apply_increment(1.0, hop=3) == pytest.approx(1.125)


def test_increment_clamps_to_heat_max():
    assert apply_increment(2.9, hop=0) == pytest.approx(HEAT_MAX)


def test_decay_clamps_to_heat_min():
    assert decay(0.001, days_elapsed=100) >= HEAT_MIN


def test_tier_thresholds():
    assert tier(1.6) == "HOT"
    assert tier(1.5) == "WARM"  # boundary is exclusive per paper 09 (heat > 1.5)
    assert tier(0.6) == "WARM"
    assert tier(0.5) == "COLD"  # boundary is exclusive (heat > 0.5)
    assert tier(0.0) == "COLD"
