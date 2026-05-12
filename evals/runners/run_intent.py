"""Run the intent-detection eval.

Usage:
    .venv/bin/python -m evals.runners.run_intent
    .venv/bin/python -m evals.runners.run_intent --no-auto-preload
    .venv/bin/python -m evals.runners.run_intent -v
"""
import sys
from pathlib import Path

from evals.runners._common import (
    REPO_ROOT,
    ensure_docsets,
    init_storage,
    load_yaml_cases,
    parse_common_args,
    write_results,
)
from evals.scorers.intent_scorer import format_intent_report, score_intent

DATASET_PATH = REPO_ROOT / "evals" / "datasets" / "intent_cases.yaml"


def run(auto_preload: bool = True, verbose: bool = False) -> dict:
    cases = load_yaml_cases(DATASET_PATH)

    storage = init_storage()
    storage = ensure_docsets(storage, auto_preload=auto_preload)

    # Embedder is needed for the semantic-similarity signal in QueryIntentDetector
    from sentence_transformers import SentenceTransformer   # noqa: E402
    import os
    model_name = os.environ.get("DOCS_RAG_MODEL", "all-MiniLM-L6-v2")
    embedder = SentenceTransformer(model_name)

    from docs_rag.intent_detector import QueryIntentDetector   # noqa: E402
    detector = QueryIntentDetector(storage=storage, embedder=embedder)
    detector.refresh_docset_metadata()

    predictions = []
    for case in cases:
        pred = detector.analyze(case["query"])
        predictions.append(pred)
        if verbose:
            mark = "✓" if bool(pred["needs_docs"]) == bool(case["needs_docs"]) else "✗"
            print(f"  {mark} [{pred['confidence']:.2f}] {case['query']!r} → needs_docs={pred['needs_docs']}, suggested={pred['suggested_docsets']}")

    result = score_intent(cases, predictions)
    print(format_intent_report(result))

    out = write_results("intent", result, extra={"dataset": str(DATASET_PATH.relative_to(REPO_ROOT))})
    print(f"\nWrote: {out.relative_to(REPO_ROOT)}")
    return result


def main():
    args = parse_common_args(sys.argv[1:])
    run(**args)


if __name__ == "__main__":
    main()
