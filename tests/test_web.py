import os
import pytest
from unittest.mock import patch

from fastapi.testclient import TestClient

from theeye.db import get_db, run_migrations


@pytest.fixture
def client(tmp_path):
    db_path = str(tmp_path / "test.db")
    db = get_db(db_path)
    run_migrations(db)

    # Insert test data
    db.execute(
        "INSERT INTO sources (name, url, type) VALUES (?, ?, ?)",
        ("Test Source", "https://example.com", "rss"),
    )
    db.execute(
        """INSERT INTO articles (source_id, url, title, author, content_text)
           VALUES (?, ?, ?, ?, ?)""",
        (1, "https://example.com/post1", "First Post", "Alice",
         "Content of the first post."),
    )
    db.execute(
        """INSERT INTO articles (source_id, url, title, content_text)
           VALUES (?, ?, ?, ?)""",
        (1, "https://example.com/post2", "Second Post",
         "Content of the second post."),
    )
    db.execute(
        """INSERT INTO summaries (article_id, summary_title, summary_text)
           VALUES (?, ?, ?)""",
        (1, "Better Title for First Post",
         "This is a summary of the first post."),
    )
    db.commit()
    db.close()

    with patch.dict(os.environ, {"THEEYE_DB": db_path}):
        from theeye.web.app import app
        yield TestClient(app)


def test_feed_page(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Better Title for First Post" in resp.text
    assert "Second Post" in resp.text
    assert "Test Source" in resp.text


def test_feed_filter_unread(client):
    # Mark first article as read
    client.post("/article/1/read")
    resp = client.get("/?status=unread")
    assert resp.status_code == 200
    assert "Second Post" in resp.text
    assert "Better Title for First Post" not in resp.text


def test_feed_filter_source(client):
    resp = client.get("/?source=1")
    assert resp.status_code == 200
    assert "First Post" in resp.text or "Better Title" in resp.text


def test_article_detail(client):
    resp = client.get("/article/1")
    assert resp.status_code == 200
    assert "Better Title for First Post" in resp.text
    assert "summary of the first post" in resp.text
    assert "Content of the first post" in resp.text


def test_article_detail_auto_marks_read(client):
    # Visit article detail
    client.get("/article/2")
    # Now filter by read — should include article 2
    resp = client.get("/?status=read")
    assert "Second Post" in resp.text


def test_article_not_found(client):
    resp = client.get("/article/999")
    assert resp.status_code == 404


def test_mark_read_unread(client):
    client.post("/article/1/read")
    resp = client.get("/?status=read")
    assert "First Post" in resp.text or "Better Title" in resp.text

    client.post("/article/1/unread")
    resp = client.get("/?status=read")
    assert "Better Title for First Post" not in resp.text


def test_save_note(client):
    client.post("/article/1/note", data={"text": "My note here"})
    resp = client.get("/article/1")
    assert "My note here" in resp.text


def test_delete_note(client):
    client.post("/article/1/note", data={"text": "My note"})
    client.post("/article/1/note", data={"text": ""})
    resp = client.get("/article/1")
    assert "My note" not in resp.text


def test_note_indicator_in_feed(client):
    client.post("/article/1/note", data={"text": "A note"})
    resp = client.get("/")
    # The feed should show a note indicator for article 1
    assert 'has-note' in resp.text
