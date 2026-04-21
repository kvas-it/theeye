import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


def get_db(path: str = "theeye.db") -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    return db


def run_migrations(db: sqlite3.Connection, migrations_dir: Path | None = None):
    if migrations_dir is None:
        migrations_dir = MIGRATIONS_DIR

    db.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    row = db.execute(
        "SELECT COALESCE(MAX(version), 0) AS v FROM schema_version"
    ).fetchone()
    current = row["v"]

    migration_files = sorted(migrations_dir.glob("*.sql"))
    for mf in migration_files:
        # Parse version from filename like "001_initial.sql"
        parts = mf.stem.split("_", 1)
        version = int(parts[0])
        name = parts[1] if len(parts) > 1 else mf.stem

        if version <= current:
            continue

        sql = mf.read_text()
        db.executescript(sql)
        db.execute(
            "INSERT INTO schema_version (version, name) VALUES (?, ?)",
            (version, name),
        )
        db.commit()
