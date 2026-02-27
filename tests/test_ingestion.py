#!/usr/bin/env python3
"""
test_ingestion.py
=================
Unit and integration tests for Phase 1 — Corpus Ingestion.
(Updated for Pydantic & Hierarchical Parsing)

Run with:
    pytest tests/test_ingestion.py -v
"""

import json
import tempfile
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.pdf_processor import (
    PageRecord,
    SectionBlock,
    Chunk,
    _clean_text,
    _SECTION_RE,
    _CHAPTER_RE,
    detect_sections,
    chunk_sections,
    save_chunks,
    load_chunks,
    verify_chunks,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_TEXT = (
    "Psychology is the scientific study of behavior and mental processes. "
    "It encompasses a wide range of topics including perception, cognition, "
    "emotion, personality, behavior, and interpersonal relationships. "
)

SAMPLE_BOOK_SIM = """
Chapter 1 Introduction

1.1 What Is Psychology?
Psychology is the scientific study of the mind. OpenStax Psychology 2e
Access for free at openstax.org

1.2 History
The history starts with Wundt.
"""

@pytest.fixture
def sample_pages():
    return [
        PageRecord(page_number=1, text="Chapter 1 Introduction\n\n1.1 What Is Psychology?\n" + SAMPLE_TEXT),
        PageRecord(page_number=2, text="1.2 History\nThe history of psychology starts long ago."),
    ]


@pytest.fixture
def sample_sections():
    return [
        SectionBlock(
            chapter_id="1", section_id="1.1", section_title="1.1 What Is Psychology?",
            page_start=1, page_end=1, text=SAMPLE_TEXT * 5
        )
    ]


# ---------------------------------------------------------------------------
# 1. Text cleaning
# ---------------------------------------------------------------------------

def test_cleaning_strips_artifacts():
    dirty = "Some text. OpenStax Psychology 2e. Access for free at openstax.org"
    clean = _clean_text(dirty)
    assert "OpenStax" not in clean
    assert "openstax.org" not in clean
    assert "Some text." in clean


# ---------------------------------------------------------------------------
# 2. Section/Chapter Regex
# ---------------------------------------------------------------------------

def test_chapter_regex():
    text = "Chapter 12 Stress"
    match = _CHAPTER_RE.search(text)
    assert match is not None
    assert match.group(1) == "12"

def test_section_regex():
    text = "1.2 History of Psychology"
    match = _SECTION_RE.search(text)
    assert match is not None
    assert match.group(1) == "1.2"
    assert "History" in match.group(2)


# ---------------------------------------------------------------------------
# 3. detect_sections (Hierarchy)
# ---------------------------------------------------------------------------

def test_detect_sections_hierarchy(sample_pages):
    sections = detect_sections(sample_pages)
    assert len(sections) >= 2
    assert sections[0].chapter_id == "1"
    assert sections[0].section_id == "1.1"
    assert sections[1].chapter_id == "1"
    assert sections[1].section_id == "1.2"


# ---------------------------------------------------------------------------
# 4. chunk_sections & Metadata
# ---------------------------------------------------------------------------

def test_chunk_sections_metadata(sample_sections):
    chunks = chunk_sections(sample_sections, chunk_size=300, chunk_overlap=50)
    assert len(chunks) > 0
    chunk = chunks[0]
    assert isinstance(chunk, Chunk)
    assert chunk.chapter_id == "1"
    assert chunk.section_id == "1.1"
    # Ensure raw_text alias works (as requested in schema: raw_text)
    data = chunk.model_dump(by_alias=True)
    assert "raw_text" in data
    assert data["raw_text"] == chunk.text


# ---------------------------------------------------------------------------
# 5. Pydantic Persistence
# ---------------------------------------------------------------------------

def test_save_load_roundtrip(sample_sections):
    chunks = chunk_sections(sample_sections, chunk_size=300)
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tmp:
        path = tmp.name
    
    save_chunks(chunks, path)
    loaded = load_chunks(path)
    
    assert len(loaded) == len(chunks)
    assert loaded[0].chunk_id == chunks[0].chunk_id
    assert loaded[0].text == chunks[0].text


# ---------------------------------------------------------------------------
# 6. Verification
# ---------------------------------------------------------------------------

def test_verify_chunks(sample_sections):
    chunks = chunk_sections(sample_sections, chunk_size=300)
    stats = verify_chunks(chunks)
    assert stats["total_chunks"] > 0
    assert stats["unique_chapters"] == 1
    assert stats["avg_word_count"] > 0
    assert stats["errors"] == []
