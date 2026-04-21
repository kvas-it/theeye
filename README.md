# The Eye

An information aggregator that crawls the web for articles and presents them
in a feed with AI-generated summaries, plus dashboards with configurable
indicators.

## Architecture

- **Crawler** — fetches configured sources (RSS feeds, web pages), extracts
  article text, stores in SQLite
- **Summarizer** — generates titles and summaries via Claude Code CLI
  (headless mode), designed to run during off-peak hours
- **Web UI** — FastAPI + Jinja2 server-rendered feed with read/unread tracking
  and notes

## Setup

```bash
pyenv local theeye  # Python 3.12 virtualenv
pip install -e ".[dev]"
```

## Usage

```bash
# Crawl all configured sources
theeye crawl

# Summarize new articles via Claude CLI
theeye summarize

# Start the web server
theeye serve
```

## Configuration

Sources are defined in `sources.yaml`:

```yaml
sources:
  - name: "Example Blog"
    url: "https://example.com/feed.xml"
    type: rss

  - name: "Example Site"
    url: "https://example.com/articles"
    type: web
    link_pattern: "/articles/\\d{4}/"
```

## Development

```bash
pytest                 # run tests
pytest --cov=theeye    # run tests with coverage
```
