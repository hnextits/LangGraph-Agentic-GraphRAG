# MD Document Summarization System

H100 2장 환경에서 SGLang과 Qwen3를 활용한 고성능 문서 요약 시스템

## 시스템 특징

- **고속 처리**: SGLang의 RadixAttention으로 최적화된 추론
- **병렬 처리**: H100 2장을 활용한 멀티 GPU 처리
- **MD 문서 특화**: 마크다운 구조 인식 및 파싱
- **요약 인덱스**: 문서 수준 RAG로 효율적인 검색

## 아키텍처

```
┌─────────────────┐
│  MD Documents   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  MD Parser      │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────┐
│  SGLang Server (H100 x2)    │
│  - GPU 0: Qwen2.5-14B       │
│  - GPU 1: Qwen2.5-14B       │
└────────┬────────────────────┘
         │
         ▼
┌─────────────────┐
│ Summary Index   │
│ - Documents     │
│ - Summaries     │
│ - Rankings      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  FastAPI Server │
└─────────────────┘
```

## 디렉토리 구조

```
md_summarizer/
├── README.md
├── requirements.txt
├── config/
│   ├── model_config.yaml
│   └── server_config.yaml
├── scripts/
│   ├── start_sglang_dual.sh
│   ├── start_sglang_single.sh
│   └── benchmark.py
├── src/
│   ├── __init__.py
│   ├── md_parser.py
│   ├── summary_index.py
│   ├── sglang_client.py
│   └── api_server.py
├── tests/
│   ├── test_md_parser.py
│   ├── test_summary_index.py
│   └── sample_documents/
└── examples/
    └── usage_example.py
```

## 설치 방법

```bash
# 1. 환경 생성
conda create -n md_summarizer python=3.10
conda activate md_summarizer

# 2. 의존성 설치
pip install -r requirements.txt

# 3. SGLang 설치
pip install "sglang[all]"

# 4. 모델 다운로드 (선택)
huggingface-cli download Qwen/Qwen2.5-14B-Instruct
```

## 사용 방법

### 1. SGLang 서버 시작 (듀얼 GPU)

```bash
bash scripts/start_sglang_dual.sh
```

### 2. API 서버 시작

```bash
python src/api_server.py
```

### 3. 문서 요약

```python
from src.summary_index import MDSummaryIndex

# 초기화
summarizer = MDSummaryIndex(
    sglang_endpoints=["http://localhost:30000", "http://localhost:30001"]
)

# 문서 추가
summarizer.add_document("doc1", "path/to/document.md")

# 요약 생성
summarizer.generate_summaries()

# 검색
results = summarizer.search("특정 주제에 대한 내용")
```

## 성능 최적화

### H100 2장 활용 전략

1. **듀얼 서버 모드**: 각 GPU에 별도 SGLang 인스턴스
2. **로드 밸런싱**: 라운드 로빈 방식으로 요청 분산
3. **배치 처리**: 여러 문서를 동시에 처리

### 예상 성능

- **Qwen2.5-14B 기준**
  - 단일 GPU: ~50-80 tokens/sec
  - 듀얼 GPU: ~100-160 tokens/sec
  - 문서당 요약 시간: 2-5초 (문서 길이에 따라)

## 연동 가이드

기존 시스템과 연동하기 위한 REST API 제공:

```bash
POST /api/v1/documents/add
POST /api/v1/summaries/generate
GET  /api/v1/search?query=검색어
GET  /api/v1/documents/{doc_id}/summary
```

## 라이선스

MIT License
