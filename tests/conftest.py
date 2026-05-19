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


@pytest.fixture(autouse=True)
def _reset_crawler_throttle(monkeypatch):
    """Skip throttle sleeps and clear per-host state across tests."""
    from theeye.crawler import crawl
    crawl._last_request_time.clear()
    monkeypatch.setattr(crawl.time, "sleep", lambda _s: None)
