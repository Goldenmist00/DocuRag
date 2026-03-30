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
    Depends,
    FastAPI,
    File,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

load_dotenv()

from src.embedder import Embedder, EmbeddingTier
from src.generator import Generator
from src.retriever import Retriever, RetrievedChunk, create_retriever
from src.vector_store import PgVectorStore
from src.services import notebook_service, source_service, podcast_service
from src.services import batch_query_service
from src.db import (
    podcast_db, chunk_db, chunk_graph_db, notebook_db,
    repo_db, repo_memory_db, repo_context_db, session_db,
    repo_reference_db, repo_code_chunk_db,
)
from src.services.answer_validator import AnswerValidator
from services import summaryService, quizService, mindMapService, flashcardService
from src.controllers.repo_controller import router as repo_router
from src.controllers.session_controller import router as session_router
from src.controllers.github_controller import router as github_router
from src.utils.auth import require_current_user

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


class AnswerGradeResponse(BaseModel):
    """Quality grade for a generated answer."""
    faithfulness: float = 0.0
    completeness: float = 0.0
    citation_accuracy: float = 0.0
    overall: float = 0.0
    passed: bool = True
    issues: List[str] = []


class QueryResponse(BaseModel):
    """Response body for query endpoints."""
    question: str
    answer: str
    references: Dict
    chunks_used: int
    latency_ms: float
    sources: List[ChunkResult]
    grade: Optional[AnswerGradeResponse] = None


class BatchQueryResult(BaseModel):
    """One question's result within a batch."""
    question: str
    answer: Optional[str] = None
    error: Optional[str] = None
    sources: List[ChunkResult] = []
    grade: Optional[AnswerGradeResponse] = None
    latency_ms: float = 0.0


class BatchQueryResponse(BaseModel):
    """Response body for POST /notebooks/{id}/batch-query."""
    results: List[BatchQueryResult]
    total_questions: int
    answered: int
    failed: int
    total_latency_ms: float


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


class FlashcardsRequest(BaseModel):
    """Request body for POST /flashcards."""
    text: str = Field(..., min_length=10)
    count: int = Field(10, ge=1, le=50)


class SummaryRequest(BaseModel):
    """Request body for POST /summary."""
    text: str = Field(..., min_length=10)
    level: str = Field("medium", pattern="^(short|medium|detailed)$")


class MindMapRequest(BaseModel):
    """Request body for POST /mindmap."""
    text: str = Field(..., min_length=10)


class QuizRequest(BaseModel):
    """Request body for POST /quiz."""
    text: str = Field(..., min_length=10)
    count: int = Field(10, ge=1, le=50)
    difficulty: str = Field("mixed", pattern="^(easy|medium|hard|mixed)$")


# ---------------------------------------------------------------------------
# App state
# ---------------------------------------------------------------------------

class _AppState:
    retriever: Optional[Retriever] = None
    generator: Optional[Generator] = None
    vector_store: Optional[PgVectorStore] = None
    embedder: Optional[Embedder] = None
    source_pool: Optional[ThreadPoolExecutor] = None
    batch_pool: Optional[ThreadPoolExecutor] = None
    validator: Optional[AnswerValidator] = None


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

    podcast_db.ensure_table()
    chunk_graph_db.ensure_table()
    chunk_db.ensure_hnsw_index()
    notebook_db.ensure_conversation_history_column()

    repo_db.ensure_table()
    repo_memory_db.ensure_table()
    repo_context_db.ensure_table()
    repo_reference_db.ensure_table()
    repo_code_chunk_db.ensure_table()
    session_db.ensure_table()

    from src.db import github_db
    github_db.ensure_table()
    notebook_db.ensure_user_id_column()

    try:
        _state.validator = AnswerValidator()
        logger.info("Answer validator ready")
    except Exception as exc:
        logger.warning("Answer validator init failed (non-fatal): %s", exc)
        _state.validator = None

    _state.source_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="source")
    _state.batch_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="batch")

    from src.db.async_pool import init_async_pool
    try:
        await init_async_pool()
        logger.info("Async DB pool initialised")
    except Exception as exc:
        logger.warning("Async DB pool init failed (falling back to sync): %s", exc)

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

    from src.db.async_pool import close_async_pool
    await close_async_pool()

    if _state.batch_pool:
        _state.batch_pool.shutdown(wait=True)
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

app.include_router(repo_router)
app.include_router(session_router)
app.include_router(github_router)


# ---------------------------------------------------------------------------
# Helper — shared query logic
# ---------------------------------------------------------------------------

def _run_query(
    request: QueryRequest,
    notebook_id: Optional[str] = None,
    skip_validation: bool = False,
    query_vec=None,
) -> QueryResponse:
    """
    Shared retrieve-and-generate logic with multi-hop retrieval and answer validation.

    Pipeline:
      1. Multi-hop retrieve (vector search + graph expansion)
      2. Generate answer with LLM
      3. Validate answer quality (unless skip_validation is True)
      4. Retry once if validation fails

    Args:
        request:          Validated query request.
        notebook_id:      If provided, restrict retrieval to this notebook.
        skip_validation:  If True, skip the answer-validation LLM call.
        query_vec:        Pre-computed query embedding (skips re-embedding).

    Returns:
        QueryResponse with answer, references, sources, and quality grade.
    """
    if _state.retriever is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Retriever not initialised — check database connection.",
        )

    chunks: List[RetrievedChunk] = _state.retriever.retrieve_multihop(
        request.question,
        top_k=request.top_k,
        notebook_id=notebook_id,
        max_hops=1,
        expansion_k=3,
        query_vec=query_vec,
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

    result = _state.generator.generate(
        question=request.question,
        chunks=chunks,
        validator=None if skip_validation else _state.validator,
    )

    grade_resp: Optional[AnswerGradeResponse] = None
    if result.grade is not None:
        grade_resp = AnswerGradeResponse(
            faithfulness=result.grade.faithfulness,
            completeness=result.grade.completeness,
            citation_accuracy=result.grade.citation_accuracy,
            overall=result.grade.overall,
            passed=result.grade.passed,
            issues=result.grade.issues,
        )

    return QueryResponse(
        question=request.question,
        answer=result.answer,
        references=references,
        chunks_used=result.chunks_used,
        latency_ms=round(result.latency_ms, 1),
        sources=source_list,
        grade=grade_resp,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  NOTEBOOK ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/notebooks", status_code=status.HTTP_201_CREATED, summary="Create notebook")
async def create_notebook(body: NotebookCreate, user_id: str = Depends(require_current_user)):
    """Create a new empty notebook owned by the authenticated user."""
    try:
        return notebook_service.create_notebook(body.title, user_id=user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/notebooks", summary="List notebooks")
async def list_notebooks(user_id: str = Depends(require_current_user)):
    """Return notebooks for the authenticated user, most recently updated first."""
    from src.db import notebook_db as nb_db

    try:
        return await nb_db.async_list_notebooks(user_id=user_id)
    except RuntimeError:
        return notebook_service.list_notebooks(user_id=user_id)


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
    generates a cited answer, and persists the Q&A pair to the
    notebook's conversation history for later context export.
    """
    try:
        notebook_service.get_notebook(notebook_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    result = _run_query(request, notebook_id=notebook_id)

    try:
        notebook_db.append_conversation_entry(
            notebook_id, {"role": "user", "content": request.question},
        )
        notebook_db.append_conversation_entry(
            notebook_id, {"role": "ai", "content": result.answer},
        )
    except Exception:
        logger.warning("Failed to persist conversation entry for notebook %s", notebook_id, exc_info=True)

    return result


# ═══════════════════════════════════════════════════════════════════════════
#  NOTEBOOK CONVERSATION HISTORY
# ═══════════════════════════════════════════════════════════════════════════


@app.get(
    "/notebooks/{notebook_id}/history",
    summary="Get notebook conversation history",
)
async def get_notebook_history(notebook_id: str):
    """Return the full Q&A conversation history for a notebook.

    Args:
        notebook_id: UUID of the notebook.

    Returns:
        List of ``{role, content}`` message dicts.

    Raises:
        HTTPException: 404 if notebook not found.
    """
    try:
        notebook_service.get_notebook(notebook_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return notebook_db.get_conversation_history(notebook_id)


@app.delete(
    "/notebooks/{notebook_id}/history",
    status_code=204,
    summary="Clear notebook conversation history",
)
async def clear_notebook_history(notebook_id: str):
    """Reset the conversation history for a notebook.

    Args:
        notebook_id: UUID of the notebook.

    Raises:
        HTTPException: 404 if notebook not found.
    """
    try:
        notebook_service.get_notebook(notebook_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    notebook_db.clear_conversation_history(notebook_id)


@app.get(
    "/notebooks/{notebook_id}/export-context",
    summary="Export notebook context for repo session import",
)
async def export_notebook_context(notebook_id: str):
    """Bundle notebook title, sources, and conversation into a context payload.

    This payload can be imported into a repo agent session to give the
    coding agent full awareness of everything planned in the notebook.

    Args:
        notebook_id: UUID of the notebook.

    Returns:
        Dict with ``notebook_id``, ``title``, ``sources``, and
        ``conversation_history``.

    Raises:
        HTTPException: 404 if notebook not found.
    """
    try:
        nb = notebook_service.get_notebook(notebook_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    from src.db import source_db
    sources_raw = source_db.list_sources(notebook_id)
    sources_summary = [
        {"name": s.get("name", ""), "source_type": s.get("source_type", "")}
        for s in sources_raw
    ]

    history = notebook_db.get_conversation_history(notebook_id)

    return {
        "notebook_id": nb["id"],
        "title": nb["title"],
        "sources": sources_summary,
        "conversation_history": history,
    }


# ═══════════════════════════════════════════════════════════════════════════
#  BATCH QUERY ENDPOINT
# ═══════════════════════════════════════════════════════════════════════════

@app.post(
    "/notebooks/{notebook_id}/batch-query",
    response_model=BatchQueryResponse,
    summary="Batch Q&A from file",
)
async def batch_query(
    notebook_id: str,
    file: UploadFile = File(...),
    top_k: int = 5,
):
    """
    Upload a JSON or PDF file containing questions and receive
    answers for each one, using this notebook's sources.

    **JSON format:** an array of strings — ``["Q1?", "Q2?"]`` —
    or ``{"questions": ["Q1?", "Q2?"]}``.

    **PDF format:** lines ending with ``?`` or numbered patterns
    like ``Q1.``, ``1)``, ``- question?``.
    """
    try:
        notebook_service.get_notebook(notebook_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    if _state.retriever is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Retriever not initialised.",
        )

    raw_bytes = await file.read()
    try:
        questions = batch_query_service.extract_questions(
            file.filename or "upload", raw_bytes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    loop = asyncio.get_running_loop()

    if _state.embedder is not None:
        import numpy as np
        all_vecs = await loop.run_in_executor(
            None,
            lambda: _state.embedder.embed_batch(
                questions, show_progress=False, use_cache=True,
            ),
        )
        vec_map = {i: all_vecs[i] for i in range(len(questions))}
        logger.info(
            "Batch: pre-embedded %d questions in one call", len(questions),
        )
    else:
        vec_map = {}

    def _run_single(question: str, qk: int, nb_id: str, q_vec=None):
        """Run a single query with an optional pre-computed embedding."""
        try:
            req = QueryRequest(question=question, top_k=qk)
            return _run_query(
                req, notebook_id=nb_id,
                skip_validation=True, query_vec=q_vec,
            )
        except HTTPException as exc:
            raise RuntimeError(exc.detail) from exc

    batch_results = await loop.run_in_executor(
        _state.batch_pool,
        batch_query_service.run_batch,
        questions,
        _run_single,
        notebook_id,
        top_k,
        vec_map,
    )

    results: List[BatchQueryResult] = []
    answered = 0
    failed = 0
    total_lat = 0.0

    for br in batch_results:
        total_lat += br.latency_ms
        src_list = [
            ChunkResult(
                citation=s.get("citation", ""),
                section_title="",
                page=s.get("page", 0),
                score=s.get("score", 0.0),
                source_name=s.get("source_name", ""),
            )
            for s in br.sources
        ]
        grade_resp = None
        if br.grade:
            grade_resp = AnswerGradeResponse(
                faithfulness=br.grade.get("faithfulness", 0),
                completeness=br.grade.get("completeness", 0),
                citation_accuracy=br.grade.get("citation_accuracy", 0),
                overall=br.grade.get("overall", 0),
                passed=br.grade.get("passed", True),
                issues=br.grade.get("issues", []),
            )
        if br.error:
            failed += 1
        else:
            answered += 1
        results.append(BatchQueryResult(
            question=br.question,
            answer=br.answer,
            error=br.error,
            sources=src_list,
            grade=grade_resp,
            latency_ms=br.latency_ms,
        ))

    return BatchQueryResponse(
        results=results,
        total_questions=len(questions),
        answered=answered,
        failed=failed,
        total_latency_ms=round(total_lat, 1),
    )


# ═══════════════════════════════════════════════════════════════════════════
#  STUDIO ENDPOINTS (flashcards, summary, mindmap, quiz)
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/flashcards", summary="Generate flashcards")
async def generate_flashcards(body: FlashcardsRequest):
    """Generate flashcards from provided text using Gemini."""
    try:
        cards = flashcardService.generate_flashcards(body.text, body.count)
        return {"flashcards": cards}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Flashcard generation failed: {exc}")


@app.post("/summary", summary="Generate summary")
async def generate_summary(body: SummaryRequest):
    """Generate a summary from provided text using Gemini."""
    try:
        summary = summaryService.generate_summary(body.text, body.level)
        return {"summary": summary, "level": body.level}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Summary generation failed: {exc}")


@app.post("/mindmap", summary="Generate mind map")
async def generate_mind_map(body: MindMapRequest):
    """Generate a mind map structure from provided text using Gemini."""
    try:
        data = mindMapService.generate_mind_map(body.text)
        return data
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Mind map generation failed: {exc}")


@app.post("/quiz", summary="Generate quiz")
async def generate_quiz(body: QuizRequest):
    """Generate quiz questions from provided text using Gemini."""
    try:
        questions = quizService.generate_quiz(body.text, body.count, body.difficulty)
        return {"questions": questions}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Quiz generation failed: {exc}")


# ═══════════════════════════════════════════════════════════════════════════
#  PODCAST ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════

@app.post(
    "/notebooks/{notebook_id}/podcast",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate podcast",
)
async def create_podcast(notebook_id: str):
    """
    Trigger podcast generation from this notebook's sources.

    Retrieves key content, generates a two-host conversational
    transcript via LLM, synthesizes speech with TTS, and assembles
    a single audio file. Processing runs in a background thread.
    Poll GET .../podcast to track status.
    """
    if _state.retriever is None or _state.generator is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Retriever or Generator not initialised.",
        )

    try:
        notebook_service.get_notebook(notebook_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    try:
        podcast = podcast_service.generate_podcast(
            notebook_id, _state.retriever, _state.generator,
        )
        loop = asyncio.get_running_loop()
        loop.run_in_executor(
            _state.source_pool,
            podcast_service.process_podcast,
            podcast["id"],
            _state.retriever,
            _state.generator,
        )
        return podcast
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/notebooks/{notebook_id}/podcast", summary="Get podcast status")
async def get_podcast(notebook_id: str):
    """Return the latest podcast for this notebook with its current status."""
    try:
        notebook_service.get_notebook(notebook_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    podcast = podcast_service.get_podcast_for_notebook(notebook_id)
    if not podcast:
        raise HTTPException(status_code=404, detail="No podcast found for this notebook.")
    return podcast


@app.get("/notebooks/{notebook_id}/podcast/audio", summary="Stream podcast audio")
async def get_podcast_audio(notebook_id: str):
    """Serve the generated podcast MP3 audio file."""
    podcast = podcast_service.get_podcast_for_notebook(notebook_id)
    if not podcast:
        raise HTTPException(status_code=404, detail="No podcast found.")
    if podcast["status"] != "ready":
        raise HTTPException(status_code=409, detail=f"Podcast is not ready (status: {podcast['status']}).")

    audio_path = podcast.get("audio_path")
    if not audio_path or not Path(audio_path).exists():
        raise HTTPException(status_code=404, detail="Audio file not found on disk.")

    return FileResponse(
        audio_path,
        media_type="audio/mpeg",
        filename=f"podcast-{notebook_id[:8]}.mp3",
    )


@app.delete(
    "/notebooks/{notebook_id}/podcast",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete podcast",
)
async def delete_podcast(notebook_id: str):
    """Delete the podcast and its audio file for this notebook."""
    podcast = podcast_service.get_podcast_for_notebook(notebook_id)
    if not podcast:
        raise HTTPException(status_code=404, detail="No podcast found.")
    try:
        podcast_service.delete_podcast(podcast["id"])
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


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
