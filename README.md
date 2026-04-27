# Autonomous AI Agent for Ceph Cluster Management

An LLM-powered autonomous agent for managing Ceph storage clusters through natural language. Combines semantic object storage with ReAct-based reasoning, automated runbooks, anomaly detection, and safe cluster management actions.

## 🎯 Overview

Autonomous AI Agent for Ceph Cluster Management that manages Ceph RADOS clusters using multi-step reasoning and tool use. It goes beyond simple intent classification by implementing a **ReAct (Reasoning + Acting) loop** that can decompose complex management tasks, execute multi-step plans, and proactively detect cluster anomalies.

Key capabilities:

- **🧠 ReAct Reasoning Loop**: Multi-step autonomous reasoning with tool use (Thought → Action → Observation cycles)
- **🔧 Cluster Management Actions**: Safe execution of OSD, pool, PG, and configuration operations with risk-based approval gates
- **📋 Automated Runbooks**: Pre-defined remediation procedures for common failure scenarios (OSD recovery, PG repair, rebalancing)
- **🔍 Anomaly Detection**: Proactive rule-based monitoring with health scoring and automated remediation suggestions
- **📐 Task Planning**: LLM-powered decomposition of complex operations into dependency-ordered steps
<!-- - **📚 RAG-Augmented Responses**: Retrieval-augmented generation from Ceph documentation -->
- **🛡️ Safety Framework**: Risk classification, dry-run mode, rate limiting, and audit logging for all destructive operations

## 🆕 Agent Capabilities

```bash
# Interactive chat mode — the agent reasons autonomously
./run.sh chat

# Example interactions:
You: One of my OSDs is down, can you investigate and fix it?
You: Plan a capacity expansion — we're running low on space
You: Run the performance investigation runbook
You: What anomalies do you see in the cluster right now?
You: Create a new pool called analytics with 128 PGs

# One-shot commands
./run.sh execute "check cluster health and suggest fixes"
./run.sh execute "rebalance the cluster"
```

### Agent Modes

| Mode | Trigger | Description |
|------|---------|-------------|
| **ReAct Loop** | Complex queries (investigate, plan, fix, troubleshoot) | Multi-step autonomous reasoning with tool calls |
| **Simple Intent** | Direct commands (search, create, delete) | Single-step intent classification + execution |

### Management Actions

The agent can perform cluster management operations with built-in safety:

- **OSD Management**: Mark OSDs in/out, reweight, restart
- **Pool Management**: Create, delete, configure pools
- **PG Operations**: Repair, deep-scrub placement groups
- **Cluster Flags**: Set/unset noout, norebalance, norecover, etc.
- **Configuration**: Get/set Ceph daemon configuration

All destructive actions pass through the **ActionEngine** which enforces:
- Risk classification (LOW → CRITICAL)
- Approval gates (auto-approve only low-risk by default)
- Rate limiting (max 20 actions per session)
- Dry-run mode for testing
- Full audit logging

### Anomaly Detection

Proactive monitoring with configurable thresholds:

- OSD utilization (warn: 75%, critical: 85%)
- Cluster capacity (warn: 70%, critical: 80%)
- PG distribution per OSD (30–300 range)
- Near-full prediction (< 30 days to full)


```

### Components

**Agent Layer** (autonomous reasoning):
- `agent_loop.py`: ReAct reasoning loop — Thought/Action/Observation cycles with LLM
- `action_engine.py`: Safety-checked execution with risk classification, approval gates, audit log
- `planner.py`: LLM-powered task decomposition with dependency tracking
- `runbooks.py`: Automated multi-step remediation procedures
- `anomaly_detector.py`: Rule-based anomaly detection with health scoring
- `tool_registry.py`: 35+ tool definitions for LLM function calling

**Core Layer** (cluster operations):
- `cluster_manager.py`: Read + write operations for Ceph cluster management
- `rados_client.py`: Interface to Ceph RADOS for object operations
- `embedding_generator.py`: Vector embeddings using sentence-transformers or OpenAI
- `content_processor.py`: Text extraction and preprocessing


## 🚀 Installation

### Prerequisites

1. **Ceph Cluster**: A running Ceph cluster with RADOS access
2. **Python**: Python 3.8+
3. **System Dependencies**:
   ```bash
   sudo apt-get update
   sudo apt-get install -y python3-rados python3-dev libmagic1
   ```

### Setup

1. **Clone and navigate**:
   ```bash
   cd /path/to/semantic-ceph-llm
   ```

2. **Install system dependencies**:
   ```bash
   sudo apt-get update
   sudo apt-get install -y python3-rados python3-venv python3-dev libmagic1 ceph-common
   ```

3. **Create virtual environment**:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

4. **Install Python dependencies**:
   ```bash
   # Create a requirements file without rados (it's system-wide)
   grep -v "^rados" requirements.txt > requirements_venv.txt
   pip install -r requirements_venv.txt
   
   # Link the system rados module to the virtual environment
   ln -s /usr/lib/python3/dist-packages/rados*.so venv/lib/python3.*/site-packages/
   ```

5. **Configure**:
   Edit `config.yaml` to match your setup:
   ```yaml
   ceph:
     config_file: /etc/ceph/ceph.conf
     pool_name: cephfs.cephfs.data  # Your pool name
   ```

6. **Verify Ceph access**:
   ```bash
   sudo ceph -s
   sudo ceph osd pool ls
   ```

## 📖 Usage

### Running Commands

Since Ceph keyring files require root permissions, you need to run commands with sudo while using the virtual environment's Python:

```bash
# Option 1: Use the convenience script
./run.sh index

# Option 2: Manually activate and run with sudo
source venv/bin/activate
sudo venv/bin/python cli.py index
```

### Research Questions

1. **Agent Effectiveness for Cluster Management**:
   - Can LLM-based agents autonomously diagnose and remediate storage cluster issues?
   - How does ReAct-style multi-step reasoning compare to single-step intent classification?
   - What is the impact of safety frameworks on agent utility vs. risk?

2. **Semantic Search over Object Storage**:
   - Effectiveness of embedding-based search vs. metadata search on RADOS objects
   - Precision/recall across different embedding models
   - Integration overhead for semantic indexing in production clusters

3. **Proactive Monitoring with LLMs**:
   - Can rule-based anomaly detection combined with LLM reasoning provide actionable insights?
   - How effective are automated runbooks vs. manual remediation?

4. **Safety and Trust in Autonomous Systems**:
   - Risk classification accuracy for cluster management actions
   - Impact of approval gates on operator trust and adoption
   - Audit logging completeness for compliance


### Extensibility

Easy extension points for research:

1. **Custom Embedding Models**:
   ```python
   # In embedding_generator.py
   class CustomEmbeddingGenerator(EmbeddingGenerator):
       def encode(self, texts):
           # Your custom model
           pass
   ```

2. **LLM Integration**:
   ```python
   # Add to indexer.py
   def generate_summary(text):
       # Call GPT-4, Llama, etc.
       return summary
   ```

3. **Re-ranking Algorithms**:
   ```python
   # In searcher.py
   def rerank_results(query, results):
       # Custom re-ranking logic
       return reranked_results
   ```

## 🔧 Configuration

### Embedding Models

**Local Models** (sentence-transformers):
- `all-MiniLM-L6-v2`: Fast, 384 dims (default)
- `all-mpnet-base-v2`: Better quality, 768 dims
- `paraphrase-multilingual-MiniLM-L12-v2`: Multilingual support

**Cloud Models** (future):
- OpenAI `text-embedding-3-small`: 1536 dims
- OpenAI `text-embedding-3-large`: 3072 dims

Edit `config.yaml`:
```yaml
embedding:
  provider: sentence-transformers
  model: all-MiniLM-L6-v2
  device: cpu  # or cuda for GPU
```


## 🔐 Security

**Important**: This system requires root/sudo access to read Ceph keyrings. For production:

1. Create a dedicated Ceph client with limited permissions:
   ```bash
   ceph auth get-or-create client.semantic mon 'allow r' osd 'allow r pool=your-pool'
   ```

2. Update `config.yaml`:
   ```yaml
   ceph:
     client_name: client.semantic
   ```

3. Set appropriate permissions:
   ```bash
   sudo chown semantic-user:semantic-user /etc/ceph/ceph.client.semantic.keyring
   sudo chmod 600 /etc/ceph/ceph.client.semantic.keyring
   ```

## 🤝 Contributing

Research contributions welcome! Areas of interest:

- Novel embedding models for file content
- LLM-based metadata extraction
- Advanced re-ranking algorithms
- Multi-modal embeddings (code + docs)
- Distributed indexing for large clusters

## 📝 Citation

If you use this work in academic research, please cite:

```bibtex
@inproceedings{cephsem2026,
  title     = {CephSem: An Autonomous LLM Agent for Semantic Ceph Cluster Management},
  author    = {Vladislav Esaulov},
  booktitle = {CHEOPS Workshop at EuroSys},
  year      = {2026},
  note      = {Research prototype — autonomous agent for distributed storage management}
}
```

## 📚 References

- **LSFS**: LLM-based Semantic File System concepts
- **Ceph**: https://docs.ceph.com/
- **Sentence Transformers**: https://www.sbert.net/
- **ChromaDB**: https://docs.trychroma.com/

## 🐛 Troubleshooting

### Common Issues

**1. Permission Denied (RADOS)**:
```bash
# Run with sudo
sudo python3 cli.py command

# Or fix keyring permissions
sudo chown $USER /etc/ceph/ceph.client.admin.keyring
```

**2. Module Not Found**:
```bash
# Install dependencies
sudo pip3 install -r requirements.txt
```

**3. CUDA Out of Memory**:
```yaml
# In config.yaml, switch to CPU
embedding:
  device: cpu
```

**4. Slow Indexing**:
```yaml
# Reduce file size limit
indexing:
  max_file_size_mb: 10
  
# Use GPU if available
embedding:
  device: cuda
  batch_size: 64
```

## 📄 License

MIT License - See LICENSE file

## 🎓 Academic Context

This project is a research platform for exploring **autonomous AI agents in distributed storage systems**:

- LLM-driven cluster management and remediation
- ReAct reasoning for multi-step system administration tasks
- Safety frameworks for autonomous infrastructure agents
- Semantic search integration with object storage
- Proactive anomaly detection with automated response

Suitable for:
- Master's/PhD research on AI for systems
- Storage systems and cluster management papers
- Human-agent interaction studies
- Safety and trust in autonomous infrastructure
- CHEOPS, EuroSys, SOSP, OSDI, ATC venues

---

**Note**: This is a research prototype. For production use, additional hardening, security audits, and performance optimization are recommended.
