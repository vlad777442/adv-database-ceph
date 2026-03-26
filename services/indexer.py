"""
Indexing service for scanning and indexing RADOS objects.

This module handles the process of scanning a Ceph pool, extracting content,
generating embeddings, and storing them in the vector database.
"""

import logging
from typing import List, Optional, Dict
from datetime import datetime
from tqdm import tqdm
import time

from core.rados_client import RadosClient
from core.embedding_generator import EmbeddingGenerator
from core.content_processor import ContentProcessor
from core.rados_vector_store import RadosVectorStore
from core.metadata_schema import ObjectMetadata, IndexingStats

# Optional import for LLM metadata generation
try:
    from services.llm_metadata import LLMMetadataGenerator, GeneratedMetadata
    LLM_METADATA_AVAILABLE = True
except ImportError:
    LLM_METADATA_AVAILABLE = False

logger = logging.getLogger(__name__)


class Indexer:
    """
    Service for indexing RADOS objects into vector database.
    
    Orchestrates the process of:
    1. Scanning pool for objects
    2. Extracting text content
    3. Generating embeddings
    4. Storing in vector database
    """
    
    def __init__(
        self,
        rados_client: RadosClient,
        embedding_generator: EmbeddingGenerator,
        content_processor: ContentProcessor,
        vector_store: RadosVectorStore,
        batch_size: int = 10
    ):
        """
        Initialize indexer.
        
        Args:
            rados_client: RADOS client instance
            embedding_generator: Embedding generator instance
            content_processor: Content processor instance
            vector_store: Vector store instance
            batch_size: Number of objects to process in batch
        """
        self.rados_client = rados_client
        self.embedding_generator = embedding_generator
        self.content_processor = content_processor
        self.vector_store = vector_store
        self.batch_size = batch_size
        
        logger.info("Initialized Indexer service")
    
    def index_object(
        self,
        object_name: str,
        force_reindex: bool = False
    ) -> Optional[ObjectMetadata]:
        """
        Index a single object.
        
        Args:
            object_name: Name of the object to index
            force_reindex: Whether to reindex if already exists
            
        Returns:
            ObjectMetadata if successful, None otherwise
        """
        try:
            # Generate object ID
            object_id = self.rados_client.generate_object_id(object_name)
            
            # Check if already indexed
            if not force_reindex:
                if self.vector_store.has_embedding(object_name):
                    logger.debug(f"Object {object_name} already indexed, skipping")
                    return None
            
            # Check if supported
            if not self.content_processor.is_supported(object_name):
                logger.debug(f"Object {object_name} not supported, skipping")
                return None
            
            # Get object stats
            size_bytes, modified_at = self.rados_client.get_object_stat(object_name)
            
            # Read object content
            data = self.rados_client.read_object(object_name)
            
            # Extract text
            try:
                text, encoding = self.content_processor.extract_text(data, object_name)
            except ValueError as e:
                logger.warning(f"Cannot extract text from {object_name}: {e}")
                return None
            
            # Preprocess and create preview
            text = self.content_processor.preprocess_text(text)
            content_preview = self.content_processor.create_content_preview(text)
            
            # Generate embedding
            embedding = self.embedding_generator.encode(text)
            
            # Detect content type
            content_type = self.content_processor.detect_content_type(data, object_name)
            
            # Create metadata
            metadata = ObjectMetadata(
                object_id=object_id,
                object_name=object_name,
                pool_name=self.rados_client.pool_name,
                content_type=content_type,
                size_bytes=size_bytes,
                encoding=encoding,
                modified_at=modified_at,
                indexed_at=datetime.now(),
                content_preview=content_preview,
                full_text=text if len(text) < 10000 else None,  # Store full text for small files
                embedding_model=self.embedding_generator.model_name,
                embedding_dimensions=self.embedding_generator.get_embedding_dimension()
            )
            
            # Store in vector database
            rados_metadata = {
                "pool_name": metadata.pool_name,
                "content_type": metadata.content_type,
                "size_bytes": str(metadata.size_bytes),
                "embedding_model": metadata.embedding_model,
                "summary": metadata.summary or "",
                "keywords": ",".join(metadata.keywords or []),
                "tags": ",".join(metadata.tags or []),
            }
            self.vector_store.store_embedding(
                object_name=object_name,
                embedding=embedding,
                model_name=metadata.embedding_model,
                content_preview=metadata.content_preview,
                metadata=rados_metadata,
            )
            
            logger.info(f"Successfully indexed: {object_name}")
            return metadata
            
        except Exception as e:
            logger.error(f"Failed to index {object_name}: {e}")
            return None
    
    def index_pool(
        self,
        prefix: Optional[str] = None,
        limit: Optional[int] = None,
        force_reindex: bool = False,
        show_progress: bool = True
    ) -> IndexingStats:
        """
        Index all objects in the pool.
        
        Args:
            prefix: Optional prefix filter
            limit: Maximum number of objects to index
            force_reindex: Whether to reindex existing objects
            show_progress: Whether to show progress bar
            
        Returns:
            IndexingStats with operation statistics
        """
        logger.info(f"Starting pool indexing: {self.rados_client.pool_name}")
        
        start_time = time.time()
        stats = IndexingStats()
        
        try:
            # Ensure connection
            self.rados_client.ensure_connected()
            
            # List objects
            logger.info("Listing objects in pool...")
            objects = self.rados_client.list_objects(prefix=prefix, limit=limit)
            stats.total_objects = len(objects)
            
            logger.info(f"Found {len(objects)} objects to process")
            
            # Process objects
            iterator = tqdm(objects, desc="Indexing objects") if show_progress else objects
            
            for object_name in iterator:
                try:
                    result = self.index_object(object_name, force_reindex)
                    
                    if result:
                        stats.successfully_indexed += 1
                        stats.total_size_bytes += result.size_bytes
                    else:
                        stats.skipped += 1
                        
                except Exception as e:
                    stats.failed += 1
                    error_msg = f"Failed to index {object_name}: {str(e)}"
                    stats.errors.append(error_msg)
                    logger.error(error_msg)
            
            stats.duration_seconds = time.time() - start_time
            
            logger.info(f"Indexing complete: {stats.successfully_indexed} indexed, "
                       f"{stats.skipped} skipped, {stats.failed} failed")
            
            return stats
            
        except Exception as e:
            logger.error(f"Pool indexing failed: {e}")
            stats.duration_seconds = time.time() - start_time
            stats.errors.append(str(e))
            return stats
    
    def index_batch(
        self,
        object_names: List[str],
        force_reindex: bool = False
    ) -> IndexingStats:
        """
        Index a specific list of objects.
        
        Args:
            object_names: List of object names to index
            force_reindex: Whether to reindex existing objects
            
        Returns:
            IndexingStats with operation statistics
        """
        logger.info(f"Starting batch indexing: {len(object_names)} objects")
        
        start_time = time.time()
        stats = IndexingStats(total_objects=len(object_names))
        
        for object_name in tqdm(object_names, desc="Indexing batch"):
            try:
                result = self.index_object(object_name, force_reindex)
                
                if result:
                    stats.successfully_indexed += 1
                    stats.total_size_bytes += result.size_bytes
                else:
                    stats.skipped += 1
                    
            except Exception as e:
                stats.failed += 1
                error_msg = f"Failed to index {object_name}: {str(e)}"
                stats.errors.append(error_msg)
                logger.error(error_msg)
        
        stats.duration_seconds = time.time() - start_time
        
        logger.info(f"Batch indexing complete: {stats.successfully_indexed} indexed, "
                   f"{stats.skipped} skipped, {stats.failed} failed")
        
        return stats
    
    def reindex_all(self, show_progress: bool = True) -> IndexingStats:
        """
        Reindex all objects in the pool.
        
        Args:
            show_progress: Whether to show progress bar
            
        Returns:
            IndexingStats with operation statistics
        """
        logger.warning("Reindexing ALL objects in pool")
        return self.index_pool(force_reindex=True, show_progress=show_progress)
    
    def get_indexing_status(self) -> Dict:
        """
        Get current indexing status.
        
        Returns:
            Dictionary with status information
        """
        try:
            # Get pool stats
            pool_objects = len(self.rados_client.list_objects())
            
            # Get vector store stats
            indexed_objects = self.vector_store.count()
            
            return {
                "pool_name": self.rados_client.pool_name,
                "total_objects_in_pool": pool_objects,
                "indexed_objects": indexed_objects,
                "index_coverage": f"{(indexed_objects/pool_objects*100):.1f}%" if pool_objects > 0 else "0%",
                "embedding_model": self.embedding_generator.model_name,
                "embedding_dimension": self.embedding_generator.get_embedding_dimension()
            }
            
        except Exception as e:
            logger.error(f"Failed to get indexing status: {e}")
            return {"error": str(e)}
    
    def index_with_llm_metadata(
        self,
        object_name: str,
        content: str,
        size_bytes: int,
        llm_config: Optional[Dict] = None,
        user_description: Optional[str] = None,
        use_llm: bool = True
    ) -> Optional[ObjectMetadata]:
        """
        Index an object with LLM-generated metadata.
        
        This method is used after uploading a file to generate rich metadata
        (summary, keywords, tags) using an LLM and store it in the vector database.
        
        Args:
            object_name: Name of the object in Ceph
            content: Text content of the object
            size_bytes: Size of the object in bytes
            llm_config: LLM configuration (required if use_llm=True)
            user_description: Optional user-provided description hint
            use_llm: Whether to use LLM for metadata generation
            
        Returns:
            ObjectMetadata if successful, None otherwise
        """
        try:
            # Generate object ID
            object_id = self.rados_client.generate_object_id(object_name)
            
            # Initialize metadata fields
            summary = user_description or ""
            keywords = []
            tags = []
            
            # Generate LLM metadata if enabled
            if use_llm and llm_config:
                if not LLM_METADATA_AVAILABLE:
                    logger.warning("LLM metadata module not available, skipping LLM generation")
                else:
                    try:
                        llm_generator = LLMMetadataGenerator(llm_config=llm_config)
                        generated = llm_generator.generate(
                            content=content,
                            filename=object_name,
                            user_description=user_description
                        )
                        summary = generated.summary
                        keywords = generated.keywords
                        tags = generated.tags
                        logger.info(f"LLM generated metadata: {len(keywords)} keywords, {len(tags)} tags")
                    except Exception as e:
                        logger.warning(f"LLM metadata generation failed: {e}")
                        # Continue with basic metadata
            
            # Preprocess content
            text = self.content_processor.preprocess_text(content)
            content_preview = self.content_processor.create_content_preview(text)
            
            # For embedding, combine content with summary for better semantic matching
            embedding_text = text
            if summary:
                embedding_text = f"{summary}\n\n{text}"
            
            # Generate embedding
            embedding = self.embedding_generator.encode(embedding_text)
            
            # Detect content type
            content_type = self.content_processor.detect_content_type(
                content.encode('utf-8'), 
                object_name
            )
            
            # Create metadata
            metadata = ObjectMetadata(
                object_id=object_id,
                object_name=object_name,
                pool_name=self.rados_client.pool_name,
                content_type=content_type,
                size_bytes=size_bytes,
                encoding="utf-8",
                modified_at=datetime.now(),
                indexed_at=datetime.now(),
                content_preview=content_preview,
                full_text=text if len(text) < 10000 else None,
                embedding_model=self.embedding_generator.model_name,
                embedding_dimensions=self.embedding_generator.get_embedding_dimension(),
                summary=summary if summary else None,
                keywords=keywords,
                tags=tags
            )
            
            # Store in vector database
            rados_metadata = {
                "pool_name": metadata.pool_name,
                "content_type": metadata.content_type,
                "size_bytes": str(metadata.size_bytes),
                "embedding_model": metadata.embedding_model,
                "summary": summary or "",
                "keywords": ",".join(keywords),
                "tags": ",".join(tags),
            }
            self.vector_store.store_embedding(
                object_name=object_name,
                embedding=embedding,
                model_name=metadata.embedding_model,
                content_preview=metadata.content_preview,
                metadata=rados_metadata,
            )
            
            logger.info(f"Successfully indexed with LLM metadata: {object_name}")
            return metadata
            
        except Exception as e:
            logger.error(f"Failed to index {object_name} with LLM metadata: {e}")
            return None