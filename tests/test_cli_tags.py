import argparse
import os
from unittest.mock import patch

import pytest

from theeye.db import get_db, run_migrations


@pytest.fixture
def db_env(tmp_path):
    """Set up a DB and return (db, env_patch) for CLI commands."""
    db_path = str(tmp_path / "test.db")
    sources_path = str(tmp_path / "sources.yaml")
    # Write a minimal sources file
    with open(sources_path, "w") as f:
        f.write("sources: []\n")

    db = get_db(db_path)
    run_migrations(db)

    env = {"THEEYE_DB": db_path}
    with patch.dict(os.environ, env):
        yield db, sources_path

    db.close()


def make_args(sources, **kwargs):
    return argparse.Namespace(sources=sources, **kwargs)


class TestTagAdd:
    def test_creates_tag(self, db_env, capsys):
        db, sources = db_env
        from theeye.cli import cmd_tag_add

        cmd_tag_add(make_args(sources, name="python"))

        row = db.execute(
            "SELECT name FROM tags WHERE name = 'python'"
        ).fetchone()
        assert row is not None
        assert "Created tag 'python'" in capsys.readouterr().out

    def test_normalizes_to_lowercase(self, db_env):
        db, sources = db_env
        from theeye.cli import cmd_tag_add

        cmd_tag_add(make_args(sources, name="Python"))

        row = db.execute("SELECT name FROM tags").fetchone()
        assert row["name"] == "python"

    def test_rejects_duplicate(self, db_env, capsys):
        db, sources = db_env
        from theeye.cli import cmd_tag_add

        db.execute("INSERT INTO tags (name) VALUES ('python')")
        db.commit()

        with pytest.raises(SystemExit, match="1"):
            cmd_tag_add(make_args(sources, name="python"))
        assert "already exists" in capsys.readouterr().err


class TestTagRemove:
    def test_removes_unused_tag(self, db_env, capsys):
        db, sources = db_env
        from theeye.cli import cmd_tag_remove

        db.execute("INSERT INTO tags (name) VALUES ('old')")
        db.commit()

        cmd_tag_remove(make_args(sources, name="old", force=False))

        row = db.execute("SELECT id FROM tags WHERE name = 'old'").fetchone()
        assert row is None
        assert "Removed tag 'old'" in capsys.readouterr().out

    def test_refuses_used_tag_without_force(self, db_env, capsys):
        db, sources = db_env
        from theeye.cli import cmd_tag_remove

        db.execute(
            "INSERT INTO sources (name, url, type) VALUES (?, ?, ?)",
            ("s", "https://example.com", "rss"),
        )
        db.execute(
            "INSERT INTO articles (source_id, url, title, content_text)"
            " VALUES (1, 'https://example.com/a', 'A', 'text')"
        )
        db.execute("INSERT INTO tags (name) VALUES ('used')")
        db.execute(
            "INSERT INTO article_tags (article_id, tag_id) VALUES (1, 1)"
        )
        db.commit()

        with pytest.raises(SystemExit, match="1"):
            cmd_tag_remove(make_args(sources, name="used", force=False))

        err = capsys.readouterr().err
        assert "applied to 1 article" in err
        assert "--force" in err

        # Tag still exists
        assert db.execute("SELECT id FROM tags WHERE name = 'used'").fetchone()

    def test_removes_used_tag_with_force(self, db_env, capsys):
        db, sources = db_env
        from theeye.cli import cmd_tag_remove

        db.execute(
            "INSERT INTO sources (name, url, type) VALUES (?, ?, ?)",
            ("s", "https://example.com", "rss"),
        )
        db.execute(
            "INSERT INTO articles (source_id, url, title, content_text)"
            " VALUES (1, 'https://example.com/a', 'A', 'text')"
        )
        db.execute("INSERT INTO tags (name) VALUES ('used')")
        db.execute(
            "INSERT INTO article_tags (article_id, tag_id) VALUES (1, 1)"
        )
        db.commit()

        cmd_tag_remove(make_args(sources, name="used", force=True))

        assert not db.execute(
            "SELECT id FROM tags WHERE name = 'used'"
        ).fetchone()
        assert not db.execute(
            "SELECT * FROM article_tags WHERE tag_id = 1"
        ).fetchone()
        assert "Removed tag 'used'" in capsys.readouterr().out

    def test_nonexistent_tag(self, db_env, capsys):
        _, sources = db_env
        from theeye.cli import cmd_tag_remove

        with pytest.raises(SystemExit, match="1"):
            cmd_tag_remove(make_args(sources, name="nope", force=False))
        assert "not found" in capsys.readouterr().err


class TestTagList:
    def test_empty(self, db_env, capsys):
        _, sources = db_env
        from theeye.cli import cmd_tag_list

        cmd_tag_list(make_args(sources))

        assert "No tags." in capsys.readouterr().out

    def test_lists_tags_with_counts(self, db_env, capsys):
        db, sources = db_env
        from theeye.cli import cmd_tag_list

        db.execute(
            "INSERT INTO sources (name, url, type) VALUES (?, ?, ?)",
            ("s", "https://example.com", "rss"),
        )
        db.execute(
            "INSERT INTO articles (source_id, url, title, content_text)"
            " VALUES (1, 'https://example.com/a', 'A', 'text')"
        )
        db.execute("INSERT INTO tags (name) VALUES ('alpha')")
        db.execute("INSERT INTO tags (name) VALUES ('beta')")
        db.execute(
            "INSERT INTO article_tags (article_id, tag_id) VALUES (1, 1)"
        )
        db.commit()

        cmd_tag_list(make_args(sources))

        out = capsys.readouterr().out
        assert "alpha (1)" in out
        assert "beta (0)" in out
