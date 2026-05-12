"""Scoring for retrieval evals.

A result hits at rank `r` when result[r] satisfies BOTH:
  - its `source` URL contains `expected_source_substring` (case-insensitive)
  - its `text` contains at least one of `expected_keywords` (case-insensitive)

Two signals (URL + keyword) because URL alone is too permissive (any chunk
from the right page passes) and keywords alone are too brittle (a keyword
can incidentally appear in an unrelated page).

Metrics: Hit@1, Hit@3, Hit@5, MRR. Optional docset routing accuracy when
the first hit's docset is checked against `expected_docset`.
"""
from typing import Any

DEFAULT_K_VALUES = (1, 3, 5)


def _is_hit(result: dict, expected_source_substring: str, expected_keywords: list[str]) -> bool:
    source = (result.get("source") or "").lower()
    text = (result.get("text") or "").lower()
    if expected_source_substring.lower() not in source:
        return False
    if not expected_keywords:
        return True
    return any(kw.lower() in text for kw in expected_keywords)


def score_retrieval(
    cases: list[dict],
    predictions: list[list[dict]],
    k_values: tuple[int, ...] = DEFAULT_K_VALUES,
) -> dict[str, Any]:
    """Score retrieval predictions against labeled cases.

    Args:
        cases: list of {query, expected_docset, expected_source_substring, expected_keywords}
        predictions: list of result-lists from DocsRetriever.search, same length/order as cases.
                     Each result is a dict with keys: text, source, citation, score, retriever.
        k_values: which Hit@k values to compute.

    Returns:
        dict with summary metrics + per-case detail.
    """
    if len(cases) != len(predictions):
        raise ValueError(f"cases ({len(cases)}) and predictions ({len(predictions)}) length mismatch")

    hits_at = {k: 0 for k in k_values}
    mrr_sum = 0.0
    routing_total = 0
    routing_correct = 0
    details = []

    for case, results in zip(cases, predictions):
        expected_sub = case["expected_source_substring"]
        expected_kws = case.get("expected_keywords") or []
        expected_ds = case.get("expected_docset")

        first_hit_rank = None
        for idx, res in enumerate(results):
            if _is_hit(res, expected_sub, expected_kws):
                first_hit_rank = idx + 1
                break

        for k in k_values:
            if first_hit_rank is not None and first_hit_rank <= k:
                hits_at[k] += 1

        if first_hit_rank is not None:
            mrr_sum += 1.0 / first_hit_rank

        first_docset = None
        if results:
            citation = results[0].get("citation", "")
            first_docset = citation.split(">", 1)[0].strip() if ">" in citation else citation.strip()
        if expected_ds:
            routing_total += 1
            if first_docset == expected_ds:
                routing_correct += 1

        details.append({
            "query": case["query"],
            "expected_docset": expected_ds,
            "expected_source_substring": expected_sub,
            "expected_keywords": expected_kws,
            "first_hit_rank": first_hit_rank,
            "top1_docset": first_docset,
            "top1_source": results[0].get("source") if results else None,
            "result_count": len(results),
        })

    total = len(cases)
    summary = {
        "total": total,
        "hit_at_k": {k: {"count": hits_at[k], "rate": round(hits_at[k] / total, 4) if total else 0.0}
                     for k in k_values},
        "mrr": round(mrr_sum / total, 4) if total else 0.0,
        "routing": {
            "total_with_expected_docset": routing_total,
            "correct": routing_correct,
            "accuracy": round(routing_correct / routing_total, 4) if routing_total else None,
        },
    }

    return {"summary": summary, "details": details}


def format_retrieval_report(result: dict[str, Any]) -> str:
    """Human-readable summary for stdout."""
    s = result["summary"]
    lines = [f"Retrieval eval — {s['total']} queries"]
    for k, stats in s["hit_at_k"].items():
        lines.append(f"  Hit@{k}: {stats['count']}/{s['total']} ({stats['rate']:.1%})")
    lines.append(f"  MRR:   {s['mrr']:.3f}")
    r = s["routing"]
    if r["accuracy"] is not None:
        lines.append(
            f"  docset routing (top-1): {r['correct']}/{r['total_with_expected_docset']} ({r['accuracy']:.1%})"
        )
    return "\n".join(lines)
