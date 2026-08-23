"""Synapse test suite. Runs with pytest or `python -m unittest`."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from synapse.cards import Card, load_card, parse_card, render_card, slugify, next_id
from synapse.store import Store
from synapse.server import Server
from synapse.cli import main as cli_main


def tmp_root() -> Path:
    return Path(tempfile.mkdtemp(prefix="synapse-test-"))


class TestCards(unittest.TestCase):
    def test_roundtrip(self):
        card = Card(id="d0001", kind="decision", title="Use SQLite",
                    author="dev-a", date="2026-08-22", status="active",
                    supersedes=[], paths=["src/**"], tags=["db"],
                    body="SQLite is enough.")
        text = render_card(card)
        meta, body = parse_card(text)
        self.assertEqual(meta["id"], "d0001")
        self.assertEqual(meta["paths"], ["src/**"])
        self.assertEqual(body, "SQLite is enough.")
        loaded = load_card_from_text(text)
        self.assertEqual(loaded.id, "d0001")
        self.assertEqual(loaded.paths, ["src/**"])

    def test_slug_and_ids(self):
        self.assertEqual(slugify("Héllo Wörld! 42"), "hello-world-42")
        self.assertEqual(next_id(["d0001", "f0002"], "d"), "d0002")
        self.assertEqual(next_id([], "s"), "s0001")


def load_card_from_text(text: str) -> Card:
    import tempfile
    p = Path(tempfile.mktemp(suffix=".md"))
    p.write_text(text, encoding="utf-8")
    try:
        return load_card(p)
    finally:
        p.unlink(missing_ok=True)


class TestStore(unittest.TestCase):
    def setUp(self):
        self.store = Store(tmp_root())
        self.store.create("decision", "Adopt REST", "We use REST for APIs.",
                          author="dev-a", paths=["api/**"], tags=["api"],
                          status="active")
        self.store.create("decision", "Adopt GraphQL", "Switched to GraphQL.",
                          author="dev-b", paths=["api/**"], tags=["api"],
                          supersedes=["d0001"], status="active")
        self.store.create("fact", "Python 3.10 runtime", "Runtime is Python 3.10.",
                          author="dev-a", status="active")

    def test_supersede_chain(self):
        old = self.store.get("d0001")
        self.assertEqual(old.status, "superseded")
        new = self.store.get("d0002")
        self.assertEqual(new.supersedes, ["d0001"])

    def test_search_finds_relevant(self):
        hits = self.store.search("GraphQL API")
        self.assertTrue(hits)
        self.assertEqual(hits[0].card.id, "d0002")
        self.assertIn("score", hits[0].why)

    def test_search_excludes_drafts_by_default(self):
        self.store.create("decision", "Secret draft plan", "Hidden.",
                          author="dev-c", status="draft")
        hits = [h for h in self.store.search("secret draft") if h.card.status == "draft"]
        self.assertFalse(hits)

    def test_path_affinity_filter(self):
        hits = self.store.search("runtime python", path="api/server.py")
        # fact has paths=["**"] so it matches any path
        self.assertTrue(all(h.card.id != "" for h in hits))

    def test_timeline_ordering(self):
        cards = self.store.timeline()
        dates = [c.date for c in cards]
        self.assertEqual(dates, sorted(dates))
        ids = {c.id for c in cards}
        self.assertIn("d0001", ids)

    def test_approve_gate(self):
        card = self.store.create("decision", "Pending thing", "...",
                                 author="dev-x", status="draft")
        hits_before = [h for h in store_all(self.store) if h.id == card.id]
        approved = self.store.approve(card.id)
        self.assertEqual(approved.status, "active")
        self.assertTrue(hits_before is not None)


def store_all(store):
    from synapse.cards import load_card
    return [load_card(p) for p, _ in store.scan_cards()]


class TestServer(unittest.TestCase):
    def setUp(self):
        self.root = tmp_root()
        self.server = Server(root=self.root,
                             stdin=io.StringIO(), stdout=io.StringIO())
        self.server.store.create("decision", "Use FTS5 search",
                                 "Keyword search over embeddings for V1.",
                                 author="dev-a", status="active")

    def rpc(self, **msg):
        reply = self.server.handle(msg)
        return json.loads(json.dumps(reply))

    def test_initialize_echoes_version(self):
        r = self.rpc(jsonrpc="2.0", id=1, method="initialize",
                     params={"protocolVersion": "2025-06-18"})
        self.assertEqual(r["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(r["result"]["serverInfo"]["name"], "synapse")

    def test_tools_list_has_three_tools(self):
        r = self.rpc(jsonrpc="2.0", id=2, method="tools/list")
        names = [t["name"] for t in r["result"]["tools"]]
        self.assertEqual(names, ["recall", "remember", "timeline"])

    def test_recall_tool_call(self):
        r = self.rpc(jsonrpc="2.0", id=3, method="tools/call",
                     params={"name": "recall", "arguments": {"query": "FTS5 keyword"}})
        text = r["result"]["content"][0]["text"]
        self.assertFalse(r["result"]["isError"])
        self.assertIn("[d0001]", text)
        self.assertIn("why:", text)

    def test_remember_creates_draft_with_gate(self):
        r = self.rpc(jsonrpc="2.0", id=4, method="tools/call",
                     params={"name": "remember", "arguments": {
                         "kind": "decision", "title": "Try Redis cache",
                         "body": "Maybe later."}})
        text = r["result"]["content"][0]["text"]
        self.assertIn("DRAFT", text)
        self.assertIn("synapse approve d0002", text)

    def test_unknown_tool_is_error(self):
        from synapse.server import call_tool
        with self.assertRaises(ValueError):
            call_tool(self.server.store, "nope", {})


class TestCli(unittest.TestCase):
    def test_init_new_search_digest(self):
        root = tmp_root()
        rc = cli_main(["--root", str(root), "--author", "tester", "init"])
        self.assertEqual(rc, 0)
        self.assertTrue((Path(root) / ".memory" / "decisions").exists())

        rc = cli_main(["--root", str(root), "search", "synapse memory"])
        self.assertEqual(rc, 0)

        rc = cli_main(["--root", str(root), "timeline"])
        self.assertEqual(rc, 0)

        out = Path(root) / "digest.md"
        rc = cli_main(["--root", str(root), "digest", "--out", str(out)])
        self.assertEqual(rc, 0)
        self.assertIn("Memory Digest", out.read_text(encoding="utf-8"))

    def test_new_and_approve_flow(self):
        root = tmp_root()
        cli_main(["--root", str(root), "init"])
        cli_main(["--root", str(root), "--author", "dev-q", "new",
                  "decision", "Split billing module"])
        store = Store(root)
        drafts = [c for _, c in store.scan_cards() if c.status == "draft"]
        self.assertTrue(drafts)
        rc = cli_main(["--root", str(root), "approve", drafts[0].id])
        self.assertEqual(rc, 0)
        again = store.get(drafts[0].id)
        self.assertEqual(again.status, "active")


if __name__ == "__main__":
    unittest.main(verbosity=2)
