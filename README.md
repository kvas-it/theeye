# The Eye

A self-hosted information aggregator. Crawls configured sources (RSS feeds
and web pages), extracts article text, generates titles and summaries with
the Claude Code CLI, and serves the result as a web feed with read/unread
tracking, favorites, tags, and per-article notes.

## Features

- **Multiple source types**: RSS/Atom feeds, plus generic web pages with
  CSS-selector–based link extraction (useful for forums and sites without
  feeds).
- **AI summaries**: each new article gets a clearer title and a short
  summary, generated via the Claude Code CLI.
- **Tags**: auto-assigned during summarization, plus manual tagging from
  the web UI or CLI.
- **Lightweight stack**: Python 3.12, FastAPI, server-rendered Jinja2
  templates, SQLite. No JS build step.

## Prerequisites

- Python 3.12
- [Claude Code CLI](https://claude.com/claude-code) on your `PATH` — the
  summarizer shells out to `claude -p`. Without it, crawling still works
  but summaries won't be generated.

## Setup

```bash
pip install -e ".[dev]"
cp sources.example.yaml sources.yaml   # then edit to add your feeds
```

## Usage

```bash
theeye crawl                # fetch new articles from all sources
theeye crawl --summarize    # crawl, then summarize new articles
theeye summarize            # summarize unsummarized articles
theeye add <url>            # crawl a single article on demand
theeye serve                # web UI on http://127.0.0.1:8000

theeye tag list             # list tags and article counts
theeye tag add <name>       # create a new tag
theeye tag remove <name>    # delete a tag (use --force if it's in use)
```

A typical workflow is to run `theeye crawl --summarize` on a schedule
(cron, systemd timer, etc.) and leave `theeye serve` running.

## Configuration

Sources are defined in `sources.yaml` (gitignored — it's local config).
Start from `sources.example.yaml`:

```yaml
sources:
  - name: "Example Blog"
    url: "https://example.com/feed.xml"
    type: rss

  - name: "Example Forum"
    url: "https://example.com/forum/"
    type: web
    link_selector: "div.thread-title a"      # CSS selector for article links
    link_pattern: "/threads/[^/]+\\.\\d+/"   # regex filter for URLs
    content_selector: "article .content"     # CSS selector for content
```

Source types:
- `rss` — RSS/Atom feed, parsed with `feedparser`.
- `web` — HTML page that links to articles. Use `link_selector` and
  `link_pattern` to target the right links, and `content_selector` to
  extract content from specific elements (avoids picking up page chrome).

The SQLite database lives at `theeye.db` in the working directory by
default. Override with the `THEEYE_DB` environment variable.

## Development

```bash
pytest                  # run all tests
pytest --cov=theeye     # with coverage
```

Tests use a fresh SQLite database per test (via the `db` fixture in
`tests/conftest.py`). Crawler tests use mocked HTTP responses.

## License

MIT — see [LICENSE](LICENSE).
