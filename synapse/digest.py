"""Digest: auto-generated gallery of memory, newest first."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from .store import Store


def render_digest(store: Store) -> str:
    groups: dict[str, list] = defaultdict(list)
    for card in store.all_cards(statuses=("active", "superseded")):
        groups[card.date[:7]].append(card)  # month bucket

    out = ["# Memory Digest", ""]
    for month in sorted(groups, reverse=True):
        out.append(f"## {month}")
        out.append("")
        for c in sorted(groups[month], key=lambda x: x.date):
            flag = " (superseded)" if c.status == "superseded" else ""
            chain = f" <- {' '.join(c.supersedes)}" if c.supersedes else ""
            out.append(f"- **{c.date}** [{c.id}] {c.title}{flag}{chain}")
        out.append("")
    if len(out) == 2:
        out.append("_No approved memories yet. Record one with `synapse new`._")
    return "\n".join(out).strip() + "\n"


def write_digest(root: Path | None = None) -> Path:
    store = Store(root)
    text = render_digest(store)
    target = store.memory / "digest.md"
    target.write_text(text, encoding="utf-8")
    return target
