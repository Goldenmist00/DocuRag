"""
embedder.py
===========
API-based embedding via Gemini (text-embedding-004, 768d) with
NVIDIA bge-m3 fallback.  Provider is selected automatically at
init based on available API keys (Gemini preferred).
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

_GEMINI_EMBED_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:batchEmbedContents"
_GEMINI_MODEL = "gemini-embedding-001"
_GEMINI_DIM = 768

_NVIDIA_EMBED_URL = "https://integrate.api.nvidia.com/v1/embeddings"
_NVIDIA_MODEL = "baai/bge-m3"
_NVIDIA_DIM = 1024

_BATCH_SIZE = 48
_MAX_CHARS = 8000
_WORKERS = 12

logger = logging.getLogger(__name__)


class EmbeddingTier(str, Enum):
    """Kept for backward compatibility."""
    NVIDIA   = "nvidia"
    FAST     = "fast"
    BALANCED = "balanced"
    DEEP     = "deep"


TIER_CONFIGS = {
    EmbeddingTier.NVIDIA: {
        "model_name": _NVIDIA_MODEL,
        "dimensions": _NVIDIA_DIM,
        "description": "BAAI bge-m3 — 1024d, API-based via NVIDIA NIM",
    },
}
for _t in (EmbeddingTier.FAST, EmbeddingTier.BALANCED, EmbeddingTier.DEEP):
    TIER_CONFIGS[_t] = TIER_CONFIGS[EmbeddingTier.NVIDIA]


class Embedder:
    """API-based embedder.  Gemini text-embedding-004 (768d) is the
    primary provider; falls back to NVIDIA bge-m3 (1024d) when no
    ``GEMINI_API_KEY`` is set.

    Args:
        tier:      Legacy tier selector (ignored — provider is chosen
                   automatically from env keys).
        cache_dir: Directory for on-disk embedding cache.
        batch_size: Ignored (uses module-level ``_BATCH_SIZE``).
        device:    Ignored — API-based.

    Raises:
        ValueError: If neither ``GEMINI_API_KEY`` nor any NVIDIA key
                    is configured.
    """

    def __init__(
        self,
        tier: EmbeddingTier = EmbeddingTier.NVIDIA,
        cache_dir: str = "embeddings/cache",
        batch_size: int = _BATCH_SIZE,
        device: Optional[str] = None,
    ):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.batch_size = _BATCH_SIZE

        gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
        nvidia_key = (
            os.getenv("NVIDIA_EMBED_API_KEY", "").strip()
            or os.getenv("NVIDIA_API_KEY", "").strip()
        )

        if gemini_key:
            self._provider = "gemini"
            self._api_key = gemini_key
            self._embed_url = _GEMINI_EMBED_URL
            self._model = _GEMINI_MODEL
            self._dim = _GEMINI_DIM
        elif nvidia_key:
            self._provider = "nvidia"
            self._api_key = nvidia_key
            self._embed_url = _NVIDIA_EMBED_URL
            self._model = _NVIDIA_MODEL
            self._dim = _NVIDIA_DIM
        else:
            raise ValueError(
                "Set GEMINI_API_KEY or NVIDIA_API_KEY / NVIDIA_EMBED_API_KEY in .env"
            )

        self.tier = EmbeddingTier.NVIDIA
        self.config = {
            "model_name": self._model,
            "dimensions": self._dim,
            "description": f"{self._model} — {self._dim}d, API-based via {self._provider}",
        }

        self._headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        self._cache_lock = threading.Lock()
        self._mem_cache: Dict[str, np.ndarray] = {}
        self._cache_dirty = False
        self._load_cache_into_memory()

        self._model_loaded = True
        logger.info(
            "Embedder ready | provider=%s | model=%s | dim=%d",
            self._provider, self._model, self._dim,
        )

    def _load_model(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Embedding API call
    # ------------------------------------------------------------------

    def _embed_api_batch(self, texts: List[str]) -> np.ndarray:
        """Embed a batch of texts via the active provider's API.

        Gemini uses the native ``batchEmbedContents`` endpoint
        (``?key=`` auth, structured request body).  NVIDIA uses the
        OpenAI-compatible ``/v1/embeddings`` format.

        Args:
            texts: Raw text strings (will be truncated to ``_MAX_CHARS``).

        Returns:
            L2-normalised float32 array of shape ``(len(texts), self._dim)``.

        Raises:
            RuntimeError: After exhausting retries on all sub-batches.
        """
        safe_texts = [t[:_MAX_CHARS] for t in texts]

        if self._provider == "gemini":
            return self._call_gemini(safe_texts)
        return self._call_nvidia(safe_texts)

    def _call_gemini(self, batch: List[str]) -> np.ndarray:
        """Call Gemini batchEmbedContents endpoint.

        Auth is via ``?key=`` query parameter.  The request body wraps
        each text in ``{model, content: {parts: [{text}]}}`` objects.

        Args:
            batch: Truncated text strings.

        Returns:
            L2-normalised float32 array.

        Raises:
            RuntimeError: On non-retryable errors after exhausting retries.
        """
        url = f"{self._embed_url}?key={self._api_key}"
        model_ref = f"models/{self._model}"
        payload = {
            "requests": [
                {
                    "model": model_ref,
                    "content": {"parts": [{"text": t}]},
                    "outputDimensionality": _GEMINI_DIM,
                }
                for t in batch
            ]
        }
        headers = {"Content-Type": "application/json"}

        for attempt in range(4):
            resp = None
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=60)
                if resp.status_code in (500, 502, 503) and len(batch) > 1:
                    mid = len(batch) // 2
                    logger.warning(
                        "%d on batch of %d — splitting into %d + %d",
                        resp.status_code, len(batch), mid, len(batch) - mid,
                    )
                    return np.vstack([
                        self._call_gemini(batch[:mid]),
                        self._call_gemini(batch[mid:]),
                    ])
                if resp.status_code == 429:
                    wait = 2 ** attempt
                    logger.warning("Gemini embed rate limited — retrying in %ds", wait)
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                vecs = [emb["values"] for emb in data["embeddings"]]
                arr = np.array(vecs, dtype=np.float32)
                norms = np.linalg.norm(arr, axis=1, keepdims=True)
                return arr / np.where(norms == 0, 1.0, norms)
            except requests.HTTPError:
                status = resp.status_code if resp is not None else "?"
                raise RuntimeError(
                    f"gemini embed API {status}: "
                    f"{resp.text if resp is not None else 'no response'}"
                )
            except RuntimeError:
                raise
            except Exception as exc:
                if attempt == 3:
                    raise RuntimeError(f"gemini embed API failed: {exc}") from exc
                time.sleep(2 ** attempt)
        raise RuntimeError("gemini embed API failed after retries")

    def _call_nvidia(self, batch: List[str]) -> np.ndarray:
        """Call NVIDIA OpenAI-compatible embeddings endpoint.

        Args:
            batch: Truncated text strings.

        Returns:
            L2-normalised float32 array.

        Raises:
            RuntimeError: On non-retryable errors after exhausting retries.
        """
        payload = {
            "input": batch,
            "model": self._model,
            "input_type": "passage",
            "encoding_format": "float",
            "truncate": "END",
        }
        for attempt in range(4):
            resp = None
            try:
                resp = requests.post(
                    self._embed_url, headers=self._headers,
                    json=payload, timeout=60,
                )
                if resp.status_code in (500, 502, 503) and len(batch) > 1:
                    mid = len(batch) // 2
                    logger.warning(
                        "%d on batch of %d — splitting into %d + %d",
                        resp.status_code, len(batch), mid, len(batch) - mid,
                    )
                    return np.vstack([
                        self._call_nvidia(batch[:mid]),
                        self._call_nvidia(batch[mid:]),
                    ])
                if resp.status_code == 429:
                    wait = 2 ** attempt
                    logger.warning("NVIDIA embed rate limited — retrying in %ds", wait)
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                vecs = [
                    item["embedding"]
                    for item in sorted(data["data"], key=lambda x: x["index"])
                ]
                arr = np.array(vecs, dtype=np.float32)
                norms = np.linalg.norm(arr, axis=1, keepdims=True)
                return arr / np.where(norms == 0, 1.0, norms)
            except requests.HTTPError:
                status = resp.status_code if resp is not None else "?"
                raise RuntimeError(
                    f"nvidia embed API {status}: "
                    f"{resp.text if resp is not None else 'no response'}"
                )
            except RuntimeError:
                raise
            except Exception as exc:
                if attempt == 3:
                    raise RuntimeError(f"nvidia embed API failed: {exc}") from exc
                time.sleep(2 ** attempt)
        raise RuntimeError("nvidia embed API failed after retries")

    # ------------------------------------------------------------------
    # In-memory cache with lazy disk persistence
    # ------------------------------------------------------------------

    @staticmethod
    def _hash(text: str) -> str:
        """SHA-256 digest used as cache key."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _load_cache_into_memory(self) -> None:
        """Load the on-disk .npz cache into ``_mem_cache`` once at init."""
        p = self.cache_dir / _CACHE_FILE
        if p.exists():
            try:
                data = np.load(p, allow_pickle=False)
                valid = {
                    k: v for k, v in data.items()
                    if isinstance(v, np.ndarray) and v.shape == (self._dim,)
                }
                self._mem_cache = valid
                skipped = len(data.files) - len(valid)
                if skipped:
                    logger.info(
                        "Loaded %d cached embeddings (skipped %d with wrong dim)",
                        len(valid), skipped,
                    )
                else:
                    logger.info("Loaded %d cached embeddings from disk", len(valid))
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
        """Embed a single string (e.g. a query).

        Args:
            text: Input string.
            use_cache: Whether to consult the in-memory cache.

        Returns:
            1-D float32 array of shape ``(self._dim,)``.
        """
        return self.embed_batch([text], show_progress=False, use_cache=use_cache)[0]

    def embed_batch(
        self,
        texts: List[str],
        batch_size: int = _BATCH_SIZE,
        show_progress: bool = True,
        use_cache: bool = True,
        on_batch_done: Optional[Callable[[int, int], None]] = None,
    ) -> np.ndarray:
        """Embed a list of strings using in-memory cache and parallel API calls.

        Args:
            texts:         Strings to embed.
            batch_size:    Ignored (uses module-level ``_BATCH_SIZE``).
            show_progress: Show tqdm bar.
            use_cache:     Whether to use the in-memory embedding cache.
            on_batch_done: Optional callback ``(batch_idx, total_batches)``
                           invoked after each API batch completes.

        Returns:
            ``(N, self._dim)`` float32 array.
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
                to_compute[i: i + _BATCH_SIZE]
                for i in range(0, len(to_compute), _BATCH_SIZE)
            ]
            n_batches = len(batches)
            computed_map: Dict[int, np.ndarray] = {}
            done_count = 0

            desc = f"Embedding ({self._provider.upper()} API)"
            pbar = tqdm(total=n_batches, desc=desc, unit="batch") if show_progress else None

            with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
                future_to_idx = {
                    pool.submit(self._embed_api_batch, batch): idx
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
        """Embed a list of ``Chunk`` objects.

        Args:
            chunks:        Chunk objects with a ``.text`` attribute.
            use_cache:     Use in-memory cache.
            show_progress: Show tqdm bar.

        Returns:
            Tuple of ``(embeddings, stats_dict)``.
        """
        texts = [c.text for c in chunks]
        t0 = time.time()
        embeddings = self.embed_batch(texts, show_progress=show_progress, use_cache=use_cache)
        elapsed = time.time() - t0
        stats = {
            "total_chunks":      len(chunks),
            "cached":            self._stats_cache_hits,
            "computed":          self._stats_cache_misses,
            "dimensions":        self._dim,
            "elapsed_seconds":   round(elapsed, 2),
            "chunks_per_second": round(len(chunks) / elapsed, 1) if elapsed > 0 else 0,
            "tier":              self._provider,
            "model":             self._model,
        }
        logger.info(
            "Embeddings done: %d chunks | %.1fs | %d cached / %d computed",
            len(chunks), elapsed, stats["cached"], stats["computed"],
        )
        return embeddings, stats

    def get_stats(self) -> Dict:
        """Return cache hit/miss statistics."""
        hits = getattr(self, "_stats_cache_hits", 0)
        misses = getattr(self, "_stats_cache_misses", 0)
        total = hits + misses
        return {
            "cache_hits": hits,
            "cache_misses": misses,
            "hit_rate": hits / total if total else 0.0,
        }

    @property
    def model_name(self) -> str:
        """Active embedding model identifier."""
        return self._model

    @property
    def embedding_dim(self) -> int:
        """Dimensionality of the output vectors."""
        return self._dim

    @property
    def device(self) -> str:
        """Compatibility property — embedder is API-based."""
        return "api"


_singleton_embedder: Optional[Embedder] = None
_singleton_lock = threading.Lock()


def get_embedder() -> Embedder:
    """Return a process-wide singleton Embedder instance.

    Returns:
        Shared ``Embedder`` instance.

    Raises:
        ValueError: If no embedding API key is configured.
    """
    global _singleton_embedder
    if _singleton_embedder is not None:
        return _singleton_embedder
    with _singleton_lock:
        if _singleton_embedder is not None:
            return _singleton_embedder
        _singleton_embedder = Embedder()
        return _singleton_embedder
