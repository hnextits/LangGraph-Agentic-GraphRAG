# NextitsLM SGLang 프로젝트 개요

NextITSLM SGLang은 RAG (Retrieval-Augmented Generation) 기술을 기반으로 하는 차세대 지능형 학습 관리 시스템입니다. 텍스트와 이미지를 모두 처리하는 멀티모달 AI 시스템으로, 고성능 SGLang 기반 LLM 인프라를 활용하여 실시간으로 정확한 문서 검색 및 질의응답 서비스를 제공합니다.

---

## 주요 기능

### AI 기반 지능형 Q&A 시스템
- **멀티모달 RAG**: 텍스트와 이미지를 동시에 처리하는 통합 검색 및 질의응답
- **고속 실시간 응답**: SGLang 기반의 LLM 서비스로 응답 속도 달성 최적화
- **지능형 질의 라우팅**: 질의 유형을 분석하여 텍스트/이미지 검색기를 병렬로 실행
- **답변 정제 및 평가**: 검색된 컨텍스트를 활용한 정확한 답변 생성, 답변 품질 자동 평가 및 정제 기능
- **자동 서버 관리**: SGLang 임베딩/리랭커 서버가 첫 요청 시 자동으로 시작되어 지속적으로 실행

### 데이터 처리 및 인프라
- **문서 처리 파이프라인**: OCR, 레이아웃 분석, Late Chunking을 통한 문서 구조화 및 배치 처리
- **고성능 벡터 검색**: Weaviate 기반 벡터 데이터베이스를 활용한 고성능 유사도 검색 엔진
- **웹 크롤링 및 수집**: Google 검색 API 및 웹 크롤링을 통한 콘텐츠 자동 수집 및 정제
- **실시간 모니터링**: 문서 처리 및 비동기 작업의 진행 상태 추적

---

## 시스템 아키텍처

> #### 최근 업데이트: SGLang 서버 자동 시작 & 메모리 최적화
> - **SGLang 서버 자동 관리**: 임베딩 및 리랭커 서버가 첫 요청 시 자동으로 시작되어 백그라운드에서 지속 실행
> - **메모리 최적화**: Generator(20%), Summarizer(15%), Embedding(15%), Reranker(15%)로 GPU 메모리 효율적 분배
> - **Lazy Loading**: `LazyModelManager`가 Answer/RAG/Mindmap 모델을 `idle_timeout=20s`로 등록
> - **GPU Cleanup**: `cleanup_rag_pipeline()`이 RAGRouter·검색기·QueryRewriter·SharedEmbedding·리랭커까지 정리
> - **서버 시작 로그**: 첫 문서 업로드 시 `임베딩 서버 시작 중...`, 첫 리랭킹 시 `리랭커 서버 시작 중...` 메시지 확인
> - GPU 상태 확인: (1) 요청 실행 → (2) 20초 대기 → (3) 로그 확인 → (4) `nvidia-smi`로 메모리 확인

NextITSLM SGL은 모듈화된 3-Tier 아키텍처로 설계되었습니다.


```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Frontend      │    │   Backend API   │    │   LLM Service   │
│   (React)       │◄──►│   (FastAPI)     │◄──►│   (SGLang)      │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                               │
                      ┌─────────────────┐
                      │   Weaviate      │
                      │   (Vector DB)   │
                      └─────────────────┘
```

```TSX
graph LR
    A[Frontend (Next.js/React)] -->|REST API| B(Backend API (FastAPI));
    B -->|Query/Context| C(LLM Service (SGLang));
    B -->|Vector Search| D(Weaviate (Vector DB));
    D -->|Embeddings| B;
    C -->|Generated Answer| B;
    B -->|Final Response| A;
```

```
nextitslm/
├── backend/                     # 백엔드 서버 (FastAPI)
│   ├── api/                    # API 라우터
│   │   ├── chat.py            # 채팅 API
│   │   ├── routes.py          # 메인 라우트
│   │   └── pause_api.py       # 일시정지 API
│   ├── notebooklm/             # RAG 시스템 핵심 모듈
│   │   ├── rag_pipeline.py    # RAG 파이프라인 오케스트레이터
│   │   ├── shared_embedding.py # SGLang 임베딩 서버 클라이언트
│   │   ├── embedding_text.py  # 텍스트 임베딩 파이프라인 (Weaviate 업서트)
│   │   ├── embedding_image.py # 이미지 임베딩 파이프라인 (Weaviate 업서트)
│   │   ├── generator.py       # LLM 답변 생성기
│   │   ├── evaluator.py       # 답변 품질 평가기
│   │   ├── refiner.py         # 답변 정제기
│   │   ├── router.py          # 질의 라우팅
│   │   ├── query_rewriter.py  # 질의 재작성
│   │   ├── parallel_search.py # 병렬 검색
│   │   ├── qwen3_late_chunking.py # Late Chunking 구현
│   │   ├── weaviate_utils.py  # Weaviate 유틸리티
│   │   ├── rag_text/          # 텍스트 검색 모듈
│   │   │   ├── text_search.py
│   │   │   └── text_reranker_improved_2.py
│   │   └── rag_image/         # 이미지 검색 모듈
│   │       ├── image_search.py
│   │       └── image_reranker.py
│   ├── nextits_data/           # 데이터 처리 파이프라인
│   ├── search_test/            # 웹 크롤링 모듈
│   ├── services/               # 비즈니스 로직 서비스
│   ├── utils/                  # 유틸리티 함수
│   ├── main.py                 # FastAPI 메인 서버
│   ├── app.py                  # 애플리케이션 설정
│   └── requirements.txt        # Python 의존성
├── frontend/                   # 프론트엔드 (Next.js)
│   └── src/
│       ├── components/         # React 컴포넌트
│       ├── pages/              # 페이지 컴포넌트
│       └── styles/             # 스타일 정의
├── pyproject.toml              # Poetry 프로젝트 설정
├── poetry.lock                 # Poetry 의존성 잠금 파일
└── Jenkinsfile                 # CI/CD 파이프라인
```

## 백엔드 구조 상세

### 1. 메인 애플리케이션 (`main.py`)
- **FastAPI 서버**: 비동기 웹 서버 프레임워크
- **CORS 미들웨어**: 크로스 오리진 요청 처리
- **LazyModelManager 초기화**: RAG/Answer/Mindmap 빌더를 lazy 등록하고 GPU 리소스를 자동 회수 (`idle_timeout=20s`)
- **API 라우터 통합**: 모든 엔드포인트를 중앙에서 관리

### 2. RAG 시스템 (`notebooklm/`)

#### 핵심 컴포넌트
- **`rag_pipeline.py`**: RAG 시스템의 메인 오케스트레이터
  - 질의 라우팅, 검색, 답변 생성, 평가의 전체 파이프라인 관리
  - 텍스트/이미지 검색 결과 통합 및 base64 이미지 변환
  - 피드백 루프 및 답변 정제 기능

- **`shared_embedding.py`**: SGLang 기반 임베딩 시스템
  - SGLang 서버를 OpenAI 호환 API로 호출하는 클라이언트
  - 첫 요청 시 SGLang 임베딩 서버 자동 시작 (포트 30001)
  - Qwen3-Embedding-4B 모델 사용 (GPU 메모리 15% 할당)
  - 싱글톤 패턴으로 구현되어 전역적으로 공유
  - 서버 상태 자동 확인 및 재시작 기능

- **`embedding_text.py` / `embedding_image.py`**: 데이터 업서트 파이프라인
  - `shared_embedding`을 통해 SGLang 임베딩 서버에 질의하여 벡터 생성
  - 텍스트/이미지 청크를 전처리하고 Weaviate에 업서트
  - Late Chunking, 정규화 등 RAG 파이프라인 전용 로직 유지

- **`qwen3_late_chunking.py`**: Late Chunking 구현
  - 문서를 청킹한 후 임베딩하는 대신, 전체 문서를 임베딩한 후 청킹
  - 청크 간 컨텍스트 보존으로 검색 품질 향상
  - Qwen3 모델에 최적화된 구현

- **`router.py`**: 지능형 질의 라우팅
  - 질의 유형 분석 및 적절한 검색기 선택
  - 텍스트/이미지 검색기 병렬 실행

- **`generator.py`**: LLM 기반 답변 생성
  - 검색된 컨텍스트를 활용한 정확한 답변 생성
  - 프롬프트 엔지니어링 및 응답 품질 최적화

- **`evaluator.py`**: 답변 품질 평가
  - 생성된 답변의 품질 자동 평가
  - 피드백 기반 답변 개선

- **`refiner.py`**: 답변 정제
  - 생성된 답변의 품질 향상 및 일관성 보장

#### 검색 시스템
- **텍스트 검색** (`rag_text/`)
  - `text_search.py`: Weaviate 기반 시맨틱 검색
  - `text_reranker_improved_2.py`: SGLang 기반 리랭커 (Qwen3-Reranker-4B)
    - 첫 요청 시 SGLang 리랭커 서버 자동 시작 (포트 30002)
    - GPU 메모리 15% 할당으로 효율적 운영
- **이미지 검색** (`rag_image/`)
  - `image_search.py`: 이미지 임베딩 기반 유사도 검색
  - `image_reranker.py`: SGLang 기반 이미지 리랭커 (Qwen3-Reranker-8B)
    - 텍스트 리랭커와 동일한 서버 공유 (포트 30002)
- **병렬 검색** (`parallel_search.py`): 다중 검색기 동시 실행으로 성능 최적화

#### 설정 관리 (`config.py`)
- **모델 설정**: 임베딩 모델, 생성 모델 설정
- **경로 설정**: 데이터, 인덱스, 캐시 경로 관리
- **성능 튜닝**: 배치 크기, 디바이스 설정 등

### 3. 데이터 처리 파이프라인 (`nextits_data/`)

#### 파이프라인 구조 (`pipe/`)
- **텍스트 문서 처리 파이프라인**
  - 레이아웃 JSON 파일 처리
  - 텍스트 블록 정렬 및 구조화
  - 마크다운 변환 및 Late Chunking 적용

- **이미지 문서 처리 파이프라인**
  - 이미지 OCR 및 레이아웃 분석
  - 이미지 임베딩 생성 및 인덱싱

#### 처리 단계
1. **문서 업로드**: 다양한 형식의 문서 지원 (PDF, 이미지 등)
2. **OCR 처리**: 텍스트 추출 및 레이아웃 분석
3. **구조화**: 텍스트 블록 정렬 및 의미 단위 분할
4. **Late Chunking**: 전체 문서 임베딩 후 청킹으로 컨텍스트 보존
5. **임베딩 생성**: 텍스트/이미지 임베딩 벡터 생성
6. **인덱싱**: Weaviate 벡터 인덱스 구축

### 4. API 엔드포인트 (`api/`)

#### 주요 엔드포인트
- **`POST /v1/chat`**: RAG 기반 질의응답 (chat.py)
- **`POST /search`**: 웹 검색 수행
- **`POST /add_document_from_search`**: 검색 결과에서 문서 추가
- **`POST /upload`**: 파일 업로드 및 처리
- **`POST /search_and_summarize`**: 검색 및 요약
- **`GET /task_status/{task_id}`**: 비동기 작업 상태 확인
- **`GET /files`**: 문서 목록 조회
- **`GET /file/{filename}`**: 문서 내용 조회
- **`POST /pause`**: 작업 일시정지 (pause_api.py)

#### 비동기 처리
- **백그라운드 작업**: 파일 처리, 인덱싱 등 시간이 오래 걸리는 작업
- **작업 상태 추적**: 실시간 진행 상황 모니터링
- **오류 처리**: 견고한 예외 처리 및 로깅

### 5. 웹 크롤링 (`search_test/`)
- **Google 검색 API**: 검색 결과 수집
- **웹 페이지 크롤링**: 검색 결과 페이지 내용 추출
- **콘텐츠 정제**: HTML 파싱 및 텍스트 추출
- **마크다운 변환**: 구조화된 문서 형태로 저장

## 프론트엔드 구조 (`frontend/`)

### 기술 스택
- **Next.js 14**: React 기반 풀스택 프레임워크
- **TypeScript**: 타입 안전성 보장
- **Material-UI**: 현대적이고 일관된 UI 컴포넌트
- **Tailwind CSS**: 유틸리티 우선 CSS 프레임워크
- **Axios**: HTTP 클라이언트

### 주요 컴포넌트
- **채팅 인터페이스**: 실시간 질의응답 UI
- **파일 업로드**: 드래그 앤 드롭 파일 업로드
- **검색 결과 표시**: 텍스트 및 이미지 검색 결과 시각화
- **작업 상태 모니터링**: 비동기 작업 진행 상황 표시

## 설치 및 실행

### 백엔드 설정

1. **의존성 설치**
```bash
cd backend
pip install -r requirements.txt
```

2. **환경 변수 설정**
```bash
# .env 파일 생성
cp .env.sample .env
# 필요한 환경 변수 설정 (API 키, 모델 경로 등)
```

3. **서버 실행**
```bash
python main.py
# SGLang 임베딩/리랭커 서버는 첫 요청 시 자동으로 시작됩니다
# 로그에서 "임베딩 서버 시작 중..." 메시지를 확인하세요
```

### 프론트엔드 설정

1. **의존성 설치**
```bash
cd frontend
npm install
```

2. **개발 서버 실행**
```bash
npm run dev
```

3. **프로덕션 빌드**
```bash
npm run build
npm start
```

## 주요 설정

### 모델 설정
- **임베딩 모델**: Qwen3-Embedding-4B (SGLang 서버, GPU 메모리 15%)
- **리랭커 모델**: Qwen3-Reranker-4B/8B (SGLang 서버, GPU 메모리 15%)
- **생성 모델**: Qwen3-8B (SGLang Engine, GPU 메모리 20%)
- **요약 모델**: Qwen3-4B-Instruct-2507 (SGLang Engine, GPU 메모리 15%)
- **디바이스**: GPU 1 (임베딩/리랭커), GPU 0 (생성/요약)
- **Late Chunking**: 컨텍스트 보존을 위한 청킹 기법 적용

### 성능 최적화

- **SGLang 서버 자동 관리**: 임베딩/리랭커 서버가 첫 요청 시 자동 시작되어 지속 실행
- **메모리 효율화**: GPU 메모리를 Generator(20%), Summarizer(15%), Embedding(15%), Reranker(15%)로 최적 분배
- **Late Chunking**: 컨텍스트 보존으로 검색 품질 향상
- **병렬 검색**: 텍스트/이미지 검색 동시 실행
- **캐싱**: 작업 상태 1시간 캐시 유지
- **비동기 처리**: 백그라운드 작업 처리
- **Lazy Loading**: `LazyModelManager`가 RAG/Answer/Mindmap 모델을 요청 시점에만 로드
- **GPU Cleanup**: `cleanup_rag_pipeline()`이 모든 리소스 자동 해제
- **벡터 검색 최적화**: Weaviate 인덱싱 최적화

### 확장성
- **모듈화**: 각 컴포넌트 독립적 개발 및 테스트 가능
- **플러그인 아키텍처**: 새로운 검색기 및 처리기 쉽게 추가
- **API 우선**: RESTful API로 다양한 클라이언트 지원

## 데이터 플로우

### 문서 처리 플로우
1. **문서 입력**: 파일 업로드 또는 웹 크롤링
2. **전처리**: OCR, 레이아웃 분석, 텍스트 추출
3. **구조화**: Late Chunking 및 메타데이터 추출
4. **임베딩**: 텍스트/이미지 벡터 임베딩 생성
5. **인덱싱**: Weaviate 벡터 인덱스 구축

### 질의응답 플로우
1. **질의 입력**: 사용자 질문 수신
2. **질의 분석**: 라우터가 질의 유형 분석
3. **병렬 검색**: 텍스트/이미지 검색 실행
4. **재순위화**: 검색 결과 재순위화 및 필터링
5. **답변 생성**: SGLang 기반 LLM으로 답변 생성
6. **답변 평가**: 답변 품질 자동 평가
7. **답변 정제**: 필요시 답변 개선 및 최종 응답

## 로깅 및 모니터링

- **구조화된 로깅**: 각 컴포넌트별 상세 로그
- **성능 메트릭**: 응답 시간, 메모리 사용량 추적
- **오류 추적**: 예외 상황 자동 로깅 및 알림
- **작업 상태**: 비동기 작업 진행 상황 실시간 모니터링
- **SGLang 서버 로그**: `sglang_embedding_server.log`, `sglang_reranker_server.log` 파일 확인
- **GPU 상태 확인 절차**
  1. `/api/v1/chat` 등 RAG 요청 수행 후 응답 완료까지 대기
  2. 첫 요청 시 "임베딩 서버 시작 중...", "리랭커 서버 시작 중..." 로그 확인
  3. 20초 동안 추가 요청이 없으면 LazyModelManager가 모델 언로드
  4. `nvidia-smi`로 GPU 사용량 확인 (GPU 0: Generator+Summarizer, GPU 1: Embedding+Reranker)
  5. SGLang 서버는 백그라운드에서 계속 실행됨 (종료: `pkill -f sglang.launch_server`)

## 보안 및 안정성

- **입력 검증**: 모든 사용자 입력에 대한 엄격한 검증
- **파일 안전성**: 업로드 파일 타입 및 크기 제한
- **API 보안**: CORS 설정 및 요청 제한
- **오류 복구**: 견고한 예외 처리 및 자동 복구

## 개발 및 기여

### 코드 구조
- **모듈화**: 각 기능별 독립적인 모듈 구조
- **타입 안전성**: Python 타입 힌트 및 TypeScript 활용
- **문서화**: 상세한 주석 및 독스트링
- **테스트**: 단위 테스트 및 통합 테스트 지원

### 개발 가이드라인
- **코드 스타일**: PEP 8 (Python), ESLint (JavaScript/TypeScript)
- **커밋 메시지**: 명확하고 설명적인 커밋 메시지
- **브랜치 전략**: 기능별 브랜치 및 PR 기반 개발
- **코드 리뷰**: 모든 변경사항에 대한 코드 리뷰

## 라이선스

이 프로젝트는 MIT, Apache-2.0 라이선스 하에 배포됩니다.

## 연락처
#### backend
프로젝트에 대한 문의사항이나 기여를 원하시면 이슈를 생성하거나 PR, E-mail을 제출해 주세요.

- **RAG**
  - jeongnext@hnextits.com 
- **OCR**
  - junseung_lim@hnextits.com

#### frontend

- **UX/UI**
  - fbgjungits@hnextits.com
