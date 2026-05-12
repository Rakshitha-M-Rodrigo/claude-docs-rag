"""MCP Server for Documentation RAG with implicit intent detection."""
import asyncio
import json
import os
import sys
from typing import Any, Dict, List, Optional
from pathlib import Path

import numpy as np

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .chunker import MarkdownChunker, extract_keywords
from .storage import HybridStorage
from .cache import QueryCache, EmbeddingCache
from .retriever import DocsRetriever, QueryIntelligence
from .scraper import DocScraper
from .intent_detector import QueryIntentDetector
from .tracing import DecisionTracer


class DocsRAGServer:
    """Documentation RAG MCP Server with auto-trigger intent detection."""

    def __init__(self, persist_dir: Optional[str] = None):
        if persist_dir is None:
            persist_dir = os.environ.get("DOCS_RAG_DIR", os.path.expanduser("~/.claude-docs-rag"))

        self.persist_dir = persist_dir
        os.makedirs(persist_dir, exist_ok=True)

        print(f"Initializing Docs RAG server with persist dir: {persist_dir}", file=sys.stderr)

        # Initialize components
        self.storage = HybridStorage(persist_dir=persist_dir)
        self.chunker = MarkdownChunker(chunk_size=800, chunk_overlap=150)
        self.scraper = DocScraper()
        self.query_cache = QueryCache(ttl_seconds=1800)
        self.embedding_cache = EmbeddingCache()
        self.tracer = DecisionTracer(persist_dir=persist_dir)

        # Initialize embedder (lazy load)
        self._embedder = None
        self._load_embedder()

        self.retriever = DocsRetriever(
            storage=self.storage,
            embedder=self,
            query_cache=self.query_cache,
            embedding_cache=self.embedding_cache
        )

        # Intent detector for auto-trigger
        self.intent_detector = QueryIntentDetector(storage=self.storage, embedder=self)
        self.intent_detector.refresh_docset_metadata()

        # MCP Server
        self.server = Server("docs-rag")
        self._setup_handlers()

    def _load_embedder(self):
        """Lazy load sentence transformer model."""
        if self._embedder is None:
            try:
                from sentence_transformers import SentenceTransformer
                model_name = os.environ.get("DOCS_RAG_MODEL", "all-MiniLM-L6-v2")
                print(f"Loading embedding model: {model_name}", file=sys.stderr)
                self._embedder = SentenceTransformer(model_name)
                print("Model loaded successfully", file=sys.stderr)
            except Exception as e:
                print(f"ERROR loading embedder: {e}", file=sys.stderr)
                raise

    def encode(self, texts, convert_to_numpy=True, normalize_embeddings=True):
        """Embedding interface for retriever."""
        if isinstance(texts, str):
            texts = [texts]
        return self._embedder.encode(
            texts,
            convert_to_numpy=convert_to_numpy,
            normalize_embeddings=normalize_embeddings
        )

    def _setup_handlers(self):
        @self.server.list_tools()
        async def list_tools() -> List[Tool]:
            return [
                Tool(
                    name="docs_index_url",
                    description="Index documentation from a URL. Scrapes the page, chunks it, and stores for semantic search.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "url": {"type": "string", "description": "URL to scrape and index"},
                            "docset_name": {"type": "string", "description": "Name for this documentation set (e.g., 'react-docs', 'my-api')"},
                            "title": {"type": "string", "description": "Optional title for the documentation"}
                        },
                        "required": ["url", "docset_name"]
                    }
                ),
                Tool(
                    name="docs_index_file",
                    description="Index documentation from a local file (Markdown, HTML, or plain text).",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string", "description": "Absolute path to the file"},
                            "docset_name": {"type": "string", "description": "Name for this documentation set"}
                        },
                        "required": ["file_path", "docset_name"]
                    }
                ),
                Tool(
                    name="docs_search",
                    description=(
                        "Search indexed documentation using hybrid semantic + keyword retrieval. "
                        "Call this automatically when answering questions about APIs, libraries, frameworks, "
                        "technologies, configuration, error messages, or best practices. "
                        "Do not wait for the user to explicitly ask for documentation."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search query"},
                            "docset_name": {"type": "string", "description": "Optional: restrict to specific docset"},
                            "top_k": {"type": "integer", "description": "Number of results (default 5)", "default": 5}
                        },
                        "required": ["query"]
                    }
                ),
                Tool(
                    name="docs_analyze_query",
                    description=(
                        "Analyze ANY user query to determine if indexed documentation should be consulted. "
                        "Call this SILENTLY before answering technical questions. Returns confidence score, "
                        "reasoning, and suggested docsets. If confidence >= 0.5, proceed to docs_search. "
                        "Use this to decide whether to retrieve docs without explicit user hints like '@docs' or 'documentation'."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "The user's raw query to analyze"},
                            "conversation_history": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Optional recent conversation messages for context"
                            }
                        },
                        "required": ["query"]
                    }
                ),
                Tool(
                    name="docs_list_sources",
                    description="List all indexed documentation sources with chunk counts.",
                    inputSchema={"type": "object", "properties": {}}
                ),
                Tool(
                    name="docs_delete_source",
                    description="Delete an indexed documentation source and all its chunks.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "docset_name": {"type": "string", "description": "Name of the docset to delete"}
                        },
                        "required": ["docset_name"]
                    }
                ),
                Tool(
                    name="docs_stats",
                    description="Get statistics about the docs RAG system (cache hit rates, docset counts).",
                    inputSchema={"type": "object", "properties": {}}
                ),
                Tool(
                    name="docs_view_trace",
                    description="View recent decision trace logs to understand why docs were or were not retrieved.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "n": {"type": "integer", "description": "Number of recent events to show (default 10)", "default": 10},
                            "event_type": {"type": "string", "description": "Filter by event type: intent_analysis, search, tool_call"}
                        }
                    }
                ),
                Tool(
                    name="docs_export_trace",
                    description="Export the current session trace logs to a JSON file for debugging.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "output_path": {"type": "string", "description": "Optional output file path"}
                        }
                    }
                ),
            ]

        @self.server.call_tool()
        async def call_tool(name: str, arguments: Any) -> List[TextContent]:
            try:
                if name == "docs_index_url":
                    return await self._handle_index_url(arguments)
                elif name == "docs_index_file":
                    return await self._handle_index_file(arguments)
                elif name == "docs_search":
                    return await self._handle_search(arguments)
                elif name == "docs_analyze_query":
                    return await self._handle_analyze_query(arguments)
                elif name == "docs_list_sources":
                    return await self._handle_list_sources(arguments)
                elif name == "docs_delete_source":
                    return await self._handle_delete_source(arguments)
                elif name == "docs_stats":
                    return await self._handle_stats(arguments)
                elif name == "docs_view_trace":
                    return await self._handle_view_trace(arguments)
                elif name == "docs_export_trace":
                    return await self._handle_export_trace(arguments)
                else:
                    return [TextContent(type="text", text=f"Unknown tool: {name}")]
            except Exception as e:
                import traceback
                error_msg = f"Error in {name}: {str(e)}\n{traceback.format_exc()}"
                print(error_msg, file=sys.stderr)
                self.tracer.log_tool_call(name, arguments, success=False, error=str(e))
                return [TextContent(type="text", text=f"Error: {str(e)}")]

    async def _handle_index_url(self, args: Dict) -> List[TextContent]:
        url = args["url"]
        docset_name = args["docset_name"]
        title = args.get("title", "")
        docset_name = self._sanitize_docset_name(docset_name)

        print(f"Indexing URL: {url} as docset: {docset_name}", file=sys.stderr)
        self.tracer.log_tool_call("docs_index_url", args, success=True)

        markdown = self.scraper.fetch_url(url)
        if not title:
            title = self.scraper.extract_title(markdown, url)

        chunks = self.chunker.chunk_document(markdown, source=url, docset=docset_name)
        if not chunks:
            return [TextContent(type="text", text=f"No content found at {url}")]

        texts = [c["text"] for c in chunks]
        embeddings = self.encode(texts)

        docset = self.storage.get_or_create_docset(docset_name)
        docset.add_chunks(chunks, embeddings)
        self.intent_detector.refresh_docset_metadata()

        keywords = extract_keywords(markdown)[:10]
        result = {
            "status": "success",
            "docset": docset_name,
            "title": title,
            "url": url,
            "chunks_indexed": len(chunks),
            "keywords": keywords
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    async def _handle_index_file(self, args: Dict) -> List[TextContent]:
        file_path = args["file_path"]
        docset_name = args["docset_name"]
        docset_name = self._sanitize_docset_name(docset_name)

        print(f"Indexing file: {file_path} as docset: {docset_name}", file=sys.stderr)
        self.tracer.log_tool_call("docs_index_file", args, success=True)

        content = self.scraper.fetch_local(file_path)
        chunks = self.chunker.chunk_document(content, source=file_path, docset=docset_name)
        if not chunks:
            return [TextContent(type="text", text=f"No content found in {file_path}")]

        texts = [c["text"] for c in chunks]
        embeddings = self.encode(texts)

        docset = self.storage.get_or_create_docset(docset_name)
        docset.add_chunks(chunks, embeddings)
        self.intent_detector.refresh_docset_metadata()

        result = {
            "status": "success",
            "docset": docset_name,
            "file_path": file_path,
            "chunks_indexed": len(chunks)
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    async def _handle_search(self, args: Dict) -> List[TextContent]:
        query = args["query"]
        docset_name = args.get("docset_name")
        top_k = args.get("top_k", 5)

        print(f"Search query: {query} (docset: {docset_name}, top_k: {top_k})", file=sys.stderr)

        results = self.retriever.search(query=query, docset_name=docset_name, top_k=top_k)
        self.tracer.log_search(query, docset_name, top_k, len(results), results)
        self.tracer.log_tool_call("docs_search", args, success=True)

        if not results:
            return [TextContent(type="text", text="No results found.")]

        output_lines = [f"Found {len(results)} relevant document chunks:\n"]
        for i, r in enumerate(results, 1):
            output_lines.append(f"\n--- Result {i} ---")
            output_lines.append(f"Source: {r['citation']}")
            output_lines.append(f"Relevance: {r['score']:.3f}")
            output_lines.append(f"\n{r['text']}")

        return [TextContent(type="text", text="\n".join(output_lines))]

    async def _handle_analyze_query(self, args: Dict) -> List[TextContent]:
        query = args["query"]
        history = args.get("conversation_history", [])

        print(f"Analyzing query intent: {query}", file=sys.stderr)

        result = self.intent_detector.analyze(query, conversation_history=history)
        self.tracer.log_intent_analysis(query, result)
        self.tracer.log_tool_call("docs_analyze_query", args, success=True)

        # Format as a decision card for Claude
        decision = "RETRIEVE DOCS" if result["needs_docs"] else "USE TRAINING DATA"
        output = f"""Intent Analysis Result
========================
Decision: {decision}
Confidence: {result['confidence']}
Reasoning: {result['reasoning']}
Suggested Docsets: {', '.join(result['suggested_docsets']) if result['suggested_docsets'] else 'None'}
Latency: {result['latency_ms']}ms

Instruction: If confidence >= 0.5 and suggested docsets exist, call docs_search with the original query. Otherwise answer from training data.
"""
        return [TextContent(type="text", text=output)]

    async def _handle_list_sources(self, args: Dict) -> List[TextContent]:
        docsets = self.storage.list_docsets()
        if not docsets:
            return [TextContent(type="text", text="No documentation sources indexed yet.")]

        sources = []
        for name in docsets:
            storage = self.storage.docsets.get(name)
            count = storage.count() if storage else 0
            sources.append({"docset_name": name, "chunks_indexed": count})

        self.tracer.log_tool_call("docs_list_sources", args, success=True)
        return [TextContent(type="text", text=json.dumps(sources, indent=2))]

    async def _handle_delete_source(self, args: Dict) -> List[TextContent]:
        docset_name = args["docset_name"]
        if docset_name not in self.storage.list_docsets():
            return [TextContent(type="text", text=f"Docset '{docset_name}' not found.")]

        self.storage.delete_docset(docset_name)
        self.retriever.invalidate_docset(docset_name)
        self.intent_detector.refresh_docset_metadata()
        self.tracer.log_tool_call("docs_delete_source", args, success=True)

        return [TextContent(type="text", text=f"Deleted docset '{docset_name}' and invalidated caches.")]

    async def _handle_stats(self, args: Dict) -> List[TextContent]:
        docsets = self.storage.list_docsets()
        total_chunks = sum(
            self.storage.docsets.get(name, type("X", (), {"count": lambda: 0})()).count()
            for name in docsets
        )
        trace_stats = self.tracer.get_stats()

        stats = {
            "docsets": len(docsets),
            "total_chunks": total_chunks,
            "docset_names": docsets,
            "persist_dir": self.persist_dir,
            "embedding_model": os.environ.get("DOCS_RAG_MODEL", "all-MiniLM-L6-v2"),
            "trace_stats": trace_stats,
        }
        self.tracer.log_tool_call("docs_stats", args, success=True)
        return [TextContent(type="text", text=json.dumps(stats, indent=2))]

    async def _handle_view_trace(self, args: Dict) -> List[TextContent]:
        n = args.get("n", 10)
        event_type = args.get("event_type")
        entries = self.tracer.get_recent(n=n, event_type=event_type)

        if not entries:
            return [TextContent(type="text", text="No trace entries found.")]

        lines = [f"Recent Trace Entries (last {len(entries)}):\n"]
        for entry in entries:
            ts = entry.get("timestamp", "?")
            et = entry.get("event_type", "?")
            data = entry.get("data", {})
            lines.append(f"\n[{ts}] {et}")
            if et == "intent_analysis":
                lines.append(f"  Query: {data.get('query', '?')}")
                lines.append(f"  Decision: {'RETRIEVE' if data.get('needs_docs') else 'SKIP'} (conf={data.get('confidence')})")
                lines.append(f"  Reason: {data.get('reasoning', '?')}")
            elif et == "search":
                lines.append(f"  Query: {data.get('query', '?')}")
                lines.append(f"  Results: {data.get('results_count', 0)}")
            elif et == "tool_call":
                lines.append(f"  Tool: {data.get('tool_name', '?')} | Success: {data.get('success')}")

        return [TextContent(type="text", text="\n".join(lines))]

    async def _handle_export_trace(self, args: Dict) -> List[TextContent]:
        output_path = args.get("output_path")
        path = self.tracer.export_session(output_path=output_path)
        return [TextContent(type="text", text=f"Session trace exported to: {path}")]

    def _sanitize_docset_name(self, name: str) -> str:
        import re
        sanitized = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
        return sanitized[:50]

    async def run(self):
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options(),
            )


def main():
    persist_dir = os.environ.get("DOCS_RAG_DIR")
    server = DocsRAGServer(persist_dir=persist_dir)
    asyncio.run(server.run())


if __name__ == "__main__":
    main()