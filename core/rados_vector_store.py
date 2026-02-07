"""
RADOS-native vector store using extended attributes (xattrs).

Stores embedding vectors directly as RADOS object extended attributes,
eliminating the external ChromaDB dependency for embedding storage.
This is a Ceph-native contribution: the storage system itself manages
the semantic index alongside the data, using RADOS as a unified store.

Architecture:
- Each indexed object gets xattrs:
    user.semantic.embedding    = binary float32 vector
    user.semantic.model        = embedding model name
    user.semantic.indexed_at   = ISO timestamp
    user.semantic.content_hash = SHA256 of content at index time
    user.semantic.dim          = embedding dimension
- A manifest object (_semantic_index) tracks all indexed objects
- Search: read embeddings from xattrs, compute cosine similarity in-process

Advantages over external vector DB:
1. No additional service to manage (ChromaDB, Milvus, etc.)
2. Embeddings co-located with data (data locality)
3. Automatic replication via Ceph (embeddings replicated with objects)
4. Consistent lifecycle (delete object = delete embedding)
5. Works with RADOS namespaces for multi-tenant isolation

Limitations:
- Linear scan for search (no ANN index) — suitable for <50K objects
- xattr size limit (~64KB per attr in default Ceph config)
- Higher search latency than dedicated vector DB at large scale
"""

import logging
import json
import struct
import hashlib
import time
import numpy as np
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)

# xattr key prefix
_PREFIX = "user.semantic."
XATTR_EMBEDDING = f"{_PREFIX}embedding"
XATTR_MODEL = f"{_PREFIX}model"
XATTR_INDEXED_AT = f"{_PREFIX}indexed_at"
XATTR_CONTENT_HASH = f"{_PREFIX}content_hash"
XATTR_DIM = f"{_PREFIX}dim"
XATTR_PREVIEW = f"{_PREFIX}preview"
XATTR_METADATA = f"{_PREFIX}metadata"

# Manifest object that tracks all indexed objects
MANIFEST_OBJECT = "_semantic_index_manifest"


def _encode_embedding(embedding: np.ndarray) -> bytes:
    """Encode float32 embedding vector to bytes."""
    return embedding.astype(np.float32).tobytes()


def _decode_embedding(data: bytes) -> np.ndarray:
    """Decode bytes to float32 embedding vector."""
    return np.frombuffer(data, dtype=np.float32)


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


class RadosVectorStore:
    """
    RADOS-native vector store using extended attributes.
    
    Stores embeddings as xattrs on Ceph objects, providing a
    Ceph-native alternative to external vector databases.
    """
    
    def __init__(self, rados_client, embedding_dim: int = 384):
        """
        Initialize RADOS vector store.
        
        Args:
            rados_client: Connected RadosClient instance
            embedding_dim: Expected embedding dimension (default: 384 for MiniLM)
        """
        self.rados = rados_client
        self.embedding_dim = embedding_dim
        self._manifest_cache: Optional[Dict] = None
        self._manifest_dirty = False
        
        logger.info(f"Initialized RadosVectorStore (dim={embedding_dim})")
    
    # ========== Indexing ==========
    
    def store_embedding(
        self,
        object_name: str,
        embedding: np.ndarray,
        model_name: str = "all-MiniLM-L6-v2",
        content_preview: str = "",
        metadata: Optional[Dict[str, str]] = None
    ) -> float:
        """
        Store an embedding vector as xattrs on a RADOS object.
        
        Args:
            object_name: Name of the RADOS object
            embedding: Embedding vector (np.ndarray)
            model_name: Name of the embedding model used
            content_preview: Short text preview of content
            metadata: Additional metadata dict
            
        Returns:
            Time taken in milliseconds
        """
        t_start = time.time()
        
        # Validate
        if not isinstance(embedding, np.ndarray):
            embedding = np.array(embedding, dtype=np.float32)
        
        if embedding.shape[0] != self.embedding_dim:
            logger.warning(f"Embedding dim mismatch: expected {self.embedding_dim}, got {embedding.shape[0]}")
        
        # Store embedding as binary xattr
        emb_bytes = _encode_embedding(embedding)
        self.rados.set_xattr(object_name, XATTR_EMBEDDING, emb_bytes)
        
        # Store metadata xattrs
        self.rados.set_xattr(object_name, XATTR_MODEL, model_name.encode('utf-8'))
        self.rados.set_xattr(object_name, XATTR_INDEXED_AT, datetime.now().isoformat().encode('utf-8'))
        self.rados.set_xattr(object_name, XATTR_DIM, str(embedding.shape[0]).encode('utf-8'))
        
        if content_preview:
            # Truncate preview to fit xattr size limits
            preview = content_preview[:4096].encode('utf-8')
            self.rados.set_xattr(object_name, XATTR_PREVIEW, preview)
        
        if metadata:
            meta_json = json.dumps(metadata)[:8192]
            self.rados.set_xattr(object_name, XATTR_METADATA, meta_json.encode('utf-8'))
        
        # Content hash for staleness detection
        content_hash = hashlib.sha256(emb_bytes).hexdigest()[:16]
        self.rados.set_xattr(object_name, XATTR_CONTENT_HASH, content_hash.encode('utf-8'))
        
        # Update manifest
        self._update_manifest(object_name, "add")
        
        elapsed_ms = (time.time() - t_start) * 1000
        logger.debug(f"Stored embedding for '{object_name}' ({len(emb_bytes)} bytes, {elapsed_ms:.1f}ms)")
        return elapsed_ms
    
    def remove_embedding(self, object_name: str) -> bool:
        """
        Remove embedding xattrs from a RADOS object.
        
        Args:
            object_name: Name of the RADOS object
            
        Returns:
            True if removed, False if not found
        """
        try:
            for attr in [XATTR_EMBEDDING, XATTR_MODEL, XATTR_INDEXED_AT,
                         XATTR_DIM, XATTR_PREVIEW, XATTR_METADATA, XATTR_CONTENT_HASH]:
                try:
                    # Remove xattr (set to empty to "delete" — RADOS doesn't have rmxattr easily)
                    self.rados.set_xattr(object_name, attr, b"")
                except Exception:
                    pass
            
            self._update_manifest(object_name, "remove")
            return True
        except Exception as e:
            logger.error(f"Failed to remove embedding for '{object_name}': {e}")
            return False
    
    def has_embedding(self, object_name: str) -> bool:
        """Check if an object has a stored embedding."""
        data = self.rados.get_xattr(object_name, XATTR_EMBEDDING)
        return data is not None and len(data) > 0
    
    def get_embedding(self, object_name: str) -> Optional[np.ndarray]:
        """
        Retrieve the embedding vector for an object.
        
        Args:
            object_name: Name of the RADOS object
            
        Returns:
            Embedding vector or None
        """
        data = self.rados.get_xattr(object_name, XATTR_EMBEDDING)
        if data is None or len(data) == 0:
            return None
        return _decode_embedding(data)
    
    def get_embedding_metadata(self, object_name: str) -> Dict[str, Any]:
        """Get all semantic metadata for an object."""
        result = {}
        
        for attr, key in [(XATTR_MODEL, "model"), (XATTR_INDEXED_AT, "indexed_at"),
                          (XATTR_DIM, "dim"), (XATTR_PREVIEW, "preview"),
                          (XATTR_CONTENT_HASH, "content_hash")]:
            data = self.rados.get_xattr(object_name, attr)
            if data:
                result[key] = data.decode('utf-8', errors='replace')
        
        meta_data = self.rados.get_xattr(object_name, XATTR_METADATA)
        if meta_data:
            try:
                result["metadata"] = json.loads(meta_data.decode('utf-8'))
            except json.JSONDecodeError:
                pass
        
        return result
    
    # ========== Search ==========
    
    def search(
        self,
        query_embedding: np.ndarray,
        top_k: int = 10,
        min_similarity: float = 0.0
    ) -> List[Dict[str, Any]]:
        """
        Search for similar objects using cosine similarity.
        
        Performs linear scan over all indexed objects' xattr embeddings.
        
        Args:
            query_embedding: Query embedding vector
            top_k: Number of results to return
            min_similarity: Minimum similarity threshold
            
        Returns:
            List of dicts with 'object_name', 'similarity', 'preview', 'metadata'
        """
        t_start = time.time()
        
        if not isinstance(query_embedding, np.ndarray):
            query_embedding = np.array(query_embedding, dtype=np.float32)
        
        # Get list of indexed objects from manifest
        indexed_objects = self._get_indexed_objects()
        
        if not indexed_objects:
            logger.warning("No indexed objects found")
            return []
        
        # Linear scan: compute similarity with each indexed object
        results = []
        for obj_name in indexed_objects:
            try:
                emb = self.get_embedding(obj_name)
                if emb is None:
                    continue
                
                sim = _cosine_similarity(query_embedding, emb)
                if sim >= min_similarity:
                    # Get preview
                    preview_data = self.rados.get_xattr(obj_name, XATTR_PREVIEW)
                    preview = preview_data.decode('utf-8', errors='replace') if preview_data else ""
                    
                    results.append({
                        'object_name': obj_name,
                        'similarity': sim,
                        'preview': preview,
                    })
            except Exception as e:
                logger.debug(f"Skipping '{obj_name}' during search: {e}")
        
        # Sort by similarity (descending) and take top_k
        results.sort(key=lambda x: x['similarity'], reverse=True)
        results = results[:top_k]
        
        elapsed_ms = (time.time() - t_start) * 1000
        logger.debug(f"RADOS xattr search: {len(indexed_objects)} objects scanned, "
                     f"{len(results)} results in {elapsed_ms:.1f}ms")
        
        return results
    
    def search_by_text(
        self,
        query_text: str,
        embedding_generator,
        top_k: int = 10,
        min_similarity: float = 0.0
    ) -> List[Dict[str, Any]]:
        """
        Search using a text query (generates embedding first).
        
        Args:
            query_text: Natural language query
            embedding_generator: Object with generate(text) method
            top_k: Number of results
            min_similarity: Minimum similarity threshold
            
        Returns:
            Search results
        """
        query_embedding = embedding_generator.generate(query_text)
        return self.search(query_embedding, top_k=top_k, min_similarity=min_similarity)
    
    # ========== Manifest Management ==========
    
    def _get_indexed_objects(self) -> List[str]:
        """Get list of all indexed objects from manifest."""
        manifest = self._load_manifest()
        return manifest.get("objects", [])
    
    def _update_manifest(self, object_name: str, action: str):
        """Update the manifest object that tracks indexed objects."""
        manifest = self._load_manifest()
        objects = set(manifest.get("objects", []))
        
        if action == "add":
            objects.add(object_name)
        elif action == "remove":
            objects.discard(object_name)
        
        manifest["objects"] = sorted(objects)
        manifest["count"] = len(objects)
        manifest["updated_at"] = datetime.now().isoformat()
        
        # Write manifest back to RADOS
        manifest_bytes = json.dumps(manifest, indent=2).encode('utf-8')
        self.rados.write_object(MANIFEST_OBJECT, manifest_bytes)
        self._manifest_cache = manifest
    
    def _load_manifest(self) -> Dict:
        """Load manifest from RADOS or create empty one."""
        if self._manifest_cache is not None:
            return self._manifest_cache
        
        try:
            data = self.rados.read_object(MANIFEST_OBJECT)
            self._manifest_cache = json.loads(data.decode('utf-8'))
        except Exception:
            self._manifest_cache = {"objects": [], "count": 0, "created_at": datetime.now().isoformat()}
        
        return self._manifest_cache
    
    def rebuild_manifest(self) -> int:
        """
        Rebuild manifest by scanning all objects for embedding xattrs.
        
        Returns:
            Number of indexed objects found
        """
        logger.info("Rebuilding RADOS vector store manifest...")
        objects = self.rados.list_objects()
        indexed = []
        
        for obj_name in objects:
            if obj_name == MANIFEST_OBJECT:
                continue
            if self.has_embedding(obj_name):
                indexed.append(obj_name)
        
        manifest = {
            "objects": sorted(indexed),
            "count": len(indexed),
            "updated_at": datetime.now().isoformat(),
            "rebuilt": True,
        }
        
        manifest_bytes = json.dumps(manifest, indent=2).encode('utf-8')
        self.rados.write_object(MANIFEST_OBJECT, manifest_bytes)
        self._manifest_cache = manifest
        
        logger.info(f"Manifest rebuilt: {len(indexed)} indexed objects")
        return len(indexed)
    
    # ========== Statistics ==========
    
    def get_stats(self) -> Dict[str, Any]:
        """Get vector store statistics."""
        manifest = self._load_manifest()
        
        total_embedding_bytes = 0
        for obj_name in manifest.get("objects", []):
            emb_data = self.rados.get_xattr(obj_name, XATTR_EMBEDDING)
            if emb_data:
                total_embedding_bytes += len(emb_data)
        
        return {
            "indexed_objects": manifest.get("count", 0),
            "embedding_dim": self.embedding_dim,
            "total_embedding_bytes": total_embedding_bytes,
            "total_embedding_kb": total_embedding_bytes / 1024,
            "bytes_per_embedding": self.embedding_dim * 4,  # float32
            "backend": "rados_xattr",
            "manifest_object": MANIFEST_OBJECT,
        }
    
    def count(self) -> int:
        """Return number of indexed objects."""
        manifest = self._load_manifest()
        return manifest.get("count", 0)
