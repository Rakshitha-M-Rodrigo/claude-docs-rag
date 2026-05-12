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
User Query
↓
[docs_analyze_query] — Intent Detection Layer
↓
Confidence >= 0.5? → [docs_search] → Retrieved Chunks → Cited Answer
Confidence < 0.5?  → Answer from training data (silent)
↓
[Decision Tracer] — Logs every choice to ~/.claude-docs-rag/logs/


---

## Installation

### Prerequisites
- Python 3.9+
- Claude Code installed (`claude` CLI)

### Step 1: Clone and install

```bash
git clone https://github.com/Rakshitha-M-Rodrigo/claude-docs-rag.git claude-docs-rag
cd claude-docs-rag
pip install -e .
```

Step 2: Configure Claude Code
Copy the MCP config:
```bash
cp claude_mcp_config.json ~/.claude-code-mcp.json
```

Step 3: Install the Skill
```bash
mkdir -p ~/.claude/skills
cp -r skills/docs-search ~/.claude/skills/
```



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

