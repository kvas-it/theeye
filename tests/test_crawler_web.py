from unittest.mock import MagicMock, patch

from theeye.config import Source
from theeye.crawler.web import extract_links, crawl_web
from theeye.crawler.crawl import ensure_source

INDEX_HTML = """\
<html><body>
<main>
  <a href="/articles/2024/post-one">First Article</a>
  <a href="/articles/2024/post-two">Second Article</a>
  <a href="/about">About Us</a>
  <a href="https://external.com/foo">External</a>
  <a href="#section">Anchor</a>
</main>
<footer>
  <a href="/privacy">Privacy</a>
</footer>
</body></html>"""

ARTICLE_HTML = """\
<html><head><title>First Article</title></head>
<body><article>
<h1>First Article</h1>
<p>This article has enough substantial content to pass the minimum
length check. It discusses important topics at length to ensure
readability can extract meaningful text from the page.</p>
<p>More content here to ensure we pass the 200 char threshold that
the web crawler uses to filter out non-article pages.</p>
</article></body></html>"""


def test_extract_links_basic():
    links = extract_links(INDEX_HTML, "https://example.com/articles")
    # Should include same-domain links, exclude external and anchors
    assert "https://example.com/articles/2024/post-one" in links
    assert "https://example.com/articles/2024/post-two" in links
    assert "https://example.com/about" in links
    assert "https://example.com/privacy" in links
    # External link excluded
    assert not any("external.com" in l for l in links)


def test_extract_links_with_pattern():
    links = extract_links(
        INDEX_HTML, "https://example.com/articles",
        link_pattern=r"/articles/\d{4}/",
    )
    assert len(links) == 2
    assert "https://example.com/articles/2024/post-one" in links
    assert "https://example.com/articles/2024/post-two" in links


def test_extract_links_with_selector():
    links = extract_links(
        INDEX_HTML, "https://example.com/articles",
        link_selector="main",
    )
    # Only links inside <main>, not <footer>
    urls = set(links)
    assert "https://example.com/articles/2024/post-one" in urls
    assert "https://example.com/privacy" not in urls


def test_crawl_web_inserts_articles(db):
    src = Source(
        name="Test Site", url="https://example.com/articles",
        type="web", link_pattern=r"/articles/\d{4}/",
    )
    source_id = ensure_source(db, src)

    def mock_get(url, **kw):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        if url == "https://example.com/articles":
            resp.text = INDEX_HTML
        else:
            resp.text = ARTICLE_HTML
        return resp

    mock_client = MagicMock()
    mock_client.get.side_effect = mock_get

    count = crawl_web(db, mock_client, src, source_id)
    assert count == 2

    rows = db.execute("SELECT url FROM articles ORDER BY url").fetchall()
    urls = [r["url"] for r in rows]
    assert "https://example.com/articles/2024/post-one" in urls
    assert "https://example.com/articles/2024/post-two" in urls


def test_crawl_web_skips_existing(db):
    src = Source(
        name="Test Site", url="https://example.com/articles",
        type="web", link_pattern=r"/articles/\d{4}/",
    )
    source_id = ensure_source(db, src)
    # Pre-insert one article
    db.execute(
        "INSERT INTO articles (source_id, url, title) VALUES (?, ?, ?)",
        (source_id, "https://example.com/articles/2024/post-one", "Old"),
    )
    db.commit()

    def mock_get(url, **kw):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        if url == "https://example.com/articles":
            resp.text = INDEX_HTML
        else:
            resp.text = ARTICLE_HTML
        return resp

    mock_client = MagicMock()
    mock_client.get.side_effect = mock_get

    count = crawl_web(db, mock_client, src, source_id)
    assert count == 1  # only post-two is new
