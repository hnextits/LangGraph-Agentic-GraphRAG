# 기존 nextitslm 시스템과 통합 가이드

## 개요

이 문서는 새로운 `md_summarizer` 시스템을 기존 `nextitslm` 프로젝트에 통합하는 방법을 설명합니다.

## 핵심 변경사항

### 1. 모델 서빙 방식 변경

**기존 (nextitslm)**
```python
from transformers import AutoModelForCausalLM, AutoTokenizer

# 모델을 직접 로드
model = AutoModelForCausalLM.from_pretrained("Qwen/Qwen3-4B-Instruct-2507")
tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen3-4B-Instruct-2507")
```

**신규 (md_summarizer)**
```bash
# SGLang 서버로 모델 서빙
bash scripts/start_sglang_dual.sh
```

### 2. AnswerGenerator 대체

**기존 코드**
```python
from search_test.crawler_summary_llm import AnswerGenerator

generator = AnswerGenerator()
summary = generator.generate_answer(content)
generator.cleanup_model()
```

**신규 코드 (드롭인 대체)**
```python
from md_summarizer.src import SGLangClient as AnswerGenerator

generator = AnswerGenerator(endpoints=["http://localhost:30000", "http://localhost:30001"])
summary = generator.generate_answer(content)
generator.cleanup_model()  # 호환성 유지 (실제로는 불필요)
```

## 통합 단계

### Step 1: SGLang 서버 시작

```bash
cd /home/jeonghs/workspace/md_summarizer
bash scripts/start_sglang_dual.sh
```

서버가 시작되면 다음 엔드포인트가 활성화됩니다:
- GPU 0: `http://localhost:30000`
- GPU 1: `http://localhost:30001`

### Step 2: nextitslm 코드 수정

#### 방법 A: 최소 변경 (드롭인 대체)

`/home/jeonghs/workspace/nextitslm/backend/api/routes.py` 수정:

```python
# 기존 import 주석 처리
# from search_test.crawler_summary_llm import AnswerGenerator

# 새로운 import 추가
import sys
sys.path.append('/home/jeonghs/workspace/md_summarizer')
from src.sglang_client import SGLangClient as AnswerGenerator

# 사용 방법은 동일
generator = AnswerGenerator(endpoints=["http://localhost:30000", "http://localhost:30001"])
summary = generator.generate_answer(content)
```

#### 방법 B: 요약 인덱스 시스템 활용 (권장)

더 나은 성능과 검색 기능을 원한다면:

```python
import sys
sys.path.append('/home/jeonghs/workspace/md_summarizer')
from src import MDSummaryIndex

# 초기화 (한 번만)
summarizer = MDSummaryIndex(
    sglang_endpoints=["http://localhost:30000", "http://localhost:30001"]
)

# 문서 추가 및 요약
summarizer.add_document("doc1.md", content=content)
summarizer.generate_summaries()

# 검색 기능 활용
results = summarizer.search("검색어", top_k=3)
```

### Step 3: 기존 API 엔드포인트 수정

`/api/v1/summarize` 엔드포인트를 다음과 같이 수정:

```python
@router.post("/api/v1/summarize", response_model=SummarizeResponse)
async def summarize_files(request_data: SummarizeRequest):
    file_names = request_data.filenames
    
    # SGLang 클라이언트 사용
    import sys
    sys.path.append('/home/jeonghs/workspace/md_summarizer')
    from src.sglang_client import SGLangClient
    
    client = SGLangClient(endpoints=["http://localhost:30000", "http://localhost:30001"])
    
    # 나머지 로직은 동일
    summaries = []
    for file_name in file_names:
        # 파일 읽기
        file_path = OCR_RESULTS_DIR / f"{Path(file_name).stem}.md"
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 요약 생성 (기존과 동일한 방식)
        summary = client.generate_answer(content)
        summaries.append(summary)
    
    # ... 나머지 코드 동일
```

## 성능 비교

### 기존 시스템 (Transformers 직접 로드)
- 모델 로딩 시간: ~30초
- 추론 속도: ~50 tokens/sec (단일 GPU)
- 메모리 사용: 모델당 ~8GB VRAM
- 동시 처리: 어려움 (모델 로드/언로드 필요)

### 신규 시스템 (SGLang 서버)
- 모델 로딩 시간: 0초 (서버가 이미 실행 중)
- 추론 속도: ~80-100 tokens/sec (RadixAttention 최적화)
- 메모리 사용: ~8GB VRAM (서버당)
- 동시 처리: 우수 (듀얼 GPU 라운드 로빈)

### H100 2장 환경 예상 성능
- 처리량: ~160-200 tokens/sec (듀얼 서버)
- 문서당 요약 시간: 2-5초 (문서 길이에 따라)
- 동시 요청 처리: 10+ requests/sec

## 주요 장점

### 1. 속도 향상
- **RadixAttention**: KV 캐시 재사용으로 반복 패턴 최적화
- **배치 처리**: 여러 요청을 효율적으로 처리
- **병렬 처리**: 듀얼 GPU로 처리량 2배

### 2. 메모리 효율성
- 모델을 한 번만 로드
- 요청마다 로드/언로드 불필요
- GPU 메모리 안정적 사용

### 3. 확장성
- 서버 추가로 쉽게 확장 가능
- 로드 밸런싱 자동 처리
- 무중단 배포 가능

### 4. 개발 편의성
- 기존 코드와 호환
- 드롭인 대체 가능
- API 인터페이스 동일

## 테스트 방법

### 1. SGLang 서버 테스트

```bash
# 서버 상태 확인
curl http://localhost:30000/health
curl http://localhost:30001/health

# 간단한 생성 테스트
curl -X POST http://localhost:30000/generate \
  -H "Content-Type: application/json" \
  -d '{"text": "안녕하세요", "sampling_params": {"max_new_tokens": 100}}'
```

### 2. Python 클라이언트 테스트

```python
from md_summarizer.src import SGLangClient

client = SGLangClient(endpoints=["http://localhost:30000"])
result = client.generate_answer("테스트 문서입니다.")
print(result)
```

### 3. 통합 테스트

```bash
# 기존 nextitslm API 테스트
curl -X POST http://localhost:5001/api/v1/summarize \
  -H "Content-Type: application/json" \
  -d '{"filenames": ["test.md"]}'
```

## 문제 해결

### SGLang 서버가 시작되지 않는 경우

```bash
# 로그 확인
tail -f /home/jeonghs/workspace/md_summarizer/logs/sglang_gpu0.log
tail -f /home/jeonghs/workspace/md_summarizer/logs/sglang_gpu1.log

# GPU 상태 확인
nvidia-smi

# 포트 사용 확인
netstat -tulpn | grep 30000
```

### 메모리 부족 오류

```yaml
# config/model_config.yaml 수정
sglang:
  mem_fraction_static: 0.75  # 0.85에서 낮춤
```

### 느린 응답 속도

```python
# 타임아웃 증가
client = SGLangClient(endpoints=["http://localhost:30000"])
client.timeout = 120.0  # 기본 60초에서 증가
```

## 롤백 방법

문제가 발생하면 기존 시스템으로 쉽게 롤백 가능:

```python
# 새로운 import 주석 처리
# from md_summarizer.src import SGLangClient as AnswerGenerator

# 기존 import 복원
from search_test.crawler_summary_llm import AnswerGenerator
```

## 추가 기능

### 요약 인덱스 검색

```python
# 문서 인덱싱
summarizer = MDSummaryIndex(sglang_endpoints=["http://localhost:30000"])
summarizer.add_documents_batch(file_paths)
summarizer.generate_summaries()

# 검색
results = summarizer.search("특정 주제", top_k=5)
```

### 인덱스 저장/로드

```python
# 저장
summarizer.save_index("index.json")

# 로드 (서버 재시작 후)
summarizer.load_index("index.json")
```

## 연락처

문제가 발생하거나 질문이 있으면:
- 로그 파일 확인: `/home/jeonghs/workspace/md_summarizer/logs/`
- 이슈 리포트: 프로젝트 저장소
