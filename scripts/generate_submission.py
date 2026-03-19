#!/usr/bin/env python3
"""
generate_submission.py
======================
Primary deliverable — runs the full RAG pipeline over every query in
data/queries.json and writes submission.csv.

Output columns:
  ID         — query_id from queries.json
  context    — concatenated retrieved chunk texts (newline-separated)
  answer     — LLM-generated answer (NVIDIA API)
  references — JSON string: {"sections": [...], "pages": [...]}

Features:
  - Progress bar via tqdm
  - Per-query error isolation (one bad query never kills the run)
  - Resume support: skips queries already present in output file
  - Dry-run mode: retrieval only, no API calls
  - Configurable top-k and embedding tier via CLI flags

Usage:
    # Full run (requires NVIDIA_API_KEY in .env)
    python scripts/generate_submission.py

    # Dry run — retrieval only, no LLM calls
    python scripts/generate_submission.py --dry-run

    # Override top-k and tier
    python scripts/generate_submission.py --top-k 7 --tier balanced

    # Resume a partial run
    python scripts/generate_submission.py --resume

    # Custom output path
    python scripts/generate_submission.py --output outputs/my_submission.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional

import yaml
from dotenv import load_dotenv
from tqdm import tqdm

# Load .env from project root regardless of cwd
load_dotenv(Path(__file__).parent.parent / ".env")

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.embedder import Embedder, EmbeddingTier
from src.generator import Generator
from src.retriever import Retriever, RetrievedChunk, create_retriever
from src.vector_store import PgVectorStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

QUERIES_PATH = Path("data/queries.json")
DEFAULT_OUTPUT = Path("submission.csv")
CSV_COLUMNS = ["ID", "context", "answer", "references"]

_TIER_MAP = {
    "fast":     EmbeddingTier.FAST,
    "balanced": EmbeddingTier.BALANCED,
    "deep":     EmbeddingTier.DEEP,
}


# ---------------------------------------------------------------------------
# Config / setup helpers
# ---------------------------------------------------------------------------

def load_config() -> Dict:
    """Load config.yaml from project root."""
    cfg_path = Path("config.yaml")
    if not cfg_path.exists():
        raise FileNotFoundError(
            "config.yaml not found — run from the project root."
        )
    with open(cfg_path) as f:
        return yaml.safe_load(f) or {}


def load_queries(path: Path = QUERIES_PATH) -> List[Dict]:
    """
    Load queries from JSON file.

    Args:
        path: Path to queries.json.

    Returns:
        List of dicts with keys ``query_id`` and ``question``.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file is empty or malformed.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"Queries file not found: {path}\n"
            "Download it from the hackathon portal and place it at data/queries.json"
        )
    with open(path) as f:
        queries = json.load(f)
    if not queries:
        raise ValueError(f"No queries found in {path}")
    logger.info("Loaded %d queries from %s", len(queries), path)
    return queries


def load_existing_ids(output_path: Path) -> set:
    """
    Read already-completed query IDs from an existing CSV (for resume).

    Args:
        output_path: Path to the (possibly partial) submission CSV.

    Returns:
        Set of query_id strings already present in the file.
    """
    if not output_path.exists():
        return set()
    with open(output_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return {row["ID"] for row in reader if row.get("ID")}


def build_components(
    cfg: Dict,
    tier_override: Optional[str] = None,
    top_k_override: Optional[int] = None,
) -> tuple[Retriever, Optional[Generator]]:
    """
    Construct Embedder → PgVectorStore → Retriever and optionally Generator.

    Args:
        cfg:            Parsed config.yaml dict.
        tier_override:  CLI tier override.
        top_k_override: CLI top-k override.

    Returns:
        (retriever, generator_or_None)
    """
    tier_name = tier_override or cfg.get("embedding", {}).get("tier", "balanced")
    tier = _TIER_MAP.get(tier_name, EmbeddingTier.BALANCED)

    embedder = Embedder(
        tier=tier,
        cache_dir=cfg.get("cache", {}).get("embeddings_cache", "embeddings/cache"),
    )

    pg = cfg.get("vector_store", {}).get("connection", {})
    vector_store = PgVectorStore(
        embedding_dim=embedder.embedding_dim,
        host=pg.get("host", "localhost"),
        port=int(pg.get("port", 5432)),
        database=pg.get("database", "rag_db"),
        user=pg.get("user", "postgres"),
        password=pg.get("password", "postgres"),
    )

    retrieval_cfg = cfg.get("retrieval", {})
    if top_k_override is not None:
        retrieval_cfg = {**retrieval_cfg, "top_k": top_k_override}

    retriever = create_retriever(
        embedder=embedder,
        vector_store=vector_store,
        cfg=retrieval_cfg,
    )

    return retriever, None  # generator built separately after API key check


# ---------------------------------------------------------------------------
# Row formatting
# ---------------------------------------------------------------------------

def format_references(chunks: List[RetrievedChunk]) -> str:
    """
    Build the references JSON string from retrieved chunks.

    Format: {"sections": ["1.1", "1.2", ...], "pages": [12, 13, ...]}

    Args:
        chunks: Retrieved chunks for a single query.

    Returns:
        JSON-encoded references string.
    """
    sections = sorted({c.section_id for c in chunks if c.section_id})
    pages = sorted({c.page_start for c in chunks if c.page_start})
    return json.dumps({"sections": sections, "pages": pages})


def format_context(chunks: List[RetrievedChunk]) -> str:
    """
    Concatenate chunk texts into a single context string.

    Args:
        chunks: Retrieved chunks for a single query.

    Returns:
        Newline-separated passage texts.
    """
    return "\n".join(c.text for c in chunks)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run(
    queries: List[Dict],
    retriever: Retriever,
    generator: Optional[Generator],
    output_path: Path,
    resume: bool = False,
    dry_run: bool = False,
    workers: int = 4,
) -> None:
    """
    Run the full RAG pipeline over all queries and write submission.csv.

    Uses a thread pool so multiple queries are retrieved + generated in
    parallel, cutting total wall-clock time significantly.

    Args:
        queries:     List of {query_id, question} dicts.
        retriever:   Configured Retriever instance.
        generator:   Configured Generator instance (None in dry-run mode).
        output_path: Path to write the CSV output.
        resume:      Skip queries already in the output file (skips error rows too).
        dry_run:     Retrieval only — write empty answers.
        workers:     Thread pool size (default 4 — safe for both APIs).
    """
    # Resume: find already-done IDs (exclude error rows so they get retried)
    done_ids: set = set()
    if resume and output_path.exists():
        raw_ids = load_existing_ids(output_path)
        # Re-read to filter out error placeholder rows
        with open(output_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            done_ids = {
                row["ID"] for row in reader
                if row.get("ID") and not row.get("answer", "").startswith("[ERROR:")
            }
        logger.info("Resume mode: %d valid queries already done", len(done_ids))

    pending = [q for q in queries if q.get("query_id", "") not in done_ids]
    skipped = len(queries) - len(pending)

    write_mode  = "a" if (resume and done_ids) else "w"
    write_header = write_mode == "w"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    errors: List[str] = []
    processed = 0

    def process_query(item: Dict) -> Dict:
        """Retrieve + generate for one query. Returns a CSV row dict."""
        qid      = item.get("query_id", "")
        question = item.get("question", "")
        try:
            chunks     = retriever.retrieve(question)
            context    = format_context(chunks)
            references = format_references(chunks)
            if dry_run or generator is None:
                answer = "[dry-run: no answer generated]"
            else:
                answer = generator.generate(question=question, chunks=chunks).answer
            return {"ID": qid, "context": context, "answer": answer, "references": references, "_ok": True}
        except Exception as exc:
            logger.error("Query %s failed: %s", qid, exc)
            return {
                "ID": qid, "context": "", "references": json.dumps({"sections": [], "pages": []}),
                "answer": f"[ERROR: {exc}]", "_ok": False, "_err": f"{qid}: {exc}",
            }

    with open(output_path, write_mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        if write_header:
            writer.writeheader()

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(process_query, q): q for q in pending}
            with tqdm(total=len(pending), desc="Generating", unit="query") as bar:
                for future in as_completed(futures):
                    row = future.result()
                    ok  = row.pop("_ok", True)
                    err = row.pop("_err", None)
                    writer.writerow({k: row[k] for k in CSV_COLUMNS})
                    f.flush()
                    if ok:
                        processed += 1
                    else:
                        errors.append(err or row["ID"])
                    bar.update(1)

    print(f"\n{'=' * 60}")
    print(f"Done. {processed} queries processed, {skipped} skipped (resume).")
    if errors:
        print(f"{len(errors)} errors:")
        for e in errors:
            print(f"  - {e}")
    print(f"Output: {output_path.resolve()}")
    print("=" * 60)


def _is_bad_answer(answer: str) -> bool:
    """Return True if the answer is empty, truncated, or a known bad pattern."""
    if not answer or not answer.strip():
        return True
    a = answer.strip()
    if a == "The":
        return True
    if a.startswith("[ERROR:"):
        return True
    # Truncated: starts with "According to the context" but is very short
    if a.startswith("According to the context") and len(a) < 80:
        return True
    return False


def retry_empty(
    output_path: Path,
    queries: List[Dict],
    retriever: Retriever,
    generator: Generator,
) -> None:
    """
    Re-run only queries with bad/empty answers and overwrite those rows in the CSV.

    Args:
        output_path: Path to existing submission.csv.
        queries:     Full list of {query_id, question} dicts.
        retriever:   Configured Retriever instance.
        generator:   Configured Generator instance.
    """
    if not output_path.exists():
        raise FileNotFoundError(f"Output file not found: {output_path}")

    # Read all existing rows
    with open(output_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # Find bad row IDs
    bad_ids = {row["ID"] for row in rows if _is_bad_answer(row.get("answer", ""))}
    if not bad_ids:
        print("No bad answers found — nothing to retry.")
        return

    logger.info("Retrying %d bad answers: %s", len(bad_ids), sorted(bad_ids))

    # Build lookup: query_id → question
    q_lookup = {str(q["query_id"]): q["question"] for q in queries}

    # Re-run single-threaded to avoid rate limiting
    retried: Dict[str, Dict] = {}
    for qid in sorted(bad_ids):
        question = q_lookup.get(qid)
        if not question:
            logger.warning("query_id %s not found in queries.json — skipping", qid)
            continue
        logger.info("  Retrying query %s...", qid)
        try:
            chunks     = retriever.retrieve(question)
            context    = format_context(chunks)
            references = format_references(chunks)
            answer     = generator.generate(question=question, chunks=chunks).answer
            retried[qid] = {"ID": qid, "context": context, "answer": answer, "references": references}
            logger.info("  ✓ Query %s done (%d chars)", qid, len(answer))
        except Exception as exc:
            logger.error("  Query %s failed again: %s", qid, exc)
            retried[qid] = {
                "ID": qid,
                "context": "",
                "answer": f"[ERROR: {exc}]",
                "references": json.dumps({"sections": [], "pages": []}),
            }

    # Overwrite only the retried rows, keep everything else
    updated = []
    for row in rows:
        if row["ID"] in retried:
            updated.append(retried[row["ID"]])
        else:
            updated.append(row)

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(updated)

    print(f"\n{'=' * 60}")
    print(f"Retried {len(retried)} queries. Output: {output_path.resolve()}")
    print("=" * 60)




def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate submission.csv via full RAG pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--queries",
        type=Path,
        default=QUERIES_PATH,
        help=f"Path to queries JSON file (default: {QUERIES_PATH})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output CSV path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--tier",
        choices=["fast", "balanced", "deep"],
        default=None,
        help="Embedding tier override (default: from config.yaml)",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=None,
        dest="top_k",
        help="Number of chunks to retrieve per query (default: from config.yaml)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Retrieval only — skip LLM generation (no API key needed)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip queries already present in the output file",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Parallel worker threads for generation (default: 4)",
    )
    parser.add_argument(
        "--retry-empty",
        action="store_true",
        dest="retry_empty",
        help="Re-run queries with empty/truncated answers and overwrite those rows",
    )
    return parser.parse_args()


def main() -> None:
    """Entry point."""
    args = parse_args()

    # ── Load config and queries ───────────────────────────────────────────
    cfg = load_config()
    queries = load_queries(args.queries)

    # ── Retry-empty mode ──────────────────────────────────────────────────
    if args.retry_empty:
        logger.info("Retry-empty mode: scanning %s for bad answers...", args.output)
        try:
            retriever, _ = build_components(cfg, args.tier, args.top_k)
        except Exception as exc:
            print(f"\n❌  Setup failed: {exc}")
            sys.exit(1)
        gen_cfg = cfg.get("generation", {})
        generator = Generator(
            model=gen_cfg.get("model") or None,
            temperature=gen_cfg.get("temperature", 0.2),
            max_tokens=gen_cfg.get("max_tokens", 512),
            top_p=gen_cfg.get("top_p", 0.9),
        )
        retriever.embedder._load_model()
        try:
            retry_empty(
                output_path=args.output,
                queries=queries,
                retriever=retriever,
                generator=generator,
            )
        finally:
            retriever.vector_store.close()
        return

    # ── Check for any LLM provider (unless dry-run) ───────────────────────
    nvidia_key   = os.getenv("NVIDIA_API_KEY", "").strip()
    groq_key     = os.getenv("GROQ_API_KEY",   "").strip()
    nvidia_ready = bool(nvidia_key and nvidia_key != "your_nvidia_api_key_here")
    groq_ready   = bool(groq_key)

    if not args.dry_run and not nvidia_ready and not groq_ready:
        print("\n❌  No LLM provider found. Options:")
        print("    1. Groq (free): sign up at console.groq.com, add GROQ_API_KEY to .env")
        print("    2. NVIDIA:      add NVIDIA_API_KEY to .env")
        print("    Or run with --dry-run to skip generation.")
        sys.exit(1)

    # ── Build components ──────────────────────────────────────────────────
    logger.info("Connecting to database and loading embedder...")
    try:
        retriever, _ = build_components(cfg, args.tier, args.top_k)
    except Exception as exc:
        print(f"\n❌  Setup failed: {exc}")
        print("    Is PostgreSQL running? Run: python scripts/setup_postgres.py")
        sys.exit(1)

    generator: Optional[Generator] = None
    if not args.dry_run:
        gen_cfg = cfg.get("generation", {})
        generator = Generator(
            model=gen_cfg.get("model") or None,  # None = auto-select per provider
            temperature=gen_cfg.get("temperature", 0.2),
            max_tokens=gen_cfg.get("max_tokens", 512),
            top_p=gen_cfg.get("top_p", 0.9),
        )

    # ── Run pipeline ──────────────────────────────────────────────────────
    mode = "dry-run (retrieval only)" if args.dry_run else "full RAG"

    # MUST pre-load model on main thread before spawning workers — SentenceTransformer
    # is not thread-safe during initialization (meta tensor issue)
    logger.info("Pre-loading embedding model on main thread...")
    retriever.embedder._load_model()
    logger.info("Embedding model ready.")

    logger.info("Starting %s | %d queries → %s", mode, len(queries), args.output)

    t0 = time.time()
    try:
        run(
            queries=queries,
            retriever=retriever,
            generator=generator,
            output_path=args.output,
            resume=args.resume,
            dry_run=args.dry_run,
            workers=args.workers,
        )
    finally:
        retriever.vector_store.close()

    elapsed = time.time() - t0
    logger.info("Total time: %.1fs", elapsed)


if __name__ == "__main__":
    main()
