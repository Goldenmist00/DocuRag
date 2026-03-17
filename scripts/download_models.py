#!/usr/bin/env python3
"""
Pre-download all embedding models to avoid delays during demo/deployment.
Run this BEFORE your hackathon presentation!
"""
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sentence_transformers import SentenceTransformer
from tqdm import tqdm


def download_model(model_name: str, description: str):
    """Download a single model with progress."""
    print(f"\n{'='*70}")
    print(f"Downloading: {description}")
    print(f"Model: {model_name}")
    print(f"{'='*70}")
    
    try:
        model = SentenceTransformer(model_name)
        print(f"✓ Successfully downloaded {model_name}")
        print(f"  Embedding dimension: {model.get_sentence_embedding_dimension()}")
        return True
    except Exception as e:
        print(f"✗ Failed to download {model_name}: {e}")
        return False


def main():
    """Download all models used in the project."""
    print("="*70)
    print("MODEL DOWNLOAD UTILITY")
    print("Pre-downloading all models for offline use")
    print("="*70)
    
    models = [
        ("sentence-transformers/all-MiniLM-L6-v2", "Fast Tier (80MB)"),
        ("BAAI/bge-base-en-v1.5", "Balanced Tier (438MB)"),
        ("BAAI/bge-large-en-v1.5", "Deep Tier (1.34GB)"),
        ("cross-encoder/ms-marco-MiniLM-L-6-v2", "Cross-Encoder for Reranking (80MB)")
    ]
    
    results = []
    total_size = "~1.93GB"
    
    print(f"\nTotal download size: {total_size}")
    print(f"Models to download: {len(models)}")
    print("\nThis may take 5-15 minutes depending on your internet speed...")
    
    input("\nPress Enter to start downloading...")
    
    for model_name, description in models:
        success = download_model(model_name, description)
        results.append((model_name, success))
    
    # Summary
    print("\n" + "="*70)
    print("DOWNLOAD SUMMARY")
    print("="*70)
    
    successful = sum(1 for _, success in results if success)
    failed = len(results) - successful
    
    for model_name, success in results:
        status = "✓" if success else "✗"
        print(f"{status} {model_name}")
    
    print(f"\nSuccessful: {successful}/{len(results)}")
    
    if failed > 0:
        print(f"Failed: {failed}/{len(results)}")
        print("\n⚠️  Some models failed to download. Check your internet connection.")
        sys.exit(1)
    else:
        print("\n✓ All models downloaded successfully!")
        print("✓ Ready for offline deployment!")
        print("\nYou can now run the pipeline without internet access.")


if __name__ == "__main__":
    main()
