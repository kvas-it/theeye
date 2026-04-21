import json
from unittest.mock import patch, MagicMock

from theeye.summarizer.summarize import (
    get_unsummarized, build_prompt, call_claude, summarize_all,
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
