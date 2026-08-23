"""Synapse: team memory as art. Markdown cards, deterministic retrieval, MCP tools."""

__version__ = "0.1.0"

MEMORY_DIR = ".memory"
KINDS = {
    "decision": {"dir": "decisions", "prefix": "d"},
    "fact": {"dir": "facts", "prefix": "f"},
    "session": {"dir": "sessions", "prefix": "s"},
}
