---
id: d0001
kind: decision
title: Synapse adopted as team memory
author: ox-alpha
date: 2026-08-22
status: active
supersedes: []
paths: ["**"]
tags: ["meta"]
---

This project uses Synapse for shared AI team memory.

- Memory lives in `.memory/` as plain markdown, versioned by git.
- Agents retrieve via MCP tools (`recall`, `timeline`).
- Agent proposals land as drafts; humans approve.
