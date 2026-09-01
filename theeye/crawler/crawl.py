import logging
import sqlite3
import time
from urllib.parse import urljoin, urlparse

import feedparser
import httpx
from readability import Document

from theeye.config import Source

log = logging.getLogger(__name__)

# Per-host throttling. Sites like LessWrong return 429 if we fetch
# articles back-to-back without pause.
MIN_REQUEST_INTERVAL = 1.5  # seconds between requests to the same host
RETRY_AFTER_DEFAULT = 5.0   # used when 429 response has no Retry-After
RETRY_AFTER_CAP = 30.0      # never wait longer than this on a single 429

_last_request_time: dict[str, float] = {}


def ensure_source(db: sqlite3.Connection, source: Source) -> int:
    """Get or create the source row, return its id."""
    row = db.execute(
        "SELECT id FROM sources WHERE url = ?", (source.url,)
    ).fetchone()
    if row:
        return row["id"]
    cur = db.execute(
        "INSERT INTO sources (name, url, type) VALUES (?, ?, ?)",
        (source.name, source.url, source.type),
    )
    db.commit()
    return cur.lastrowid


def article_exists(db: sqlite3.Connection, url: str) -> bool:
    row = db.execute(
        "SELECT 1 FROM articles WHERE url = ?", (url,)
    ).fetchone()
    return row is not None


def extract_text(
    html: str, url: str, content_selector: str | None = None,
) -> tuple[str | None, str | None]:
    """Extract title and main text from HTML.

    If content_selector is given, extract text from matching elements
    instead of using readability's heuristic.
    """
    from lxml.html import fromstring

    if content_selector:
        from lxml.cssselect import CSSSelector
        tree = fromstring(html)
        tree.make_links_absolute(url)
        title_el = tree.find(".//title")
        title = title_el.text_content().strip() if title_el is not None else None
        sel = CSSSelector(content_selector)
        parts = [el.text_content().strip() for el in sel(tree)]
        text = "\n\n".join(parts) if parts else None
        return title, text

    doc = Document(html, url=url)
    title = doc.short_title() or None
    summary_html = doc.summary()
    try:
        tree = fromstring(summary_html)
        text = tree.text_content().strip()
    except Exception:
        text = summary_html
    return title, text


def feed_entry_text(entry) -> str | None:
    """Extract plain text from content supplied in the feed entry itself.

    Some sites (e.g. LessWrong) block direct page fetches with bot
    protection but publish full article HTML in their feed.
    """
    from lxml.html import fromstring

    html = None
    content = entry.get("content")
    if content:
        html = content[0].get("value")
    if not html:
        html = entry.get("summary")
    if not html:
        return None
    try:
        text = fromstring(html).text_content().strip()
    except Exception:
        return None
    return text or None


def _throttle(host: str) -> None:
    """Sleep so consecutive requests to the same host stay polite."""
    last = _last_request_time.get(host)
    if last is not None:
        elapsed = time.monotonic() - last
        if elapsed < MIN_REQUEST_INTERVAL:
            time.sleep(MIN_REQUEST_INTERVAL - elapsed)
    _last_request_time[host] = time.monotonic()


def _parse_retry_after(value: str | None) -> float:
    if not value:
        return RETRY_AFTER_DEFAULT
    try:
        return min(float(value), RETRY_AFTER_CAP)
    except ValueError:
        return RETRY_AFTER_DEFAULT


def fetch_page(client: httpx.Client, url: str) -> str | None:
    host = urlparse(url).hostname or ""
    for attempt in (1, 2):
        _throttle(host)
        try:
            resp = client.get(url, follow_redirects=True, timeout=30)
        except Exception as e:
            log.warning("Failed to fetch %s: %s", url, e)
            return None
        if resp.status_code == 429 and attempt == 1:
            delay = _parse_retry_after(resp.headers.get("Retry-After"))
            log.info("429 from %s, retrying in %.1fs", host, delay)
            time.sleep(delay)
            continue
        try:
            resp.raise_for_status()
        except Exception as e:
            log.warning("Failed to fetch %s: %s", url, e)
            return None
        return resp.text
    return None


def crawl_rss(
    db: sqlite3.Connection,
    client: httpx.Client,
    source: Source,
    source_id: int,
) -> int:
    """Crawl an RSS/Atom feed. Returns count of new articles."""
    log.info("Crawling RSS: %s (%s)", source.name, source.url)
    feed = feedparser.parse(source.url)
    if feed.bozo and not feed.entries:
        log.warning(
            "Feed error for %s: %s", source.name, feed.bozo_exception
        )
        return 0

    new_count = 0
    for entry in feed.entries:
        url = entry.get("link")
        if not url or article_exists(db, url):
            continue

        # Try to get full article text from the page
        title = entry.get("title")
        author = entry.get("author")
        published = entry.get("published")
        content_text = None

        html = fetch_page(client, url)
        if html:
            extracted_title, content_text = extract_text(html, url)
            if not title:
                title = extracted_title
        if not content_text:
            # Page fetch blocked or extraction failed; fall back to
            # content embedded in the feed.
            content_text = feed_entry_text(entry)

        db.execute(
            """INSERT INTO articles
               (source_id, url, title, author, content_text, published_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (source_id, url, title, author, content_text, published),
        )
        new_count += 1
        log.info("  New: %s", title or url)

    db.commit()
    return new_count


MANUAL_SOURCE_NAME = "Manual"


def match_source_by_hostname(
    db: sqlite3.Connection, url: str,
) -> int | None:
    """Find a source whose URL shares a hostname with the given URL."""
    hostname = urlparse(url).hostname
    if not hostname:
        return None
    sources = db.execute("SELECT id, url FROM sources").fetchall()
    for source in sources:
        source_host = urlparse(source["url"]).hostname
        if source_host and source_host == hostname:
            return source["id"]
    return None


def get_manual_source(db: sqlite3.Connection) -> int:
    """Get or create the Manual catch-all source."""
    row = db.execute(
        "SELECT id FROM sources WHERE name = ?", (MANUAL_SOURCE_NAME,),
    ).fetchone()
    if row:
        return row["id"]
    cur = db.execute(
        "INSERT INTO sources (name, url, type) VALUES (?, ?, ?)",
        (MANUAL_SOURCE_NAME, "", "manual"),
    )
    db.commit()
    return cur.lastrowid


def crawl_url(db: sqlite3.Connection, url: str) -> int | None:
    """Crawl a single URL. Returns the article id, or None on failure."""
    client = httpx.Client(
        headers={"User-Agent": "TheEye/0.1 (feed aggregator)"},
    )
    try:
        html = fetch_page(client, url)
        if not html:
            log.error("Failed to fetch %s", url)
            return None

        title, content_text = extract_text(html, url)

        # Match to existing source or use Manual
        source_id = match_source_by_hostname(db, url)
        if source_id is None:
            source_id = get_manual_source(db)
            log.info("No matching source, using Manual")

        existing = db.execute(
            "SELECT id FROM articles WHERE url = ?", (url,),
        ).fetchone()

        if existing:
            article_id = existing["id"]
            db.execute(
                """UPDATE articles SET title = ?, content_text = ?
                   WHERE id = ?""",
                (title, content_text, article_id),
            )
            log.info("Updated: %s", title or url)
        else:
            cursor = db.execute(
                """INSERT INTO articles
                   (source_id, url, title, content_text)
                   VALUES (?, ?, ?, ?)""",
                (source_id, url, title, content_text),
            )
            article_id = cursor.lastrowid
            log.info("Added: %s", title or url)

        db.commit()
        return article_id
    finally:
        client.close()


def refetch_missing(db: sqlite3.Connection, limit: int = 0) -> int:
    """Refetch articles whose body extraction previously failed.

    Articles with an empty `content_text` are revisited; on success
    the title and body are updated in place. Returns the number of
    articles that now have body content.
    """
    query = (
        "SELECT id, url FROM articles "
        "WHERE content_text IS NULL OR content_text = ''"
    )
    if limit > 0:
        query += " LIMIT ?"
        rows = db.execute(query, (limit,)).fetchall()
    else:
        rows = db.execute(query).fetchall()

    if not rows:
        log.info("No articles need refetching.")
        return 0

    log.info("Refetching %d article(s)", len(rows))
    client = httpx.Client(
        headers={"User-Agent": "TheEye/0.1 (feed aggregator)"},
    )
    try:
        success = 0
        for row in rows:
            url = row["url"]
            html = fetch_page(client, url)
            if not html:
                continue
            title, content_text = extract_text(html, url)
            if not content_text:
                continue
            db.execute(
                "UPDATE articles SET title = COALESCE(?, title), "
                "content_text = ? WHERE id = ?",
                (title, content_text, row["id"]),
            )
            success += 1
            log.info("  Refetched: %s", title or url)
        db.commit()
        log.info("Refetched %d/%d article(s) successfully", success, len(rows))
        return success
    finally:
        client.close()


def crawl_all(db: sqlite3.Connection, sources: list[Source]):
    client = httpx.Client(
        headers={"User-Agent": "TheEye/0.1 (feed aggregator)"},
    )
    try:
        total = 0
        for source in sources:
            source_id = ensure_source(db, source)
            if source.type == "rss":
                count = crawl_rss(db, client, source, source_id)
            elif source.type == "web":
                from theeye.crawler.web import crawl_web
                count = crawl_web(db, client, source, source_id)
            else:
                log.warning(
                    "Unknown source type %r for %s", source.type, source.name
                )
                continue
            total += count
            log.info("%s: %d new articles", source.name, count)
        log.info("Total new articles: %d", total)
    finally:
        client.close()
