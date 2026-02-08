"""
Vector store interface using ChromaDB for semantic search.

This module provides a high-level interface to ChromaDB for storing
and retrieving object embeddings with metadata.
"""

import logging
from typing import List, Optional, Dict, Any, Tuple
import chromadb
from chromadb.config import Settings
from chromadb.utils import embedding_functions
import numpy as np
from datetime import datetime

from .metadata_schema import ObjectMetadata, SearchResult

logger = logging.getLogger(__name__)


class VectorStore:
    """
    Vector database interface using ChromaDB.
    
    Handles storage and retrieval of embeddings with associated metadata
    for semantic search operations.
    """
    
    def __init__(
        self,
        persist_directory: str = "./chroma_data",
        collection_name: str = "ceph_semantic_objects",
        distance_metric: str = "cosine"
    ):
        """
        Initialize vector store.
        
        Args:
            persist_directory: Directory to persist ChromaDB data
            collection_name: Name of the collection
            distance_metric: Distance metric (cosine, l2, ip)
        """
        self.persist_directory = persist_directory
        self.collection_name = collection_name
        self.distance_metric = distance_metric
        
        logger.info(f"Initializing ChromaDB at: {persist_directory}")
        
        # Initialize ChromaDB client
        self.client = chromadb.PersistentClient(
            path=persist_directory,
            settings=Settings(
                anonymized_telemetry=False,
                allow_reset=True
            )
        )
        
        # Create or get collection
        self.collection = self._get_or_create_collection()
        
        logger.info(f"Collection '{collection_name}' ready with {self.count()} items")
    
    def _get_or_create_collection(self):
        """Get existing collection or create new one."""
        try:
            collection = self.client.get_collection(
                name=self.collection_name,
                embedding_function=None  # We provide embeddings directly
            )
            logger.info(f"Loaded existing collection: {self.collection_name}")
            return collection
            
        except Exception:
            # Collection doesn't exist, create it
            collection = self.client.create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": self.distance_metric},
                embedding_function=None
            )
            logger.info(f"Created new collection: {self.collection_name}")
            return collection
    
    def add(
        self,
        object_id: str,
        embedding: np.ndarray,
        metadata: ObjectMetadata
    ) -> None:
        """
        Add an object embedding to the vector store.
        
        Args:
            object_id: Unique object identifier
            embedding: Embedding vector
            metadata: Object metadata
        """
        try:
            # Convert numpy array to list if needed
            if isinstance(embedding, np.ndarray):
                embedding = embedding.tolist()
            
            # Prepare metadata for ChromaDB (must be flat dict with simple types)
            chroma_metadata = {
                "object_name": metadata.object_name,
                "pool_name": metadata.pool_name,
                "content_type": metadata.content_type,
                "size_bytes": metadata.size_bytes,
                "indexed_at": metadata.indexed_at.isoformat(),
                "embedding_model": metadata.embedding_model,
                "content_preview": metadata.content_preview[:1000],  # Limit size
            }
            
            # Add optional fields if present
            if metadata.modified_at:
                chroma_metadata["modified_at"] = metadata.modified_at.isoformat()
            if metadata.summary:
                chroma_metadata["summary"] = metadata.summary[:1000]
            if metadata.keywords:
                chroma_metadata["keywords"] = ",".join(metadata.keywords[:10])
            if metadata.tags:
                chroma_metadata["tags"] = ",".join(metadata.tags[:10])
            
            # Add to collection
            self.collection.add(
                ids=[object_id],
                embeddings=[embedding],
                metadatas=[chroma_metadata],
                documents=[metadata.content_preview]  # Store preview as document
            )
            
            logger.debug(f"Added object {object_id} to vector store")
            
        except Exception as e:
            logger.error(f"Failed to add object {object_id}: {e}")
            raise
    
    def add_batch(
        self,
        object_ids: List[str],
        embeddings: List[np.ndarray],
        metadatas: List[ObjectMetadata]
    ) -> None:
        """
        Add multiple objects in batch.
        
        Args:
            object_ids: List of object IDs
            embeddings: List of embedding vectors
            metadatas: List of object metadata
        """
        if not (len(object_ids) == len(embeddings) == len(metadatas)):
            raise ValueError("Length mismatch between ids, embeddings, and metadatas")
        
        try:
            # Convert embeddings to lists
            embeddings_list = [
                emb.tolist() if isinstance(emb, np.ndarray) else emb
                for emb in embeddings
            ]
            
            # Prepare metadata
            chroma_metadatas = []
            documents = []
            
            for metadata in metadatas:
                chroma_metadata = {
                    "object_name": metadata.object_name,
                    "pool_name": metadata.pool_name,
                    "content_type": metadata.content_type,
                    "size_bytes": metadata.size_bytes,
                    "indexed_at": metadata.indexed_at.isoformat(),
                    "embedding_model": metadata.embedding_model,
                    "content_preview": metadata.content_preview[:1000],
                }
                
                if metadata.modified_at:
                    chroma_metadata["modified_at"] = metadata.modified_at.isoformat()
                if metadata.summary:
                    chroma_metadata["summary"] = metadata.summary[:1000]
                if metadata.keywords:
                    chroma_metadata["keywords"] = ",".join(metadata.keywords[:10])
                if metadata.tags:
                    chroma_metadata["tags"] = ",".join(metadata.tags[:10])
                
                chroma_metadatas.append(chroma_metadata)
                documents.append(metadata.content_preview)
            
            # Add batch to collection
            self.collection.add(
                ids=object_ids,
                embeddings=embeddings_list,
                metadatas=chroma_metadatas,
                documents=documents
            )
            
            logger.info(f"Added batch of {len(object_ids)} objects to vector store")
            
        except Exception as e:
            logger.error(f"Failed to add batch: {e}")
            raise
    
    def search(
        self,
        query_embedding: np.ndarray,
        top_k: int = 10,
        filter_dict: Optional[Dict[str, Any]] = None
    ) -> List[Tuple[str, float, Dict[str, Any]]]:
        """
        Search for similar objects.
        
        Args:
            query_embedding: Query embedding vector
            top_k: Number of results to return
            filter_dict: Optional metadata filters
            
        Returns:
            List of tuples (object_id, distance, metadata)
        """
        try:
            # Convert to list if needed
            if isinstance(query_embedding, np.ndarray):
                query_embedding = query_embedding.tolist()
            
            # Perform search
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                where=filter_dict,
                include=["metadatas", "distances", "documents"]
            )
            
            # Parse results
            search_results = []
            
            if results['ids'] and len(results['ids'][0]) > 0:
                for i in range(len(results['ids'][0])):
                    object_id = results['ids'][0][i]
                    distance = results['distances'][0][i]
                    metadata = results['metadatas'][0][i]
                    
                    search_results.append((object_id, distance, metadata))
            
            logger.debug(f"Search returned {len(search_results)} results")
            return search_results
            
        except Exception as e:
            logger.error(f"Search failed: {e}")
            raise
    
    def get(self, object_id: str) -> Optional[Dict[str, Any]]:
        """
        Get object by ID.
        
        Args:
            object_id: Object identifier
            
        Returns:
            Object metadata or None if not found
        """
        try:
            results = self.collection.get(
                ids=[object_id],
                include=["metadatas", "embeddings", "documents"]
            )
            
            if results['ids']:
                # Use 'is not None' to avoid numpy array truth value ambiguity
                embeddings = results.get('embeddings')
                documents = results.get('documents')
                
                has_embeddings = embeddings is not None and len(embeddings) > 0
                has_documents = documents is not None and len(documents) > 0
                
                return {
                    'id': results['ids'][0],
                    'metadata': results['metadatas'][0],
                    'embedding': embeddings[0] if has_embeddings else None,
                    'document': documents[0] if has_documents else None
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to get object {object_id}: {e}")
            return None
    
    def delete(self, object_id: str) -> None:
        """
        Delete object from vector store.
        
        Args:
            object_id: Object identifier
        """
        try:
            self.collection.delete(ids=[object_id])
            logger.debug(f"Deleted object {object_id}")
        except Exception as e:
            logger.error(f"Failed to delete object {object_id}: {e}")
            raise
    
    def update(
        self,
        object_id: str,
        embedding: Optional[np.ndarray] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Update object in vector store.
        
        Args:
            object_id: Object identifier
            embedding: New embedding (optional)
            metadata: New metadata (optional)
        """
        try:
            update_kwargs = {"ids": [object_id]}
            
            if embedding is not None:
                if isinstance(embedding, np.ndarray):
                    embedding = embedding.tolist()
                update_kwargs["embeddings"] = [embedding]
            
            if metadata is not None:
                update_kwargs["metadatas"] = [metadata]
            
            self.collection.update(**update_kwargs)
            logger.debug(f"Updated object {object_id}")
            
        except Exception as e:
            logger.error(f"Failed to update object {object_id}: {e}")
            raise
    
    def count(self) -> int:
        """Get total number of objects in collection."""
        return self.collection.count()
    
    def list_all(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        List all objects in the collection.
        
        Args:
            limit: Maximum number of objects to return
            
        Returns:
            List of objects with metadata
        """
        try:
            results = self.collection.get(
                limit=limit,
                include=["metadatas"]
            )
            
            objects = []
            if results['ids']:
                for i, obj_id in enumerate(results['ids']):
                    objects.append({
                        'id': obj_id,
                        'metadata': results['metadatas'][i]
                    })
            
            return objects
            
        except Exception as e:
            logger.error(f"Failed to list objects: {e}")
            raise
    
    def clear(self) -> None:
        """Clear all objects from collection."""
        logger.warning("Clearing all objects from collection")
        self.client.delete_collection(name=self.collection_name)
        self.collection = self._get_or_create_collection()
        logger.info("Collection cleared")
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the vector store.
        
        Returns:
            Dictionary with stats
        """
        count = self.count()
        
        stats = {
            "collection_name": self.collection_name,
            "total_objects": count,
            "distance_metric": self.distance_metric,
            "persist_directory": self.persist_directory
        }
        
        # Get sample metadata to determine pools
        if count > 0:
            sample = self.collection.get(limit=min(100, count), include=["metadatas"])
            pools = set()
            models = set()
            
            for metadata in sample['metadatas']:
                if 'pool_name' in metadata:
                    pools.add(metadata['pool_name'])
                if 'embedding_model' in metadata:
                    models.add(metadata['embedding_model'])
            
            stats["pools"] = list(pools)
            stats["embedding_models"] = list(models)
        
        return stats
