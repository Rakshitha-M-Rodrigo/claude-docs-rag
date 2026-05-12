---
name: docs-search
description: |
  Documentation retrieval system for Claude Code. 
  Automatically activates when the user asks technical questions about APIs, libraries, frameworks, 
  configuration, error messages, or best practices. No explicit @docs or /command needed.
  
  This skill enables the main Claude agent to silently detect when documentation should be consulted,
  retrieve relevant chunks, and cite sources automatically.
triggers:
  - pattern: "@docs"
    type: mention
  - pattern: "(?i)(how (do|can|to)|what is|explain|documentation|docs|api|reference|guide|tutorial|error|exception|config|parameter|function|method|class|import|library|framework)"
    type: regex
---

# Documentation Search Skill (Auto-Trigger Mode)

## Core Principle: Implicit Detection
**Do NOT wait for the user to mention "docs", "documentation", or use @docs.** 
Instead, silently analyze EVERY user query to determine if indexed documentation is relevant.

## When to auto-trigger docs retrieval
- User asks "How do I..." about ANY technology, library, or framework
- User references a function, class, API endpoint, or configuration option
- User pastes an error message or stack trace
- User asks "What is..." about a technical concept
- User asks for code examples, best practices, or migration guides
- User mentions version numbers, deprecated features, or changelogs
- User asks about configuration files (JSON, YAML, TOML, .env)

## When NOT to use docs
- General chat ("hi", "thanks", "ok")
- Questions about the current project code (use codebase search instead)
- Opinion questions with no factual basis in docs
- Creative writing or non-technical tasks

## Auto-Trigger Workflow

### Step 1: SILENT INTENT ANALYSIS (Always do this first)
Before answering ANY technical question, call `docs_analyze_query` with the user's exact query.

This returns:
- `needs_docs`: boolean — should you retrieve docs?
- `confidence`: 0.0–1.0 — how confident is the detector?
- `reasoning`: string — why it made this decision
- `suggested_docsets`: list — which docsets to search

### Step 2: CONDITIONAL RETRIEVAL
- If `confidence &gt;= 0.5` AND `suggested_docsets` is not empty:
  → Call `docs_search` with the original query, scoped to the suggested docset if specific
- If `confidence &gt;= 0.5` but no suggested docsets:
  → Call `docs_search` without docset restriction (broad search)
- If `confidence &lt; 0.5`:
  → Answer from your training data. Do NOT mention that you skipped docs.

### Step 3: SYNTHESIZE WITH CITATIONS
- Use ONLY information from retrieved chunks
- Cite the source for every claim using the citation provided
- Include code examples exactly as shown in the docs
- If the answer is not in the retrieved chunks, say so explicitly

## Example Implicit Trigger Scenarios

**User:** "How does useEffect cleanup work?"
1. Call `docs_analyze_query` with query="How does useEffect cleanup work?"
2. Result: needs_docs=true, confidence=0.92, suggested_docsets=["react-hooks"]
3. Call `docs_search` with query="useEffect cleanup work", docset_name="react-hooks"
4. Synthesize answer with citations

**User:** "What's the weather like?"
1. Call `docs_analyze_query` with query="What's the weather like?"
2. Result: needs_docs=false, confidence=0.05
3. Answer from training data. No docs retrieved.

**User:** "claude.messages.create keeps throwing 401"
1. Call `docs_analyze_query` with query="claude.messages.create keeps throwing 401"
2. Result: needs_docs=true, confidence=0.88, suggested_docsets=["claude-api"]
3. Call `docs_search` with query="claude.messages.create 401 error"
4. Provide troubleshooting steps from docs

## Tools Reference
- `docs_analyze_query(query)` — **ALWAYS call this first for technical questions**
- `docs_search(query, docset_name?, top_k?)` — Retrieve relevant chunks
- `docs_index_url(url, docset_name)` — Add new documentation from URL
- `docs_index_file(file_path, docset_name)` — Add documentation from local file
- `docs_list_sources()` — See available docsets
- `docs_view_trace(n?)` — Inspect recent auto-trigger decisions
- `docs_export_trace()` — Export decision log for debugging

## Tracing & Debugging
If the user asks "Why did you look that up?" or "Why didn't you check the docs?":
- Call `docs_view_trace(n=5)` to show the recent intent analysis decisions
- Explain the confidence score and reasoning transparently