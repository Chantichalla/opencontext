# OpenContext Analysis & Context Architecture Report

## 1. OpenContext PRD Analysis
**OpenContext** is proposed as a shared AI memory layer for development teams using VS Code. Its primary goal is to solve the "isolated AI problem" where individual developers' AI coding sessions lack awareness of team-wide architectural decisions and current module ownership.

**Key Mechanics & Architecture:**
- **Context Injection:** Prepends shared architectural context and team decisions to AI prompts automatically, based on the file currently actively being edited.
- **Memory Types:** Project Memory (stack/conventions), Decision Memory (architectural choices manually pushed), and Task/State Memory (module ownership and presence).
- **Architecture:** 
  - **VS Code Extension (Client):** Intercepts prompts, reads a local cache, injects context.
  - **Sync Server (Backend):** Node.js + Express + SQLite, managing a JSON context store and syncing it to clients via WebSockets.
  - **Local Cache:** A lightweight JSON copy stored locally for fast, offline-tolerant reads.

---

## 2. How Context Works in Antigravity
You asked how **Antigravity** (the AI agent you are currently interacting with) gathers and uses context, and whether it relies on similarity searches.

### The Antigravity Context Model: Agentic vs. Passive
Unlike traditional AI coding tools (like standard GitHub Copilot) that rely primarily on **passive context gathering** (e.g., semantic similarity searches (RAG) over a vector database or just reading the active file window), Antigravity uses an **Agentic Context Gathering** approach.

1. **System & Ephemeral Context (Passive):**
   When a conversation starts, Antigravity is provided with your OS environment, current timestamp, workspace paths, currently active files, and cursor positions. 

2. **Active Exploration (Agentic):**
   Instead of relying on a blind vector similarity search (which often pulls in irrelevant code), Antigravity actively navigates your project like a human developer:
   - Using `list_dir`, `find_by_name`, and `grep_search` to map out the codebase.
   - Using `view_file` to read the exact lines of code needed to understand the mechanics of a module.

3. **Knowledge Discovery / KI System (Persistent Memory):**
   Antigravity uses a system called **Knowledge Items (KIs)**. After conversations, an asynchronous subagent distills learnings, architectural decisions, and patterns into markdown artifacts stored systematically in a `knowledge` directory. Before starting new research or tasks, Antigravity actively reads these KI summaries to understand the established project context—very similar to what OpenContext aims to achieve.

### Why not just Similarity Search?
While similarity search (Cosine Similarity via Embeddings) is great for "find me code that looks like this," it is terrible at answering "why did we choose to use GraphQL here?" Antigravity overcomes this by reading explicit documentation, analyzing tool outputs, and maintaining persistent knowledge artifacts, relying on active reasoning rather than just mathematical similarity.

---

## 3. Deep Research: Ways to Build the OpenContext Tool
Based on the `@[/deep-research]` workflow, here is a comprehensive analysis of how to technically build the OpenContext tool, drawing from current web paradigms regarding AI architecture extensibility.

### Option A: The Continue.dev Custom Context Provider (Recommended path)
As identified in your PRD, intercepting prompts for tools like GitHub Copilot is functionally undocumented and highly fragile. The most robust way to build OpenContext is by hooking into **Continue.dev**, an open-source AI assistant framework.

**How to implement it:**
1. **HTTP Context Provider:** Continue.dev allows you to define an `@HTTP` context provider in its configuration (`config.json` or `config.yaml`). 
2. **The Flow:** OpenContext's local VS Code extension can spin up an internal HTTP server (or the Continue config can point directly to the OpenContext local cache). When the user types a prompt, Continue.dev sends a request to this HTTP endpoint with the user's active file information.
3. **Response:** The OpenContext endpoint reads the local context `JSON`, filters out the non-relevant modules based on the file path, and returns the curated string to Continue.dev, which automatically prepends it to the LLM prompt.

### Option B: The Model Context Protocol (MCP)
A newer standard emerging in the AI tooling space is the **Model Context Protocol (MCP)** by Anthropic. MCP standardizes how AI models access external data. 
- You could build the OpenContext Sync Server as an **MCP Server**. 
- Any MCP-compatible VS Code extension (like Claude for VS Code, or potentially Cursor in the future) could natively connect to your OpenContext MCP Server to retrieve the "Decision Memory" as explicit tools or context chunks.

### Option C: Standalone VS Code Extension using Language Model APIs
If you abandon Continue.dev and build an independent extension, VS Code now natively offers APIs for AI integration:
- **Chat Participant API:** You can create a custom chat interface (`@opencontext`). When a user talks to `@opencontext`, your extension handles the prompt, reads the shared team context, and then forwards the augmented prompt to the underlying LLM.
- **Language Model API:** Allows your extension to invoke LLMs directly within VS Code, ensuring you maintain complete control over the prompt payload before it leaves the machine.

### Building the Central Synchronization Pipeline
To make the "Team Shared Memory" work seamlessly:
1. **The Sync Server (Backend):** Use a lightweight Node.js/Express server backed by SQLite to store the canonical `context.json`.
2. **WebSockets (ws):** Maintain a persistent WebSocket connection from every developer's VS Code extension to the Sync Server.
3. **Conflict Resolution:** Since AI context is eventually consistent, a simple "Last-Write-Wins" policy is acceptable for V1. When a developer triggers `OpenContext: Save Decision`, the server updates the SQLite DB and broadcasts an invalidation payload to all connected WebSocket clients, forcing their local caches to update within milliseconds.

### Conclusion
Building OpenContext is highly feasible today. The key architectural pivot is relying on **open ecosystems** (Continue.dev context providers or the Model Context Protocol) rather than trying to reverse-engineer closed systems like GitHub Copilot's prompt ingestion pipeline.
