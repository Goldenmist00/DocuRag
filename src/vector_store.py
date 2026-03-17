"""
vector_store.py
===============
PostgreSQL + pgvector Vector Store Implementation

Responsibilities:
  1. Connect to PostgreSQL database with pgvector extension
  2. Store document chunks with their embeddings
  3. Perform vector similarity search
  4. Manage indexes for optimal performance
  5. Connection pooling and retry logic for production reliability
"""

import logging
import time
from typing import List, Dict, Optional, Tuple
from contextlib import contextmanager

import numpy as np
import psycopg2
from psycopg2 import pool
from psycopg2.extras import execute_values
from pgvector.psycopg2 import register_vector

from src.pdf_processor import Chunk

logger = logging.getLogger(__name__)


class PgVectorStore:
    """
    PostgreSQL + pgvector vector store for RAG system.
    
    Features:
    - Connection pooling for better performance
    - Retry logic with exponential backoff
    - Comprehensive error handling
    - Performance metrics tracking
    """
    
    def __init__(
        self,
        host: str = "localhost",
        port: int = 5432,
        database: str = "rag_db",
        user: str = "postgres",
        password: str = "postgres",
        table_name: str = "document_chunks",
        min_connections: int = 1,
        max_connections: int = 10
    ):
        """
        Initialize vector store with connection pooling.
        
        Args:
            host: PostgreSQL host
            port: PostgreSQL port
            database: Database name
            user: Database user
            password: Database password
            table_name: Table name for storing chunks
            min_connections: Minimum connections in pool
            max_connections: Maximum connections in pool
        """
        self.connection_params = {
            "host": host,
            "port": port,
            "database": database,
            "user": user,
            "password": password
        }
        self.table_name = table_name
        
        # Initialize connection pool
        try:
            self.connection_pool = pool.ThreadedConnectionPool(
                min_connections,
                max_connections,
                **self.connection_params
            )
            logger.info(f"✓ Connection pool created ({min_connections}-{max_connections} connections)")
        except Exception as e:
            raise RuntimeError(f"Failed to create connection pool: {e}") from e
        
        self._test_connection()
    
    def _test_connection(self):
        """
        Test database connection and pgvector extension.
        
        Raises:
            RuntimeError: If connection or pgvector extension check fails
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
                    result = cur.fetchone()
                    if result:
                        logger.info(f"✓ Connected to PostgreSQL with pgvector {result[0]}")
                    else:
                        raise RuntimeError("pgvector extension not installed")
        except Exception as e:
            raise RuntimeError(f"Failed to connect to PostgreSQL: {e}") from e
    
    @contextmanager
    def _get_connection(self):
        """
        Context manager for database connections with retry logic.
        
        Yields:
            psycopg2 connection with pgvector registered
        """
        max_retries = 3
        retry_delay = 1  # seconds
        
        for attempt in range(max_retries):
            conn = None
            try:
                conn = self.connection_pool.getconn()
                register_vector(conn)  # Register pgvector types
                yield conn
                conn.commit()
                return
            except Exception as e:
                if conn:
                    conn.rollback()
                
                if attempt < max_retries - 1:
                    logger.warning(f"Connection attempt {attempt + 1} failed, retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    logger.error(f"All connection attempts failed: {e}")
                    raise
            finally:
                if conn:
                    self.connection_pool.putconn(conn)
    
    def insert_chunks(
        self,
        chunks: List[Chunk],
        embeddings: np.ndarray,
        batch_size: int = 100
    ) -> int:
        """
        Insert chunks with their embeddings into the database.
        
        Args:
            chunks: List of Chunk objects
            embeddings: numpy array of shape (n_chunks, embedding_dim)
            batch_size: Number of chunks to insert per batch
        
        Returns:
            Number of chunks inserted
            
        Raises:
            ValueError: If chunks and embeddings length mismatch
            RuntimeError: If insertion fails
        """
        if len(chunks) != len(embeddings):
            raise ValueError(f"Mismatch: {len(chunks)} chunks but {len(embeddings)} embeddings")
        
        logger.info(f"Inserting {len(chunks)} chunks into {self.table_name}")
        start_time = time.time()
        
        insert_query = f"""
            INSERT INTO {self.table_name} (
                chunk_id, text, embedding,
                section_id, chapter_id, section_title,
                page_start, page_end,
                chunk_index_in_section, char_count, word_count
            ) VALUES %s
            ON CONFLICT (chunk_id) DO UPDATE SET
                text = EXCLUDED.text,
                embedding = EXCLUDED.embedding,
                updated_at = CURRENT_TIMESTAMP
        """
        
        inserted = 0
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    for i in range(0, len(chunks), batch_size):
                        batch_chunks = chunks[i:i + batch_size]
                        batch_embeddings = embeddings[i:i + batch_size]
                        
                        values = [
                            (
                                chunk.chunk_id,
                                chunk.text,
                                batch_embeddings[j].tolist(),
                                chunk.section_id,
                                chunk.chapter_id,
                                chunk.section_title,
                                chunk.page_start,
                                chunk.page_end,
                                chunk.chunk_index_in_section,
                                chunk.char_count,
                                chunk.word_count
                            )
                            for j, chunk in enumerate(batch_chunks)
                        ]
                        
                        execute_values(cur, insert_query, values)
                        inserted += len(batch_chunks)
                        
                        if (i + batch_size) % 500 == 0:
                            logger.info(f"Progress: {inserted}/{len(chunks)} chunks")
            
            elapsed = time.time() - start_time
            logger.info(f"✓ Inserted {inserted} chunks in {elapsed:.2f}s ({inserted/elapsed:.1f} chunks/s)")
            return inserted
            
        except Exception as e:
            logger.error(f"Insertion failed after {inserted} chunks: {e}")
            raise RuntimeError(f"Failed to insert chunks: {e}") from e
    
    def create_index(self, index_type: str = "ivfflat", lists: int = 100):
        """
        Create vector similarity index.
        
        Args:
            index_type: "ivfflat" or "hnsw"
            lists: Number of lists for IVFFlat (ignored for HNSW)
        """
        logger.info(f"Creating {index_type} index on embeddings...")
        
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                # Drop existing index if any
                cur.execute(f"DROP INDEX IF EXISTS idx_embedding_{index_type}")
                
                if index_type == "ivfflat":
                    # IVFFlat: faster build, good for most use cases
                    cur.execute(f"""
                        CREATE INDEX idx_embedding_ivfflat 
                        ON {self.table_name} 
                        USING ivfflat (embedding vector_cosine_ops) 
                        WITH (lists = {lists})
                    """)
                elif index_type == "hnsw":
                    # HNSW: slower build, better query performance
                    cur.execute(f"""
                        CREATE INDEX idx_embedding_hnsw 
                        ON {self.table_name} 
                        USING hnsw (embedding vector_cosine_ops)
                    """)
                else:
                    raise ValueError(f"Unknown index type: {index_type}")
        
        logger.info(f"✓ Created {index_type} index")
    
    def search(
        self,
        query_embedding: np.ndarray,
        top_k: int = 5,
        probes: Optional[int] = None
    ) -> List[Dict]:
        """
        Search for similar chunks using cosine similarity.
        
        Args:
            query_embedding: Query vector of shape (embedding_dim,)
            top_k: Number of results to return
            probes: Number of probes for IVFFlat (None = default)
        
        Returns:
            List of dicts with chunk data and similarity scores
            
        Raises:
            RuntimeError: If search fails
        """
        try:
            start_time = time.time()
            query_vector = query_embedding.tolist()
            
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    # Set probes for IVFFlat if specified
                    if probes is not None:
                        cur.execute(f"SET ivfflat.probes = {probes}")
                    
                    # Cosine similarity search (1 - cosine_distance)
                    cur.execute(f"""
                        SELECT 
                            chunk_id, text, 
                            section_id, chapter_id, section_title,
                            page_start, page_end,
                            chunk_index_in_section, char_count, word_count,
                            1 - (embedding <=> %s::vector) AS similarity
                        FROM {self.table_name}
                        ORDER BY embedding <=> %s::vector
                        LIMIT %s
                    """, (query_vector, query_vector, top_k))
                    
                    results = []
                    for row in cur.fetchall():
                        results.append({
                            "chunk_id": row[0],
                            "text": row[1],
                            "section_id": row[2],
                            "chapter_id": row[3],
                            "section_title": row[4],
                            "page_start": row[5],
                            "page_end": row[6],
                            "chunk_index_in_section": row[7],
                            "char_count": row[8],
                            "word_count": row[9],
                            "similarity": float(row[10])
                        })
                    
                    elapsed = time.time() - start_time
                    logger.info(f"✓ Search completed in {elapsed*1000:.1f}ms, found {len(results)} results")
                    return results
                    
        except Exception as e:
            logger.error(f"Search failed: {e}")
            raise RuntimeError(f"Vector search failed: {e}") from e
    
    def get_stats(self) -> Dict:
        """
        Get database statistics.
        
        Returns:
            Dictionary with chunk counts and metadata
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(f"SELECT COUNT(*) FROM {self.table_name}")
                    total_chunks = cur.fetchone()[0]
                    
                    cur.execute(f"""
                        SELECT COUNT(DISTINCT section_id) FROM {self.table_name}
                    """)
                    unique_sections = cur.fetchone()[0]
                    
                    cur.execute(f"""
                        SELECT COUNT(DISTINCT chapter_id) FROM {self.table_name}
                    """)
                    unique_chapters = cur.fetchone()[0]
                    
                    return {
                        "total_chunks": total_chunks,
                        "unique_sections": unique_sections,
                        "unique_chapters": unique_chapters
                    }
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {
                "total_chunks": 0,
                "unique_sections": 0,
                "unique_chapters": 0,
                "error": str(e)
            }
    
    def clear(self):
        """
        Clear all data from the table.
        
        Warning: This operation cannot be undone!
        """
        logger.warning(f"Clearing all data from {self.table_name}")
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(f"TRUNCATE TABLE {self.table_name} RESTART IDENTITY")
            logger.info("✓ Table cleared")
        except Exception as e:
            logger.error(f"Failed to clear table: {e}")
            raise RuntimeError(f"Table clear failed: {e}") from e
    
    def close(self):
        """Close all connections in the pool."""
        if hasattr(self, 'connection_pool'):
            self.connection_pool.closeall()
            logger.info("✓ Connection pool closed")
