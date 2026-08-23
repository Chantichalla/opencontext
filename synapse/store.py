"""Memory store: SQLite + FTS5 index over markdown cards.

The .memory/ directory is the truth (plain git-versioned markdown).
SQLite is a derived, rebuildable index -- never the source of truth.

Retrieval is deterministic and explainable:
    score = 0.60 * text_relevance + 0.25 * recency + 0.15 * path_affinity
Every result carries its own "why" line.
"""

from __future__ import annotations

import fnmatch
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from . import KINDS, MEMORY_DIR
from .cards import Card, load_card, next_id, render_card, slugify, today, write_card

WEIGHT_TEXT = 0.60
WEIGHT_RECENCY = 0.25
WEIGHT_PATH = 0.15


@dataclass
class Hit:
    card: Card
    score: float
    parts: dict  # {"text": .., "recency": .., "path": ..}

    @property
    def why(self) -> str:
        p = self.parts
        return (
            f"score {self.score:.2f} "
            f"(text {p.get('text', 0):.2f} x{WEIGHT_TEXT}"
            f" + recency {p.get('recency', 0):.2f} x{WEIGHT_RECENCY}"
            f" + path {p.get('path', 0):.2f} x{WEIGHT_PATH})"
        )


class Store:
    def __init__(self, root: Path | str | None = None):
        self.root = Path(root) if root else Path.cwd()
        self.memory = self.root / MEMORY_DIR
        self.db_path = self.memory / ".index.db"
        self._conn: sqlite3.Connection | None = None
        self.fts_available = True

    # ---------- lifecycle ----------

    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self.memory.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.db_path)
            try:
                self._conn.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS cards USING fts5("
                    "id UNINDEXED, kind, title, body, paths, tags, date, status)"
                )
            except sqlite3.OperationalError:
                self.fts_available = False
                self._conn.execute(
                    "CREATE TABLE IF NOT EXISTS cards ("
                    "id TEXT PRIMARY KEY, kind TEXT, title TEXT, body TEXT,"
                    "paths TEXT, tags TEXT, date TEXT, status TEXT)"
                )
        return self._conn

    def close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ---------- indexing ----------

    def scan_cards(self) -> list[tuple[Path, Card]]:
        out = []
        if not self.memory.exists():
            return out
        for md in sorted(self.memory.rglob("*.md")):
            try:
                out.append((md, load_card(md)))
            except Exception:
                continue
        return out

    def reindex(self) -> int:
        c = self.conn()
        c.execute("DELETE FROM cards")
        n = 0
        for _, card in self.scan_cards():
            self._upsert(card)
            n += 1
        c.commit()
        return n

    def _upsert(self, card: Card):
        c = self.conn()
        if not self.fts_available:
            c.execute("INSERT OR REPLACE INTO cards VALUES (?,?,?,?,?,?,?,?)",
                      (card.id, card.kind, card.title, card.body,
                       ",".join(card.paths), ",".join(card.tags), card.date, card.status))
            return
        c.execute("DELETE FROM cards WHERE id = ?", (card.id,))
        c.execute("INSERT INTO cards VALUES (?,?,?,?,?,?,?,?)",
                  (card.id, card.kind, card.title, card.body,
                   ",".join(card.paths), ",".join(card.tags), card.date, card.status))

    def ensure_index(self):
        """Rebuild only when files changed since last build."""
        marker = self.db_path.with_suffix(".stamp")
        latest = max((p.stat().st_mtime for p in self.scan_files()), default=0)
        if not self.db_path.exists() or not marker.exists() \
                or float(marker.read_text().strip() or 0) < latest:
            self.reindex()
            self.conn().commit()
            marker.write_text(str(latest))

    def scan_files(self) -> list[Path]:
        return list(self.memory.rglob("*.md")) if self.memory.exists() else []

    # ---------- writes ----------

    def create(self, kind: str, title: str, body: str, author: str,
               paths: list[str] | None = None, tags: list[str] | None = None,
               supersedes: list[str] | None = None, status: str = "draft") -> Card:
        assert kind in KINDS, f"kind must be one of {list(KINDS)}"
        existing = [c.id for _, c in self.scan_cards()]
        prefix = KINDS[kind]["prefix"]
        card_id = next_id(existing, prefix)

        if kind == "session":
            card_id = f"s{date.today().strftime('%Y%m%d')}-{slugify(title)[:24]}"

        card = Card(
            id=card_id, kind=kind, title=title, author=author or "unknown",
            date=today(), status=status,
            supersedes=list(supersedes or []), paths=list(paths or ["**"]),
            tags=list(tags or []), body=body.strip(),
        )
        write_card(self.memory / KINDS[kind]["dir"], card)

        # supersede chain: old cards become superseded history, never deleted
        for old_id in card.supersedes:
            old = self.get(old_id)
            if old and old.status != "superseded":
                old.status = "superseded"
                self._rewrite(old)

        self._upsert(card)
        self.conn().commit()
        self._bump_stamp()
        return card

    def get(self, card_id: str) -> Card | None:
        for _, card in self.scan_cards():
            if card.id == card_id:
                return card
        return None

    def _rewrite(self, card: Card):
        directory = self.memory / KINDS.get(card.kind, KINDS["decision"])["dir"]
        target = directory / card.filename
        if not target.exists():  # filename may differ; find by id
            for p, c in self.scan_cards():
                if c.id == card.id:
                    target = p
                    break
        target.write_text(render_card(card), encoding="utf-8")
        self._upsert(card)

    def approve(self, card_id: str) -> Card | None:
        card = self.get(card_id)
        if not card:
            return None
        card.status = "active"
        self._rewrite(card)
        self.conn().commit()
        self._bump_stamp()
        return card

    def _bump_stamp(self):
        stamp = self.db_path.with_suffix(".stamp")
        stamp.parent.mkdir(parents=True, exist_ok=True)
        latest = max((p.stat().st_mtime for p in self.scan_files()), default=0)
        stamp.write_text(str(latest))

    # ---------- retrieval ----------

    def _fts_query(self, query: str) -> str:
        tokens = re.findall(r"[\w]+", query.lower())[:12]
        if not tokens:
            return ""
        and_q = " AND ".join(f'"{t}"' for t in tokens)
        or_q = " OR ".join(f'"{t}"*' for t in tokens)
        return and_q + "|" + or_q

    def search(self, query: str, path: str | None = None,
               limit: int = 5, include_drafts: bool = False) -> list[Hit]:
        self.ensure_index()
        rows = self._raw_search(query)
        now = datetime.now(timezone.utc).timestamp()
        hits: list[Hit] = []
        ranks = [abs(r[8]) for r in rows] or [1]
        max_rank = max(max(ranks), 1)

        for r in rows:
            card = self.get(r[0]) or Card(
                id=r[0], kind=r[1], title=r[2], body=r[3], author="unknown",
                date=r[6], status=r[7],
                paths=[p for p in r[4].split(",") if p],
                tags=[t for t in r[5].split(",") if t])
            if card.status == "superseded":
                continue
            if card.status == "draft" and not include_drafts:
                continue
            if path and not any(fnmatch.fnmatch(path, g) for g in card.paths):
                continue

            text_part = 1 - min(abs(r[8]) / max_rank, 1) if r[8] else 0.0
            rec_part = recency(card.date)
            path_part = path_affinity(path, card.paths)
            score = (WEIGHT_TEXT * text_part + WEIGHT_RECENCY * rec_part
                     + WEIGHT_PATH * path_part)
            hits.append(Hit(card, round(score, 4),
                            {"text": round(text_part, 2),
                             "recency": round(rec_part, 2),
                             "path": round(path_part, 2)}))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:limit]

    def _raw_search(self, query: str):
        c = self.conn()
        q = self._fts_query(query)
        if not q:
            rows = []
        elif self.fts_available:
            and_q, or_q = q.split("|")
            rows = c.execute(
                "SELECT id, kind, title, body, paths, tags, date, status, rank "
                "FROM cards WHERE cards MATCH ? ORDER BY rank LIMIT 50", (and_q,)
            ).fetchall()
            if not rows:
                rows = c.execute(
                    "SELECT id, kind, title, body, paths, tags, date, status, rank "
                    "FROM cards WHERE cards MATCH ? ORDER BY rank LIMIT 50", (or_q,)
                ).fetchall()
        else:
            term = query.split("|")[0].strip('"')
            like = "%" + term + "%"
            rows = c.execute(
                "SELECT id, kind, title, body, paths, tags, date, status, 0 "
                "FROM cards WHERE body LIKE ? OR title LIKE ? LIMIT 50",
                (like, like)).fetchall()
        return [(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7],
                 float(r[8]) if r[8] else 0.0) for r in rows]

    def all_cards(self, statuses=("draft", "active")) -> list[Card]:
        return sorted(
            (c for _, c in self.scan_cards() if c.status in statuses),
            key=lambda c: c.date,
        )

    def timeline(self, path: str | None = None) -> list[Card]:
        import fnmatch as fm
        cards = []
        for c in self.all_cards(statuses=("active", "superseded", "draft")):
            if path and not any(fm.fnmatch(path, g) for g in c.paths):
                continue
            cards.append(c)
        return cards


# ---------- scoring helpers ----------

def recency(date_iso: str, half_life_days: float = 180.0) -> float:
    try:
        d = date.fromisoformat(date_iso[:10])
    except ValueError:
        return 0.5
    age = max((date.today() - d).days, 0)
    decay = 0.5 ** (age / half_life_days)
    return 0.5 + 0.5 * decay  # never fully forget


def path_affinity(current: str | None, globs: list[str]) -> float:
    if not current:
        return 0.5  # neutral
    if any(fnmatch.fnmatch(current.replace("\\", "/"), g) for g in globs):
        return 1.0
    segs = set(re.split(r"[\\/]", current))
    best = 0.0
    for g in globs:
        overlap = len(segs & set(re.split(r"[\\/]", g))) / max(len(segs), 1)
        best = max(best, min(overlap, 0.9))
    return best
