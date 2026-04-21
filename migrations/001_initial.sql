CREATE TABLE sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL DEFAULT 'rss',
    config_json TEXT
);

CREATE TABLE articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    url TEXT NOT NULL UNIQUE,
    title TEXT,
    author TEXT,
    content_text TEXT,
    discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    published_at TIMESTAMP
);

CREATE INDEX idx_articles_source ON articles(source_id);
CREATE INDEX idx_articles_discovered ON articles(discovered_at);

CREATE TABLE summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id INTEGER NOT NULL UNIQUE REFERENCES articles(id),
    summary_title TEXT,
    summary_text TEXT,
    generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id INTEGER NOT NULL UNIQUE REFERENCES articles(id),
    text TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE read_state (
    article_id INTEGER PRIMARY KEY REFERENCES articles(id),
    read_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
