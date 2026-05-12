"""Query intelligence and retrieval orchestration."""
import re
from typing import List, Dict, Optional, Any
import numpy as np

from .storage import HybridStorage
from .cache import QueryCache, EmbeddingCache
from .chunker import extract_keywords


class QueryIntelligence:
    """Pre-retrieval query processing."""

    # Simple synonym expansion for common tech terms
    SYNONYMS = {
        "hook": ["hooks", "useEffect", "useState", "useCallback"],
        "effect": ["useEffect", "side effect", "cleanup"],
        "state": ["useState", "state management", "Redux", "Zustand"],
        "ref": ["useRef", "forwardRef", "createRef"],
        "memo": ["useMemo", "React.memo", "memoization"],
        "context": ["useContext", "Context API", "Provider"],
        "router": ["React Router", "useRouter", "Next.js routing"],
        "deploy": ["deployment", "hosting", "Vercel", "Netlify", "Docker"],
        "auth": ["authentication", "authorization", "OAuth", "JWT", "session"],
        "test": ["testing", "Jest", "Vitest", "Cypress", "Playwright"],
        "db": ["database", "PostgreSQL", "MySQL", "MongoDB", "Prisma"],
        "api": ["API", "REST", "GraphQL", "endpoint", "fetch", "axios"],
    }

    @classmethod
    def expand_query(cls, query: str) -> str:
        """Expand query with synonyms."""
        words = query.lower().split()
        expanded = set(words)
        for word in words:
            if word in cls.SYNONYMS:
                expanded.update(cls.SYNONYMS[word])
        return " ".join(expanded)

    @classmethod
    def classify_query(cls, query: str) -> str:
        """Classify query type for strategy selection."""
        q = query.lower()
        if re.search(r"[a-zA-Z_][a-zA-Z0-9_]*\.[a-zA-Z_][a-zA-Z0-9_]*\(", q):
            return "api_lookup"
        if re.search(r"(error|exception|traceback|failed|bug)", q):
            return "troubleshooting"
        if re.search(r"^(how (do|can|to)|what is|explain)", q):
            return "how_to"
        if re.search(r"(compare|vs\.?|versus|difference between)", q):
            return "comparison"
        return "general"

    @classmethod
    def extract_code_terms(cls, query: str) -> List[str]:
        """Extract code identifiers for BM25 boosting."""
        # dot notation: claude.messages.create
        dotted = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*\.[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?", query)
        # function calls: createMessage()
        funcs = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*\(", query)
        # CamelCase / snake_case identifiers
        ids = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", query)
        return list(dict.fromkeys(dotted + funcs + ids))


class DocsRetriever:
    """Orchestrates hybrid retrieval with RRF fusion."""

    def __init__(self, storage: HybridStorage, embedder, query_cache: QueryCache, embedding_cache: EmbeddingCache):
        self.storage = storage
        self.embedder = embedder
        self.query_cache = query_cache
        self.embedding_cache = embedding_cache

    def search(self, query: str, docset_name: Optional[str] = None, top_k: int = 5) -> List[Dict[str, Any]]:
        """Hybrid search with caching and RRF fusion."""
        cache_key = f"{query}:{docset_name}:{top_k}"
        cached = self.query_cache.get(cache_key)
        if cached is not None:
            return cached

        # Query intelligence
        query_type = QueryIntelligence.classify_query(query)
        expanded_query = QueryIntelligence.expand_query(query)
        code_terms = QueryIntelligence.extract_code_terms(query)

        # Determine docsets to search
        if docset_name:
            docsets = [docset_name] if docset_name in self.storage.list_docsets() else []
        else:
            docsets = self.storage.list_docsets()

        if not docsets:
            return []

        # Collect results from all docsets
        all_vector_hits = []
        all_bm25_hits = []

        for ds_name in docsets:
            docset = self.storage.get_or_create_docset(ds_name)
            
            # Vector search
            query_emb = self.embedding_cache.get(query)
            if query_emb is None:
                query_emb = self.embedder.encode([query], normalize_embeddings=True)[0]
                self.embedding_cache.set(query, query_emb)
            
            vector_hits = docset.search_vector(query_emb, top_k=top_k * 2)
            for h in vector_hits:
                h["docset"] = ds_name
                h["retriever"] = "vector"
            all_vector_hits.extend(vector_hits)

            # BM25 search (use expanded query + code terms)
            bm25_query = expanded_query
            if code_terms:
                bm25_query += " " + " ".join(code_terms)
            
            bm25_hits = docset.search_bm25(bm25_query, top_k=top_k * 2)
            for h in bm25_hits:
                h["docset"] = ds_name
                h["retriever"] = "bm25"
            all_bm25_hits.extend(bm25_hits)

        # RRF Fusion
        fused = self._reciprocal_rank_fusion(all_vector_hits, all_bm25_hits, k=60)
        
        # Deduplicate
        seen_texts = set()
        deduped = []
        for item in fused:
            text_hash = hash(item["text"][:200])
            if text_hash not in seen_texts:
                seen_texts.add(text_hash)
                deduped.append(item)

        # Format results
        results = []
        for item in deduped[:top_k]:
            results.append({
                "text": item["text"],
                "citation": f"{item['docset']} > {item['metadata'].get('header', 'Unknown')}",
                "source": item["metadata"].get("source", ""),
                "score": item.get("rrf_score", 0.0),
                "retriever": item.get("retriever", "unknown"),
            })

        self.query_cache.set(cache_key, results)
        return results

    def _reciprocal_rank_fusion(self, vector_hits: List[Dict], bm25_hits: List[Dict], k: int = 60) -> List[Dict]:
        """Combine rankings using Reciprocal Rank Fusion."""
        scores = {}
        
        # Score vector results
        for rank, hit in enumerate(vector_hits):
            doc_id = hit["id"]
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
            if doc_id not in [h["id"] for h in bm25_hits]:
                scores[doc_id] = hit.get("score", 0.0) * 0.5  # boost if only in vector
        
        # Score BM25 results
        for rank, hit in enumerate(bm25_hits):
            doc_id = hit["id"]
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
            if doc_id not in [h["id"] for h in vector_hits]:
                scores[doc_id] = hit.get("score", 0.0) * 0.5  # boost if only in BM25
        
        # Merge and sort
        all_hits = {h["id"]: h for h in (vector_hits + bm25_hits)}
        fused = []
        for doc_id, score in sorted(scores.items(), key=lambda x: x[1], reverse=True):
            if doc_id in all_hits:
                hit = all_hits[doc_id].copy()
                hit["rrf_score"] = score
                fused.append(hit)
        
        return fused

    def invalidate_docset(self, docset_name: str):
        """Invalidate cache entries for a docset."""
        self.query_cache.invalidate_by_prefix(docset_name)