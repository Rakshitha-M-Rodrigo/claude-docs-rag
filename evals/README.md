# Evals

Quality harness for the two subsystems in `claude-docs-rag`:

| Subsystem | What it does | Metrics |
|---|---|---|
| **Intent detection** (`docs_rag.intent_detector.QueryIntentDetector`) | Binary: should we retrieve docs? + suggest a docset | accuracy, precision, recall, F1; top-1 docset routing accuracy |
| **Retrieval** (`docs_rag.retriever.DocsRetriever`) | Given a query, return top-k chunks via hybrid BM25 + vector + RRF | Hit@1, Hit@3, Hit@5, MRR, top-1 docset routing |

The harness is **local-only** and imports the system directly (no MCP transport). It evaluates logic, not transport.

## Running

```bash
make eval              # both intent + retrieval, single summary
make eval-intent       # intent only
make eval-retrieval    # retrieval only
```

Or directly:

```bash
.venv/bin/python -m evals.runners.run_all
.venv/bin/python -m evals.runners.run_intent  -v          # verbose: per-query trace
.venv/bin/python -m evals.runners.run_retrieval --no-auto-preload
```

Use a custom index location (will auto-preload into it if empty):

```bash
DOCS_RAG_DIR=/tmp/test-index .venv/bin/python -m evals.runners.run_all
```

### Auto-preload

On startup each runner checks that every docset listed in `scripts/docsets.yaml` is present and non-empty in the index (`DOCS_RAG_DIR`, default `~/.claude-docs-rag`). Any missing docset is auto-preloaded for you — no `make preload` step required.

- Pass `--no-auto-preload` to fail fast instead of preloading.
- Custom docsets indexed outside `docsets.yaml` (e.g. via the MCP tool) are left alone.
- If preload fails for any URL, the eval aborts rather than scoring against a half-loaded index.

To explicitly test the auto-preload path, blow away the index and rerun:

```bash
rm -rf ~/.claude-docs-rag
make eval                # auto-preloads all 6 docsets (~5 min first time)
```

### Output

Console: human-readable summary with metrics.

JSON: per-run artifact at `evals/results/{timestamp}_{name}.json` containing the summary and per-case details. The `evals/results/` directory is gitignored except for `.gitkeep`.

### Inspecting failures

Drill into the latest result JSON to see which queries failed and why:

```bash
.venv/bin/python -c "
import json, glob
latest = sorted(glob.glob('evals/results/*_intent.json'))[-1]
with open(latest) as f: d = json.load(f)
for det in d['result']['details']:
    if not det['correct']:
        print(f\"  FAIL: {det['query']!r}\")
        print(f\"    truth={det['needs_docs_truth']} pred={det['needs_docs_pred']} conf={det['confidence']}\")
"
```

For retrieval failures, swap `*_intent.json` for `*_retrieval.json` and filter on `det['first_hit_rank'] is None`.

## Dataset format

Datasets live in `evals/datasets/` as YAML. Both files use a top-level `cases:` list.

### `intent_cases.yaml`

```yaml
cases:
  - query: "how does asyncio.gather propagate exceptions"
    needs_docs: true
    expected_docset: python      # optional; omit for ambiguous positives
  - query: "hi"
    needs_docs: false
```

`expected_docset` is only used for routing accuracy on positives. Omit it when the query is positive but any reasonable docset would do.

### `retrieval_cases.yaml`

```yaml
cases:
  - query: "how does asyncio.gather handle exceptions"
    expected_docset: python
    expected_source_substring: "asyncio-task"
    expected_keywords: ["gather", "return_exceptions", "exception"]
```

**Scoring:** a result hits at rank `r` when result[r] satisfies BOTH:
- its `source` URL contains `expected_source_substring` (case-insensitive)
- its `text` contains ≥1 of `expected_keywords` (case-insensitive)

Two signals because URL alone is too permissive (any chunk from the right page passes) and keywords alone are too brittle.

## Layout

```
evals/
  datasets/
    intent_cases.yaml      ← ~30 labeled cases (20 positives + 10 negatives)
    retrieval_cases.yaml   ← ~20 labeled cases across the 6 shipped docsets
  runners/
    _common.py             ← bootstrap: sys.path, storage, auto-preload, IO
    run_intent.py
    run_retrieval.py
    run_all.py
  scorers/
    intent_scorer.py       ← accuracy / P / R / F1, routing accuracy
    retrieval_scorer.py    ← Hit@k, MRR, routing accuracy
  results/                 ← gitignored; per-run JSON artifacts
```

## Adding cases

1. Pick a docset and a canonical reference page already covered by `scripts/docsets.yaml`.
2. For retrieval cases, pick a URL substring distinctive enough to avoid false positives across other docsets.
3. Choose 2–4 keywords that uniquely identify the answer chunk on that page.
4. Re-run `make eval` and inspect `evals/results/*.json` to confirm the new case behaves as expected.

## Baseline (initial run, all 6 shipped docsets preloaded)

Captured on the first end-to-end run after authoring the harness. Use as a reference when judging future regressions or improvements.

| Metric | Value |
|---|---|
| **Intent** accuracy | 20/30 (66.7%) |
| **Intent** P / R / F1 | 1.000 / 0.500 / 0.667 |
| **Intent** routing (top-1) | 11/15 (73.3%) |
| **Retrieval** Hit@1 | 11/20 (55.0%) |
| **Retrieval** Hit@3 | 15/20 (75.0%) |
| **Retrieval** Hit@5 | 16/20 (80.0%) |
| **Retrieval** MRR | 0.652 |

**Notable observations:**
- Intent detector is **conservative**: precision is perfect (no false positives), but recall is 50% — many genuine doc-needing queries score below the 0.45 threshold. Particularly weak on HTML/PHP queries (the `library_ref` regex in `intent_detector.py` doesn't list them).
- The retrieval eval scores **within the expected docset** (`docset_name=case["expected_docset"]` passed to `search`). This mirrors the production path: intent detector routes → search filters. Cross-docset retrieval *without* a docset hint performs poorly (covered by the intent routing metric).

## Known cold-start quirk

`QueryIntentDetector.refresh_docset_metadata()` reads `self.storage.docsets` (a Python dict), which is only populated when `HybridStorage.get_or_create_docset(name)` is called. On a freshly-instantiated storage object (process start), this dict is empty even when ChromaDB has collections — so the detector has no docset awareness until something triggers a `get_or_create_docset`. This also affects the live MCP server on cold start until its first index operation.

The eval runner mirrors steady-state by calling `warm_up_storage()` after `ensure_docsets()`. See `evals/runners/_common.py:warm_up_storage`.

## Scope

In scope: retrieval quality, intent classification quality.

Out of scope:
- LLM-as-judge answer quality (this is a retrieval system, not a generator)
- Latency benchmarks
- CI workflows (local-only first)
- Synthetic data generation
