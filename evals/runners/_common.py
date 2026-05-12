"""Shared bootstrap for eval runners.

Handles:
  - sys.path so `docs_rag` (src/) and `preload` (scripts/) are importable
  - persist_dir resolution (mirrors the MCP server)
  - storage init + lazy embedder
  - missing-docset detection vs scripts/docsets.yaml
  - auto-preload of missing docsets (skippable via --no-auto-preload)
  - YAML dataset loading
  - JSON result writing with timestamp
"""
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from docs_rag.storage import HybridStorage   # noqa: E402


def persist_dir() -> str:
    return os.environ.get("DOCS_RAG_DIR", os.path.expanduser("~/.claude-docs-rag"))


def load_yaml_cases(path: Path) -> list[dict]:
    with open(path) as f:
        data = yaml.safe_load(f)
    cases = (data or {}).get("cases") or []
    if not cases:
        raise RuntimeError(f"no cases found in {path}")
    return cases


def expected_docsets_from_yaml() -> list[str]:
    """Read docset names from scripts/docsets.yaml — the canonical preload list."""
    cfg_path = REPO_ROOT / "scripts" / "docsets.yaml"
    with open(cfg_path) as f:
        data = yaml.safe_load(f)
    return list((data or {}).get("docsets", {}).keys())


def init_storage() -> HybridStorage:
    pd = persist_dir()
    os.makedirs(pd, exist_ok=True)
    return HybridStorage(persist_dir=pd)


def missing_docsets(storage: HybridStorage, expected: list[str]) -> list[str]:
    """Return expected docsets that are absent or empty in storage."""
    present = set(storage.list_docsets())
    missing = []
    for name in expected:
        if name not in present:
            missing.append(name)
            continue
        # Treat empty docsets as missing (e.g. a previous preload failed mid-flight)
        try:
            ds = storage.get_or_create_docset(name)
            if ds.count() == 0:
                missing.append(name)
        except Exception:
            missing.append(name)
    return missing


def warm_up_storage(storage: HybridStorage) -> None:
    """Populate storage.docsets dict for every present collection.

    Why: HybridStorage tracks docsets via ChromaDB collections (list_docsets)
    AND a Python dict (self.docsets). The dict is only populated when
    get_or_create_docset(name) is called. On a fresh process, this dict
    is empty even when Chroma has collections — which breaks
    QueryIntentDetector.refresh_docset_metadata (it reads self.storage.docsets).
    Warming up here matches the steady-state the running MCP server reaches
    after any index/search operation.
    """
    for name in storage.list_docsets():
        storage.get_or_create_docset(name)


def ensure_docsets(storage: HybridStorage, auto_preload: bool) -> HybridStorage:
    """Verify all expected docsets are present and non-empty; preload missing ones if allowed.

    Returns a (possibly fresh) HybridStorage with its docsets dict warmed up.
    After preload runs, ChromaDB collections are re-listed via a new HybridStorage
    instance to avoid stale collection handles.
    """
    expected = expected_docsets_from_yaml()
    missing = missing_docsets(storage, expected)
    if missing:
        if not auto_preload:
            print(
                f"ERROR: missing docsets {missing} and --no-auto-preload was passed.\n"
                f"Run `make preload` to load them.",
                file=sys.stderr,
            )
            sys.exit(2)

        print(f"Preloading missing docsets: {missing}")
        print("(this calls scripts/preload.py for the missing docsets only)\n")
        from preload import run_preload   # imported lazily so preload's heavy deps load only when needed
        rc = run_preload(selected=missing, append=False)
        if rc != 0:
            print(f"\nERROR: preload returned non-zero exit code {rc}; aborting eval.", file=sys.stderr)
            sys.exit(rc)

        # Re-init storage to pick up newly created collections cleanly
        storage = init_storage()

    warm_up_storage(storage)
    return storage


def write_results(name: str, result: dict[str, Any], extra: Optional[dict[str, Any]] = None) -> Path:
    out_dir = REPO_ROOT / "evals" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    out_path = out_dir / f"{stamp}_{name}.json"
    payload = {
        "timestamp": stamp,
        "name": name,
        "result": result,
    }
    if extra:
        payload.update(extra)
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return out_path


def parse_common_args(argv: list[str]) -> dict[str, Any]:
    """Tiny arg parser to avoid argparse boilerplate in 3 runners."""
    return {
        "auto_preload": "--no-auto-preload" not in argv,
        "verbose": "-v" in argv or "--verbose" in argv,
    }
