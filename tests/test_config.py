import tempfile
from pathlib import Path

from theeye.config import Source, load_sources, load_config


def test_load_sources_from_yaml(tmp_path):
    p = tmp_path / "sources.yaml"
    p.write_text("""\
sources:
  - name: Test Blog
    url: https://example.com/feed.xml
    type: rss
  - name: Test Site
    url: https://example.com/articles
    type: web
    link_pattern: "/articles/.*"
    link_selector: "main a"
""")
    sources = load_sources(p)
    assert len(sources) == 2
    assert sources[0] == Source(
        name="Test Blog", url="https://example.com/feed.xml", type="rss",
    )
    assert sources[1].link_pattern == "/articles/.*"
    assert sources[1].link_selector == "main a"


def test_load_sources_missing_file(tmp_path):
    sources = load_sources(tmp_path / "nope.yaml")
    assert sources == []


def test_load_sources_empty_file(tmp_path):
    p = tmp_path / "sources.yaml"
    p.write_text("")
    sources = load_sources(p)
    assert sources == []


def test_load_config_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("THEEYE_DB", raising=False)
    p = tmp_path / "sources.yaml"
    p.write_text("sources: []")
    config = load_config(p)
    assert config.db_path == "theeye.db"
    assert config.sources == []


def test_load_config_db_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("THEEYE_DB", "/tmp/custom.db")
    p = tmp_path / "sources.yaml"
    p.write_text("sources: []")
    config = load_config(p)
    assert config.db_path == "/tmp/custom.db"


def test_load_sources_prefer_feed_content(tmp_path):
    f = tmp_path / "sources.yaml"
    f.write_text("""
sources:
  - name: A
    url: https://a.example/feed
    prefer_feed_content: true
  - name: B
    url: https://b.example/feed
""")
    sources = load_sources(f)
    assert sources[0].prefer_feed_content is True
    assert sources[1].prefer_feed_content is False
