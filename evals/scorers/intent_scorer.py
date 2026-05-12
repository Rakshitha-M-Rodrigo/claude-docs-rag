"""Scoring for intent-detection evals.

Two metrics:
  1. Binary classification on `needs_docs` (positive = "docs needed"):
     accuracy, precision, recall, F1.
  2. Top-1 docset routing accuracy on positive cases that specify an
     expected_docset (a positive case may omit it, e.g. ambiguous queries
     where any retrieval is acceptable).
"""
from typing import Any


def score_intent(cases: list[dict], predictions: list[dict]) -> dict[str, Any]:
    """Score intent predictions against labeled cases.

    Args:
        cases: list of {query, needs_docs, expected_docset?}
        predictions: list of {needs_docs, suggested_docsets, confidence, ...}
                     Same length and order as `cases`.

    Returns:
        dict with summary metrics + per-case detail.
    """
    if len(cases) != len(predictions):
        raise ValueError(f"cases ({len(cases)}) and predictions ({len(predictions)}) length mismatch")

    tp = fp = tn = fn = 0
    routing_total = 0
    routing_correct = 0
    details = []

    for case, pred in zip(cases, predictions):
        truth = bool(case["needs_docs"])
        guess = bool(pred["needs_docs"])

        if truth and guess:
            tp += 1
        elif not truth and guess:
            fp += 1
        elif not truth and not guess:
            tn += 1
        else:
            fn += 1

        expected_ds = case.get("expected_docset")
        suggested = pred.get("suggested_docsets") or []
        top1 = suggested[0] if suggested else None
        routing_hit = None
        if truth and expected_ds:
            routing_total += 1
            routing_hit = (top1 == expected_ds)
            if routing_hit:
                routing_correct += 1

        details.append({
            "query": case["query"],
            "needs_docs_truth": truth,
            "needs_docs_pred": guess,
            "correct": truth == guess,
            "expected_docset": expected_ds,
            "predicted_top1_docset": top1,
            "routing_hit": routing_hit,
            "confidence": pred.get("confidence"),
        })

    total = tp + fp + tn + fn
    accuracy = (tp + tn) / total if total else 0.0
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    routing_acc = (routing_correct / routing_total) if routing_total else None

    return {
        "summary": {
            "total": total,
            "accuracy": round(accuracy, 4),
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "confusion": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
            "routing": {
                "total_positives_with_expected_docset": routing_total,
                "correct": routing_correct,
                "accuracy": round(routing_acc, 4) if routing_acc is not None else None,
            },
        },
        "details": details,
    }


def format_intent_report(result: dict[str, Any]) -> str:
    """Human-readable summary for stdout."""
    s = result["summary"]
    c = s["confusion"]
    lines = [
        f"Intent eval — {c['tp'] + c['tn']}/{s['total']} correct ({s['accuracy']:.1%})",
        f"  needs_docs:  P={s['precision']:.3f}  R={s['recall']:.3f}  F1={s['f1']:.3f}",
        f"  confusion:   TP={c['tp']}  FP={c['fp']}  TN={c['tn']}  FN={c['fn']}",
    ]
    r = s["routing"]
    if r["accuracy"] is not None:
        lines.append(
            f"  docset routing (top-1, positives only): "
            f"{r['correct']}/{r['total_positives_with_expected_docset']} ({r['accuracy']:.1%})"
        )
    else:
        lines.append("  docset routing: n/a (no positives with expected_docset, or docsets unloaded)")
    return "\n".join(lines)
