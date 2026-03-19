"""
api.py
======
FastAPI application — live demo endpoint for the RAG system.

Endpoints:
  POST /query   — retrieve + generate a grounded answer
  GET  /health  — liveness check (DB + embedder status)
  GET  /stats   — vector store statistics

The app initialises the Retriever and Generator once at startup
(lifespan context manager) and reuses them across requests.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator, Dict, List, Optional

import yaml
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

load_dotenv()

# project root on sys.path when run via uvicorn from project root
from src.embedder import Embedder, EmbeddingTier
from src.generator import Generator
from src.retriever import Retriever, RetrievedChunk, create_retriever
from src.vector_store import PgVectorStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

def _load_config() -> Dict:
    cfg_path = Path("config.yaml")
    if not cfg_path.exists():
        raise FileNotFoundError("config.yaml not found — run from project root.")
    with open(cfg_path) as f:
        return yaml.safe_load(f) or {}


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class QueryRequest(BaseModel):
    """Request body for POST /query."""
    question: str = Field(..., min_length=3, max_length=1000, description="The question to answer")
    top_k: int = Field(5, ge=1, le=20, description="Number of chunks to retrieve")


class ChunkResult(BaseModel):
    """A single retrieved chunk in the response."""
    citation: str
    section_title: str
    page: int
    score: float


class QueryResponse(BaseModel):
    """Response body for POST /query."""
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


# ---------------------------------------------------------------------------
# App state — holds shared instances across requests
# ---------------------------------------------------------------------------

class _AppState:
    retriever: Optional[Retriever] = None
    generator: Optional[Generator] = None
    vector_store: Optional[PgVectorStore] = None


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
        # password resolved from POSTGRES_PASSWORD env var inside PgVectorStore
    )

    _state.retriever = create_retriever(
        embedder=embedder,
        vector_store=_state.vector_store,
        cfg=cfg.get("retrieval", {}),
    )

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

    # Shutdown
    if _state.vector_store:
        _state.vector_store.close()
    logger.info("API shutdown complete")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="DocuRAG — Psychology 2e Q&A",
    description="RAG system for OpenStax Psychology 2e with citation-verifiable answers.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/query", response_model=QueryResponse, summary="Answer a question")
async def query(request: QueryRequest) -> QueryResponse:
    """
    Retrieve relevant passages and generate a grounded answer.

    - Embeds the question using the configured sentence-transformer tier
    - Searches PostgreSQL for the top-k most similar chunks
    - Calls the NVIDIA LLM to generate a cited answer
    - Returns the answer, citations, and source metadata
    """
    if _state.retriever is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Retriever not initialised — check database connection.",
        )

    # Retrieve
    chunks: List[RetrievedChunk] = _state.retriever.retrieve(
        request.question, top_k=request.top_k
    )

    if not chunks:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No relevant passages found. Is the database populated?",
        )

    # Build references for submission format
    references = {
        "sections": sorted({c.section_id for c in chunks if c.section_id}),
        "pages":    sorted({c.page_start for c in chunks if c.page_start}),
    }

    sources = [
        ChunkResult(
            citation=c.citation(),
            section_title=c.section_title,
            page=c.page_start,
            score=round(c.score, 4),
        )
        for c in chunks
    ]

    # Generate (if API key available)
    if _state.generator is None:
        return QueryResponse(
            question=request.question,
            answer="[Generation unavailable — NVIDIA_API_KEY not set]",
            references=references,
            chunks_used=len(chunks),
            latency_ms=0.0,
            sources=sources,
        )

    result = _state.generator.generate(question=request.question, chunks=chunks)

    return QueryResponse(
        question=request.question,
        answer=result.answer,
        references=references,
        chunks_used=result.chunks_used,
        latency_ms=round(result.latency_ms, 1),
        sources=sources,
    )


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
