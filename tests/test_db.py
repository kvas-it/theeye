from theeye.db import get_db, run_migrations


def test_migrations_create_tables(db):
    tables = {
        row["name"]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    expected = {
        "schema_version", "sources", "articles",
        "summaries", "notes", "read_state",
    }
    assert expected.issubset(tables)


def test_schema_version_recorded(db):
    row = db.execute(
        "SELECT version, name FROM schema_version ORDER BY version"
    ).fetchone()
    assert row["version"] == 1
    assert row["name"] == "initial"


def test_migrations_idempotent(db, tmp_path):
    """Running migrations twice doesn't error or duplicate."""
    from pathlib import Path
    migrations_dir = Path(__file__).parent.parent / "migrations"
    run_migrations(db, migrations_dir)
    rows = db.execute("SELECT COUNT(*) AS c FROM schema_version").fetchone()
    assert rows["c"] == 1


def test_foreign_keys_enabled(db):
    fk = db.execute("PRAGMA foreign_keys").fetchone()
    assert fk[0] == 1


def test_insert_and_query_article(db):
    db.execute(
        "INSERT INTO sources (name, url, type) VALUES (?, ?, ?)",
        ("Test", "https://example.com", "rss"),
    )
    db.execute(
        "INSERT INTO articles (source_id, url, title) VALUES (?, ?, ?)",
        (1, "https://example.com/post1", "Post 1"),
    )
    db.commit()
    row = db.execute("SELECT * FROM articles WHERE id=1").fetchone()
    assert row["title"] == "Post 1"
    assert row["source_id"] == 1
