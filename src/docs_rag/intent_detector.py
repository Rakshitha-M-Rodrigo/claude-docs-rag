"""Query intent detection for automatic docs retrieval."""
import re
import json
import time
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path
import numpy as np


class QueryIntentDetector:
    """Detects when a user query needs documentation lookup without explicit hints."""

    # Patterns that strongly suggest documentation need
    TECHNICAL_PATTERNS = {
        "api_call": re.compile(
            r"([a-zA-Z_][a-zA-Z0-9_]*\.[a-zA-Z_][a-zA-Z0-9_]*\.[a-zA-Z_][a-zA-Z0-9_]*)|"
            r"([a-zA-Z_][a-zA-Z0-9_]*\.[a-zA-Z_][a-zA-Z0-9_]*\(.*?\))"
        ),
        "function_sig": re.compile(
            r"(def|function|fn|method)\s+[a-zA-Z_][a-zA-Z0-9_]*|"
            r"[a-zA-Z_][a-zA-Z0-9_]*\s*\([^)]*\)\s*\{|"
            r"[a-zA-Z_][a-zA-Z0-9_]*\(.*?\)"
        ),
        "error_msg": re.compile(
            r"(error|exception|traceback|failed|failure|crash|bug|\bERR\b|\bWARN\b)[:\s]",
            re.IGNORECASE
        ),
        "config_file": re.compile(
            r"\.(yaml|yml|json|toml|ini|cfg|conf|config|env)\b|"
            r"(config|configuration|setting|option|parameter|flag)",
            re.IGNORECASE
        ),
        "how_to": re.compile(
            r"^(how (do|can|to|should|would|does)|"
            r"what(\s+is|\'s|s)?\s+(the|a|an)?\s*(best|correct|proper)?|"
            r"why (is|does|would|can\'t|cant)|"
            r"when (should|does|is|to)|"
            r"where (is|does|should)|"
            r"explain|understand|difference between|compare|vs\.?|versus)"
        ),
        "library_ref": re.compile(
            r"\b(react|vue|angular|svelte|next\.js|nuxt|django|flask|fastapi|"
            r"express|nestjs|spring|rails|laravel|dotnet|kubernetes|docker|terraform|"
            r"aws|gcp|azure|claude|openai|anthropic|langchain|llamaindex|"
            r"numpy|pandas|scipy|sklearn|matplotlib|tensorflow|pytorch|"
            r"node\.js|npm|yarn|pnpm|webpack|vite|rollup|esbuild|babel|"
            r"typescript|javascript|python|go|rust|java|kotlin|swift|c\+\+|"
            r"postgresql|mysql|mongodb|redis|elasticsearch|kafka|rabbitmq)\b",
            re.IGNORECASE
        ),
        "version_specific": re.compile(
            r"\b(v?\d+\.\d+(\.\d+)?|version\s+\d+|"
            r"latest|deprecated|changelog|migration|upgrade|update)\b",
            re.IGNORECASE
        ),
    }

    # Question types that rarely need docs
    GENERAL_CHAT = re.compile(
        r"^(hi|hello|hey|thanks|thank you|ok|okay|great|nice|cool|"
        r"good morning|good afternoon|good evening|bye|goodbye)\b",
        re.IGNORECASE
    )

    def __init__(self, storage=None, embedder=None):
        self.storage = storage
        self.embedder = embedder
        self._docset_keywords = {}  # cache of docset metadata

    def refresh_docset_metadata(self):
        """Load metadata about indexed docsets for better matching."""
        if self.storage is None:
            return
        self._docset_keywords = {}
        for name in self.storage.list_docsets():
            docset = self.storage.docsets.get(name)
            if docset:
                # Aggregate keywords from all chunks
                all_keywords = []
                for chunk in docset.get_all_chunks()[:50]:  # sample first 50
                    all_keywords.extend(chunk.get("keywords", []))
                # Get unique, weighted by frequency
                from collections import Counter
                counts = Counter(all_keywords)
                self._docset_keywords[name] = {
                    "top_keywords": [k for k, _ in counts.most_common(20)],
                    "total_chunks": docset.count(),
                }

    def analyze(self, query: str, conversation_history: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Analyze a query to determine if documentation lookup is needed.
        Returns a structured decision with confidence and reasoning.
        """
        start_time = time.time()
        query_lower = query.lower().strip()

        # 1. Fast rejection: general chat
        if self.GENERAL_CHAT.match(query_lower) or len(query_lower) < 4:
            return self._result(
                needs_docs=False,
                confidence=0.99,
                reasoning="General chat or too short to need documentation",
                suggested_docsets=[],
                latency_ms=(time.time() - start_time) * 1000
            )

        scores = {}
        signals = []

        # 2. Pattern-based scoring
        for signal_name, pattern in self.TECHNICAL_PATTERNS.items():
            matches = pattern.findall(query)
            if matches:
                scores[signal_name] = len(matches)
                signals.append(f"{signal_name}({len(matches)})")

        # 3. Docset keyword overlap
        docset_scores = {}
        if self._docset_keywords:
            query_tokens = set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", query_lower))
            for docset_name, meta in self._docset_keywords.items():
                docset_tokens = set(k.lower() for k in meta["top_keywords"])
                overlap = query_tokens & docset_tokens
                if overlap:
                    docset_scores[docset_name] = len(overlap) / len(query_tokens) if query_tokens else 0
                    signals.append(f"docset_match:{docset_name}({len(overlap)})")

        # 4. Semantic similarity to docset descriptions (if embedder available)
        semantic_scores = {}
        if self.embedder and self._docset_keywords:
            try:
                query_emb = self.embedder.encode([query], normalize_embeddings=True)[0]
                for docset_name, meta in self._docset_keywords.items():
                    desc = " ".join(meta["top_keywords"])
                    if desc:
                        desc_emb = self.embedder.encode([desc], normalize_embeddings=True)[0]
                        sim = float(np.dot(query_emb, desc_emb))
                        if sim > 0.5:
                            semantic_scores[docset_name] = sim
                            signals.append(f"semantic:{docset_name}({sim:.2f})")
            except Exception:
                pass

        # 5. Combine scores into confidence
        base_confidence = min(len(scores) * 0.15, 0.6)

        # Boost for strong signals
        if "api_call" in scores or "error_msg" in scores:
            base_confidence += 0.25
        if "how_to" in scores and "library_ref" in scores:
            base_confidence += 0.20
        if docset_scores:
            base_confidence += max(docset_scores.values()) * 0.3
        if semantic_scores:
            base_confidence += max(semantic_scores.values()) * 0.2

        # Cap and threshold
        confidence = min(base_confidence, 0.95)
        needs_docs = confidence >= 0.45

        # Determine suggested docsets
        suggested = []
        if docset_scores:
            suggested = sorted(docset_scores.keys(), key=lambda x: docset_scores[x], reverse=True)[:3]
        elif semantic_scores:
            suggested = sorted(semantic_scores.keys(), key=lambda x: semantic_scores[x], reverse=True)[:3]

        reasoning_parts = []
        if signals:
            reasoning_parts.append(f"Detected signals: {', '.join(signals)}")
        if suggested:
            reasoning_parts.append(f"Matched docsets: {', '.join(suggested)}")
        if not signals and not suggested:
            reasoning_parts.append("No strong technical signals detected")

        return self._result(
            needs_docs=needs_docs,
            confidence=round(confidence, 3),
            reasoning="; ".join(reasoning_parts),
            suggested_docsets=suggested,
            latency_ms=round((time.time() - start_time) * 1000, 2)
        )

    def _result(self, needs_docs: bool, confidence: float, reasoning: str,
                suggested_docsets: List[str], latency_ms: float) -> Dict[str, Any]:
        return {
            "needs_docs": needs_docs,
            "confidence": confidence,
            "reasoning": reasoning,
            "suggested_docsets": suggested_docsets,
            "latency_ms": latency_ms,
            "timestamp": time.time(),
        }