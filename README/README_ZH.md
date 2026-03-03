# LangGraph-Agentic-Graph RAG

<div align="center">

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

[English](../README.md) | [한국어](README_KO.md) | 中文
</div>

LangGraph-Graph RAG 是一个基于 **LangGraph + SGLang** 的向量–图混合 RAG 平台。
数据摄取管道通过带有检查点持久化的 LangGraph 状态机将原始文档转换为 Markdown 块和图元数据。在查询阶段，带有质量门控回溯的跳数路由器从 Vector、Weaviate GraphRAG 或 Neo4j GraphDB 三条检索路径中选择一条来生成答案。

<div align="center">
<img src="https://github.com/user-attachments/assets/441a4a4b-d239-45c1-b385-80ddd95f31e6" width="512" height="768" ></img><br/>
</div>

---

## 核心功能

- **LangGraph 状态机**：数据摄取、查询推理、摘要生成和思维导图生成均运行在带有 `MemorySaver` 检查点的 LangGraph `StateGraph` 上。
- **检查点与回溯**：每个节点转换都会被检查点；当质量不足时，质量门和 GoT 快照会回滚到替代检索路径或更早的扩展（可通过 `MAX_BACKTRACK_COUNT` 配置）。
- **3 路检索路由**：根据查询复杂度（hop 数）路由到 Vector RAG、Weaviate Cross-Reference GraphQL 或 Neo4j Deep Graph Traversal（阈值可通过 `GRAPH_MAX_HOPS` 配置）。跳数边界映射了底层数据模型：纯语义问题保留在 TextDocument 嵌入索引，实体/属性推理利用 Weaviate 交叉引用，≥ 6 跳的模式化关系推理会升级到 Neo4j Cypher 查询。Path 1 与 Path 2 均运行在 Weaviate 内：Path 1 偏向于在 late-chunk 语料上执行快速语义相似度，Path 2 则显式遍历 Cross-Reference 邻域，在不进入 Neo4j 的情况下先挖掘与查询关联的实体/事件。
- **观察者 LLM + GoT 扩展**：观察者 LLM 对每个路径结果评分（0–1）。超过 `QUALITY_GATE_THRESHOLD` 的结果会触发 Graph-of-Thought 分支/合并以获取更深层次的上下文。
- **SGLang 推理**：生成器、嵌入、重排序器、跳数分类器和观察者 LLM 均运行在带有延迟加载（`LazyModelManager` + `SGLangServerManager`）的 SGLang 服务器上。
  - **延迟加载**：服务器在首次请求时自动启动，空闲超时可通过 `SGLANG_IDLE_TIMEOUT` 配置，释放 GPU 内存
  - **GPU 分配**：Generator (device/mem_fraction 可配置)，Embedding/Reranker/Refiner (device/mem_fraction 可配置)）
  - **分块重试逻辑**：LLM 元数据提取失败时自动重启服务器并重试（可通过 `GRAPH_EXTRACTOR_RETRY_ON_FAILURE` 配置）
- **自动图更新插入**：OCR → LLM 实体/事件/关系提取 → 同步写入 Weaviate + Neo4j。
- **异步任务监控**：通过任务 API 跟踪上传、OCR 和嵌入的处理进度。

---

## 架构

```
┌──────────────┐    ┌─────────────────────────────┐
│   输入层     │ →  │  LangGraph 上传管道          │ →  Markdown + *.graph.json
│ (PDF/IMG/…)  │    │  (MemorySaver 检查点)        │
└──────────────┘    └─────────────────────────────┘
                                  │
┌──────────────┐    ┌─────────────────────────────┐
│   用户查询   │ →  │  LangGraph RAG 工作流        │
└──────────────┘    │  (MemorySaver 检查点)        │
                    └─────────────────────────────┘
                                  │
                    ┌─────────────┴──────────────┐
                    │   跳数路由器（LLM + 规则）   │
                    └─────────────┬──────────────┘
                                  │
     ┌────────────────────────────┼────────────────────────────┐
     │                            │                            │
  路径 1                        路径 2                       路径 3
  Vector RAG                   Weaviate Cross-Ref            Neo4j GraphDB
  TextSearcher+Reranker         GraphQL QueryReference        深度遍历
  (≤ 2 跳)                      (3–5 跳)                      (≥ 6 跳)
                                  │
                                  ▼
                 ┌──────────────────────────────────────────┐
                 │  质量门控 + 观察者 LLM（0~1 评分）        │
                 └────────────────┬─────────────────────────┘
                                  │
                        ┌─────────▼──────────────┐
                        │  GoT 思维扩展器         │
                        │  分支合并 + 剪枝        │
                        └─────────┬──────────────┘
                                  │
                           ┌──────▼──────┐
                           │  LLM 答案   │
                           └─────────────┘
```

### 工作流图（查询）

```
planner → tool_router ┬→ rag_router →┬→ vector_retriever  ──→┐
                      │               ├→ crossref_retriever ─→├→ quality_gate →┬→ thought_expander → aggregator → END
                      │               └→ graphdb_retriever ──→┘                └→ rag_router (backtrack)
                      │
                      └→ tool_executor ────────────────────────────────────────→ aggregator → END
```

**Tool Router**：使用 LLM 分类查询意图（knowledge/calculation/database/api_call/code_exec）（可通过 `TOOL_INTENT_CLASSIFIER_ENDPOINT` 配置）。将知识查询路由到 RAG 管道，将计算任务路由到工具执行器。

**Tool Executor**：通过 MCP 服务器（如果 `MCP_SERVER_ENABLED=true`）或本地 fallback 执行工具。当前支持：
- Calculator（基于 AST 的安全评估）
- SQL executor（存根）
- API caller（存根）
- Code runner（存根）

---

## 输入 / 预处理层

由 `LangGraphUploadPipeline`（`langgraph_upload_pipeline.py`）在所有节点上进行 `MemorySaver` 检查点处理：

1. **转换与布局**：`run_file_processor.py` 处理 PDF/Office/图像/音频输入 → `Results/1.Converted_images` + `Results/2.LayoutDetection`。
2. **OCR 与 Markdown**：使用 SGLang 驱动的 OCRFlux 的 `run_ocr_processing()` 生成逐页 Markdown → `Results/4.OCR_results`。
3. **LLM 元数据提取**：`LLMMetadataExtractor` 从 Markdown 中提取实体/事件/关系 → `Results/8.graph_metadata/*.graph.json`。
   - **分块大小**：可通过 `GRAPH_EXTRACTOR_CHUNK_SIZE` 配置
   - **超时**：可通过 `GRAPH_EXTRACTOR_API_TIMEOUT` 配置
   - **重试逻辑**：超时时重启 SGLang generator 服务器并重试同一块一次
   - **保活**：处理期间后台线程每20秒 touch 服务器
4. **图更新插入**：
   - `GraphSchemaManager` 确保 Weaviate GraphEntity/GraphEvent/GraphRelation 集合存在，带有交叉引用（source/target/event）
   - `LegacyGraphIngestor` / `Neo4jManager` 使用确定性 UUID 将节点/关系 MERGE 到 Neo4j
5. **延迟分块与嵌入**：`embedding_text.py` 将 Markdown 分割成块，并通过 `SharedEmbeddingModel` 上传到 Weaviate TextDocument 集合（模型可通过 `EMBEDDING_MODEL` 配置）。

---

## 查询 / 推理层

由 `GraphReasoner`（`graph_reasoner.py`）配合 `MemorySaver` 检查点和智能回溯处理：

1. **跳数分类器（LLM + 启发式混合）** (`HopClassifier`)：
   - **主要**：基于 LLM 的分类器通过 SGLang 服务器估计查询复杂度（1–`GRAPH_MAX_HOPS`）。
   - **备用**：基于关键词、箭头数量和概念分隔符的启发式评分。
   - 估计的跳数决定初始检索路径。
2. **规划器**：分析查询，根据 LLM+启发式分类动态设置 `max_hops`（由 `GRAPH_MAX_HOPS` 限制），并初始化搜索计划。
3. **路由器**：根据跳数分类和查询特征选择 Path 1/2/3。
   - **初始路由**：跳数 ≤ 2 → Path 1（VectorRetriever），3–5 → Path 2（CrossRefRetriever），≥ 6 → Path 3（GraphDBRetriever）。
   - **回溯路由**：使用 `PathSelector.select_best_path()` 评估剩余未尝试路径，根据查询关键词和跳数对每条路径评分以选择最合适的替代方案。
4. **检索节点**：
   - **路径 1 – Vector RAG**：委托给 `rag_pipeline` 现有的 TextSearcher + Reranker（quality=1.0）。
   - **路径 2 – Cross-Ref GraphRAG**：BM25 种子实体 → Weaviate Cross-Reference `QueryReference` 多跳遍历（source/target/event refs），在升级到 Neo4j 之前先在 Weaviate 内收集与查询相邻的实体/事件。
   - **路径 3 – Neo4j GraphDB**：通过 `legacy_graph_client.py` Cypher 模板执行 ≥ 6 跳的模式化深度推理，或在 Weaviate cross-reference 结果枯竭后继续深化。
5. **质量门 + 观察者 LLM** (`QualityEvaluator`)：每个路径结果由观察者 LLM 评分 0.0–1.0（Path 1 委托时默认为 1.0）。
   - **通过条件**：质量 ≥ `QUALITY_GATE_THRESHOLD` → 进入下一阶段。
   - **回溯**：质量 < `QUALITY_GATE_THRESHOLD` → `PathSelector.select_best_path()` 根据查询特征（关键词、跳数）评估剩余路径并选择最合适的替代路径。
   - **终止**：所有路径耗尽或达到 `MAX_BACKTRACK_COUNT` 限制后，继续使用最佳上下文并在 `answer_notes` 中标记降级。
   - **路径跟踪**：`tried_paths` 状态字段防止重试相同路径。
6. **GoT 思维扩展器**（`GOT_MODE_ENABLED=true`）：通过分支、评分和合并进行图形化思维探索。
   - 每步最多并行扩展 `GOT_BRANCH_FACTOR` 个候选查询。
   - 观察者 LLM 对每个分支的相关性、覆盖度和新颖性评分（0.0–1.0）。
   - 高于 `GOT_THOUGHT_SCORE_THRESHOLD` 的分支通过 `GOT_MERGE_STRATEGY`（`top_k` / `weighted_union` / `vote`）合并。
   - 低质量边缘通过 `GOT_EDGE_PRUNE_THRESHOLD` 关键词重叠评分修剪。
   - 连续全分支失败（由 `GOT_MAX_CONSECUTIVE_FAILURES` 跟踪）触发基于快照的回溯（状态回滚到上次成功合并）。
7. **聚合器**：从实体/事件/关系构建用于 LLM 生成的上下文片段。
8. **生成**（`generator.py`）：将思维/路径片段与原始查询合并以生成答案；`refiner.py` / `evaluator.py` 可选地对响应进行后处理。

---

## 模块地图

```
backend/
├── main.py                          # FastAPI 服务器入口点
├── config.py                        # 服务器级配置
├── logging_config.py                # 日志配置
│
├── api/                             # API 层
│   ├── routes.py                    # 主要上传/文件/会话路由
│   ├── chat.py                      # POST /v1/chat 端点
│   ├── ocr_routes.py                # OCR 处理端点
│   └── pause_api.py                 # 任务暂停/恢复 API
│
├── notebooklm/                      # RAG 核心模块
│   ├── config.py                    # 模型/路径/图配置
│   ├── rag_pipeline.py              # LangGraph RAG 工作流编排器
│   ├── graph_reasoner.py            # LangGraph 工作流编排
│   ├── graph_schema.py              # Weaviate Entity/Event/Relation 模式
│   ├── hop_classifier.py            # 查询复杂度估计器
│   ├── reasoner/                    # 重构的 GraphReasoner 模块
│   │   ├── state.py                 # GraphReasonerState 定义
│   │   ├── routing.py               # PathSelector, HopClassifier
│   │   ├── quality.py               # QualityEvaluator
│   │   ├── retrievers.py            # VectorRetriever, CrossRefRetriever, GraphDBRetriever
│   │   └── __init__.py
│   ├── legacy_graph_client.py       # Neo4j Cypher 遍历客户端
│   ├── legacy_graph_ingestor.py     # Neo4j 更新插入助手
│   ├── embedding_text.py            # 延迟分块 + Weaviate 文本索引
│   ├── embedding_image.py           # 图像嵌入 + Weaviate 图像索引
│   ├── image_processor.py           # 图像处理工具
│   ├── shared_embedding.py          # SGLang 嵌入/重排序客户端（单例）
│   ├── sglang_server_manager.py     # SGLang 服务器生命周期管理器
│   ├── generator.py                 # LLM 答案生成
│   ├── refiner.py                   # 答案精炼
│   ├── evaluator.py                 # 答案质量评估
│   ├── router.py                    # 查询类型路由
│   ├── query_rewriter.py            # 查询重写
│   ├── parallel_search.py           # 并行文本+图像搜索
│   ├── weaviate_utils.py            # Weaviate 客户端工具
│   ├── tools/                       # 工具调用 & MCP 集成
│   │   ├── mcp_client.py            # MCP 服务器 REST 客户端
│   │   ├── tool_executor.py         # 工具执行（MCP/本地 fallback）
│   │   └── __init__.py
│   ├── rag_text/                    # 文本搜索 + 重排序器
│   └── rag_image/                   # 图像搜索 + 重排序器
│
├── nextits_data/                    # 数据处理管道
│   └── pipe/
│       ├── langgraph_upload_pipeline.py  # LangGraph 上传工作流（带检查点）
│       ├── llm_metadata_extractor.py     # 实体/事件/关系提取
│       ├── neo4j_manager.py              # Neo4j 更新插入管理器
│       ├── run_file_processor.py         # 转换/布局/OCR 编排器
│       ├── pipeline_image.py             # 图像管道
│       ├── pipeline_sound.py             # 音频管道
│       └── main_pipe/
│           ├── ocr_pipe/                 # 基于 SGLang 的 OCRFlux 引擎
│           ├── udp_pdftopng_300dpi.py    # PDF → PNG 转换
│           └── udp_layoutdetection.py    # 布局检测
│
├── services/                        # 业务逻辑服务
│   ├── model_manager.py             # LazyModelManager（GPU 生命周期）
│   ├── ocr_vision_manager.py        # OCR 引擎管理
│   └── rag_service.py               # RAG 服务编排
│
└── utils/
    ├── task_queue.py                # GPU 任务队列（异步任务管理）
    ├── helpers.py                   # 共享工具函数
    ├── path_helpers.py              # 路径计算助手
    └── file_utils.py                # 文件操作工具
```

---

## 数据管道

1. **文件上传**（`POST /upload/files`）
   - `api/routes.py` 将文件存储在每个会话的文件夹中，并通过 `task_queue.py` 将 `run_processing_pipeline` 加入队列。
2. **GPU 任务队列**
   - `task_queue.py` 管理带有进度跟踪的顺序 GPU 绑定任务（转换 → 布局 → OCR）。
3. **文本索引**（`run_text_indexing` / `run_text_indexing_v2`）
   - 初始化 `SharedEmbeddingModel` → 运行 `process_markdown_files` 进行 Weaviate 延迟分块索引。
4. **图提取与摄取**
   - `LLMMetadataExtractor` 生成 `*.graph.json` → `GraphSchemaManager` 更新插入到 Weaviate → `Neo4jManager` / `LegacyGraphIngestor` 更新插入到 Neo4j。
5. **存储状态**
   - Weaviate：TextDocument + GraphEntity/Event/Relation 集合。
   - Neo4j：Entity/Event 节点 + 带有确定性 UUID 和自动创建约束的关系边。

---

## 查询处理流程

1. `POST /v1/chat` → 调用 `rag_pipeline.retrieve()`。
2. **跳数分类（LLM + 启发式）**：
   - 基于 LLM 的分类器（通过 SGLang）估计查询复杂度（1–6 跳）。
   - 启发式备用方案使用关键词模式和查询结构分析。
3. `graph_reasoner.py` 运行 LangGraph 工作流：
   - **planner** → 仅负责分析查询并记录计划/历史。
   - **tool_router** → LLM 判别 query intent（knowledge/calculation/database/api_call/code_exec），决定进入 RAG 或 Tool。
   - **rag_router** → 基于 LLM+启发式跳数分类设置 `max_hops`，并选择 Vector/Cross-Ref/GraphDB 路径。
   - **检索节点**（路径 1/2/3）→ 执行选定的检索策略。
   - **quality_gate** → 观察者 LLM 对结果评分（0.0–1.0）。
   - 如果 quality < threshold → **智能回溯**：`_select_best_path()` 基于查询关键词和跳数评估剩余路径，选择最合适的替代方案（最多 MAX_BACKTRACK 次重试）。
   - 如果启用 GoT → 带有基于快照回溯的 **thought_expander**。
   - **tool_executor** → 优先调用 MCP 服务器，失败时回退到本地实现：
     - 计算器：AST 安全计算（已完成）
     - API 调用/代码执行：轻量本地实现（适合 PoC，建议配合 MCP 正式工具）
     - SQL 执行：当前为 `not_implemented`
   - **aggregator** 构建上下文片段或格式化工具结果。
4. `generator.py` 从原始查询 + 上下文片段生成答案。
5. （可选）`refiner.py` 润色答案；`evaluator.py` 记录质量说明。
6. 响应包含用于调试的 `plan`、`hops`、`notes`、`context_snippets`、`backtrack_count`、`tried_paths` 和 `thought_steps`。

---

## 安装与运行

```bash
cd backend
pip install -r requirements.txt

# 环境变量设置（参见 .env.example）
export GRAPH_RAG_ENABLED=true
export LANGGRAPH_ENABLED=true
export GOT_MODE_ENABLED=true
export LEGACY_GRAPH_ENABLED=true
export LEGACY_GRAPH_URI=bolt://localhost:7687
export LEGACY_GRAPH_USER=neo4j
export LEGACY_GRAPH_PASSWORD=your_password

python main.py
# SGLang 嵌入/重排序服务器在首次请求时自动启动。
```

本地启动 Neo4j：

```bash
docker run -d --name neo4j-dev \
  -p7474:7474 -p7687:7687 \
  -e NEO4J_AUTH=neo4j/your_password \
  -v neo4j-data:/data \
  neo4j:5
```

---

## 关键配置（`notebooklm/config.py`）

- **Graph RAG 开关**：`GRAPH_RAG_ENABLED`、`LANGGRAPH_ENABLED`、`GOT_MODE_ENABLED`、`GRAPH_MAX_HOPS`。
- **GoT 调优**：`GOT_BRANCH_FACTOR`、`GOT_MERGE_STRATEGY`（`top_k`/`weighted_union`/`vote`）、`GOT_MERGE_TOP_K`、`GOT_THOUGHT_SCORE_THRESHOLD`、`GOT_EDGE_PRUNE_THRESHOLD`、`GOT_MAX_STEPS`、`GOT_MAX_CONSECUTIVE_FAILURES`、`GOT_OBSERVER_ENDPOINT`/`GOT_OBSERVER_MODEL`。
- **传统图**：`LEGACY_GRAPH_ENABLED`、`LEGACY_GRAPH_URI`、`LEGACY_GRAPH_LABELS`、`LEGACY_GRAPH_MAX_PATHS`。
- **Weaviate**：`WEAVIATE_HOST/PORT`、`WEAVIATE_TEXT_CLASS`、`WEAVIATE_VECTORIZER`。
- **嵌入/重排序器**：`EMBEDDING_DEVICE`（SGLang 服务器 URL）。
- **会话目录**：`DATA_ROOT/Results`、`sessions/<id>` 布局。

---

## API 概览

| 端点 | 描述 |
|---|---|
| `POST /upload/files` | 触发 LangGraph 上传管道 |
| `POST /v1/chat` | 运行带检查点/回溯的 3 路 RAG |
| `GET /api/v1/tasks/{task_id}` | 监控排队的上传/OCR 任务 |
| `GET /files` | 列出会话产物 |
| `POST /pause` | 暂停/恢复后台任务 |

---

## 日志与运维

- `sglang_embedding_server.log`、`sglang_reranker_server.log` – SGLang 模型服务器健康状态。
- `Results/8.graph_metadata/*.graph.json` – LLM 提取结果存档。
- `LegacyGraphIngestor` 在首次运行时自动创建约束；无需手动设置。
- `LazyModelManager` 在空闲约 60 秒后释放 GPU 内存。
- 所有 LangGraph 工作流记录检查点 ID 和回溯次数以供追踪。
- **SGLang 冷启动**：延迟加载意味着首次 `/v1/chat`（或 hop classifier）请求需为每个 SGLang 服务器加载模型到 VRAM，耗时 20–60 秒；建议在对外提供服务前进行预热请求或使用 keep-alive cron 以避免客户端超时。
- **易失性检查点**：`MemorySaver` 将图快照存储在进程内，只要 FastAPI 重启，进行中的状态就会丢失；在迁移至 `SqliteSaver`/`PostgresSaver` 之前，请将其视作易失会话。

---

## 路线图

1. ~~**GoT（Graph of Thought）**~~
   - `thought_expander` 现在执行图形化探索：每步扩展 `GOT_BRANCH_FACTOR` 个分支，观察者 LLM 对每个分支评分，最佳结果通过 `GOT_MERGE_STRATEGY` 合并。低质量边被剪枝，连续失败触发基于快照的回溯。
2. **高级跳数分类器**
   - 使用查询元数据（词元长度、实体数量）增强混合路由器。
3. **多图检索优化**
   - 改进 3–5 跳 Weaviate 遍历的上下文过滤/去重，并为 ≥ 6 跳 Neo4j 探索添加 Cypher 模板。
4. **LangGraph 工作流可观测性**
   - 发出每节点延迟/错误指标，并在 `GraphReasoner` 和 `LegacyGraphClient` 内集成重试策略。
5. **持久化检查点**
   - 从 `MemorySaver` 迁移到 `SqliteSaver` / `PostgresSaver` 以实现跨会话状态恢复。

---

## 贡献与联系

欢迎提交 Issue 和 PR。如有问题，请联系 jeongnext@hnextits.com。

---

## 许可证

本项目采用双重许可：
- **MIT 许可证** - 详情请参阅 [LICENSE](LICENSE) 文件
- **Apache 许可证 2.0** - 详情请参阅 [LICENSE-APACHE](LICENSE-APACHE) 文件

您可以选择其中任一许可证来管理您对本软件的使用。

---

## 引用

如果您在研究中使用了本项目，请引用以下内容：

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
