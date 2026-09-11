import time

from loci_engine.heat import apply_increment, decay, tier
from loci_engine.provenance import resolve_trust

GATE_LOWER = 0.8
GATE_HIGHER = 1.2


def _decayed_heat(row_heat: float, last_used: float, now: float) -> float:
    days_elapsed = max(0.0, (now - last_used) / 86400.0)
    return decay(row_heat, days_elapsed)


def remember_entity(
    conn,
    entity: str,
    gist: str | None = None,
    expanded: str | None = None,
    now: float | None = None,
) -> None:
    now = time.time() if now is None else now
    conn.execute(
        """
        INSERT INTO isymprev (entity, gist, expanded, heat, confidence, uses, last_used)
        VALUES (?, ?, ?, 0.333, 1.0, 0, ?)
        ON CONFLICT(entity) DO UPDATE SET
            gist = COALESCE(excluded.gist, isymprev.gist),
            expanded = COALESCE(excluded.expanded, isymprev.expanded)
        """,
        (entity, gist, expanded, now),
    )
    conn.commit()


def get_entity(conn, entity: str, now: float | None = None) -> dict | None:
    now = time.time() if now is None else now
    row = conn.execute(
        "SELECT entity, gist, heat, confidence, uses, last_used, expanded "
        "FROM isymprev WHERE entity = ?",
        (entity,),
    ).fetchone()
    if row is None:
        return None
    entity_, gist, heat, confidence, uses, last_used, expanded = row
    decayed_heat = _decayed_heat(heat, last_used, now)
    return {
        "entity": entity_,
        "gist": gist,
        "heat": decayed_heat,
        "tier": tier(decayed_heat),
        "confidence": confidence,
        "uses": uses,
        "last_used": last_used,
        "expanded": expanded,
    }


def touch_entity(conn, entity: str, hop: int = 0, now: float | None = None) -> float:
    now = time.time() if now is None else now
    row = conn.execute(
        "SELECT heat, last_used FROM isymprev WHERE entity = ?", (entity,)
    ).fetchone()
    if row is None:
        raise KeyError(entity)
    heat, last_used = row
    decayed = _decayed_heat(heat, last_used, now)
    new_heat = apply_increment(decayed, hop)
    conn.execute(
        "UPDATE isymprev SET heat = ?, uses = uses + 1, last_used = ? WHERE entity = ?",
        (new_heat, now, entity),
    )
    conn.commit()
    return new_heat


def add_fact(
    conn,
    entity: str,
    key: str,
    value: str,
    unit: str | None = None,
    source: "object | None" = None,
    confidence: float = 1.0,
    now: float | None = None,
) -> dict:
    now = time.time() if now is None else now
    parent = get_entity(conn, entity, now=now)
    if parent is None:
        raise KeyError(entity)

    challenger_trust = resolve_trust(source)
    source_label = source.value if hasattr(source, "value") else source

    incumbent = conn.execute(
        "SELECT id, value, heat, source_trust FROM qsymprev "
        "WHERE entity = ? AND key = ? AND valid_until IS NULL",
        (entity, key),
    ).fetchone()

    if incumbent is None:
        cursor = conn.execute(
            "INSERT INTO qsymprev "
            "(entity, key, value, unit, ts, heat, confidence, source, source_trust, "
            " supersedes, valid_from, valid_until) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL)",
            (entity, key, value, unit, now, parent["heat"], confidence,
             source_label, challenger_trust, now),
        )
        conn.commit()
        return {"accepted": True, "fact_id": cursor.lastrowid, "reason": None}

    incumbent_id, incumbent_value, incumbent_heat, incumbent_trust = incumbent
    multiplier = GATE_LOWER if challenger_trust >= incumbent_trust else GATE_HIGHER
    fires = confidence > incumbent_heat * multiplier
    if not fires:
        return {
            "accepted": False, "fact_id": None,
            "reason": (
                f"confidence {confidence} did not clear the gate "
                f"({incumbent_heat} * {multiplier} = {incumbent_heat * multiplier})"
            ),
        }

    conn.execute(
        "UPDATE qsymprev SET valid_until = ? WHERE id = ?", (now, incumbent_id)
    )
    cursor = conn.execute(
        "INSERT INTO qsymprev "
        "(entity, key, value, unit, ts, heat, confidence, source, source_trust, "
        " supersedes, valid_from, valid_until) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
        (entity, key, value, unit, now, parent["heat"], confidence,
         source_label, challenger_trust, incumbent_value, now),
    )
    conn.commit()
    return {"accepted": True, "fact_id": cursor.lastrowid, "reason": None}


def get_facts(conn, entity: str, key: str | None = None) -> list[dict]:
    return _select_facts(conn, entity, key, current_only=True)


def get_fact_history(conn, entity: str, key: str) -> list[dict]:
    return _select_facts(conn, entity, key, current_only=False)


def _select_facts(conn, entity: str, key: str | None, current_only: bool) -> list[dict]:
    query = (
        "SELECT id, entity, key, value, unit, ts, heat, confidence, source, "
        "source_trust, supersedes, valid_from, valid_until FROM qsymprev "
        "WHERE entity = ?"
    )
    params: list = [entity]
    if key is not None:
        query += " AND key = ?"
        params.append(key)
    if current_only:
        query += " AND valid_until IS NULL"
    query += " ORDER BY valid_from"
    rows = conn.execute(query, params).fetchall()
    return [
        {
            "id": r[0], "entity": r[1], "key": r[2], "value": r[3], "unit": r[4],
            "ts": r[5], "heat": r[6], "confidence": r[7], "source": r[8],
            "source_trust": r[9], "supersedes": r[10], "valid_from": r[11],
            "valid_until": r[12],
        }
        for r in rows
    ]
