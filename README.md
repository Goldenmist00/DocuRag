# DocuRAG

A notebook-scoped Retrieval-Augmented Generation (RAG) system with multi-hop retrieval, citation-grounded answers, and an integrated study toolkit. DocuRAG enables users to upload documents into isolated notebooks, ask natural-language questions scoped to those documents, and receive LLM-generated answers with verifiable inline citations.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
  - [System Diagram](#system-diagram)
  - [Backend Pipeline](#backend-pipeline)
  - [Frontend](#frontend)
- [Core Features](#core-features)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
  - [Backend Setup](#backend-setup)
  - [Frontend Setup](#frontend-setup)
- [Configuration](#configuration)
  - [Environment Variables](#environment-variables)
  - [Application Configuration](#application-configuration)
- [Running the Application](#running-the-application)
- [API Reference](#api-reference)
  - [Notebooks](#notebooks)
  - [Sources](#sources)
  - [Query](#query)
  - [Batch Query](#batch-query)
  - [Studio Tools](#studio-tools)
  - [Podcast](#podcast)
  - [System](#system)
- [Ingestion Pipeline](#ingestion-pipeline)
  - [PDF Processing](#pdf-processing)
  - [Chunking Strategy](#chunking-strategy)
  - [Embedding](#embedding)
  - [Vector Storage](#vector-storage)
  - [Knowledge Graph Construction](#knowledge-graph-construction)
- [Retrieval and Generation](#retrieval-and-generation)
  - [Source-Aware Retrieval](#source-aware-retrieval)
  - [Multi-Hop Graph Expansion](#multi-hop-graph-expansion)
  - [Answer Generation](#answer-generation)
  - [Answer Validation](#answer-validation)
- [Batch Processing](#batch-processing)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## Overview

DocuRAG implements a production-grade RAG pipeline where each notebook maintains its own isolated set of sources (PDFs, text, JSON files). Questions are answered exclusively from the sources within a notebook, ensuring precise, scoped retrieval with full citation traceability.

The system goes beyond basic vector search by combining per-source retrieval allocation, multi-hop graph traversal, LLM-based answer validation with automatic retry, and a suite of study tools including flashcard generation, quizzes, mind maps, summaries, and AI-generated podcasts.

---

## Architecture

### System Diagram

```
                     +-------------------+
                     |  Next.js Frontend |
                     |    (MindSync)     |
                     +---------+---------+
                               |
                          HTTP / REST
                               |
                     +---------v---------+
                     |   FastAPI Server   |
                     |     (api.py)       |
                     +---------+---------+
                               |
            +------------------+------------------+
            |                  |                  |
   +--------v------+  +-------v-------+  +-------v--------+
   |   Services     |  |   Retriever   |  | Studio Services|
   | (source_svc,   |  | (multi-hop,   |  | (Gemini API)   |
   |  notebook_svc,  |  |  per-source)  |  | flashcards,    |
   |  podcast_svc)   |  +-------+-------+  | summary, quiz, |
   +--------+------+          |          | mindmap         |
            |                  |          +----------------+
            |          +-------v-------+
            |          |   Generator   |
            |          | (NVIDIA/Groq) |
            |          +-------+-------+
            |                  |
   +--------v------------------v--------+
   |        Database Layer (db/)        |
   |  notebook_db | source_db | chunk_db|
   |  chunk_graph_db | podcast_db       |
   +--------+--------------------------+
            |
   +--------v--------+
   |   PostgreSQL     |
   |   + pgvector     |
   +-----------------+
```

### Backend Pipeline

The backend follows a layered architecture:

1. **API Layer** (`src/api.py`) -- FastAPI application handling HTTP request/response routing. No business logic resides here; all processing is delegated to service and retrieval modules.

2. **Service Layer** (`src/services/`) -- Contains all business logic including source ingestion orchestration, notebook management, podcast generation, batch query processing, and answer validation.

3. **Database Layer** (`src/db/`) -- Centralizes all PostgreSQL operations. Every database call passes through dedicated `*_db.py` modules with connection pooling via a shared connection manager.

4. **Core Modules** (`src/`) -- Standalone processing components: PDF extraction, chunking, embedding, vector search, and LLM generation. Each module is independently testable.

### Frontend

The frontend (branded "MindSync") is a Next.js 14 application providing:

- Notebook management with source upload and processing status tracking
- Chat-style Q&A interface with markdown rendering and citation display
- Batch query interface for processing question files
- Studio tools: flashcards, summaries, mind maps, quizzes
- Podcast player for AI-generated audio discussions
- Authentication flows (login, signup, password recovery)

---

## Core Features

**Notebook-Scoped RAG** -- Each notebook is an isolated container of sources. Queries retrieve only from the sources within that notebook, preventing cross-contamination between different document sets.

**Multi-Format Source Ingestion** -- Supports PDF files (with multi-column layout correction), plain text, and JSON files. Each source is independently processed, chunked, embedded, and indexed.

**Source-Aware Retrieval** -- When a notebook contains multiple sources, retrieval is performed independently per source with slot allocation to guarantee representation from every document. If the query mentions a source by name, that source receives boosted allocation.

**Multi-Hop Graph Retrieval** -- A knowledge graph of chunk relationships is built during ingestion using entity extraction and keyword overlap. At query time, the retriever traverses graph edges to discover related chunks that may not rank highly by vector similarity alone.

**Answer Validation and Retry** -- Generated answers are graded by a separate LLM call on faithfulness, completeness, and citation accuracy. If the answer fails validation, a retry is attempted with corrective feedback injected into the prompt.

**Citation-Grounded Answers** -- Every answer includes inline citation markers (`[1]`, `[2]`, etc.) that map to specific source passages with section, chapter, and page metadata.

**Study Toolkit (Studio)** -- Powered by Google Gemini:
- Flashcard generation with configurable count
- Summaries at short, medium, or detailed levels
- Mind map generation for visual topic organization
- Quiz generation with configurable difficulty and count

**AI Podcast Generation** -- Converts notebook content into a two-host conversational podcast using LLM script generation and Deepgram Aura neural TTS. The pipeline retrieves key content, generates a natural dialogue, synthesizes speech with distinct voices per host, and assembles a playable MP3.

**Batch Query Processing** -- Upload a JSON or PDF file containing multiple questions and receive answers for all of them in a single request. Embeddings are pre-computed in bulk for efficiency.

---

## Tech Stack

| Layer         | Technology                                              |
|---------------|--------------------------------------------------------|
| Frontend      | Next.js 14, React 18, TypeScript, Tailwind CSS 4, Framer Motion, Three.js |
| API Server    | Python 3.10+, FastAPI, Uvicorn                          |
| Embeddings    | NVIDIA NIM API (`baai/bge-m3`, 1024 dimensions)         |
| LLM (RAG)     | NVIDIA API (`meta/llama-3.3-70b-instruct`), Groq fallback (`llama-3.3-70b-versatile`) |
| LLM (Studio)  | Google Gemini (`gemini-2.5-flash`)                      |
| TTS (Podcast) | Deepgram Aura (Orion, Asteria voices)                   |
| Vector Store  | PostgreSQL + pgvector (HNSW indexing, cosine similarity) |
| PDF Parsing   | PyMuPDF (fitz)                                          |
| Validation    | Pydantic v2                                             |

---

## Project Structure

```
DocuRag/
├── config.yaml                      # Application configuration
├── .env.example                     # Environment variable template
├── requirements.txt                 # Python production dependencies
├── requirements-dev.txt             # Python development dependencies
│
├── src/                             # Core backend modules
│   ├── api.py                       # FastAPI application and endpoint definitions
│   ├── pdf_processor.py             # PDF extraction, section detection, chunking
│   ├── chunker.py                   # Recursive hierarchical text chunking
│   ├── embedder.py                  # NVIDIA API embedding with caching
│   ├── vector_store.py              # PostgreSQL + pgvector operations
│   ├── retriever.py                 # Source-aware and multi-hop retrieval
│   ├── generator.py                 # LLM answer generation (NVIDIA/Groq)
│   │
│   ├── db/                          # Database access layer
│   │   ├── connection.py            # Shared PostgreSQL connection pool
│   │   ├── notebook_db.py           # Notebook CRUD operations
│   │   ├── source_db.py             # Source CRUD operations
│   │   ├── chunk_db.py              # Chunk storage and HNSW index management
│   │   ├── chunk_graph_db.py        # Knowledge graph edge storage
│   │   └── podcast_db.py            # Podcast metadata storage
│   │
│   └── services/                    # Business logic layer
│       ├── notebook_service.py      # Notebook management logic
│       ├── source_service.py        # Source ingestion pipeline orchestration
│       ├── batch_query_service.py   # Batch question processing
│       ├── podcast_service.py       # Podcast generation pipeline
│       ├── answer_validator.py      # LLM-based answer quality grading
│       └── entity_extractor.py      # Regex-based entity extraction for graph edges
│
├── services/                        # Studio feature services (Gemini)
│   ├── summaryService.py            # Summary generation
│   ├── flashcardService.py          # Flashcard generation
│   ├── mindMapService.py            # Mind map generation
│   └── quizService.py               # Quiz generation
│
├── scripts/                         # CLI utilities and pipeline scripts
│   ├── setup_postgres.py            # Database initialization
│   ├── run_pipeline.py              # Batch pipeline orchestration
│   ├── embed_and_store.py           # Embedding and storage pipeline
│   ├── generate_submission.py       # Batch Q&A to CSV export
│   ├── ingest.py                    # Source ingestion script
│   ├── migrate_schema.py            # Database schema migration
│   ├── setup_data.py                # Data setup utilities
│   └── pre_demo_test.py             # Pre-deployment validation
│
├── frontend/nextjs-project/         # Next.js frontend application
│   ├── package.json
│   ├── src/
│   │   ├── app/                     # Next.js App Router pages
│   │   │   ├── page.tsx             # Landing page
│   │   │   ├── dashboard/page.tsx   # Main application dashboard
│   │   │   ├── login/page.tsx       # Authentication
│   │   │   └── ...
│   │   ├── lib/
│   │   │   └── api.ts               # Backend API client
│   │   └── components/              # Reusable UI components
│   └── public/                      # Static assets
│
├── data/
│   ├── raw/                         # Input PDF files
│   ├── processed/                   # Generated chunks (JSONL)
│   └── queries.json                 # Batch query input
│
├── embeddings/cache/                # Disk-persisted embedding cache (.npz)
├── uploads/                         # Uploaded source files
│   └── podcasts/                    # Generated podcast MP3 files
├── logs/                            # Application logs
└── tests/                           # Test suite
```

---

## Prerequisites

- **Python** 3.10 or higher
- **Node.js** 18 or higher (for the frontend)
- **PostgreSQL** 14 or higher with the [pgvector](https://github.com/pgvector/pgvector) extension installed
- **NVIDIA API Key** -- obtain one at [build.nvidia.com](https://build.nvidia.com)
- **Groq API Key** (optional) -- for LLM fallback; obtain at [console.groq.com](https://console.groq.com)
- **Google Gemini API Key** (optional) -- required for Studio features (flashcards, summaries, mind maps, quizzes)
- **Deepgram API Key** (optional) -- required for podcast generation; obtain at [deepgram.com](https://deepgram.com)

---

## Installation

### Backend Setup

```bash
git clone https://github.com/Goldenmist00/DocuRag.git
cd DocuRag

python -m venv venv

# Windows
venv\Scripts\activate
# Linux / macOS
source venv/bin/activate

pip install -r requirements.txt
```

Copy the environment template and configure your API keys:

```bash
cp .env.example .env
```

Initialize the PostgreSQL database:

```bash
python scripts/setup_postgres.py
```

This creates the database, enables the pgvector extension, and sets up all required tables.

### Frontend Setup

```bash
cd frontend/nextjs-project
npm install
```

Create a `.env.local` file in the frontend directory:

```
NEXT_PUBLIC_API_URL=http://localhost:8000
```

---

## Configuration

### Environment Variables

Configure the following in your `.env` file:

| Variable              | Required | Description                                      |
|-----------------------|----------|--------------------------------------------------|
| `NVIDIA_API_KEY`      | Yes      | NVIDIA NIM API key for LLM generation            |
| `NVIDIA_EMBED_API_KEY`| No       | Separate key for embeddings (falls back to `NVIDIA_API_KEY`) |
| `GROQ_API_KEY`        | No       | Groq API key for LLM fallback                    |
| `GEMINI_API_KEY`      | No       | Google Gemini API key for Studio features         |
| `DEEPGRAM_API_KEY`    | No       | Deepgram API key for podcast TTS                  |
| `POSTGRES_HOST`       | Yes      | PostgreSQL host address                           |
| `POSTGRES_PORT`       | No       | PostgreSQL port (default: 5432)                   |
| `POSTGRES_DB`         | Yes      | Database name                                     |
| `POSTGRES_USER`       | Yes      | Database user                                     |
| `POSTGRES_PASSWORD`   | Yes      | Database password                                 |
| `POSTGRES_SSLMODE`    | No       | SSL mode (default: `require`)                     |

### Application Configuration

All tunable parameters are defined in `config.yaml`:

```yaml
# Text chunking
chunking:
  chunk_size: 800           # Target characters per chunk
  chunk_overlap: 100        # Overlap between consecutive chunks
  min_chunk_size: 150       # Minimum chunk size (rejects fragments)
  min_letter_ratio: 0.4     # Minimum alphabetic character ratio

# Embedding
embedding:
  tier: "nvidia"            # baai/bge-m3 via NVIDIA NIM (1024d)

# Vector store
vector_store:
  type: "pgvector"
  index_type: "hnsw"        # HNSW index for approximate nearest neighbor

# Retrieval
retrieval:
  top_k: 5                  # Default chunks returned per query

# Generation
generation:
  model: "meta/llama-3.3-70b-instruct"
  temperature: 0.3
  max_tokens: 512
  top_p: 0.9
```

---

## Running the Application

Start the backend API server:

```bash
uvicorn src.api:app --reload --port 8000
```

Start the frontend development server (in a separate terminal):

```bash
cd frontend/nextjs-project
npm run dev
```

The application is now accessible at:
- **Frontend**: `http://localhost:3000`
- **API**: `http://localhost:8000`
- **API Documentation (Swagger)**: `http://localhost:8000/docs`

---

## API Reference

### Notebooks

| Method   | Endpoint                    | Description              |
|----------|-----------------------------|--------------------------|
| `POST`   | `/notebooks`                | Create a new notebook    |
| `GET`    | `/notebooks`                | List all notebooks       |
| `GET`    | `/notebooks/{id}`           | Get a specific notebook  |
| `PATCH`  | `/notebooks/{id}`           | Rename a notebook        |
| `DELETE` | `/notebooks/{id}`           | Delete notebook and all its data |

### Sources

| Method   | Endpoint                                    | Description                 |
|----------|---------------------------------------------|-----------------------------|
| `POST`   | `/notebooks/{id}/sources/upload`            | Upload a PDF or text file   |
| `POST`   | `/notebooks/{id}/sources/text`              | Add pasted text as a source |
| `GET`    | `/notebooks/{id}/sources`                   | List sources with status    |
| `DELETE` | `/notebooks/{id}/sources/{source_id}`       | Delete a source and its chunks |

Source processing is asynchronous. After uploading, poll `GET .../sources` to track processing status through the stages: `pending` -> `extracting` -> `chunking` -> `embedding` -> `storing` -> `graphing` -> `ready`.

### Query

| Method   | Endpoint                        | Description                              |
|----------|---------------------------------|------------------------------------------|
| `POST`   | `/notebooks/{id}/query`         | Ask a question scoped to notebook sources |
| `POST`   | `/query`                        | Global query across all chunks (legacy)   |

**Request body:**

```json
{
  "question": "What is classical conditioning?",
  "top_k": 5
}
```

**Response includes:**
- `answer` -- LLM-generated response with inline citations
- `sources` -- List of retrieved passages with citation, section, page, and similarity score
- `references` -- Aggregated section IDs and page numbers
- `grade` -- Optional quality assessment (faithfulness, completeness, citation accuracy)
- `latency_ms` -- End-to-end processing time

### Batch Query

| Method   | Endpoint                            | Description                    |
|----------|-------------------------------------|--------------------------------|
| `POST`   | `/notebooks/{id}/batch-query`       | Process multiple questions from a file |

Upload a JSON file (`["Q1?", "Q2?"]`) or a PDF with questions. Returns answers for all questions with per-question timing and error reporting.

### Studio Tools

| Method   | Endpoint       | Description                     |
|----------|----------------|---------------------------------|
| `POST`   | `/flashcards`  | Generate flashcards from text   |
| `POST`   | `/summary`     | Generate summary (short/medium/detailed) |
| `POST`   | `/mindmap`     | Generate mind map structure     |
| `POST`   | `/quiz`        | Generate quiz with configurable difficulty |

### Podcast

| Method   | Endpoint                             | Description                     |
|----------|--------------------------------------|---------------------------------|
| `POST`   | `/notebooks/{id}/podcast`            | Trigger podcast generation      |
| `GET`    | `/notebooks/{id}/podcast`            | Get podcast status              |
| `GET`    | `/notebooks/{id}/podcast/audio`      | Stream the generated MP3 audio  |
| `DELETE` | `/notebooks/{id}/podcast`            | Delete podcast and audio file   |

### System

| Method   | Endpoint    | Description                    |
|----------|-------------|--------------------------------|
| `GET`    | `/health`   | Liveness check with component status |
| `GET`    | `/stats`    | Vector store statistics         |

---

## Ingestion Pipeline

When a source is uploaded to a notebook, it passes through the following stages:

### PDF Processing

1. **Block-level extraction** -- Text is extracted using PyMuPDF's block bounding boxes rather than raw `get_text()`. Blocks are sorted by column position (left half vs. right half of the page), then top-to-bottom within each column, correcting multi-column reading order.

2. **Header/footer detection** -- Edge lines from the first and last three lines of each page are collected. Any line appearing on more than 60% of pages is classified as a repeated header, footer, or watermark and stripped.

3. **Text cleaning** -- Handles Unicode normalization (NFKC), dehyphenation across line breaks, removal of inline page numbers, structural noise lines (Figure/Table captions), and known artifacts.

4. **Table of Contents filtering** -- Pages where more than 30% of non-empty lines match the pattern "Title ......... 42" are classified as TOC pages and excluded.

5. **Hierarchical section detection** -- Chapter headers (`Chapter N`) and section headers (`N.N Title`) are identified via regex. The document is split into `SectionBlock` objects preserving chapter/section/page metadata. Back matter (Appendix, Glossary, Index) receives distinct tagging.

6. **Per-chunk page attribution** -- Character-level offset-to-page mappings are maintained so each chunk can be attributed to its exact page range rather than the section-level page range.

### Chunking Strategy

The chunker uses a recursive hierarchical splitting algorithm:

1. **Level 1** -- Split on double newlines (paragraph boundaries)
2. **Level 2** -- Split on sentence boundaries using abbreviation-safe detection (handles Dr., U.S., Fig., etc.)
3. **Level 3** -- Split on clause boundaries (semicolons, colons, em dashes)
4. **Level 4** -- Split on whitespace as a last resort

Each level is attempted only when the previous level produces chunks exceeding `chunk_size`. Quality filtering rejects chunks shorter than `min_chunk_size` or with an alphabetic character ratio below `min_letter_ratio`. Content-hash deduplication eliminates repeated chunks.

**Parameters** (configurable in `config.yaml`):
- `chunk_size`: 800 characters (approximately 150--200 words)
- `chunk_overlap`: 100 characters of overlap between consecutive chunks
- `min_chunk_size`: 150 characters minimum
- `min_letter_ratio`: 0.4 (rejects tables of numbers, etc.)
- `cross_section_overlap`: 100 characters carried across section boundaries

### Embedding

- **Model**: BAAI bge-m3 via NVIDIA NIM API (1024 dimensions)
- **Batch size**: 48 texts per API call
- **Concurrency**: 12 parallel workers for API requests
- **Caching**: In-memory cache keyed by SHA-256 hash, persisted to disk as `.npz` on shutdown and loaded at startup. Re-runs skip previously embedded text.
- **Normalization**: L2-normalized vectors for cosine similarity

### Vector Storage

- **Database**: PostgreSQL with pgvector extension
- **Column type**: `vector(1024)` for dimensions up to 2000; `halfvec(N)` for larger dimensions
- **Index**: HNSW (Hierarchical Navigable Small Worlds) with cosine distance operator, `m=16`, `ef_construction=64`
- **Upsert semantics**: Duplicate `chunk_id` values are updated in place, making re-ingestion safe
- **Connection pooling**: Thread-safe `ThreadedConnectionPool` with exponential-backoff retry on transient failures

### Knowledge Graph Construction

After chunks are stored, a knowledge graph is built to enable multi-hop retrieval:

1. **Entity extraction** -- Regex-based extraction identifies named entities and key terms within each chunk.
2. **Edge creation** -- Edges are created between chunks that share entities or have significant keyword overlap, weighted by the strength of the relationship.
3. **Storage** -- Edges are persisted in the `chunk_graph` table with source/target chunk IDs, relationship type, weight, and notebook scope.

---

## Retrieval and Generation

### Source-Aware Retrieval

When a notebook contains multiple sources, retrieval guarantees representation from every document:

1. **Source detection** -- The query is checked for mentions of source filenames using substring matching (minimum 4 character match, case-insensitive).
2. **Slot allocation** -- If a source is mentioned, it receives 70% of `top_k` slots. Remaining slots are distributed evenly across other sources. Without a mention, slots are distributed equally.
3. **Per-source search** -- A single SQL query with `ROW_NUMBER() OVER (PARTITION BY source_id ...)` fetches the best chunks from each source in one database round-trip.
4. **Score normalization** -- Per-source scores are normalized to a 0--1 range to prevent a high-scoring source from dominating results.
5. **Merge** -- Chunks are selected according to slot allocation, with round-robin backfill for any remaining capacity.

### Multi-Hop Graph Expansion

After the initial vector search (hop 0), the retriever expands results using the knowledge graph:

1. **Edge lookup** -- For each retrieved chunk, neighboring chunks are fetched via `chunk_graph` edges.
2. **Scoring** -- Neighbors are scored with a weighted combination: `0.6 * cosine_similarity(query, neighbor) + 0.4 * edge_weight`.
3. **Merge** -- The top `expansion_k` neighbors (default 3) are added to the result set, deduplicated against existing results.
4. **Re-ranking** -- The combined set is sorted by score and truncated to `top_k`.

### Answer Generation

The generator supports dual-provider operation:

- **Primary**: NVIDIA NIM API (`meta/llama-3.3-70b-instruct`)
- **Fallback**: Groq API (`llama-3.3-70b-versatile`)

If NVIDIA fails after exhausting retries (5 attempts with exponential backoff and jitter), the same prompt is automatically sent to Groq. Both providers use SSE streaming for token-by-token response parsing.

The system prompt enforces:
- Answers grounded strictly in provided context
- Inline citation markers (`[1]`, `[2]`) matching numbered passages
- Explicit acknowledgment of insufficient context or contradictions
- Markdown formatting with `###` headings, bold terms, and bullet points

A thread-level semaphore limits concurrent API calls to 2, preventing rate-limit storms during batch processing.

### Answer Validation

An optional post-generation validation step grades answers on three weighted dimensions:

| Dimension          | Weight | Description                                           |
|--------------------|--------|-------------------------------------------------------|
| Faithfulness       | 50%    | Is every claim grounded in context passages?           |
| Completeness       | 30%    | Are all parts of the question addressed?               |
| Citation Accuracy  | 20%    | Do citation markers reference the correct passages?    |

Each dimension is scored 0--10 by a separate LLM call. The weighted overall score must exceed 0.6 to pass. If validation fails, a retry is automatically attempted with corrective feedback appended to the original prompt. The higher-scoring attempt is returned.

---

## Batch Processing

### CLI Pipeline

For offline batch processing (e.g., processing a textbook and generating answers for a question set):

```bash
# Step 1: Extract and chunk a PDF
python scripts/run_pipeline.py --step extract

# Step 2: Embed and store chunks
python scripts/embed_and_store.py --tier balanced --clear --create-index

# Step 3: Generate answers for all queries
python scripts/generate_submission.py
```

Options for `generate_submission.py`:

```bash
python scripts/generate_submission.py --dry-run     # Retrieval only, no LLM calls
python scripts/generate_submission.py --resume       # Resume a partial run
python scripts/generate_submission.py --top-k 7      # Override retrieval depth
```

Output is written to `submission.csv` with columns: `ID`, `context`, `answer`, `references`.

### API Batch Endpoint

Upload a JSON file (`["Q1?", "Q2?"]`) or a PDF containing questions to `POST /notebooks/{id}/batch-query`. All question embeddings are pre-computed in a single bulk call before answers are generated concurrently.

---

## Troubleshooting

**PostgreSQL connection refused**
Verify PostgreSQL is running and accessible. Check `POSTGRES_HOST`, `POSTGRES_PORT`, and `POSTGRES_PASSWORD` in `.env`.

**pgvector extension not found**
Install pgvector and enable it:
```sql
CREATE EXTENSION vector;
```
Refer to the [pgvector installation guide](https://github.com/pgvector/pgvector) for platform-specific instructions.

**NVIDIA API 401 Unauthorized**
Verify your `NVIDIA_API_KEY` in `.env`. Keys should start with `nvapi-`. Obtain a key at [build.nvidia.com](https://build.nvidia.com).

**Embedding API 429 Rate Limit**
The embedder includes automatic retry with exponential backoff. For persistent rate limiting, reduce the worker count or batch size in the embedder configuration.

**No relevant passages found (404)**
Ensure sources have been uploaded to the notebook and their processing status is `ready`. Check with `GET /notebooks/{id}/sources`.

**Podcast generation fails with "DEEPGRAM_API_KEY not set"**
Set `DEEPGRAM_API_KEY` in `.env`. This key is required only for podcast generation.

**Studio features return 500 errors**
Set `GEMINI_API_KEY` in `.env`. Studio features (flashcards, summaries, mind maps, quizzes) require a Google Gemini API key.

**Frontend cannot reach the backend**
Ensure `NEXT_PUBLIC_API_URL` in `frontend/nextjs-project/.env.local` points to the running backend (default: `http://localhost:8000`). Verify CORS is not blocking requests.

**Re-ingest from scratch**
```bash
python scripts/embed_and_store.py --tier balanced --clear --create-index
```

---

## License

This project is provided as-is for educational and research purposes.
