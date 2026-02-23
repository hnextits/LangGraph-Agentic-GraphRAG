# LangGraph-Agentic-Graph RAG

<div align="center">

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

English | [한국어](README/README_KO.md) | [中文](README/README_ZH.md)
</div> 


LangGraph-Agentic-Graph RAG is a vector–graph hybrid RAG platform powered by **LangGraph + SGLang**. The ingestion pipeline converts raw documents into Markdown chunks and graph metadata via LangGraph state machines with checkpoint persistence. During query time, a hop-based router with quality-gate backtracking selects among three retrieval paths—Vector, Weaviate GraphRAG, or Neo4j GraphDB—to generate answers.

<div align="center">
<img src="https://github.com/user-attachments/assets/f1ee3090-a1a2-4962-86d6-03f4347a93b3" width="512" height="768" ></img><br/>
</div> 

---

## Key Capabilities

- **LangGraph state machines**: ingestion, query reasoning, summarization, and mindmap generation all run on LangGraph `StateGraph` with `MemorySaver` checkpointing.
- **Checkpoint & backtracking**: every node transition is checkpointed; the quality gate and GoT snapshotting roll back to alternative retrieval paths or earlier expansions when quality is insufficient (up to 2 retries).
- **3-way retrieval routing**: hop ≤ 2 → Vector RAG (TextSearcher + Reranker), hop 3–5 → Weaviate Cross-Reference GraphQL traversal, hop ≥ 6 → Neo4j Deep Graph Traversal. Hop boundaries mirror the underlying data model: semantic-only questions stay on the TextDocument embedding index, entity/attribute hops leverage Weaviate cross-references, and schema-heavy relationship reasoning (≥ 6 hops) escalates to Neo4j Cypher traversals. Path 1 and Path 2 both live inside Weaviate: Path 1 favors fast semantic similarity on the late-chunked corpus, whereas Path 2 deliberately walks Cross-Reference neighborhoods to surface query-linked entities/events within Weaviate before escalating to Neo4j.
- **Observer LLM + GoT expansion**: an observer LLM scores each path result (0–1). Passing results trigger Graph-of-Thought branching/merging for deeper context.
- **SGLang inference**: generator, embedding, reranker, hop classifier, and the observer LLM all run on SGLang servers with lazy loading (`LazyModelManager` + `SGLangServerManager`).
  - **Lazy-loading**: servers auto-start on first request, idle timeout 60s with GPU memory release
  - **GPU allocation**: Generator (cuda:0, 30% VRAM), Embedding/Reranker/Refiner (cuda:1, shared)
  - **Chunk retry logic**: LLM metadata extraction auto-retries failed chunks with server restart (configurable via `GRAPH_EXTRACTOR_RETRY_ON_FAILURE`)
- **Automatic graph upsert**: OCR → LLM entity/event/relation extraction → simultaneous Weaviate + Neo4j ingestion.
- **Async job monitoring**: upload, OCR, and embedding progress tracked through task APIs.

---

## Architecture

```
┌──────────────┐    ┌─────────────────────────────┐
│ Input Layer  │ →  │ LangGraph Upload Pipeline   │ →  Markdown + *.graph.json
│ (PDF/IMG/…)  │    │ (MemorySaver checkpoint)    │
└──────────────┘    └─────────────────────────────┘
                                  │
┌──────────────┐    ┌─────────────────────────────┐
│ User Query   │ →  │ LangGraph RAG Workflow      │
└──────────────┘    │ (MemorySaver checkpoint)    │
                    └─────────────────────────────┘
                                  │
                    ┌─────────────┴──────────────┐
                    │   Hop Router (LLM+rule)    │
                    └─────────────┬──────────────┘
                                  │
     ┌────────────────────────────┼────────────────────────────┐
     │                            │                            │
 Path 1                      Path 2                       Path 3
 Vector RAG                  Weaviate Cross-Ref           Neo4j GraphDB
 TextSearcher+Reranker       GraphQL QueryReference       Deep Traversal
 (≤ 2 hop)                   (3–5 hop)                    (≥ 6 hop)
                                  │
                                  ▼
                 ┌──────────────────────────────────────────┐
                 │ Quality Gate + Observer LLM (0~1 score)  │
                 └────────────────┬─────────────────────────┘
                                  │
                        ┌─────────▼──────────────┐
                        │ GoT Thought Expander   │
                        │ Branch merge + pruning │
                        └─────────┬──────────────┘
                                  │
                           ┌──────▼──────┐
                           │ LLM Answer  │
                           └─────────────┘
```

### Workflow Graph (Query)

```
planner →  router →┬→ vector_retriever  ──→┐
                   ├→ crossref_retriever ─→├→ quality_gate →┬→ thought_expander → aggregator → END
                   └→ graphdb_retriever ──→┘                └→ router (backtrack)
```

---

## Input / Preprocessing Layer

Handled by `LangGraphUploadPipeline` (`langgraph_upload_pipeline.py`) with `MemorySaver` checkpointing across all nodes:

1. **Conversion & Layout**: `run_file_processor.py` handles PDF/Office/image/audio inputs → `Results/1.Converted_images` + `Results/2.LayoutDetection`.
2. **OCR & Markdown**: `run_ocr_processing()` with SGLang-powered OCRFlux produces per-page Markdown → `Results/4.OCR_results`.
3. **LLM Metadata Extraction**: `LLMMetadataExtractor` extracts entities/events/relations from Markdown → `Results/8.graph_metadata/*.graph.json`.
   - **Chunk size**: configurable via `GRAPH_EXTRACTOR_CHUNK_SIZE
   - **Timeout**: configurable via `GRAPH_EXTRACTOR_API_TIMEOUT
   - **Retry logic**: On timeout, SGLang generator server restarts and retries the same chunk once
   - **Keepalive**: Background thread touches server every 20s during processing
4. **Graph Upsert**:
   - `GraphSchemaManager` ensures Weaviate GraphEntity/GraphEvent/GraphRelation collections exist with cross-references (source/target/event)
   - `LegacyGraphIngestor` / `Neo4jManager` MERGEs nodes/relationships into Neo4j with deterministic UUIDs
5. **Late Chunking & Embedding**: `embedding_text.py` splits Markdown into chunks and uploads into the Weaviate TextDocument collection via `SharedEmbeddingModel` (Qwen3-Embedding-4B).

---

## Query / Reasoning Layer

Handled by `GraphReasoner` (`graph_reasoner.py`) with `MemorySaver` checkpointing and quality-gate backtracking:

1. **Hop Classifier** (`hop_classifier.py`): estimates query complexity (hop count) to determine retrieval path.
2. **Planner**: analyzes the query, sets `max_hops`, and initializes the search plan.
3. **Router**: selects Path 1/2/3 based on hop classification.
4. **Retrieval Nodes**:
   - **Path 1 – Vector RAG**: `rag_pipeline`'s TextSearcher + Reranker.
   - **Path 2 – Cross-Ref GraphRAG**: BM25 seed entities → Weaviate Cross-Reference `QueryReference` multi-hop traversal (source/target/event refs) to collect query-adjacent entities/events within Weaviate before escalating to Neo4j.
   - **Path 3 – Neo4j GraphDB**: deep traversal via `legacy_graph_client.py` Cypher templates for ≥ 6-hop schema-intensive reasoning or when Weaviate cross-references exhaust.
5. **Quality Gate + Observer LLM**: every path result is scored 0.0–1.0 by the observer LLM (Path 1 defaults to 1.0 when delegated). If the score falls below the configured quality threshold, the workflow re-enters the router with the next retrieval path in the fallback order (Vector → Cross-Ref → GraphDB) and repeats until either a path passes or the 2-retry limit is reached; after the limit it continues with the best-effort context and flags the degradation in `answer_notes`.
6. **GoT Thought Expander** (`GOT_MODE_ENABLED=true`): graph-shaped thought exploration with branching, scoring, and merging.
   - Each step fans out up to `GOT_BRANCH_FACTOR` candidate queries in parallel.
   - An observer LLM scores each branch (0.0–1.0) for relevance, coverage, and novelty.
   - Branches above `GOT_THOUGHT_SCORE_THRESHOLD` are merged via `GOT_MERGE_STRATEGY` (`top_k` / `weighted_union` / `vote`).
   - Low-quality edges are pruned by `GOT_EDGE_PRUNE_THRESHOLD` keyword-overlap scoring.
   - Consecutive all-branch failures trigger snapshot-based backtracking (state rollback to last successful merge).
7. **Aggregator**: builds context snippets from entities/events/relations for LLM generation.
8. **Generation** (`generator.py`): merges thought/path snippets with the original query to produce the answer; `refiner.py` / `evaluator.py` optionally post-process the response.

---

## Module Map

```
backend/
├── main.py                          # FastAPI server entry point
├── app.py                           # Application setup & middleware
├── config.py                        # Server-level configuration
│
├── api/                             # API layer
│   ├── routes.py                    # Main upload/file/session routes
│   ├── chat.py                      # POST /v1/chat endpoint
│   ├── ocr_routes.py                # OCR processing endpoints
│   └── pause_api.py                 # Task pause/resume API
│
├── notebooklm/                      # RAG core modules
│   ├── config.py                    # Model/path/graph configuration
│   ├── rag_pipeline.py              # LangGraph RAG workflow orchestrator
│   ├── graph_reasoner.py            # 3-Way retrieval + checkpoint + backtracking
│   ├── graph_schema.py              # Weaviate Entity/Event/Relation schema
│   ├── hop_classifier.py            # Query complexity estimator
│   ├── legacy_graph_client.py       # Neo4j Cypher traversal client
│   ├── legacy_graph_ingestor.py     # Neo4j upsert helper
│   ├── embedding_text.py            # Late chunking + Weaviate text indexing
│   ├── embedding_image.py           # Image embedding + Weaviate image indexing
│   ├── shared_embedding.py          # SGLang embedding/reranker client (singleton)
│   ├── generator.py                 # LLM answer generation
│   ├── refiner.py                   # Answer refinement
│   ├── evaluator.py                 # Answer quality evaluation
│   ├── router.py                    # Query type routing
│   ├── query_rewriter.py            # Query rewriting
│   ├── parallel_search.py           # Parallel text+image search
│   ├── weaviate_utils.py            # Weaviate client utilities
│   ├── rag_text/                    # Text search + reranker
│   └── rag_image/                   # Image search + reranker
│
├── nextits_data/                    # Data processing pipeline
│   └── pipe/
│       ├── langgraph_upload_pipeline.py  # LangGraph upload workflow (checkpointed)
│       ├── llm_metadata_extractor.py     # Entity/event/relation extraction
│       ├── neo4j_manager.py              # Neo4j upsert manager
│       ├── run_file_processor.py         # Convert/layout/OCR orchestrator
│       ├── pipeline_image.py             # Image pipeline
│       ├── pipeline_sound.py             # Audio pipeline
│       └── main_pipe/
│           ├── ocr_pipe/                 # SGLang-based OCRFlux engine
│           ├── udp_pdftopng_300dpi.py    # PDF → PNG conversion
│           └── udp_layoutdetection.py    # Layout detection
│
├── services/                        # Business logic services
│   ├── model_manager.py             # LazyModelManager (GPU lifecycle)
│   ├── ocr_vision_manager.py        # OCR engine management
│   └── rag_service.py               # RAG service orchestration
│
└── utils/
    ├── task_queue.py                # GPU task queue (async job management)
    └── helpers.py                   # Shared utility functions
```

---

## Data Pipeline

1. **File upload** (`POST /upload/files`)
   - `api/routes.py` stores files in per-session folders and enqueues `run_processing_pipeline` via `task_queue.py`.
2. **GPU task queue**
   - `task_queue.py` manages sequential GPU-bound tasks (convert → layout → OCR) with progress tracking.
3. **Text indexing** (`run_text_indexing` / `run_text_indexing_v2`)
   - Initializes `SharedEmbeddingModel` → runs `process_markdown_files` for Weaviate late-chunking indexing.
4. **Graph extraction & ingestion**
   - `LLMMetadataExtractor` produces `*.graph.json` → `GraphSchemaManager` upserts to Weaviate → `Neo4jManager` / `LegacyGraphIngestor` upserts to Neo4j.
5. **Storage state**
   - Weaviate: TextDocument + GraphEntity/Event/Relation collections.
   - Neo4j: Entity/Event nodes + relation edges with deterministic UUIDs and auto-created constraints.

---

## Query Processing Flow

1. `POST /v1/chat` → `rag_pipeline.retrieve()` is invoked.
2. `hop_classifier.py` estimates query complexity → determines `max_hops`.
3. `graph_reasoner.py` runs the LangGraph workflow:
   - **planner** → **router** → **retrieval node** (Path 1/2/3) → **quality_gate**
   - If quality < threshold → **backtrack** to router with alternative path (max 2 retries).
   - If GoT enabled → **thought_expander** with snapshot-based backtracking.
   - **aggregator** builds context snippets.
4. `generator.py` produces the answer from original query + context snippets.
5. (Optional) `refiner.py` polishes the answer; `evaluator.py` logs quality notes.
6. Response includes `plan`, `hops`, `notes`, `context_snippets`, `backtrack_count`, and `thought_steps` for debugging.

---

## Installation & Run

```bash
cd backend
pip install -r requirements.txt

# Environment variables (see .env.example)
export GRAPH_RAG_ENABLED=true
export LANGGRAPH_ENABLED=true
export GOT_MODE_ENABLED=true
export LEGACY_GRAPH_ENABLED=true
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=your_password

# LLM Models (customize based on your hardware)
export LLM_MODEL
export EMBEDDING_MODEL
export RERANKER_MODEL

# SGLang server endpoints
export SGLANG_GENERATOR_ENDPOINT=http://localhost:30000
export SGLANG_EMBEDDING_ENDPOINT=http://localhost:30001
export SGLANG_RERANKER_ENDPOINT=http://localhost:30002

# Graph extractor settings
export GRAPH_EXTRACTOR_API_TIMEOUT
export GRAPH_EXTRACTOR_CHUNK_SIZE
export GRAPH_EXTRACTOR_RETRY_ON_FAILURE=true

python main.py
# SGLang servers (generator/embedding/reranker) autostart on first request with lazy-loading.
```

To launch Neo4j locally:

```bash
docker run -d --name neo4j-dev \
  -p7474:7474 -p7687:7687 \
  -e NEO4J_AUTH=neo4j/your_password \
  -v neo4j-data:/data \
  neo4j:5
```

---

## Key Settings (`notebooklm/config.py`)

- **Graph RAG toggles**: `GRAPH_RAG_ENABLED`, `LANGGRAPH_ENABLED`, `GOT_MODE_ENABLED`, `GRAPH_MAX_HOPS`.
- **GoT tuning**: `GOT_BRANCH_FACTOR`, `GOT_MERGE_STRATEGY` (`top_k`/`weighted_union`/`vote`), `GOT_MERGE_TOP_K`, `GOT_THOUGHT_SCORE_THRESHOLD`, `GOT_EDGE_PRUNE_THRESHOLD`, `GOT_MAX_STEPS`, `GOT_MAX_CONSECUTIVE_FAILURES`, `GOT_OBSERVER_ENDPOINT`/`GOT_OBSERVER_MODEL`.
- **Neo4j**: `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `GRAPH_MAX_HOPS`.
- **Weaviate**: `WEAVIATE_HOST/PORT`, `WEAVIATE_TEXT_CLASS` (TextDocument), `WEAVIATE_VECTORIZER` (text2vec-model2vec).
- **SGLang models**: `LLM_MODEL`, `EMBEDDING_MODEL`, `RERANKER_MODEL`, `REFINER_MODEL`, `QUERY_REWRITER_MODEL`.
- **SGLang servers**: `SGLANG_GENERATOR_ENDPOINT`, `SGLANG_EMBEDDING_ENDPOINT`, `SGLANG_RERANKER_ENDPOINT`, `SGLANG_REFINER_ENDPOINT`, `SGLANG_QUERY_REWRITER_ENDPOINT`.
- **SGLang lifecycle**: `SGLANG_IDLE_TIMEOUT` (60s), `SGLANG_KEEPALIVE_INTERVAL` (20s).
- **Graph extractor**: `GRAPH_EXTRACTOR_API_TIMEOUT` (60s), `GRAPH_EXTRACTOR_CHUNK_SIZE` (800), `GRAPH_EXTRACTOR_RETRY_ON_FAILURE` (true).
- **Session directories**: `DATA_ROOT/Results`, `sessions/<id>` layout.

---

## API Highlights

| Endpoint | Description |
|---|---|
| `POST /upload/files` | Triggers the LangGraph upload pipeline |
| `POST /v1/chat` | Runs 3-way RAG with checkpoint/backtracking |
| `GET /api/v1/tasks/{task_id}` | Monitors queued upload/OCR tasks |
| `GET /files` | Lists session artifacts |
| `POST /pause` | Pauses/resumes background tasks |

---

## Logging & Operations

- `sglang_embedding_server.log`, `sglang_reranker_server.log` – SGLang model server health.
- `Results/8.graph_metadata/*.graph.json` – archive of LLM extraction results.
- `LegacyGraphIngestor` auto-creates constraints on first run; no manual setup required.
- `SGLangServerManager` releases GPU memory after 60 seconds of idling (configurable via `SGLANG_IDLE_TIMEOUT`).
- All LangGraph workflows log checkpoint IDs and backtrack counts for traceability.
- **SGLang cold start**: lazy loading means the first `/v1/chat` (or hop-classifier) request must warm each SGLang server, which can take 20–60s VRAM load time; issue a warm-up request or keep-alive cron to avoid client timeouts.
- **Chunk retry mechanism**: If LLM metadata extraction times out (default 60s), the generator server is automatically restarted and the same chunk is retried once. This prevents hanging on problematic chunks while maintaining extraction quality.
- **Volatile checkpoints**: `MemorySaver` stores graph snapshots in-process, so any FastAPI restart drops in-flight state until the planned migration to `SqliteSaver`/`PostgresSaver` lands.
- **Weaviate v4 API**: Uses `weaviate.connect_to_custom()` with gRPC support (port 50051).

---

## Roadmap

1. ~~**GoT (Graph of Thought)**~~
   - `thought_expander` now performs graph-shaped exploration: each step fans out `GOT_BRANCH_FACTOR` branches, an observer LLM scores each branch, and the best results are merged via `GOT_MERGE_STRATEGY`. Low-quality edges are pruned, and consecutive failures trigger snapshot-based backtracking.
2. **Advanced hop classifier**
   - Augment with query metadata (token length, entity counts) for a hybrid router.
3. **Multi-graph retrieval optimization**
   - Improve context filtering/dedup for 3–5 hop Weaviate traversals and add Cypher templates for ≥ 6 hop Neo4j exploration.
4. **LangGraph workflow observability**
   - Emit per-node latency/error metrics and integrate retry policies inside `GraphReasoner` and `LegacyGraphClient`.
5. **Persistent checkpointer**
   - Migrate from `MemorySaver` to `SqliteSaver` / `PostgresSaver` for cross-session state recovery.

---

## Contribution & Contact

Issues and PRs are welcome. For questions or concerns, please open an issue on GitHub.

---

## License

This project is dual-licensed under:
- **MIT License** - see the [LICENSE](LICENSE) file for details
- **Apache License 2.0** - see the [LICENSE-APACHE](LICENSE-APACHE) file for details

You may choose either license to govern your use of this software.

---

## Citation

If you use this project in your research, please cite the following:

### SGLang
```bibtex
@misc{zheng2023sglang,
  title={SGLang: Efficient Execution of Structured Language Model Programs},
  author={Lianmin Zheng and Liangsheng Yin and Zhiqiang Xie and Jeff Huang and Chuyue Sun and Cody Hao Yu and Shiyi Cao and Christos Kozyrakis and Ion Stoica and Joseph E. Gonzalez and Clark Barrett and Ying Sheng},
  year={2023},
  url={https://github.com/sgl-project/sglang}
}
```

### LangGraph
```bibtex
@software{langgraph2024,
  title={LangGraph: A Framework for Building Stateful Multi-Actor Applications},
  author={LangChain AI},
  year={2024},
  url={https://github.com/langchain-ai/langgraph}
}
```

### Weaviate
```bibtex
@software{weaviate2024,
  title={Weaviate: An Open-Source Vector Database},
  author={Weaviate B.V.},
  year={2024},
  url={https://github.com/weaviate/weaviate}
}
```

### Neo4j
```bibtex
@software{neo4j2024,
  title={Neo4j: The Graph Database Platform},
  author={Neo4j, Inc.},
  year={2024},
  url={https://github.com/neo4j/neo4j}
}
```

### OCRFlux
```bibtex
@software{ocrflux2024,
  title={OCRFlux: Vision-Language Model for OCR},
  author={ChatDOC},
  year={2024},
  url={https://huggingface.co/ChatDOC/OCRFlux-3B}
}
```