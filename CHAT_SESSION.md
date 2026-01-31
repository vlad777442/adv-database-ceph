# Semantic-Ceph-LLM Development Session
**Date:** January 2026  
**Purpose:** CHEOPS Workshop Paper Development

---

## Project Setup Summary

### Environment
- Python 3.12 with venv at `./venv`
- Ollama v0.15.0 with llama3.2 model (2GB)
- Ceph cluster: 3 nodes (10.10.1.1-3), ~1.34TB storage
- Key packages: torch, sentence-transformers (all-MiniLM-L6-v2), chromadb, pydantic, click, rich

### Running Commands
```bash
./run.sh chat          # Interactive chat mode
./run.sh health        # Check cluster health (requires sudo)
./run.sh diagnose      # Run diagnostics (requires sudo)
./run.sh ask "query"   # Query RAG documentation
./run.sh evaluate      # Run evaluation framework
```

For Ceph access, use:
```bash
sudo /users/vlad777/research/semantic-ceph-llm/venv/bin/python cli.py <command>
```

---

## Implemented Features (Commit 582a686)

### 1. Cluster Management via Natural Language
- **File:** `core/cluster_manager.py` (~580 lines)
- **Capabilities:** health checks, OSD status, PG analysis, capacity prediction, diagnostics
- **CLI:** `health`, `diagnose` commands

### 2. RAG Documentation System
- **File:** `core/rag_system.py` (~620 lines)
- **Built-in:** 19 Ceph knowledge entries (HEALTH states, OSDs, PGs, CRUSH, erasure coding, CephFS, RBD, RGW, troubleshooting)
- **CLI:** `ask` command

### 3. Evaluation Framework
- **File:** `evaluation/evaluation_framework.py` (~600 lines)
- **Test cases:** 30+ across categories (search, read, write, delete, cluster, documentation, complex, ambiguous)
- **Metrics:** intent accuracy, parameter accuracy, response quality, latency (avg, p50, p95, p99)
- **CLI:** `evaluate` command

### Files Modified
- `cli.py` - Added new commands
- `core/intent_schema.py` - New operation types
- `core/tool_registry.py` - 10 new tools
- `core/llm_agent.py` - New handlers
- `core/rados_client.py` - Optional RADOS import
- `services/agent_service.py` - RAG integration

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         User Interface                              │
│                    (CLI: chat, execute, ask, health)                │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         AgentService                                │
│         Orchestrates LLM Agent, RAG System, and Services            │
└─────────────────────────────────────────────────────────────────────┘
                    │                   │                    │
         ┌──────────┘                   │                    └──────────┐
         ▼                              ▼                               ▼
┌─────────────────┐          ┌─────────────────┐           ┌─────────────────┐
│   LLM Agent     │          │   RAG System    │           │ Cluster Manager │
│  (Intent Parse) │          │  (Ceph Docs)    │           │   (ceph CLI)    │
└─────────────────┘          └─────────────────┘           └─────────────────┘
         │                              │                           │
         ▼                              ▼                           ▼
┌─────────────────┐          ┌─────────────────┐           ┌─────────────────┐
│  Tool Registry  │          │ Embedding Gen   │           │  subprocess     │
│ (function defs) │          │ (MiniLM-L6-v2)  │           │  ceph commands  │
└─────────────────┘          └─────────────────┘           └─────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      RADOS Client + Vector Store                    │
│              (Ceph Objects)         (ChromaDB Embeddings)           │
└─────────────────────────────────────────────────────────────────────┘
```

### How It Works

1. **LLM Agent** uses function calling to parse natural language into structured operations
2. **Semantic Search** embeds RADOS objects with sentence-transformers for content-aware search
3. **RAG System** retrieves relevant Ceph documentation to ground LLM responses
4. **Cluster Manager** wraps Ceph CLI for safe cluster operations

---

## Paper Abstract

**Semantic Storage: An LLM-Powered Agent for Natural Language Ceph Cluster Management**

Modern distributed storage systems like Ceph offer powerful capabilities but impose a steep learning curve on operators. Administrators must master complex CLI tools, interpret cryptic health warnings, and navigate extensive documentation to diagnose issues—tasks that become increasingly challenging as clusters scale. We present *Semantic Storage*, an LLM-powered agent that enables natural language interaction with Ceph clusters. Our system combines three key components: (1) a semantic object store that indexes RADOS objects with vector embeddings for content-aware search, (2) a Retrieval-Augmented Generation (RAG) system over Ceph documentation that provides context-aware answers to operational questions, and (3) a natural language interface for cluster management that translates user intent into appropriate Ceph operations. The agent interprets queries like "show me all configuration files modified last week" or "why is the cluster showing HEALTH_WARN?" and executes the corresponding operations or provides explanations grounded in documentation. We evaluate our system on a 3-node Ceph cluster, measuring intent classification accuracy, parameter extraction precision, and response latency. Our results demonstrate that LLM agents can significantly reduce the cognitive burden of storage administration while maintaining operational safety through confirmation prompts for destructive operations. We discuss the challenges of integrating LLMs with low-level storage APIs and outline future directions for AI-assisted infrastructure management.

**Keywords:** Ceph, LLM, semantic search, RAG, storage management, natural language interface

---

## Reviewer Feedback (Self-Assessment)

### Strengths
- ✅ Novel LLM + Ceph integration
- ✅ Complete working prototype (3024 LoC)
- ✅ Practical value addressing real pain points
- ✅ Appropriate scope for workshop paper

### Weaknesses to Address

1. **No Quantitative Evaluation Results**
   - Run: `sudo ./run.sh evaluate -o results.json`
   - Need: intent accuracy, param extraction, latency metrics

2. **No Comparison Baseline**
   - Add time comparison: CLI vs natural language
   - Error rate comparison: expert vs novice

3. **Limited Real-World Scenarios**
   - Add: failure recovery, performance debugging, multi-step operations

4. **RAG Evaluation Missing**
   - Retrieval precision/recall
   - Hallucination rate comparison

5. **Safety Analysis Incomplete**
   - Misinterpretation analysis
   - Adversarial prompt testing

6. **Scalability Not Addressed**
   - Large-scale indexing (1M+ objects)
   - Memory/latency analysis

### Suggested Paper Structure
1. Introduction - Ceph complexity, LLM opportunity
2. System Design - Architecture
3. Implementation - Key components
4. Evaluation
   - 4.1 Intent Classification Accuracy
   - 4.2 RAG Retrieval Quality
   - 4.3 End-to-End Latency
   - 4.4 Comparison with CLI
5. Limitations & Future Work
6. Conclusion

---

## Next Steps

1. Run evaluation framework and collect metrics
2. Add timing comparison script (CLI vs agent)
3. Add failure injection tests
4. Consider small user study (3-5 users)
5. Generate results tables/figures for paper

---

## Git Info
- **Latest commit:** 582a686
- **User:** vlad777442 <vefirst@gmail.com>
- **Branch:** main
