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


# ---------------------------------------------------------------------------
# Extraction & Cleaning
# ---------------------------------------------------------------------------

def _clean_text(text: str) -> str:
    """
    Advanced cleaning of formatting artifacts & OCR noise.
    
    Args:
        text: Raw text from PDF extraction
        
    Returns:
        Cleaned text with artifacts removed
    """
    # Strip known artifacts
    for pattern in _ARTIFACTS_RE:
        text = pattern.sub("", text)
    
    # Standard cleaning
    text = text.replace("\f", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_pages(pdf_path: str) -> List[PageRecord]:
    """
    Memory-efficient PDF text extraction with error handling.
    
    Args:
        pdf_path: Path to PDF file
        
    Returns:
        List of PageRecord objects with cleaned text
        
    Raises:
        FileNotFoundError: If PDF file doesn't exist
        RuntimeError: If PDF extraction fails
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    records: List[PageRecord] = []
    try:
        with fitz.open(str(pdf_path)) as doc:
            total_pages = len(doc)
            logger.info(f"Extracting {total_pages} pages from PDF...")
            
            for page_idx in range(total_pages):
                try:
                    raw_text = doc[page_idx].get_text("text")
                    records.append(PageRecord(
                        page_number=page_idx + 1,
                        text=_clean_text(raw_text)
                    ))
                except Exception as e:
                    logger.warning(f"Failed to extract page {page_idx + 1}: {e}")
                    # Add empty page record to maintain page numbering
                    records.append(PageRecord(page_number=page_idx + 1, text=""))
            
            logger.info(f"✓ Extracted {len(records)} pages")
            return records
            
    except Exception as e:
        raise RuntimeError(f"PDF extraction failed: {e}") from e


# ---------------------------------------------------------------------------
# Hierarchical Section Detection
# ---------------------------------------------------------------------------

def detect_sections(pages: List[PageRecord]) -> List[SectionBlock]:
    """
    Detect Chapter/Section hierarchy for better citation anchoring.
    
    Args:
        pages: List of PageRecord objects
        
    Returns:
        List of SectionBlock objects with hierarchical metadata
    """
    if not pages:
        logger.warning("No pages provided for section detection")
        return []
    
    full_text_parts: List[str] = []
    offset_to_page: List[int] = []

    for record in pages:
        chunk = record.text + "\n\n"
        full_text_parts.append(chunk)
        offset_to_page.extend([record.page_number] * len(chunk))

    full_text = "".join(full_text_parts)
    logger.info(f"Detecting sections in {len(full_text)} characters...")

    # Find Chapters and Sections
    chapters = list(_CHAPTER_RE.finditer(full_text))
    sections = list(_SECTION_RE.finditer(full_text))
    
    # Combine and sort markers by offset
    markers = []
    for m in chapters:
        markers.append({"type": "chapter", "match": m, "offset": m.start()})
    for m in sections:
        markers.append({"type": "section", "match": m, "offset": m.start()})
    
    markers.sort(key=lambda x: x["offset"])

    if not markers:
        return [SectionBlock(
            chapter_id="0", section_id="0.0", section_title="Full Text",
            page_start=1, page_end=pages[-1].page_number, text=full_text
        )]

    blocks: List[SectionBlock] = []
    current_chapter = "0"

    for i, marker in enumerate(markers):
        start = marker["offset"]
        end = markers[i+1]["offset"] if i+1 < len(markers) else len(full_text)
        text = full_text[start:end].strip()
        
        match = marker["match"]
        if marker["type"] == "chapter":
            current_chapter = match.group(1)
            # Create a block for chapter intro text (before first section)
            # Only if there's substantial text before next marker
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
                    text=text
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
            text=text
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
