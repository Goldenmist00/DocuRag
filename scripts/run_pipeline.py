#!/usr/bin/env python3
"""
Main pipeline orchestration script.
Run the complete RAG pipeline or individual steps.
"""
import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import yaml
from dotenv import load_dotenv

# Load .env from project root regardless of cwd
_ROOT = Path(__file__).parent.parent
load_dotenv(_ROOT / ".env")

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.pdf_processor import run_ingestion, load_chunks, verify_chunks
from src.embedder import Embedder, EmbeddingTier
from src.vector_store import PgVectorStore
from src.retriever import create_retriever
from src.generator import Generator


def setup_logging():
    """Configure logging with UTF-8 stream handler for Windows compatibility."""
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('logs/rag_system.log', encoding='utf-8'),
            logging.StreamHandler(
                stream=open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1, closefd=False)
            ),
        ]
    )
    return logging.getLogger(__name__)

def run_extract(logger):
    """Extract and chunk PDF text (Phase 1)."""
    logger.info("Step 1: Extracting and chunking PDF...")

    # Load config
    cfg_path = Path("config.yaml")
    cfg = {}
    if cfg_path.exists():
        with open(cfg_path) as f:
            cfg = yaml.safe_load(f) or {}

    pdf_path    = cfg.get("pdf", {}).get("input_path",   "data/raw/openstax_psychology_2e.pdf")
    output_path = cfg.get("cache", {}).get("processed_chunks_path", "data/processed/chunks.jsonl")
    chunk_size  = cfg.get("chunking", {}).get("chunk_size",   800)
    overlap     = cfg.get("chunking", {}).get("chunk_overlap", 100)
    min_chunk   = cfg.get("chunking", {}).get("min_chunk_size", 150)

    chunks, stats = run_ingestion(
        pdf_path=pdf_path,
        output_path=output_path,
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        min_chunk=min_chunk,
    )

    if stats["errors"]:
        raise RuntimeError(f"Ingestion errors: {stats['errors']}")

    logger.info(f"✓ PDF extraction complete — {stats['total_chunks']} chunks, "
                f"{stats['unique_sections']} sections, "
                f"pages {stats['page_range']}")


def run_embed(logger):
    """Generate embeddings for chunks (Phase 3)."""
    logger.info("Step 2: Generating embeddings...")
    
    # Load config
    cfg_path = Path("config.yaml")
    cfg = {}
    if cfg_path.exists():
        with open(cfg_path) as f:
            cfg = yaml.safe_load(f) or {}
    
    # Get paths and settings
    chunks_path = cfg.get("cache", {}).get("processed_chunks_path", "data/processed/chunks.jsonl")
    tier_name = cfg.get("embedding", {}).get("tier", "balanced")
    cache_dir = cfg.get("cache", {}).get("embeddings_cache", "embeddings/cache")
    
    # Map tier name to enum
    tier_map = {
        "fast": EmbeddingTier.FAST,
        "balanced": EmbeddingTier.BALANCED,
        "deep": EmbeddingTier.DEEP
    }
    tier = tier_map.get(tier_name, EmbeddingTier.BALANCED)
    
    # Load chunks
    chunks = load_chunks(chunks_path)
    logger.info(f"  Loaded {len(chunks)} chunks")
    
    # Initialize embedder
    embedder = Embedder(tier=tier, cache_dir=cache_dir)
    logger.info(f"  Using {embedder.model_name} ({embedder.embedding_dim}d)")
    
    # Generate embeddings — load_chunks() returns Pydantic objects
    texts = [chunk.text for chunk in chunks]
    embeddings = embedder.embed_batch(texts, batch_size=32, show_progress=True)
    
    stats = embedder.get_stats()
    logger.info(f"✓ Generated {len(embeddings)} embeddings")
    logger.info(f"  Cache hit rate: {stats['hit_rate']:.1%}")
    
    return chunks, embeddings, embedder.embedding_dim

def run_index(logger, chunks=None, embeddings=None, embedding_dim=None):
    """Insert embeddings into PostgreSQL vector store (Phase 2)."""
    logger.info("Step 3: Storing vectors in PostgreSQL...")
    
    # Load config
    cfg_path = Path("config.yaml")
    cfg = {}
    if cfg_path.exists():
        with open(cfg_path) as f:
            cfg = yaml.safe_load(f) or {}
    
    # If not provided, load chunks and embeddings
    if chunks is None or embeddings is None:
        logger.info("  Loading chunks and embeddings...")
        chunks_path = cfg.get("cache", {}).get("processed_chunks_path", "data/processed/chunks.jsonl")
        chunks = load_chunks(chunks_path)
        
        cache_dir = cfg.get("cache", {}).get("embeddings_cache", "embeddings/cache")
        embedder = Embedder(cache_dir=cache_dir)
        texts = [chunk.text for chunk in chunks]
        embeddings = embedder.embed_batch(texts, show_progress=True, use_cache=True)
        embedding_dim = embedder.embedding_dim

    # Connect to PostgreSQL — config path: vector_store.connection
    pg = cfg.get("vector_store", {}).get("connection", {})
    vector_store = PgVectorStore(
        embedding_dim=embedding_dim,
        host=pg.get("host", "localhost"),
        port=pg.get("port", 5432),
        database=pg.get("database", "rag_db"),
        user=pg.get("user", "postgres"),
        password=pg.get("password", ""),
    )
    
    # Insert vectors
    vector_store.insert_chunks(chunks, embeddings)
    logger.info(f"  Inserted {len(chunks)} vectors")
    
    # Create index — IVFFlat max is 2000d, use HNSW for 4096d
    vector_store.create_index(index_type="hnsw")
    logger.info(f"  Created HNSW index")
    
    # Show stats
    stats = vector_store.get_stats()
    logger.info(f"✓ Vector store ready")
    logger.info(f"  Total chunks: {stats['total_chunks']}")
    logger.info(f"  Unique pages: {stats['unique_pages']}")
    
    vector_store.close()

def run_load(logger):
    """Load chunks + cached embeddings directly into DB — skips NVIDIA API entirely."""
    logger.info("Step: Loading from cache into PostgreSQL (no API calls)...")

    cfg_path = Path("config.yaml")
    cfg = {}
    if cfg_path.exists():
        with open(cfg_path) as f:
            cfg = yaml.safe_load(f) or {}

    chunks_path = cfg.get("cache", {}).get("processed_chunks_path", "data/processed/chunks.jsonl")
    cache_dir   = Path(cfg.get("cache", {}).get("embeddings_cache", "embeddings/cache"))
    cache_file  = cache_dir / "embeddings_cache.npz"

    if not Path(chunks_path).exists():
        raise FileNotFoundError(f"Chunks file not found: {chunks_path} — run --step extract first")
    if not cache_file.exists():
        raise FileNotFoundError(f"Embeddings cache not found: {cache_file} — run --step embed first")

    chunks = load_chunks(chunks_path)
    logger.info("  Loaded %d chunks", len(chunks))

    # Load cache and match to chunks by SHA-256 hash (same key used by Embedder)
    import hashlib as _hashlib
    store = dict(np.load(cache_file, allow_pickle=False))
    logger.info("  Cache contains %d embeddings", len(store))

    def _hash(text: str) -> str:
        return _hashlib.sha256(text.encode("utf-8")).hexdigest()

    embeddings_list = []
    missing = []
    for chunk in chunks:
        h = _hash(chunk.text)
        if h in store:
            embeddings_list.append(store[h])
        else:
            missing.append(chunk.chunk_id)

    if missing:
        raise RuntimeError(
            f"{len(missing)} chunks have no cached embedding. "
            "Run --step embed first to populate the cache."
        )

    embeddings = np.vstack(embeddings_list)
    embedding_dim = embeddings.shape[1]
    logger.info("  Embeddings shape: %s (dim=%d)", embeddings.shape, embedding_dim)

    pg = cfg.get("vector_store", {}).get("connection", {})
    vector_store = PgVectorStore(
        embedding_dim=embedding_dim,
        host=pg.get("host", "localhost"),
        port=pg.get("port", 5432),
        database=pg.get("database", "rag_db"),
        user=pg.get("user", "postgres"),
        password=pg.get("password", ""),
    )

    vector_store.insert_chunks(chunks, embeddings)
    logger.info("  Inserted %d vectors", len(chunks))

    vector_store.create_index(index_type="hnsw")

    stats = vector_store.get_stats()
    logger.info("✓ Vector store ready — %d chunks, %d pages", stats["total_chunks"], stats["unique_pages"])
    vector_store.close()


def run_generate(logger):
    """Run Q&A generation — delegates to generate_submission logic."""
    logger.info("Step 4: Generating answers...")

    import os
    sys.path.insert(0, str(Path(__file__).parent))
    from generate_submission import load_config, load_queries, build_components, run, QUERIES_PATH

    cfg     = load_config()
    queries = load_queries(QUERIES_PATH)

    nvidia_key   = os.getenv("NVIDIA_API_KEY", "").strip()
    groq_key     = os.getenv("GROQ_API_KEY",   "").strip()
    nvidia_ready = bool(nvidia_key and nvidia_key != "your_nvidia_api_key_here")
    dry_run      = not nvidia_ready and not groq_key

    if dry_run:
        logger.warning("No LLM provider configured — running retrieval-only dry-run")

    retriever, _ = build_components(cfg)

    generator = None
    if not dry_run:
        from src.generator import Generator
        gen_cfg = cfg.get("generation", {})
        generator = Generator(
            model=gen_cfg.get("model") or None,
            temperature=gen_cfg.get("temperature", 1.0),
            max_tokens=gen_cfg.get("max_tokens", 4096),
            top_p=gen_cfg.get("top_p", 1.0),
        )

    output_path = Path("outputs/submission.csv")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    run(queries=queries, retriever=retriever, generator=generator,
        output_path=output_path, dry_run=dry_run)

    retriever.vector_store.close()
    logger.info("Answer generation complete — output: %s", output_path)


def main():
    parser = argparse.ArgumentParser(description="RAG Pipeline Orchestration")
    parser.add_argument(
        "--step",
        choices=["extract", "embed", "index", "load", "generate"],
        help="Run specific pipeline step"
    )
    parser.add_argument("--all", action="store_true", help="Run all pipeline steps")
    parser.add_argument("--force", action="store_true", help="Force recomputation (ignore cache)")
    args = parser.parse_args()

    Path("logs").mkdir(exist_ok=True)
    logger = setup_logging()

    logger.info("=" * 60)
    logger.info("RAG Pipeline Starting")
    logger.info("=" * 60)

    try:
        if args.all:
            run_extract(logger)
            chunks, embeddings, embedding_dim = run_embed(logger)
            run_index(logger, chunks, embeddings, embedding_dim)
            run_generate(logger)
        elif args.step == "extract":
            run_extract(logger)
        elif args.step == "embed":
            run_embed(logger)
        elif args.step == "index":
            run_index(logger)
        elif args.step == "load":
            run_load(logger)
        elif args.step == "generate":
            run_generate(logger)
        else:
            parser.print_help()
            return

        logger.info("=" * 60)
        logger.info("Pipeline completed successfully!")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
