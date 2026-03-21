"""
chunker.py
==========
Unified chunking service for both batch ingestion and web-upload paths.

Improvements over the original dual-path approach:
  - Recursive hierarchical splitting (paragraphs -> sentences -> clauses -> whitespace)
  - Abbreviation-safe sentence boundary detection
  - Quality filtering (min length, letter ratio, deduplication)
  - Configurable overlap for cross-chunk context preservation
  - Contextual metadata prepending for embedding enrichment
  - Cross-section overlap for boundary context
"""

import hashlib
import logging
import re
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default configuration (overridden by config.yaml at runtime)
# ---------------------------------------------------------------------------

DEFAULT_CHUNK_SIZE = 800
DEFAULT_CHUNK_OVERLAP = 100
DEFAULT_MIN_CHUNK = 150
DEFAULT_MIN_LETTER_RATIO = 0.4
DEFAULT_CROSS_SECTION_OVERLAP = 100

# ---------------------------------------------------------------------------
# Robust sentence splitting
# ---------------------------------------------------------------------------

_ABBREVIATIONS = frozenset({
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr",
    "vs", "etc", "inc", "ltd", "dept", "est",
    "approx", "assn", "avg",
    "fig", "vol", "no", "ch", "sec", "ed", "rev",
    "gen", "gov", "sgt", "cpl", "pvt", "capt",
    "st", "ave", "blvd", "rd",
    "jan", "feb", "mar", "apr", "jun", "jul",
    "aug", "sep", "oct", "nov", "dec",
})

_DOTTED_ABBR_RE = re.compile(r"\b(?:[A-Za-z]\.){2,}")
_SENTENCE_CANDIDATE_RE = re.compile(r"(?<=[.!?])\s+")
_CLAUSE_SPLIT_RE = re.compile(r"(?<=[;:])\s+|\s+(?=—)\s*")
_DECIMAL_TAIL_RE = re.compile(r"\d\.$")


def _is_abbreviation_boundary(text_before: str) -> bool:
    """
    Check whether a period at the end of text_before is an abbreviation
    rather than a true sentence boundary.

    Handles dotted abbreviations (U.S., e.g., i.e.), single-word
    abbreviations (Dr., Fig.), and trailing decimals (3.).

    Args:
        text_before: Text preceding the candidate split point.

    Returns:
        True if the period is part of an abbreviation.
    """
    tail = text_before[-8:]
    if _DOTTED_ABBR_RE.search(tail):
        return True

    words = text_before.rstrip(".").rsplit(None, 1)
    if words:
        last_word = words[-1].lower().rstrip(".")
        if last_word in _ABBREVIATIONS:
            return True

    if _DECIMAL_TAIL_RE.search(tail):
        return True

    return False


def robust_sentence_split(text: str) -> List[str]:
    """
    Split text into sentences with abbreviation and decimal awareness.

    Uses candidate sentence boundaries ([.!?] followed by whitespace)
    then filters out false positives from abbreviations and decimals.

    Args:
        text: Input text to split into sentences.

    Returns:
        List of sentence strings.
    """
    if not text.strip():
        return []

    candidates = list(_SENTENCE_CANDIDATE_RE.finditer(text))
    if not candidates:
        return [text.strip()]

    sentences: List[str] = []
    prev_end = 0

    for match in candidates:
        split_pos = match.start()
        before = text[prev_end:split_pos]

        if before.rstrip().endswith(".") and _is_abbreviation_boundary(before.rstrip()):
            continue

        sentence = before.strip()
        if sentence:
            sentences.append(sentence)
        prev_end = match.end()

    remainder = text[prev_end:].strip()
    if remainder:
        sentences.append(remainder)

    return sentences if sentences else [text.strip()]


# ---------------------------------------------------------------------------
# Recursive hierarchical splitting
# ---------------------------------------------------------------------------

def _split_paragraphs(text: str) -> List[str]:
    """
    Split text on double-newlines, falling back to single newlines.

    Args:
        text: Raw text block.

    Returns:
        List of paragraph strings (empty strings are filtered out).
    """
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paras and text.strip():
        paras = [p.strip() for p in text.split("\n") if p.strip()]
    if not paras and text.strip():
        paras = [text.strip()]
    return paras


def recursive_split(text: str, max_chars: int) -> List[str]:
    """
    Hierarchically split text to stay under max_chars per piece.

    Split priority (largest natural boundary first):
      1. Paragraph breaks (double newline)
      2. Sentence boundaries (abbreviation-safe)
      3. Clause boundaries (semicolons, colons, em-dashes)
      4. Whitespace (last resort)

    Args:
        text: Text to split.
        max_chars: Maximum characters per resulting piece.

    Returns:
        List of text pieces, each at or under max_chars.
    """
    if len(text) <= max_chars:
        return [text]

    paragraphs = _split_paragraphs(text)
    if len(paragraphs) > 1:
        result: List[str] = []
        for para in paragraphs:
            result.extend(recursive_split(para, max_chars))
        return result

    sentences = robust_sentence_split(text)
    if len(sentences) > 1:
        result = []
        for sent in sentences:
            result.extend(recursive_split(sent, max_chars))
        return result

    clauses = [c.strip() for c in _CLAUSE_SPLIT_RE.split(text) if c.strip()]
    if len(clauses) > 1:
        result = []
        for clause in clauses:
            result.extend(recursive_split(clause, max_chars))
        return result

    words = text.split()
    result = []
    current: List[str] = []
    current_len = 0
    for word in words:
        w_len = len(word) + 1
        if current_len + w_len > max_chars and current:
            result.append(" ".join(current))
            current = []
            current_len = 0
        current.append(word)
        current_len += w_len
    if current:
        result.append(" ".join(current))

    return result


# ---------------------------------------------------------------------------
# Quality filters
# ---------------------------------------------------------------------------

def has_enough_content(
    text: str,
    min_chars: int = DEFAULT_MIN_CHUNK,
    min_letter_ratio: float = DEFAULT_MIN_LETTER_RATIO,
) -> bool:
    """
    Check that a chunk has enough alphabetic content to produce a
    meaningful embedding vector.

    Rejects chunks that are mostly numbers, symbols, or list markers.

    Args:
        text: Candidate chunk text.
        min_chars: Minimum character count.
        min_letter_ratio: Minimum fraction of alphabetic characters.

    Returns:
        True if the chunk is worth embedding.
    """
    if len(text) < min_chars:
        return False
    alpha = sum(1 for c in text if c.isalpha())
    return (alpha / len(text)) >= min_letter_ratio


# ---------------------------------------------------------------------------
# Contextual metadata prepending
# ---------------------------------------------------------------------------

def enrich_chunk_text(
    text: str,
    section_title: str,
    chapter_id: str,
) -> str:
    """
    Prepend hierarchical context to chunk text so the embedding
    vector captures document structure.

    Implements the "Contextual Retrieval" pattern: the embedding model
    sees WHERE a chunk lives, improving retrieval for section-specific
    or chapter-specific queries.

    Args:
        text: Raw chunk text.
        section_title: Title of the parent section.
        chapter_id: Parent chapter identifier.

    Returns:
        Text with context header prepended.
    """
    if chapter_id and chapter_id not in ("0", ""):
        return f"[Chapter {chapter_id} | {section_title}] {text}"
    if section_title:
        return f"[{section_title}] {text}"
    return text


# ---------------------------------------------------------------------------
# Core chunking engine
# ---------------------------------------------------------------------------

def chunk_text_with_overlap(
    pieces: List[str],
    chunk_size: int,
    chunk_overlap: int,
    min_chunk: int,
    min_letter_ratio: float,
) -> List[str]:
    """
    Group text pieces into overlapping chunks that respect size limits.

    Each piece (typically a sentence or short paragraph) is accumulated
    until chunk_size is reached, then a new chunk starts. Overlap is
    achieved by carrying forward the last N pieces whose total length
    fits within chunk_overlap.

    Args:
        pieces: Atomic text units (sentences or short paragraphs).
        chunk_size: Maximum characters per chunk.
        chunk_overlap: Characters of overlap between consecutive chunks.
        min_chunk: Minimum character length for a chunk to be kept.
        min_letter_ratio: Minimum alphabetic ratio for quality filter.

    Returns:
        List of chunk text strings that pass quality filters.
    """
    if not pieces:
        return []

    result: List[str] = []
    current_pieces: List[str] = []
    current_len = 0

    for piece in pieces:
        p_len = len(piece) + 1

        if current_len + p_len > chunk_size and current_pieces:
            chunk_text = " ".join(current_pieces)
            if has_enough_content(chunk_text, min_chunk, min_letter_ratio):
                result.append(chunk_text)

            overlap_pieces: List[str] = []
            overlap_len = 0
            for j in range(len(current_pieces) - 1, -1, -1):
                s_len = len(current_pieces[j]) + 1
                if overlap_len + s_len <= chunk_overlap:
                    overlap_pieces.insert(0, current_pieces[j])
                    overlap_len += s_len
                else:
                    break
            current_pieces = overlap_pieces
            current_len = overlap_len

        current_pieces.append(piece)
        current_len += p_len

    if current_pieces:
        chunk_text = " ".join(current_pieces)
        if has_enough_content(chunk_text, min_chunk, min_letter_ratio):
            result.append(chunk_text)

    return result


def chunk_section_text(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    min_chunk: int = DEFAULT_MIN_CHUNK,
    min_letter_ratio: float = DEFAULT_MIN_LETTER_RATIO,
) -> List[str]:
    """
    Chunk a single section's text using recursive splitting and overlap.

    Pipeline:
      1. Recursively split into atomic pieces (respecting paragraphs,
         sentences, clauses, then words).
      2. Group pieces with overlap into chunks.
      3. Filter by quality (length + letter ratio).

    Args:
        text: Section text to chunk.
        chunk_size: Maximum characters per chunk.
        chunk_overlap: Characters to overlap between chunks.
        min_chunk: Minimum chunk size to keep.
        min_letter_ratio: Minimum alphabetic character ratio.

    Returns:
        List of chunk text strings.
    """
    pieces = recursive_split(text, chunk_size)
    return chunk_text_with_overlap(
        pieces, chunk_size, chunk_overlap, min_chunk, min_letter_ratio,
    )


def _page_for_char_offset(
    page_breaks: List[Tuple[int, int]],
    offset: int,
) -> int:
    """
    Resolve the page number for a character offset using page_breaks.

    Args:
        page_breaks: Sorted (local_char_offset, page_number) tuples.
        offset: Character offset within the section text.

    Returns:
        Page number for that offset.
    """
    page = page_breaks[0][1] if page_breaks else 1
    for brk_offset, brk_page in page_breaks:
        if brk_offset <= offset:
            page = brk_page
        else:
            break
    return page


def chunk_sections_unified(
    sections: List,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    min_chunk: int = DEFAULT_MIN_CHUNK,
    min_letter_ratio: float = DEFAULT_MIN_LETTER_RATIO,
    cross_section_overlap: int = DEFAULT_CROSS_SECTION_OVERLAP,
    enrich_context: bool = True,
    dedup: bool = True,
) -> List[Dict]:
    """
    Chunk a list of SectionBlock objects into enriched, deduplicated
    chunk dicts ready for embedding and storage.

    This is the unified entry point that replaces both the batch-path
    sentence chunker and the web-upload paragraph chunker.

    Features:
      - Recursive hierarchical splitting
      - Abbreviation-safe sentence boundaries
      - Configurable overlap
      - Cross-section overlap (trailing text from previous section)
      - Quality filtering (letter ratio + min length)
      - Content-hash deduplication
      - Contextual metadata prepending

    Args:
        sections: List of SectionBlock objects.
        chunk_size: Maximum characters per chunk.
        chunk_overlap: Characters to overlap between consecutive chunks.
        min_chunk: Minimum chunk size to keep.
        min_letter_ratio: Minimum alphabetic character ratio.
        cross_section_overlap: Characters of trailing context to carry
            from the previous section into the first chunk of the next.
        enrich_context: Whether to prepend section/chapter context.
        dedup: Whether to deduplicate chunks by content hash.

    Returns:
        List of chunk dicts with keys: chunk_id, text, section_id,
        chapter_id, section_title, page_num, chunk_index, char_count,
        word_count.
    """
    if not sections:
        logger.warning("No sections provided for chunking")
        return []

    logger.info(
        "Chunking %d sections (size=%d, overlap=%d, cross_section=%d)...",
        len(sections), chunk_size, chunk_overlap, cross_section_overlap,
    )

    chunk_dicts: List[Dict] = []
    chunk_idx = 0
    seen_hashes: set = set() if dedup else None
    prev_section_tail = ""

    for sec_i, section in enumerate(sections):
        section_text = section.text
        if not section_text.strip():
            continue

        if cross_section_overlap > 0 and prev_section_tail:
            section_text = prev_section_tail + " " + section_text

        raw_chunks = chunk_section_text(
            section_text,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            min_chunk=min_chunk,
            min_letter_ratio=min_letter_ratio,
        )

        if cross_section_overlap > 0 and section.text.strip():
            tail = section.text.strip()[-cross_section_overlap:]
            last_space = tail.find(" ")
            prev_section_tail = tail[last_space + 1:] if last_space >= 0 else tail
        else:
            prev_section_tail = ""

        page_breaks = getattr(section, "page_breaks", [])
        has_page_breaks = bool(page_breaks)
        search_start = 0

        for chunk_text in raw_chunks:
            if dedup and seen_hashes is not None:
                content_hash = hashlib.sha256(
                    chunk_text[:128].encode()
                ).hexdigest()[:16]
                if content_hash in seen_hashes:
                    continue
                seen_hashes.add(content_hash)

            if enrich_context:
                enriched = enrich_chunk_text(
                    chunk_text, section.section_title, section.chapter_id,
                )
            else:
                enriched = chunk_text

            if has_page_breaks:
                pos = section.text.find(chunk_text[:80], search_start)
                if pos < 0:
                    pos = search_start
                end_pos = pos + len(chunk_text)
                search_start = max(search_start, pos + 1)
                page_num = _page_for_char_offset(page_breaks, pos)
            else:
                page_num = section.page_start

            cid = hashlib.sha256(
                f"{section.section_id}{chunk_idx}{chunk_text[:64]}".encode()
            ).hexdigest()[:16]

            chunk_dicts.append({
                "chunk_id": cid,
                "text": enriched,
                "section_id": section.section_id,
                "chapter_id": section.chapter_id,
                "section_title": section.section_title,
                "page_num": page_num,
                "chunk_index": chunk_idx,
                "char_count": len(enriched),
                "word_count": len(enriched.split()),
            })
            chunk_idx += 1

    logger.info(
        "Produced %d chunks from %d sections", len(chunk_dicts), len(sections),
    )
    return chunk_dicts
