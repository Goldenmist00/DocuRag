"""
entity_extractor.py
===================
Extract entities and key concepts from document chunks to build
a knowledge graph for multi-hop retrieval.

Uses a hybrid approach:
  1. Fast regex/heuristic extraction (proper nouns, section refs,
     capitalised terms, acronyms) — no API cost.
  2. TF-IDF keyword overlap between chunk pairs to detect shared
     concepts and create graph edges.

Avoids LLM calls during ingestion to keep upload latency low.
"""

import hashlib
import logging
import re
from collections import Counter, defaultdict
from typing import Dict, List, Set, Tuple

logger = logging.getLogger(__name__)

_ACRONYM_RE = re.compile(r"\b[A-Z]{2,6}\b")

_PROPER_NOUN_RE = re.compile(
    r"\b([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,}){0,3})\b"
)

_SECTION_REF_RE = re.compile(
    r"(?:see|refer\s+to|described\s+in|discussed\s+in|"
    r"as\s+(?:mentioned|noted|explained)\s+in)\s+"
    r"(?:Section|Chapter|§)\s*(\d{1,2}(?:\.\d{1,2})?)",
    re.IGNORECASE,
)

_STOP_ENTITIES = {
    "the", "this", "that", "these", "those", "which", "where",
    "when", "what", "how", "who", "will", "can", "may", "also",
    "not", "but", "and", "for", "with", "from", "into", "about",
    "such", "each", "other", "more", "most", "very", "well",
    "however", "therefore", "figure", "table", "chapter", "section",
    "example", "note", "source", "result", "part", "type", "form",
    "case", "use", "way", "one", "two", "three", "see", "new",
    "first", "second", "third", "many", "much", "like", "just",
}

_MIN_ENTITY_LEN = 3
_MIN_KEYWORD_OVERLAP = 2
_MAX_EDGES_PER_NOTEBOOK = 5000


def extract_entities(text: str) -> Set[str]:
    """
    Extract entities from a text chunk using regex heuristics.

    Extracts:
      - Acronyms (2-6 uppercase letters)
      - Proper noun phrases (Capitalised sequences)
      - Section/chapter cross-references

    Args:
        text: Chunk text to extract from.

    Returns:
        Set of normalised entity strings.
    """
    entities: Set[str] = set()

    for m in _ACRONYM_RE.finditer(text):
        term = m.group(0)
        if term.lower() not in _STOP_ENTITIES and len(term) >= 2:
            entities.add(term)

    for m in _PROPER_NOUN_RE.finditer(text):
        term = m.group(1).strip()
        if (
            len(term) >= _MIN_ENTITY_LEN
            and term.lower() not in _STOP_ENTITIES
            and not term.isupper()
        ):
            entities.add(term)

    for m in _SECTION_REF_RE.finditer(text):
        entities.add(f"§{m.group(1)}")

    return entities


def extract_keywords(text: str, top_n: int = 15) -> List[str]:
    """
    Extract top-N significant keywords from text using term frequency.

    Filters stop words and short tokens, then returns by frequency.

    Args:
        text:  Chunk text.
        top_n: Number of keywords to return.

    Returns:
        List of keyword strings sorted by frequency.
    """
    words = re.findall(r"[a-zA-Z]{3,}", text.lower())
    filtered = [w for w in words if w not in _STOP_ENTITIES and len(w) >= _MIN_ENTITY_LEN]
    counts = Counter(filtered)
    return [word for word, _ in counts.most_common(top_n)]


def build_graph_edges(
    chunk_dicts: List[Dict],
    notebook_id: str,
) -> List[Dict]:
    """
    Build knowledge graph edges between chunks that share entities or keywords.

    Strategy:
      1. Extract entities and keywords from each chunk.
      2. Build an inverted index: entity → list of chunk_ids.
      3. For each entity shared by 2+ chunks, create edges between them.
      4. Compute keyword overlap as edge weight (higher overlap = stronger link).
      5. Detect section cross-references and link referenced chunks.

    Args:
        chunk_dicts: List of chunk dicts (must have chunk_id, text, section_id).
        notebook_id: Parent notebook UUID.

    Returns:
        List of edge dicts ready for chunk_graph_db.insert_edges().
    """
    if len(chunk_dicts) < 2:
        return []

    chunk_entities: Dict[str, Set[str]] = {}
    chunk_keywords: Dict[str, Set[str]] = {}
    section_to_chunks: Dict[str, List[str]] = defaultdict(list)

    for c in chunk_dicts:
        cid = c["chunk_id"]
        text = c.get("text", "")
        section_id = c.get("section_id", "")

        chunk_entities[cid] = extract_entities(text)
        chunk_keywords[cid] = set(extract_keywords(text, top_n=20))

        if section_id:
            section_to_chunks[section_id].append(cid)

    entity_index: Dict[str, List[str]] = defaultdict(list)
    for cid, entities in chunk_entities.items():
        for entity in entities:
            entity_index[entity].append(cid)

    edges: List[Dict] = []
    seen_pairs: Set[Tuple[str, str]] = set()

    for entity, chunk_ids in entity_index.items():
        if len(chunk_ids) < 2 or len(chunk_ids) > 50:
            continue

        for i, cid_a in enumerate(chunk_ids):
            for cid_b in chunk_ids[i + 1:]:
                pair = (min(cid_a, cid_b), max(cid_a, cid_b))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)

                kw_a = chunk_keywords.get(cid_a, set())
                kw_b = chunk_keywords.get(cid_b, set())
                overlap = len(kw_a & kw_b)

                if overlap < _MIN_KEYWORD_OVERLAP:
                    continue

                weight = min(1.0, overlap / 10.0)

                edges.append({
                    "source_chunk_id": pair[0],
                    "target_chunk_id": pair[1],
                    "relation_type": "shared_entity",
                    "entity": entity,
                    "weight": round(weight, 3),
                    "notebook_id": notebook_id,
                })

    for c in chunk_dicts:
        cid = c["chunk_id"]
        for entity in chunk_entities.get(cid, set()):
            if not entity.startswith("§"):
                continue
            ref_section = entity[1:]
            target_chunks = section_to_chunks.get(ref_section, [])
            for target_cid in target_chunks:
                if target_cid == cid:
                    continue
                pair = (min(cid, target_cid), max(cid, target_cid))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)

                edges.append({
                    "source_chunk_id": cid,
                    "target_chunk_id": target_cid,
                    "relation_type": "cross_reference",
                    "entity": entity,
                    "weight": 0.9,
                    "notebook_id": notebook_id,
                })

    _add_keyword_overlap_edges(
        chunk_dicts, chunk_keywords, seen_pairs, edges, notebook_id,
    )

    if len(edges) > _MAX_EDGES_PER_NOTEBOOK:
        edges.sort(key=lambda e: e["weight"], reverse=True)
        edges = edges[:_MAX_EDGES_PER_NOTEBOOK]

    logger.info(
        "Built %d graph edges for notebook %s from %d chunks",
        len(edges), notebook_id, len(chunk_dicts),
    )
    return edges


def _add_keyword_overlap_edges(
    chunk_dicts: List[Dict],
    chunk_keywords: Dict[str, Set[str]],
    seen_pairs: Set[Tuple[str, str]],
    edges: List[Dict],
    notebook_id: str,
    min_overlap: int = 5,
) -> None:
    """
    Add edges between chunk pairs with high keyword overlap even if
    they don't share named entities. Catches topically related chunks
    that discuss the same concepts with different terminology.

    Uses an inverted keyword index (keyword -> chunk_ids) instead of
    O(N^2) pairwise comparison. Candidate pairs are discovered via the
    index, then exact overlap is computed only for those candidates.

    Args:
        chunk_dicts:    Full list of chunk dicts.
        chunk_keywords: Pre-computed keyword sets per chunk.
        seen_pairs:     Already-linked pairs to skip.
        edges:          Mutable list to append new edges to.
        notebook_id:    Parent notebook UUID.
        min_overlap:    Minimum shared keywords to create an edge.
    """
    kw_index: Dict[str, List[str]] = defaultdict(list)
    for c in chunk_dicts:
        cid = c["chunk_id"]
        for kw in chunk_keywords.get(cid, set()):
            kw_index[kw].append(cid)

    candidate_counts: Counter = Counter()
    for kw, cids in kw_index.items():
        if len(cids) < 2 or len(cids) > 100:
            continue
        for i, cid_a in enumerate(cids):
            for cid_b in cids[i + 1:]:
                pair = (min(cid_a, cid_b), max(cid_a, cid_b))
                candidate_counts[pair] += 1

    for pair, shared_count in candidate_counts.items():
        if shared_count < min_overlap:
            continue
        if pair in seen_pairs:
            continue

        kw_a = chunk_keywords.get(pair[0], set())
        kw_b = chunk_keywords.get(pair[1], set())
        overlap_kws = kw_a & kw_b
        overlap = len(overlap_kws)

        if overlap < min_overlap:
            continue

        seen_pairs.add(pair)
        weight = min(1.0, overlap / 15.0)
        edges.append({
            "source_chunk_id": pair[0],
            "target_chunk_id": pair[1],
            "relation_type": "keyword_overlap",
            "entity": ", ".join(sorted(overlap_kws)[:5]),
            "weight": round(weight, 3),
            "notebook_id": notebook_id,
        })
