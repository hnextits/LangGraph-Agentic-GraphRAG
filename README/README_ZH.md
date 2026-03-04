# LangGraph-Agentic-Graph RAG

<div align="center">

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

[English](../README.md) | [한국어](README_KO.md) | 中文
</div>
<br>
**一个将检索、推理与工具执行统一于状态化图工作流中的混合智能体 RAG 平台**

## Introduction

> 传统 RAG 系统在多跳推理、依赖工具执行的查询以及动态知识整合方面往往存在局限。仅依赖向量相似度检索，难以充分应对需要结构化图遍历、条件分支以及计算执行的复杂分析任务。
>
> LangGraph-Agentic-Graph RAG 提出了一种基于 LangGraph 构建、由 SGLang 驱动的状态化图编排架构。
>
> 该系统将知识检索与工具执行统一于单一的可检查点工作流之中，实现智能路由、基于质量门控的回溯机制，以及通过 Graph-of-Thought 扩展实现的自适应多路径推理。
<br>
LangGraph-Agentic-Graph RAG 是一个智能混合 RAG 平台，由 **LangGraph + SGLang** 驱动，无缝集成知识检索与工具执行。

系统特性：

- **双模式查询处理**：通过基于 LLM 的意图分类在知识型 RAG 检索和计算工具执行之间自动路由
- **高级文档摄取**：通过 LangGraph 状态机和检查点持久化将原始文档（PDF/图像/音频）转换为 Markdown 块和结构化图元数据
- **智能检索路由**：根据查询复杂度在三条检索路径（Vector、Weaviate Cross-Reference GraphRAG、Neo4j Deep Graph Traversal）中动态选择，配合质量门控回溯
- **工具调用框架**：集成 MCP（Model Context Protocol）服务器和本地 fallback，支持计算器、API 调用、代码执行和数据库查询
- **Graph-of-Thought 推理**：用于复杂分析查询的多分支探索和基于快照的回溯

<div align="center">
<img src="https://github.com/user-attachments/assets/441a4a4b-d239-45c1-b385-80ddd95f31e6" width="512" height="768" ></img><br/>
</div>

---

## 核心功能

- **LangGraph 状态机**：所有工作流（摄取、查询推理、工具执行、摘要、思维导图生成）均运行在带有 `MemorySaver` 检查点的 LangGraph `StateGraph` 上，实现完整的状态持久化和恢复。

- **智能查询路由**：基于 LLM 的意图分类自动确定查询需要知识检索还是计算工具执行：
  - **知识查询** → 带有 3 路检索路由的 RAG 管道
  - **计算查询** → 计算器工具，支持高级数学（sqrt、log、trig、sigma）的 AST 安全评估
  - **数据库查询** → SQL 执行器（计划中）
  - **API 调用** → 可配置端点的 HTTP API 调用器
  - **代码执行** → 受限 built-in 的 Python 沙箱

- **检查点与智能回溯**：所有节点转换都被检查点，质量门评估检索结果并在质量不足时触发智能路径选择：
  - **质量评估**：观察者 LLM 对每个路径结果相对于 `QUALITY_GATE_THRESHOLD` 评分 0.0–1.0
  - **智能路径选择**：`PathSelector` 根据查询关键词、跳数和路径特征分析剩余未尝试路径，选择最合适的替代方案
  - **回溯限制**：可通过 `MAX_BACKTRACK_COUNT` 配置以防止无限循环
  - **状态跟踪**：`tried_paths` 字段防止重试失败的策略

- **3 路检索路由**：查询复杂度（跳数）决定最优检索策略：
  - **路径 1 – Vector RAG（≤ 2 跳）**：通过 BM25 + 重排序器在 late-chunked TextDocument 语料上快速语义相似度搜索。适合直接事实问题。
  - **路径 2 – Weaviate Cross-Reference GraphRAG（3–5 跳）**：BM25 种子实体搜索后在 Weaviate 内进行多跳 cross-reference 遍历（source/target/event refs）。通过关系行走浮现查询相邻的实体和事件。
  - **路径 3 – Neo4j Deep Graph Traversal（≥ 6 跳）**：基于 Cypher 的深度图遍历，用于模式化关系推理。处理需要广泛图探索的复杂多实体查询。
  - **跳数分类**：混合 LLM + 启发式方法估计查询复杂度，LLM 主分类配合基于关键词的 fallback

- **Graph-of-Thought 扩展**：带有基于快照回溯的多分支推理，用于复杂分析查询：
  - **分支探索**：每步并行扩展 `GOT_BRANCH_FACTOR` 个候选查询
  - **质量评分**：观察者 LLM 对每个分支的相关性、覆盖度和新颖性评分 0.0–1.0
  - **智能合并**：通过可配置策略（`top_k`/`weighted_union`/`vote`）合并高于 `GOT_THOUGHT_SCORE_THRESHOLD` 的分支
  - **边缘剪枝**：通过关键词重叠评分（`GOT_EDGE_PRUNE_THRESHOLD`）移除低质量连接
  - **失败恢复**：连续全分支失败触发快照回滚到最后成功的合并点

- **SGLang 推理生态系统**：所有 LLM 操作（生成、嵌入、重排序、跳数分类、质量评估）在带有智能生命周期管理的 SGLang 服务器上运行：
  - **延迟加载架构**：服务器在首次请求时自动启动，消除初始化期间的冷启动开销
  - **空闲超时**：非活动 `SGLANG_IDLE_TIMEOUT`（默认 60 秒）后自动释放 GPU 内存
  - **GPU 分配**：每个服务器（generator、embedding、reranker、refiner）可配置设备分配和内存比例
  - **保活机制**：后台线程在长时间运行操作期间维护服务器状态
  - **分块重试逻辑**：LLM 元数据提取在服务器重启时自动重试失败的块（可通过 `GRAPH_EXTRACTOR_RETRY_ON_FAILURE` 配置）

- **工具调用框架**：集成 MCP（Model Context Protocol）服务器和本地 fallback：
  - **MCP 优先架构**：当 MCP 服务器可用时（`MCP_SERVER_ENABLED=true`）通过 MCP 服务器主执行
  - **本地 fallback**：MCP 不可用时自动回退到本地实现
  - **计算器**：AST 安全表达式评估，支持高级数学函数（sqrt、cbrt、log、exp、sin、cos、tan、sigma）
  - **自然语言解析**：将韩语/英语数学表达式（"144의 제곱근"、"루트 144"）转换为可执行代码
  - **API 调用器**：执行 HTTP 请求，可配置端点和方法
  - **代码运行器**：Python 沙箱，受限 built-in 和令牌过滤以确保安全
  - **SQL 执行器**：未来数据库查询支持的占位符

- **自动图构建**：从原始文档到可查询知识图的端到端管道：
  - **OCR 处理**：基于 SGLang 的 OCRFlux 将文档转换为 Markdown
  - **LLM 提取**：从 Markdown 块中提取实体/事件/关系，可配置块大小和超时
  - **双存储**：同步更新插入到 Weaviate（cross-reference 图）和 Neo4j（深度图），使用确定性 UUID
  - **模式管理**：自动创建 Weaviate 集合，带有 cross-reference 定义

- **异步任务监控**：通过 REST API 跟踪完整任务生命周期：
  - **上传进度**：文件上传和处理阶段的实时状态
  - **OCR 进度**：逐页 OCR 完成跟踪
  - **嵌入进度**：块级索引状态
  - **任务取消**：优雅终止长时间运行的操作

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

### 核心组件

**Reasoner 模块**（`backend/notebooklm/reasoner/`）：
- `HopClassifier`：查询复杂度估计（LLM + 启发式 fallback）
- `PathSelector`：回溯的最优检索路径选择
- `QualityEvaluator`：基于 Observer LLM 的结果质量评估
- `VectorRetriever`、`CrossRefRetriever`、`GraphDBRetriever`：模块化检索实现

### 工作流图（查询）

```
planner → tool_router ┬→ rag_router →┬→ vector_retriever  ──→┐
                      │               ├→ crossref_retriever ─→├→ quality_gate →┬→ thought_expander → aggregator → END
                      │               └→ graphdb_retriever ──→┘                └→ rag_router (backtrack)
                      │
                      └→ tool_executor ────────────────────────────────────────→ aggregator → END
```

**Tool Router**：基于 LLM 的意图分类决定查询路由策略：
- **分类端点**：可通过 `TOOL_INTENT_CLASSIFIER_ENDPOINT` 配置（默认为 SGLang generator）
- **意图类别**：`knowledge`、`calculation`、`database`、`api_call`、`code_exec`
- **路由逻辑**：
  - `knowledge` → RAG 管道（3 路检索路由）
  - 其他意图 → 工具执行器（MCP/本地 fallback）
- **Fallback 机制**：LLM 分类失败时使用启发式关键词匹配

**Tool Executor**（`backend/notebooklm/tools/tool_executor.py`）：
- MCP 服务器集成及本地 fallback
- 支持：计算器、API 调用器、代码运行器、SQL 执行器（计划中）
- 详细信息见下方查询处理流程章节

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
├── mcp_server/                      # MCP（Model Context Protocol）工具服务器
│   └── main.py                      # 用于工具执行的 FastAPI 服务器
│
├── data_pipeline/                   # 数据处理管道
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

1. **请求启动**：`POST /v1/chat` → `RAGPipeline.process_query()` 调用 `GraphReasoner.retrieve()`

2. **LangGraph 工作流执行**（`graph_reasoner.py`）：

   **步骤 1：规划器**（`planner` 节点）
   - 分析用户查询并提取核心概念
   - 记录高级检索计划和推理步骤
   - 初始化多轮上下文的查询历史
   - **输出**：`plan`、`query_analysis`

   **步骤 2：Tool Router**（`tool_router` 节点）
   - 通过 `ToolExecutor.classify_intent()` 进行 LLM 查询意图分类：
     - `knowledge` → 路由到 **rag_router**（知识检索路径）
     - `calculation` → 路由到 **tool_executor**（计算器）
     - `database` → 路由到 **tool_executor**（SQL 执行器）
     - `api_call` → 路由到 **tool_executor**（API 调用器）
     - `code_exec` → 路由到 **tool_executor**（代码运行器）
   - **输出**：`intent`、路由决策

   **分支 A：知识查询路径**

   **步骤 3a：RAG Router**（`rag_router` 节点，用于知识查询）
   - 执行跳数分类（LLM + 启发式混合）
   - 设置 `max_hops` = `min(llm_estimate, heuristic_estimate, GRAPH_MAX_HOPS)`
   - 初始检索路径选择：
     - 跳数 ≤ 2 → `vector_retriever`（路径 1）
     - 跳数 3–5 → `crossref_retriever`（路径 2）
     - 跳数 ≥ 6 → `graphdb_retriever`（路径 3）
   - **输出**：`max_hops`、`retrieval_path`、`tried_paths`

   **步骤 4a：检索执行**（路径 1/2/3）
   - **路径 1**：TextDocument 中 BM25 语义搜索 + 重排序器
   - **路径 2**：BM25 种子搜索 + Weaviate cross-reference 多跳遍历
   - **路径 3**：Neo4j Cypher 深度图遍历
   - **输出**：`context_snippets`、`entities`、`events`、`relations`

   **步骤 5a：质量门**（`quality_gate` 节点）
   - 观察者 LLM 对检索结果评分（0.0–1.0）
   - **如果质量 ≥ `QUALITY_GATE_THRESHOLD`**：
     - 进入 aggregator 或 thought expander（如果启用 GoT）
   - **如果质量 < threshold**：
     - 触发智能回溯：
       - `PathSelector.select_best_path()` 分析剩余路径
       - 根据查询关键词、跳数和路径特征评分
       - 选择最合适的替代方案（非随机）
       - 用新路径返回步骤 4a
     - **终止**：`MAX_BACKTRACK_COUNT` 次重试后或所有路径耗尽
   - **输出**：`retrieval_quality`、`backtrack_count`、`tried_paths`

   **步骤 6a：Thought Expander**（`thought_expander` 节点，如果 `GOT_MODE_ENABLED=true`）
   - 并行扩展 `GOT_BRANCH_FACTOR` 个候选查询
   - 观察者 LLM 对每个分支评分（0.0–1.0）
   - 通过策略合并高于 `GOT_THOUGHT_SCORE_THRESHOLD` 的分支
   - 剪枝低质量边缘（< `GOT_EDGE_PRUNE_THRESHOLD`）
   - 连续失败时基于快照的回溯
   - **输出**：`thought_steps`、扩展的上下文

   **分支 B：工具执行路径**

   **步骤 3b：Tool Executor**（`tool_executor` 节点，用于计算任务）
   - 将意图映射到特定工具：
     - `calculation` → 计算器（AST 安全评估）
     - `api_call` → API 调用器（HTTP 请求）
     - `code_exec` → 代码运行器（Python 沙箱）
     - `database` → SQL 执行器（占位符）
   - 准备工具输入：
     - 计算器：提取数学表达式，自然语言转换（"144의 제곱근" → `sqrt(144)`）
     - API 调用器：从提示中提取 URL
     - 代码运行器：提取代码片段
   - 执行工具：
     - **MCP 优先**：尝试通过 MCP 服务器 REST API 执行
     - **本地 fallback**：MCP 不可用时回退到本地实现
   - **输出**：带有状态（`ok`/`error`）、结果值和元数据的 `tool_result`
   - **注意**：工具失败返回错误消息；不回退到 RAG

   **步骤 7：聚合器**（`aggregator` 节点）
   - **用于 RAG 查询**：从实体/事件/关系/思维构建上下文片段
   - **用于工具查询**：将工具结果格式化为自然语言：
     - 计算器：`"表达式 = 结果"`（例如 `"sqrt(144) = 12.0"`）
     - API/代码：结果值或成功消息
     - 错误：用户友好的错误消息
   - 收集元数据：`context_snippets`、`thought_steps`、`backtrack_count`、`tried_paths`、`tool_result`
   - **输出**：聚合的上下文或格式化的工具结果

3. **答案生成**：
   - **用于 RAG 查询**：`generator.py` 从原始查询 + 上下文片段合成答案
   - **用于工具查询**：直接返回格式化的工具结果（无需 LLM 生成）
   - **可选后处理**：`refiner.py` 润色答案，`evaluator.py` 记录质量说明

4. **响应构建**（`RAGPipeline._build_response()` 或 `_build_tool_only_response()`）：
   - **用于 RAG 查询**：带有答案、上下文、片段、检索结果的完整响应
   - **用于工具查询**：带有工具结果作为答案的简化响应
   - **包含的元数据**：`plan`、`max_hops`、`retrieval_quality`、`backtrack_count`、`tried_paths`、`thought_steps`、`tool_result`（如适用）
   - **调试支持**：所有工作流状态暴露以实现可追溯性

5. **返回客户端**：带有答案、元数据和调试信息的 JSON 响应

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
