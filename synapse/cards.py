"""Memory cards: markdown files with a tiny frontmatter header.

A card is the atomic unit of Synapse memory. It is a museum plaque:
human-readable with `cat`, parseable without dependencies, versioned by git.

    ---
    id: d0001
    kind: decision
    title: Use pure Python stdlib
    author: dev-a
    date: 2026-08-22
    status: active
    supersedes: []
    paths: ["**"]
    tags: [stack]
    ---

    Body markdown. Context, decision, consequences.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path


@dataclass
class Card:
    id: str
    kind: str  # decision | fact | session
    title: str
    author: str
    date: str  # ISO yyyy-mm-dd
    status: str = "active"  # draft | active | superseded
    supersedes: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=lambda: ["**"])
    tags: list[str] = field(default_factory=list)
    body: str = ""

    @property
    def filename(self) -> str:
        return f"{self.id}-{slugify(self.title)}.md"


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:60] or "untitled"


def _parse_value(raw: str):
    raw = raw.strip()
    if not raw:
        return ""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        pass
    if "," in raw and ":" not in raw:
        return [p.strip() for p in raw.split(",") if p.strip()]
    return raw


def parse_card(text: str) -> tuple[dict, str]:
    """Split a card file into (metadata dict, body string)."""
    lines = text.splitlines()
    meta: dict = {}
    body_start = 0
    if lines and lines[0].strip() == "---":
        end = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end = i
                break
        if end is not None:
            for line in lines[1:end]:
                m = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", line)
                if m:
                    meta[m.group(1).lower()] = _parse_value(m.group(2))
            body_start = end + 1
            while body_start < len(lines) and not lines[body_start].strip():
                body_start += 1
    return meta, "\n".join(lines[body_start:]).strip()


def load_card(path: Path) -> Card:
    meta, body = parse_card(path.read_text(encoding="utf-8"))
    return Card(
        id=str(meta.get("id", path.stem)),
        kind=str(meta.get("kind", "decision")),
        title=str(meta.get("title", path.stem)),
        author=str(meta.get("author", "unknown")),
        date=str(meta.get("date", datetime.utcnow().date().isoformat())),
        status=str(meta.get("status", "active")),
        supersedes=[str(s) for s in (meta.get("supersedes") or [])],
        paths=[str(p) for p in (meta.get("paths") or ["**"])],
        tags=[str(t) for t in (meta.get("tags") or [])],
        body=body,
    )


def render_card(card: Card) -> str:
    def enc(v):
        if isinstance(v, list):
            return json.dumps(v)
        return str(v)

    fm = "\n".join(
        f"{k}: {enc(card.__dict__[k])}"
        for k in ("id", "kind", "title", "author", "date", "status", "supersedes", "paths", "tags")
    )
    return f"---\n{fm}\n---\n\n{card.body.strip()}\n"


def write_card(directory: Path, card: Card) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    out = directory / card.filename
    out.write_text(render_card(card), encoding="utf-8")
    return out


def plaque(card: Card, why: str | None = None) -> str:
    """Render a card as a compact museum plaque for LLM/human consumption."""
    head = f"[{card.id}] {card.title} ({card.kind}, {card.status}, {card.date}, by {card.author})"
    if card.supersedes:
        head += f" · supersedes {' '.join(card.supersedes)}"
    lines = [head]
    if card.paths and card.paths != ["**"]:
        lines.append(f"paths: {', '.join(card.paths)}")
    if why:
        lines.append(f"why: {why}")
    lines.append(card.body.strip())
    return "\n".join(lines)


def next_id(existing: list[str], prefix: str) -> str:
    """Smallest unused zero-padded id for a prefix, e.g. d0003."""
    nums = [int(e[1:]) for e in existing
            if e.startswith(prefix) and e[1:].isdigit()]
    return f"{prefix}{max(nums, default=0) + 1:04d}"


def today() -> str:
    return date.today().isoformat()
