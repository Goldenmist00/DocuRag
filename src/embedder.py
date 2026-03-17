"""
embedder.py
===========
Phase 3 — Embedding Generation with Tiered Model Selection

Responsibilities:
  1. Load sentence-transformer models based on user-selected tier
  2. Generate embeddings for text chunks with batch processing
  3. Cache embeddings using content hashing for efficiency
  4. Track progress and performance metrics
  5. Support GPU acceleration when available

Three Tiers:
  - Fast Mode: all-MiniLM-L6-v2 (384 dim, 80MB, ~2 min for 4000 chunks)
  - Balanced Mode: BAAI/bge-base-en-v1.5 (768 dim, 438MB, ~6 min) [DEFAULT]
  - Deep Mode: BAAI/bge-large-en-v1.5 (1024 dim, 1.34GB, ~15 min)
"""

import hashlib
import logging
import time
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from enum import Enum

import numpy as np
import torch
from sentence_transformers import SentenceTransformer
from tqdm import tqdm

from src.pdf_processor import Chunk

logger = logging.getLogger(__name__)


class EmbeddingTier(str, Enum):
    """Embedding model tiers with different speed/quality tradeoffs."""
    FAST = "fast"
    BALANCED = "balanced"
    DEEP = "deep"


# Model configurations
TIER_CONFIGS = {
    EmbeddingTier.FAST: {
        "model_name": "all-MiniLM-L6-v2",
        "dimensions": 384,
        "size_mb": 80,
        "description": "Fast mode - Quick answers, good for exploration",
        "est_time_4k_chunks": "~2 minutes (CPU)"
    },
    EmbeddingTier.BALANCED: {
        "model_name": "BAAI/bge-base-en-v1.5",
        "dimensions": 768,
        "size_mb": 438,
        "description": "Balanced mode - Best speed/quality tradeoff (DEFAULT)",
        "est_time_4k_chunks": "~6 minutes (CPU)"
    },
    EmbeddingTier.DEEP: {
        "model_name": "BAAI/bge-large-en-v1.5",
        "dimensions": 1024,
        "size_mb": 1340,
        "description": "Deep mode - Maximum precision, thorough answers",
        "est_time_4k_chunks": "~15 minutes (CPU)"
    }
}


class Embedder:
    """
    Sentence embedding generator with tiered model selection.
    
    Features:
    - Three quality tiers (fast/balanced/deep)
    - Batch processing for efficiency
    - Content-based caching
    - GPU acceleration support
    - Progress tracking
    - Performance metrics
    """
    
    def __init__(
        self,
        tier: EmbeddingTier = EmbeddingTier.BALANCED,
        cache_dir: str = "embeddings/cache",
        batch_size: int = 32,
        device: Optional[str] = None
    ):
        """
        Initialize embedder with specified tier.
        
        Args:
            tier: Model tier (fast/balanced/deep)
            cache_dir: Directory for caching embeddings
            batch_size: Number of texts to process per batch
            device: Device to use ('cuda', 'cpu', or None for auto-detect)
        """
        self.tier = tier
        self.config = TIER_CONFIGS[tier]
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.batch_size = batch_size
        
        # Auto-detect device
        if device is None:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = device
        
        # Model will be loaded lazily
        self.model: Optional[SentenceTransformer] = None
        self._model_loaded = False
        
        logger.info(f"Embedder initialized with tier: {tier.value}")
        logger.info(f"Model: {self.config['model_name']} ({self.config['dimensions']} dim)")
        logger.info(f"Device: {self.device}")
    
    def _load_model(self) -> None:
        """
        Load the sentence-transformer model (lazy loading).
        
        Raises:
            RuntimeError: If model loading fails
        """
        if self._model_loaded:
            return
        
        try:
            logger.info("=" * 70)
            logger.info(f"Loading {self.tier.value} mode model...")
            logger.info(f"Model: {self.config['model_name']}")
            logger.info(f"Size: {self.config['size_mb']}MB")
            logger.info(f"Dimensions: {self.config['dimensions']}")
            logger.info("=" * 70)
            
            start_time = time.time()
            
            # Load model
            self.model = SentenceTransformer(
                self.config['model_name'],
                device=self.device
            )
            
            # Set to evaluation mode
            self.model.eval()
            
            elapsed = time.time() - start_time
            logger.info(f"✓ Model loaded in {elapsed:.2f}s")
            
            # Show device info
            if self.device == "cuda":
                gpu_name = torch.cuda.get_device_name(0)
                logger.info(f"✓ Using GPU: {gpu_name}")
            else:
                logger.info("✓ Using CPU (consider GPU for faster processing)")
            
            self._model_loaded = True
            
        except Exception as e:
            raise RuntimeError(f"Failed to load model {self.config['model_name']}: {e}") from e
    
    def _get_cache_path(self, text: str) -> Path:
        """
        Get cache file path for a text using content hash.
        
        Args:
            text: Input text
            
        Returns:
            Path to cache file
        """
        content_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()
        return self.cache_dir / f"{content_hash}.npy"
    
    def _load_from_cache(self, text: str) -> Optional[np.ndarray]:
        """
        Load embedding from cache if available.
        
        Args:
            text: Input text
            
        Returns:
            Cached embedding or None if not found
        """
        cache_path = self._get_cache_path(text)
        if cache_path.exists():
            try:
                return np.load(cache_path)
            except Exception as e:
                logger.warning(f"Failed to load cache {cache_path}: {e}")
                return None
        return None
    
    def _save_to_cache(self, text: str, embedding: np.ndarray) -> None:
        """
        Save embedding to cache.
        
        Args:
            text: Input text
            embedding: Generated embedding
        """
        try:
            cache_path = self._get_cache_path(text)
            np.save(cache_path, embedding)
        except Exception as e:
            logger.warning(f"Failed to save cache: {e}")
    
    def embed_text(self, text: str, use_cache: bool = True) -> np.ndarray:
        """
        Generate embedding for a single text.
        
        Args:
            text: Input text
            use_cache: Whether to use caching
            
        Returns:
            Embedding vector of shape (dimensions,)
        """
        # Check cache first
        if use_cache:
            cached = self._load_from_cache(text)
            if cached is not None:
                return cached
        
        # Load model if needed
        self._load_model()
        
        # Generate embedding
        embedding = self.model.encode(
            text,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False
        )
        
        # Save to cache
        if use_cache:
            self._save_to_cache(text, embedding)
        
        return embedding
    
    def embed_chunks(
        self,
        chunks: List[Chunk],
        use_cache: bool = True,
        show_progress: bool = True
    ) -> Tuple[np.ndarray, Dict]:
        """
        Generate embeddings for multiple chunks with batch processing.
        
        Args:
            chunks: List of Chunk objects
            use_cache: Whether to use caching
            show_progress: Whether to show progress bar
            
        Returns:
            Tuple of (embeddings array, statistics dict)
            
        Raises:
            RuntimeError: If embedding generation fails
        """
        if not chunks:
            logger.warning("No chunks provided for embedding")
            return np.array([]), {"total": 0, "cached": 0, "computed": 0}
        
        logger.info("=" * 70)
        logger.info(f"Generating embeddings for {len(chunks)} chunks")
        logger.info(f"Tier: {self.tier.value} ({self.config['dimensions']} dimensions)")
        logger.info("=" * 70)
        
        start_time = time.time()
        
        # Load model
        self._load_model()
        
        # Check cache
        embeddings_list = []
        texts_to_compute = []
        indices_to_compute = []
        cached_count = 0
        
        logger.info("Checking cache...")
        for i, chunk in enumerate(chunks):
            if use_cache:
                cached = self._load_from_cache(chunk.text)
                if cached is not None:
                    embeddings_list.append(cached)
                    cached_count += 1
                    continue
            
            # Need to compute
            embeddings_list.append(None)  # Placeholder
            texts_to_compute.append(chunk.text)
            indices_to_compute.append(i)
        
        logger.info(f"✓ Found {cached_count} cached embeddings")
        logger.info(f"✓ Need to compute {len(texts_to_compute)} new embeddings")
        
        # Compute new embeddings in batches
        if texts_to_compute:
            try:
                logger.info(f"Computing embeddings (batch_size={self.batch_size})...")
                
                # Process in batches with progress bar
                computed_embeddings = []
                iterator = range(0, len(texts_to_compute), self.batch_size)
                
                if show_progress:
                    iterator = tqdm(
                        iterator,
                        desc="Embedding",
                        unit="batch",
                        total=(len(texts_to_compute) + self.batch_size - 1) // self.batch_size
                    )
                
                for i in iterator:
                    batch_texts = texts_to_compute[i:i + self.batch_size]
                    
                    # Generate embeddings for batch
                    batch_embeddings = self.model.encode(
                        batch_texts,
                        convert_to_numpy=True,
                        normalize_embeddings=True,
                        show_progress_bar=False,
                        batch_size=self.batch_size
                    )
                    
                    computed_embeddings.append(batch_embeddings)
                
                # Concatenate all batches
                computed_embeddings = np.vstack(computed_embeddings)
                
                # Insert computed embeddings into result list
                for idx, embedding in zip(indices_to_compute, computed_embeddings):
                    embeddings_list[idx] = embedding
                    
                    # Save to cache
                    if use_cache:
                        self._save_to_cache(chunks[idx].text, embedding)
                
            except Exception as e:
                raise RuntimeError(f"Failed to generate embeddings: {e}") from e
        
        # Convert to numpy array
        embeddings = np.vstack(embeddings_list)
        
        # Calculate statistics
        elapsed = time.time() - start_time
        chunks_per_sec = len(chunks) / elapsed if elapsed > 0 else 0
        
        stats = {
            "total_chunks": len(chunks),
            "cached": cached_count,
            "computed": len(texts_to_compute),
            "dimensions": self.config['dimensions'],
            "elapsed_seconds": round(elapsed, 2),
            "chunks_per_second": round(chunks_per_sec, 1),
            "tier": self.tier.value,
            "model": self.config['model_name'],
            "device": self.device
        }
        
        logger.info("=" * 70)
        logger.info("✓ Embedding generation complete!")
        logger.info(f"  Total: {stats['total_chunks']} chunks")
        logger.info(f"  Cached: {stats['cached']} | Computed: {stats['computed']}")
        logger.info(f"  Time: {stats['elapsed_seconds']}s ({stats['chunks_per_second']} chunks/s)")
        logger.info(f"  Shape: {embeddings.shape}")
        logger.info("=" * 70)
        
        return embeddings, stats
    
    def get_embedding_dimension(self) -> int:
        """
        Get the embedding dimension for the current tier.
        
        Returns:
            Embedding dimension
        """
        return self.config['dimensions']
    
    @staticmethod
    def list_tiers() -> Dict[str, Dict]:
        """
        List all available embedding tiers with their configurations.
        
        Returns:
            Dictionary of tier configurations
        """
        return TIER_CONFIGS
    
    @staticmethod
    def print_tier_info() -> None:
        """Print information about all available tiers."""
        print("=" * 70)
        print("EMBEDDING TIERS")
        print("=" * 70)
        
        for tier, config in TIER_CONFIGS.items():
            print(f"\n{tier.value.upper()} MODE:")
            print(f"  Model: {config['model_name']}")
            print(f"  Dimensions: {config['dimensions']}")
            print(f"  Size: {config['size_mb']}MB")
            print(f"  Description: {config['description']}")
            print(f"  Est. time (4000 chunks): {config['est_time_4k_chunks']}")
        
        print("\n" + "=" * 70)
        print("Recommendation: Use 'balanced' for most cases")
        print("=" * 70)


def create_embedder(tier: str = "balanced", **kwargs) -> Embedder:
    """
    Factory function to create an Embedder instance.
    
    Args:
        tier: Tier name ('fast', 'balanced', or 'deep')
        **kwargs: Additional arguments for Embedder
        
    Returns:
        Embedder instance
        
    Raises:
        ValueError: If tier is invalid
    """
    try:
        tier_enum = EmbeddingTier(tier.lower())
        return Embedder(tier=tier_enum, **kwargs)
    except ValueError:
        valid_tiers = [t.value for t in EmbeddingTier]
        raise ValueError(f"Invalid tier '{tier}'. Choose from: {valid_tiers}")
