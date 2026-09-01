"""One-off: backfill empty LessWrong articles via the GraphQL API."""
import re
import sys
import time

import httpx
from lxml.html import fromstring

from theeye.db import get_db, run_migrations

QUERY = '{post(input:{selector:{_id:"%s"}}){result{title htmlBody}}}'

db = get_db("theeye.db")
run_migrations(db)
rows = db.execute(
    "SELECT id, url FROM articles"
    " WHERE (content_text IS NULL OR content_text = '')"
    " AND url LIKE 'https://www.lesswrong.com/posts/%'"
).fetchall()
print(f"{len(rows)} articles to backfill", flush=True)

client = httpx.Client(headers={"User-Agent": "TheEye/0.1 (feed aggregator)"})
ok = failed = 0
for row in rows:
    m = re.match(r"https://www\.lesswrong\.com/posts/([^/]+)/", row["url"])
    if not m:
        failed += 1
        continue
    try:
        resp = client.post(
            "https://www.lesswrong.com/graphql",
            json={"query": QUERY % m.group(1)},
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()["data"]["post"]["result"]
        html = result and result.get("htmlBody")
    except Exception as e:
        print(f"  FAIL {row['id']} {row['url']}: {e}", flush=True)
        failed += 1
        time.sleep(1.5)
        continue
    if not html:
        print(f"  EMPTY {row['id']} {row['url']}", flush=True)
        failed += 1
        time.sleep(1.5)
        continue
    text = fromstring(html).text_content().strip()
    db.execute(
        "UPDATE articles SET content_text = ?,"
        " title = COALESCE(title, ?) WHERE id = ?",
        (text, result.get("title"), row["id"]),
    )
    db.commit()
    ok += 1
    time.sleep(1.5)

print(f"done: {ok} filled, {failed} failed", flush=True)
