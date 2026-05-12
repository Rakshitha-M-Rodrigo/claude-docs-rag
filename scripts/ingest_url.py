"""One-shot URL ingestion for docs-rag.

Mirrors DocsRAGServer._handle_index_url without booting MCP/stdio.
Run with the project venv:

    .venv/bin/python scripts/ingest_url.py <URL> <docset_name>

Writes to $DOCS_RAG_DIR (defaults to ~/.claude-docs-rag).
"""
import os
import sys
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from docs_rag.scraper import DocScraper
from docs_rag.chunker import MarkdownChunker, extract_keywords
from docs_rag.storage import HybridStorage


def main():
    if len(sys.argv) < 3:
        print("Usage: ingest_url.py <URL> <docset_name>", file=sys.stderr)
        sys.exit(2)

    url = sys.argv[1]
    docset_name = sys.argv[2]

    persist_dir = os.environ.get("DOCS_RAG_DIR", os.path.expanduser("~/.claude-docs-rag"))
    os.makedirs(persist_dir, exist_ok=True)

    print(f"[ingest] persist_dir={persist_dir}", file=sys.stderr)
    print(f"[ingest] fetching {url}", file=sys.stderr)

    scraper = DocScraper()
    markdown = scraper.fetch_url(url)
    title = scraper.extract_title(markdown, url)
    print(f"[ingest] title={title!r}, markdown_len={len(markdown)}", file=sys.stderr)

    chunker = MarkdownChunker(chunk_size=800, chunk_overlap=150)
    chunks = chunker.chunk_document(markdown, source=url, docset=docset_name)
    if not chunks:
        print(f"[ingest] no chunks produced for {url}", file=sys.stderr)
        sys.exit(1)
    print(f"[ingest] {len(chunks)} chunks", file=sys.stderr)

    from sentence_transformers import SentenceTransformer
    model_name = os.environ.get("DOCS_RAG_MODEL", "all-MiniLM-L6-v2")
    print(f"[ingest] loading model {model_name}", file=sys.stderr)
    model = SentenceTransformer(model_name)

    texts = [c["text"] for c in chunks]
    embeddings = model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
    print(f"[ingest] embeddings shape={embeddings.shape}", file=sys.stderr)

    storage = HybridStorage(persist_dir=persist_dir)
    docset = storage.get_or_create_docset(docset_name)
    docset.add_chunks(chunks, embeddings)

    result = {
        "status": "success",
        "docset": docset_name,
        "title": title,
        "url": url,
        "chunks_indexed": len(chunks),
        "keywords": extract_keywords(markdown)[:10],
        "persist_dir": persist_dir,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
