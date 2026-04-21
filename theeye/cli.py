import argparse
import sys


def cmd_crawl(args):
    from theeye.config import load_config
    from theeye.db import get_db, run_migrations
    from theeye.crawler.crawl import crawl_all

    config = load_config(args.sources)
    db = get_db(config.db_path)
    run_migrations(db)
    crawl_all(db, config.sources)


def cmd_summarize(args):
    from theeye.config import load_config
    from theeye.db import get_db, run_migrations
    from theeye.summarizer.summarize import summarize_all

    config = load_config(args.sources)
    db = get_db(config.db_path)
    run_migrations(db)
    summarize_all(db, limit=args.limit)


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

    sub.add_parser("crawl", help="Crawl all configured sources")

    p_sum = sub.add_parser("summarize", help="Summarize new articles")
    p_sum.add_argument(
        "--limit", type=int, default=0,
        help="Max articles to summarize (0 = all)",
    )

    p_serve = sub.add_parser("serve", help="Start web server")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--reload", action="store_true")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    handler = {"crawl": cmd_crawl, "summarize": cmd_summarize,
               "serve": cmd_serve}
    handler[args.command](args)


if __name__ == "__main__":
    main()
