from loci_engine.db import open_db


def test_open_db_creates_isymprev_and_qsymprev_tables(tmp_path):
    conn = open_db(str(tmp_path / "loci.db"))

    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }

    assert "isymprev" in tables
    assert "qsymprev" in tables


def test_open_db_is_idempotent(tmp_path):
    db_path = str(tmp_path / "loci.db")

    open_db(db_path).close()
    conn = open_db(db_path)  # must not raise "table already exists"

    conn.execute(
        "INSERT INTO isymprev (entity, heat, confidence, uses, last_used) "
        "VALUES ('e1', 1.0, 1.0, 0, 0.0)"
    )
    conn.commit()
    row = conn.execute("SELECT entity FROM isymprev WHERE entity = 'e1'").fetchone()

    assert row == ("e1",)
