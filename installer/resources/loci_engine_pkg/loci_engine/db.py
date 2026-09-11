import sqlite3
from importlib import resources


def open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    try:
        # WAL lets readers (e.g. a query from the compact lane) proceed without blocking
        # on a concurrent writer (e.g. a fact update from the expand lane) — needed once
        # both lanes touch the same store, not just for a single always-serial caller.
        conn.execute("PRAGMA journal_mode=WAL")
        schema = resources.files("loci_engine").joinpath("schema.sql").read_text()
        conn.executescript(schema)
        conn.commit()
    except Exception:
        conn.close()
        raise
    return conn
