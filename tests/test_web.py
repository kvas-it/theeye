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


def test_feed_default_filter_is_unread(client):
    # Mark first article as read; default feed should hide it.
    client.post("/article/1/read")
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Second Post" in resp.text
    assert "Better Title for First Post" not in resp.text


def test_feed_filter_all_shows_read(client):
    client.post("/article/1/read")
    resp = client.get("/?status=all")
    assert resp.status_code == 200
    assert "Better Title for First Post" in resp.text
    assert "Second Post" in resp.text


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
    resp = client.get("/?status=all")
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
    resp = client.get("/?tag=1&status=all")
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
    resp = client.get("/?status=all")
    assert "tag-chip" in resp.text
    assert "ai" in resp.text


def test_empty_tag_ignored(client):
    resp = client.post(
        "/article/1/tag", data={"tag_name": ""},
        follow_redirects=False,
    )
    assert resp.status_code == 303


def test_search_matches_content(client):
    resp = client.get("/?q=second")
    assert resp.status_code == 200
    assert "Second Post" in resp.text
    assert "First Post" not in resp.text
    assert "<mark>Second</mark>" in resp.text


def test_search_matches_summary(client):
    resp = client.get("/?q=summary")
    assert "Better Title for First Post" in resp.text
    assert "Second Post" not in resp.text


def test_search_includes_read_articles_by_default(client):
    client.post("/article/1/read")
    resp = client.get("/?q=first")
    assert "Better Title for First Post" in resp.text


def test_search_respects_status_filter(client):
    client.post("/article/1/read")
    resp = client.get("/?q=first&status=unread")
    assert "Better Title for First Post" not in resp.text


def test_search_tolerates_fts_syntax(client):
    resp = client.get('/?q=first OR "unclosed (weird')
    assert resp.status_code == 200


def test_search_no_results(client):
    resp = client.get("/?q=zzzqqq")
    assert resp.status_code == 200
    assert "Nothing found" in resp.text


def test_search_snippet_escapes_html(client):
    import sqlite3
    db = sqlite3.connect(os.environ["THEEYE_DB"])
    db.execute(
        "UPDATE articles SET content_text = 'kumquat <script>x</script>'"
        " WHERE id = 2"
    )
    db.commit()
    db.close()
    resp = client.get("/?q=kumquat")
    assert "<mark>kumquat</mark>" in resp.text
    assert "<script>x</script>" not in resp.text
    assert "&lt;script&gt;" in resp.text


def test_fts_index_follows_updates(client):
    import sqlite3
    db = sqlite3.connect(os.environ["THEEYE_DB"])
    db.execute(
        "UPDATE articles SET content_text = 'now about giraffes' WHERE id = 2"
    )
    db.execute(
        "INSERT INTO summaries (article_id, summary_text)"
        " VALUES (2, 'a summary mentioning zebras')"
    )
    db.commit()
    db.close()
    assert "Second Post" in client.get("/?q=giraffes").text
    assert "Second Post" in client.get("/?q=zebras").text
    # Old content no longer indexed
    assert "Second Post" not in client.get("/?q=content").text


def test_search_matches_notes(client):
    client.post("/article/2/note", data={"text": "remember the pelican"})
    assert "Second Post" in client.get("/?q=pelican").text
    client.post("/article/2/note", data={"text": "changed"})
    assert "Second Post" not in client.get("/?q=pelican").text
    client.post("/article/2/note", data={"text": ""})
    assert "Second Post" not in client.get("/?q=changed").text
    # Article itself still searchable after note deletion
    assert "Second Post" in client.get("/?q=second").text
