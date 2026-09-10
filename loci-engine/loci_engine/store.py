import time

from loci_engine.heat import apply_increment, decay, tier


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
        VALUES (?, ?, ?, 1.0, 1.0, 0, ?)
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
    source: str | None = None,
    now: float | None = None,
) -> int:
    now = time.time() if now is None else now
    parent = get_entity(conn, entity, now=now)
    if parent is None:
        raise KeyError(entity)
    cursor = conn.execute(
        "INSERT INTO qsymprev (entity, key, value, unit, ts, heat, confidence, source) "
        "VALUES (?, ?, ?, ?, ?, ?, 1.0, ?)",
        (entity, key, value, unit, now, parent["heat"], source),
    )
    conn.commit()
    return cursor.lastrowid


def get_facts(conn, entity: str, key: str | None = None) -> list[dict]:
    if key is None:
        rows = conn.execute(
            "SELECT id, entity, key, value, unit, ts, heat, confidence, source "
            "FROM qsymprev WHERE entity = ?",
            (entity,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, entity, key, value, unit, ts, heat, confidence, source "
            "FROM qsymprev WHERE entity = ? AND key = ?",
            (entity, key),
        ).fetchall()
    return [
        {
            "id": r[0],
            "entity": r[1],
            "key": r[2],
            "value": r[3],
            "unit": r[4],
            "ts": r[5],
            "heat": r[6],
            "confidence": r[7],
            "source": r[8],
        }
        for r in rows
    ]
