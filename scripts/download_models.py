#!/usr/bin/env python3
"""
Pre-download embedding models to avoid runtime delays.
"""
import os
from sentence_transformers import SentenceTransformer

def download_models():
    """Download and cache embedding models."""
    model_name = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
    cache_dir = "./models"
    
    print(f"Downloading model: {model_name}")
    print(f"Cache directory: {cache_dir}")
    
    os.makedirs(cache_dir, exist_ok=True)
    
    # Download model
    model = SentenceTransformer(model_name, cache_folder=cache_dir)
    
    print(f"✓ Model downloaded successfully")
    print(f"  Embedding dimension: {model.get_sentence_embedding_dimension()}")

if __name__ == "__main__":
    download_models()
