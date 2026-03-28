-- Initialize PostgreSQL database with pgvector extension
-- This script runs automatically when the Docker container starts

-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- ─── Notebooks ───
CREATE TABLE IF NOT EXISTS notebooks (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title                 TEXT NOT NULL DEFAULT 'Untitled notebook',
    conversation_history  JSONB DEFAULT '[]',
    created_at            TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at            TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- ─── Sources (per notebook) ───
CREATE TABLE IF NOT EXISTS sources (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    notebook_id   UUID NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    source_type   TEXT NOT NULL DEFAULT 'file',
    file_path     TEXT,
    raw_content   TEXT,
    status        TEXT NOT NULL DEFAULT 'pending',
    error_message TEXT,
    chunk_count   INTEGER DEFAULT 0,
    created_at    TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_sources_notebook ON sources(notebook_id);

-- ─── Document chunks with vector embeddings ───
CREATE TABLE IF NOT EXISTS document_chunks (
    id SERIAL PRIMARY KEY,
    chunk_id TEXT UNIQUE NOT NULL,
    text TEXT NOT NULL,
    embedding halfvec(4096),

    -- Foreign keys for notebook scoping
    notebook_id UUID REFERENCES notebooks(id) ON DELETE CASCADE,
    source_id   UUID REFERENCES sources(id) ON DELETE CASCADE,

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

CREATE INDEX IF NOT EXISTS idx_chunk_id ON document_chunks(chunk_id);
CREATE INDEX IF NOT EXISTS idx_section_id ON document_chunks(section_id);
CREATE INDEX IF NOT EXISTS idx_chapter_id ON document_chunks(chapter_id);
CREATE INDEX IF NOT EXISTS idx_chunks_notebook ON document_chunks(notebook_id);
CREATE INDEX IF NOT EXISTS idx_chunks_source ON document_chunks(source_id);

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Triggers for updated_at
CREATE TRIGGER update_document_chunks_updated_at
    BEFORE UPDATE ON document_chunks
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_notebooks_updated_at
    BEFORE UPDATE ON notebooks
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_sources_updated_at
    BEFORE UPDATE ON sources
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
