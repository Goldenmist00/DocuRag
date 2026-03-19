-- Initialize PostgreSQL database with pgvector extension
-- This script runs automatically when the Docker container starts

-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Create table for document chunks with vector embeddings
CREATE TABLE IF NOT EXISTS document_chunks (
    id SERIAL PRIMARY KEY,
    chunk_id VARCHAR(32) UNIQUE NOT NULL,
    text TEXT NOT NULL,
    embedding vector(768),  -- 768 dimensions for balanced tier (BAAI/bge-base-en-v1.5)
    
    -- Metadata for citations
    section_id VARCHAR(50),
    chapter_id VARCHAR(50),
    section_title TEXT,
    page_num INTEGER,
    
    -- Additional metadata
    chunk_index INTEGER,
    char_count INTEGER,
    word_count INTEGER,
    
    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create index on chunk_id for fast lookups
CREATE INDEX IF NOT EXISTS idx_chunk_id ON document_chunks(chunk_id);

-- Create index on section_id for filtering
CREATE INDEX IF NOT EXISTS idx_section_id ON document_chunks(section_id);

-- Create index on chapter_id for filtering
CREATE INDEX IF NOT EXISTS idx_chapter_id ON document_chunks(chapter_id);

-- Create IVFFlat index for vector similarity search
-- Note: This will be created after data is inserted (needs training data)
-- CREATE INDEX IF NOT EXISTS idx_embedding_ivfflat ON document_chunks 
-- USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- Alternative: HNSW index (better performance, more memory)
-- CREATE INDEX IF NOT EXISTS idx_embedding_hnsw ON document_chunks 
-- USING hnsw (embedding vector_cosine_ops);

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Trigger to automatically update updated_at
CREATE TRIGGER update_document_chunks_updated_at 
    BEFORE UPDATE ON document_chunks 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();
