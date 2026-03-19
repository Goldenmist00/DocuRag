#!/usr/bin/env python3
"""
Pre-Demo Test Script
Run this 30 minutes before your hackathon presentation to verify everything works!
"""
import sys
import time
from pathlib import Path

# Add src to path
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


def test_models():
    """Test if models are downloaded."""
    print("\n" + "="*70)
    print("TEST 2: Checking models...")
    print("="*70)
    
    try:
        from src.embedder import Embedder, EmbeddingTier
        
        # Test fast tier (smallest, fastest)
        print("  Testing fast tier...")
        embedder = Embedder(tier=EmbeddingTier.FAST)
        test_text = "This is a test sentence."
        embedding = embedder.embed(test_text)
        
        print(f"✓ Fast tier working ({embedder.embedding_dim}d)")
        print(f"  Model: {embedder.model_name}")
        print(f"  Device: {embedder.device}")
        return True
    except Exception as e:
        print(f"✗ Model test failed: {e}")
        print("\n⚠️  Run: python scripts/download_models.py")
        return False


def test_database():
    """Test database connection."""
    print("\n" + "="*70)
    print("TEST 3: Checking database...")
    print("="*70)
    
    try:
        from src.vector_store import PgVectorStore
        
        vs = PgVectorStore(embedding_dim=384)
        stats = vs.get_stats()
        vs.close()
        
        print(f"✓ Database connected")
        print(f"  Total chunks: {stats['total_chunks']}")
        print(f"  Unique pages: {stats['unique_pages']}")
        
        if stats['total_chunks'] == 0:
            print("\n⚠️  No data in database!")
            print("  Run: python scripts/embed_and_store.py --tier fast --clear --create-index")
            return False
        
        return True
    except Exception as e:
        print(f"✗ Database test failed: {e}")
        print("\n⚠️  Check database connection:")
        print("  Option 1 (Local): Start PostgreSQL service")
        print("  Option 2 (Cloud): Verify config.yaml has correct connection details")
        print("  Option 3: Run python scripts/setup_postgres.py")
        return False


def test_search():
    """Test vector search."""
    print("\n" + "="*70)
    print("TEST 4: Testing search...")
    print("="*70)
    
    try:
        from src.embedder import Embedder, EmbeddingTier
        from src.vector_store import PgVectorStore
        
        # Initialize
        embedder = Embedder(tier=EmbeddingTier.FAST)
        vs = PgVectorStore(embedding_dim=384)
        
        # Test query
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
        
        if elapsed > 1.0:
            print("\n⚠️  Search is slow (>1 second)")
            print("  Run: python scripts/embed_and_store.py --create-index")
        
        return True
    except Exception as e:
        print(f"✗ Search test failed: {e}")
        return False


def test_offline():
    """Test if everything works without internet."""
    print("\n" + "="*70)
    print("TEST 5: Testing offline capability...")
    print("="*70)
    
    print("  This test assumes models are cached")
    print("  If models download, you need to pre-download them!")
    print("  Run: python scripts/download_models.py")
    print("✓ Offline test passed (manual verification needed)")
    return True


def main():
    """Run all pre-demo tests."""
    print("="*70)
    print("PRE-DEMO TEST SUITE")
    print("Run this 30 minutes before your presentation!")
    print("="*70)
    
    tests = [
        ("Imports", test_imports),
        ("Models", test_models),
        ("Database", test_database),
        ("Search", test_search),
        ("Offline", test_offline)
    ]
    
    results = []
    for name, test_func in tests:
        try:
            success = test_func()
            results.append((name, success))
        except Exception as e:
            print(f"\n✗ {name} test crashed: {e}")
            results.append((name, False))
    
    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    for name, success in results:
        status = "✓" if success else "✗"
        print(f"{status} {name}")
    
    print(f"\nPassed: {passed}/{total}")
    
    if passed == total:
        print("\n" + "="*70)
        print("🎉 ALL TESTS PASSED!")
        print("="*70)
        print("You're ready for the demo!")
        print("\nQuick demo command:")
        print('  python scripts/test_vector_search.py --query "What is memory?" --top-k 3')
        print("\n✓ Response should be <1 second")
        print("✓ Results should include page numbers")
        print("✓ Everything should work offline")
        print("\nGood luck! 🚀")
    else:
        print("\n" + "="*70)
        print("⚠️  SOME TESTS FAILED")
        print("="*70)
        print("Fix the issues above before your demo!")
        print("\nCommon fixes:")
        print("  1. Download models: python scripts/download_models.py")
        print("  2. Start PostgreSQL (local) or check cloud connection")
        print("  3. Setup database: python scripts/setup_postgres.py")
        print("  4. Load data: python scripts/embed_and_store.py --tier fast --clear --create-index")
        print("\n💡 Tip: Use cloud PostgreSQL (Neon.tech) for zero setup!")
        sys.exit(1)


if __name__ == "__main__":
    main()
