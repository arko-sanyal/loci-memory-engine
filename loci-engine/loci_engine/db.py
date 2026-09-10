import sqlite3
from importlib import resources


def open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    schema = resources.files("loci_engine").joinpath("schema.sql").read_text()
    conn.executescript(schema)
    conn.commit()
    return conn
