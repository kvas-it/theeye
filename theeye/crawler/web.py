import logging
import re
import sqlite3
from urllib.parse import urljoin, urlparse

import httpx
from lxml.html import fromstring

from theeye.config import Source
from theeye.crawler.crawl import article_exists, extract_text, fetch_page

log = logging.getLogger(__name__)


def extract_links(
    html: str,
    base_url: str,
    link_selector: str | None = None,
    link_pattern: str | None = None,
) -> list[str]:
    """Extract article links from a page.

    If link_selector is given, only look at links matching that CSS
    selector. If link_pattern is given, filter URLs by regex.
    """
    tree = fromstring(html)
    tree.make_links_absolute(base_url)

    if link_selector:
        from lxml.cssselect import CSSSelector
        sel = CSSSelector(link_selector)
        elements = sel(tree)
        anchors = []
        for el in elements:
            if el.tag == "a":
                anchors.append(el)
            else:
                anchors.extend(el.iter("a"))
    else:
        anchors = tree.iter("a")

    seen = set()
    links = []
    base_domain = urlparse(base_url).netloc

    for a in anchors:
        href = a.get("href")
        if not href or href.startswith("#") or href.startswith("javascript:"):
            continue
        url = urljoin(base_url, href)
        # Only keep links on the same domain
        if urlparse(url).netloc != base_domain:
            continue
        # Strip fragments
        url = url.split("#")[0]
        if url in seen or url == base_url:
            continue
        seen.add(url)

        if link_pattern and not re.search(link_pattern, url):
            continue

        links.append(url)

    return links


def crawl_web(
    db: sqlite3.Connection,
    client: httpx.Client,
    source: Source,
    source_id: int,
) -> int:
    """Crawl a web page source for new articles."""
    log.info("Crawling web: %s (%s)", source.name, source.url)

    html = fetch_page(client, source.url)
    if not html:
        return 0

    links = extract_links(
        html, source.url,
        link_selector=source.link_selector,
        link_pattern=source.link_pattern,
    )
    log.info("  Found %d candidate links", len(links))

    new_count = 0
    for url in links:
        if article_exists(db, url):
            continue

        page_html = fetch_page(client, url)
        if not page_html:
            continue

        title, content_text = extract_text(
            page_html, url, content_selector=source.content_selector,
        )
        # Skip very short pages — probably not articles
        if content_text and len(content_text) < 200:
            log.debug("  Skipping short page: %s", url)
            continue

        db.execute(
            """INSERT INTO articles
               (source_id, url, title, author, content_text)
               VALUES (?, ?, ?, ?, ?)""",
            (source_id, url, title, None, content_text),
        )
        new_count += 1
        log.info("  New: %s", title or url)

    db.commit()
    return new_count
