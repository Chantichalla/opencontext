"""Synapse MCP server: JSON-RPC 2.0 over stdio, zero dependencies.

Exposes exactly three tools -- the whole API surface:
    recall(query, path?, limit?)   deterministic retrieval with score explanations
    remember(kind, title, body, ..) agent proposes; human approves (curation gate)
    timeline(path?)                chronological walk with supersede chains

Protocol notes:
- Messages are newline-delimited JSON (MCP stdio transport).
- initialize -> echo the client's requested protocolVersion.
- All output is compact markdown plaques with citations.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from . import __version__
from .store import Store
from .cards import plaque

PROTOCOL_VERSION = "2024-11-05"


def _author() -> str:
    return (os.environ.get("SYNAPSE_AUTHOR")
            or os.environ.get("USERNAME")
            or os.environ.get("USER")
            or "unknown")


def tool_specs() -> list[dict]:
    return [
        {
            "name": "recall",
            "description": (
                "Search the team's shared memory for decisions, facts and session "
                "notes relevant to a query. Deterministic scoring; every hit "
                "explains why it surfaced. Use before answering questions about "
                "'why/how/when' of the project."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What you want to remember"},
                    "path": {"type": "string", "description": "Current file path for affinity filtering"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": ["query"],
            },
        },
        {
            "name": "remember",
            "description": (
                "Propose a memory card (decision/fact/session). Created as 'draft'; "
                "a human must approve via `synapse approve <id>`. Never overwrite "
                "existing cards -- supersede them instead."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["decision", "fact", "session"]},
                    "title": {"type": "string"},
                    "body": {"type": "string", "description": "Context, decision, consequences"},
                    "author": {"type": "string"},
                    "paths": {"type": "array", "items": {"type": "string"}, "description": "Globs where relevant"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "supersedes": {"type": "array", "items": {"type": "string"}},
                    "status": {"type": "string", "enum": ["draft", "active"]},
                },
                "required": ["kind", "title", "body"],
            },
        },
        {
            "name": "timeline",
            "description": (
                "Walk the project's decision history chronologically, including "
                "supersession chains. Use for onboarding or understanding how a "
                "module evolved."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Filter by path glob"},
                },
            },
        },
    ]


def call_tool(store: Store, name: str, args: dict) -> str:
    if name == "recall":
        hits = store.search(
            args.get("query", ""),
            path=args.get("path"),
            limit=int(args.get("limit", 5)),
        )
        if not hits:
            return "No memories matched. Try broader terms, or check `timeline`."
        return "\n\n".join(plaque(h.card, why=h.why) for h in hits)

    if name == "remember":
        card = store.create(
            kind=args["kind"],
            title=args["title"],
            body=args["body"],
            author=args.get("author") or _author(),
            paths=args.get("paths"),
            tags=args.get("tags"),
            supersedes=args.get("supersedes"),
            status=args.get("status", "draft"),
        )
        gate = ("Status: DRAFT - waiting for human approval:\n"
                f"  synapse approve {card.id}"
                if card.status == "draft" else "Status: active.")
        return plaque(card, why=gate)

    if name == "timeline":
        cards = store.timeline(args.get("path"))
        if not cards:
            return "Memory is empty. Run `synapse init` and record your first decision."
        lines = [f"{c.date}  [{c.id}] {c.status:<10} {c.title} ({c.kind})"
                 for c in sorted(cards, key=lambda c: c.date)]
        return "TIMELINE\n" + "\n".join(lines)

    raise ValueError(f"Unknown tool: {name}")


class Server:
    def __init__(self, root: Path | None = None, stdin=None, stdout=None):
        self.store = Store(root)
        self.stdin = stdin or sys.stdin
        self.stdout = stdout or sys.stdout

    def _send(self, payload: dict):
        self.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.stdout.flush()

    def handle(self, msg: dict) -> dict | None:
        method = msg.get("method", "")
        mid = msg.get("id")
        params = msg.get("params") or {}

        if method == "initialize":
            version = params.get("protocolVersion", PROTOCOL_VERSION)
            return {
                "jsonrpc": "2.0", "id": mid,
                "result": {
                    "protocolVersion": version,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "synapse", "version": __version__},
                },
            }
        if method.startswith("notifications/"):
            return None
        if method == "ping":
            return {"jsonrpc": "2.0", "id": mid, "result": {}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": mid, "result": {"tools": tool_specs()}}
        if method == "tools/call":
            try:
                text = call_tool(self.store, params["name"], params.get("arguments") or {})
                result = {"content": [{"type": "text", "text": text}], "isError": False}
            except Exception as e:  # noqa: BLE001 - report errors to client
                result = {"content": [{"type": "text", "text": f"error: {e}"}], "isError": True}
            return {"jsonrpc": "2.0", "id": mid, "result": result}

        if mid is not None:
            return {"jsonrpc": "2.0", "id": mid,
                    "error": {"code": -32601, "message": f"Method not found: {method}"}}
        return None

    def serve_forever(self):
        for line in self.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                self._send({"jsonrpc": "2.0", "id": None,
                            "error": {"code": -32700, "message": "Parse error"}})
                continue
            reply = self.handle(msg)
            if reply is not None:
                self._send(reply)
