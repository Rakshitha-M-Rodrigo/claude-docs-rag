# Claude Docs RAG

A production-grade documentation attachment system for **Claude Code**, inspired by Cursor's `@Docs`.

**New: Auto-Trigger Mode** — The main Claude agent now automatically detects when it needs to reference docs, with **no `@docs` mention, no `/command`, and no keyword hints required**.

---

## Features

| Feature | Description |
|---------|-------------|
| **Auto-Trigger Intent Detection** | Claude silently analyzes every query to decide if docs should be consulted |
| **Hybrid Search** | BM25 keyword + dense vector semantic search with RRF fusion |
| **Contextual Chunking** | Preserves markdown headers and adds situated context |
| **Query Intelligence** | Auto-classifies queries and adjusts retrieval strategy |
| **Multi-Tier Caching** | Embedding cache, query cache, and result cache |
| **Decision Tracing** | Full audit log of why docs were or weren't retrieved |
| **Local-First** | All data stays on your machine |
| **MCP Native** | Standard MCP tools that Claude Code invokes directly |

---

## Architecture
```
User Query
↓
[docs_analyze_query] — Intent Detection Layer
↓
Confidence >= 0.5? → [docs_search] → Retrieved Chunks → Cited Answer
Confidence < 0.5?  → Answer from training data (silent)
↓
[Decision Tracer] — Logs every choice to ~/.claude-docs-rag/logs/
```


---

## Installation

### Prerequisites
- Python 3.9+
- Claude Code installed (`claude` CLI on `$PATH`) — see [Claude Code quickstart](https://docs.anthropic.com/en/docs/claude-code/quickstart)

### One-shot install

```bash
git clone https://github.com/Rakshitha-M-Rodrigo/claude-docs-rag.git
cd claude-docs-rag
./install.sh
```

That single command:

1. Creates `.venv/` (isolated from system Python).
2. `pip install -e .` so `python -m docs_rag.server` works from any cwd.
3. Pre-caches the `all-MiniLM-L6-v2` embedding model (~90 MB) so the first query is fast.
4. Registers the `docs-rag` MCP server at **user scope** in Claude Code via `claude mcp add` — available in every session.
5. Health-checks the MCP server (fails loudly if connection isn't `✓ Connected`).
6. Copies the `docs-search` skill to `~/.claude/skills/docs-search/` so auto-trigger works.

Then **restart Claude Code** so it picks up the new MCP server + skill.

### Useful Make targets

```bash
make install     # same as ./install.sh
make verify      # health-check the MCP server
make reinstall   # uninstall + install (preserves your indexed docs)
make uninstall   # remove MCP registration, venv, and skill (keeps index)
make clean       # remove .venv and build artefacts only
```

### Custom install knobs

```bash
PYTHON=python3.11 ./install.sh        # pick a specific Python
DOCS_RAG_DIR=/data/docs ./install.sh  # store the index outside ~/.claude-docs-rag
./install.sh --no-skill               # MCP only, skip the auto-trigger skill
```

### Uninstall

```bash
./uninstall.sh           # removes MCP registration + venv + skill, keeps index
./uninstall.sh --purge   # also deletes the indexed docs at ~/.claude-docs-rag
```

---

## Preloading documentation

Skip ad-hoc indexing — `scripts/docsets.yaml` defines curated reference URLs
per language/framework. Run once after install:

```bash
make preload                                   # ingest every docset in the yaml
.venv/bin/python scripts/preload.py python php # subset
.venv/bin/python scripts/preload.py --append   # add to existing chunks
```

Default behavior is **rebuild per docset**: each docset listed in the yaml is
deleted and re-ingested. Docsets not listed (e.g. one-off docsets indexed via
the MCP tool) are left untouched.

### Shipped docsets

| Docset | Source | Notes |
|---|---|---|
| `python` | docs.python.org/3 | functions, stdtypes, asyncio, typing, tutorial |
| `javascript` | MDN | Array, Object, Promise, Map, async, operators |
| `html` | MDN | form, input, table, select, global attributes |
| `java` | Oracle javadocs (JDK 21) | String, List, Map, Optional, Stream, CompletableFuture |
| `swift` | swift-book GitHub raw markdown | basics, control flow, functions, closures, concurrency |
| `php` | php.net manual | function refs (strpos, array_map, preg_match) and language refs |

### Adding your own docsets

Edit `scripts/docsets.yaml`. Pick **concrete reference / function pages**
(not chapter landing pages), and prefer **server-rendered** sites. The
current scraper has no JS engine, so SPAs like developer.android.com,
developer.apple.com, and docs.swift.org's DocC site return empty shells —
use upstream markdown sources (e.g. swift-book on GitHub) instead.



## Available MCP Tools

| Tool                                       | Purpose                                                    |
| ------------------------------------------ | ---------------------------------------------------------- |
| `docs_analyze_query(query)`                | **Auto-trigger core**: analyze if docs should be consulted |
| `docs_search(query, docset_name?, top_k?)` | Hybrid search across indexed docs                          |
| `docs_index_url(url, docset_name)`         | Scrape and index a documentation URL                       |
| `docs_index_file(file_path, docset_name)`  | Index a local file                                         |
| `docs_list_sources()`                      | List all docsets                                           |
| `docs_delete_source(docset_name)`          | Remove a docset                                            |
| `docs_stats()`                             | System statistics                                          |
| `docs_view_trace(n?, event_type?)`         | Inspect recent auto-trigger decisions                      |
| `docs_export_trace(output_path?)`          | Export decision log to JSON                                |

