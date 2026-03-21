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
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Union

import numpy as np

from src.db import source_db, chunk_graph_db, chunk_db

logger = logging.getLogger(__name__)

MIN_PER_SOURCE_K = 5
MIN_GUARANTEED_PER_SOURCE = 3

_SOURCE_BOOST_RATIO = 0.7
_OTHER_MIN_SLOTS = 1


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
            chunks = self._per_source_retrieve(query_vec, k, notebook_id, query)
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

    def retrieve_multihop(
        self,
        query: str,
        top_k: Optional[int] = None,
        notebook_id: Optional[str] = None,
        max_hops: int = 1,
        expansion_k: int = 3,
        query_vec: Optional[np.ndarray] = None,
    ) -> List[RetrievedChunk]:
        """
        Multi-hop retrieval: source-aware search + graph edge expansion.

        Hop 0: Source-aware per-source retrieval — if the query mentions
               a source name, that source gets boosted allocation.
        Hop 1+: Follow chunk_graph edges from retrieved chunks, fetch
                 neighbor chunks, score them against the query, and merge
                 the best ones into the result set.

        Args:
            query:        Natural-language question.
            top_k:        Final number of chunks to return.
            notebook_id:  If provided, restrict to this notebook.
            max_hops:     Number of graph traversal hops (default 1).
            expansion_k:  Max neighbor chunks to add per hop.
            query_vec:    Pre-computed embedding; skips re-embedding if
                          provided (used by batch processing).

        Returns:
            List of RetrievedChunk ordered by combined score.
        """
        k = top_k if top_k is not None else self.top_k

        if query_vec is None:
            query_vec = self.embedder.embed(query)

        if notebook_id:
            hop0 = self._per_source_retrieve(query_vec, k, notebook_id, query)
        else:
            raw = self.vector_store.search(query_vec, top_k=k)
            hop0 = [self._to_chunk(row) for row in raw]

        if self.score_threshold is not None:
            hop0 = [c for c in hop0 if c.score >= self.score_threshold]

        if not hop0 or not notebook_id:
            logger.info(
                "Multi-hop: returning %d hop-0 chunks (no graph expansion)",
                len(hop0),
            )
            return hop0

        sources = source_db.list_sources(notebook_id)
        source_name_map = {s["id"]: s.get("name", "") for s in sources}

        seen_ids = {c.chunk_id for c in hop0}
        all_chunks = list(hop0)

        current_ids = [c.chunk_id for c in hop0]

        for hop in range(max_hops):
            edges = chunk_graph_db.get_neighbors(current_ids, notebook_id=notebook_id)
            if not edges:
                break

            neighbor_ids: set = set()
            for edge in edges:
                for cid in (edge["source_chunk_id"], edge["target_chunk_id"]):
                    if cid not in seen_ids:
                        neighbor_ids.add(cid)

            if not neighbor_ids:
                break

            neighbor_rows = self._fetch_chunks_by_ids(
                list(neighbor_ids), notebook_id,
            )

            scored_neighbors: List[RetrievedChunk] = []
            for row in neighbor_rows:
                emb = row.get("embedding")
                if emb is not None:
                    emb_arr = np.array(emb, dtype=np.float32)
                    norm_q = np.linalg.norm(query_vec)
                    norm_e = np.linalg.norm(emb_arr)
                    if norm_q > 0 and norm_e > 0:
                        cosine = float(np.dot(query_vec, emb_arr) / (norm_q * norm_e))
                    else:
                        cosine = 0.0
                else:
                    cosine = 0.0

                edge_weight = max(
                    (e["weight"] for e in edges
                     if row["chunk_id"] in (e["source_chunk_id"], e["target_chunk_id"])),
                    default=0.5,
                )
                combined = 0.6 * cosine + 0.4 * edge_weight

                src_id = row.get("source_id", "") or ""
                src_name = source_name_map.get(src_id, "")
                chunk = self._to_chunk(row, source_name=src_name)
                chunk.score = round(combined, 4)
                scored_neighbors.append(chunk)

            scored_neighbors.sort(key=lambda c: c.score, reverse=True)
            added = 0
            next_hop_ids = []
            for nb_chunk in scored_neighbors:
                if added >= expansion_k:
                    break
                if nb_chunk.chunk_id not in seen_ids:
                    all_chunks.append(nb_chunk)
                    seen_ids.add(nb_chunk.chunk_id)
                    next_hop_ids.append(nb_chunk.chunk_id)
                    added += 1

            current_ids = next_hop_ids
            logger.info(
                "Multi-hop %d: added %d neighbor chunks from %d edges",
                hop + 1, added, len(edges),
            )

        all_chunks.sort(key=lambda c: c.score, reverse=True)
        result = all_chunks[:k]

        logger.info(
            "Multi-hop retrieval: %d total chunks (hop0=%d, expanded=%d) for query: %.60s",
            len(result), len(hop0), len(result) - len(hop0), query,
        )
        return result

    def _fetch_chunks_by_ids(
        self,
        chunk_ids: List[str],
        notebook_id: Optional[str] = None,
    ) -> List[Dict]:
        """
        Fetch full chunk rows (with embeddings) by chunk_id list.

        Args:
            chunk_ids:   List of chunk_id strings.
            notebook_id: Optional notebook scope.

        Returns:
            List of chunk row dicts including embedding.
        """
        if not chunk_ids:
            return []

        from src.db.connection import get_connection

        placeholders = ",".join(["%s"] * len(chunk_ids))
        params: list = list(chunk_ids)

        where_nb = ""
        if notebook_id:
            where_nb = " AND notebook_id = %s"
            params.append(notebook_id)

        sql = f"""
            SELECT chunk_id, text, section_id, chapter_id,
                   section_title, page_num, chunk_index,
                   char_count, word_count, source_id,
                   embedding
            FROM document_chunks
            WHERE chunk_id IN ({placeholders}){where_nb}
        """

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()

        return [
            {
                "chunk_id": r[0],
                "text": r[1],
                "section_id": r[2],
                "chapter_id": r[3],
                "section_title": r[4],
                "page_num": r[5],
                "chunk_index": r[6],
                "char_count": r[7],
                "word_count": r[8],
                "source_id": r[9],
                "embedding": r[10],
            }
            for r in rows
        ]

    # ------------------------------------------------------------------

    def _per_source_retrieve(
        self,
        query_vec,
        top_k: int,
        notebook_id: str,
        query: str = "",
    ) -> List[RetrievedChunk]:
        """
        Retrieve from each ready source independently and merge using
        source-aware allocation + round-robin interleaving with score
        normalisation.

        Strategy:
          1. Detect if the query explicitly mentions a source name.
             If yes, allocate ``SOURCE_BOOST_RATIO`` of top_k slots to
             that source and distribute the rest evenly.
          2. Over-fetch ``max(MIN_PER_SOURCE_K, top_k)`` chunks per source.
          3. Normalise scores within each source (0-1 range).
          4. Fill slots per source allocation; once a source exhausts its
             allocation, remaining slots go to round-robin across others.
          5. Re-sort by normalised score for final ordering.

        Args:
            query_vec:   Pre-computed embedding of the user query.
            top_k:       Final number of chunks to return.
            notebook_id: Notebook UUID.
            query:       Original query text for source detection.

        Returns:
            Merged list of RetrievedChunk sorted by normalised score descending.
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

        target_source_id = self._detect_source_mention(query, ready)

        per_k = max(MIN_PER_SOURCE_K, top_k)
        name_map = {s["id"]: s.get("name", "") for s in ready}
        source_ids = [s["id"] for s in ready]

        raw_by_source = self.vector_store.search_multi_source(
            query_vec,
            source_ids=source_ids,
            per_source_k=per_k,
            notebook_id=notebook_id,
        )

        by_source: Dict[str, List[RetrievedChunk]] = {}
        for src_key, rows in raw_by_source.items():
            name = name_map.get(src_key, "")
            chunks = [self._to_chunk(row, source_name=name) for row in rows]
            if chunks:
                by_source[src_key] = chunks

        if not by_source:
            return []

        for src_key, chunks in by_source.items():
            chunks.sort(key=lambda c: c.score, reverse=True)
            scores = [c.score for c in chunks]
            s_min = min(scores)
            s_max = max(scores)
            spread = s_max - s_min

            for c in chunks:
                if spread > 0:
                    c.score = round((c.score - s_min) / spread, 4)
                else:
                    c.score = 1.0

        slot_alloc = self._compute_slot_allocation(
            top_k, list(by_source.keys()), target_source_id,
        )

        seen_ids: set = set()
        result: List[RetrievedChunk] = []

        for src_key, alloc in slot_alloc.items():
            if src_key not in by_source:
                continue
            for c in by_source[src_key]:
                if alloc <= 0:
                    break
                if c.chunk_id not in seen_ids:
                    seen_ids.add(c.chunk_id)
                    result.append(c)
                    alloc -= 1

        if len(result) < top_k:
            source_keys = list(by_source.keys())
            max_depth = max(len(v) for v in by_source.values())
            for depth in range(max_depth):
                if len(result) >= top_k:
                    break
                for src_key in source_keys:
                    if len(result) >= top_k:
                        break
                    chunks = by_source[src_key]
                    if depth < len(chunks):
                        c = chunks[depth]
                        if c.chunk_id not in seen_ids:
                            seen_ids.add(c.chunk_id)
                            result.append(c)

        result.sort(key=lambda c: c.score, reverse=True)

        if target_source_id:
            logger.info(
                "Per-source retrieval (source-aware): %d chunks from %d sources, "
                "boosted source=%s",
                len(result), len(by_source), target_source_id,
            )
        else:
            logger.info(
                "Per-source retrieval: %d chunks from %d sources (round-robin + normalised)",
                len(result), len(by_source),
            )
        return result[:top_k]

    # ------------------------------------------------------------------
    # Source-aware helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_source_mention(
        query: str,
        ready_sources: List[Dict],
    ) -> Optional[str]:
        """
        Check if the query references a specific source by name.

        Matches against the source file name (without extension) using
        case-insensitive substring matching.  Requires at least 4 chars
        of the source stem to appear in the query to avoid false positives.

        Args:
            query:          User's natural-language query.
            ready_sources:  List of ready source dicts with "id" and "name".

        Returns:
            source_id of the best-matching source, or None.
        """
        if not query:
            return None

        q_lower = query.lower()
        best_match: Optional[Tuple[str, int]] = None

        for src in ready_sources:
            name = src.get("name", "")
            stem = re.sub(r"\.[^.]+$", "", name)
            stem_lower = stem.lower()
            if len(stem_lower) < 4:
                continue
            tokens = re.split(r"[\s_\-\.]+", stem_lower)
            matched_chars = 0
            for tok in tokens:
                if len(tok) >= 3 and tok in q_lower:
                    matched_chars += len(tok)

            if matched_chars >= 4:
                if best_match is None or matched_chars > best_match[1]:
                    best_match = (src["id"], matched_chars)

        if best_match:
            logger.info(
                "Source-aware detection: matched source_id=%s (%d chars)",
                best_match[0], best_match[1],
            )
        return best_match[0] if best_match else None

    @staticmethod
    def _compute_slot_allocation(
        top_k: int,
        source_keys: List[str],
        target_source_id: Optional[str],
    ) -> Dict[str, int]:
        """
        Compute how many retrieval slots each source gets.

        If ``target_source_id`` is set, that source receives
        ``SOURCE_BOOST_RATIO`` of ``top_k`` slots (min 1).  The remaining
        slots are distributed evenly.  Every non-target source gets at
        least ``_OTHER_MIN_SLOTS`` slots.

        When no target is detected, slots are distributed evenly.

        Args:
            top_k:            Total slots available.
            source_keys:      List of source_id strings.
            target_source_id: The source to boost, or None.

        Returns:
            Dict mapping source_id → number of allocated slots.
        """
        n = len(source_keys)
        alloc: Dict[str, int] = {}

        if not target_source_id or target_source_id not in source_keys:
            per = max(1, top_k // n)
            for sk in source_keys:
                alloc[sk] = per
            return alloc

        boosted = max(1, int(top_k * _SOURCE_BOOST_RATIO))
        remaining = top_k - boosted
        others = [sk for sk in source_keys if sk != target_source_id]
        other_per = max(_OTHER_MIN_SLOTS, remaining // max(1, len(others)))

        alloc[target_source_id] = boosted
        for sk in others:
            alloc[sk] = other_per

        return alloc

    def _build_source_name_map(self, notebook_id: str) -> Dict[str, str]:
        """
        Build a mapping of source_id → display name for all sources
        in a notebook.

        Args:
            notebook_id: Notebook UUID.

        Returns:
            Dict mapping source_id to source name.
        """
        sources = source_db.list_sources(notebook_id)
        return {s["id"]: s.get("name", "") for s in sources}

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
