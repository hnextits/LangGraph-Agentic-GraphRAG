# LangGraph-Agentic-Graph RAG

<div align="center">

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

[English](../README.md) | 한국어 | [中文](README_ZH.md)
</div>

LangGraph-Agentic-Graph RAG는 **LangGraph + SGLang** 기반의 벡터–그래프 하이브리드 RAG 플랫폼입니다. 수집 파이프라인은 LangGraph 상태 머신과 체크포인트 영속성을 통해 원시 문서를 Markdown 청크 및 그래프 메타데이터로 변환합니다. 쿼리 시점에는 품질 게이트 백트래킹이 적용된 홉 기반 라우터가 Vector, Weaviate GraphRAG, Neo4j GraphDB 세 가지 검색 경로 중 하나를 선택하여 답변을 생성합니다.

<div align="center">
<img src="https://github.com/user-attachments/assets/441a4a4b-d239-45c1-b385-80ddd95f31e6" width="512" height="768" ></img><br/>
</div>

---

## 주요 기능

- **LangGraph 상태 머신**: 수집, 쿼리 추론, 요약, 마인드맵 생성이 모두 `MemorySaver` 체크포인팅을 갖춘 LangGraph `StateGraph` 위에서 동작합니다.
- **체크포인트 & 백트래킹**: 모든 노드 전환이 체크포인트됩니다; 품질 게이트와 GoT 스냅샷이 품질이 불충분할 때 대체 검색 경로나 이전 확장으로 롤백합니다(`MAX_BACKTRACK_COUNT`로 설정 가능).
- **3-way 검색 라우팅**: 쿼리 복잡도(hop 수)에 따라 Vector RAG, Weaviate Cross-Reference GraphQL, Neo4j Deep Graph Traversal로 라우팅(`GRAPH_MAX_HOPS`로 임계값 설정 가능). 홉 경계는 데이터 모델 특성을 반영합니다: 의미 기반 질의는 TextDocument 임베딩 인덱스에, 엔티티/속성 추론은 Weaviate Cross-Reference에, 6홉 이상 스키마 중심 관계 추론은 Neo4j Cypher 탐색으로 승격됩니다. Path 1과 Path 2 모두 Weaviate에서 동작하며, Path 1은 Late chunking 코퍼스 위에서 빠른 의미 유사성을, Path 2는 Cross-Reference 이웃을 걸으며 Neo4j까지 가지 않고도 질의 연관 엔티티/이벤트를 추가 발굴합니다.
- **관찰자 LLM + GoT 확장**: 관찰자 LLM이 각 경로 결과를 0–1로 점수화합니다. `QUALITY_GATE_THRESHOLD` 이상의 결과는 더 깊은 컨텍스트를 위해 Graph-of-Thought 분기/병합을 트리거합니다.
- **SGLang 추론**: 생성기, 임베딩, 리랭커, 홉 분류기, 관찰자 LLM 모두 지연 로딩(`LazyModelManager` + `SGLangServerManager`)이 적용된 SGLang 서버에서 동작합니다.
  - **지연 로딩**: 서버는 첫 요청 시 자동 시작, 유휴 타임아웃 `SGLANG_IDLE_TIMEOUT`으로 설정 가능하며 GPU 메모리 해제
  - **GPU 할당**: Generator (device/mem_fraction 설정 가능), Embedding/Reranker/Refiner (device/mem_fraction 설정 가능)
  - **청크 재시도 로직**: LLM 메타데이터 추출 시 실패한 청크를 서버 재시작 후 자동 재시도 (`GRAPH_EXTRACTOR_RETRY_ON_FAILURE`로 설정 가능)
- **자동 그래프 업서트**: OCR → LLM 엔티티/이벤트/관계 추출 → Weaviate + Neo4j 동시 수집.
- **비동기 작업 모니터링**: 업로드, OCR, 임베딩 진행 상황을 작업 API를 통해 추적합니다.

---

## 아키텍처

```
┌──────────────┐    ┌─────────────────────────────┐
│  입력 레이어  │ →  │  LangGraph 업로드 파이프라인 │ →  Markdown + *.graph.json
│ (PDF/IMG/…)  │    │   (MemorySaver 체크포인트)   │
└──────────────┘    └─────────────────────────────┘
                                  │
┌──────────────┐    ┌─────────────────────────────┐
│  사용자 쿼리  │ →  │  LangGraph RAG 워크플로우   │
└──────────────┘    │   (MemorySaver 체크포인트)   │
                    └─────────────────────────────┘
                                  │
                    ┌─────────────┴──────────────┐
                    │   홉 라우터 (LLM + 규칙)    │
                    └─────────────┬──────────────┘
                                  │
     ┌────────────────────────────┼────────────────────────────┐
     │                            │                            │
  Path 1                       Path 2                        Path 3
  Vector RAG                   Weaviate Cross-Ref            Neo4j GraphDB
  TextSearcher+Reranker         GraphQL QueryReference        Deep Traversal
  (≤ 2 홉)                      (3–5 홉)                      (≥ 6 홉)
                                  │
                                  ▼
                 ┌──────────────────────────────────────────┐
                 │  품질 게이트 + 관찰자 LLM (0~1 점수)      │
                 └────────────────┬─────────────────────────┘
                                  │
                        ┌─────────▼──────────────┐
                        │  GoT Thought Expander  │
                        │  분기 병합 + 가지치기   │
                        └─────────┬──────────────┘
                                  │
                           ┌──────▼──────┐
                           │  LLM 답변   │
                           └─────────────┘
```

### 워크플로우 그래프 (쿼리)

```
planner → tool_router ┬→ rag_router →┬→ vector_retriever  ──→┐
                      │               ├→ crossref_retriever ─→├→ quality_gate →┬→ thought_expander → aggregator → END
                      │               └→ graphdb_retriever ──→┘                └→ rag_router (backtrack)
                      │
                      └→ tool_executor ────────────────────────────────────────→ aggregator → END
```

**Tool Router**: LLM을 사용하여 쿼리 의도를 분류(knowledge/calculation/database/api_call/code_exec)합니다(`TOOL_INTENT_CLASSIFIER_ENDPOINT`로 설정 가능). 지식 쿼리는 RAG 파이프라인으로, 계산 작업은 tool executor로 라우팅합니다.

**Tool Executor**: MCP 서버(`MCP_SERVER_ENABLED=true`인 경우) 또는 로컬 fallback을 통해 도구를 실행합니다. 현재 지원:
- Calculator (AST 기반 안전한 평가)
- SQL executor (스텁)
- API caller (스텁)
- Code runner (스텁)

---

## 입력 / 전처리 레이어

`LangGraphUploadPipeline` (`langgraph_upload_pipeline.py`)이 모든 노드에 걸쳐 `MemorySaver` 체크포인팅과 함께 처리합니다:

1. **변환 & 레이아웃**: `run_file_processor.py`가 PDF/Office/이미지/오디오 입력을 처리 → `Results/1.Converted_images` + `Results/2.LayoutDetection`.
2. **OCR & Markdown**: SGLang 기반 OCRFlux를 사용하는 `run_ocr_processing()`이 페이지별 Markdown 생성 → `Results/4.OCR_results`.
3. **LLM 메타데이터 추출**: `LLMMetadataExtractor`가 Markdown에서 엔티티/이벤트/관계 추출 → `Results/8.graph_metadata/*.graph.json`.
   - **청크 크기**: configurable via `GRAPH_EXTRACTOR_CHUNK_SIZE
   - **타임아웃**: configurable via `GRAPH_EXTRACTOR_API_TIMEOUT
   - **재시도 로직**: 타임아웃 발생 시 SGLang generator 서버 재시작 후 동일 청크 1회 재시도
   - **Keepalive**: 처리 중 20초마다 서버 touch하는 백그라운드 스레드
4. **그래프 업서트**:
   - `GraphSchemaManager`가 Weaviate GraphEntity/GraphEvent/GraphRelation 컬렉션을 Cross-Reference(source/target/event)와 함께 생성
   - `LegacyGraphIngestor` / `Neo4jManager`가 결정론적 UUID로 Neo4j에 노드/관계를 MERGE
5. **Late Chunking & 임베딩**: `embedding_text.py`가 Markdown을 청크로 분할하고 `SharedEmbeddingModel`을 통해 Weaviate TextDocument 컬렉션에 업로드합니다(`EMBEDDING_MODEL`로 모델 설정 가능).

---

## 쿼리 / 추론 레이어

`GraphReasoner` (`graph_reasoner.py`)가 `MemorySaver` 체크포인팅과 지능형 백트래킹으로 처리합니다:

1. **홉 분류기 (LLM + 휴리스틱 하이브리드)** (`HopClassifier`):
   - **주요**: LLM 기반 분류기가 SGLang 서버를 통해 쿼리 복잡도(1–`GRAPH_MAX_HOPS`)를 추정합니다.
   - **대체**: 키워드, 화살표 개수, 개념 구분자를 기반으로 한 휴리스틱 점수 계산.
   - 추정된 홉 수가 초기 검색 경로를 결정합니다.
2. **플래너**: 쿼리를 분석하고 LLM+휴리스틱 분류에 따라 `max_hops`를 동적으로 설정(`GRAPH_MAX_HOPS`로 제한)하며 검색 계획을 초기화합니다.
3. **라우터**: 홉 분류 및 쿼리 특성에 따라 Path 1/2/3을 선택합니다.
   - **초기 라우팅**: 홉 ≤ 2 → Path 1 (VectorRetriever), 3–5 → Path 2 (CrossRefRetriever), ≥ 6 → Path 3 (GraphDBRetriever).
   - **백트래킹 라우팅**: `PathSelector.select_best_path()`를 사용하여 남은 미시도 경로를 평가하며, 쿼리 키워드와 홉 수를 기반으로 각 경로를 점수화하여 가장 적합한 대안을 선택합니다.
4. **검색 노드**:
   - **Path 1 – Vector RAG**: `rag_pipeline`의 TextSearcher + Reranker (기존 벡터 검색으로 위임, quality=1.0).
   - **Path 2 – Cross-Ref GraphRAG**: BM25 시드 엔티티 → Weaviate Cross-Reference `QueryReference` 멀티홉 탐색 (source/target/event refs)을 수행해 Neo4j로 escalation하기 전에 질의 인접 엔티티/이벤트를 Weaviate 내부에서 추가 확보합니다.
   - **Path 3 – Neo4j GraphDB**: `legacy_graph_client.py` Cypher 템플릿을 통한 6홉 이상 스키마 집중 탐색 또는 Weaviate Cross-Reference가 바닥났을 때의 심층 탐색.
5. **품질 게이트 + 관찰자 LLM** (`QualityEvaluator`): 모든 경로 결과는 관찰자 LLM에 의해 0.0–1.0으로 점수화됩니다 (Path 1은 위임 시 기본값 1.0).
   - **통과 조건**: 품질 ≥ `QUALITY_GATE_THRESHOLD` → 다음 단계로 진행.
   - **백트래킹**: 품질 < `QUALITY_GATE_THRESHOLD` → `PathSelector.select_best_path()`가 남은 경로를 쿼리 특성(키워드, 홉 수)에 따라 평가하여 가장 적합한 대체 경로를 선택합니다.
   - **종료**: 모든 경로가 소진되거나 `MAX_BACKTRACK_COUNT` 한도에 도달하면 최선의 컨텍스트로 계속 진행하고 `answer_notes`에 품질 저하를 표시합니다.
   - **경로 추적**: `tried_paths` 상태 필드가 동일한 경로의 재시도를 방지합니다.
6. **GoT Thought Expander** (`GOT_MODE_ENABLED=true`): 분기, 점수화, 병합을 통한 그래프 형태의 사고 탐색.
   - 각 단계는 최대 `GOT_BRANCH_FACTOR`개의 후보 쿼리를 병렬로 분기합니다.
   - 관찰자 LLM이 각 분기를 관련성, 범위, 참신성에 대해 0.0–1.0으로 점수화합니다.
   - `GOT_THOUGHT_SCORE_THRESHOLD` 이상의 분기는 `GOT_MERGE_STRATEGY`(`top_k` / `weighted_union` / `vote`)를 통해 병합됩니다.
   - 저품질 엣지는 `GOT_EDGE_PRUNE_THRESHOLD` 키워드 오버랩 점수로 가지치기됩니다.
   - 연속적인 전체 분기 실패(`GOT_MAX_CONSECUTIVE_FAILURES`로 추적)는 스냅샷 기반 백트래킹을 트리거합니다(마지막 성공적인 병합으로 상태 롤백).
7. **어그리게이터**: LLM 생성을 위해 엔티티/이벤트/관계에서 컨텍스트 스니펫을 구성합니다.
8. **생성** (`generator.py`): 사고/경로 스니펫을 원본 쿼리와 병합하여 답변을 생성합니다; `refiner.py` / `evaluator.py`가 선택적으로 응답을 후처리합니다.

---

## 모듈 맵

```
backend/
├── main.py                          # FastAPI 서버 진입점
├── config.py                        # 서버 수준 설정
├── logging_config.py                # 로깅 설정
│
├── api/                             # API 레이어
│   ├── routes.py                    # 주요 업로드/파일/세션 라우트
│   ├── chat.py                      # POST /v1/chat 엔드포인트
│   ├── ocr_routes.py                # OCR 처리 엔드포인트
│   └── pause_api.py                 # 작업 일시정지/재개 API
│
├── notebooklm/                      # RAG 핵심 모듈
│   ├── config.py                    # 모델/경로/그래프 설정
│   ├── rag_pipeline.py              # LangGraph RAG 워크플로우 오케스트레이터
│   ├── graph_reasoner.py            # LangGraph 워크플로우 오케스트레이션
│   ├── graph_schema.py              # Weaviate Entity/Event/Relation 스키마
│   ├── hop_classifier.py            # 쿼리 복잡도 추정기
│   ├── reasoner/                    # 리팩터링된 GraphReasoner 모듈
│   │   ├── state.py                 # GraphReasonerState 정의
│   │   ├── routing.py               # PathSelector, HopClassifier
│   │   ├── quality.py               # QualityEvaluator
│   │   ├── retrievers.py            # VectorRetriever, CrossRefRetriever, GraphDBRetriever
│   │   └── __init__.py
│   ├── legacy_graph_client.py       # Neo4j Cypher 탐색 클라이언트
│   ├── legacy_graph_ingestor.py     # Neo4j 업서트 헬퍼
│   ├── embedding_text.py            # Late chunking + Weaviate 텍스트 인덱싱
│   ├── embedding_image.py           # 이미지 임베딩 + Weaviate 이미지 인덱싱
│   ├── image_processor.py           # 이미지 처리 유틸리티
│   ├── shared_embedding.py          # SGLang 임베딩/리랭커 클라이언트 (싱글톤)
│   ├── sglang_server_manager.py     # SGLang 서버 생명주기 관리자
│   ├── generator.py                 # LLM 답변 생성
│   ├── refiner.py                   # 답변 정제
│   ├── evaluator.py                 # 답변 품질 평가
│   ├── router.py                    # 쿼리 유형 라우팅
│   ├── query_rewriter.py            # 쿼리 재작성
│   ├── parallel_search.py           # 병렬 텍스트+이미지 검색
│   ├── weaviate_utils.py            # Weaviate 클라이언트 유틸리티
│   ├── weaviate_s.py                # Weaviate 스키마 유틸리티
│   ├── clean_weaviate.py            # Weaviate + Neo4j 데이터 정리 스크립트
│   ├── tools/                       # 툴 호출 & MCP 통합
│   │   ├── mcp_client.py            # MCP 서버 REST 클라이언트
│   │   ├── tool_executor.py         # 툴 실행 (MCP/로컬 fallback)
│   │   └── __init__.py
│   ├── rag_text/                    # 텍스트 검색 + 리랭커
│   └── rag_image/                   # 이미지 검색 + 리랭커
│
├── nextits_data/                    # 데이터 처리 파이프라인
│   └── pipe/
│       ├── langgraph_upload_pipeline.py  # LangGraph 업로드 워크플로우 (체크포인팅)
│       ├── llm_metadata_extractor.py     # 엔티티/이벤트/관계 추출
│       ├── neo4j_manager.py              # Neo4j 업서트 매니저
│       ├── run_file_processor.py         # 변환/레이아웃/OCR 오케스트레이터
│       ├── pipeline_image.py             # 이미지 파이프라인
│       ├── pipeline_sound.py             # 오디오 파이프라인
│       └── main_pipe/
│           ├── ocr_pipe/                 # SGLang 기반 OCRFlux 엔진
│           ├── udp_pdftopng_300dpi.py    # PDF → PNG 변환
│           └── udp_layoutdetection.py    # 레이아웃 감지
│
├── services/                        # 비즈니스 로직 서비스
│   ├── model_manager.py             # LazyModelManager (GPU 생명주기)
│   ├── ocr_vision_manager.py        # OCR 엔진 관리
│   └── rag_service.py               # RAG 서비스 오케스트레이션
│
└── utils/
    ├── task_queue.py                # GPU 작업 큐 (비동기 작업 관리)
    ├── helpers.py                   # 공유 유틸리티 함수
    ├── path_helpers.py              # 경로 계산 헬퍼
    └── file_utils.py                # 파일 작업 유틸리티
```

---

## 데이터 파이프라인

1. **파일 업로드** (`POST /upload/files`)
   - `api/routes.py`가 파일을 세션별 폴더에 저장하고 `task_queue.py`를 통해 `run_processing_pipeline`을 큐에 추가합니다.
2. **GPU 작업 큐**
   - `task_queue.py`가 진행 상황 추적과 함께 순차적 GPU 바운드 작업(변환 → 레이아웃 → OCR)을 관리합니다.
3. **텍스트 인덱싱** (`run_text_indexing` / `run_text_indexing_v2`)
   - `SharedEmbeddingModel` 초기화 → Weaviate late-chunking 인덱싱을 위한 `process_markdown_files` 실행.
4. **그래프 추출 & 수집**
   - `LLMMetadataExtractor`가 `*.graph.json` 생성 → `GraphSchemaManager`가 Weaviate에 업서트 → `Neo4jManager` / `LegacyGraphIngestor`가 Neo4j에 업서트.
5. **저장소 상태**
   - Weaviate: TextDocument + GraphEntity/Event/Relation 컬렉션.
   - Neo4j: Entity/Event 노드 + 결정론적 UUID와 자동 생성 제약 조건을 가진 관계 엣지.

---

## 쿼리 처리 흐름

1. `POST /v1/chat` → `rag_pipeline.retrieve()` 호출.
2. **홉 분류 (LLM + Heuristic)**:
   - LLM 기반 분류기(SGLang 사용)가 쿼리 복잡도(1–6 홉)를 추정합니다.
   - 휴리스틱 fallback은 키워드 패턴과 쿼리 구조 분석을 사용합니다.
   - 결과가 초기 검색 경로 선택을 결정합니다.
3. `graph_reasoner.py`가 LangGraph 워크플로우 실행:
   - **planner** → 쿼리 분석, LLM+Heuristic 분류 기반으로 `max_hops` 설정.
   - **router** → 홉 수 기반으로 초기 경로(Vector/Cross-Ref/GraphDB) 선택.
   - **검색 노드** (Path 1/2/3) → 선택된 검색 전략 실행.
   - **quality_gate** → 관찰자 LLM이 결과 점수화 (0.0–1.0).
   - quality < threshold이면 → **지능형 백트래킹**: `_select_best_path()`가 쿼리 키워드와 홉 수 기반으로 남은 경로를 평가하여 가장 적합한 대안 선택 (최대 MAX_BACKTRACK 재시도).
   - GoT 활성화 시 → 스냅샷 기반 백트래킹이 적용된 **thought_expander**.
   - **aggregator**가 컨텍스트 스니펫을 구성합니다.
4. `generator.py`가 원본 쿼리 + 컨텍스트 스니펫으로 답변을 생성합니다.
5. (선택) `refiner.py`가 답변을 다듬고; `evaluator.py`가 품질 노트를 기록합니다.
6. 응답에는 디버깅을 위한 `plan`, `hops`, `notes`, `context_snippets`, `backtrack_count`, `tried_paths`, `thought_steps`가 포함됩니다.

---

## 설치 & 실행

```bash
cd backend
pip install -r requirements.txt

# 환경 변수 설정 (see .env.example)
export GRAPH_RAG_ENABLED=true
export LANGGRAPH_ENABLED=true
export GOT_MODE_ENABLED=true
export LEGACY_GRAPH_ENABLED=true
export LEGACY_GRAPH_URI=bolt://localhost:7687
export LEGACY_GRAPH_USER=neo4j
export LEGACY_GRAPH_PASSWORD=your_password

python main.py
# SGLang 임베딩/리랭커 서버는 첫 요청 시 자동으로 시작됩니다.
```

Neo4j 로컬 실행:

```bash
docker run -d --name neo4j-dev \
  -p7474:7474 -p7687:7687 \
  -e NEO4J_AUTH=neo4j/your_password \
  -v neo4j-data:/data \
  neo4j:5
```

---

## 주요 설정 (`notebooklm/config.py`)

- **Graph RAG 토글**: `GRAPH_RAG_ENABLED`, `LANGGRAPH_ENABLED`, `GOT_MODE_ENABLED`, `GRAPH_MAX_HOPS`.
- **GoT 튜닝**: `GOT_BRANCH_FACTOR`, `GOT_MERGE_STRATEGY` (`top_k`/`weighted_union`/`vote`), `GOT_MERGE_TOP_K`, `GOT_THOUGHT_SCORE_THRESHOLD`, `GOT_EDGE_PRUNE_THRESHOLD`, `GOT_MAX_STEPS`, `GOT_MAX_CONSECUTIVE_FAILURES`, `GOT_OBSERVER_ENDPOINT`/`GOT_OBSERVER_MODEL`.
- **레거시 그래프**: `LEGACY_GRAPH_ENABLED`, `LEGACY_GRAPH_URI`, `LEGACY_GRAPH_LABELS`, `LEGACY_GRAPH_MAX_PATHS`.
- **Weaviate**: `WEAVIATE_HOST/PORT`, `WEAVIATE_TEXT_CLASS`, `WEAVIATE_VECTORIZER`.
- **임베딩/리랭커**: `EMBEDDING_DEVICE` (SGLang 서버 URL).
- **세션 디렉토리**: `DATA_ROOT/Results`, `sessions/<id>` 레이아웃.

---

## API 요약

| 엔드포인트 | 설명 |
|---|---|
| `POST /upload/files` | LangGraph 업로드 파이프라인 트리거 |
| `POST /v1/chat` | 체크포인트/백트래킹이 적용된 3-Way RAG 실행 |
| `GET /api/v1/tasks/{task_id}` | 큐에 등록된 업로드/OCR 작업 모니터링 |
| `GET /files` | 세션 아티팩트 목록 조회 |
| `POST /pause` | 백그라운드 작업 일시정지/재개 |

---

## 로깅 & 운영

- `sglang_embedding_server.log`, `sglang_reranker_server.log` – SGLang 모델 서버 상태.
- `Results/8.graph_metadata/*.graph.json` – LLM 추출 결과 아카이브.
- `LegacyGraphIngestor`가 첫 실행 시 제약 조건을 자동 생성합니다; 수동 설정 불필요.
- `LazyModelManager`가 약 60초 유휴 후 GPU 메모리를 해제합니다.
- 모든 LangGraph 워크플로우가 추적성을 위해 체크포인트 ID와 백트래킹 횟수를 기록합니다.
- **SGLang 콜드 스타트**: 지연 로딩 구조라 첫 `/v1/chat`(또는 hop classifier) 요청 시 각 SGLang 서버가 VRAM에 모델을 적재하며 20–60초가 소요될 수 있습니다. 클라이언트 타임아웃을 피하려면 웜업 요청 또는 keep-alive cron을 권장합니다.
- **휘발성 체크포인트**: `MemorySaver`는 프로세스 내부에 그래프 스냅샷을 저장하므로 FastAPI가 재시작되면 진행 중 상태가 모두 소실됩니다. `SqliteSaver`/`PostgresSaver`로의 마이그레이션 전까지는 세션이 휘발성임을 유의하세요.

---

## 로드맵

1. ~~**GoT (Graph of Thought)**~~
   - `thought_expander`가 이제 그래프 형태의 탐색을 수행합니다: 각 단계에서 `GOT_BRANCH_FACTOR`개의 분기를 확장하고, 관찰자 LLM이 각 분기를 점수화하며, 최적 결과가 `GOT_MERGE_STRATEGY`로 병합됩니다. 저품질 엣지는 가지치기되고, 연속 실패 시 스냅샷 기반 백트래킹이 트리거됩니다.
2. **고급 홉 분류기**
   - 하이브리드 라우터를 위해 쿼리 메타데이터(토큰 길이, 엔티티 수)로 보강합니다.
3. **멀티 그래프 검색 최적화**
   - 3–5 홉 Weaviate 탐색의 컨텍스트 필터링/중복 제거를 개선하고 ≥ 6 홉 Neo4j 탐색을 위한 Cypher 템플릿을 추가합니다.
4. **LangGraph 워크플로우 관찰 가능성**
   - 노드별 지연/오류 메트릭을 내보내고 `GraphReasoner` 및 `LegacyGraphClient` 내에 재시도 정책을 통합합니다.
5. **영속적 체크포인터**
   - 크로스 세션 상태 복구를 위해 `MemorySaver`에서 `SqliteSaver` / `PostgresSaver`로 마이그레이션합니다.

---

## 기여 & 연락처

이슈와 PR을 환영합니다. 문의 사항은 jeongnext@hnextits.com으로 연락해 주세요.

---

## 라이선스

이 프로젝트는 이중 라이선스로 제공됩니다:
- **MIT 라이선스** - 자세한 내용은 [LICENSE](LICENSE) 파일을 참조하세요.
- **Apache 라이선스 2.0** - 자세한 내용은 [LICENSE-APACHE](LICENSE-APACHE) 파일을 참조하세요.

이 소프트웨어 사용에 적용할 라이선스를 선택할 수 있습니다.

---

## 인용

이 프로젝트를 연구에 사용하는 경우 다음을 인용해 주세요:

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
