# RAG System for OpenStax Psychology 2e Q&A

Production-ready Retrieval-Augmented Generation system for textbook-based question answering.

## Project Overview

- **Corpus**: OpenStax Psychology 2e PDF (~800 pages)
- **Task**: Answer queries with grounded responses including section references and page numbers
- **Embedding**: Local embedding model (sentence-transformers)
- **Vector Store**: FAISS for efficient similarity search
- **LLM**: NVIDIA free-tier API for answer generation

## Quick Start

### Prerequisites

- Python 3.10 or 3.11 (recommended)
- pip package manager
- 8GB+ RAM recommended
- NVIDIA API key (free tier)

### Installation

```bash
# Clone or navigate to project directory
cd rag-textbook-qa

# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Download embedding model (first run only)
python scripts/download_models.py
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

### Step-by-step execution:

```bash
# 1. Process PDF and create chunks
python scripts/run_pipeline.py --step extract

# 2. Generate embeddings
python scripts/run_pipeline.py --step embed

# 3. Build FAISS index
python scripts/run_pipeline.py --step index

# 4. Run Q&A pipeline
python scripts/run_pipeline.py --step generate

# Or run all steps at once:
python scripts/run_pipeline.py --all
```

### Caching Strategy

- **Embeddings**: Cached in `embeddings/cache/` as pickle files
- **FAISS Index**: Saved in `vector_store/faiss_index/`
- **Processed Chunks**: Stored in `data/processed/chunks.jsonl`
- **Models**: Downloaded once to `models/` directory

Subsequent runs will skip already-completed steps unless `--force` flag is used.

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

## Troubleshooting

**Out of Memory**: Reduce batch size in config or process in smaller chunks
**FAISS Issues**: Ensure numpy version compatibility
**PDF Extraction**: Install poppler-utils if using pdf2image

## License

MIT
