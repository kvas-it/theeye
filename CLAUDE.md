# The Eye — Development Guide

## Project overview

Web information aggregator: crawl sources, extract articles, summarize with
Claude CLI, serve as a feed with notes. Python 3.12, FastAPI, SQLite.

## Commands

```bash
pip install -e ".[dev]"    # install with dev dependencies
pytest                     # run all tests
pytest --cov=theeye        # tests with coverage report
theeye crawl               # crawl all sources
theeye summarize           # summarize unsummarized articles
theeye serve               # start web server (default port 8000)
```

## Architecture

```
theeye/
  __init__.py
  cli.py             # CLI entry points (crawl, summarize, serve)
  config.py          # load sources.yaml and app settings
  db.py              # SQLite connection, migration runner
  crawler/           # feed parsing and article extraction
  summarizer/        # Claude CLI integration for summaries
  web/               # FastAPI app, routes, Jinja2 templates
migrations/          # numbered SQL files (001_initial.sql, ...)
templates/           # Jinja2 HTML templates
static/              # CSS, JS
tests/               # pytest tests mirroring src structure
sources.yaml         # feed source configuration
```

## Key decisions

- **Migrations**: simple numbered SQL files in `migrations/`, tracked by
  `schema_version` table. App runs pending migrations on startup.
- **Extraction**: `feedparser` for RSS/Atom, `readability-lxml` for article
  text from any URL. Sources can set `content_selector` to extract from
  specific CSS-selected elements instead of readability heuristics.
- **Summarization**: Claude Code CLI in pipe mode (`claude -p`), decoupled
  from crawling. Uses `--output-format json` and `--json-schema`; the
  structured result is in the `structured_output` field of the JSON
  response. Do NOT use `--bare` flag (breaks Max subscription auth).
- **Frontend**: server-rendered Jinja2 templates. Add htmx for interactivity
  as needed — no JS build step.
- **Config**: sources in `sources.yaml`, app settings via environment
  variables or a config file.

## Testing

- All new code must have tests. Run `pytest` before committing.
- Tests use a fresh in-memory SQLite database (via fixture).
- For crawler tests, use recorded HTTP responses (fixtures or mocking).
- For web tests, use FastAPI TestClient.
- Aim for good coverage of business logic; don't obsess over 100% but do
  cover the important paths.

## Style

- Follow PEP 8, prioritize readability
- Line length: aim for 80 columns, up to ~100 if it helps readability
- Make code self-documenting; comment the "why" not the "what"
- Keep functions well-scoped but not artificially short

## Task tracking

Tasks are managed with `tsk` (markdown tickets in `tsk/`).
