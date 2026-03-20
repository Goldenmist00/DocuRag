"""
api.py
======
FastAPI application — notebook-scoped RAG system.

Endpoints:
  Notebooks:
    POST   /notebooks                          — create notebook
    GET    /notebooks                          — list notebooks
    GET    /notebooks/{notebook_id}            — get notebook
    PATCH  /notebooks/{notebook_id}            — rename notebook
    DELETE /notebooks/{notebook_id}            — delete notebook

  Sources:
    POST   /notebooks/{notebook_id}/sources/upload  — upload file
    POST   /notebooks/{notebook_id}/sources/text    — paste text
    GET    /notebooks/{notebook_id}/sources         — list sources
    DELETE /notebooks/{notebook_id}/sources/{id}    — delete source

  Query:
    POST   /notebooks/{notebook_id}/query      — scoped Q&A

  Legacy (backward-compat):
    POST   /query   — global Q&A
    GET    /health  — liveness check
    GET    /stats   — vector store statistics
"""

from __future__ import annotations

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator, Dict, List, Optional

import yaml
from dotenv import load_dotenv
from fastapi import (
    FastAPI,
    File,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

load_dotenv()

from src.embedder import Embedder, EmbeddingTier
from src.generator import Generator
from src.retriever import Retriever, RetrievedChunk, create_retriever
from src.vector_store import PgVectorStore
from src.services import notebook_service, source_service

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

def _load_config() -> Dict:
    """
    Load config.yaml from project root.

    Returns:
        Parsed YAML dict.

    Raises:
        FileNotFoundError: If config.yaml is missing.
    """
    cfg_path = Path("config.yaml")
    if not cfg_path.exists():
        raise FileNotFoundError("config.yaml not found — run from project root.")
    with open(cfg_path) as f:
        return yaml.safe_load(f) or {}


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class QueryRequest(BaseModel):
    """Request body for POST /query and POST /notebooks/{id}/query."""
    question: str = Field(..., min_length=3, max_length=1000)
    top_k: int = Field(5, ge=1, le=20)


class ChunkResult(BaseModel):
    """A single retrieved chunk in the response."""
    citation: str
    section_title: str
    page: int
    score: float
    source_name: str = ""


class QueryResponse(BaseModel):
    """Response body for query endpoints."""
    question: str
    answer: str
    references: Dict
    chunks_used: int
    latency_ms: float
    sources: List[ChunkResult]


class HealthResponse(BaseModel):
    """Response body for GET /health."""
    status: str
    db_connected: bool
    embedder_tier: str
    model: str


class StatsResponse(BaseModel):
    """Response body for GET /stats."""
    total_chunks: int
    unique_sections: int
    unique_chapters: int
    unique_pages: int
    embedding_dim: int
    has_index: bool


class NotebookCreate(BaseModel):
    """Request body for POST /notebooks."""
    title: Optional[str] = None


class NotebookUpdate(BaseModel):
    """Request body for PATCH /notebooks/{id}."""
    title: str


class TextSourceCreate(BaseModel):
    """Request body for POST /notebooks/{id}/sources/text."""
    name: Optional[str] = "Pasted text"
    text: str = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# App state
# ---------------------------------------------------------------------------

class _AppState:
    retriever: Optional[Retriever] = None
    generator: Optional[Generator] = None
    vector_store: Optional[PgVectorStore] = None
    embedder: Optional[Embedder] = None
    source_pool: Optional[ThreadPoolExecutor] = None


_state = _AppState()


# ---------------------------------------------------------------------------
# Lifespan — startup / shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """Initialise shared components once at startup, clean up on shutdown."""
    cfg = _load_config()

    tier_name = cfg.get("embedding", {}).get("tier", "balanced")
    tier = EmbeddingTier(tier_name)

    embedder = Embedder(
        tier=tier,
        cache_dir=cfg.get("cache", {}).get("embeddings_cache", "embeddings/cache"),
    )

    pg = cfg.get("vector_store", {}).get("connection", {})
    _state.vector_store = PgVectorStore(
        embedding_dim=embedder.embedding_dim,
        host=pg.get("host", "localhost"),
        port=int(pg.get("port", 5432)),
        database=pg.get("database", "rag_db"),
        user=pg.get("user", "postgres"),
    )

    _state.retriever = create_retriever(
        embedder=embedder,
        vector_store=_state.vector_store,
        cfg=cfg.get("retrieval", {}),
    )

    _state.embedder = embedder
    source_service.set_embedder(embedder)

    _state.source_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="source")

    api_key = os.getenv("NVIDIA_API_KEY", "").strip()
    if api_key:
        gen_cfg = cfg.get("generation", {})
        _state.generator = Generator(
            model=gen_cfg.get("model", "meta/llama-3.1-8b-instruct"),
            temperature=gen_cfg.get("temperature", 0.2),
            max_tokens=gen_cfg.get("max_tokens", 512),
            top_p=gen_cfg.get("top_p", 0.9),
            api_key=api_key,
        )
        logger.info("Generator ready | model=%s", _state.generator.model)
    else:
        logger.warning("NVIDIA_API_KEY not set — /query will return retrieval only")

    logger.info("API startup complete")
    yield

    if _state.source_pool:
        _state.source_pool.shutdown(wait=True)
    if _state.embedder:
        _state.embedder.flush_cache()
    if _state.vector_store:
        _state.vector_store.close()
    logger.info("API shutdown complete")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="DocuRAG — Notebook-scoped Q&A",
    description="NotebookLM-style RAG system with per-notebook sources and scoped retrieval.",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Helper — shared query logic
# ---------------------------------------------------------------------------

def _run_query(request: QueryRequest, notebook_id: Optional[str] = None) -> QueryResponse:
    """
    Shared retrieve-and-generate logic used by both /query and scoped endpoint.

    Args:
        request:     Validated query request.
        notebook_id: If provided, restrict retrieval to this notebook.

    Returns:
        QueryResponse with answer, references, and sources.
    """
    if _state.retriever is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Retriever not initialised — check database connection.",
        )

    chunks: List[RetrievedChunk] = _state.retriever.retrieve(
        request.question, top_k=request.top_k, notebook_id=notebook_id,
    )

    if not chunks:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No relevant passages found. Add sources to your notebook first.",
        )

    references = {
        "sections": sorted({c.section_id for c in chunks if c.section_id}),
        "pages":    sorted({c.page_start for c in chunks if c.page_start}),
    }

    source_list = [
        ChunkResult(
            citation=c.citation(),
            section_title=c.section_title,
            page=c.page_start,
            score=round(c.score, 4),
            source_name=c.source_name,
        )
        for c in chunks
    ]

    if _state.generator is None:
        return QueryResponse(
            question=request.question,
            answer="[Generation unavailable — NVIDIA_API_KEY not set]",
            references=references,
            chunks_used=len(chunks),
            latency_ms=0.0,
            sources=source_list,
        )

    result = _state.generator.generate(question=request.question, chunks=chunks)

    return QueryResponse(
        question=request.question,
        answer=result.answer,
        references=references,
        chunks_used=result.chunks_used,
        latency_ms=round(result.latency_ms, 1),
        sources=source_list,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  NOTEBOOK ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/notebooks", status_code=status.HTTP_201_CREATED, summary="Create notebook")
async def create_notebook(body: NotebookCreate):
    """Create a new empty notebook."""
    try:
        return notebook_service.create_notebook(body.title)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/notebooks", summary="List notebooks")
async def list_notebooks():
    """Return all notebooks, most recently updated first."""
    return notebook_service.list_notebooks()


@app.get("/notebooks/{notebook_id}", summary="Get notebook")
async def get_notebook(notebook_id: str):
    """Fetch a single notebook by ID."""
    try:
        return notebook_service.get_notebook(notebook_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.patch("/notebooks/{notebook_id}", summary="Rename notebook")
async def update_notebook(notebook_id: str, body: NotebookUpdate):
    """Update a notebook's title."""
    try:
        return notebook_service.update_title(notebook_id, body.title)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.delete("/notebooks/{notebook_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete notebook")
async def delete_notebook(notebook_id: str):
    """Delete a notebook and all its sources and chunks."""
    try:
        notebook_service.delete_notebook(notebook_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ═══════════════════════════════════════════════════════════════════════════
#  SOURCE ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════

@app.post(
    "/notebooks/{notebook_id}/sources/upload",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload file source",
)
async def upload_source(
    notebook_id: str,
    file: UploadFile = File(...),
):
    """
    Upload a PDF or text file as a notebook source.

    The file is saved and processing (chunk + embed + store) runs
    concurrently in a thread pool. Poll GET .../sources to track status.
    """
    try:
        file_bytes = await file.read()
        source = source_service.add_file_source(notebook_id, file.filename or "upload", file_bytes)
        loop = asyncio.get_running_loop()
        loop.run_in_executor(_state.source_pool, source_service.process_source, source["id"])
        return source
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post(
    "/notebooks/{notebook_id}/sources/text",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Add text source",
)
async def add_text_source(
    notebook_id: str,
    body: TextSourceCreate,
):
    """
    Add pasted text as a notebook source.

    Processing (chunk + embed + store) runs concurrently in a thread pool.
    """
    try:
        source = source_service.add_text_source(notebook_id, body.name or "Pasted text", body.text)
        loop = asyncio.get_running_loop()
        loop.run_in_executor(_state.source_pool, source_service.process_source, source["id"])
        return source
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/notebooks/{notebook_id}/sources", summary="List sources")
async def list_sources(notebook_id: str):
    """Return all sources for a notebook with their processing status."""
    return source_service.list_sources(notebook_id)


@app.delete(
    "/notebooks/{notebook_id}/sources/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete source",
)
async def delete_source(notebook_id: str, source_id: str):
    """Remove a source and all its embedded chunks."""
    try:
        source_service.delete_source(source_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ═══════════════════════════════════════════════════════════════════════════
#  SCOPED QUERY ENDPOINT
# ═══════════════════════════════════════════════════════════════════════════

@app.post(
    "/notebooks/{notebook_id}/query",
    response_model=QueryResponse,
    summary="Ask question (scoped to notebook)",
)
async def notebook_query(notebook_id: str, request: QueryRequest) -> QueryResponse:
    """
    Answer a question using only this notebook's sources.

    Embeds the question, searches chunks scoped to the notebook,
    and generates a cited answer.
    """
    try:
        notebook_service.get_notebook(notebook_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return _run_query(request, notebook_id=notebook_id)


# ═══════════════════════════════════════════════════════════════════════════
#  LEGACY ENDPOINTS (backward compatibility)
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/query", response_model=QueryResponse, summary="Answer a question (global)")
async def query(request: QueryRequest) -> QueryResponse:
    """Global query — searches all chunks regardless of notebook."""
    return _run_query(request)


@app.get("/health", response_model=HealthResponse, summary="Liveness check")
async def health() -> HealthResponse:
    """Check that the database and embedder are reachable."""
    db_ok = False
    if _state.vector_store:
        try:
            _state.vector_store.get_stats()
            db_ok = True
        except Exception:
            db_ok = False

    tier = "unknown"
    if _state.retriever:
        tier = _state.retriever.embedder.tier.value

    model = _state.generator.model if _state.generator else "not configured"

    return HealthResponse(
        status="ok" if db_ok else "degraded",
        db_connected=db_ok,
        embedder_tier=tier,
        model=model,
    )


@app.get("/stats", response_model=StatsResponse, summary="Vector store statistics")
async def stats() -> StatsResponse:
    """Return statistics about the indexed document chunks."""
    if _state.vector_store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vector store not initialised.",
        )
    s = _state.vector_store.get_stats()
    return StatsResponse(
        total_chunks=s.get("total_chunks", 0),
        unique_sections=s.get("unique_sections", 0),
        unique_chapters=s.get("unique_chapters", 0),
        unique_pages=s.get("unique_pages", 0),
        embedding_dim=s.get("embedding_dim", 0),
        has_index=s.get("has_index", False),
    )
