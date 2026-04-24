from unittest.mock import patch, MagicMock

from theeye.config import Source
from theeye.crawler.crawl import (
    ensure_source, article_exists, extract_text, crawl_rss,
    match_source_by_hostname, get_manual_source, crawl_url,
    MANUAL_SOURCE_NAME,
)

SAMPLE_RSS = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <title>Test Feed</title>
  <item>
    <title>First Post</title>
    <link>https://example.com/post1</link>
    <author>Alice</author>
    <pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate>
  </item>
  <item>
    <title>Second Post</title>
    <link>https://example.com/post2</link>
  </item>
</channel>
</rss>"""

SAMPLE_HTML = """\
<html><head><title>First Post</title></head>
<body><article><h1>First Post</h1>
<p>This is the content of the first post. It has enough text to be
recognized by readability as the main content of the page and not
just boilerplate or navigation.</p>
<p>Another paragraph with more content to make readability happy.</p>
</article></body></html>"""


def test_ensure_source_creates(db):
    src = Source(name="Test", url="https://example.com/feed", type="rss")
    sid = ensure_source(db, src)
    assert sid == 1
    # Second call returns same id
    assert ensure_source(db, src) == 1


def test_article_exists(db):
    db.execute(
        "INSERT INTO sources (name, url, type) VALUES (?, ?, ?)",
        ("Test", "https://example.com", "rss"),
    )
    db.execute(
        "INSERT INTO articles (source_id, url, title) VALUES (?, ?, ?)",
        (1, "https://example.com/post1", "Post 1"),
    )
    db.commit()
    assert article_exists(db, "https://example.com/post1")
    assert not article_exists(db, "https://example.com/post2")


def test_extract_text():
    title, text = extract_text(SAMPLE_HTML, "https://example.com/post1")
    assert title == "First Post"
    assert "content of the first post" in text


def test_crawl_rss_inserts_new_articles(db):
    src = Source(name="Test Feed", url="https://example.com/feed.xml",
                 type="rss")
    source_id = ensure_source(db, src)

    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = SAMPLE_HTML
    mock_resp.raise_for_status = MagicMock()
    mock_client.get.return_value = mock_resp

    with patch("theeye.crawler.crawl.feedparser.parse") as mock_parse:
        mock_parse.return_value = MagicMock(
            bozo=False,
            entries=[
                {"link": "https://example.com/post1", "title": "First Post",
                 "author": "Alice", "published": "2024-01-01"},
                {"link": "https://example.com/post2", "title": "Second Post"},
            ],
        )
        count = crawl_rss(db, mock_client, src, source_id)

    assert count == 2
    rows = db.execute("SELECT * FROM articles ORDER BY id").fetchall()
    assert len(rows) == 2
    assert rows[0]["title"] == "First Post"
    assert rows[0]["author"] == "Alice"
    assert rows[1]["title"] == "Second Post"


def test_crawl_rss_skips_existing(db):
    src = Source(name="Test", url="https://example.com/feed.xml", type="rss")
    source_id = ensure_source(db, src)
    # Pre-insert one article
    db.execute(
        "INSERT INTO articles (source_id, url, title) VALUES (?, ?, ?)",
        (source_id, "https://example.com/post1", "Old Post"),
    )
    db.commit()

    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = SAMPLE_HTML
    mock_resp.raise_for_status = MagicMock()
    mock_client.get.return_value = mock_resp

    with patch("theeye.crawler.crawl.feedparser.parse") as mock_parse:
        mock_parse.return_value = MagicMock(
            bozo=False,
            entries=[
                {"link": "https://example.com/post1", "title": "First"},
                {"link": "https://example.com/post2", "title": "Second"},
            ],
        )
        count = crawl_rss(db, mock_client, src, source_id)

    assert count == 1  # only post2 is new


# --- crawl_url tests ---

def test_match_source_by_hostname(db):
    db.execute(
        "INSERT INTO sources (name, url, type) VALUES (?, ?, ?)",
        ("Example", "https://example.com/feed", "rss"),
    )
    db.commit()
    assert match_source_by_hostname(db, "https://example.com/post1") == 1
    assert match_source_by_hostname(db, "https://other.com/post") is None


def test_get_manual_source_creates(db):
    sid = get_manual_source(db)
    assert sid is not None
    row = db.execute(
        "SELECT name FROM sources WHERE id = ?", (sid,),
    ).fetchone()
    assert row["name"] == MANUAL_SOURCE_NAME
    # Second call returns same id
    assert get_manual_source(db) == sid


def test_crawl_url_new_article(db):
    mock_resp = MagicMock()
    mock_resp.text = SAMPLE_HTML
    mock_resp.raise_for_status = MagicMock()
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp

    with patch("theeye.crawler.crawl.httpx.Client", return_value=mock_client):
        ok = crawl_url(db, "https://example.com/post1")

    assert ok
    row = db.execute("SELECT * FROM articles WHERE url = ?",
                     ("https://example.com/post1",)).fetchone()
    assert row is not None
    assert row["title"] == "First Post"
    assert "content of the first post" in row["content_text"]


def test_crawl_url_matches_existing_source(db):
    db.execute(
        "INSERT INTO sources (name, url, type) VALUES (?, ?, ?)",
        ("Example Blog", "https://example.com/feed", "rss"),
    )
    db.commit()

    mock_resp = MagicMock()
    mock_resp.text = SAMPLE_HTML
    mock_resp.raise_for_status = MagicMock()
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp

    with patch("theeye.crawler.crawl.httpx.Client", return_value=mock_client):
        crawl_url(db, "https://example.com/post1")

    row = db.execute("SELECT source_id FROM articles").fetchone()
    assert row["source_id"] == 1  # matched to Example Blog


def test_crawl_url_uses_manual_source(db):
    mock_resp = MagicMock()
    mock_resp.text = SAMPLE_HTML
    mock_resp.raise_for_status = MagicMock()
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp

    with patch("theeye.crawler.crawl.httpx.Client", return_value=mock_client):
        crawl_url(db, "https://example.com/post1")

    row = db.execute("SELECT source_id FROM articles").fetchone()
    source = db.execute(
        "SELECT name FROM sources WHERE id = ?", (row["source_id"],),
    ).fetchone()
    assert source["name"] == MANUAL_SOURCE_NAME


def test_crawl_url_recrawl_updates(db):
    # First crawl
    mock_resp = MagicMock()
    mock_resp.text = SAMPLE_HTML
    mock_resp.raise_for_status = MagicMock()
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp

    with patch("theeye.crawler.crawl.httpx.Client", return_value=mock_client):
        crawl_url(db, "https://example.com/post1")

    # Re-crawl with updated content
    updated_html = SAMPLE_HTML.replace("First Post", "Updated Post")
    mock_resp2 = MagicMock()
    mock_resp2.text = updated_html
    mock_resp2.raise_for_status = MagicMock()
    mock_client2 = MagicMock()
    mock_client2.get.return_value = mock_resp2

    with patch("theeye.crawler.crawl.httpx.Client", return_value=mock_client2):
        crawl_url(db, "https://example.com/post1")

    rows = db.execute("SELECT * FROM articles").fetchall()
    assert len(rows) == 1  # no duplicate
    assert rows[0]["title"] == "Updated Post"


def test_crawl_url_fetch_failure(db):
    mock_client = MagicMock()
    mock_client.get.side_effect = Exception("connection failed")

    with patch("theeye.crawler.crawl.httpx.Client", return_value=mock_client):
        ok = crawl_url(db, "https://example.com/broken")

    assert not ok
    assert db.execute("SELECT COUNT(*) as c FROM articles").fetchone()["c"] == 0
