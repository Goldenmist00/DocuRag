"""
retriever.py
============
Phase 4 — Semantic Retrieval

Wraps Embedder + PgVectorStore into a clean retrieval interface.
Returns typed RetrievedChunk objects with citation helpers used by
both the Generator and the submission pipeline.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class RetrievedChunk:
    """A single retrieved passage with metadata and similarity score."""

    chunk_id: str
    text: str
    score: float

    # Citation metadata
    section_id: str = ""
    chapter_id: str = ""
    section_title: str = ""
    page_start: int = 0
    page_end: int = 0
    chunk_index: int = 0

    def citation(self) -> str:
        """Human-readable citation string for prompt and references."""
        parts: List[str] = []
        if self.chapter_id:
            parts.append(f"Chapter {self.chapter_id}")
        if self.section_id:
            parts.append(f"\u00a7{self.section_id}")
        if self.section_title:
            parts.append(self.section_title)
        if self.page_start:
            parts.append(f"p.{self.page_start}")
        return " | ".join(parts) if parts else self.chunk_id

    def to_dict(self) -> Dict:
        return {
            "chunk_id":      self.chunk_id,
            "text":          self.text,
            "score":         round(self.score, 4),
            "section_id":    self.section_id,
            "chapter_id":    self.chapter_id,
            "section_title": self.section_title,
            "page_start":    self.page_start,
            "page_end":      self.page_end,
            "chunk_index":   self.chunk_index,
        }


# ---------------------------------------------------------------------------
# Retriever
# ---------------------------------------------------------------------------

class Retriever:
    """
    Semantic retriever: embeds a query and fetches the top-k most similar
    chunks from the PostgreSQL vector store.

    Args:
        embedder:        Configured Embedder instance.
        vector_store:    Configured PgVectorStore instance.
        top_k:           Number of chunks to return per query.
        score_threshold: Optional minimum cosine similarity (0-1).
    """

    def __init__(
        self,
        embedder,
        vector_store,
        top_k: int = 5,
        score_threshold: Optional[float] = None,
    ) -> None:
        self.embedder = embedder
        self.vector_store = vector_store
        self.top_k = top_k
        self.score_threshold = score_threshold

    def retrieve(self, query: str, top_k: Optional[int] = None) -> List[RetrievedChunk]:
        """
        Embed query and return the top-k most similar chunks.

        Args:
            query: Natural-language question.
            top_k: Override instance top_k for this call.

        Returns:
            List of RetrievedChunk ordered by descending similarity score.
        """
        k = top_k if top_k is not None else self.top_k
        query_vec = self.embedder.embed(query)
        raw = self.vector_store.search(query_vec, top_k=k)

        chunks = [self._to_chunk(row) for row in raw]

        if self.score_threshold is not None:
            chunks = [c for c in chunks if c.score >= self.score_threshold]

        logger.debug("Retrieved %d chunks for query: %.60s", len(chunks), query)
        return chunks

    def retrieve_with_stats(
        self, query: str, top_k: Optional[int] = None
    ) -> Tuple[List[RetrievedChunk], Dict]:
        """Same as retrieve() but also returns timing and score statistics."""
        t0 = time.time()
        chunks = self.retrieve(query, top_k=top_k)
        elapsed_ms = (time.time() - t0) * 1000

        scores = [c.score for c in chunks]
        stats = {
            "num_chunks": len(chunks),
            "latency_ms": round(elapsed_ms, 1),
            "top_score":  round(max(scores), 4) if scores else 0.0,
            "min_score":  round(min(scores), 4) if scores else 0.0,
            "avg_score":  round(sum(scores) / len(scores), 4) if scores else 0.0,
        }
        return chunks, stats

    def _to_chunk(self, row: Dict) -> RetrievedChunk:
        """Map a raw DB result row dict to a typed RetrievedChunk."""
        page = row.get("page_num") or 0
        return RetrievedChunk(
            chunk_id=      row.get("chunk_id", ""),
            text=          row.get("text", ""),
            score=         float(row.get("score", 0.0)),
            section_id=    row.get("section_id", "") or "",
            chapter_id=    row.get("chapter_id", "") or "",
            section_title= row.get("section_title", "") or "",
            page_start=    page,
            page_end=      page,
            chunk_index=   row.get("chunk_index", 0) or 0,
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_retriever(
    embedder,
    vector_store,
    cfg: Optional[Dict] = None,
) -> Retriever:
    """
    Factory — build a Retriever from a config dict.

    Args:
        embedder:     Configured Embedder instance.
        vector_store: Configured PgVectorStore instance.
        cfg:          Retrieval config dict (top_k, score_threshold).

    Returns:
        Configured Retriever instance.
    """
    cfg = cfg or {}
    return Retriever(
        embedder=embedder,
        vector_store=vector_store,
        top_k=cfg.get("top_k", 5),
        score_threshold=cfg.get("score_threshold"),
    )
