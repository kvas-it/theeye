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


def test_add_tag(client):
    client.post("/article/1/tag", data={"tag_name": "tech"})
    resp = client.get("/article/1")
    assert "tech" in resp.text


def test_add_tag_creates_new(client):
    client.post("/article/1/tag", data={"tag_name": "science"})
    client.post("/article/2/tag", data={"tag_name": "science"})
    # Both articles should have the same tag (not duplicated)
    resp = client.get("/article/2")
    assert "science" in resp.text


def test_add_tag_normalizes_case(client):
    client.post("/article/1/tag", data={"tag_name": "Tech"})
    resp = client.get("/article/1")
    assert "tech" in resp.text


def test_remove_tag(client):
    client.post("/article/1/tag", data={"tag_name": "removeme"})
    resp = client.get("/article/1")
    # Tag chip should be present (with remove button)
    assert "tag-remove" in resp.text
    # Remove it (tag id will be 1 since it's the first tag)
    client.post("/article/1/untag/1")
    resp = client.get("/article/1")
    # No more tag chips with remove buttons for this article
    assert "tag-remove" not in resp.text


def test_filter_by_tag(client):
    client.post("/article/1/tag", data={"tag_name": "alpha"})
    # Filter by tag 1 — should show only article 1
    resp = client.get("/?tag=1")
    assert resp.status_code == 200
    assert "First Post" in resp.text or "Better Title" in resp.text
    assert "Second Post" not in resp.text


def test_delete_tag(client):
    client.post("/article/1/tag", data={"tag_name": "obsolete"})
    client.post("/tags/1/delete")
    # Tag should be gone from article
    resp = client.get("/article/1")
    assert "obsolete" not in resp.text


def test_tags_shown_in_feed(client):
    client.post("/article/1/tag", data={"tag_name": "ai"})
    resp = client.get("/")
    assert "tag-chip" in resp.text
    assert "ai" in resp.text


def test_empty_tag_ignored(client):
    resp = client.post(
        "/article/1/tag", data={"tag_name": ""},
        follow_redirects=False,
    )
    assert resp.status_code == 303
