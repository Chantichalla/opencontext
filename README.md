# Synapse — team memory as art

Shared AI memory for development teams. Markdown cards in `.memory/`,
a deterministic SQLite/FTS5 index, and an MCP stdio server with exactly
three tools: `recall`, `remember`, `timeline`.

Zero dependencies. Python 3.10+ standard library only.

```bash
python -m synapse init        # create .memory/ skeleton + first decision card
python -m synapse serve       # run the MCP server (stdio)
python -m synapse search "why graphql"
python -m synapse timeline
python -m synapse digest      # gallery view -> .memory/digest.md
```

Wire it into any MCP client (opencode, Claude Desktop, Cursor):

```jsonc
// mcp servers config
{ "synapse": { "type": "stdio", "command": "python", "args": ["-m", "synapse", "serve"] } }
```

Agents propose memory (`remember` -> draft); humans approve (`synapse approve <id>`).
Decisions are never overwritten — they are superseded, keeping visible history.

Read `doc_ev.md` for the complete end-to-end story: why the old design failed,
the principles behind this one, every file explained, protocol details, and roadmap.
