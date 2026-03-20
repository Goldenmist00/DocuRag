"""
retriever.py
============
Phase 4 — Semantic Retrieval

Wraps Embedder + PgVectorStore into a clean retrieval interface.
Returns typed RetrievedChunk objects with citation helpers used by
both the Generator and the submission pipeline.

Uses per-source retrieval when a notebook has multiple sources,
guaranteeing that every source contributes chunks to the result set.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

from src.db import source_db

logger = logging.getLogger(__name__)

MIN_PER_SOURCE_K = 3


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class RetrievedChunk:
    """A single retrieved passage with metadata and similarity score."""

    chunk_id: str
    text: str
    score: float

    section_id: str = ""
    chapter_id: str = ""
    section_title: str = ""
    page_start: int = 0
    page_end: int = 0
    chunk_index: int = 0

    source_id: str = ""
    source_name: str = ""

    def citation(self) -> str:
        """Human-readable citation string for prompt and references."""
        parts: List[str] = []
        if self.source_name:
            parts.append(self.source_name)
        if self.chapter_id:
            parts.append(f"Chapter {self.chapter_id}")
        if self.section_id:
            parts.append(f"\u00a7{self.section_id}")
        if self.section_title:
            parts.append(self.section_title)
        if self.page_start:
            parts.append(f"p.{self.page_start}")
        return " | ".join(parts) if parts else self.chunk_id



# ---------------------------------------------------------------------------
# Retriever
# ---------------------------------------------------------------------------

class Retriever:
    """
    Semantic retriever: embeds a query and fetches the top-k most similar
    chunks from the PostgreSQL vector store.

    When a notebook_id is provided and the notebook has multiple sources,
    retrieval is performed per-source and the results are merged. This
    guarantees every source gets representation in the final set.

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
        top_k: int = 10,
        score_threshold: Optional[float] = None,
    ) -> None:
        self.embedder = embedder
        self.vector_store = vector_store
        self.top_k = top_k
        self.score_threshold = score_threshold

    def retrieve(
        self,
        query: str,
        top_k: Optional[int] = None,
        notebook_id: Optional[str] = None,
    ) -> List[RetrievedChunk]:
        """
        Embed query and return the top-k most similar chunks.

        When ``notebook_id`` is provided the retriever fetches per-source
        results and merges them so every ready source is represented.
        Falls back to a single global search when there is no notebook
        or only one source.

        Args:
            query:       Natural-language question.
            top_k:       Override instance top_k for this call.
            notebook_id: If provided, restrict search to this notebook's chunks.

        Returns:
            List of RetrievedChunk ordered by descending similarity score.
        """
        k = top_k if top_k is not None else self.top_k
        query_vec = self.embedder.embed(query)

        if notebook_id:
            chunks = self._per_source_retrieve(query_vec, k, notebook_id)
        else:
            raw = self.vector_store.search(query_vec, top_k=k)
            chunks = [self._to_chunk(row) for row in raw]

        if self.score_threshold is not None:
            chunks = [c for c in chunks if c.score >= self.score_threshold]

        logger.info(
            "Retrieved %d chunks (top_k=%d) for query: %.60s",
            len(chunks), k, query,
        )
        return chunks

    # ------------------------------------------------------------------

    def _per_source_retrieve(
        self,
        query_vec,
        top_k: int,
        notebook_id: str,
    ) -> List[RetrievedChunk]:
        """
        Retrieve from each ready source independently and merge results.

        Over-fetches per source (``max(MIN_PER_SOURCE_K, top_k)``), then
        de-duplicates, sorts globally by score, and trims to ``top_k``.

        Args:
            query_vec:   Pre-computed embedding of the user query.
            top_k:       Final number of chunks to return.
            notebook_id: Notebook UUID.

        Returns:
            Merged list of RetrievedChunk sorted by score descending.
        """
        sources = source_db.list_sources(notebook_id)
        ready = [s for s in sources if s.get("status") == "ready"]

        if not ready:
            raw = self.vector_store.search(
                query_vec, top_k=top_k, notebook_id=notebook_id,
            )
            return [self._to_chunk(row) for row in raw]

        if len(ready) == 1:
            raw = self.vector_store.search(
                query_vec, top_k=top_k,
                notebook_id=notebook_id, source_id=ready[0]["id"],
            )
            name = ready[0].get("name", "")
            return [self._to_chunk(row, source_name=name) for row in raw]

        per_k = max(MIN_PER_SOURCE_K, top_k)

        all_chunks: List[RetrievedChunk] = []
        for src in ready:
            raw = self.vector_store.search(
                query_vec, top_k=per_k,
                notebook_id=notebook_id, source_id=src["id"],
            )
            name = src.get("name", "")
            all_chunks.extend(self._to_chunk(row, source_name=name) for row in raw)

        seen: set = set()
        unique: List[RetrievedChunk] = []
        for c in all_chunks:
            if c.chunk_id not in seen:
                seen.add(c.chunk_id)
                unique.append(c)

        unique.sort(key=lambda c: c.score, reverse=True)
        return unique[:top_k]

    # ------------------------------------------------------------------

    def _to_chunk(self, row: Dict, source_name: str = "") -> RetrievedChunk:
        """
        Map a raw DB result row dict to a typed RetrievedChunk.

        Args:
            row:         Dict from vector_store.search().
            source_name: Display name of the source (e.g. filename).

        Returns:
            RetrievedChunk instance.
        """
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
            source_id=     row.get("source_id", "") or "",
            source_name=   source_name,
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
        top_k=cfg.get("top_k", 10),
        score_threshold=cfg.get("score_threshold"),
    )
