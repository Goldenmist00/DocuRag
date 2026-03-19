#!/usr/bin/env python3
"""
Embed chunks and store them in PostgreSQL vector database.
This script bridges Phase 3 (Embeddings) and Phase 2 (Vector Store).
"""
import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Dict, Any

import yaml

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.embedder import Embedder, EmbeddingTier
from src.pdf_processor import load_chunks
from src.vector_store import PgVectorStore


def setup_logging() -> logging.Logger:
    """Configure logging for the script."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    return logging.getLogger(__name__)


def load_config() -> Dict[str, Any]:
    """Load configuration from config.yaml."""
    cfg_path = Path("config.yaml")
    if not cfg_path.exists():
        raise FileNotFoundError("config.yaml not found")
    
    with open(cfg_path) as f:
        return yaml.safe_load(f) or {}


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description="Generate embeddings and store in PostgreSQL vector database"
    )
    parser.add_argument(
        "--tier",
        choices=["fast", "balanced", "deep"],
        default="balanced",
        help="Embedding tier to use (default: balanced)"
    )
    parser.add_argument(
        "--chunks",
        type=str,
        help="Path to chunks JSONL file (default: from config)"
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear existing vectors before inserting"
    )
    parser.add_argument(
        "--create-index",
        action="store_true",
        help="Create vector index after insertion"
    )
    parser.add_argument(
        "--index-type",
        choices=["ivfflat", "hnsw"],
        default="ivfflat",
        help="Index type to create (default: ivfflat)"
    )
    
    args = parser.parse_args()
    logger = setup_logging()
    
    logger.info("=" * 70)
    logger.info("EMBEDDING AND STORAGE PIPELINE")
    logger.info("=" * 70)
    
    try:
        # Load configuration
        cfg = load_config()
        
        # Determine chunks path
        chunks_path = args.chunks or cfg.get("cache", {}).get(
            "processed_chunks_path", 
            "data/processed/chunks.jsonl"
        )
        
        logger.info(f"Configuration loaded")
        logger.info(f"  Tier: {args.tier}")
        logger.info(f"  Chunks: {chunks_path}")
        
        # Step 1: Load chunks
        logger.info("\n" + "=" * 70)
        logger.info("STEP 1: Loading chunks")
        logger.info("=" * 70)
        
        chunks = load_chunks(chunks_path)
        logger.info(f"✓ Loaded {len(chunks)} chunks")
        
        # Step 2: Initialize embedder
        logger.info("\n" + "=" * 70)
        logger.info("STEP 2: Initializing embedder")
        logger.info("=" * 70)
        
        tier_map = {
            "fast": EmbeddingTier.FAST,
            "balanced": EmbeddingTier.BALANCED,
            "deep": EmbeddingTier.DEEP
        }
        
        embedder = Embedder(
            tier=tier_map[args.tier],
            cache_dir=cfg.get("cache", {}).get("embeddings_cache", "embeddings/cache")
        )
        
        logger.info(f"✓ Embedder initialized")
        logger.info(f"  Model: {embedder.model_name}")
        logger.info(f"  Dimensions: {embedder.embedding_dim}")
        logger.info(f"  Device: {embedder.device}")
        
        # Step 3: Generate embeddings
        logger.info("\n" + "=" * 70)
        logger.info("STEP 3: Generating embeddings")
        logger.info("=" * 70)
        
        start_time = time.time()
        texts = [chunk.text for chunk in chunks]
        embeddings = embedder.embed_batch(texts, batch_size=32, show_progress=True)
        embed_time = time.time() - start_time
        
        logger.info(f"✓ Generated {len(embeddings)} embeddings")
        logger.info(f"  Time: {embed_time:.2f}s")
        logger.info(f"  Speed: {len(embeddings)/embed_time:.1f} chunks/s")
        logger.info(f"  Shape: {embeddings.shape}")
        
        # Get embedder stats
        stats = embedder.get_stats()
        logger.info(f"  Cache hits: {stats['cache_hits']}")
        logger.info(f"  Cache misses: {stats['cache_misses']}")
        logger.info(f"  Hit rate: {stats['hit_rate']:.1%}")
        
        # Step 4: Connect to vector store
        logger.info("\n" + "=" * 70)
        logger.info("STEP 4: Connecting to PostgreSQL")
        logger.info("=" * 70)

        pg = cfg.get("vector_store", {}).get("connection", {})
        vector_store = PgVectorStore(
            embedding_dim=embedder.embedding_dim,
            host=pg.get("host", "localhost"),
            port=pg.get("port", 5432),
            database=pg.get("database", "rag_db"),
            user=pg.get("user", "postgres"),
            password=pg.get("password", ""),
        )
        
        logger.info(f"✓ Connected to PostgreSQL")
        
        # Step 5: Clear if requested
        if args.clear:
            logger.info("\n" + "=" * 70)
            logger.info("STEP 5: Clearing existing vectors")
            logger.info("=" * 70)
            
            vector_store.clear()
            logger.info(f"✓ Database cleared")
        
        # Step 6: Insert embeddings
        logger.info("\n" + "=" * 70)
        logger.info(f"STEP {'6' if args.clear else '5'}: Inserting vectors into database")
        logger.info("=" * 70)
        
        start_time = time.time()
        vector_store.insert_chunks(chunks, embeddings)
        insert_time = time.time() - start_time
        
        logger.info(f"✓ Inserted {len(chunks)} vectors")
        logger.info(f"  Time: {insert_time:.2f}s")
        logger.info(f"  Speed: {len(chunks)/insert_time:.1f} chunks/s")
        
        # Step 7: Create index if requested
        if args.create_index:
            logger.info("\n" + "=" * 70)
            logger.info(f"STEP {'7' if args.clear else '6'}: Creating vector index")
            logger.info("=" * 70)
            
            start_time = time.time()
            vector_store.create_index(index_type=args.index_type)
            index_time = time.time() - start_time
            
            logger.info(f"✓ Created {args.index_type.upper()} index")
            logger.info(f"  Time: {index_time:.2f}s")
        
        # Step 8: Show database stats
        logger.info("\n" + "=" * 70)
        logger.info("DATABASE STATISTICS")
        logger.info("=" * 70)
        
        db_stats = vector_store.get_stats()
        logger.info(f"  Total chunks: {db_stats['total_chunks']}")
        logger.info(f"  Unique pages: {db_stats['unique_pages']}")
        logger.info(f"  Unique sections: {db_stats['unique_sections']}")
        logger.info(f"  Embedding dimension: {db_stats['embedding_dim']}")
        logger.info(f"  Has index: {db_stats['has_index']}")
        
        # Cleanup
        vector_store.close()
        
        logger.info("\n" + "=" * 70)
        logger.info("✓ PIPELINE COMPLETE")
        logger.info("=" * 70)
        logger.info(f"Total time: {embed_time + insert_time:.2f}s")
        logger.info(f"Ready for retrieval!")
        
    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
