"""Synapse CLI.

    synapse init                      create .memory/ skeleton + first decision card
    synapse serve                     run the MCP stdio server
    synapse search "query" [--path]   search memory (same scoring as MCP recall)
    synapse timeline [--path]         chronological walk
    synapse new <kind> "<title>"      human writes a card from a template
    synapse approve <id>              curation gate: draft -> active
    synapse supersede <id> "<title>"  replace a decision, keep history
    synapse digest [--out]            render gallery to digest.md / stdout
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import KINDS, __version__
from .cards import Card, plaque, today
from .digest import render_digest
from .store import Store

TEMPLATE = """## Context

What was the situation?

## Decision

What did you decide?

## Consequences

What does this imply going forward?
"""


def cmd_init(args) -> int:
    store = Store(args.root)
    store.memory.mkdir(parents=True, exist_ok=True)
    for spec in KINDS.values():
        (store.memory / spec["dir"]).mkdir(parents=True, exist_ok=True)
    if not store.scan_files():
        store.create(
            kind="decision",
            title="Synapse adopted as team memory",
            body=("This project uses Synapse for shared AI team memory.\n\n"
                  "- Memory lives in `.memory/` as plain markdown, versioned by git.\n"
                  "- Agents retrieve via MCP tools (`recall`, `timeline`).\n"
                  "- Agent proposals land as drafts; humans approve."),
            author=args.author,
            status="active", tags=["meta"],
        )
        print("Created .memory/ with your first decision card.")
    n = store.reindex()
    print(f"Indexed {n} cards. Ready.")
    return 0


def cmd_serve(args) -> int:
    from .server import Server
    Server(Path(args.root).resolve() if args.root else Path.cwd()).serve_forever()
    return 0


def cmd_search(args) -> int:
    store = Store(args.root)
    hits = store.search(" ".join(args.query), path=args.path, limit=args.limit)
    if not hits:
        print("No memories matched.")
        return 0
    print(("\n\n" + "-" * 60 + "\n").join(plaque(h.card, why=h.why) for h in hits))
    return 0


def cmd_timeline(args) -> int:
    store = Store(args.root)
    from .server import call_tool
    print(call_tool(store, "timeline", {"path": args.path}))
    return 0


def cmd_new(args) -> int:
    store = Store(args.root)
    card = store.create(
        kind=args.kind, title=args.title, body=TEMPLATE,
        author=args.author, paths=args.paths or ["**"], tags=args.tags or [],
        status="draft",
    )
    target = store.memory / KINDS[args.kind]["dir"] / card.filename
    print(f"Draft created: {target}")
    print(f"When done editing: synapse approve {card.id}")
    return 0


def cmd_approve(args) -> int:
    store = Store(args.root)
    card = store.approve(args.id)
    if not card:
        print(f"Not found: {args.id}", file=sys.stderr)
        return 1
    print(f"[{card.id}] approved and active: {card.title}")
    return 0


def cmd_supersede(args) -> int:
    store = Store(args.root)
    old = store.get(args.old_id)
    if not old:
        print(f"Not found: {args.old_id}", file=sys.stderr)
        return 1
    card = store.create(
        kind=old.kind, title=args.new_title, body=args.body or TEMPLATE,
        author=args.author, paths=old.paths, tags=old.tags,
        supersedes=[old.id], status="draft",
    )
    print(f"Supersession drafted: [{card.id}] replaces {old.id}")
    print(f"When done editing: synapse approve {card.id}")
    return 0


def cmd_digest(args) -> int:
    store = Store(args.root)
    text = render_digest(store)
    if args.out:
        out = Path(args.out)
        out.write_text(text, encoding="utf-8")
        print(f"Digest written to {out}")
    else:
        print(text)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="synapse", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=None, help="project root (default: cwd)")
    p.add_argument("--author", default=None, help="author name override")
    p.add_argument("--version", action="version", version=f"synapse {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init"); s.set_defaults(fn=cmd_init)
    s = sub.add_parser("serve"); s.set_defaults(fn=cmd_serve)
    s = sub.add_parser("search")
    s.add_argument("query", nargs="+")
    s.add_argument("--path", default=None)
    s.add_argument("--limit", type=int, default=5)
    s.set_defaults(fn=cmd_search)
    s = sub.add_parser("timeline"); s.add_argument("--path", default=None)
    s.set_defaults(fn=cmd_timeline)
    s = sub.add_parser("new")
    s.add_argument("kind", choices=list(KINDS))
    s.add_argument("title")
    s.add_argument("--paths", nargs="*", default=["**"])
    s.add_argument("--tags", nargs="*", default=[])
    s.set_defaults(fn=cmd_new)
    s = sub.add_parser("approve"); s.add_argument("id")
    s.set_defaults(fn=cmd_approve)
    s = sub.add_parser("supersede")
    s.add_argument("old_id")
    s.add_argument("new_title")
    s.add_argument("--body", default=None)
    s.set_defaults(fn=cmd_supersede)
    s = sub.add_parser("digest")
    s.add_argument("--out", default=None)
    s.set_defaults(fn=cmd_digest)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
