HEAT_MIN = 0.0
HEAT_MAX = 3.0
DECAY_RATE_PER_DAY = 0.95
HOP_INCREMENTS = {0: 1.0, 1: 0.5, 2: 0.25, 3: 0.125}


def decay(heat: float, days_elapsed: float) -> float:
    decayed = heat * (DECAY_RATE_PER_DAY ** days_elapsed)
    return max(HEAT_MIN, decayed)


def apply_increment(heat: float, hop: int) -> float:
    incremented = heat + HOP_INCREMENTS[hop]
    return min(HEAT_MAX, incremented)


def tier(heat: float) -> str:
    if heat > 1.5:
        return "HOT"
    if heat > 0.5:
        return "WARM"
    return "COLD"
