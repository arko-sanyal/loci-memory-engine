CREATE TABLE IF NOT EXISTS isymprev (
    entity TEXT PRIMARY KEY,
    gist TEXT,
    heat REAL DEFAULT 1.0,
    confidence REAL DEFAULT 1.0,
    uses INTEGER DEFAULT 0,
    last_used REAL,
    expanded TEXT
);

CREATE TABLE IF NOT EXISTS qsymprev (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    unit TEXT,
    ts REAL,
    heat REAL DEFAULT 0.333,
    confidence REAL DEFAULT 1.0,
    source TEXT,
    source_trust REAL DEFAULT 0.5,
    supersedes TEXT,
    valid_from REAL,
    valid_until REAL
);

CREATE INDEX IF NOT EXISTS idx_qsymprev_entity ON qsymprev(entity);
CREATE INDEX IF NOT EXISTS idx_qsymprev_key ON qsymprev(key);
