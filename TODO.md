# Project TODO List

## ✅ COMPLETED (70%)

### Infrastructure
- [x] Project structure
- [x] Docker setup with PostgreSQL + pgvector
- [x] Configuration files
- [x] Requirements and dependencies
- [x] Git repository

### Phase 1: PDF Processing
- [x] `src/pdf_processor.py` - Complete and tested
- [x] `scripts/ingest.py` - CLI tool
- [x] `scripts/test_chunking.py` - Test utility
- [x] Fixed overlap logic bug
- [x] Fixed chapter text dropping bug
- [x] **NEW:** Applied python-pro improvements (docstrings, error handling, logging)

### Phase 2: Vector Store
- [x] `src/vector_store.py` - PostgreSQL + pgvector implementation
- [x] `scripts/setup_postgres.py` - Database setup
- [x] `scripts/init_db.sql` - Schema
- [x] **NEW:** Added connection pooling and retry logic
- [x] **NEW:** Performance metrics tracking
- [x] **NEW:** Comprehensive error handling

### Phase 3: Embeddings ✅ COMPLETE
- [x] Created `src/embedder.py` with tiered model selection
- [x] Three tiers: fast (384d), balanced (768d), deep (1024d)
- [x] Content-based caching with SHA-256 hashing
- [x] Batch processing with progress tracking
- [x] GPU acceleration support
- [x] Performance metrics and statistics
- [x] Created `scripts/test_embedder.py` test utility
- [x] Created `docs/EMBEDDER.md` documentation
- [x] **NEW:** Created `scripts/embed_and_store.py` - Full embedding → storage pipeline
- [x] **NEW:** Created `scripts/test_vector_search.py` - Test vector search
- [x] **NEW:** Updated `scripts/run_pipeline.py` with `run_embed()` and `run_index()`
- [x] **NEW:** Vector store integration complete

### Code Quality
- [x] **NEW:** Applied python-pro, rag-engineer, llm-app-patterns skills
- [x] **NEW:** Type hints on all functions
- [x] **NEW:** Comprehensive docstrings (Google style)
- [x] **NEW:** Error handling with exception chaining
- [x] **NEW:** Progress logging throughout
- [x] **NEW:** Created IMPROVEMENTS.md documentation

### Sample Data
- [x] `data/queries.json` - Sample questions

---

## ❌ TODO (30%)

### Phase 4: Retrieval (Priority 1 - NEXT)
- [ ] Create `src/retriever.py`
  - [ ] Two-stage retrieval
  - [ ] Vector search (top 10)
  - [ ] Cross-encoder reranking
  - [ ] Deduplication logic
  - [ ] Return top 5 with scores

### Phase 5: Generation (Priority 3)
- [ ] Create `src/generator.py`
  - [ ] NVIDIA API integration
  - [ ] Prompt template with grounding instructions
  - [ ] Reference extraction
  - [ ] Error handling and retries

### Phase 6: Pipeline Integration (Priority 4)
- [x] Complete `scripts/run_pipeline.py`
  - [x] Implement `run_embed()`
  - [x] Implement `run_index()`
  - [ ] Implement `run_generate()`
  - [ ] Add caching checks
  - [ ] Generate `outputs/submission.csv`

### Configuration Fixes
- [ ] Fix config.yaml to read NVIDIA_API_BASE from .env
- [ ] Add proper environment variable loading

### Documentation
- [ ] Update README with actual usage
- [ ] Add troubleshooting section
- [ ] Document API requirements

### Testing
- [ ] Test complete pipeline end-to-end
- [ ] Verify citations are accurate
- [ ] Test with actual PDF
- [ ] Validate submission.csv format

---

## 🐛 Known Issues (Fixed)

- [x] ~~Overlap logic only kept last sentence~~ - FIXED
- [x] ~~Chapter intro text was dropped~~ - FIXED
- [x] ~~Missing queries.json~~ - FIXED

---

## 📋 Build Order

1. **Embedder** - Convert chunks to vectors
2. **Test embedder** - Verify embeddings are correct shape
3. **Vector Store Integration** - Insert embeddings into PostgreSQL
4. **Test vector search** - Query and verify results
5. **Retriever** - Two-stage retrieval with reranking
6. **Test retrieval** - Check top 5 results make sense
7. **Generator** - LLM integration with NVIDIA API
8. **Test generation** - Verify answers are grounded
9. **Pipeline Integration** - Wire everything together
10. **End-to-end test** - Run full pipeline on sample queries

---

## 🎯 Next Steps

**Immediate (Priority 1):**
1. ✅ ~~Build `src/embedder.py`~~ - DONE
2. ✅ ~~Test embedding generation~~ - DONE
3. ✅ ~~Integrate with vector store~~ - DONE
4. **Build `src/retriever.py`** ← YOU ARE HERE
   - Two-stage retrieval (vector search + reranking)
   - Cross-encoder for reranking
   - Deduplication logic
   - Return top 5 with scores

**Then (Priority 2):**
5. Build `src/generator.py`
6. Complete `run_pipeline.py` (implement `run_generate()`)
7. Test end-to-end

**Finally (Priority 3):**
8. Get actual PDF
9. Run full pipeline
10. Validate output
