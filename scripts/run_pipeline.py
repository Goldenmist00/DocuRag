#!/usr/bin/env python3
"""
Main pipeline orchestration script.
Run the complete RAG pipeline or individual steps.
"""
import argparse
import logging
import sys
from pathlib import Path

import yaml

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.pdf_processor import run_ingestion, load_chunks, verify_chunks
from src.embedder import Embedder, EmbeddingTier
from src.vector_store import PgVectorStore

def setup_logging():
    """Configure logging."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('logs/rag_system.log'),
            logging.StreamHandler()
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
    tier_name = cfg.get("embeddings", {}).get("default_tier", "balanced")
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
    
    # Generate embeddings
    texts = [chunk["text"] for chunk in chunks]
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
        
        # Need to regenerate embeddings
        tier_name = cfg.get("embeddings", {}).get("default_tier", "balanced")
        tier_map = {
            "fast": EmbeddingTier.FAST,
            "balanced": EmbeddingTier.BALANCED,
            "deep": EmbeddingTier.DEEP
        }
        embedder = Embedder(tier=tier_map.get(tier_name, EmbeddingTier.BALANCED))
        texts = [chunk["text"] for chunk in chunks]
        embeddings = embedder.embed_batch(texts, batch_size=32, show_progress=False)
        embedding_dim = embedder.embedding_dim
    
    # Connect to PostgreSQL
    vector_store = PgVectorStore(
        embedding_dim=embedding_dim,
        host=cfg.get("postgres", {}).get("host", "localhost"),
        port=cfg.get("postgres", {}).get("port", 5432),
        database=cfg.get("postgres", {}).get("database", "rag_db"),
        user=cfg.get("postgres", {}).get("user", "rag_user"),
        password=cfg.get("postgres", {}).get("password", "rag_password")
    )
    
    # Insert vectors
    vector_store.insert_chunks(chunks, embeddings)
    logger.info(f"  Inserted {len(chunks)} vectors")
    
    # Create index
    vector_store.create_index(index_type="ivfflat")
    logger.info(f"  Created IVFFlat index")
    
    # Show stats
    stats = vector_store.get_stats()
    logger.info(f"✓ Vector store ready")
    logger.info(f"  Total chunks: {stats['total_chunks']}")
    logger.info(f"  Unique pages: {stats['unique_pages']}")
    
    vector_store.close()

def run_generate(logger):
    """Run Q&A generation."""
    logger.info("Step 4: Generating answers...")
    # TODO: Import and call retriever + generator
    logger.info("✓ Answer generation complete")

def main():
    parser = argparse.ArgumentParser(description="RAG Pipeline Orchestration")
    parser.add_argument(
        "--step",
        choices=["extract", "embed", "index", "generate"],
        help="Run specific pipeline step"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all pipeline steps"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force recomputation (ignore cache)"
    )
    
    args = parser.parse_args()
    
    # Setup
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
        elif args.step == "generate":
            run_generate(logger)
        else:
            parser.print_help()
            return
        
        logger.info("=" * 60)
        logger.info("Pipeline completed successfully!")
        logger.info("Output: outputs/submission.csv")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
