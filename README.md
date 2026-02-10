# LangGraph-Graph RAG Backend Overview

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

LangGraph-Graph RAG (Backend) is a vector–graph hybrid RAG platform powered by **LangGraph + SGLang**. Ingestion is handled by the LangGraph Upload pipeline that converts raw documents into Markdown chunks and graph metadata. During query time, a hop-based router selects among Vector Retrieval, Weaviate GraphRAG, or the legacy GraphDB (Neo4j) path to generate answers.

<div align="center">
<img src="https://github.com/user-attachments/assets/2c81abe6-8a42-4d28-a9c8-a3cf6aa0d3c6" width="512" height="768" ></img><br/>
</div> 

---

## Key Capabilities

- **LangGraph-driven pipeline**: both ingestion and query reasoning run on LangGraph state machines.
- **3-way retrieval**: hop ≤ 2 → Weaviate vector search, hop 3–5 → Weaviate GraphRAG, hop ≥ 6 → Neo4j GraphDB.
- **LLM router**: a small LLM hop classifier plus heuristics estimate reasoning depth.
- **Always-on SGLang servers**: generator/embedding/reranker/summarizer services stay warm on dedicated GPUs via LazyModelManager.
- **Automatic graph upsert**: OCR → LLM extraction results are ingested into Weaviate and Neo4j simultaneously.
- **Async job monitoring**: upload/OCR/embedding progress is tracked through task APIs.

---

## Backend Architecture

```
┌──────────────┐    ┌────────────────────────┐
│ Input Layer  │ → │ LangGraph Upload Flow  │ → Markdown + Graph JSON
└──────────────┘    └────────────────────────┘
                              │
┌──────────────┐    ┌────────────────────────┐    ┌───────────────────┐
│ User Query   │ → │ LangGraph RAG Workflow │ → │ SGLang Generation │
└──────────────┘    └────────────────────────┘    └───────────────────┘
                              │
                 ┌────────────┴────────────┐
                 │ 3-Way Retrieval Router │
                 └────────────┬────────────┘
                              │
      ┌───────────────────────┼────────────────────────┐
      │                       │                        │
  Path 1                 Path 2                   Path 3
  Vector ≤2 hop          Weaviate GraphRAG        Neo4j GraphDB ≥6 hop
```

### Input / Preprocessing Layer (LangGraphUploadPipeline)
1. **Conversion & Layout**: `run_file_processor.py` handles PDF/Office/image/audio inputs and writes `Results/1.Converted_images`.
2. **OCR & Markdown**: `run_ocr_processing()` + vLLM-powered OCR Flux produce per-page Markdown.
3. **LLM Metadata Extraction**: `LLMMetadataExtractor` chunks Markdown and stores entity/event/relation JSON files (`*.graph.json`).
4. **Graph Upsert**:
   - `GraphSchemaManager` ensures Weaviate Entity/Event/Relation collections exist, then upserts objects.
   - `LegacyGraphIngestor` MERGEs nodes/relationships into Neo4j with constraints.
5. **Late Chunking & Embedding**: `embedding_text.py` uploads Markdown chunks into the Weaviate TextDocument collection.

### Query / Reasoning Layer (RAGPipeline)
1. **Hop Classifier** (`hop_classifier.py`): a small LLM estimates query complexity.
2. **LangGraph Workflow** (`rag_pipeline.py`): manages the `planner → router → retrieval node → generation → finalizer` state transitions.
3. **Retrieval Paths**:
   - **Path 1: Vector RAG** – `embedding_text.text_search` + `text_reranker`.
   - **Path 2: Weaviate GraphReasoner** – `graph_reasoner.py` expands over LangGraph subgraphs and emits context snippets.
   - **Path 3: Legacy GraphDB** – `legacy_graph_client.py` executes Cypher templates against Neo4j.
4. **Generation** (`generator.py`): the SGLang LLM answers with original query + retrieved context, optionally refined by `refiner.py`/`evaluator.py`.

### Module Map

```
backend/
├── api/               # FastAPI routes and background tasks
├── notebooklm/
│   ├── rag_pipeline.py        # LangGraph RAG workflow
│   ├── graph_reasoner.py      # Weaviate graph expansion
│   ├── legacy_graph_client.py # Neo4j traversal client
│   ├── legacy_graph_ingestor.py # Neo4j upsert helper
│   ├── embedding_text.py / embedding_image.py
│   ├── shared_embedding.py    # SGLang embedding/reranker client
│   ├── generator.py / refiner.py / evaluator.py
│   └── config.py              # model/path/graph configuration
└── nextits_data/
    └── pipe/
        ├── langgraph_upload_pipeline.py
        ├── run_file_processor.py (convert/layout/OCR)
        └── ocr_pipe/ …
```

---

## Data Pipeline Summary

1. **File upload (`POST /upload/files`)**
   - `api/routes.py` stores files in per-session folders and enqueues `run_processing_pipeline`.
2. **GPU task queue**
   - `run_file_processor.py --stage convert/layout/ocr` executes sequentially.
3. **LangGraph upload workflow**
   - Collect OCR outputs → run `LLMMetadataExtractor` → upsert via `GraphSchemaManager` + `LegacyGraphIngestor` → late chunking with `embedding_text`.
4. **Weaviate & Neo4j state**
   - Weaviate maintains TextDocument + GraphEntity/Event/Relation collections.
   - Neo4j MERGEs Entity/Event nodes and relation edges based on deterministic UUIDs.

---

## Query Processing Flow

1. `POST /v1/chat` → `rag_pipeline.retrieve()` is invoked.
2. The router selects Path 1/2/3 based on hop classification.
3. Each path pushes context snippets into `state.context_snippets`.
4. `generator.py` produces the answer from the original query + context.
5. (Optional) `refiner.py` polishes the answer and `evaluator.py` logs quality notes.
6. Responses include plan/hops/notes/context_snippets for debugging.

---

## Installation & Run (Backend)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Environment variables (.env example)
export GRAPH_RAG_ENABLED=true
export LEGACY_GRAPH_ENABLED=true
export LEGACY_GRAPH_URI=bolt://localhost:7687
export LEGACY_GRAPH_USER=neo4j
export LEGACY_GRAPH_PASSWORD=your_password

python main.py
# SGLang embedding/reranker servers autostart on first request.
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

## Key Settings (`config.py`)

- **Models**: `EMBEDDING_MODEL`, `LLM_MODEL`, `HOP_CLASSIFIER_MODEL`, etc.
- **Graph RAG toggles**: `GRAPH_RAG_ENABLED`, `LANGGRAPH_ENABLED`, `GOT_MODE_ENABLED`, `GRAPH_MAX_HOPS`.
- **Legacy graph**: `LEGACY_GRAPH_ENABLED`, `LEGACY_GRAPH_URI`, `LEGACY_GRAPH_LABELS`, `LEGACY_GRAPH_MAX_PATHS`.
- **Weaviate**: `WEAVIATE_HOST/PORT`, `WEAVIATE_TEXT_CLASS`, `WEAVIATE_VECTORIZER`.
- **Session directories**: `DATA_ROOT/Results`, `sessions/<id>` layout.

---

## API Highlights

- `POST /upload/files` – triggers the LangGraph upload pipeline.
- `POST /v1/chat` – runs 3-way RAG and returns plan/notes/context.
- `GET /task_status/{task_id}` – monitors queued upload tasks.
- `GET /files`, `GET /files/{filename}` – inspects session artifacts.

---

## Logging & Operations

- `sglang_embedding_server.log`, `sglang_reranker_server.log` – model server health.
- `Results/graph_metadata/*.graph.json` – archive of LLM extraction results.
- `LegacyGraphIngestor` auto-creates constraints on first run; no manual setup required.
- LazyModelManager releases GPU memory after ~20 seconds of idling.

---

## Roadmap

1. **GoT (Graph of Thought)**
   - Enable `GOT_MODE_ENABLED` and branch the LangGraph flow to persist step-by-step reasoning states.
2. **Advanced hop classifier**
   - Tune thresholds/features of the small LLM classifier and augment with query metadata (token length, entity counts) for a hybrid router.
3. **Multi-graph retrieval optimization**
   - Improve context filtering/dedup for 3–5 hop Weaviate traversals and add Cypher templates for ≥6 hop Neo4j exploration.
4. **LangGraph workflow observability**
   - Emit per-node latency/error metrics to Prometheus and integrate retry policies inside GraphReasoner and LegacyGraphClient.

---

## Contribution & Contact

- Issues and PRs are welcome—feel free to propose backend-focused improvements. For any questions or concerns, please reach out to jeongnext@hnextits.com.

---

## 📄 License

This project is dual-licensed under:
- **MIT License** - see the [LICENSE](LICENSE) file for details
- **Apache License 2.0** - see the [LICENSE-APACHE](LICENSE-APACHE) file for details

You may choose either license to govern your use of this software.

---

## 🎓 Citation

If you use this project in your research, please cite the following papers and projects:

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
