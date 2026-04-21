import pytest
from theeye.db import get_db, run_migrations


@pytest.fixture
def db(tmp_path):
    """Fresh SQLite database with all migrations applied."""
    db_path = str(tmp_path / "test.db")
    conn = get_db(db_path)
    run_migrations(conn)
    yield conn
    conn.close()
