import json
from unittest.mock import patch, MagicMock

from theeye.summarizer.summarize import (
    get_unsummarized, build_prompt, call_claude, summarize_all,
    summarize_one, get_all_tags, save_article_tags,
    MAX_ARTICLE_CHARS,
)


def _insert_article(db, title="Test Article", content="Some content " * 50):
    db.execute(
        "INSERT INTO sources (name, url, type) VALUES (?, ?, ?)",
        ("Test Source", "https://example.com", "rss"),
    )
    db.execute(
        """INSERT INTO articles (source_id, url, title, content_text)
           VALUES (?, ?, ?, ?)""",
        (1, "https://example.com/post1", title, content),
    )
    db.commit()


def test_get_unsummarized(db):
    _insert_article(db)
    rows = get_unsummarized(db)
    assert len(rows) == 1
    assert rows[0]["title"] == "Test Article"
    assert rows[0]["source_name"] == "Test Source"


def test_get_unsummarized_excludes_summarized(db):
    _insert_article(db)
    db.execute(
        """INSERT INTO summaries (article_id, summary_title, summary_text)
           VALUES (?, ?, ?)""",
        (1, "Summary", "Summary text"),
    )
    db.commit()
    rows = get_unsummarized(db)
    assert len(rows) == 0


def test_get_unsummarized_excludes_no_content(db):
    db.execute(
        "INSERT INTO sources (name, url, type) VALUES (?, ?, ?)",
        ("Test Source", "https://example.com", "rss"),
    )
    db.execute(
        """INSERT INTO articles (source_id, url, title, content_text)
           VALUES (?, ?, ?, ?)""",
        (1, "https://example.com/post1", "No Content", None),
    )
    db.commit()
    rows = get_unsummarized(db)
    assert len(rows) == 0


def test_get_unsummarized_limit(db):
    db.execute(
        "INSERT INTO sources (name, url, type) VALUES (?, ?, ?)",
        ("Test Source", "https://example.com", "rss"),
    )
    for i in range(5):
        db.execute(
            """INSERT INTO articles (source_id, url, title, content_text)
               VALUES (?, ?, ?, ?)""",
            (1, f"https://example.com/post{i}", f"Post {i}", "Content"),
        )
    db.commit()
    rows = get_unsummarized(db, limit=3)
    assert len(rows) == 3


def test_build_prompt():
    prompt = build_prompt("Title", "Author", "Source", "Text content")
    assert "Source: Source" in prompt
    assert "Title: Title" in prompt
    assert "Author: Author" in prompt
    assert "Text content" in prompt


def test_build_prompt_truncates():
    long_text = "x" * (MAX_ARTICLE_CHARS + 1000)
    prompt = build_prompt("T", None, "S", long_text)
    # The text in the prompt should be truncated
    assert len(prompt) < MAX_ARTICLE_CHARS + 200


def test_call_claude_success():
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = json.dumps({
        "result": json.dumps({
            "summary_title": "Good Title",
            "summary_text": "Good summary.",
        })
    })
    with patch("theeye.summarizer.summarize.subprocess.run",
               return_value=mock_result):
        result = call_claude("test prompt")
    assert result == {
        "summary_title": "Good Title",
        "summary_text": "Good summary.",
    }


def test_call_claude_error():
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "error"
    with patch("theeye.summarizer.summarize.subprocess.run",
               return_value=mock_result):
        result = call_claude("test prompt")
    assert result is None


def test_summarize_all(db):
    _insert_article(db)

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = json.dumps({
        "result": json.dumps({
            "summary_title": "Summarized Title",
            "summary_text": "This is a summary.",
        })
    })
    with patch("theeye.summarizer.summarize.subprocess.run",
               return_value=mock_result):
        summarize_all(db)

    row = db.execute(
        "SELECT * FROM summaries WHERE article_id = 1"
    ).fetchone()
    assert row is not None
    assert row["summary_title"] == "Summarized Title"
    assert row["summary_text"] == "This is a summary."


def _mock_claude(summary_title, summary_text):
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = json.dumps({
        "result": json.dumps({
            "summary_title": summary_title,
            "summary_text": summary_text,
        })
    })
    return mock_result


def test_summarize_one(db):
    _insert_article(db)

    with patch("theeye.summarizer.summarize.subprocess.run",
               return_value=_mock_claude("Title", "Summary.")):
        ok = summarize_one(db, 1)

    assert ok
    row = db.execute(
        "SELECT * FROM summaries WHERE article_id = 1"
    ).fetchone()
    assert row["summary_title"] == "Title"


def test_summarize_one_replaces_existing_summary(db):
    _insert_article(db)
    db.execute(
        """INSERT INTO summaries (article_id, summary_title, summary_text)
           VALUES (?, ?, ?)""",
        (1, "Old Title", "Old summary."),
    )
    db.commit()

    with patch("theeye.summarizer.summarize.subprocess.run",
               return_value=_mock_claude("New Title", "New summary.")):
        ok = summarize_one(db, 1)

    assert ok
    rows = db.execute(
        "SELECT * FROM summaries WHERE article_id = 1"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["summary_title"] == "New Title"
    assert rows[0]["summary_text"] == "New summary."


def test_summarize_one_missing_article(db):
    assert not summarize_one(db, 42)


def test_summarize_one_no_content(db):
    db.execute(
        "INSERT INTO sources (name, url, type) VALUES (?, ?, ?)",
        ("Test Source", "https://example.com", "rss"),
    )
    db.execute(
        """INSERT INTO articles (source_id, url, title, content_text)
           VALUES (?, ?, ?, ?)""",
        (1, "https://example.com/post1", "No Content", None),
    )
    db.commit()
    assert not summarize_one(db, 1)


def test_get_all_tags(db):
    db.execute("INSERT INTO tags (name) VALUES (?)", ("tech",))
    db.execute("INSERT INTO tags (name) VALUES (?)", ("science",))
    db.commit()
    tags = get_all_tags(db)
    assert tags == {"tech": 1, "science": 2}


def test_get_all_tags_empty(db):
    assert get_all_tags(db) == {}


def test_save_article_tags(db):
    _insert_article(db)
    db.execute("INSERT INTO tags (name) VALUES (?)", ("tech",))
    db.execute("INSERT INTO tags (name) VALUES (?)", ("ai",))
    db.commit()
    tag_lookup = get_all_tags(db)

    save_article_tags(db, 1, ["tech", "ai"], tag_lookup)
    db.commit()

    rows = db.execute(
        "SELECT tag_id FROM article_tags WHERE article_id = 1"
    ).fetchall()
    assert {r["tag_id"] for r in rows} == {1, 2}


def test_save_article_tags_ignores_unknown(db):
    _insert_article(db)
    db.execute("INSERT INTO tags (name) VALUES (?)", ("tech",))
    db.commit()
    tag_lookup = get_all_tags(db)

    save_article_tags(db, 1, ["tech", "nonexistent"], tag_lookup)
    db.commit()

    rows = db.execute(
        "SELECT tag_id FROM article_tags WHERE article_id = 1"
    ).fetchall()
    assert len(rows) == 1


def test_summarize_all_with_tags(db):
    _insert_article(db)
    db.execute("INSERT INTO tags (name) VALUES (?)", ("tech",))
    db.execute("INSERT INTO tags (name) VALUES (?)", ("ai",))
    db.commit()

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = json.dumps({
        "result": json.dumps({
            "summary_title": "AI Article",
            "summary_text": "About AI.",
            "tags": ["tech", "ai"],
        })
    })
    with patch("theeye.summarizer.summarize.subprocess.run",
               return_value=mock_result):
        summarize_all(db)

    tags = db.execute(
        "SELECT t.name FROM article_tags at"
        " JOIN tags t ON at.tag_id = t.id"
        " WHERE at.article_id = 1"
    ).fetchall()
    assert {r["name"] for r in tags} == {"tech", "ai"}


def test_summarize_all_no_tags_in_db(db):
    """When no tags exist, summarizer should not include tags field."""
    _insert_article(db)

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = json.dumps({
        "result": json.dumps({
            "summary_title": "Plain Summary",
            "summary_text": "No tags.",
        })
    })
    with patch("theeye.summarizer.summarize.subprocess.run",
               return_value=mock_result) as mock_run:
        summarize_all(db)

    # Verify the system prompt didn't include tag instructions
    call_args = mock_run.call_args
    cmd = call_args[0][0]
    system_prompt_idx = cmd.index("--system-prompt") + 1
    assert "tags" not in cmd[system_prompt_idx].lower()
