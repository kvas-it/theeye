import json
import logging
import sqlite3
import subprocess

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a summarizer for a news/article feed reader. Given an article's \
title, author, source, and text, produce a JSON summary.

Rules:
- summary_title: If the original title is informative enough, keep it. \
If not, write a 1-sentence informative title.
- summary_text: A single paragraph (2-4 sentences) capturing the key points. \
Be concise and informative."""

JSON_SCHEMA = json.dumps({
    "type": "object",
    "properties": {
        "summary_title": {"type": "string"},
        "summary_text": {"type": "string"},
    },
    "required": ["summary_title", "summary_text"],
})

# Truncate very long articles to keep costs/latency reasonable
MAX_ARTICLE_CHARS = 15000


def get_unsummarized(db: sqlite3.Connection, limit: int = 0):
    query = """
        SELECT a.id, a.title, a.author, a.content_text, s.name as source_name
        FROM articles a
        JOIN sources s ON a.source_id = s.id
        LEFT JOIN summaries sm ON a.id = sm.article_id
        WHERE sm.id IS NULL AND a.content_text IS NOT NULL
        ORDER BY a.discovered_at
    """
    if limit > 0:
        query += f" LIMIT {limit}"
    return db.execute(query).fetchall()


def build_prompt(title, author, source_name, content_text):
    text = content_text[:MAX_ARTICLE_CHARS]
    parts = [f"Source: {source_name}"]
    if title:
        parts.append(f"Title: {title}")
    if author:
        parts.append(f"Author: {author}")
    parts.append(f"\nArticle text:\n{text}")
    return "\n".join(parts)


def call_claude(prompt: str) -> dict | None:
    """Call Claude CLI in print mode, return parsed JSON."""
    cmd = [
        "claude", "-p",
        "--output-format", "json",
        "--model", "haiku",
        "--system-prompt", SYSTEM_PROMPT,
        "--json-schema", JSON_SCHEMA,
        "--bare",
    ]
    try:
        result = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            log.warning("Claude CLI error: %s", result.stderr[:500])
            return None
        data = json.loads(result.stdout)
        # --output-format json wraps in {"result": "..."}
        text = data.get("result", result.stdout)
        # The result itself should be JSON from --json-schema
        if isinstance(text, str):
            return json.loads(text)
        return text
    except subprocess.TimeoutExpired:
        log.warning("Claude CLI timed out")
        return None
    except (json.JSONDecodeError, KeyError) as e:
        log.warning("Failed to parse Claude response: %s", e)
        return None


def summarize_all(db: sqlite3.Connection, limit: int = 0):
    articles = get_unsummarized(db, limit)
    log.info("Found %d articles to summarize", len(articles))

    success = 0
    for article in articles:
        prompt = build_prompt(
            article["title"], article["author"],
            article["source_name"], article["content_text"],
        )
        log.info("Summarizing: %s", article["title"] or f"#{article['id']}")

        result = call_claude(prompt)
        if not result:
            log.warning("  Failed, skipping")
            continue

        db.execute(
            """INSERT INTO summaries (article_id, summary_title, summary_text)
               VALUES (?, ?, ?)""",
            (article["id"], result["summary_title"], result["summary_text"]),
        )
        db.commit()
        success += 1
        log.info("  Done: %s", result["summary_title"])

    log.info("Summarized %d/%d articles", success, len(articles))
