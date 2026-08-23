# Synapse Build Documentation (doc_ev.md)

**Read this top-to-bottom and you understand the entire project: why it exists,
how every piece works, and how to use it.**

---

## 0. TL;DR

Synapse is **shared AI team memory**: plain markdown cards in `.memory/`,
indexed by SQLite/FTS5, served to AI agents over MCP with exactly three tools
(`recall`, `remember`, `timeline`). Zero dependencies (Python 3.10+ stdlib).
Agents propose memory; humans approve. Decisions are never overwritten — they
are superseded, keeping visible history like museum plaques.

```bash
python -m synapse init      # one-time setup per project
python -m synapse serve     # MCP server (stdio) — point any MCP client at this
```

---

## 1. History: what was here before, and why it was deleted

This repo (`opencontext`) previously held 13 planning documents (~10 weeks of
phased roadmaps) for an earlier "Synapse" design. They were all talk and no
code, and they contradicted each other:

| Question | Doc A said | Doc B said |
|---|---|---|
| Language | TypeScript + Drizzle | Python/FastAPI ("or Go if you're serious") |
| Database | PostgreSQL + Redis | SQLite + FTS5 |
| Search | OpenAI embeddings default-ON | "Ditch vector search" → LanceDB anyway |
| Delivery | Continue.dev @HTTP + custom VS Code ext | MCP mandatory, zero frontend |
| Sync | WebSocket broadcast of one giant JSON blob | SSE via MCP |

Concrete technical bugs found in those plans included an invalid `git log`
invocation that broke on first run, `vi.fn()` used without import, an Express
auth middleware inside a stdio JSON-RPC design, a redactor whose `/token/i`
pattern would flag nearly every AI-related memory as sensitive, type errors in
the relevance pipeline (`item.relevanceScore` didn't exist), and a listener
leak in the sync manager. The single most important artifact — the actual V1
implementation plan — lived in a gitignored folder.

**Lesson recorded as principle zero:** a tool that records decisions must have
its own decision record. Hence card `d0001`.

### What was kept from the old plans
- MCP is mandatory (write zero frontend code).
- FTS5 keyword search beats vector search at team scale (<10k memories).
- Three-tier memory: ephemeral / structured / knowledge.
- Agentic pull beats blind auto-injection.
- Real-time freshness matters; Git commits are too slow *for notifications*.

### What was inverted
- Old: central server holds canonical state (Postgres/Redis/SQLite-in-cloud).
  New: **the git repo holds truth; the network only carries invalidation pings.**
- Old: inject context into every prompt (100% injection success metric!).
  New: agent pulls via tools; nothing is injected silently.
- Old: LLM rewrites memory continuously ("Librarian").
  New: agent drafts, human approves. One gate kills hallucination drift.

---

## 2. Design principles (the "art")

1. **One truth, boring storage.** Memory is markdown under `.memory/`.
   Readable with `cat`, diffable by git, mergeable by humans. SQLite is a
   derived index — delete `.memory/.index.db` and it rebuilds losslessly.
2. **Push notifications, pull truth.** Optional hub (`synapse/hub.py`)
   broadcasts "cache invalidated" events but stores nothing.
3. **Agentic pull, minimal injection.** Exactly three tools. Every result
   carries a citation and a score explanation.
4. **Deterministic retrieval.** No embeddings in V1. Score = text + recency +
   path-affinity. Explainable, reproducible, sub-millisecond.
5. **Curation gate.** Agent-written cards land as `draft`; a human runs
   `synapse approve <id>`. History is append-only via supersession chains.

---

## 3. Architecture

```
                ┌──────────────────────────────────────────┐
                │            YOUR PROJECT REPO             │
                │                                          │
                │   .memory/                               │
                │   ├── decisions/  d0001-use-x.md         │   ← TRUTH
                │   ├── facts/      f0001-runtime.md       │   (plain markdown,
                │   ├── sessions/   s20260822-....md       │    versioned by git)
                │   └── .index.db / .index.stamp           │   ← derived index
                │        ▲                                 │
                │        │ reads/writes                    │
                │   ┌────┴─────┐                           │
                │   │  Store   │  SQLite + FTS5            │
                │   └────┬─────┘                           │
                │        │ search/create/timeline          │
                │   ┌────▼──────────────┐                  │
                │   │  MCP stdio server │◄──── AI agent    │
                │   │  recall remember  │      (opencode,  │
                │   │  timeline         │   Claude, etc.)  │
                │   └───────────────────┘                  │
                └──────────────────────────────────────────┘

   optional: hub.py (SSE) ── "cache invalidated" pings between machines
                             (carries NO truth, ~100 lines, stdlib)
```

Data flow of a decision:
`human/agent writes → draft card (.md) → git commit → approve → active →
FTS5 index rebuilt lazily → agents recall it with citations forever after.`

---

## 4. File-by-file walkthrough

```
synapse/
├── __init__.py    constants: MEMORY_DIR, KINDS (dir + id prefix per kind)
├── __main__.py    enables `python -m synapse`
├── cards.py       Card dataclass, frontmatter parse/render, plaques, ids
├── store.py       Store class: scan/reindex/search/timeline/approve + scoring
├── digest.py      renders .memory/digest.md gallery grouped by month
├── server.py      JSON-RPC 2.0 over stdio: initialize/tools/list/tools/call
├── cli.py         argparse CLI: init serve search timeline new approve supersede digest
└── hub.py         optional SSE invalidation broadcaster (stdlib http.server)
tests/
└── test_synapse.py 15 unit tests (cards/store/server/cli), unittest-compatible
doc_ev.md           this file
README.md           quickstart
```

### 4.1 `cards.py` — the plaque format
A card = YAML-ish frontmatter + markdown body. The parser needs no PyYAML:
values are tried as JSON first (so lists work), else comma-split, else raw.

Fields: `id, kind, title, author, date, status, supersedes[], paths[], tags[]`.
- `status`: `draft → active`, or `superseded` (never deleted).
- `paths`: glob list for path-affinity (`["src/api/**"]`, `"**"` = everywhere).
- `supersedes`: ids of cards this one replaces.

`plaque(card, why)` renders the compact form agents see:

```
[d0002] Adopt GraphQL (decision, active, 2026-08-22, by dev-b) · supersedes d0001
paths: api/**
why: score 0.83 (text 0.92 x0.6 + recency 1.00 x0.25 + path 1.00 x0.15)
<body>
```

IDs: `next_id()` gives smallest unused number per prefix (`d0003`); sessions
use date-slugs (`s20260822-auth-work`). Filenames are `id-slug.md`.

### 4.2 `store.py` — truth + derived index
- `scan_cards()` walks `**/*.md` — the source of truth read.
- `reindex()` rebuilds FTS5 table `cards(id, kind, title, body, paths, tags,
  date, status)`. `ensure_index()` compares newest file mtime against a stamp;
  rebuilds only when stale (cheap, automatic).
- Graceful degradation: if the Python build lacks FTS5, falls back to LIKE.
- `search(query, path, limit)`:
  1. tokenize query → quoted AND query; fallback to OR-prefix if empty;
  2. hydrate full cards from disk (index never lies about content);
  3. skip superseded; hide drafts unless asked;
  4. filter by path glob when given;
  5. score each hit (below), sort, cut.
- `create(...)` writes the file, flips old cards to `superseded`, upserts index.
- `timeline(path)` returns chronological cards including superseded history.

### 4.3 Scoring — deterministic and explainable
```
score = 0.60·text + 0.25·recency + 0.15·path
text    = 1 − |bm25 rank| / max_rank_in_resultset
recency = 0.5 + 0.5 · 0.5^(age_days / 180)      # half-life 180d, never 0
path    = 1.0 glob match | segment-overlap ≤0.9 | 0.5 neutral (no path given)
```
Every hit prints its own breakdown — retrieval you can argue with.

### 4.4 `server.py` — the whole API surface
Newline-delimited JSON-RPC 2.0 over stdio (MCP standard transport):
- `initialize` → echoes client's requested protocolVersion (compat-safe),
  advertises `{tools:{}}`.
- `notifications/*` → no reply (per spec).
- `tools/list` → three schemas (recall / remember / timeline).
- `tools/call` → dispatches into Store; errors returned as `isError:true`
  results, never as crashes.
Author identity comes from `SYNAPSE_AUTHOR` env, then `USERNAME`/`USER`.

### 4.5 `cli.py` — human rituals
| Command | Meaning |
|---|---|
| `synapse init` | create `.memory/{decisions,facts,sessions}` + seed card d0001 |
| `synapse serve` | start MCP server on stdin/stdout |
| `synapse search "q" [--path p] [--limit n]` | same scoring as `recall` |
| `synapse timeline [--path p]` | chronological walk |
| `synapse new <kind> "<title>"` | human drafts a card from template |
| `synapse approve <id>` | curation gate: draft → active |
| `synapse supersede <old> "<new title>"` | replace, keep history |
| `synapse digest [--out f]` | monthly gallery → `.memory/digest.md` |

### 4.6 `hub.py` — realtime without authority
GET `/events` (SSE stream) · POST `/notify?who=dev-a` (broadcast invalidate) ·
GET `/health`. Holds connections open; cleans dead writers on OSError.
Run one instance anywhere (`python -m synapse.hub 7610`).

---

## 5. Usage end-to-end

### Human setup (once per repo)
```bash
python -m synapse init --author yourname
git add .memory && git commit -m "adopt synapse memory"
```

### Wire an agent (any MCP client)
```jsonc
{ "mcpServers": { "synapse":
    { "command": "python", "args": ["-m", "synapse", "serve"] } } }
```
Now the agent can call `recall("why did we drop jwt")`, propose
`remember(kind="decision", ...)`, and walk `timeline(path="src/api/**")`.

### The daily loop
1. Agent finishes a task → proposes a decision card (draft).
2. You edit the file if needed → `synapse approve d0007`.
3. Commit. Everyone's next `recall` sees it. No server, no lock-in.
4. Changed your mind later? `synapse supersede d0007 "New direction"` —
   history stays visible.

---

## 6. Testing & verification performed during this build

| Check | Result |
|---|---|
| `python -m unittest discover -s tests` | **15/15 OK** |
| Card roundtrip (render→parse→load) | OK |
| Supersede chain flips old card status | OK |
| Drafts hidden from search until approved | OK |
| Timeline sorted chronologically | OK |
| MCP handshake echoes client protocolVersion | OK |
| `tools/list` returns exactly 3 tools | OK |
| `recall` returns plaque + why-line | OK |
| `remember` creates draft + approval hint | OK |
| CLI init→search→timeline→digest flow | OK |
| Stdio smoke test (piped JSON-RPC session) | OK |
| Hub health + notify broadcast | OK |
| Bug found & fixed during smoke: `Path(None)` when `--root` omitted in `cmd_serve` | fixed |

Run everything yourself:
```bash
python -m unittest discover -s tests -v
```

---

## 7. Build log (what was done, in order)

1. Audited old repo: 13 docs, contradictions catalogued, zero code.
2. Deleted all planning artifacts (`plan.md`, `*_architecture*.md`,
   `synapse_*.{md,html}`, `tech_stack.md`, `decode/`).
3. Verified toolchain: Python 3.10.11 available.
4. Chose pure-stdlib Python (zero deps = zero-config, offline, portable).
5. Wrote `cards.py` (format + plaques), `store.py` (FTS5 + scoring),
   `server.py` (MCP), `cli.py` (rituals), `digest.py` (gallery),
   `hub.py` (optional realtime), `__main__.py`.
6. Wrote 15 tests; fixed an f-string syntax bug and a test-side import;
   fixed the `--root None` crash found in live smoke test.
7. Dogfooded: ran `synapse init` in this repo — `.memory/decisions/d0001`
   records the adoption itself.
8. Smoke-tested the full MCP session over stdio pipes.
9. Updated `.gitignore` (derived index ignored, markdown committed),
   wrote README + this document.

---

## 8. Roadmap (deliberately short)

- **When >10k memories or synonym failures hurt:** add embedding search as a
  *fourth* score component behind the same explainable interface.
- **When two machines fight over edits:** run hub.py; conflicts still resolve
  in git, hub only speeds awareness.
- **Maybe someday:** `synapse onboard <path>` guided tour; editor sidebar.

Not planned, on purpose: Postgres, Redis, vector DBs in V1, background LLM
rewriters, prompt auto-injection, custom IDE extensions.

---

## 9. Glossary

- **Card** — one markdown memory with frontmatter (the atomic unit).
- **Plaque** — compact rendering of a card shown to agents/humans.
- **Supersede** — replace a decision while keeping the old visible.
- **Curation gate** — drafts require explicit human approval.
- **Invalidation ping** — hub event saying "re-read git", carrying no data.
