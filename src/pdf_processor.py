"""
pdf_processor.py
================
Phase 1 — Corpus Ingestion & Metadata Preparation
(Aligned with SKILLS.md standards: Pydantic, Hierarchical Parsing, Advanced Cleaning)

Responsibilities:
  1. Extract raw text page-by-page from the OpenStax Psychology 2e PDF.
  2. Detect Chapter and Section headers to build a hierarchical metadata path.
  3. Clean formatting artifacts (headers/footers/OCR noise).
  4. Perform section-aware chunking with Pydantic validation.
  5. Persist JSONL with rigorous metadata for citation anchoring.
"""

import re
import json
import hashlib
import logging
import unicodedata
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Optional, Tuple, Dict
from pydantic import BaseModel, Field, ConfigDict

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pydantic Models (Type-safe & Validated - Aligned with SKILLS.md)
# ---------------------------------------------------------------------------

class PageRecord(BaseModel):
    """Raw text extracted from a single PDF page."""
    page_number: int
    text: str


class SectionBlock(BaseModel):
    """Contiguous text belonging to one detected section or chapter."""
    chapter_id: str
    section_id: str
    section_title: str
    page_start: int
    page_end: int
    text: str


class Chunk(BaseModel):
    """
    A single text chunk with full metadata.
    Aligned with SKILLS.md: chunk_id, section_identifier, page_number, raw_text.
    """
    model_config = ConfigDict(extra='ignore', populate_by_name=True)

    chunk_id: str = Field(..., description="Deterministic unique ID")
    text: str = Field(..., alias="raw_text")
    section_id: str
    chapter_id: str
    section_title: str
    page_start: int
    page_end: int
    # stored as chunk_index in DB — alias keeps JSONL backward-compatible
    chunk_index: int = Field(0, alias="chunk_index_in_section")
    char_count: int
    word_count: int

    @property
    def page_num(self) -> int:
        """Convenience alias used by vector_store insert."""
        return self.page_start


# ---------------------------------------------------------------------------
# Constants & Regex
# ---------------------------------------------------------------------------

DEFAULT_CHUNK_SIZE    = 2000
DEFAULT_CHUNK_OVERLAP = 200
DEFAULT_MIN_CHUNK     = 150

# Regex for Chapters: "Chapter 1 Introduction"
_CHAPTER_RE = re.compile(r"^\s*Chapter\s+(\d+)", re.MULTILINE | re.IGNORECASE)

# Regex for Sections: "1.1 What Is Psychology?"
_SECTION_RE = re.compile(r"^\s*(\d{1,2}\.\d{1,2})\s+(.+)", re.MULTILINE)

# Sentence boundary
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+")

# Artifacts to strip (OpenStax specific)
_ARTIFACTS_RE = [
    re.compile(r"OpenStax Psychology 2e", re.IGNORECASE),
    re.compile(r"Access for free at openstax.org", re.IGNORECASE),
]

_DEHYPHEN_RE = re.compile(r"(\w)-\n(\w)")
_INLINE_PAGE_NUM_RE = re.compile(r"^\s*\d{1,4}\s*$", re.MULTILINE)

# Non-content structural patterns to strip
_STRUCTURAL_NOISE_RE = [
    re.compile(r"^\s*(?:Figure|Table|Chart)\s+\d+[\.\:]?\s*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^\s*(?:Source|Note|Notes)\s*:\s*$", re.MULTILINE | re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Extraction & Cleaning
# ---------------------------------------------------------------------------

def _clean_text(text: str) -> str:
    """
    Clean formatting artifacts, OCR noise, and PDF extraction quirks.

    Handles: known artifacts, dehyphenation across line breaks,
    Unicode ligature normalization, inline page numbers, and
    structural noise lines.

    Args:
        text: Raw text from PDF extraction.

    Returns:
        Cleaned text.
    """
    for pattern in _ARTIFACTS_RE:
        text = pattern.sub("", text)

    text = unicodedata.normalize("NFKC", text)

    text = _DEHYPHEN_RE.sub(r"\1\2", text)

    text = _INLINE_PAGE_NUM_RE.sub("", text)

    for pattern in _STRUCTURAL_NOISE_RE:
        text = pattern.sub("", text)

    text = text.replace("\f", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_page_blocks_sorted(page: fitz.Page) -> str:
    """
    Extract text from a page using block-level bounding boxes to fix
    multi-column reading order.

    PyMuPDF's ``get_text("text")`` reads top-to-bottom which interleaves
    columns. This function sorts text blocks by column position first
    (left half vs right half), then top-to-bottom within each column.

    Args:
        page: A PyMuPDF page object.

    Returns:
        Concatenated text in corrected reading order.
    """
    blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
    text_blocks = []
    page_width = page.rect.width
    mid_x = page_width / 2

    for block in blocks:
        if block["type"] != 0:
            continue
        lines_text = []
        for line in block.get("lines", []):
            spans_text = "".join(span.get("text", "") for span in line.get("spans", []))
            if spans_text.strip():
                lines_text.append(spans_text)
        if lines_text:
            block_x0 = block["bbox"][0]
            block_y0 = block["bbox"][1]
            col = 0 if block_x0 < mid_x else 1
            text_blocks.append((col, block_y0, "\n".join(lines_text)))

    text_blocks.sort(key=lambda b: (b[0], b[1]))
    return "\n\n".join(t for _, _, t in text_blocks)


def _detect_repeated_lines(
    pages_text: List[str],
    sample_size: int = 20,
    threshold: float = 0.6,
) -> set:
    """
    Detect header/footer/watermark lines that repeat across many pages.

    Collects the first and last few lines of each page, then flags
    any line appearing on more than ``threshold`` fraction of pages.

    Args:
        pages_text: List of raw page texts.
        sample_size: How many pages to sample from start and end.
        threshold: Fraction of pages a line must appear on to be flagged.

    Returns:
        Set of normalised line strings to strip.
    """
    if len(pages_text) < 4:
        return set()

    line_page_count: Counter = Counter()
    total = len(pages_text)

    for page_text in pages_text:
        lines = page_text.split("\n")
        edge_lines = set()
        for line in lines[:3] + lines[-3:]:
            normalised = line.strip().lower()
            if len(normalised) > 3:
                edge_lines.add(normalised)
        for nl in edge_lines:
            line_page_count[nl] += 1

    min_count = int(total * threshold)
    return {line for line, count in line_page_count.items() if count >= min_count}


def extract_pages(pdf_path: str) -> List[PageRecord]:
    """
    PDF text extraction with multi-column fix and header/footer stripping.

    Pipeline:
      1. Extract text using block-level bounding boxes (fixes column order).
      2. Detect repeated edge lines across pages (headers/footers/watermarks).
      3. Strip detected repeated lines from each page.
      4. Clean remaining artifacts via ``_clean_text``.

    Args:
        pdf_path: Path to PDF file.

    Returns:
        List of PageRecord objects with cleaned text.

    Raises:
        FileNotFoundError: If PDF file doesn't exist.
        RuntimeError: If PDF extraction fails.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    raw_texts: List[str] = []
    try:
        with fitz.open(str(pdf_path)) as doc:
            total_pages = len(doc)
            logger.info("Extracting %d pages from PDF...", total_pages)

            for page_idx in range(total_pages):
                try:
                    raw_texts.append(_extract_page_blocks_sorted(doc[page_idx]))
                except Exception:
                    try:
                        raw_texts.append(doc[page_idx].get_text("text"))
                    except Exception as e:
                        logger.warning("Failed to extract page %d: %s", page_idx + 1, e)
                        raw_texts.append("")

    except Exception as e:
        raise RuntimeError(f"PDF extraction failed: {e}") from e

    repeated = _detect_repeated_lines(raw_texts)
    if repeated:
        logger.info("Stripping %d repeated header/footer/watermark lines", len(repeated))

    records: List[PageRecord] = []
    for idx, text in enumerate(raw_texts):
        if repeated:
            lines = text.split("\n")
            lines = [l for l in lines if l.strip().lower() not in repeated]
            text = "\n".join(lines)
        records.append(PageRecord(page_number=idx + 1, text=_clean_text(text)))

    logger.info("Extracted %d pages", len(records))
    return records


# ---------------------------------------------------------------------------
# Hierarchical Section Detection
# ---------------------------------------------------------------------------

_TOC_LINE_RE = re.compile(
    r"^\s*\d{1,2}(?:\.\d{1,2})?\s+.{3,60}\.{2,}\s*\d{1,4}\s*$",
    re.MULTILINE,
)

_BACKMATTER_RE = re.compile(
    r"^\s*(Appendix|Glossary|Index|Bibliography|References|Works Cited)\b",
    re.MULTILINE | re.IGNORECASE,
)


def _is_toc_page(text: str) -> bool:
    """
    Detect Table of Contents pages by counting lines that look like
    "Section Title ......... 42".

    Args:
        text: Cleaned page text.

    Returns:
        True if the page is likely a TOC page.
    """
    toc_hits = len(_TOC_LINE_RE.findall(text))
    total_lines = max(1, len([l for l in text.split("\n") if l.strip()]))
    return toc_hits >= 3 and toc_hits / total_lines > 0.3


def detect_sections(pages: List[PageRecord]) -> List[SectionBlock]:
    """
    Detect Chapter/Section hierarchy for better citation anchoring.

    Also:
      - Skips pages detected as Table of Contents.
      - Tags appendix/glossary/index sections with distinct chapter_id
        so they can be filtered or down-weighted at retrieval time.

    Args:
        pages: List of PageRecord objects.

    Returns:
        List of SectionBlock objects with hierarchical metadata.
    """
    if not pages:
        logger.warning("No pages provided for section detection")
        return []

    filtered_pages: List[PageRecord] = []
    toc_skipped = 0
    for record in pages:
        if _is_toc_page(record.text):
            toc_skipped += 1
            continue
        filtered_pages.append(record)

    if toc_skipped:
        logger.info("Skipped %d Table of Contents pages", toc_skipped)

    if not filtered_pages:
        logger.warning("All pages were TOC — returning empty")
        return []

    full_text_parts: List[str] = []
    offset_to_page: List[int] = []

    for record in filtered_pages:
        chunk = record.text + "\n\n"
        full_text_parts.append(chunk)
        offset_to_page.extend([record.page_number] * len(chunk))

    full_text = "".join(full_text_parts)
    logger.info("Detecting sections in %d characters...", len(full_text))

    chapters = list(_CHAPTER_RE.finditer(full_text))
    sections = list(_SECTION_RE.finditer(full_text))

    markers = []
    for m in chapters:
        markers.append({"type": "chapter", "match": m, "offset": m.start()})
    for m in sections:
        markers.append({"type": "section", "match": m, "offset": m.start()})

    backmatter = list(_BACKMATTER_RE.finditer(full_text))
    for m in backmatter:
        markers.append({"type": "backmatter", "match": m, "offset": m.start()})

    markers.sort(key=lambda x: x["offset"])

    if not markers:
        return [SectionBlock(
            chapter_id="0", section_id="0.0", section_title="Full Text",
            page_start=1, page_end=filtered_pages[-1].page_number, text=full_text
        )]

    blocks: List[SectionBlock] = []
    current_chapter = "0"
    in_backmatter = False

    first_offset = markers[0]["offset"]
    if first_offset > 100:
        preface_text = full_text[:first_offset].strip()
        if preface_text:
            p_start = offset_to_page[0]
            p_end = offset_to_page[min(first_offset, len(offset_to_page) - 1)]
            blocks.append(SectionBlock(
                chapter_id="0",
                section_id="0.0",
                section_title="Preface",
                page_start=p_start,
                page_end=p_end,
                text=preface_text,
            ))
            logger.info("Captured %d chars of pre-chapter text as Preface", len(preface_text))

    for i, marker in enumerate(markers):
        start = marker["offset"]
        end = markers[i+1]["offset"] if i+1 < len(markers) else len(full_text)
        text = full_text[start:end].strip()

        match = marker["match"]

        if marker["type"] == "backmatter":
            in_backmatter = True
            bm_title = match.group(1).strip().title()
            current_chapter = f"BM_{bm_title}"
            section_id = f"{current_chapter}.0"
            p_start = offset_to_page[start]
            p_end = offset_to_page[min(end, len(offset_to_page)-1)]
            blocks.append(SectionBlock(
                chapter_id=current_chapter,
                section_id=section_id,
                section_title=bm_title,
                page_start=p_start,
                page_end=p_end,
                text=text,
            ))
            continue

        if marker["type"] == "chapter":
            current_chapter = match.group(1)
            in_backmatter = False
            if i+1 < len(markers) and end - start > 100:
                section_id = f"{current_chapter}.0"
                section_title = f"Chapter {current_chapter} Introduction"
                p_start = offset_to_page[start]
                p_end = offset_to_page[min(end, len(offset_to_page)-1)]
                blocks.append(SectionBlock(
                    chapter_id=current_chapter,
                    section_id=section_id,
                    section_title=section_title,
                    page_start=p_start,
                    page_end=p_end,
                    text=text,
                ))
            continue

        section_id = match.group(1)
        section_title = f"{section_id} {match.group(2).strip()}"

        p_start = offset_to_page[start]
        p_end = offset_to_page[min(end, len(offset_to_page)-1)]

        blocks.append(SectionBlock(
            chapter_id=current_chapter,
            section_id=section_id,
            section_title=section_title,
            page_start=p_start,
            page_end=p_end,
            text=text,
        ))

    return blocks


# ---------------------------------------------------------------------------
# Chunking & Persistence
# ---------------------------------------------------------------------------

def _chunk_single_section(
    args: Tuple,
) -> List[Chunk]:
    """
    Chunk one SectionBlock into overlapping Chunk objects.
    Module-level so ThreadPoolExecutor can use it.

    Args:
        args: (section, chunk_size, chunk_overlap, min_chunk)

    Returns:
        List of Chunk objects for this section.
    """
    section, chunk_size, chunk_overlap, min_chunk = args
    sentences = [s.strip() for s in _SENTENCE_END_RE.split(section.text) if s.strip()]

    chunks: List[Chunk] = []
    current_chunk_sentences: List[str] = []
    current_len = 0
    idx = 0

    for sentence in sentences:
        s_len = len(sentence) + 1
        if current_len + s_len > chunk_size and current_chunk_sentences:
            chunk_text = " ".join(current_chunk_sentences)
            if len(chunk_text) >= min_chunk:
                cid = hashlib.sha256(
                    f"{section.section_id}{idx}{chunk_text[:32]}".encode()
                ).hexdigest()[:16]
                chunks.append(Chunk(
                    chunk_id=cid, raw_text=chunk_text,
                    section_id=section.section_id, chapter_id=section.chapter_id,
                    section_title=section.section_title,
                    page_start=section.page_start, page_end=section.page_end,
                    chunk_index_in_section=idx, char_count=len(chunk_text),
                    word_count=len(chunk_text.split()),
                ))
                idx += 1

            # Overlap: keep last N sentences up to overlap budget
            overlap_sentences: List[str] = []
            overlap_len = 0
            for sent in reversed(current_chunk_sentences):
                sent_len = len(sent) + 1
                if overlap_len + sent_len <= chunk_overlap:
                    overlap_sentences.insert(0, sent)
                    overlap_len += sent_len
                else:
                    break
            current_chunk_sentences = overlap_sentences
            current_len = overlap_len

        current_chunk_sentences.append(sentence)
        current_len += s_len

    # Final chunk
    if current_chunk_sentences:
        chunk_text = " ".join(current_chunk_sentences)
        if len(chunk_text) >= min_chunk:
            cid = hashlib.sha256(
                f"{section.section_id}{idx}{chunk_text[:32]}".encode()
            ).hexdigest()[:16]
            chunks.append(Chunk(
                chunk_id=cid, raw_text=chunk_text,
                section_id=section.section_id, chapter_id=section.chapter_id,
                section_title=section.section_title,
                page_start=section.page_start, page_end=section.page_end,
                chunk_index_in_section=idx, char_count=len(chunk_text),
                word_count=len(chunk_text.split()),
            ))

    return chunks


def chunk_sections(
    sections: List[SectionBlock],
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    min_chunk: int = DEFAULT_MIN_CHUNK,
) -> List[Chunk]:
    """
    Produce overlapping chunks with sentence-boundary awareness.
    Parallelized across sections using ThreadPoolExecutor.

    Args:
        sections:      List of SectionBlock objects.
        chunk_size:    Maximum characters per chunk.
        chunk_overlap: Characters to overlap between chunks.
        min_chunk:     Minimum chunk size to keep.

    Returns:
        List of Chunk objects with metadata, in section order.
    """
    if not sections:
        logger.warning("No sections provided for chunking")
        return []

    logger.info(
        "Chunking %d sections in parallel (size=%d, overlap=%d)...",
        len(sections), chunk_size, chunk_overlap,
    )

    args = [(s, chunk_size, chunk_overlap, min_chunk) for s in sections]

    # ThreadPoolExecutor (Windows-compatible, avoids spawn overhead)
    with ThreadPoolExecutor() as executor:
        results = list(executor.map(_chunk_single_section, args))

    all_chunks = [chunk for section_chunks in results for chunk in section_chunks]
    logger.info("✓ Produced %d chunks from %d sections", len(all_chunks), len(sections))
    return all_chunks


def save_chunks(chunks: List[Chunk], path: str) -> None:
    """
    Save chunks to JSONL file with Pydantic serialization.
    
    Args:
        chunks: List of Chunk objects
        path: Output file path
    """
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for c in chunks:
                f.write(c.model_dump_json(by_alias=True) + "\n")
        logger.info(f"✓ Saved {len(chunks)} chunks to {path}")
    except Exception as e:
        raise RuntimeError(f"Failed to save chunks: {e}") from e


def load_chunks(path: str) -> List[Chunk]:
    """
    Load and validate chunks from JSONL file with Pydantic.
    
    Args:
        path: Input file path
        
    Returns:
        List of validated Chunk objects
        
    Raises:
        FileNotFoundError: If file doesn't exist
        RuntimeError: If validation fails
    """
    if not Path(path).exists():
        raise FileNotFoundError(f"Chunks file not found: {path}")
    
    try:
        chunks = []
        with open(path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                if line.strip():
                    try:
                        chunks.append(Chunk.model_validate_json(line))
                    except Exception as e:
                        logger.warning(f"Skipping invalid chunk at line {line_num}: {e}")
        
        logger.info(f"✓ Loaded {len(chunks)} chunks from {path}")
        return chunks
    except Exception as e:
        raise RuntimeError(f"Failed to load chunks: {e}") from e


def verify_chunks(chunks: List[Chunk]) -> Dict:
    """
    Quality audit for the ingestion pipeline.
    
    Args:
        chunks: List of Chunk objects to verify
        
    Returns:
        Dictionary with statistics and validation results
    """
    if not chunks:
        return {
            "total_chunks": 0,
            "unique_sections": 0,
            "unique_chapters": 0,
            "avg_char_count": 0,
            "avg_word_count": 0,
            "min_char_count": 0,
            "max_char_count": 0,
            "page_range": (0, 0),
            "errors": ["No chunks produced!"],
            "warnings": []
        }

    char_counts = [c.char_count for c in chunks]
    word_counts = [c.word_count for c in chunks]
    pages = [c.page_start for c in chunks] + [c.page_end for c in chunks]

    stats = {
        "total_chunks": len(chunks),
        "unique_sections": len(set(c.section_id for c in chunks)),
        "unique_chapters": len(set(c.chapter_id for c in chunks)),
        "avg_char_count": round(sum(char_counts) / len(chunks), 1),
        "avg_word_count": round(sum(word_counts) / len(chunks), 1),
        "min_char_count": min(char_counts),
        "max_char_count": max(char_counts),
        "page_range": (min(pages), max(pages)),
        "errors": [],
        "warnings": []
    }
    # ID transparency check — duplicates are handled by upsert, warn only
    if len(set(c.chunk_id for c in chunks)) != len(chunks):
        stats["warnings"].append("Duplicate chunk_ids found (will be upserted safely)")
    return stats


def run_ingestion(pdf_path: str, output_path: str, **kwargs) -> Tuple[List[Chunk], Dict]:
    """
    Hierarchical ingestion pipeline with comprehensive error handling.
    
    Args:
        pdf_path: Path to input PDF file
        output_path: Path to output JSONL file
        **kwargs: Additional arguments for chunk_sections
        
    Returns:
        Tuple of (chunks list, statistics dict)
        
    Raises:
        RuntimeError: If any pipeline stage fails
    """
    try:
        logger.info("=" * 60)
        logger.info(f"Starting PDF ingestion: {pdf_path}")
        logger.info("=" * 60)
        
        pages = extract_pages(pdf_path)
        sections = detect_sections(pages)
        logger.info(f"✓ Detected {len(sections)} sections")
        
        chunks = chunk_sections(sections, **kwargs)
        logger.info(f"✓ Created {len(chunks)} chunks")
        
        save_chunks(chunks, output_path)
        stats = verify_chunks(chunks)
        
        logger.info("=" * 60)
        logger.info("✓ Ingestion complete!")
        logger.info(f"  Total chunks: {stats['total_chunks']}")
        logger.info(f"  Sections: {stats['unique_sections']}")
        logger.info(f"  Chapters: {stats['unique_chapters']}")
        logger.info(f"  Page range: {stats['page_range']}")
        logger.info("=" * 60)
        
        return chunks, stats
        
    except Exception as e:
        logger.error(f"Ingestion failed: {e}", exc_info=True)
        raise RuntimeError(f"PDF ingestion failed: {e}") from e
