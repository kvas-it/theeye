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

SYSTEM_PROMPT_WITH_TAGS = """\
You are a summarizer for a news/article feed reader. Given an article's \
title, author, source, and text, produce a JSON summary.

Rules:
- summary_title: If the original title is informative enough, keep it. \
If not, write a 1-sentence informative title.
- summary_text: A single paragraph (2-4 sentences) capturing the key points. \
Be concise and informative.
- tags: Pick relevant tags from this list ONLY: {tags}. \
Return an empty array if none fit. Do NOT invent new tags."""

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "summary_title": {"type": "string"},
        "summary_text": {"type": "string"},
    },
    "required": ["summary_title", "summary_text"],
}

SUMMARY_SCHEMA_WITH_TAGS = {
    "type": "object",
    "properties": {
        "summary_title": {"type": "string"},
        "summary_text": {"type": "string"},
        "tags": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["summary_title", "summary_text", "tags"],
}

JSON_SCHEMA = json.dumps(SUMMARY_SCHEMA)

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


def call_claude(
    prompt: str,
    system_prompt: str = SYSTEM_PROMPT,
    json_schema: str = JSON_SCHEMA,
) -> dict | None:
    """Call Claude CLI in print mode, return parsed JSON."""
    cmd = [
        "claude", "-p",
        "--output-format", "json",
        "--model", "haiku",
        "--system-prompt", system_prompt,
        "--json-schema", json_schema,
    ]
    try:
        result = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            log.warning(
                "Claude CLI error (rc=%d): %s",
                result.returncode,
                result.stderr[:500] or result.stdout[:500],
            )
            return None
        data = json.loads(result.stdout)
        if data.get("is_error"):
            log.warning("Claude CLI error: %s", data.get("result", "")[:500])
            return None
        # --json-schema puts structured output in "structured_output"
        structured = data.get("structured_output")
        if isinstance(structured, dict):
            return structured
        # Fallback: try parsing "result" as JSON
        text = data.get("result", "")
        if isinstance(text, str):
            return json.loads(text)
        return text
    except subprocess.TimeoutExpired:
        log.warning("Claude CLI timed out")
        return None
    except (json.JSONDecodeError, KeyError) as e:
        log.warning("Failed to parse Claude response: %s", e)
        return None


def get_all_tags(db: sqlite3.Connection) -> dict[str, int]:
    """Return {tag_name: tag_id} for all existing tags."""
    rows = db.execute("SELECT id, name FROM tags").fetchall()
    return {row["name"]: row["id"] for row in rows}


def save_article_tags(db, article_id, tag_names, tag_lookup):
    """Insert article_tags rows for recognized tag names."""
    for name in tag_names:
        tag_id = tag_lookup.get(name)
        if tag_id is not None:
            db.execute(
                """INSERT OR IGNORE INTO article_tags (article_id, tag_id)
                   VALUES (?, ?)""",
                (article_id, tag_id),
            )


def summarize_all(db: sqlite3.Connection, limit: int = 0):
    articles = get_unsummarized(db, limit)
    log.info("Found %d articles to summarize", len(articles))

    # Build tagging prompt/schema if tags exist
    tag_lookup = get_all_tags(db)
    if tag_lookup:
        tag_list = ", ".join(sorted(tag_lookup))
        system_prompt = SYSTEM_PROMPT_WITH_TAGS.format(tags=tag_list)
        schema = json.dumps(SUMMARY_SCHEMA_WITH_TAGS)
        log.info("Auto-tagging enabled with %d tags", len(tag_lookup))
    else:
        system_prompt = SYSTEM_PROMPT
        schema = JSON_SCHEMA

    success = 0
    for article in articles:
        prompt = build_prompt(
            article["title"], article["author"],
            article["source_name"], article["content_text"],
        )
        log.info("Summarizing: %s", article["title"] or f"#{article['id']}")

        result = call_claude(prompt, system_prompt, schema)
        if not result:
            log.warning("  Failed, skipping")
            continue

        db.execute(
            """INSERT INTO summaries (article_id, summary_title, summary_text)
               VALUES (?, ?, ?)""",
            (article["id"], result["summary_title"], result["summary_text"]),
        )

        if tag_lookup and result.get("tags"):
            save_article_tags(
                db, article["id"], result["tags"], tag_lookup,
            )

        db.commit()
        success += 1
        log.info("  Done: %s", result["summary_title"])

    log.info("Summarized %d/%d articles", success, len(articles))
