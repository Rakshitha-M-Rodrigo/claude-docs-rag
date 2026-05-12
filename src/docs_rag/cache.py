"""Multi-tier caching for embeddings and queries."""
import hashlib
import time
from typing import Any, Optional, List, Dict
from functools import lru_cache
import numpy as np


class TTLEntry:
    """Cache entry with TTL."""
    def __init__(self, value: Any, ttl_seconds: float):
        self.value = value
        self.expires_at = time.time() + ttl_seconds

    def is_expired(self) -> bool:
        return time.time() > self.expires_at


class QueryCache:
    """TTL-based cache for query results."""
    def __init__(self, ttl_seconds: float = 1800):
        self.ttl_seconds = ttl_seconds
        self._store: Dict[str, TTLEntry] = {}

    def get(self, key: str) -> Optional[Any]:
        entry = self._store.get(key)
        if entry is None:
            return None
        if entry.is_expired():
            del self._store[key]
            return None
        return entry.value

    def set(self, key: str, value: Any):
        self._store[key] = TTLEntry(value, self.ttl_seconds)

    def invalidate_by_prefix(self, prefix: str):
        """Invalidate keys starting with prefix."""
        keys_to_remove = [k for k in self._store.keys() if k.startswith(prefix)]
        for k in keys_to_remove:
            del self._store[k]


class EmbeddingCache:
    """LRU cache for text embeddings."""
    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self._store: Dict[str, np.ndarray] = {}
        self._access_order: List[str] = []

    def _make_key(self, text: str) -> str:
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    def get(self, text: str) -> Optional[np.ndarray]:
        key = self._make_key(text)
        if key in self._store:
            # Move to end (most recently used)
            self._access_order.remove(key)
            self._access_order.append(key)
            return self._store[key]
        return None

    def set(self, text: str, embedding: np.ndarray):
        key = self._make_key(text)
        if key in self._store:
            self._access_order.remove(key)
        elif len(self._store) >= self.max_size:
            # Evict least recently used
            lru_key = self._access_order.pop(0)
            del self._store[lru_key]
        
        self._store[key] = embedding
        self._access_order.append(key)