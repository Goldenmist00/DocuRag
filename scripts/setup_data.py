#!/usr/bin/env python3
"""
Initialize project directory structure.
"""
import os


def setup_directories():
    """Create all necessary directories."""
    directories = [
        "data/raw",
        "data/processed",
        "embeddings/cache",
        "models",
        "outputs",
        "logs",
        "src",
        "scripts",
        "tests"
    ]

    for directory in directories:
        os.makedirs(directory, exist_ok=True)
        print(f"✓ Created: {directory}")

    init_file = "src/__init__.py"
    if not os.path.exists(init_file):
        with open(init_file, "w") as f:
            f.write('"""RAG System for Textbook Q&A"""\n')
        print(f"✓ Created: {init_file}")

    print("\n✓ Project structure initialized successfully!")
    print("\nNext steps:")
    print("1. Place OpenStax Psychology 2e PDF in data/raw/")
    print("2. Place queries.json in data/")
    print("3. Copy .env.example to .env and add your NVIDIA API key")
    print("4. Run: python scripts/run_pipeline.py --all")


if __name__ == "__main__":
    setup_directories()
