# Search Skill Module

크롤링, 검색, 요약 기능을 통합한 모듈입니다.

## 구조

```
search/
├── __init__.py           # 모듈 초기화
├── google_search.py      # Google 검색 API 클라이언트
├── summarizer.py         # 요약 기능 (md_summarizer 활용)
├── pipeline.py           # 통합 파이프라인
├── util.py               # 유틸리티 함수
├── crawler/              # 크롤러 모듈
│   ├── __init__.py
│   ├── namuwiki.py       # 나무위키 크롤러
│   └── wikipedia.py      # 위키피디아 크롤러
└── README.md             # 이 파일
```

## 설정

설정은 `notebooklm/config.py`의 `RAGConfig` 클래스에서 관리됩니다.
- Google Search API 키 및 CX ID
- 요약 모델 설정
- 크롤링 설정
- 데이터 저장 경로

## 기능

### 1. Google 검색
```python
from skill.search import search_google

results = search_google("검색 쿼리", num=10)
```

### 2. 요약
```python
from skill.search import Summarizer

summarizer = Summarizer()
summarizer.load()
summary = summarizer.summarize("요약할 텍스트")
summarizer.cleanup()
```

### 3. 검색 + 요약 통합
```python
from skill.search import search_and_summarize

result = search_and_summarize("검색 쿼리", num_results=10, use_llm=True)
print(result['summary'])
```


## 의존성

- md_summarizer: 요약 기능 제공
- requests: HTTP 요청
- torch: GPU 지원

## 사용 예시

```python
# 간단한 검색
from skill.search import search_google

results = search_google("한화 이글스", num=5)
for result in results:
    print(f"{result['title']}: {result['link']}")

# 검색 및 요약
from skill.search import search_and_summarize

result = search_and_summarize("한화 이글스", num_results=10, use_llm=True)
print(f"검색 결과: {result['count']}개")
print(f"요약:\n{result['summary']}")
```

## 주의사항

- Google Search API 키가 필요합니다
- 요약 기능은 md_summarizer의 Qwen3-4B-Instruct-2507 모델을 사용합니다
- LLM 요약 사용 시 GPU 메모리가 필요합니다 (약 16GB)
