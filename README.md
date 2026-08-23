<div align="center">

# 🧠 Synapse

**Team memory as art — shared AI memory that humans curate and agents query.**

Markdown cards in `.memory/` · a deterministic SQLite/FTS5 index · an MCP stdio server
with exactly three tools.

*Zero dependencies. Python 3.10+ standard library only.*

[Quickstart](#-quickstart) · [MCP setup](#-wire-up-your-ai-agents) · [How it works](#-how-it-works) · [Design principles](#-design-principles) · [Roadmap](#-roadmap)

</div>

---

## Why

AI coding agents forget everything between sessions, and the knowledge they do
accumulate is trapped per-tool, per-developer. Context documents rot; wikis go
unread; nobody writes ADRs.

**Synapse** is a shared, versioned memory layer that sits between your team and
every AI agent you use:

- **Humans stay in control** — agents can only *propose* memories; a human approves them.
- **Decisions are never overwritten** — they are *superseded*, keeping visible history.
- **Retrieval is deterministic and explainable** — every result tells you *why* it surfaced.
- **Plain markdown is the truth** — `cat` any card, diff it in git, read it in 10 years.

No database server. No API keys. No vendor. Just files and an index you can rebuild anytime.

## ⚡ Quickstart

```bash
python -m synapse init        # create .memory/ skeleton + first decision card
python -m synapse serve       # run the MCP server (stdio)
```

Human rituals:

```bash
python -m synapse search "why graphql"   # same scoring as MCP recall
python -m synapse timeline               # chronological walk with supersede chains
python -m synapse new decision "Split billing module"   # write a card from template
python -m synapse approve d0002          # curation gate: draft -> active
python -m synapse supersede d0002 "New billing design"  # replace, keep history
python -m synapse digest                 # gallery view -> .memory/digest.md
```

Requires Python **3.10+**. That's it — no `pip install`.

## 🔌 Wire up your AI agents

Any MCP client works — opencode, Claude Desktop, Cursor, VS Code:

```jsonc
// mcp servers config
{
  "synapse": {
    "type": "stdio",
    "command": "python",
    "args": ["-m", "synapse", "serve"]
  }
}
```

Your agent now gets exactly three tools:

| Tool | What it does |
|---|---|
| `recall(query, path?, limit?)` | Deterministic retrieval with score explanations |
| `remember(kind, title, body, …)` | Agent *proposes* a card → lands as **draft**, human approves |
| `timeline(path?)` | Chronological walk with supersession chains |

## 🏛 How it works

```
┌──────────────────────────────────────────────────────────────┐
│                        your repository                       │
│                                                              │
│   .memory/  ◄─────── the truth (plain markdown, git-         │
│      ├── decisions/     versioned; human-readable forever)   │
│      ├── facts/                                          ▲   │
│      ├── sessions/            synapse serve              │   │
│      └── digest.md            (JSON-RPC 2.0 over stdio)  │   │
│                               ┌──────────────────┐       │   │
│   .index.db  ◄─ rebuildable   │   MCP stdio      ├───────┘   │
│   (derived, never             │   server         │  AI agent │
│    the source of              └────────┬─────────┘           │
│     truth)                             ▼                     │
│                              SQLite + FTS5 index             │
└──────────────────────────────────────────────────────────────┘
```

### The card

The atomic unit is a *museum plaque*: human-readable with `cat`, parseable
without dependencies, versioned by git.

```markdown
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
```

### Retrieval you can trust

Every result carries its own explanation:

```
[d0001] Synapse adopted as team memory (decision, active, 2026-08-23, by tester)
why: score 0.93 (text 1.00 x0.60 + recency 1.00 x0.25 + path 0.50 x0.15)
```

```
score = 0.60 × text_relevance   (BM25 via FTS5)
      + 0.25 × recency          (180-day half-life, never fully forgotten)
      + 0.15 × path_affinity    (does this card care about the file you're in?)
```

Deterministic, tunable, and honest — no black-box embeddings required.

## ✨ Design principles

1. **Curation over capture.** Memory without a gate becomes noise. Agents propose;
   humans approve (`synapse approve`). Nothing enters shared memory silently.
2. **History is sacred.** Decisions are superseded, never overwritten or deleted.
   Every card keeps its supersession chain — memory as an audit trail.
3. **Files are truth.** `.memory/` is plain markdown under git. The SQLite index
   is derived and rebuildable at any time (`python -m synapse init`).
4. **Zero dependencies.** Python stdlib only. If it doesn't run on a fresh
   laptop offline, it doesn't ship.
5. **Explainable retrieval.** No result without its reasoning.

## 📁 Project layout

```
synapse/
├── cards.py    # Card model, frontmatter parse/render, plaque formatting
├── store.py    # SQLite/FTS5 index, scoring, supersede logic
├── server.py   # MCP server: JSON-RPC 2.0 over stdio (~190 lines)
├── cli.py      # Human rituals: init, approve, supersede, search, digest
├── digest.py   # Gallery view generator
├── hub.py      # Multi-repo aggregation helpers
└── __main__.py # python -m synapse entry point
tests/          # 15 unit tests, zero mocking gymnastics
doc_ev.md       # The complete design story: why v0 failed, principles, protocol details
```

## 🗺 Roadmap

- [ ] **v2 ranking**: FTS5 per-column weights + synonym/stemming expansion
- [ ] **Usage reinforcement**: memories strengthen when retrieved, decay when ignored
- [ ] **Duplicate guard**: warn agents when a similar card already exists
- [ ] **Graph retrieval**: `related:` links + SQLite recursive-CTE traversal
  (Graphiti-style multi-hop queries — no Neo4j required)
- [ ] **`synapse doctor`**: lint cards for broken frontmatter and dangling links
- [ ] **Episodic consolidation**: opt-in summarization of session cards into drafts
- [ ] **Optional semantic search**: embeddings behind an optional dependency flag

See [`doc_ev.md`](doc_ev.md) for the full end-to-end story of how this design came to be.

## 🤝 Contributing

```bash
git clone https://github.com/Chantichalla/opencontext.git
cd opencontext
python -m unittest discover -s tests -v
```

PRs welcome — especially ones that keep the zero-dependency promise.

---

<div align="center">

*Memory is too important to be automatic. Curate it.*

</div>
