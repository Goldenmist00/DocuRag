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
    model_config = ConfigDict(extra='ignore')

    chunk_id: str = Field(..., description="Deterministic unique ID")
    text: str = Field(..., alias="raw_text")
    section_id: str
    chapter_id: str
    section_title: str
    page_start: int
    page_end: int
    chunk_index_in_section: int
    char_count: int
    word_count: int


# ---------------------------------------------------------------------------
# Constants & Regex
# ---------------------------------------------------------------------------

DEFAULT_CHUNK_SIZE    = 800
DEFAULT_CHUNK_OVERLAP = 100
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
    """Advanced cleaning of formatting artifacts & OCR noise."""
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
    """Memory-efficient PDF text extraction."""
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    records: List[PageRecord] = []
    with fitz.open(str(pdf_path)) as doc:
        for page_idx in range(len(doc)):
            raw_text = doc[page_idx].get_text("text")
            records.append(PageRecord(
                page_number=page_idx + 1,
                text=_clean_text(raw_text)
            ))
    return records


# ---------------------------------------------------------------------------
# Hierarchical Section Detection
# ---------------------------------------------------------------------------

def detect_sections(pages: List[PageRecord]) -> List[SectionBlock]:
    """Detect Chapter/Section hierarchy for better citation anchoring."""
    full_text_parts: List[str] = []
    offset_to_page: List[int] = []

    for record in pages:
        chunk = record.text + "\n\n"
        full_text_parts.append(chunk)
        offset_to_page.extend([record.page_number] * len(chunk))

    full_text = "".join(full_text_parts)

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
            # Chapter marker itself doesn't need to be a block if it's followed by sections,
            # but we record it to update the context.
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

def chunk_sections(
    sections: List[SectionBlock],
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    min_chunk: int = DEFAULT_MIN_CHUNK
) -> List[Chunk]:
    """Produce overlapping chunks with sentence-boundary awareness."""
    all_chunks = []
    for section in sections:
        sentences = [s.strip() for s in _SENTENCE_END_RE.split(section.text) if s.strip()]
        
        current_chunk_sentences = []
        current_len = 0
        idx = 0

        for sentence in sentences:
            s_len = len(sentence) + 1
            if current_len + s_len > chunk_size and current_chunk_sentences:
                chunk_text = " ".join(current_chunk_sentences)
                if len(chunk_text) >= min_chunk:
                    cid = hashlib.sha256(f"{section.section_id}{idx}{chunk_text[:32]}".encode()).hexdigest()[:16]
                    all_chunks.append(Chunk(
                        chunk_id=cid, raw_text=chunk_text,
                        section_id=section.section_id, chapter_id=section.chapter_id,
                        section_title=section.section_title,
                        page_start=section.page_start, page_end=section.page_end,
                        chunk_index_in_section=idx, char_count=len(chunk_text),
                        word_count=len(chunk_text.split())
                    ))
                    idx += 1
                
                # Handle overlap: keep last N sentences for context preservation
                # Simplification: keep last sentence if it's within overlap budget
                if len(current_chunk_sentences[-1]) < chunk_overlap:
                    current_chunk_sentences = [current_chunk_sentences[-1]]
                else:
                    current_chunk_sentences = []
                current_len = sum(len(s)+1 for s in current_chunk_sentences)

            current_chunk_sentences.append(sentence)
            current_len += s_len

        # Final chunk
        if current_chunk_sentences:
            chunk_text = " ".join(current_chunk_sentences)
            if len(chunk_text) >= min_chunk:
                cid = hashlib.sha256(f"{section.section_id}{idx}{chunk_text[:32]}".encode()).hexdigest()[:16]
                all_chunks.append(Chunk(
                    chunk_id=cid, raw_text=chunk_text,
                    section_id=section.section_id, chapter_id=section.chapter_id,
                    section_title=section.section_title,
                    page_start=section.page_start, page_end=section.page_end,
                    chunk_index_in_section=idx, char_count=len(chunk_text),
                    word_count=len(chunk_text.split())
                ))

    return all_chunks


def save_chunks(chunks: List[Chunk], path: str):
    """Save with Pydantic serialization."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(c.model_dump_json(by_alias=True) + "\n")


def load_chunks(path: str) -> List[Chunk]:
    """Load and validate with Pydantic."""
    chunks = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                chunks.append(Chunk.model_validate_json(line))
    return chunks


def verify_chunks(chunks: List[Chunk]) -> Dict:
    """Quality audit for the ingestion pipeline."""
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
    # ID transparency check
    if len(set(c.chunk_id for c in chunks)) != len(chunks):
        stats["errors"].append("Duplicate chunk_ids found!")
    return stats


def run_ingestion(pdf_path: str, output_path: str, **kwargs) -> Tuple[List[Chunk], Dict]:
    """Hierarchical ingestion pipeline."""
    logger.info(f"Ingesting: {pdf_path}")
    pages = extract_pages(pdf_path)
    sections = detect_sections(pages)
    chunks = chunk_sections(sections, **kwargs)
    save_chunks(chunks, output_path)
    stats = verify_chunks(chunks)
    return chunks, stats
