#!/usr/bin/env python3
"""
Pre-Demo Test Script
Run this before your hackathon presentation to verify everything works.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_imports():
    """Test all critical imports."""
    print("\n" + "="*70)
    print("TEST 1: Checking imports...")
    print("="*70)

    try:
        from src.embedder import Embedder, EmbeddingTier
        from src.vector_store import PgVectorStore
        from src.pdf_processor import load_chunks
        print("✓ All imports successful")
        return True
    except Exception as e:
        print(f"✗ Import failed: {e}")
        return False


def test_embedder():
    """Test NVIDIA API embedder."""
    print("\n" + "="*70)
    print("TEST 2: Checking NVIDIA embedder...")
    print("="*70)

    try:
        from src.embedder import Embedder

        embedder = Embedder()
        test_text = "This is a test sentence."
        embedding = embedder.embed(test_text)

        print(f"✓ Embedder working ({embedder.embedding_dim}d)")
        print(f"  Model: {embedder.model_name}")
        print(f"  Mode: API-based")
        return True
    except Exception as e:
        print(f"✗ Embedder test failed: {e}")
        print("\n  Check NVIDIA_EMBED_API_KEY or NVIDIA_API_KEY in .env")
        return False


def test_database():
    """Test database connection."""
    print("\n" + "="*70)
    print("TEST 3: Checking database...")
    print("="*70)

    try:
        from src.embedder import Embedder
        from src.vector_store import PgVectorStore

        embedder = Embedder()
        vs = PgVectorStore(embedding_dim=embedder.embedding_dim)
        stats = vs.get_stats()
        vs.close()

        print(f"✓ Database connected")
        print(f"  Total chunks: {stats['total_chunks']}")
        print(f"  Unique pages: {stats['unique_pages']}")

        if stats['total_chunks'] == 0:
            print("\n  No data in database!")
            print("  Run: python scripts/embed_and_store.py --clear --create-index")
            return False

        return True
    except Exception as e:
        print(f"✗ Database test failed: {e}")
        print("\n  Check PostgreSQL connection and POSTGRES_* vars in .env")
        return False


def test_search():
    """Test vector search."""
    print("\n" + "="*70)
    print("TEST 4: Testing search...")
    print("="*70)

    try:
        from src.embedder import Embedder
        from src.vector_store import PgVectorStore

        embedder = Embedder()
        vs = PgVectorStore(embedding_dim=embedder.embedding_dim)

        query = "What is memory?"
        print(f"  Query: {query}")

        start = time.time()
        query_embedding = embedder.embed(query)
        results = vs.search(query_embedding, top_k=3)
        elapsed = time.time() - start

        vs.close()

        print(f"✓ Search working")
        print(f"  Response time: {elapsed*1000:.0f}ms")
        print(f"  Results: {len(results)}")

        if elapsed > 2.0:
            print("\n  Search is slow (>2 seconds)")

        return True
    except Exception as e:
        print(f"✗ Search test failed: {e}")
        return False


def main():
    """Run all pre-demo tests."""
    print("="*70)
    print("PRE-DEMO TEST SUITE")
    print("="*70)

    tests = [
        ("Imports", test_imports),
        ("Embedder", test_embedder),
        ("Database", test_database),
        ("Search", test_search),
    ]

    results = []
    for name, test_func in tests:
        try:
            success = test_func()
            results.append((name, success))
        except Exception as e:
            print(f"\n✗ {name} test crashed: {e}")
            results.append((name, False))

    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)

    passed = sum(1 for _, success in results if success)
    total = len(results)

    for name, success in results:
        status_icon = "✓" if success else "✗"
        print(f"{status_icon} {name}")

    print(f"\nPassed: {passed}/{total}")

    if passed == total:
        print("\n" + "="*70)
        print("ALL TESTS PASSED!")
        print("="*70)
        print("You're ready for the demo!")
        print("\nQuick demo command:")
        print("  uvicorn src.api:app --reload --port 8000")
    else:
        print("\n" + "="*70)
        print("SOME TESTS FAILED")
        print("="*70)
        print("Fix the issues above before your demo!")
        print("\nCommon fixes:")
        print("  1. Check NVIDIA_API_KEY / NVIDIA_EMBED_API_KEY in .env")
        print("  2. Start PostgreSQL or check POSTGRES_* vars in .env")
        print("  3. Setup database: python scripts/setup_postgres.py")
        print("  4. Load data: python scripts/embed_and_store.py --clear --create-index")
        sys.exit(1)


if __name__ == "__main__":
    main()
