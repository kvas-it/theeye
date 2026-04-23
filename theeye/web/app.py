import os
from pathlib import Path

from urllib.parse import urlencode

from fastapi import FastAPI, Request, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from theeye.db import get_db, run_migrations

app = FastAPI(title="The Eye")

BASE_DIR = Path(__file__).parent.parent.parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

ITEMS_PER_PAGE = 25


def get_conn():
    db_path = os.environ.get("THEEYE_DB", "theeye.db")
    db = get_db(db_path)
    run_migrations(db)
    return db


@app.get("/", response_class=HTMLResponse)
def feed(
    request: Request,
    page: int = Query(1, ge=1),
    source: str | None = Query(None),
    status: str = Query("all"),  # all, unread, read, favorites
):
    db = get_conn()
    try:
        # Build query
        conditions = []
        params = []

        source_id = int(source) if source else None
        if source_id:
            conditions.append("a.source_id = ?")
            params.append(source_id)
        if status == "unread":
            conditions.append("r.article_id IS NULL")
        elif status == "read":
            conditions.append("r.article_id IS NOT NULL")
        elif status == "favorites":
            conditions.append("f.article_id IS NOT NULL")

        where = ""
        if conditions:
            where = "WHERE " + " AND ".join(conditions)

        # Count total
        count_q = f"""
            SELECT COUNT(*) as c FROM articles a
            LEFT JOIN read_state r ON a.id = r.article_id
            LEFT JOIN favorites f ON a.id = f.article_id
            {where}
        """
        total = db.execute(count_q, params).fetchone()["c"]
        total_pages = max(1, (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)

        offset = (page - 1) * ITEMS_PER_PAGE
        query = f"""
            SELECT a.id, a.url, a.title, a.author, a.discovered_at,
                   a.published_at,
                   s.name as source_name, s.id as source_id,
                   sm.summary_title, sm.summary_text,
                   r.read_at,
                   n.id as note_id,
                   f.article_id as is_favorite
            FROM articles a
            JOIN sources s ON a.source_id = s.id
            LEFT JOIN summaries sm ON a.id = sm.article_id
            LEFT JOIN read_state r ON a.id = r.article_id
            LEFT JOIN notes n ON a.id = n.article_id
            LEFT JOIN favorites f ON a.id = f.article_id
            {where}
            ORDER BY COALESCE(a.published_at, a.discovered_at) DESC
            LIMIT ? OFFSET ?
        """
        articles = db.execute(
            query, params + [ITEMS_PER_PAGE, offset]
        ).fetchall()

        # Get all sources for filter dropdown
        sources = db.execute(
            "SELECT id, name FROM sources ORDER BY name"
        ).fetchall()

        return templates.TemplateResponse(request, "feed.html", {
            "articles": articles,
            "sources": sources,
            "page": page,
            "total_pages": total_pages,
            "total": total,
            "current_source": source_id,
            "current_status": status,
        })
    finally:
        db.close()


@app.get("/article/{article_id}", response_class=HTMLResponse)
def article_detail(request: Request, article_id: int):
    db = get_conn()
    try:
        article = db.execute("""
            SELECT a.*, s.name as source_name,
                   sm.summary_title, sm.summary_text,
                   r.read_at,
                   n.text as note_text, n.id as note_id,
                   f.article_id as is_favorite
            FROM articles a
            JOIN sources s ON a.source_id = s.id
            LEFT JOIN summaries sm ON a.id = sm.article_id
            LEFT JOIN read_state r ON a.id = r.article_id
            LEFT JOIN notes n ON a.id = n.article_id
            LEFT JOIN favorites f ON a.id = f.article_id
            WHERE a.id = ?
        """, (article_id,)).fetchone()

        if not article:
            return HTMLResponse("Not found", status_code=404)

        # Auto-mark as read
        db.execute(
            """INSERT OR IGNORE INTO read_state (article_id) VALUES (?)""",
            (article_id,),
        )
        db.commit()

        return templates.TemplateResponse(request, "article.html", {
            "article": article,
        })
    finally:
        db.close()


def _feed_redirect(page: str, status: str, source: str) -> RedirectResponse:
    params = {}
    if page and page != "1":
        params["page"] = page
    if status and status != "all":
        params["status"] = status
    if source:
        params["source"] = source
    url = "/" + ("?" + urlencode(params) if params else "")
    return RedirectResponse(url, status_code=303)


@app.post("/article/{article_id}/read")
def mark_read(
    article_id: int,
    page: str = Form("1"),
    status: str = Form("all"),
    source: str = Form(""),
):
    db = get_conn()
    try:
        db.execute(
            "INSERT OR IGNORE INTO read_state (article_id) VALUES (?)",
            (article_id,),
        )
        db.commit()
        return _feed_redirect(page, status, source)
    finally:
        db.close()


@app.post("/article/{article_id}/unread")
def mark_unread(
    article_id: int,
    page: str = Form("1"),
    status: str = Form("all"),
    source: str = Form(""),
):
    db = get_conn()
    try:
        db.execute(
            "DELETE FROM read_state WHERE article_id = ?", (article_id,),
        )
        db.commit()
        return _feed_redirect(page, status, source)
    finally:
        db.close()


@app.post("/article/{article_id}/favorite")
def toggle_favorite(
    article_id: int,
    page: str = Form("1"),
    status: str = Form("all"),
    source: str = Form(""),
):
    db = get_conn()
    try:
        exists = db.execute(
            "SELECT 1 FROM favorites WHERE article_id = ?", (article_id,),
        ).fetchone()
        if exists:
            db.execute(
                "DELETE FROM favorites WHERE article_id = ?", (article_id,),
            )
        else:
            db.execute(
                "INSERT INTO favorites (article_id) VALUES (?)",
                (article_id,),
            )
        db.commit()
        return _feed_redirect(page, status, source)
    finally:
        db.close()


@app.post("/article/{article_id}/note")
def save_note(article_id: int, text: str = Form("")):
    db = get_conn()
    try:
        if text.strip():
            db.execute("""
                INSERT INTO notes (article_id, text)
                VALUES (?, ?)
                ON CONFLICT(article_id) DO UPDATE SET
                    text = excluded.text,
                    updated_at = CURRENT_TIMESTAMP
            """, (article_id, text.strip()))
        else:
            db.execute(
                "DELETE FROM notes WHERE article_id = ?", (article_id,),
            )
        db.commit()
        return RedirectResponse(f"/article/{article_id}", status_code=303)
    finally:
        db.close()
