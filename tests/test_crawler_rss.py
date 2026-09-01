from unittest.mock import patch, MagicMock

from theeye.config import Source
from theeye.crawler.crawl import (
    ensure_source, article_exists, extract_text, crawl_rss,
    match_source_by_hostname, get_manual_source, crawl_url,
    fetch_page, refetch_missing, feed_entry_text,
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
        article_id = crawl_url(db, "https://example.com/post1")

    row = db.execute("SELECT * FROM articles WHERE url = ?",
                     ("https://example.com/post1",)).fetchone()
    assert row is not None
    assert article_id == row["id"]
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
        article_id = crawl_url(db, "https://example.com/broken")

    assert article_id is None
    assert db.execute("SELECT COUNT(*) as c FROM articles").fetchone()["c"] == 0


# --- fetch_page throttling and 429 retry ---

def test_throttle_sleeps_between_same_host_requests(monkeypatch):
    from theeye.crawler import crawl as cr
    cr._last_request_time.clear()
    sleeps = []
    monkeypatch.setattr(cr.time, "sleep", sleeps.append)

    cr._throttle("example.com")  # first call: no prior, no sleep
    cr._throttle("example.com")  # second call: should sleep

    assert len(sleeps) == 1
    assert sleeps[0] > 0


def test_throttle_no_sleep_for_different_hosts(monkeypatch):
    from theeye.crawler import crawl as cr
    cr._last_request_time.clear()
    sleeps = []
    monkeypatch.setattr(cr.time, "sleep", sleeps.append)

    cr._throttle("a.com")
    cr._throttle("b.com")

    assert sleeps == []


def test_fetch_page_retries_once_on_429(monkeypatch):
    sleeps = []
    monkeypatch.setattr("theeye.crawler.crawl.time.sleep", sleeps.append)

    resp_429 = MagicMock()
    resp_429.status_code = 429
    resp_429.headers = {"Retry-After": "2"}

    resp_ok = MagicMock()
    resp_ok.status_code = 200
    resp_ok.text = "<html>ok</html>"
    resp_ok.raise_for_status = MagicMock()

    client = MagicMock()
    client.get.side_effect = [resp_429, resp_ok]

    result = fetch_page(client, "https://example.com/x")

    assert result == "<html>ok</html>"
    assert client.get.call_count == 2
    # One of the sleeps should be the Retry-After value
    assert 2.0 in sleeps


def test_fetch_page_gives_up_on_second_429(monkeypatch):
    monkeypatch.setattr("theeye.crawler.crawl.time.sleep", lambda _s: None)

    import httpx as _httpx
    resp_429 = MagicMock()
    resp_429.status_code = 429
    resp_429.headers = {"Retry-After": "0"}
    resp_429.raise_for_status.side_effect = _httpx.HTTPStatusError(
        "429", request=MagicMock(), response=resp_429,
    )

    client = MagicMock()
    client.get.return_value = resp_429

    result = fetch_page(client, "https://example.com/x")

    assert result is None
    assert client.get.call_count == 2


def test_fetch_page_missing_retry_after_uses_default(monkeypatch):
    from theeye.crawler import crawl as cr
    sleeps = []
    monkeypatch.setattr(cr.time, "sleep", sleeps.append)

    resp_429 = MagicMock()
    resp_429.status_code = 429
    resp_429.headers = {}  # no Retry-After

    resp_ok = MagicMock()
    resp_ok.status_code = 200
    resp_ok.text = "<html>ok</html>"
    resp_ok.raise_for_status = MagicMock()

    client = MagicMock()
    client.get.side_effect = [resp_429, resp_ok]

    fetch_page(client, "https://example.com/x")

    assert cr.RETRY_AFTER_DEFAULT in sleeps


# --- refetch_missing ---

def test_refetch_missing_updates_empty_content(db):
    db.execute(
        "INSERT INTO sources (name, url, type) VALUES (?, ?, ?)",
        ("Test", "https://example.com", "rss"),
    )
    db.execute(
        "INSERT INTO articles (source_id, url, title) VALUES (?, ?, ?)",
        (1, "https://example.com/post1", "Original Title"),
    )
    db.commit()

    resp = MagicMock()
    resp.status_code = 200
    resp.text = SAMPLE_HTML
    resp.raise_for_status = MagicMock()
    client = MagicMock()
    client.get.return_value = resp

    with patch("theeye.crawler.crawl.httpx.Client", return_value=client):
        count = refetch_missing(db)

    assert count == 1
    row = db.execute(
        "SELECT content_text FROM articles WHERE id = 1"
    ).fetchone()
    assert "content of the first post" in row["content_text"]


def test_refetch_missing_skips_articles_with_content(db):
    db.execute(
        "INSERT INTO sources (name, url, type) VALUES (?, ?, ?)",
        ("Test", "https://example.com", "rss"),
    )
    db.execute(
        "INSERT INTO articles (source_id, url, title, content_text) "
        "VALUES (?, ?, ?, ?)",
        (1, "https://example.com/post1", "First", "already have text"),
    )
    db.commit()

    client = MagicMock()
    with patch("theeye.crawler.crawl.httpx.Client", return_value=client):
        count = refetch_missing(db)

    assert count == 0
    client.get.assert_not_called()


def test_refetch_missing_counts_only_successful(db):
    db.execute(
        "INSERT INTO sources (name, url, type) VALUES (?, ?, ?)",
        ("Test", "https://example.com", "rss"),
    )
    db.execute(
        "INSERT INTO articles (source_id, url) VALUES (?, ?)",
        (1, "https://example.com/ok"),
    )
    db.execute(
        "INSERT INTO articles (source_id, url) VALUES (?, ?)",
        (1, "https://example.com/broken"),
    )
    db.commit()

    resp_ok = MagicMock()
    resp_ok.status_code = 200
    resp_ok.text = SAMPLE_HTML
    resp_ok.raise_for_status = MagicMock()

    def fake_get(url, **_kw):
        if url.endswith("/ok"):
            return resp_ok
        raise Exception("nope")

    client = MagicMock()
    client.get.side_effect = fake_get

    with patch("theeye.crawler.crawl.httpx.Client", return_value=client):
        count = refetch_missing(db)

    assert count == 1
    rows = db.execute(
        "SELECT url, content_text FROM articles ORDER BY id"
    ).fetchall()
    assert rows[0]["content_text"] is not None
    assert rows[1]["content_text"] is None


def test_refetch_missing_respects_limit(db):
    db.execute(
        "INSERT INTO sources (name, url, type) VALUES (?, ?, ?)",
        ("Test", "https://example.com", "rss"),
    )
    for i in range(3):
        db.execute(
            "INSERT INTO articles (source_id, url) VALUES (?, ?)",
            (1, f"https://example.com/p{i}"),
        )
    db.commit()

    resp = MagicMock()
    resp.status_code = 200
    resp.text = SAMPLE_HTML
    resp.raise_for_status = MagicMock()
    client = MagicMock()
    client.get.return_value = resp

    with patch("theeye.crawler.crawl.httpx.Client", return_value=client):
        refetch_missing(db, limit=2)

    assert client.get.call_count == 2


# --- feed content fallback ---

RSS_WITH_CONTENT = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <title>Test Feed</title>
  <item>
    <title>Embedded Post</title>
    <link>https://example.com/embedded</link>
    <description>&lt;p&gt;Full text from the feed itself.&lt;/p&gt;</description>
  </item>
</channel>
</rss>"""


def test_feed_entry_text_from_summary():
    import feedparser
    feed = feedparser.parse(RSS_WITH_CONTENT)
    assert feed_entry_text(feed.entries[0]) == "Full text from the feed itself."


def test_feed_entry_text_missing():
    import feedparser
    feed = feedparser.parse(SAMPLE_RSS)
    assert feed_entry_text(feed.entries[0]) is None


def test_crawl_rss_falls_back_to_feed_content(db):
    src = Source(name="Test", url="https://example.com/feed", type="rss")
    sid = ensure_source(db, src)
    client = MagicMock()
    import feedparser
    parsed = feedparser.parse(RSS_WITH_CONTENT)
    with patch("theeye.crawler.crawl.feedparser.parse", return_value=parsed), \
         patch("theeye.crawler.crawl.fetch_page", return_value=None):
        count = crawl_rss(db, client, src, sid)
    assert count == 1
    row = db.execute(
        "SELECT content_text FROM articles WHERE url = ?",
        ("https://example.com/embedded",),
    ).fetchone()
    assert row["content_text"] == "Full text from the feed itself."


def test_crawl_rss_prefer_feed_content_skips_fetch(db):
    src = Source(
        name="Test", url="https://example.com/feed", type="rss",
        prefer_feed_content=True,
    )
    sid = ensure_source(db, src)
    client = MagicMock()
    import feedparser
    parsed = feedparser.parse(RSS_WITH_CONTENT)
    with patch("theeye.crawler.crawl.feedparser.parse", return_value=parsed), \
         patch("theeye.crawler.crawl.fetch_page") as mock_fetch:
        count = crawl_rss(db, client, src, sid)
    assert count == 1
    mock_fetch.assert_not_called()
    row = db.execute(
        "SELECT content_text FROM articles WHERE url = ?",
        ("https://example.com/embedded",),
    ).fetchone()
    assert row["content_text"] == "Full text from the feed itself."


def test_crawl_rss_prefer_feed_content_falls_back_to_fetch(db):
    # Feed without embedded content: still fetch the page.
    src = Source(
        name="Test", url="https://example.com/feed", type="rss",
        prefer_feed_content=True,
    )
    sid = ensure_source(db, src)
    client = MagicMock()
    import feedparser
    parsed = feedparser.parse(SAMPLE_RSS)
    with patch("theeye.crawler.crawl.feedparser.parse", return_value=parsed), \
         patch("theeye.crawler.crawl.fetch_page", return_value=SAMPLE_HTML):
        crawl_rss(db, client, src, sid)
    row = db.execute(
        "SELECT content_text FROM articles WHERE url = ?",
        ("https://example.com/post1",),
    ).fetchone()
    assert "content of the first post" in row["content_text"]
