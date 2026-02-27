# Environment Setup Guide

Complete step-by-step instructions for setting up the RAG system from scratch.

## 1. Python Environment Setup

### Option A: Using venv (Recommended)

```bash
# Check Python version (3.10 or 3.11 recommended)
python --version

# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows (cmd):
venv\Scripts\activate.bat
# Windows (PowerShell):
venv\Scripts\Activate.ps1
# Linux/Mac:
source venv/bin/activate

# Upgrade pip
python -m pip install --upgrade pip
```

### Option B: Using conda

```bash
# Create conda environment
conda create -n rag-qa python=3.11

# Activate environment
conda activate rag-qa

# Upgrade pip
pip install --upgrade pip
```

## 2. Install Dependencies

```bash
# Install core dependencies
pip install -r requirements.txt

# (Optional) Install development dependencies
pip install -r requirements-dev.txt

# Verify installation
pip list
```

### Key Libraries Explained

- **PyPDF2/pdfplumber/pymupdf**: PDF text extraction (multiple options for robustness)
- **sentence-transformers**: Local embedding model (no API needed)
- **torch**: Required for sentence-transformers
- **faiss-cpu**: Fast vector similarity search
- **openai**: Used for NVIDIA API (compatible interface)
- **pandas**: Data manipulation and CSV output
- **jsonlines**: Efficient storage of processed chunks

## 3. Initialize Project Structure

```bash
# Create all necessary directories
python scripts/setup_data.py
```

This creates:
```
data/raw/              # Place PDF here
data/processed/        # Chunked text storage
embeddings/cache/      # Embedding cache
vector_store/          # FAISS index
models/                # Downloaded models
outputs/               # Final submission.csv
logs/                  # Application logs
```

## 4. Download Models

```bash
# Pre-download embedding model (recommended)
python scripts/download_models.py

# This downloads ~80MB model to models/ directory
# Subsequent runs will use cached model
```

## 5. Configuration

```bash
# Copy environment template
copy .env.example .env  # Windows
cp .env.example .env    # Linux/Mac

# Edit .env and add your NVIDIA API key
# Get free API key from: https://build.nvidia.com/
```

Required `.env` variables:
```
NVIDIA_API_KEY=nvapi-xxxxxxxxxxxxx
```

Optional configuration in `config.yaml`:
- Chunk size and overlap
- Embedding model selection
- Retrieval parameters
- Generation settings

## 6. Prepare Data

```bash
# Place your files:
# 1. OpenStax Psychology 2e PDF → data/raw/openstax_psychology_2e.pdf
# 2. queries.json → data/queries.json
```

Expected `queries.json` format:
```json
[
  {
    "query_id": "q001",
    "question": "What is classical conditioning?"
  }
]
```

## 7. Verify Setup

```bash
# Run setup verification
python -c "
import torch
import sentence_transformers
import faiss
import PyPDF2
print('✓ All core dependencies imported successfully')
"
```

## 8. First Run

```bash
# Run complete pipeline
python scripts/run_pipeline.py --all

# Or run step-by-step:
python scripts/run_pipeline.py --step extract
python scripts/run_pipeline.py --step embed
python scripts/run_pipeline.py --step index
python scripts/run_pipeline.py --step generate
```

## Docker Setup (Alternative)

If you prefer containerized deployment:

```bash
# Build Docker image
docker-compose build

# Run pipeline
docker-compose run rag-app python scripts/run_pipeline.py --all

# Access container shell
docker-compose run rag-app bash
```

## Troubleshooting

### Issue: FAISS installation fails

**Solution**: Try installing with conda:
```bash
conda install -c conda-forge faiss-cpu
```

### Issue: PyTorch too large

**Solution**: Install CPU-only version:
```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

### Issue: PDF extraction errors

**Solution**: Try different PDF library:
```python
# In your code, switch from PyPDF2 to pdfplumber or pymupdf
```

### Issue: Out of memory during embedding

**Solution**: Reduce batch size in `.env`:
```
BATCH_SIZE=8
```

### Issue: NVIDIA API errors

**Solution**: 
- Verify API key is correct
- Check rate limits (free tier has limits)
- Ensure proper API endpoint in `.env`

## Best Practices

1. **Version Control**: Commit `requirements.txt` but not `venv/` or cached data
2. **Caching**: Keep embeddings and FAISS index cached to avoid recomputation
3. **Reproducibility**: Use fixed random seeds in `config.yaml`
4. **Testing**: Run on small subset first before full pipeline
5. **Monitoring**: Check `logs/rag_system.log` for issues

## Performance Optimization

- Use GPU if available (change `device: "cuda"` in config.yaml)
- Increase batch size for faster embedding generation
- Use FAISS GPU version for large-scale retrieval
- Consider quantization for embedding model

## Next Steps

After setup is complete:
1. Implement PDF processing logic in `src/pdf_processor.py`
2. Implement embedding generation in `src/embedder.py`
3. Implement FAISS operations in `src/vector_store.py`
4. Implement retrieval in `src/retriever.py`
5. Implement generation in `src/generator.py`
6. Wire everything together in `scripts/run_pipeline.py`
