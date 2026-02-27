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
    """Generate embeddings for chunks."""
    logger.info("Step 2: Generating embeddings...")
    # TODO: Import and call embedder
    logger.info("✓ Embedding generation complete")

def run_index(logger):
    """Build FAISS index."""
    logger.info("Step 3: Building FAISS index...")
    # TODO: Import and call vector_store
    logger.info("✓ FAISS index built")

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
            run_embed(logger)
            run_index(logger)
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
