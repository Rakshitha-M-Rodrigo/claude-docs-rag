"""Run the retrieval eval.

Usage:
    .venv/bin/python -m evals.runners.run_retrieval
    .venv/bin/python -m evals.runners.run_retrieval --no-auto-preload
    .venv/bin/python -m evals.runners.run_retrieval -v
"""
import os
import sys

from evals.runners._common import (
    REPO_ROOT,
    ensure_docsets,
    init_storage,
    load_yaml_cases,
    parse_common_args,
    write_results,
)
from evals.scorers.retrieval_scorer import format_retrieval_report, score_retrieval

DATASET_PATH = REPO_ROOT / "evals" / "datasets" / "retrieval_cases.yaml"
TOP_K = 5


def run(auto_preload: bool = True, verbose: bool = False) -> dict:
    cases = load_yaml_cases(DATASET_PATH)

    storage = init_storage()
    storage = ensure_docsets(storage, auto_preload=auto_preload)

    from sentence_transformers import SentenceTransformer   # noqa: E402
    model_name = os.environ.get("DOCS_RAG_MODEL", "all-MiniLM-L6-v2")
    embedder = SentenceTransformer(model_name)

    from docs_rag.cache import EmbeddingCache, QueryCache   # noqa: E402
    from docs_rag.retriever import DocsRetriever   # noqa: E402

    retriever = DocsRetriever(
        storage=storage,
        embedder=embedder,
        query_cache=QueryCache(),
        embedding_cache=EmbeddingCache(),
    )

    # Retrieval is evaluated WITHIN the expected docset, mirroring the
    # production path: intent detector picks a docset, search filters to it.
    # Cross-docset retrieval (no docset hint) is intentionally not tested here
    # because the intent eval already covers docset routing.
    predictions = []
    for case in cases:
        results = retriever.search(case["query"], docset_name=case["expected_docset"], top_k=TOP_K)
        predictions.append(results)
        if verbose:
            print(f"\n  query: {case['query']!r}")
            print(f"    expected: docset={case['expected_docset']}, "
                  f"source~'{case['expected_source_substring']}', "
                  f"keywords={case['expected_keywords']}")
            for i, r in enumerate(results, 1):
                print(f"    [{i}] {r['citation']}  src={r['source']}")

    result = score_retrieval(cases, predictions)
    print(format_retrieval_report(result))

    out = write_results(
        "retrieval",
        result,
        extra={"dataset": str(DATASET_PATH.relative_to(REPO_ROOT)), "top_k": TOP_K},
    )
    print(f"\nWrote: {out.relative_to(REPO_ROOT)}")
    return result


def main():
    args = parse_common_args(sys.argv[1:])
    run(**args)


if __name__ == "__main__":
    main()
