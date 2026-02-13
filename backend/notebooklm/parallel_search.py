import concurrent.futures
import logging
import threading
from typing import List, Dict, Any, Optional, Set

# 환경 문제로 인해 임포트 우회
try:
    from sentence_transformers import CrossEncoder
except ImportError:
    CrossEncoder = None

from config import RAGConfig
from query_rewriter import QueryRewriter

logger = logging.getLogger(__name__)

class ParallelSearcher:
    """
    쿼리 재작성, 병렬 검색, 결과 취합 및 재정렬을 포함하는 검색 흐름을 조정합니다.
    """
    def __init__(self, config: RAGConfig, searchers: Dict[str, Any], query_rewriter=None):
        self.config = config
        self.searchers = searchers
        # RAGConfig에 속성이 없을 경우를 대비해 안전하게 처리
        # 쿼리 리라이팅 기능 사용 여부 확인 - 대문자 속성명 사용
        self.use_query_rewrite = getattr(self.config, 'ENABLE_QUERY_REWRITE', True)
        self.query_rewriter = query_rewriter

    def search(
        self,
        query: str,
        selected_searchers: List[str],
        top_k: int = 3,
        cancellation_event: Optional[threading.Event] = None,
        allowed_document_uuids: Optional[Set[str]] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        쿼리 재작성부터 병렬 검색, 재정렬까지 전체 검색 파이프라인을 실행합니다.
        """
        # 메모리 정리
        import gc
        import torch
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        
        # 1. 쿼리 재작성 (이미지 검색에서는 비활성화)
        rewritten_queries = [query]  # 원본 쿼리 포함
        
        # 이미지 검색이 포함된 경우 쿼리 재작성 비활성화
        has_image_search = 'image' in selected_searchers
        
        if has_image_search:
            # 이미지 검색이 있으면 원본 쿼리만 사용
            rewritten_queries = [query]
        else:
            # 텍스트 검색만 있는 경우 쿼리 재작성 수행
            try:
                if self.use_query_rewrite and self.query_rewriter:
                    try:
                        # 쿼리 재작성 시도
                        rewritten_queries = self.query_rewriter.rewrite_query(query)
                        if not rewritten_queries or len(rewritten_queries) == 0:
                            # 재작성 실패 시 원본 쿼리만 사용
                            logger.warning("쿼리 재작성 결과가 비어있어 원본 쿼리만 사용합니다.")
                            rewritten_queries = [query]
                    except Exception as e:
                        logger.error(f"쿼리 재작성 중 오류 발생: {e}")
                        rewritten_queries = [query]  # 오류 발생 시 원본 쿼리만 사용
            except Exception as e:
                logger.error(f"쿼리 재작성 초기화 오류: {e}")
                rewritten_queries = [query]  # 오류 발생 시 원본 쿼리만 사용
                
            # 중복 제거 및 최대 쿼리 수 제한 (텍스트 검색만 있는 경우)
            rewritten_queries = list(set(rewritten_queries))  # 중복 제거
            
            # 원본 쿼리가 포함되어 있는지 확인
            if query not in rewritten_queries:
                rewritten_queries.insert(0, query)  # 원본 쿼리가 없으면 맨 앞에 추가
            else:
                # 원본 쿼리가 있으면 맨 앞으로 이동
                rewritten_queries.remove(query)
                rewritten_queries.insert(0, query)
            
            # 원본 쿼리 + 재작성된 쿼리 2개로 제한 (총 3개)
            if len(rewritten_queries) > 3:
                logger.debug(f"쿼리 개수 제한: {len(rewritten_queries)} -> 3")
                rewritten_queries = rewritten_queries[:3]  # 원본 포함 최대 3개로 제한
        

        # 2. 병렬 검색 실행 - 이미지와 텍스트 결과 분리
        text_results = []
        image_results = []
        max_workers = max(1, min(len(selected_searchers) * len(rewritten_queries), 5))  # 최대 쓰레드 수 제한 (최소 1)
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for searcher_name in selected_searchers:
                if searcher_name in self.searchers:
                    searcher = self.searchers[searcher_name]
                    for rewritten_query in rewritten_queries:
                        # 모든 검색에 리랭킹 적용
                        rerank_needed = True
                        # 작업을 제출하기 전에 취소 확인
                        if cancellation_event and cancellation_event.is_set():
                            continue

                        futures.append(
                                executor.submit(
                                    searcher.search,
                                    rewritten_query,
                                    top_k=top_k,
                                    rerank=rerank_needed,
                                    cancellation_event=cancellation_event,
                                    allowed_document_uuids=allowed_document_uuids,
                                    session_id=session_id,
                                )
                        )
            
            # 결과 취합 - 이미지와 텍스트 분리
            for i, future in enumerate(futures):
                try:
                    result = future.result()
                    if result:
                        searcher_name = selected_searchers[i // len(rewritten_queries)]
                        
                        # 이미지 검색기인 경우
                        if searcher_name == 'image':
                            # 이미지 검색 설정값 가져오기
                            config = RAGConfig()
                            image_top_k = getattr(config, 'IMAGE_TOP_K', 5)  # 1차 선별 개수
                            image_final_k = getattr(config, 'IMAGE_FINAL_K', 3)  # 최종 개수 
                            similarity_threshold = getattr(config, 'IMAGE_SIMILARITY_THRESHOLD', 0.5)  # 1차 유사도 임계값
                            rerank_threshold = getattr(config, 'IMAGE_RERANK_SCORE_THRESHOLD', 0.8)  # 2차 리랭킹 임계값
                            
                            # 1단계: 기본 유사도 임계값으로 필터링
                            first_filtered = [img for img in result if img.get('score', 0) >= similarity_threshold]
                            top_images = first_filtered[:image_top_k]
                            
                            # 2단계: 리랭킹 점수 필터링
                            final_images = []
                            for img in top_images:
                                reranked_score = img.get('score', 0)
                                is_reranked = img.get('reranked', False)
                                if is_reranked and reranked_score >= rerank_threshold:
                                    final_images.append(img)
                                elif not is_reranked:
                                    final_images.append(img)
                            
                            final_images = final_images[:image_final_k]
                            
                            image_results.extend(final_images)
                        
                        # 텍스트 검색기인 경우
                        elif searcher_name == 'text':
                            # 텍스트 결과는 모두 추가 (이미 리랭킹된 상태)
                            text_results.extend(result)
                        
                        else:
                            # 기타 검색기의 경우 텍스트로 처리
                            text_results.extend(result)
                except Exception as e:
                    searcher_name = selected_searchers[i // len(rewritten_queries)] if i // len(rewritten_queries) < len(selected_searchers) else "unknown"
                    logger.error(f"검색기 {searcher_name} 결과 처리 중 오류: {e}")

        # allowed_document_uuids 필터링 적용 (검색기에서 필터링되지 못한 항목 대비)
        if allowed_document_uuids:
            before_text = len(text_results)
            text_results = [r for r in text_results if r.get("document_uuid") in allowed_document_uuids]
            if before_text != len(text_results):
                logger.info(
                    "텍스트 결과 UUID 필터링 적용: %d -> %d",
                    before_text,
                    len(text_results),
                )

            before_image = len(image_results)
            image_results = [r for r in image_results if r.get("document_uuid") in allowed_document_uuids]
            if before_image != len(image_results):
                logger.info(
                    "이미지 결과 UUID 필터링 적용: %d -> %d",
                    before_image,
                    len(image_results),
                )

        # 결과가 없는 경우 처리
        if not text_results and not image_results:
            logger.warning("검색 결과가 없습니다.")
            return {
                "text_documents": [],
                "image_documents": [],
                "metadata": {
                    "rewritten_queries": rewritten_queries,
                    "selected_searchers": selected_searchers,
                    "text_result_count": 0,
                    "image_result_count": 0,
                    "error": "검색 결과가 없습니다."
                }
            }

        # 3. 각각의 결과에 대해 중복 제거 및 정렬
        try:
            if text_results:
                text_results = self._deduplicate_and_sort(text_results)
            if image_results:
                image_results = self._deduplicate_and_sort(image_results)
        
        except Exception as e:
            logger.error(f"결과 중복 제거 중 오류: {e}")
            # 오류 발생 시 원본 결과 사용

        logger.info(f"검색 완료: 텍스트 {len(text_results)}개, 이미지 {len(image_results)}개")
        
        return {
            "text_documents": text_results,
            "image_documents": image_results,
            "metadata": {
                "rewritten_queries": rewritten_queries,
                "selected_searchers": selected_searchers,
                "text_result_count": len(text_results),
                "image_result_count": len(image_results),
                "total_result_count": len(text_results) + len(image_results)
            }
        }

    def _deduplicate_and_sort(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """ID를 기준으로 결과를 중복 제거하고 초기 점수로 정렬합니다."""
        unique_results = {}
        for result in results:
            doc_id = result.get('id')
            if doc_id:
                # 기존 결과보다 높은 점수인 경우에만 업데이트
                if doc_id not in unique_results or result.get('score', 0) > unique_results[doc_id].get('score', 0):
                    unique_results[doc_id] = result
        
        sorted_results = sorted(unique_results.values(), key=lambda x: x.get('score', 0), reverse=True)
        return sorted_results
