#!/usr/bin/env python3
"""
Test data setup for benchmark evaluations.

Creates necessary test objects in RADOS pool and indexes them
for comprehensive benchmark testing.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# Test documents for benchmark evaluation
TEST_DOCUMENTS = {
    "test.txt": """This is a test file.
It contains sample text for testing the semantic search system.
The file includes information about testing methodologies and best practices.""",
    
    "readme.md": """# Project README

This is the README file for the semantic Ceph storage system.

## Overview
This system provides semantic search capabilities for RADOS objects.

## Features
- Natural language queries
- Vector embeddings
- Similarity search
- LLM-powered agent interface

## Installation
Follow the installation guide in the documentation.
""",
    
    "config.yaml": """# Configuration file
llm:
  model: llama3.2
  base_url: http://localhost:11434
  
ceph:
  pool_name: testpool
  conf_file: /etc/ceph/ceph.conf
  
embedding:
  model: all-MiniLM-L6-v2
  device: cpu
""",
    
    "test_config.yaml": """# Test configuration
database:
  host: localhost
  port: 5432
  name: testdb
  
logging:
  level: DEBUG
  file: test.log
""",
    
    "notes.txt": """Development notes:
- Implement caching for embeddings
- Add support for metadata filtering
- Optimize vector search performance
- Write comprehensive tests
""",
    
    "backup.txt": """Backup procedures:
1. Create snapshot of pool
2. Export to external storage
3. Verify backup integrity
4. Document backup location
""",
    
    "monitoring.yaml": """monitoring:
  enabled: true
  interval: 60
  metrics:
    - cpu_usage
    - memory_usage
    - disk_io
    - network_traffic
""",
    
    "network_config.txt": """Network Configuration:
Interface: eth0
IP: 192.168.1.100
Gateway: 192.168.1.1
DNS: 8.8.8.8

Firewall rules:
- Allow SSH (22)
- Allow HTTP (80)
- Allow HTTPS (443)
""",
    
    "performance.txt": """Performance Tuning Guide:

1. CPU Optimization
   - Enable CPU pinning
   - Adjust thread pool size
   
2. Memory Management
   - Configure cache sizes
   - Set memory limits
   
3. Storage I/O
   - Enable direct I/O
   - Optimize block sizes
""",
    
    "deployment.txt": """Deployment Checklist:
[ ] Update configuration files
[ ] Run database migrations
[ ] Build and test containers
[ ] Deploy to staging
[ ] Run integration tests
[ ] Deploy to production
[ ] Monitor deployment
""",
}


def setup_test_data(rados_client, indexer, force_recreate=False):
    """
    Create test documents in RADOS and index them.
    
    Args:
        rados_client: Connected RadosClient instance
        indexer: Indexer instance for indexing objects
        force_recreate: If True, recreate objects even if they exist
        
    Returns:
        Tuple of (created_count, indexed_count, errors)
    """
    logger.info("Setting up test data for benchmarks...")
    
    created_count = 0
    indexed_count = 0
    errors = []
    
    # Create test objects in RADOS
    for object_name, content in TEST_DOCUMENTS.items():
        try:
            # Check if object exists
            exists = False
            try:
                rados_client.read_object(object_name)
                exists = True
            except Exception:
                pass
            
            if exists and not force_recreate:
                logger.debug(f"Object {object_name} already exists, skipping")
            else:
                # Write object
                rados_client.write_object(
                    object_name=object_name,
                    data=content.encode('utf-8')
                )
                created_count += 1
                logger.info(f"Created test object: {object_name} ({len(content)} bytes)")
        
        except Exception as e:
            error_msg = f"Failed to create {object_name}: {e}"
            logger.error(error_msg)
            errors.append(error_msg)
            continue
    
    # Index all test objects
    logger.info("Indexing test objects...")
    try:
        indexed_count = indexer.index_pool()
        logger.info(f"Indexed {indexed_count} objects")
    except Exception as e:
        error_msg = f"Failed to index objects: {e}"
        logger.error(error_msg)
        errors.append(error_msg)
    
    logger.info(f"Test data setup complete: created={created_count}, indexed={indexed_count}, errors={len(errors)}")
    
    return created_count, indexed_count, errors


def cleanup_test_data(rados_client):
    """
    Remove test documents from RADOS.
    
    Args:
        rados_client: Connected RadosClient instance
        
    Returns:
        Tuple of (deleted_count, errors)
    """
    logger.info("Cleaning up test data...")
    
    deleted_count = 0
    errors = []
    
    for object_name in TEST_DOCUMENTS.keys():
        try:
            rados_client.delete_object(object_name)
            deleted_count += 1
            logger.info(f"Deleted test object: {object_name}")
        except Exception as e:
            # Ignore errors if object doesn't exist
            if "not found" not in str(e).lower():
                error_msg = f"Failed to delete {object_name}: {e}"
                logger.error(error_msg)
                errors.append(error_msg)
    
    logger.info(f"Test data cleanup complete: deleted={deleted_count}, errors={len(errors)}")
    
    return deleted_count, errors


def verify_test_data(rados_client, vector_store):
    """
    Verify that test data is properly set up.
    
    Args:
        rados_client: Connected RadosClient instance
        vector_store: VectorStore instance
        
    Returns:
        Dictionary with verification results
    """
    logger.info("Verifying test data setup...")
    
    results = {
        "rados_objects": [],
        "indexed_objects": [],
        "missing_from_rados": [],
        "missing_from_index": [],
    }
    
    # Check RADOS objects
    for object_name in TEST_DOCUMENTS.keys():
        try:
            rados_client.read_object(object_name)
            results["rados_objects"].append(object_name)
        except Exception:
            results["missing_from_rados"].append(object_name)
    
    # Check indexed objects
    try:
        all_indexed = vector_store.list_all()
        indexed_object_names = []
        for obj in all_indexed:
            meta = obj.get("metadata", {})
            name = meta.get("object_name", "")
            if name:
                indexed_object_names.append(name)
        test_object_names = set(TEST_DOCUMENTS.keys())
        indexed_test_objects = [obj for obj in indexed_object_names if obj in test_object_names]
        results["indexed_objects"] = indexed_test_objects
        results["missing_from_index"] = list(test_object_names - set(indexed_test_objects))
    except Exception as e:
        logger.error(f"Failed to verify indexed objects: {e}")
    
    # Summary
    results["ready"] = (
        len(results["missing_from_rados"]) == 0 and
        len(results["missing_from_index"]) == 0
    )
    
    logger.info(f"Verification complete: RADOS={len(results['rados_objects'])}/{len(TEST_DOCUMENTS)}, "
               f"Indexed={len(results['indexed_objects'])}/{len(TEST_DOCUMENTS)}, "
               f"Ready={results['ready']}")
    
    return results
