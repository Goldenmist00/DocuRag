"""
embedder.py
===========
Embedding via NVIDIA API (nvidia/nv-embed-v1, 4096d).
No local model — fast API-based embedding.
"""

import hashlib
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from enum import Enum

import numpy as np
import requests
from tqdm import tqdm

from src.pdf_processor import Chunk

_CACHE_FILE = "embeddings_cache.npz"
_NVIDIA_EMBED_URL = "https://integrate.api.nvidia.com/v1/embeddings"
_NVIDIA_MODEL = "nvidia/nv-embed-v1"
_NVIDIA_DIM = 4096
_NVIDIA_BATCH_SIZE = 48   # texts per API request (smaller = less retry surface)
_NVIDIA_MAX_CHARS  = 2000 # truncate before sending (nv-embed-v1 ~512 tokens)
_NVIDIA_WORKERS    = 12   # concurrent API requests

logger = logging.getLogger(__name__)


class EmbeddingTier(str, Enum):
    """Kept for backward compatibility — only NVIDIA is active."""
    NVIDIA   = "nvidia"
    FAST     = "fast"      # legacy alias → nvidia
    BALANCED = "balanced"  # legacy alias → nvidia
    DEEP     = "deep"      # legacy alias → nvidia


TIER_CONFIGS = {
    EmbeddingTier.NVIDIA: {
        "model_name": _NVIDIA_MODEL,
        "dimensions": _NVIDIA_DIM,
        "description": "NVIDIA nv-embed-v1 — 4096d, API-based",
    },
}
# Legacy aliases resolve to NVIDIA config
for _t in (EmbeddingTier.FAST, EmbeddingTier.BALANCED, EmbeddingTier.DEEP):
    TIER_CONFIGS[_t] = TIER_CONFIGS[EmbeddingTier.NVIDIA]


class Embedder:
    """
    API-based embedder using NVIDIA nv-embed-v1 (4096d).
    Requires NVIDIA_EMBED_API_KEY or NVIDIA_API_KEY in environment.
    """

    def __init__(
        self,
        tier: EmbeddingTier = EmbeddingTier.NVIDIA,
        cache_dir: str = "embeddings/cache",
        batch_size: int = _NVIDIA_BATCH_SIZE,
        device: Optional[str] = None,  # ignored — API-based
    ):
        # All tiers map to NVIDIA
        self.tier = EmbeddingTier.NVIDIA
        self.config = TIER_CONFIGS[EmbeddingTier.NVIDIA]
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.batch_size = _NVIDIA_BATCH_SIZE

        self._api_key = (
            os.getenv("NVIDIA_EMBED_API_KEY", "").strip()
            or os.getenv("NVIDIA_API_KEY", "").strip()
        )
        if not self._api_key:
            raise ValueError("Set NVIDIA_EMBED_API_KEY or NVIDIA_API_KEY in .env")

        self._headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        self._cache_lock = threading.Lock()
        self._mem_cache: Dict[str, np.ndarray] = {}
        self._cache_dirty = False
        self._load_cache_into_memory()

        self._model_loaded = True
        logger.info("Embedder ready | model=%s | dim=%d | API-based", _NVIDIA_MODEL, _NVIDIA_DIM)

    # ------------------------------------------------------------------
    # No-op for backward compat (generate_submission calls this)
    # ------------------------------------------------------------------

    def _load_model(self) -> None:
        pass  # nothing to load — API-based

    # ------------------------------------------------------------------
    # NVIDIA API call
    # ------------------------------------------------------------------

    def _embed_nvidia_batch(self, texts: List[str]) -> np.ndarray:
        # Truncate to avoid token-limit 500 errors
        safe_texts = [t[:_NVIDIA_MAX_CHARS] for t in texts]

        # If batch > 1 and we get a 500, split and retry halves recursively
        def _call(batch: List[str]) -> np.ndarray:
            payload = {
                "input": batch,
                "model": _NVIDIA_MODEL,
                "input_type": "passage",
                "encoding_format": "float",
                "truncate": "END",
            }
            for attempt in range(3):
                try:
                    resp = requests.post(
                        _NVIDIA_EMBED_URL, headers=self._headers,
                        json=payload, timeout=60,
                    )
                    if resp.status_code == 500 and len(batch) > 1:
                        # Split batch in half and retry each half
                        mid = len(batch) // 2
                        logger.warning("500 on batch of %d — splitting into %d + %d", len(batch), mid, len(batch) - mid)
                        left  = _call(batch[:mid])
                        right = _call(batch[mid:])
                        return np.vstack([left, right])
                    resp.raise_for_status()
                    data = resp.json()
                    vecs = [item["embedding"] for item in sorted(data["data"], key=lambda x: x["index"])]
                    arr = np.array(vecs, dtype=np.float32)
                    norms = np.linalg.norm(arr, axis=1, keepdims=True)
                    return arr / np.where(norms == 0, 1.0, norms)
                except requests.HTTPError:
                    if resp.status_code == 429:
                        wait = 2 ** attempt
                        logger.warning("Rate limited — retrying in %ds", wait)
                        time.sleep(wait)
                    else:
                        raise RuntimeError(f"NVIDIA embed API {resp.status_code}: {resp.text}")
                except RuntimeError:
                    raise
                except Exception as e:
                    if attempt == 2:
                        raise RuntimeError(f"NVIDIA embed API failed: {e}") from e
                    time.sleep(2 ** attempt)
            raise RuntimeError("NVIDIA embed API failed after 3 attempts")

        return _call(safe_texts)

    # ------------------------------------------------------------------
    # In-memory cache with lazy disk persistence
    # ------------------------------------------------------------------

    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _load_cache_into_memory(self) -> None:
        """Load the on-disk .npz cache into ``_mem_cache`` once at init."""
        p = self.cache_dir / _CACHE_FILE
        if p.exists():
            try:
                data = np.load(p, allow_pickle=False)
                self._mem_cache = dict(data)
                logger.info("Loaded %d cached embeddings from disk", len(self._mem_cache))
            except Exception as e:
                logger.warning("Cache load failed, starting fresh: %s", e)

    def flush_cache(self) -> None:
        """Persist dirty in-memory cache to disk. Called on shutdown."""
        if not self._cache_dirty:
            return
        with self._cache_lock:
            try:
                np.savez(self.cache_dir / _CACHE_FILE, **self._mem_cache)
                self._cache_dirty = False
                logger.info("Flushed %d embeddings to disk cache", len(self._mem_cache))
            except Exception as e:
                logger.warning("Cache flush failed: %s", e)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def embed(self, text: str, use_cache: bool = True) -> np.ndarray:
        """Embed a single string (e.g. a query)."""
        return self.embed_batch([text], show_progress=False, use_cache=use_cache)[0]

    def embed_batch(
        self,
        texts: List[str],
        batch_size: int = _NVIDIA_BATCH_SIZE,
        show_progress: bool = True,
        use_cache: bool = True,
        on_batch_done: Optional[Callable[[int, int], None]] = None,
    ) -> np.ndarray:
        """
        Embed a list of strings using in-memory cache and parallel API calls.

        Args:
            texts:         Strings to embed.
            batch_size:    Ignored (uses _NVIDIA_BATCH_SIZE).
            show_progress: Show tqdm bar.
            use_cache:     Whether to use the in-memory embedding cache.
            on_batch_done: Optional callback ``(batch_idx, total_batches)``
                           invoked after each API batch completes.

        Returns:
            (N, 4096) float32 array.
        """
        if not texts:
            return np.array([])

        results: List[Optional[np.ndarray]] = []
        to_compute: List[str] = []
        to_compute_idx: List[int] = []
        hits = 0

        with self._cache_lock:
            for i, text in enumerate(texts):
                h = self._hash(text)
                cached = self._mem_cache.get(h) if use_cache else None
                if cached is not None:
                    results.append(cached)
                    hits += 1
                else:
                    results.append(None)
                    to_compute.append(text)
                    to_compute_idx.append(i)

        self._stats_cache_hits = hits
        self._stats_cache_misses = len(to_compute)

        if to_compute:
            batches = [
                to_compute[i: i + _NVIDIA_BATCH_SIZE]
                for i in range(0, len(to_compute), _NVIDIA_BATCH_SIZE)
            ]
            n_batches = len(batches)
            computed_map: Dict[int, np.ndarray] = {}
            done_count = 0

            pbar = tqdm(total=n_batches, desc="Embedding (NVIDIA API)", unit="batch") if show_progress else None

            with ThreadPoolExecutor(max_workers=_NVIDIA_WORKERS) as pool:
                future_to_idx = {
                    pool.submit(self._embed_nvidia_batch, batch): idx
                    for idx, batch in enumerate(batches)
                }
                for future in as_completed(future_to_idx):
                    batch_idx = future_to_idx[future]
                    computed_map[batch_idx] = future.result()
                    done_count += 1
                    if pbar:
                        pbar.update(1)
                    if on_batch_done:
                        on_batch_done(done_count, n_batches)

            if pbar:
                pbar.close()

            computed_arr = np.vstack([computed_map[i] for i in range(n_batches)])

            with self._cache_lock:
                for idx, emb in zip(to_compute_idx, computed_arr):
                    results[idx] = emb
                    if use_cache:
                        self._mem_cache[self._hash(texts[idx])] = emb
                        self._cache_dirty = True

        return np.vstack(results)

    def embed_chunks(
        self,
        chunks: List[Chunk],
        use_cache: bool = True,
        show_progress: bool = True,
    ) -> Tuple[np.ndarray, Dict]:
        texts = [c.text for c in chunks]
        t0 = time.time()
        embeddings = self.embed_batch(texts, show_progress=show_progress, use_cache=use_cache)
        elapsed = time.time() - t0
        stats = {
            "total_chunks":    len(chunks),
            "cached":          self._stats_cache_hits,
            "computed":        self._stats_cache_misses,
            "dimensions":      _NVIDIA_DIM,
            "elapsed_seconds": round(elapsed, 2),
            "chunks_per_second": round(len(chunks) / elapsed, 1) if elapsed > 0 else 0,
            "tier":  "nvidia",
            "model": _NVIDIA_MODEL,
        }
        logger.info(
            "✓ Embeddings done: %d chunks | %.1fs | %d cached / %d computed",
            len(chunks), elapsed, stats["cached"], stats["computed"],
        )
        return embeddings, stats

    def get_stats(self) -> Dict:
        hits   = getattr(self, "_stats_cache_hits",   0)
        misses = getattr(self, "_stats_cache_misses", 0)
        total  = hits + misses
        return {"cache_hits": hits, "cache_misses": misses, "hit_rate": hits / total if total else 0.0}

    @property
    def model_name(self) -> str:
        return _NVIDIA_MODEL

    @property
    def embedding_dim(self) -> int:
        return _NVIDIA_DIM

    @property
    def device(self) -> str:
        """Compatibility property — embedder is API-based."""
        return "api"
