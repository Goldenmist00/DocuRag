# RAG System for OpenStax Psychology 2e Q&A

Production-ready Retrieval-Augmented Generation system with citation-verifiable answers.

## Project Status: 70% Complete ✅

- ✅ Phase 1: PDF Processing & Chunking
- ✅ Phase 2: PostgreSQL Vector Store (pgvector)
- ✅ Phase 3: Three-Tier Embedding System
- ⏳ Phase 4: Two-Stage Retrieval (Next)
- ⏳ Phase 5: NVIDIA LLM Generation
- ⏳ Phase 6: End-to-End Pipeline

## Project Overview

- **Corpus**: OpenStax Psychology 2e PDF (~800 pages)
- **Task**: Answer queries with grounded responses including section references and page numbers
- **Embedding**: Three-tier system (fast/balanced/deep) using sentence-transformers
- **Vector Store**: PostgreSQL with pgvector extension
- **LLM**: NVIDIA free-tier API for answer generation
- **Architecture**: Two-stage retrieval (vector search + cross-encoder reranking)

## Quick Start

### Prerequisites

- Python 3.10 or 3.11 (recommended)
- pip package manager
- 8GB+ RAM recommended
- NVIDIA API key (free tier)

### Installation

```bash
# Clone repository
git clone https://github.com/Goldenmist00/Doctrace.git
cd Doctrace

# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Database Setup

**Option A: Cloud PostgreSQL (Recommended for Hackathons)**
1. Sign up at https://neon.tech (free, no credit card)
2. Create a project
3. Copy connection string
4. Update `config.yaml` with your connection details

**Option B: Local PostgreSQL**
```bash
# Install PostgreSQL + pgvector extension
# Then run:
python scripts/setup_postgres.py
```

**Option C: Docker (Optional)**
```bash
docker-compose up -d
python scripts/setup_postgres.py
```

### Configuration

1. Copy `.env.example` to `.env`
2. Add your NVIDIA API key:
   ```
   NVIDIA_API_KEY=your_api_key_here
   ```

### Project Structure

```
rag-textbook-qa/
├── data/
│   ├── raw/                    # Place OpenStax Psychology 2e PDF here
│   ├── processed/              # Chunked text with metadata
│   └── queries.json            # Input queries
├── embeddings/
│   └── cache/                  # Cached embeddings
├── vector_store/
│   └── faiss_index/            # FAISS index files
├── models/
│   └── sentence-transformers/  # Local embedding models
├── outputs/
│   └── submission.csv          # Final output
├── src/
│   ├── __init__.py
│   ├── pdf_processor.py        # PDF extraction and chunking
│   ├── embedder.py             # Embedding generation
│   ├── vector_store.py         # FAISS operations
│   ├── retriever.py            # Retrieval logic
│   └── generator.py            # NVIDIA LLM integration
├── scripts/
│   ├── download_models.py      # Pre-download models
│   ├── setup_data.py           # Initialize data directories
│   └── run_pipeline.py         # End-to-end execution
├── tests/
│   └── test_components.py      # Unit tests
├── .env.example
├── .gitignore
├── requirements.txt
├── requirements-dev.txt
├── Dockerfile
├── docker-compose.yml
└── README.md
```

## Running the Pipeline

### Quick Start (Recommended)

```bash
# 1. Process PDF and create chunks
python scripts/test_pdf_chunking.py data/raw/your-book.pdf

# 2. Generate embeddings and store in database (all-in-one)
python scripts/embed_and_store.py --tier balanced --clear --create-index

# 3. Test vector search
python scripts/test_vector_search.py --query "What is memory?" --top-k 5
```

### Step-by-Step Execution

```bash
# 1. Extract and chunk PDF
python scripts/run_pipeline.py --step extract

# 2. Generate embeddings
python scripts/run_pipeline.py --step embed

# 3. Store vectors and create index
python scripts/run_pipeline.py --step index

# 4. Run Q&A pipeline (when ready)
python scripts/run_pipeline.py --step generate

# Or run all steps at once:
python scripts/run_pipeline.py --all
```

### Embedding Tiers

Choose based on your needs:

- **Fast** (384d, 80MB): Quick prototyping, ~13 chunks/s
- **Balanced** (768d, 438MB): Production default, ~3 chunks/s ⭐
- **Deep** (1024d, 1.34GB): Maximum precision, ~1-2 chunks/s

```bash
# Use specific tier
python scripts/embed_and_store.py --tier fast --clear --create-index
```

### Caching Strategy

- **Embeddings**: Content-based caching with SHA-256 hashing in `embeddings/cache/`
- **Models**: Auto-downloaded to `models/sentence-transformers/` on first use
- **Processed Chunks**: Stored in `data/processed/chunks.jsonl`
- **Vector Index**: PostgreSQL IVFFlat/HNSW index for fast search

Second runs use cached embeddings (100% hit rate) for instant results.

## Docker Setup (Optional)

```bash
# Build image
docker-compose build

# Run pipeline
docker-compose run rag-app python scripts/run_pipeline.py --all

# Interactive shell
docker-compose run rag-app bash
```

## Reproducibility

- All dependencies pinned in `requirements.txt`
- Random seeds set in configuration
- Model versions specified
- Deterministic chunking strategy
- Cache invalidation based on content hashes

## Development

```bash
# Install dev dependencies
pip install -r requirements-dev.txt

# Run tests
pytest tests/

# Format code
black src/ scripts/

# Lint
flake8 src/ scripts/
```

## Documentation

- **[USAGE.md](docs/USAGE.md)** - Complete usage guide
- **[EMBEDDER.md](docs/EMBEDDER.md)** - Embedding system documentation
- **[INTEGRATION_COMPLETE.md](docs/INTEGRATION_COMPLETE.md)** - Phase 3 completion summary
- **[IMPROVEMENTS.md](IMPROVEMENTS.md)** - Code quality improvements
- **[TODO.md](TODO.md)** - Task tracking (70% complete)

## Key Features

✅ Three-tier embedding system (fast/balanced/deep)
✅ Content-based caching with SHA-256 hashing
✅ PostgreSQL + pgvector for scalable vector storage
✅ Connection pooling and retry logic
✅ Performance metrics tracking
✅ Comprehensive error handling
✅ Type hints and docstrings throughout
✅ GPU acceleration support

## Troubleshooting

**PostgreSQL Connection Issues**:
```bash
docker-compose down
docker-compose up -d
docker-compose logs postgres
```

**Models Not Downloading**:
```bash
python scripts/download_models.py
```

**Clear Cache**:
```bash
rm -rf embeddings/cache/*
python scripts/embed_and_store.py --clear
```

**Out of Memory**: Use fast tier or reduce batch size in scripts

## License

MIT
