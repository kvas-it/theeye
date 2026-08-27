CREATE VIRTUAL TABLE articles_fts USING fts5(
    title, content, summary, note,
    tokenize = 'porter unicode61'
);

-- Rebuild the FTS row for one article from articles + summaries + notes.
-- SQLite triggers can't call functions, so the delete+insert pair is
-- repeated in each trigger below.

CREATE TRIGGER articles_fts_ai AFTER INSERT ON articles BEGIN
    INSERT INTO articles_fts(rowid, title, content, summary, note)
    VALUES (NEW.id, NEW.title, NEW.content_text, '', '');
END;

CREATE TRIGGER articles_fts_au AFTER UPDATE ON articles BEGIN
    DELETE FROM articles_fts WHERE rowid = NEW.id;
    INSERT INTO articles_fts(rowid, title, content, summary, note)
    SELECT a.id, a.title, a.content_text,
           COALESCE(sm.summary_title, '') || ' ' || COALESCE(sm.summary_text, ''),
           COALESCE(n.text, '')
    FROM articles a
    LEFT JOIN summaries sm ON sm.article_id = a.id
    LEFT JOIN notes n ON n.article_id = a.id
    WHERE a.id = NEW.id;
END;

CREATE TRIGGER articles_fts_ad AFTER DELETE ON articles BEGIN
    DELETE FROM articles_fts WHERE rowid = OLD.id;
END;

CREATE TRIGGER summaries_fts_ai AFTER INSERT ON summaries BEGIN
    DELETE FROM articles_fts WHERE rowid = NEW.article_id;
    INSERT INTO articles_fts(rowid, title, content, summary, note)
    SELECT a.id, a.title, a.content_text,
           COALESCE(NEW.summary_title, '') || ' ' || COALESCE(NEW.summary_text, ''),
           COALESCE(n.text, '')
    FROM articles a LEFT JOIN notes n ON n.article_id = a.id
    WHERE a.id = NEW.article_id;
END;

CREATE TRIGGER summaries_fts_au AFTER UPDATE ON summaries BEGIN
    DELETE FROM articles_fts WHERE rowid = NEW.article_id;
    INSERT INTO articles_fts(rowid, title, content, summary, note)
    SELECT a.id, a.title, a.content_text,
           COALESCE(NEW.summary_title, '') || ' ' || COALESCE(NEW.summary_text, ''),
           COALESCE(n.text, '')
    FROM articles a LEFT JOIN notes n ON n.article_id = a.id
    WHERE a.id = NEW.article_id;
END;

CREATE TRIGGER summaries_fts_ad AFTER DELETE ON summaries BEGIN
    DELETE FROM articles_fts WHERE rowid = OLD.article_id;
    INSERT INTO articles_fts(rowid, title, content, summary, note)
    SELECT a.id, a.title, a.content_text, '', COALESCE(n.text, '')
    FROM articles a LEFT JOIN notes n ON n.article_id = a.id
    WHERE a.id = OLD.article_id;
END;

CREATE TRIGGER notes_fts_ai AFTER INSERT ON notes BEGIN
    DELETE FROM articles_fts WHERE rowid = NEW.article_id;
    INSERT INTO articles_fts(rowid, title, content, summary, note)
    SELECT a.id, a.title, a.content_text,
           COALESCE(sm.summary_title, '') || ' ' || COALESCE(sm.summary_text, ''),
           NEW.text
    FROM articles a LEFT JOIN summaries sm ON sm.article_id = a.id
    WHERE a.id = NEW.article_id;
END;

CREATE TRIGGER notes_fts_au AFTER UPDATE ON notes BEGIN
    DELETE FROM articles_fts WHERE rowid = NEW.article_id;
    INSERT INTO articles_fts(rowid, title, content, summary, note)
    SELECT a.id, a.title, a.content_text,
           COALESCE(sm.summary_title, '') || ' ' || COALESCE(sm.summary_text, ''),
           NEW.text
    FROM articles a LEFT JOIN summaries sm ON sm.article_id = a.id
    WHERE a.id = NEW.article_id;
END;

CREATE TRIGGER notes_fts_ad AFTER DELETE ON notes BEGIN
    DELETE FROM articles_fts WHERE rowid = OLD.article_id;
    INSERT INTO articles_fts(rowid, title, content, summary, note)
    SELECT a.id, a.title, a.content_text,
           COALESCE(sm.summary_title, '') || ' ' || COALESCE(sm.summary_text, ''),
           ''
    FROM articles a LEFT JOIN summaries sm ON sm.article_id = a.id
    WHERE a.id = OLD.article_id;
END;

INSERT INTO articles_fts(rowid, title, content, summary, note)
SELECT a.id, a.title, a.content_text,
       COALESCE(sm.summary_title, '') || ' ' || COALESCE(sm.summary_text, ''),
       COALESCE(n.text, '')
FROM articles a
LEFT JOIN summaries sm ON sm.article_id = a.id
LEFT JOIN notes n ON n.article_id = a.id;
