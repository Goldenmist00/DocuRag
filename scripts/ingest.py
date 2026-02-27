#!/usr/bin/env python3
"""
ingest.py
=========
CLI entry point for Phase 1: Corpus Ingestion & Metadata Preparation.

Usage
-----
  # Basic (uses config.yaml defaults)
  python scripts/ingest.py

  # Override paths and chunk settings
  python scripts/ingest.py \
      --pdf data/raw/openstax_psychology_2e.pdf \
      --output data/processed/chunks.jsonl \
      --chunk-size 800 \
      --overlap 100

  # Force re-ingestion even if output already exists
  python scripts/ingest.py --force
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import yaml

# Make sure src/ is importable regardless of working directory
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.pdf_processor import run_ingestion, load_chunks, verify_chunks


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_config(config_path: str = "config.yaml") -> dict:
    """Load YAML config, returning an empty dict if the file is missing."""
    p = Path(config_path)
    if p.exists():
        with open(p, "r") as f:
            return yaml.safe_load(f) or {}
    return {}


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configure root logger with console + file handlers."""
    Path("logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        handlers=[
            logging.FileHandler("logs/ingest.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger("ingest")


def print_report(stats: dict) -> None:
    """Pretty-print the verification report to stdout."""
    print("\n" + "=" * 60)
    print("  PHASE 1 VERIFICATION REPORT")
    print("=" * 60)
    print(f"  Total chunks produced   : {stats['total_chunks']}")
    print(f"  Unique sections found   : {stats['unique_sections']}")
    print(f"  Avg chars per chunk     : {stats['avg_char_count']}")
    print(f"  Avg words per chunk     : {stats['avg_word_count']}")
    print(f"  Min / Max chars         : {stats['min_char_count']} / {stats['max_char_count']}")
    print(f"  Page range covered      : {stats['page_range']}")

    if stats["errors"]:
        print("\n  ❌ ERRORS:")
        for e in stats["errors"]:
            print(f"     • {e}")
    else:
        print("\n  ✅ No errors detected.")

    if stats["warnings"]:
        print("\n  ⚠️  WARNINGS:")
        for w in stats["warnings"]:
            print(f"     • {w}")
    else:
        print("  ✅ No warnings.")

    print("=" * 60 + "\n")


def save_stats(stats: dict, path: str = "data/processed/ingestion_stats.json") -> None:
    """Persist the stats dict as JSON for later inspection."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    # --- Load config defaults ---
    cfg = load_config()
    pdf_cfg      = cfg.get("pdf", {})
    chunk_cfg    = cfg.get("chunking", {})
    cache_cfg    = cfg.get("cache", {})
    log_cfg      = cfg.get("logging", {})

    logger = setup_logging(log_cfg.get("level", "INFO"))

    # --- Argument parsing (CLI overrides config) ---
    parser = argparse.ArgumentParser(
        description="Phase 1: Ingest OpenStax Psychology 2e PDF into chunks."
    )
    parser.add_argument(
        "--pdf",
        default=pdf_cfg.get("input_path", "data/raw/openstax_psychology_2e.pdf"),
        help="Path to the input PDF file.",
    )
    parser.add_argument(
        "--output",
        default=cache_cfg.get("processed_chunks_path", "data/processed/chunks.jsonl"),
        help="Path for the output JSONL file.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=chunk_cfg.get("chunk_size", 800),
        help="Maximum characters per chunk (default: 800).",
    )
    parser.add_argument(
        "--overlap",
        type=int,
        default=chunk_cfg.get("chunk_overlap", 100),
        help="Overlap characters between consecutive chunks (default: 100).",
    )
    parser.add_argument(
        "--min-chunk",
        type=int,
        default=chunk_cfg.get("min_chunk_size", 150),
        help="Minimum chunk length; shorter chunks are discarded (default: 150).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-ingest even if output file already exists.",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Skip ingestion and only verify an existing chunks.jsonl file.",
    )

    args = parser.parse_args()

    # --- Verify-only mode ---
    if args.verify_only:
        logger.info(f"Verify-only mode: loading {args.output}")
        chunks = load_chunks(args.output)
        stats  = verify_chunks(chunks)
        print_report(stats)
        save_stats(stats)
        return

    # --- Check if output already exists ---
    output_path = Path(args.output)
    if output_path.exists() and not args.force:
        logger.info(
            f"Output already exists: {output_path}\n"
            "  Use --force to re-ingest, or --verify-only to check it."
        )
        chunks = load_chunks(args.output)
        stats  = verify_chunks(chunks)
        print_report(stats)
        return

    # --- Check PDF exists ---
    if not Path(args.pdf).exists():
        logger.error(
            f"PDF not found: {args.pdf}\n"
            "  Please place the OpenStax Psychology 2e PDF at that path."
        )
        sys.exit(1)

    # --- Run ingestion ---
    chunks, stats = run_ingestion(
        pdf_path=args.pdf,
        output_path=args.output,
        chunk_size=args.chunk_size,
        chunk_overlap=args.overlap,
        min_chunk=args.min_chunk,
    )

    # --- Report ---
    print_report(stats)
    save_stats(stats)

    if stats["errors"]:
        logger.error("Ingestion finished with errors — review the report above.")
        sys.exit(1)

    logger.info(f"✅ Phase 1 complete. Chunks saved to: {output_path}")


if __name__ == "__main__":
    main()
