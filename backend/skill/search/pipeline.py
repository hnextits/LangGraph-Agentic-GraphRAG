"""
Search Pipeline
크롤링, 검색, 요약 기능 통합 파이프라인
"""
import sys
from pathlib import Path

# 현재 디렉토리를 path에 추가
current_dir = Path(__file__).parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

# notebooklm config 경로 추가
backend_dir = current_dir.parent.parent
notebooklm_dir = backend_dir / "notebooklm"
if str(notebooklm_dir) not in sys.path:
    sys.path.insert(0, str(notebooklm_dir))

from google_search import GoogleSearchClient
from util import filter_search_results
from summarizer import Summarizer
from config import RAGConfig

# 설정 로드
config = RAGConfig()

def search_google(query: str, num: int = 10, total_result_link: list = None) -> list:
    """
    구글 검색 엔진을 불러와 구글에서 검색하는 역할을 하는 함수

    Args:
        query: 사용자가 검색한 내용
        num: 검색 결과 보여줄 개수
        total_result_link: 이미 가져온 링크들 (중복 제외용)
        
    Returns:
        list: 검색 결과 리스트
    """
    try:
        # 1. 구글 엔진 가져오기
        search_engine = GoogleSearchClient(
            api_key=config.GOOGLE_API_KEY,
            cx_id=config.GOOGLE_CX_ID
        )
        print(f"[INFO] 구글 검색 진행중... 쿼리: {query}")
        print(f"[INFO] 제외할 링크 수: {len(total_result_link) if total_result_link else 0}개")
        
        # 2. 검색하기 (타임아웃 설정 포함)
        timeout_config = {
            'connection_timeout': config.SEARCH_CONNECTION_TIMEOUT,
            'read_timeout': config.SEARCH_READ_TIMEOUT
        }
        
        def search_google_batch(query, search_num, start_index=0):
            """검색 함수 내부 함수"""
            search_params = {
                'num': min(search_num, 10),  # 한 번에 최대 10개
                'start': start_index  # 검색 시작 인덱스
            }
            
            results = search_engine.search(query, extra_params=search_params, timeout_config=timeout_config)
        
            print(f"[DEBUG] API 응답 상태: {type(results)} (start: {start_index}, num: {search_params['num']})")
            
            if results is None:
                print("[WARNING] 검색 결과가 None입니다.")
                return []
                
            if not isinstance(results, dict) or 'items' not in results:
                print(f"[WARNING] 예상과 다른 API 응답 형식: {results}")
                return []
                
            print(f"[INFO] 검색 완료 - {len(results.get('items', []))}개 원본 결과 수신")
            
            # 검색 결과 필터링 (특정 사이트 제외)
            filtered_results = filter_search_results(results, max_results=search_params['num']) 
            print(f"[INFO] 1차 필터링 완료 - {len(filtered_results) if filtered_results else 0}개 결과")
            
            return filtered_results if filtered_results else []

        # 초기 검색 수행
        all_results = []
        start_index = 0
        batch_size = 10
        max_attempts = 5  # 최대 5번 시도 (최대 50개 검색)
        
        for attempt in range(max_attempts):
            print(f"[INFO] 검색 시도 {attempt + 1}/{max_attempts} (start: {start_index})")
            
            batch_results = search_google_batch(query, batch_size, start_index)
            
            if not batch_results:
                print("[INFO] 더 이상 검색 결과가 없습니다.")
                break
                
            # 이미 가져온 링크들 제외하면서 결과 추가
            unique_results = []
            for result in batch_results:
                link = result.get('link')
                # total_result_link와 이미 추가된 결과에서 중복 체크
                existing_links = (total_result_link or []) + [r.get('link') for r in all_results]
                if link not in existing_links:
                    unique_results.append(result)
                    
            all_results.extend(unique_results)
            print(f"[INFO] 이번 배치에서 {len(unique_results)}개 새 결과 추가, 총 {len(all_results)}개")
            
            # 원하는 개수에 도달하면 중단
            if len(all_results) >= num:
                all_results = all_results[:num]  # 정확히 num개만 자르기
                break
                
            # 다음 배치를 위해 시작 인덱스 업데이트
            start_index += batch_size
        
        final_results = all_results
        
        print(f"[INFO] 중복 제거 완료 - {len(final_results)}개 최종 결과 반환")
        return final_results
        
    except Exception as e:
        print(f"[ERROR] 검색 중 오류 발생: {str(e)}")
        import traceback
        print(f"[ERROR] 상세 오류: {traceback.format_exc()}")
        return []


def summarize_search_results(results: list, use_llm: bool = True) -> str:
    """
    검색 결과 요약
    
    Args:
        results: 검색 결과 리스트
        use_llm: LLM 사용 여부
        
    Returns:
        str: 요약된 텍스트
    """
    if not results:
        return "검색 결과가 없습니다."
    
    # 검색 결과를 텍스트로 변환
    content_parts = []
    for i, result in enumerate(results, 1):
        title = result.get('title', '제목 없음')
        snippet = result.get('snippet', '')
        link = result.get('link', '')
        
        content_parts.append(f"{i}. {title}\n{snippet}\n출처: {link}\n")
    
    full_content = "\n".join(content_parts)
    
    if use_llm:
        # LLM 사용 요약
        summarizer = Summarizer(model_name=config.SUMMARIZER_MODEL)
        try:
            summary = summarizer.summarize(full_content)
            summarizer.cleanup()
            return summary
        except Exception as e:
            print(f"[ERROR] LLM 요약 실패: {e}")
            # 실패 시 간단한 요약으로 폴백
            from summarizer import simple_summarize
            return simple_summarize(full_content, ratio=0.3)
    else:
        # 간단한 요약
        from summarizer import simple_summarize
        return simple_summarize(full_content, ratio=0.3)


def search_and_summarize(query: str, num_results: int = 10, use_llm: bool = True) -> dict:
    """
    검색 및 요약 통합 함수
    
    Args:
        query: 검색 쿼리
        num_results: 검색 결과 개수
        use_llm: LLM 사용 여부
        
    Returns:
        dict: 검색 결과 및 요약
    """
    print(f"[INFO] 검색 및 요약 시작: {query}")
    
    # 1. 구글 검색
    results = search_google(query, num=num_results)
    
    if not results:
        return {
            "query": query,
            "results": [],
            "summary": "검색 결과가 없습니다."
        }
    
    # 2. 요약 생성
    summary = summarize_search_results(results, use_llm=use_llm)
    
    return {
        "query": query,
        "results": results,
        "summary": summary,
        "count": len(results)
    }


# 하위 호환성을 위한 별칭
search = search_google


if __name__ == "__main__":
    # 테스트
    result = search_and_summarize("한화 이글스", num_results=5, use_llm=False)
    print("\n=== 검색 결과 ===")
    print(f"쿼리: {result['query']}")
    print(f"결과 개수: {result['count']}")
    print(f"\n요약:\n{result['summary']}")
