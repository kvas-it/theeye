import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Source:
    name: str
    url: str
    type: str = "rss"  # rss, web, forum
    link_selector: str | None = None
    link_pattern: str | None = None


@dataclass
class Config:
    sources: list[Source] = field(default_factory=list)
    db_path: str = "theeye.db"


def load_sources(path: str | Path) -> list[Source]:
    path = Path(path)
    if not path.exists():
        return []
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    sources = []
    for s in data.get("sources", []):
        sources.append(Source(
            name=s["name"],
            url=s["url"],
            type=s.get("type", "rss"),
            link_selector=s.get("link_selector"),
            link_pattern=s.get("link_pattern"),
        ))
    return sources


def load_config(
    sources_path: str | Path = "sources.yaml",
) -> Config:
    db_path = os.environ.get("THEEYE_DB", "theeye.db")
    sources = load_sources(sources_path)
    return Config(sources=sources, db_path=db_path)
