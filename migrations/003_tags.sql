CREATE TABLE tags (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE article_tags (
    article_id INTEGER NOT NULL REFERENCES articles(id),
    tag_id INTEGER NOT NULL REFERENCES tags(id),
    PRIMARY KEY (article_id, tag_id)
);

CREATE INDEX idx_article_tags_tag ON article_tags(tag_id);
