"""Bulk-ingest documentation sources defined in scripts/docsets.yaml.

Usage:
    .venv/bin/python scripts/preload.py                    # all docsets
    .venv/bin/python scripts/preload.py python javascript  # subset
    .venv/bin/python scripts/preload.py --append python    # add to existing
    DOCS_RAG_DIR=/custom .venv/bin/python scripts/preload.py

Default behavior is DESTRUCTIVE per docset: any existing chunks in a
docset listed in docsets.yaml are deleted before re-ingesting. This makes
the preload idempotent (re-runs produce the same final state). Pass
`--append` to keep existing chunks and only add new ones.

For each URL, runs the same pipeline as the MCP `docs_index_url` tool:
fetch → chunk → embed → write to HybridStorage. Continues past per-URL
errors so one broken page doesn't abort the run. Prints a summary table
at the end and a warning for any URL that yielded suspiciously few chunks.

The `run_preload` function can also be imported and called directly
(e.g. by the eval runners to auto-load missing docsets).
"""
import os
import sys
import time
from pathlib import Path
from typing import Iterable, Optional

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from docs_rag.scraper import DocScraper
from docs_rag.chunker import MarkdownChunker
from docs_rag.storage import HybridStorage

LOW_CHUNK_WARN_THRESHOLD = 3   # warn if a URL yields fewer chunks than this


def load_config() -> dict:
    cfg_path = Path(__file__).parent / "docsets.yaml"
    with open(cfg_path) as f:
        return yaml.safe_load(f)


def run_preload(selected: Optional[Iterable[str]] = None, append: bool = False) -> int:
    """Run the preload pipeline.

    Args:
        selected: docset names to preload. None or empty = all docsets in docsets.yaml.
        append: if True, keep existing chunks in selected docsets. If False, rebuild.

    Returns:
        0 on success, non-zero on per-URL failures (matching CLI exit code).
    """
    cfg = load_config()
    docsets_cfg = cfg.get("docsets") or {}

    selected_set = set(selected) if selected else set()
    if selected_set:
        unknown = selected_set - set(docsets_cfg.keys())
        if unknown:
            print(f"Unknown docsets: {sorted(unknown)}", file=sys.stderr)
            print(f"Available: {sorted(docsets_cfg.keys())}", file=sys.stderr)
            return 2
        docsets_cfg = {k: v for k, v in docsets_cfg.items() if k in selected_set}

    persist_dir = os.environ.get("DOCS_RAG_DIR", os.path.expanduser("~/.claude-docs-rag"))
    os.makedirs(persist_dir, exist_ok=True)
    print(f"persist_dir={persist_dir}")
    print(f"docsets:    {list(docsets_cfg.keys())}")
    print(f"mode:       {'append (keep existing chunks)' if append else 'rebuild (delete existing chunks first)'}")
    print()

    scraper = DocScraper()
    chunker = MarkdownChunker(chunk_size=800, chunk_overlap=150)

    from sentence_transformers import SentenceTransformer
    model_name = os.environ.get("DOCS_RAG_MODEL", "all-MiniLM-L6-v2")
    print(f"loading embedding model: {model_name}")
    model = SentenceTransformer(model_name)

    storage = HybridStorage(persist_dir=persist_dir)
    summary = []   # (docset, url, status, chunks, body_bytes, elapsed)

    for docset_name, entry in docsets_cfg.items():
        urls = (entry or {}).get("urls") or []
        if not urls:
            print(f"[{docset_name}] no urls configured, skipping")
            continue

        print(f"\n=== {docset_name} ({len(urls)} URLs) ===")
        if not append and docset_name in storage.list_docsets():
            print(f"  (rebuilding: deleting existing '{docset_name}' docset)")
            storage.delete_docset(docset_name)
        ds = storage.get_or_create_docset(docset_name)

        for url in urls:
            t0 = time.time()
            try:
                md = scraper.fetch_url(url)
                chunks = chunker.chunk_document(md, source=url, docset=docset_name)
                if not chunks:
                    raise RuntimeError("no chunks produced")
                texts = [c["text"] for c in chunks]
                embeddings = model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
                ds.add_chunks(chunks, embeddings)
                elapsed = time.time() - t0
                status = "OK"
                if len(chunks) < LOW_CHUNK_WARN_THRESHOLD:
                    status = f"OK (low: only {len(chunks)} chunks)"
                summary.append((docset_name, url, status, len(chunks), len(md), elapsed))
                print(f"  ✓ {url}  chunks={len(chunks):3d}  body={len(md):6d}  t={elapsed:.1f}s")
            except Exception as e:
                elapsed = time.time() - t0
                summary.append((docset_name, url, f"FAIL: {type(e).__name__}: {e}", 0, 0, elapsed))
                print(f"  ✗ {url}  {type(e).__name__}: {e}")

    # ---- summary ----
    print("\n" + "=" * 72)
    print("Summary")
    print("=" * 72)
    by_docset: dict[str, dict] = {}
    for ds, url, status, chunks, body, t in summary:
        d = by_docset.setdefault(ds, {"urls": 0, "ok": 0, "fail": 0, "chunks": 0, "low": 0})
        d["urls"] += 1
        d["chunks"] += chunks
        if status.startswith("OK") and "low" not in status:
            d["ok"] += 1
        elif status.startswith("OK"):
            d["ok"] += 1
            d["low"] += 1
        else:
            d["fail"] += 1

    print(f"{'docset':12s}  {'urls':>4s}  {'ok':>3s}  {'low':>3s}  {'fail':>4s}  {'chunks':>6s}")
    total_chunks = 0
    for name, d in by_docset.items():
        print(f"{name:12s}  {d['urls']:>4d}  {d['ok']:>3d}  {d['low']:>3d}  {d['fail']:>4d}  {d['chunks']:>6d}")
        total_chunks += d["chunks"]
    print(f"{'TOTAL':12s}  {'':>4s}  {'':>3s}  {'':>3s}  {'':>4s}  {total_chunks:>6d}")

    failed = [(d, u, s) for d, u, s, _, _, _ in summary if s.startswith("FAIL")]
    if failed:
        print("\nFailures:")
        for d, u, s in failed:
            print(f"  [{d}] {u}\n      {s}")
        return 1
    return 0


def main():
    argv = sys.argv[1:]
    append_mode = False
    if "--append" in argv:
        append_mode = True
        argv = [a for a in argv if a != "--append"]
    rc = run_preload(selected=argv or None, append=append_mode)
    if rc != 0:
        sys.exit(rc)


if __name__ == "__main__":
    main()
