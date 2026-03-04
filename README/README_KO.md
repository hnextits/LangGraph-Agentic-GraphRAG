# LangGraph-Agentic-Graph RAG

<div align="center">

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

[English](../README.md) | 한국어 | [中文](README_ZH.md)
</div>

LangGraph-Agentic-Graph RAG는 **LangGraph + SGLang** 기반의 지능형 하이브리드 RAG 플랫폼으로, 지식 검색과 계산 툴 실행을 seamless하게 통합합니다. 주요 특징:

- **이중 모드 쿼리 처리**: LLM 기반 의도 분류를 통해 지식 기반 RAG 검색과 계산 툴 실행 사이를 자동으로 라우팅
- **고급 문서 수집**: 원시 문서(PDF/이미지/오디오)를 LangGraph 상태 머신과 체크포인트 영속성을 통해 Markdown 청크 및 구조화된 그래프 메타데이터로 변환
- **지능형 검색 라우팅**: 쿼리 복잡도에 따라 세 가지 검색 경로(Vector, Weaviate Cross-Reference GraphRAG, Neo4j Deep Graph Traversal) 중 하나를 품질 게이트 백트래킹과 함께 동적으로 선택
- **툴 호출 프레임워크**: API 호출, 코드 실행, 단순 연산, 데이터베이스 쿼리를 위한 MCP(Model Context Protocol) 서버 통합 및 로컬 fallback
- **Graph-of-Thought 추론**: 복잡한 분석 쿼리를 위한 멀티 브랜치 탐색 및 스냅샷 기반 백트래킹

<div align="center">
<img src="https://github.com/user-attachments/assets/441a4a4b-d239-45c1-b385-80ddd95f31e6" width="512" height="768" ></img><br/>
</div>

---

## 주요 기능

- **LangGraph 상태 머신**: 모든 워크플로우(수집, 쿼리 추론, 툴 실행, 요약, 마인드맵 생성)가 완전한 상태 영속성 및 복구를 위해 `MemorySaver` 체크포인팅을 갖춘 LangGraph `StateGraph` 위에서 동작합니다.

- **지능형 쿼리 라우팅**: LLM 기반 의도 분류가 쿼리가 지식 검색을 필요로 하는지 계산 툴 실행을 필요로 하는지 자동으로 결정합니다:
  - **지식 쿼리** → 3-way 검색 라우팅을 갖춘 RAG 파이프라인
  - **계산 쿼리** → 고급 수학(sqrt, log, trig, sigma)을 지원하는 AST 기반 안전 평가를 갖춘 계산기 툴
  - **데이터베이스 쿼리** → SQL 실행기 (계획됨)
  - **API 호출** → 설정 가능한 엔드포인트를 갖춘 HTTP API 호출기
  - **코드 실행** → 제한된 built-in을 갖춘 Python 샌드박스

- **체크포인트 & 지능형 백트래킹**: 모든 노드 전환이 체크포인트되며, 품질 게이트가 검색 결과를 평가하고 품질이 불충분할 때 지능형 경로 선택을 트리거합니다:
  - **품질 평가**: 관찰자 LLM이 각 경로 결과를 `QUALITY_GATE_THRESHOLD`에 대해 0.0–1.0으로 점수화
  - **스마트 경로 선택**: `PathSelector`가 쿼리 키워드, 홉 수, 경로 특성을 기반으로 남은 미시도 경로를 분석하여 가장 적합한 대안을 선택
  - **백트래킹 제한**: 무한 루프를 방지하기 위해 `MAX_BACKTRACK_COUNT`로 설정 가능
  - **상태 추적**: `tried_paths` 필드가 실패한 전략의 재시도를 방지

- **3-way 검색 라우팅**: 쿼리 복잡도(홉 수)가 최적의 검색 전략을 결정합니다:
  - **Path 1 – Vector RAG (≤ 2 홉)**: BM25 + 리랭커를 통한 late-chunked TextDocument 코퍼스에서의 빠른 의미 유사성 검색. 직접적인 사실 질문에 이상적.
  - **Path 2 – Weaviate Cross-Reference GraphRAG (3–5 홉)**: BM25 시드 엔티티 검색 후 Weaviate 내에서 멀티홉 cross-reference 탐색(source/target/event refs). 관계 워킹을 통해 쿼리 인접 엔티티와 이벤트를 표면화.
  - **Path 3 – Neo4j Deep Graph Traversal (≥ 6 홉)**: 스키마 집중 관계 추론을 위한 Cypher 기반 심층 그래프 탐색. 광범위한 그래프 탐색이 필요한 복잡한 다중 엔티티 쿼리 처리.
  - **홉 분류**: LLM 주요 분류와 키워드 기반 fallback을 갖춘 하이브리드 LLM + 휴리스틱 접근 방식으로 쿼리 복잡도 추정

- **Graph-of-Thought 확장**: 복잡한 분석 쿼리를 위한 스냅샷 기반 백트래킹을 갖춘 멀티 브랜치 추론:
  - **브랜치 탐색**: 각 단계에서 `GOT_BRANCH_FACTOR`개의 후보 쿼리를 병렬로 확장
  - **품질 점수화**: 관찰자 LLM이 각 브랜치를 관련성, 범위, 참신성에 대해 0.0–1.0으로 평가
  - **지능형 병합**: `GOT_THOUGHT_SCORE_THRESHOLD` 이상의 브랜치를 설정 가능한 전략(`top_k`/`weighted_union`/`vote`)을 통해 병합
  - **엣지 가지치기**: 키워드 오버랩 점수화(`GOT_EDGE_PRUNE_THRESHOLD`)로 저품질 연결 제거
  - **실패 복구**: 연속적인 전체 브랜치 실패가 마지막 성공적인 병합 지점으로의 스냅샷 롤백을 트리거

- **SGLang 추론 생태계**: 모든 LLM 작업(생성, 임베딩, 리랭킹, 홉 분류, 품질 평가)이 지능형 생명주기 관리를 갖춘 SGLang 서버에서 실행됩니다:
  - **지연 로딩 아키텍처**: 서버가 첫 요청 시 자동 시작되어 초기화 중 콜드 스타트 오버헤드 제거
  - **유휴 타임아웃**: 비활성 `SGLANG_IDLE_TIMEOUT`(기본 60초) 후 GPU 메모리 자동 해제
  - **GPU 할당**: 서버별(generator, embedding, reranker, refiner) 설정 가능한 장치 할당 및 메모리 비율
  - **Keepalive 메커니즘**: 장시간 실행 작업 중 서버 상태를 유지하는 백그라운드 스레드
  - **청크 재시도 로직**: LLM 메타데이터 추출이 서버 재시작과 함께 실패한 청크를 자동 재시도(`GRAPH_EXTRACTOR_RETRY_ON_FAILURE`로 설정 가능)

- **툴 호출 프레임워크**: 로컬 fallback을 갖춘 MCP(Model Context Protocol) 서버 통합:
  - **MCP 우선 아키텍처**: MCP 서버가 사용 가능할 때(`MCP_SERVER_ENABLED=true`) MCP 서버를 통한 주요 실행
  - **로컬 fallback**: MCP 서버를 사용할 수 없을 때 로컬 구현으로 자동 fallback
  - **계산기**: 고급 수학 함수(sqrt, cbrt, log, exp, sin, cos, tan, sigma)를 지원하는 AST 기반 안전 표현식 평가
  - **자연어 파싱**: 한국어/영어 수학 표현식("144의 제곱근", "루트 144")을 실행 가능한 코드로 변환
  - **API 호출기**: 설정 가능한 엔드포인트 및 메서드를 갖춘 HTTP 요청 실행
  - **코드 러너**: 보안을 위한 제한된 built-in 및 토큰 필터링을 갖춘 Python 샌드박스
  - **SQL 실행기**: 향후 데이터베이스 쿼리 지원을 위한 플레이스홀더

- **자동 그래프 구축**: 원시 문서에서 쿼리 가능한 지식 그래프까지의 엔드투엔드 파이프라인:
  - **OCR 처리**: SGLang 기반 OCRFlux가 문서를 Markdown으로 변환
  - **LLM 추출**: 설정 가능한 청크 크기 및 타임아웃을 갖춘 Markdown 청크에서 엔티티/이벤트/관계 추출
  - **이중 저장소**: 결정론적 UUID를 갖춘 Weaviate(cross-reference 그래프) 및 Neo4j(심층 그래프)로의 동시 업서트
  - **스키마 관리**: cross-reference 정의를 갖춘 자동 Weaviate 컬렉션 생성

- **비동기 작업 모니터링**: REST API를 통한 전체 작업 생명주기 추적:
  - **업로드 진행 상황**: 파일 업로드 및 처리 단계에 대한 실시간 상태
  - **OCR 진행 상황**: 페이지별 OCR 완료 추적
  - **임베딩 진행 상황**: 청크 수준 인덱싱 상태
  - **작업 취소**: 장시간 실행 작업의 우아한 종료

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

**Tool Router**: LLM 기반 의도 분류가 쿼리 라우팅 전략을 결정합니다:
- **분류 엔드포인트**: `TOOL_INTENT_CLASSIFIER_ENDPOINT`로 설정 가능 (기본값은 SGLang generator)
- **의도 카테고리**: `knowledge`, `calculation`, `database`, `api_call`, `code_exec`
- **라우팅 로직**:
  - `knowledge` → RAG 파이프라인 (3-way 검색 라우팅)
  - 기타 의도 → Tool executor (MCP/로컬 fallback)
- **Fallback 메커니즘**: LLM 분류 실패 시 휴리스틱 키워드 매칭

**Tool Executor** (`backend/notebooklm/tools/tool_executor.py`):
- **MCP 통합**: `MCP_SERVER_ENABLED=true`일 때 MCP 서버 REST API를 통한 주요 실행
- **로컬 fallback**: MCP를 사용할 수 없을 때 로컬 구현으로 자동 fallback
- **의도 분류**: 신뢰성을 위한 휴리스틱 fallback을 갖춘 LLM 기반
- **지원 툴**:
  - **계산기** (완전 구현):
    - AST 기반 안전 표현식 평가 (`eval()` 보안 위험 없음)
    - 고급 수학 함수: `sqrt`, `cbrt`, `abs`, `log`, `ln`, `log10`, `exp`, `sin`, `cos`, `tan`, `sigma`
    - 자연어 파싱: "144의 제곱근" → `sqrt(144)`, "2의 3제곱" → `2 ** 3`
    - 연산자 지원: `+`, `-`, `*`, `/`, `**`, `%`
  - **API 호출기** (경량 구현):
    - HTTP GET/POST 요청 실행
    - 자연어 프롬프트에서 URL 추출
    - 설정 가능한 타임아웃 및 오류 처리
  - **코드 러너** (샌드박스 구현):
    - 제한된 Python 실행 환경
    - 필터링된 built-in (`eval`, `exec`, `__import__` 없음)
    - 토큰 기반 보안 필터링
  - **SQL 실행기** (플레이스홀더):
    - `not_implemented` 상태 반환
    - 향후 데이터베이스 통합을 위해 예약됨

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

1. **플래너** (`planner` 노드):
   - **쿼리 분석**: 사용자 쿼리를 검사하고 핵심 개념 추출
   - **계획 기록**: 고수준 검색 전략 및 추론 단계 로깅
   - **히스토리 추적**: 다중 턴 대화를 위한 쿼리 컨텍스트 유지
   - **참고**: 홉 분류를 수행하지 않음 (더 나은 관심사 분리를 위해 `rag_router`로 이동)

2. **Tool Router** (`tool_router` 노드):
   - **의도 분류**: `ToolExecutor.classify_intent()`를 통한 LLM 기반 쿼리 의도 감지
   - **분류 카테고리**:
     - `knowledge`: 문서 검색이 필요한 사실 질문 → `rag_router`로 라우팅
     - `calculation`: 수학 연산 → `tool_executor`로 라우팅 (계산기)
     - `database`: SQL 쿼리 → `tool_executor`로 라우팅 (SQL 실행기)
     - `api_call`: 외부 API 요청 → `tool_executor`로 라우팅 (API 호출기)
     - `code_exec`: 코드 실행 요청 → `tool_executor`로 라우팅 (코드 러너)
   - **라우팅 결정**: 지식 쿼리는 RAG 파이프라인으로 진행; 계산 작업은 RAG를 건너뛰고 툴을 직접 실행

3. **RAG Router** (`rag_router` 노드, 지식 쿼리만):
   - **홉 분류**: 쿼리 복잡도를 추정하는 하이브리드 LLM + 휴리스틱 접근 방식
     - **LLM 분류기**: SGLang 서버를 통한 주요 분류 (1–`GRAPH_MAX_HOPS`)
     - **휴리스틱 fallback**: 키워드 기반 점수화 (화살표 개수, 개념 구분자, 관계 지표)
     - **최종 홉 수**: 보수적 라우팅을 위한 `min(llm_estimate, heuristic_estimate, GRAPH_MAX_HOPS)`
   - **경로 선택**: 홉 수를 최적의 검색 전략에 매핑
     - 홉 ≤ 2 → Path 1 (VectorRetriever)
     - 홉 3–5 → Path 2 (CrossRefRetriever)
     - 홉 ≥ 6 → Path 3 (GraphDBRetriever)
   - **상태 업데이트**: `max_hops`, `retrieval_path` 설정 및 `tried_paths` 추적 초기화

4. **Tool Executor** (`tool_executor` 노드, 계산 작업용):
   - **툴 매핑**: 의도를 특정 툴 구현에 매핑
   - **입력 준비**: 쿼리에서 관련 매개변수 추출 (표현식, URL, 코드 스니펫, SQL)
   - **실행 전략**:
     - **MCP 우선**: MCP 서버 REST API를 통한 실행 시도
     - **로컬 fallback**: MCP를 사용할 수 없거나 실패하면 로컬 구현으로 fallback
   - **결과 포맷팅**: 상태, 결과 값, 메타데이터를 갖춘 구조화된 결과 반환
   - **오류 처리**: 실행 오류를 캡처하고 실패 메시지 반환 (RAG로 fallback하지 않음)

5. **검색 노드** (지식 쿼리용):
   - **Path 1 – Vector RAG** (`vector_retriever`):
     - TextDocument 컬렉션에서 BM25 기반 의미 검색
     - 관련성 최적화를 위한 리랭커 후처리
     - 단순 사실 쿼리를 위한 빠른 실행
   - **Path 2 – Cross-Ref GraphRAG** (`crossref_retriever`):
     - GraphEntity 컬렉션에서 BM25 시드 엔티티 검색
     - Weaviate `QueryReference`를 통한 멀티홉 cross-reference 탐색
     - source/target/event 관계를 걸어 연결된 엔티티 표면화
     - Neo4j escalation 전에 Weaviate 내에서 쿼리 인접 컨텍스트 수집
   - **Path 3 – Neo4j GraphDB** (`graphdb_retriever`):
     - `LegacyGraphClient`를 통한 심층 Cypher 기반 그래프 탐색
     - 스키마 집중 관계 추론
     - 광범위한 그래프 탐색이 필요한 복잡한 다중 엔티티 쿼리 처리

6. **품질 게이트** (`quality_gate` 노드, 지식 쿼리용):
   - **품질 평가**: 관찰자 LLM이 검색 결과를 점수화 (0.0–1.0)
     - Path 1은 불필요한 LLM 호출을 피하기 위해 위임 시 기본값 1.0
     - Path 2와 3은 품질 평가를 위해 항상 평가됨
   - **통과 조건**: 품질 ≥ `QUALITY_GATE_THRESHOLD` → aggregator 또는 thought expander로 진행
   - **지능형 백트래킹**: 품질 < threshold가 스마트 경로 선택을 트리거
     - `PathSelector.select_best_path()`가 남은 미시도 경로 분석
     - 쿼리 키워드, 홉 수, 경로 특성을 기반으로 점수화
     - 가장 적합한 대체 경로 선택 (무작위 재시도 아님)
   - **종료 조건**:
     - 모든 경로 소진 → 최선의 컨텍스트로 계속 진행
     - `MAX_BACKTRACK_COUNT` 한도 도달 → `answer_notes`에 품질 저하 플래그
   - **상태 추적**: `tried_paths` 목록이 실패한 전략의 재시도를 방지

7. **GoT Thought Expander** (`thought_expander` 노드, `GOT_MODE_ENABLED=true`일 때):
   - **그래프 형태 탐색**: 복잡한 분석 쿼리를 위한 멀티 브랜치 추론
   - **브랜치 생성**: 각 단계에서 `GOT_BRANCH_FACTOR`개의 후보 쿼리를 병렬로 확장
   - **품질 점수화**: 관찰자 LLM이 각 브랜치를 평가 (0.0–1.0):
     - 원본 쿼리와의 관련성
     - 새로운 정보의 범위
     - 기존 브랜치와 비교한 참신성
   - **지능형 병합**: `GOT_THOUGHT_SCORE_THRESHOLD` 이상의 브랜치를 전략을 통해 병합:
     - `top_k`: 최고 점수 상위 K개 브랜치 선택
     - `weighted_union`: 점수 기반 가중치로 병합
     - `vote`: 브랜치 간 민주적 선택
   - **엣지 가지치기**: 키워드 오버랩 점수화를 통해 저품질 연결 (< `GOT_EDGE_PRUNE_THRESHOLD`) 제거
   - **스냅샷 기반 백트래킹**: 연속적인 전체 브랜치 실패가 상태 롤백을 트리거
     - `GOT_MAX_CONSECUTIVE_FAILURES`를 통한 연속 실패 추적
     - 마지막 성공적인 병합 지점으로 롤백
     - 무한 탐색 루프 방지

8. **어그리게이터** (`aggregator` 노드):
   - **컨텍스트 구축**: 검색 결과 또는 툴 출력에서 컨텍스트 스니펫 조립
   - **RAG 쿼리용**: 엔티티, 이벤트, 관계, 사고 단계를 일관된 컨텍스트로 병합
   - **툴 쿼리용**: 툴 결과를 자연어 응답으로 포맷팅
     - 계산기: "표현식 = 결과" 형식 (예: "sqrt(144) = 12.0")
     - API/코드: 결과 값 또는 성공 메시지
     - 오류: 사용자 친화적 오류 메시지
   - **메타데이터 수집**: 디버깅을 위한 `context_snippets`, `thought_steps`, `backtrack_count`, `tried_paths` 수집

9. **생성** (`generator.py`):
   - **답변 합성**: 원본 쿼리 + 컨텍스트 스니펫 (또는 툴 결과)을 병합하여 최종 답변 생성
   - **RAG 쿼리용**: LLM이 검색된 컨텍스트에서 답변 생성
   - **툴 쿼리용**: 포맷팅된 툴 결과를 직접 반환 (LLM 생성 불필요)
   - **후처리**: `refiner.py`를 통한 선택적 정제 및 `evaluator.py`를 통한 품질 평가

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
├── data_pipeline/                    # 데이터 처리 파이프라인
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

1. **요청 시작**: `POST /v1/chat` → `RAGPipeline.process_query()`가 `GraphReasoner.retrieve()` 호출

2. **LangGraph 워크플로우 실행** (`graph_reasoner.py`):

   **단계 1: 플래너** (`planner` 노드)
   - 사용자 쿼리를 분석하고 핵심 개념 추출
   - 고수준 검색 계획 및 추론 단계 기록
   - 다중 턴 컨텍스트를 위한 쿼리 히스토리 초기화
   - **출력**: `plan`, `query_analysis`

   **단계 2: Tool Router** (`tool_router` 노드)
   - `ToolExecutor.classify_intent()`를 통한 LLM 쿼리 의도 분류:
     - `knowledge` → **rag_router**로 라우팅 (지식 검색 경로)
     - `calculation` → **tool_executor**로 라우팅 (계산기)
     - `database` → **tool_executor**로 라우팅 (SQL 실행기)
     - `api_call` → **tool_executor**로 라우팅 (API 호출기)
     - `code_exec` → **tool_executor**로 라우팅 (코드 러너)
   - **출력**: `intent`, 라우팅 결정

   **분기 A: 지식 쿼리 경로**

   **단계 3a: RAG Router** (`rag_router` 노드, 지식 쿼리용)
   - 홉 분류 수행 (LLM + 휴리스틱 하이브리드)
   - `max_hops` = `min(llm_estimate, heuristic_estimate, GRAPH_MAX_HOPS)` 설정
   - 초기 검색 경로 선택:
     - 홉 ≤ 2 → `vector_retriever` (Path 1)
     - 홉 3–5 → `crossref_retriever` (Path 2)
     - 홉 ≥ 6 → `graphdb_retriever` (Path 3)
   - **출력**: `max_hops`, `retrieval_path`, `tried_paths`

   **단계 4a: 검색 실행** (Path 1/2/3)
   - **Path 1**: TextDocument에서 BM25 의미 검색 + 리랭커
   - **Path 2**: BM25 시드 검색 + Weaviate cross-reference 멀티홉 탐색
   - **Path 3**: Neo4j Cypher 심층 그래프 탐색
   - **출력**: `context_snippets`, `entities`, `events`, `relations`

   **단계 5a: 품질 게이트** (`quality_gate` 노드)
   - 관찰자 LLM이 검색 결과 점수화 (0.0–1.0)
   - **품질 ≥ `QUALITY_GATE_THRESHOLD`인 경우**:
     - aggregator 또는 thought expander로 진행 (GoT 활성화 시)
   - **품질 < threshold인 경우**:
     - 지능형 백트래킹 트리거:
       - `PathSelector.select_best_path()`가 남은 경로 분석
       - 쿼리 키워드, 홉 수, 경로 특성을 기반으로 점수화
       - 가장 적합한 대안 선택 (무작위 아님)
       - 새 경로로 단계 4a로 돌아감
     - **종료**: `MAX_BACKTRACK_COUNT` 재시도 후 또는 모든 경로 소진
   - **출력**: `retrieval_quality`, `backtrack_count`, `tried_paths`

   **단계 6a: Thought Expander** (`thought_expander` 노드, `GOT_MODE_ENABLED=true`인 경우)
   - `GOT_BRANCH_FACTOR`개의 후보 쿼리를 병렬로 확장
   - 관찰자 LLM이 각 브랜치 점수화 (0.0–1.0)
   - `GOT_THOUGHT_SCORE_THRESHOLD` 이상의 브랜치를 전략을 통해 병합
   - 저품질 엣지 가지치기 (< `GOT_EDGE_PRUNE_THRESHOLD`)
   - 연속 실패 시 스냅샷 기반 백트래킹
   - **출력**: `thought_steps`, 확장된 컨텍스트

   **분기 B: 툴 실행 경로**

   **단계 3b: Tool Executor** (`tool_executor` 노드, 계산 작업용)
   - 의도를 특정 툴에 매핑:
     - `calculation` → 계산기 (AST 기반 안전 평가)
     - `api_call` → API 호출기 (HTTP 요청)
     - `code_exec` → 코드 러너 (Python 샌드박스)
     - `database` → SQL 실행기 (플레이스홀더)
   - 툴 입력 준비:
     - 계산기: 수학 표현식 추출, 자연어 변환 ("144의 제곱근" → `sqrt(144)`)
     - API 호출기: 프롬프트에서 URL 추출
     - 코드 러너: 코드 스니펫 추출
   - 툴 실행:
     - **MCP 우선**: MCP 서버 REST API를 통한 실행 시도
     - **로컬 fallback**: MCP를 사용할 수 없으면 로컬 구현으로 fallback
   - **출력**: 상태(`ok`/`error`), 결과 값, 메타데이터를 갖춘 `tool_result`
   - **참고**: 툴 실패는 오류 메시지 반환; RAG로 fallback하지 않음

   **단계 7: 어그리게이터** (`aggregator` 노드)
   - **RAG 쿼리용**: 엔티티/이벤트/관계/사고에서 컨텍스트 스니펫 구축
   - **툴 쿼리용**: 툴 결과를 자연어로 포맷팅:
     - 계산기: `"표현식 = 결과"` (예: `"sqrt(144) = 12.0"`)
     - API/코드: 결과 값 또는 성공 메시지
     - 오류: 사용자 친화적 오류 메시지
   - 메타데이터 수집: `context_snippets`, `thought_steps`, `backtrack_count`, `tried_paths`, `tool_result`
   - **출력**: 집계된 컨텍스트 또는 포맷팅된 툴 결과

3. **답변 생성**:
   - **RAG 쿼리용**: `generator.py`가 원본 쿼리 + 컨텍스트 스니펫에서 답변 합성
   - **툴 쿼리용**: 포맷팅된 툴 결과를 직접 반환 (LLM 생성 불필요)
   - **선택적 후처리**: `refiner.py`가 답변 다듬기, `evaluator.py`가 품질 노트 로깅

4. **응답 구성** (`RAGPipeline._build_response()` 또는 `_build_tool_only_response()`):
   - **RAG 쿼리용**: 답변, 컨텍스트, 스니펫, 검색 결과를 갖춘 전체 응답
   - **툴 쿼리용**: 툴 결과를 답변으로 갖춘 간소화된 응답
   - **포함된 메타데이터**: `plan`, `max_hops`, `retrieval_quality`, `backtrack_count`, `tried_paths`, `thought_steps`, `tool_result` (해당하는 경우)
   - **디버깅 지원**: 추적성을 위해 노출된 모든 워크플로우 상태

5. **클라이언트로 반환**: 답변, 메타데이터, 디버깅 정보를 갖춘 JSON 응답

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
