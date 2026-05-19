import argparse
import logging
import sys


def cmd_crawl(args):
    from theeye.config import load_config
    from theeye.db import get_db, run_migrations
    from theeye.crawler.crawl import crawl_all
    from theeye.summarizer.summarize import summarize_all

    config = load_config(args.sources)
    db = get_db(config.db_path)
    run_migrations(db)
    crawl_all(db, config.sources)
    if args.summarize:
        summarize_all(db, limit=0)


def cmd_add(args):
    from theeye.config import load_config
    from theeye.db import get_db, run_migrations
    from theeye.crawler.crawl import crawl_url

    config = load_config(args.sources)
    db = get_db(config.db_path)
    run_migrations(db)
    if not crawl_url(db, args.url):
        sys.exit(1)


def cmd_refetch(args):
    from theeye.config import load_config
    from theeye.db import get_db, run_migrations
    from theeye.crawler.crawl import refetch_missing

    config = load_config(args.sources)
    db = get_db(config.db_path)
    run_migrations(db)
    refetch_missing(db, limit=args.limit)


def cmd_summarize(args):
    from theeye.config import load_config
    from theeye.db import get_db, run_migrations
    from theeye.summarizer.summarize import summarize_all

    config = load_config(args.sources)
    db = get_db(config.db_path)
    run_migrations(db)
    summarize_all(db, limit=args.limit)


def cmd_tag_add(args):
    from theeye.config import load_config
    from theeye.db import get_db, run_migrations

    config = load_config(args.sources)
    db = get_db(config.db_path)
    run_migrations(db)

    name = args.name.strip().lower()
    if not name:
        print("Tag name cannot be empty.", file=sys.stderr)
        sys.exit(1)

    existing = db.execute(
        "SELECT id FROM tags WHERE name = ?", (name,)
    ).fetchone()
    if existing:
        print(f"Tag '{name}' already exists.", file=sys.stderr)
        sys.exit(1)

    db.execute("INSERT INTO tags (name) VALUES (?)", (name,))
    db.commit()
    print(f"Created tag '{name}'.")


def cmd_tag_remove(args):
    from theeye.config import load_config
    from theeye.db import get_db, run_migrations

    config = load_config(args.sources)
    db = get_db(config.db_path)
    run_migrations(db)

    name = args.name.strip().lower()
    tag = db.execute(
        "SELECT id FROM tags WHERE name = ?", (name,)
    ).fetchone()
    if not tag:
        print(f"Tag '{name}' not found.", file=sys.stderr)
        sys.exit(1)

    count = db.execute(
        "SELECT COUNT(*) as n FROM article_tags WHERE tag_id = ?",
        (tag["id"],),
    ).fetchone()["n"]

    if count > 0 and not args.force:
        print(
            f"Tag '{name}' is applied to {count} article(s). "
            "Use --force to remove it.",
            file=sys.stderr,
        )
        sys.exit(1)

    db.execute("DELETE FROM article_tags WHERE tag_id = ?", (tag["id"],))
    db.execute("DELETE FROM tags WHERE id = ?", (tag["id"],))
    db.commit()
    print(f"Removed tag '{name}'.")


def cmd_tag_list(args):
    from theeye.config import load_config
    from theeye.db import get_db, run_migrations

    config = load_config(args.sources)
    db = get_db(config.db_path)
    run_migrations(db)

    rows = db.execute("""
        SELECT t.name, COUNT(at.article_id) as n
        FROM tags t
        LEFT JOIN article_tags at ON t.id = at.tag_id
        GROUP BY t.id
        ORDER BY t.name
    """).fetchall()

    if not rows:
        print("No tags.")
        return

    for row in rows:
        print(f"  {row['name']} ({row['n']})")


def cmd_serve(args):
    import uvicorn
    from theeye.config import load_config
    from theeye.db import get_db, run_migrations

    config = load_config(args.sources)
    db = get_db(config.db_path)
    run_migrations(db)
    db.close()

    # Set env vars so the app can pick them up
    import os
    os.environ.setdefault("THEEYE_DB", config.db_path)
    os.environ.setdefault("THEEYE_SOURCES", str(args.sources))

    uvicorn.run(
        "theeye.web.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


def main():
    parser = argparse.ArgumentParser(
        prog="theeye", description="The Eye — web information aggregator"
    )
    parser.add_argument(
        "--sources", default="sources.yaml",
        help="Path to sources.yaml config file",
    )
    sub = parser.add_subparsers(dest="command")

    p_crawl = sub.add_parser("crawl", help="Crawl all configured sources")
    p_crawl.add_argument(
        "--summarize", action="store_true",
        help="Summarize new articles after crawling",
    )

    p_add = sub.add_parser("add", help="Add a single article by URL")
    p_add.add_argument("url", help="URL of the article to crawl")

    p_refetch = sub.add_parser(
        "refetch",
        help="Re-fetch articles whose body is missing (e.g. after 429s)",
    )
    p_refetch.add_argument(
        "--limit", type=int, default=0,
        help="Max articles to refetch (0 = all)",
    )

    p_sum = sub.add_parser("summarize", help="Summarize new articles")
    p_sum.add_argument(
        "--limit", type=int, default=0,
        help="Max articles to summarize (0 = all)",
    )

    p_tag = sub.add_parser("tag", help="Manage tags")
    tag_sub = p_tag.add_subparsers(dest="tag_command")

    p_tag_add = tag_sub.add_parser("add", help="Create a new tag")
    p_tag_add.add_argument("name", help="Tag name")

    p_tag_rm = tag_sub.add_parser("remove", help="Remove a tag")
    p_tag_rm.add_argument("name", help="Tag name")
    p_tag_rm.add_argument(
        "--force", action="store_true",
        help="Remove even if applied to articles",
    )

    tag_sub.add_parser("list", help="List all tags")

    p_serve = sub.add_parser("serve", help="Start web server")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--reload", action="store_true")

    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )
    # Quiet noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "tag":
        tag_handler = {
            "add": cmd_tag_add,
            "remove": cmd_tag_remove,
            "list": cmd_tag_list,
        }
        if not args.tag_command:
            p_tag.print_help()
            sys.exit(1)
        tag_handler[args.tag_command](args)
        return

    handler = {"crawl": cmd_crawl, "add": cmd_add, "refetch": cmd_refetch,
               "summarize": cmd_summarize, "serve": cmd_serve}
    handler[args.command](args)


if __name__ == "__main__":
    main()
