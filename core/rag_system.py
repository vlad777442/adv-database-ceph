"""
RAG (Retrieval-Augmented Generation) system for Ceph documentation.

Provides semantic search over Ceph documentation to answer
user questions with accurate, documentation-backed responses.
"""

import logging
import os
import json
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class Document:
    """Represents a documentation chunk."""
    id: str
    content: str
    source: str
    title: str = ""
    section: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchResult:
    """Result from documentation search."""
    document: Document
    score: float
    highlights: List[str] = field(default_factory=list)


class CephDocRAG:
    """
    RAG system for Ceph documentation.
    
    Features:
    - Semantic search over Ceph docs
    - Context-aware responses
    - Source attribution
    - Incremental indexing
    """
    
    # Built-in knowledge base for common Ceph concepts
    # This serves as a fallback and quick reference
    BUILTIN_KNOWLEDGE = [
        {
            "id": "health_ok",
            "title": "HEALTH_OK Status",
            "section": "Cluster Health",
            "content": """HEALTH_OK means the Ceph cluster is operating normally. All OSDs are up and in, 
all PGs are active+clean, and there are no outstanding health warnings or errors. 
This is the ideal state for a production cluster."""
        },
        {
            "id": "health_warn",
            "title": "HEALTH_WARN Status",
            "section": "Cluster Health",
            "content": """HEALTH_WARN indicates the cluster has non-critical issues that should be addressed. 
Common causes include: nearfull OSDs, too few PGs, clock skew between nodes, 
degraded PGs that are recovering, or missing scrub operations. The cluster remains 
operational but should be monitored closely."""
        },
        {
            "id": "health_err",
            "title": "HEALTH_ERR Status",
            "section": "Cluster Health",
            "content": """HEALTH_ERR indicates critical issues requiring immediate attention. 
Common causes: down OSDs affecting data availability, stuck/stale PGs, 
full OSDs blocking writes, or corrupted data. Data may be at risk or unavailable. 
Immediate intervention is required."""
        },
        {
            "id": "osd_overview",
            "title": "OSD (Object Storage Daemon)",
            "section": "Architecture",
            "content": """An OSD (Object Storage Daemon) is responsible for storing data, handling data 
replication, recovery, rebalancing, and providing heartbeats to monitors. 
Each OSD manages a single storage device (HDD, SSD, or NVMe). 
States: 'up' (running) and 'in' (participating in cluster). 
An OSD that is 'up' but 'out' won't receive new data but still serves existing data."""
        },
        {
            "id": "pg_overview",
            "title": "Placement Groups (PGs)",
            "section": "Architecture",
            "content": """Placement Groups (PGs) are logical collections of objects that are replicated 
across OSDs together. PGs provide a layer of abstraction between RADOS objects 
and OSDs. The number of PGs affects performance and resource usage. 
Common states: active+clean (healthy), degraded (missing replicas), 
recovering (rebuilding), undersized (fewer OSDs than desired), 
stale (OSD not reporting)."""
        },
        {
            "id": "crush_map",
            "title": "CRUSH Map and Algorithm",
            "section": "Architecture",
            "content": """CRUSH (Controlled Replication Under Scalable Hashing) is Ceph's algorithm for 
determining where data is stored. The CRUSH map defines the cluster topology 
(hosts, racks, datacenters) and rules for data placement. CRUSH enables 
clients to calculate data location without querying a central authority, 
making Ceph highly scalable."""
        },
        {
            "id": "erasure_coding",
            "title": "Erasure Coding",
            "section": "Data Protection",
            "content": """Erasure coding (EC) is an alternative to replication for data protection. 
It splits data into k data chunks and m coding chunks. Any k chunks can 
reconstruct the original data. EC uses less storage than replication 
(e.g., k=4, m=2 uses 1.5x storage vs 3x for 3-way replication) but has 
higher CPU overhead and slower random writes. Best for cold/archive data."""
        },
        {
            "id": "pools_overview",
            "title": "Ceph Pools",
            "section": "Architecture",
            "content": """Pools are logical partitions for storing objects. Each pool has:
- Replication size or erasure code profile
- Number of placement groups (PGs)
- CRUSH rule for data placement
- Application tag (rbd, cephfs, rgw)
Pool types: replicated (copies data) or erasure-coded (calculates parity).
Create with: ceph osd pool create <name> <pg_num>"""
        },
        {
            "id": "cephfs_overview",
            "title": "CephFS (Ceph File System)",
            "section": "Storage Interfaces",
            "content": """CephFS is a POSIX-compliant distributed file system built on RADOS. 
Components: MDS (Metadata Server) for directory hierarchy and file metadata, 
data pool for file contents, metadata pool for MDS state. 
Mount via kernel client or FUSE. Supports snapshots, quotas, and multiple 
active MDS for scalability. Use for shared file access workloads."""
        },
        {
            "id": "rbd_overview",
            "title": "RBD (RADOS Block Device)",
            "section": "Storage Interfaces",
            "content": """RBD provides block storage on top of RADOS. Features: thin provisioning, 
snapshots, cloning, live migration, and striping across objects. 
Commonly used for VM disks in OpenStack/Kubernetes. 
Create with: rbd create <image> --size <MB> --pool <pool>.
Can be mapped as a block device on Linux or accessed via librbd."""
        },
        {
            "id": "rgw_overview",
            "title": "RGW (RADOS Gateway)",
            "section": "Storage Interfaces",
            "content": """RGW (RADOS Gateway) provides object storage with S3 and Swift APIs. 
Supports multi-tenancy, bucket policies, versioning, and lifecycle management.
Components: radosgw daemon (HTTP frontend), data pools, index pools.
Deploy behind load balancer for HA. Useful for cloud-native applications
and backup targets."""
        },
        {
            "id": "rebalancing",
            "title": "Data Rebalancing",
            "section": "Operations",
            "content": """Rebalancing occurs when OSDs are added, removed, or CRUSH weights change.
Ceph automatically migrates PGs to balance data distribution.
Control with: ceph osd set/unset norebalance.
Monitor progress: ceph -s shows recovery stats.
Throttle with: osd_recovery_max_active, osd_recovery_sleep settings.
Adding OSDs gradually reduces impact."""
        },
        {
            "id": "scrubbing",
            "title": "Scrubbing and Deep Scrubbing",
            "section": "Operations",
            "content": """Scrubbing verifies data integrity by comparing object metadata across replicas.
Light scrub: checks size and attributes (daily by default).
Deep scrub: reads and checksums all data (weekly by default).
Can impact performance. Schedule with osd_scrub_begin_hour/end_hour.
Force scrub: ceph pg scrub <pg_id> or deep-scrub <pg_id>.
Detects bit rot and replication inconsistencies."""
        },
        {
            "id": "recovery",
            "title": "Recovery and Backfilling",
            "section": "Operations",
            "content": """Recovery restores missing replicas after OSD failure or addition.
Backfill: bulk data migration to new OSDs.
Recovery: restoring specific missing objects.
Monitor: ceph -s, ceph pg dump.
Prioritize with: ceph pg force-recovery <pg_id>.
Tune: osd_recovery_max_active, osd_recovery_priority.
Recovery must complete before data is fully protected."""
        },
        {
            "id": "slow_requests",
            "title": "Slow Requests and Blocked Operations",
            "section": "Troubleshooting",
            "content": """Slow requests indicate operations taking longer than expected (default 30s).
Causes: overloaded OSDs, slow disks, network issues, PG problems.
Check: ceph daemon osd.<id> ops, ceph health detail.
Common types: osd_op (client I/O), osd_sub_op (replication).
Solutions: add OSDs, upgrade disks, reduce load, check network.
The 'slow request' threshold is configurable with osd_op_complaint_time."""
        },
        {
            "id": "full_osd",
            "title": "Full and Nearfull OSDs",
            "section": "Troubleshooting",
            "content": """Thresholds: nearfull (85%), backfillfull (90%), full (95%).
At nearfull: warning, monitor closely.
At backfillfull: stops backfill operations.
At full: blocks all writes to affected PGs.
Solutions: delete data, add OSDs, reweight OSDs, increase size.
Emergency: ceph osd set-full-ratio 0.97 (temporary, risky).
Use: ceph osd df to check individual OSD utilization."""
        },
        {
            "id": "mon_overview",
            "title": "Monitors (MON)",
            "section": "Architecture",
            "content": """Monitors maintain cluster maps (OSD map, PG map, CRUSH map, MDS map).
Use Paxos consensus for distributed agreement.
Require majority (quorum): deploy odd number (3, 5, 7).
Store data in key-value database (RocksDB).
Check status: ceph mon stat, ceph quorum_status.
Losing quorum = cluster is read-only or unavailable."""
        },
        {
            "id": "mgr_overview", 
            "title": "Manager Daemon (MGR)",
            "section": "Architecture",
            "content": """Manager daemon (ceph-mgr) provides monitoring, orchestration, and additional APIs.
Modules: dashboard, prometheus, rook, orchestrator, telemetry.
One active, others standby for HA.
Enable modules: ceph mgr module enable <module>.
Dashboard provides web UI for monitoring and management.
REST API available for automation."""
        },
        {
            "id": "benchmarking",
            "title": "Performance Benchmarking",
            "section": "Operations",
            "content": """Tools for benchmarking Ceph:
- rados bench: RADOS-level throughput test
  rados bench -p <pool> 60 write/seq/rand
- rbd bench: RBD block device testing
  rbd bench <image> --io-type write --io-size 4K
- fio: general-purpose I/O benchmark with rbd/rados engines
Monitor during tests: ceph -s, ceph osd perf.
Consider cache effects and run multiple iterations."""
        }
    ]
    
    def __init__(
        self,
        embedding_generator,
        docs_directory: str = "./ceph_docs",
        persist_directory: str = "./rag_data",
        chunk_size: int = 500,
        chunk_overlap: int = 50
    ):
        """
        Initialize RAG system.
        
        Args:
            embedding_generator: EmbeddingGenerator instance
            docs_directory: Directory containing Ceph docs
            persist_directory: Directory for persisting RAG index
            chunk_size: Size of document chunks
            chunk_overlap: Overlap between chunks
        """
        self.embedding_generator = embedding_generator
        self.docs_directory = Path(docs_directory)
        self.persist_directory = Path(persist_directory)
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        
        self.persist_directory.mkdir(parents=True, exist_ok=True)
        
        # In-memory document store
        self.documents: Dict[str, Document] = {}
        self.embeddings: Dict[str, List[float]] = {}
        
        # Load built-in knowledge
        self._load_builtin_knowledge()
        
        # Load persisted index if available
        self._load_index()
        
        logger.info(f"Initialized CephDocRAG with {len(self.documents)} documents")
    
    def _load_builtin_knowledge(self):
        """Load built-in Ceph knowledge base."""
        for item in self.BUILTIN_KNOWLEDGE:
            doc = Document(
                id=f"builtin_{item['id']}",
                content=item['content'],
                source="builtin_knowledge",
                title=item['title'],
                section=item['section'],
                metadata={"type": "builtin"}
            )
            self.documents[doc.id] = doc
            
            # Generate embedding
            embedding = self.embedding_generator.encode([item['content']])[0]
            self.embeddings[doc.id] = embedding.tolist() if hasattr(embedding, 'tolist') else embedding
    
    def _load_index(self):
        """Load persisted index from disk."""
        index_file = self.persist_directory / "rag_index.json"
        embeddings_file = self.persist_directory / "rag_embeddings.json"
        
        if index_file.exists() and embeddings_file.exists():
            try:
                with open(index_file, 'r') as f:
                    docs_data = json.load(f)
                with open(embeddings_file, 'r') as f:
                    embeddings_data = json.load(f)
                
                for doc_id, doc_dict in docs_data.items():
                    if doc_id not in self.documents:  # Don't override built-in
                        self.documents[doc_id] = Document(**doc_dict)
                
                for doc_id, embedding in embeddings_data.items():
                    if doc_id not in self.embeddings:
                        self.embeddings[doc_id] = embedding
                
                logger.info(f"Loaded {len(docs_data)} documents from index")
            except Exception as e:
                logger.error(f"Failed to load index: {e}")
    
    def _save_index(self):
        """Persist index to disk."""
        index_file = self.persist_directory / "rag_index.json"
        embeddings_file = self.persist_directory / "rag_embeddings.json"
        
        try:
            # Save documents
            docs_data = {}
            for doc_id, doc in self.documents.items():
                if not doc_id.startswith("builtin_"):  # Don't persist built-in
                    docs_data[doc_id] = {
                        "id": doc.id,
                        "content": doc.content,
                        "source": doc.source,
                        "title": doc.title,
                        "section": doc.section,
                        "metadata": doc.metadata
                    }
            
            with open(index_file, 'w') as f:
                json.dump(docs_data, f)
            
            # Save embeddings
            embeddings_data = {
                k: v for k, v in self.embeddings.items() 
                if not k.startswith("builtin_")
            }
            with open(embeddings_file, 'w') as f:
                json.dump(embeddings_data, f)
            
            logger.info(f"Saved {len(docs_data)} documents to index")
        except Exception as e:
            logger.error(f"Failed to save index: {e}")
    
    def add_document(self, content: str, source: str, title: str = "", section: str = ""):
        """
        Add a document to the RAG system.
        
        Args:
            content: Document content
            source: Source file or URL
            title: Document title
            section: Section within source
        """
        # Create unique ID
        doc_id = hashlib.md5(f"{source}:{title}:{content[:100]}".encode()).hexdigest()
        
        # Chunk if necessary
        chunks = self._chunk_text(content)
        
        for i, chunk in enumerate(chunks):
            chunk_id = f"{doc_id}_{i}" if len(chunks) > 1 else doc_id
            
            doc = Document(
                id=chunk_id,
                content=chunk,
                source=source,
                title=title,
                section=section,
                metadata={"chunk": i, "total_chunks": len(chunks)}
            )
            
            self.documents[chunk_id] = doc
            
            # Generate embedding
            embedding = self.embedding_generator.encode([chunk])[0]
            embedding = embedding.tolist() if hasattr(embedding, 'tolist') else embedding
            self.embeddings[chunk_id] = embedding
        
        self._save_index()
        logger.info(f"Added document: {title} ({len(chunks)} chunks)")
    
    def _chunk_text(self, text: str) -> List[str]:
        """Split text into overlapping chunks."""
        if len(text) <= self.chunk_size:
            return [text]
        
        chunks = []
        start = 0
        
        while start < len(text):
            end = start + self.chunk_size
            
            # Try to break at sentence boundary
            if end < len(text):
                # Look for sentence end
                for sep in ['. ', '.\n', '\n\n']:
                    last_sep = text[start:end].rfind(sep)
                    if last_sep > self.chunk_size * 0.5:
                        end = start + last_sep + len(sep)
                        break
            
            chunks.append(text[start:end].strip())
            start = end - self.chunk_overlap
        
        return chunks
    
    def search(self, query: str, top_k: int = 3) -> List[SearchResult]:
        """
        Search documentation for relevant content.
        
        Args:
            query: Search query
            top_k: Number of results to return
            
        Returns:
            List of SearchResult objects
        """
        if not self.documents:
            return []
        
        # Generate query embedding
        query_embedding = self.embedding_generator.encode([query])[0]
        query_embedding = query_embedding.tolist() if hasattr(query_embedding, 'tolist') else query_embedding
        
        # Calculate similarities
        similarities = []
        for doc_id, doc_embedding in self.embeddings.items():
            similarity = self._cosine_similarity(query_embedding, doc_embedding)
            similarities.append((doc_id, similarity))
        
        # Sort by similarity
        similarities.sort(key=lambda x: x[1], reverse=True)
        
        # Build results
        results = []
        for doc_id, score in similarities[:top_k]:
            doc = self.documents[doc_id]
            results.append(SearchResult(
                document=doc,
                score=score,
                highlights=self._extract_highlights(doc.content, query)
            ))
        
        return results
    
    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        import math
        dot_product = sum(x * y for x, y in zip(a, b))
        magnitude_a = math.sqrt(sum(x * x for x in a))
        magnitude_b = math.sqrt(sum(x * x for x in b))
        
        if magnitude_a == 0 or magnitude_b == 0:
            return 0.0
        
        return dot_product / (magnitude_a * magnitude_b)
    
    def _extract_highlights(self, content: str, query: str, max_length: int = 150) -> List[str]:
        """Extract relevant snippets from content."""
        # Simple keyword-based highlighting
        query_words = set(query.lower().split())
        sentences = content.replace('\n', ' ').split('. ')
        
        scored_sentences = []
        for sentence in sentences:
            sentence_words = set(sentence.lower().split())
            overlap = len(query_words & sentence_words)
            if overlap > 0:
                scored_sentences.append((sentence, overlap))
        
        scored_sentences.sort(key=lambda x: x[1], reverse=True)
        
        highlights = []
        for sentence, _ in scored_sentences[:2]:
            if len(sentence) > max_length:
                sentence = sentence[:max_length] + "..."
            highlights.append(sentence)
        
        return highlights
    
    def get_context_for_query(self, query: str, top_k: int = 3) -> str:
        """
        Get formatted context for LLM augmentation.
        
        Args:
            query: User's query
            top_k: Number of documents to include
            
        Returns:
            Formatted context string
        """
        results = self.search(query, top_k)
        
        if not results:
            return ""
        
        context_parts = ["=== Relevant Ceph Documentation ===\n"]
        
        for i, result in enumerate(results, 1):
            doc = result.document
            context_parts.append(f"[{i}] {doc.title} ({doc.section})")
            context_parts.append(f"Source: {doc.source}")
            context_parts.append(f"Content: {doc.content}")
            context_parts.append("")
        
        return "\n".join(context_parts)
    
    def answer_question(self, query: str, llm_provider) -> Dict[str, Any]:
        """
        Answer a question using RAG.
        
        Args:
            query: User's question
            llm_provider: LLM provider for generation
            
        Returns:
            Answer with sources
        """
        # Retrieve relevant documents
        results = self.search(query, top_k=3)
        context = self.get_context_for_query(query, top_k=3)
        
        if not context:
            return {
                "answer": "I don't have specific documentation on this topic.",
                "sources": [],
                "confidence": 0.0
            }
        
        # Generate answer with LLM
        system_prompt = """You are a Ceph storage expert. Answer the user's question based on the 
provided documentation context. Be accurate and cite your sources. If the documentation 
doesn't fully answer the question, say so while providing what information you can."""
        
        user_prompt = f"""Context from Ceph documentation:
{context}

Question: {query}

Provide a clear, accurate answer based on the documentation above."""
        
        response = llm_provider.generate(user_prompt, system=system_prompt)
        
        return {
            "answer": response,
            "sources": [
                {"title": r.document.title, "section": r.document.section, "score": r.score}
                for r in results
            ],
            "confidence": results[0].score if results else 0.0
        }
    
    def index_documentation_directory(self):
        """Index all documentation files in the docs directory."""
        if not self.docs_directory.exists():
            logger.warning(f"Docs directory not found: {self.docs_directory}")
            return
        
        count = 0
        for file_path in self.docs_directory.rglob("*.md"):
            try:
                with open(file_path, 'r') as f:
                    content = f.read()
                
                # Extract title from first heading
                title = file_path.stem
                lines = content.split('\n')
                for line in lines:
                    if line.startswith('# '):
                        title = line[2:].strip()
                        break
                
                self.add_document(
                    content=content,
                    source=str(file_path),
                    title=title,
                    section=file_path.parent.name
                )
                count += 1
            except Exception as e:
                logger.error(f"Failed to index {file_path}: {e}")
        
        logger.info(f"Indexed {count} documentation files")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get RAG system statistics."""
        builtin = len([d for d in self.documents if d.startswith("builtin_")])
        indexed = len(self.documents) - builtin
        
        return {
            "total_documents": len(self.documents),
            "builtin_documents": builtin,
            "indexed_documents": indexed,
            "total_embeddings": len(self.embeddings)
        }
