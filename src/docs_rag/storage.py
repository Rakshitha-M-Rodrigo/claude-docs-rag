"""Hybrid vector + BM25 storage with docset management."""
import os
import json
import pickle
from typing import List, Dict, Optional, Any
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi


class DocsetStorage:
    """Manages storage for a single docset."""

    def __init__(self, docset_name: str, persist_dir: str, chroma_client):
        self.docset_name = docset_name
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        
        self.chroma_collection = chroma_client.get_or_create_collection(
            name=docset_name,
            metadata={"hnsw:space": "cosine"}
        )
        
        self.bm25_path = self.persist_dir / f"{docset_name}_bm25.pkl"
        self.chunks_path = self.persist_dir / f"{docset_name}_chunks.json"
        
        self._chunks = []
        self._bm25 = None
        self._load()

    def _load(self):
        if self.chunks_path.exists():
            with open(self.chunks_path, "r", encoding="utf-8") as f:
                self._chunks = json.load(f)
        if self.bm25_path.exists():
            with open(self.bm25_path, "rb") as f:
                self._bm25 = pickle.load(f)

    def _save(self):
        with open(self.chunks_path, "w", encoding="utf-8") as f:
            json.dump(self._chunks, f, ensure_ascii=False)
        if self._bm25 is not None:
            with open(self.bm25_path, "wb") as f:
                pickle.dump(self._bm25, f)

    def add_chunks(self, chunks: List[Dict[str, Any]], embeddings: np.ndarray):
        """Add chunks with their embeddings."""
        start_idx = len(self._chunks)
        
        for i, chunk in enumerate(chunks):
            chunk["id"] = f"{self.docset_name}_{start_idx + i}"
            self._chunks.append(chunk)

        # Add to ChromaDB
        ids = [c["id"] for c in chunks]
        texts = [c["text"] for c in chunks]
        metadatas = [{"source": c["source"], "header": c.get("header", ""), "docset": c["docset"]} for c in chunks]
        
        self.chroma_collection.add(
            ids=ids,
            documents=texts,
            embeddings=embeddings.tolist(),
            metadatas=metadatas
        )

        # Rebuild BM25
        tokenized = [c["text"].lower().split() for c in self._chunks]
        self._bm25 = BM25Okapi(tokenized)
        self._save()

    def search_vector(self, query_embedding: np.ndarray, top_k: int = 10) -> List[Dict[str, Any]]:
        """Search using dense vector similarity."""
        results = self.chroma_collection.query(
            query_embeddings=[query_embedding.tolist()],
            n_results=min(top_k, len(self._chunks)),
            include=["documents", "metadatas", "distances"]
        )
        
        hits = []
        if results["ids"] and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                hits.append({
                    "id": doc_id,
                    "text": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i],
                    "score": 1.0 - results["distances"][0][i],  # convert distance to similarity
                })
        return hits

    def search_bm25(self, query: str, top_k: int = 10) -> List[Dict[str, Any]]:
        """Search using BM25 keyword matching."""
        if self._bm25 is None or not self._chunks:
            return []
        
        tokenized_query = query.lower().split()
        scores = self._bm25.get_scores(tokenized_query)
        top_indices = np.argsort(scores)[::-1][:top_k]
        
        hits = []
        for idx in top_indices:
            if scores[idx] > 0:
                hits.append({
                    "id": self._chunks[idx]["id"],
                    "text": self._chunks[idx]["text"],
                    "metadata": {
                        "source": self._chunks[idx]["source"],
                        "header": self._chunks[idx].get("header", ""),
                        "docset": self._chunks[idx]["docset"],
                    },
                    "score": float(scores[idx]),
                })
        return hits

    def get_all_chunks(self) -> List[Dict[str, Any]]:
        return self._chunks

    def count(self) -> int:
        return len(self._chunks)

    def clear(self):
        self._chunks = []
        self._bm25 = None
        if self.chunks_path.exists():
            self.chunks_path.unlink()
        if self.bm25_path.exists():
            self.bm25_path.unlink()
        try:
            # Note: ChromaDB delete_collection may not be available in all versions
            pass
        except Exception:
            pass


class HybridStorage:
    """Manages multiple docsets with hybrid retrieval."""

    def __init__(self, persist_dir: str):
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        
        import chromadb
        self.chroma_client = chromadb.PersistentClient(path=str(self.persist_dir / "chroma"))
        self.docsets: Dict[str, DocsetStorage] = {}

    def get_or_create_docset(self, name: str) -> DocsetStorage:
        if name not in self.docsets:
            self.docsets[name] = DocsetStorage(
                docset_name=name,
                persist_dir=self.persist_dir,
                chroma_client=self.chroma_client
            )
        return self.docsets[name]

    def list_docsets(self) -> List[str]:
        # Get from ChromaDB collections
        try:
            collections = self.chroma_client.list_collections()
            return [c.name for c in collections]
        except Exception:
            return list(self.docsets.keys())

    def delete_docset(self, name: str):
        if name in self.docsets:
            self.docsets[name].clear()
            del self.docsets[name]
        try:
            self.chroma_client.delete_collection(name)
        except Exception:
            pass