#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
텍스트 검색기 - Weaviate를 사용한 버전
"""

import os
import sys
import json
import logging
import numpy as np
import threading
from typing import List, Dict, Any, Optional, Set
import weaviate
import torch

from notebooklm.config import RAGConfig
from notebooklm.weaviate_utils import create_schema

# 로깅 설정 - main.py에서 configure_logging()이 이미 호출됨
logger = logging.getLogger(__name__)

class TextSearcher:
    def __init__(self, model_name: str = None, device: str = None):
        """텍스트 검색기를 초기화합니다."""
        config = RAGConfig()
        self.dimension = config.VECTOR_DIMENSION
        self.max_length = config.MAX_LENGTH
        self.model_name = model_name if model_name else config.EMBEDDING_MODEL
        
        # GPU 분산 배치 설정 사용
        if device:
            self.device = device
        else:
            # config에서 텍스트 임베딩 전용 GPU 사용
            self.device = config.TEXT_EMBEDDING_DEVICE if torch.cuda.is_available() else "cpu"
            
        logger.info(f"텍스트 임베딩 모델이 {self.device}에 로드됩니다.")
        
        # 공유 임베딩 모델은 Lazy 로딩
        from shared_embedding import SharedEmbeddingModel
        from query_rewriter import QueryRewriter
        from parallel_search import ParallelSearcher
        self.shared_embedding = SharedEmbeddingModel()
        
        # 개선된 텍스트 리랭커는 Lazy 로딩
        self.reranker = None
        self._reranker_lock = threading.Lock()
        
        # 메모리 정리
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        
        # Weaviate 클라이언트 초기화
        self.client = config.get_weaviate_client()
        if self.client:
            # 스키마 생성 확인
            create_schema(self.client)
        else:
            logger.error("Weaviate 클라이언트 초기화 실패")
        
        self.class_name = config.WEAVIATE_TEXT_CLASS
        logger.info(f"Weaviate 텍스트 검색기 초기화 완료 (클래스: {self.class_name})")
    
    def _ensure_reranker(self):
        """필요 시 리랭커를 Lazy 로드합니다."""
        if self.reranker is not None:
            return
        with self._reranker_lock:
            if self.reranker is not None:
                return
            try:
                from rag_text.text_reranker_improved_2 import ImprovedTextReranker
                config = RAGConfig()
                self.reranker = ImprovedTextReranker(
                    model_name=config.RERANKER_MODEL_NAME,
                    max_length=8192,
                    batch_size=config.RERANKER_BATCH_SIZE,
                )
                logger.info("개선된 텍스트 리랭커 Lazy 로딩 완료")
            except Exception as e:
                logger.error(f"개선된 텍스트 리랭커 로드 실패: {e}")
                try:
                    from rag_text.text_reranker import TextReranker
                    self.reranker = TextReranker()
                    logger.info("기존 TextReranker로 폴백 완료")
                except Exception as fallback_error:
                    logger.error(f"기존 TextReranker 폴백도 실패: {fallback_error}")
                    self.reranker = None

    def generate_embedding(self, text: str) -> np.ndarray:
        """
        쿼리 텍스트에 대한 임베딩을 생성합니다.
        공유 임베딩 모델을 사용하여 메모리 효율성을 높입니다.
        """
        try:
            # 공유 임베딩 모델 사용 확인
            if not self.shared_embedding.is_loaded:
                logger.error("공유 임베딩 모델이 로드되지 않았습니다.")
                raise RuntimeError("공유 임베딩 모델이 로드되지 않았습니다.")
            
            # 공유 임베딩 모델을 통한 임베딩 생성
            embedding = self.shared_embedding.generate_embedding(text)
            
            if len(embedding) != self.dimension:
                logger.warning(f"임베딩 차원이 예상과 다릅니다: {len(embedding)} vs {self.dimension}")
            
            return embedding.astype('float32')
            
        except Exception as e:
            logger.error(f"임베딩 생성 중 오류 발생: {e}")
            raise RuntimeError(f"임베딩 생성 실패: {e}") from e

    def _build_uuid_where_filter(self, allowed_document_uuids: Set[str]) -> Optional[Dict[str, Any]]:
        """Weaviate where 필터를 구성하여 document_uuid를 제한합니다."""
        if not allowed_document_uuids:
            return None

        uuids = [uuid for uuid in allowed_document_uuids if uuid]
        if not uuids:
            return None

        if len(uuids) == 1:
            return {
                "path": ["document_uuid"],
                "operator": "Equal",
                "valueString": uuids[0],
            }

        return {
            "operator": "Or",
            "operands": [
                {
                    "path": ["document_uuid"],
                    "operator": "Equal",
                    "valueString": uuid,
                }
                for uuid in uuids
            ],
        }

    def search(
        self,
        query: str,
        top_k: int = None,
        rerank: bool = True,
        rerank_top_k: int = None,
        cancellation_event: Optional[threading.Event] = None,
        allowed_document_uuids: Optional[Set[str]] = None,
        session_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """텍스트 쿼리로 검색을 수행합니다."""
        # config에서 기본값 가져오기
        config = RAGConfig()
        top_k = top_k if top_k is not None else config.TEXT_TOP_K
        
        if not self.client:
            logger.error("Weaviate 클라이언트가 초기화되지 않았습니다.")
            return []
        
        search_top_k = top_k  # 리랭킹 사용 시에도 필요한 개수만 검색 (속도 향상)
        
        # 취소 확인
        if cancellation_event and cancellation_event.is_set():
            raise InterruptedError("Operation cancelled before text embedding generation")
        
        try:
            # 공유 임베딩 모델 사용 (메모리 절약)
            query_embedding = self.shared_embedding.generate_embedding(query)
            
            # 취소 확인
            if cancellation_event and cancellation_event.is_set():
                raise InterruptedError("Operation cancelled before Weaviate search")
            
            # Weaviate 벡터 검색 수행 (v4 API)
            logger.debug(f"Weaviate 검색 시작 (session: {session_id}): 클래스={self.class_name}, top_k={search_top_k}")
            
            try:
                from weaviate.classes.query import Filter
                
                collection = self.client.collections.get(self.class_name)
                
                # 필터 구성 (session_id + allowed_document_uuids)
                filters = None
                
                # 1. 세션 필터 (session_id가 제공된 경우) - 기본 파일들도 포함
                if session_id:
                    filters = None
                else:
                    pass
                
                # 2. UUID 필터 (allowed_document_uuids가 제공된 경우)
                if allowed_document_uuids:
                    uuids = [uuid for uuid in allowed_document_uuids if uuid]
                    uuid_filter = None
                    if len(uuids) == 1:
                        uuid_filter = Filter.by_property("document_uuid").equal(uuids[0])
                    elif len(uuids) > 1:
                        uuid_filter = Filter.by_property("document_uuid").contains_any(uuids)
                    
                    if uuid_filter:
                        filters = filters & uuid_filter if filters else uuid_filter
                        logger.debug(f"UUID 필터 적용: {len(uuids)}개")
                else:
                    pass
                
                # 벡터 검색 실행
                response = collection.query.near_vector(
                    near_vector=query_embedding.tolist(),
                    limit=search_top_k,
                    filters=filters,
                    return_metadata=['distance'],
                    return_properties=["text", "title", "source", "page_num", "document_uuid"]
                )
                
                # 검색 결과 로깅
                logger.debug(f"Weaviate 검색 결과: {len(response.objects)}개")
            except Exception as e:
                logger.error(f"Weaviate 검색 오류: {str(e)}")
                raise
            
            # 결과 파싱
            results = []
            for i, obj in enumerate(response.objects):
                # Weaviate의 distance 가져오기
                score = obj.metadata.distance if obj.metadata.distance is not None else 0
                # 거리를 유사도 점수로 변환 (1 - 거리)
                similarity_score = 1 - score if score <= 1 else 0
                
                result = {
                    'score': similarity_score,
                    'index': i,
                    'id': str(obj.uuid),
                    'title': obj.properties.get("title", f"문서 {i}"),
                    'text': obj.properties.get("text", f"인덱스 {i}에 해당하는 문서"),
                    'source': obj.properties.get("source", ""),
                    'page_num': obj.properties.get("page_num", 0),
                    'metadata': {},
                    'document_uuid': obj.properties.get("document_uuid"),
                }
                results.append(result)
            
            logger.info(f"쿼리 '{query}'에 대한 검색 완료, 결과 수: {len(results)}")
            
            # 리랭킹 적용
            if rerank and results:
                self._ensure_reranker()
                if self.reranker:
                    try:
                        if rerank_top_k is None:
                            rerank_top_k = top_k
                        
                        logger.info(f"개선된 리랭커로 재정렬 시작 (top_k={rerank_top_k})")
                        
                        config = RAGConfig()
                        
                        if cancellation_event and cancellation_event.is_set():
                            raise InterruptedError("Operation cancelled before reranking")
                        
                        reranked_results = self.reranker.rerank(
                            query, 
                            results, 
                            top_k=rerank_top_k, 
                            min_score=config.RELEVANCE_THRESHOLD, 
                            cancellation_event=cancellation_event
                        )
                        
                        if hasattr(self.reranker, 'get_statistics'):
                            stats = self.reranker.get_statistics()
                            cache_hit_rate = stats.get('cache_hit_rate', 0)
                            logger.info(f"리랭킹 완료 - 캐시 적중률: {cache_hit_rate:.1f}%")
                        
                        results = reranked_results
                        logger.info(f"쿼리 '{query}'에 대한 개선된 리랭킹 완료, 결과 수: {len(results)}")
                        
                    
                    except Exception as e:
                        logger.error(f"개선된 리랭킹 중 오류 발생: {e}")
                        logger.warning("리랭킹 없이 원본 결과를 반환합니다.")
                else:
                    logger.warning("리랭커가 초기화되지 않아 리랭킹을 건너뜁니다.")
            
            if allowed_document_uuids:
                before_filter_count = len(results)
                results = [res for res in results if res.get('document_uuid') in allowed_document_uuids]
                if before_filter_count != len(results):
                    logger.info(
                        "텍스트 검색 결과 UUID 필터링 적용: %d -> %d",
                        before_filter_count,
                        len(results),
                    )

            return results[:top_k]
        except Exception:
            logger.exception("텍스트 검색 중 예기치 않은 오류가 발생했습니다.")
            raise

    def cleanup(self):
        """GPU 리소스를 정리합니다."""
        try:
            if self.reranker and hasattr(self.reranker, "cleanup"):
                self.reranker.cleanup()
            self.reranker = None
        except Exception as exc:
            logger.error(f"텍스트 리랭커 정리 중 오류: {exc}")
        if hasattr(self.shared_embedding, "cleanup"):
            try:
                self.shared_embedding.cleanup()
            except Exception as exc:
                logger.error(f"공유 임베딩 정리 중 오류: {exc}")

        if getattr(self, "client", None) is not None:
            try:
                self.client.close()
            except Exception as exc:
                logger.error(f"Weaviate 클라이언트 정리 중 오류: {exc}")
            finally:
                self.client = None

if __name__ == "__main__":
    # 검색 테스트
    searcher = TextSearcher()
    while True:
        query = input("검색 쿼리를 입력하세요 (종료하려면 'exit' 입력): ")
        if query.lower() == 'exit':
            break
            
        print(f"\n검색 결과 (리랭킹 미적용, 최대 5개):")
        initial_results = searcher.search(query, top_k=5, rerank=False)
        for i, result in enumerate(initial_results):
            title = result.get('title', '제목 없음')
            page_num_str = f"(페이지 {result.get('page_num', 'N/A')})" if 'page_num' in result else ''
            print(f"{i+1}. {title} {page_num_str}- 유사도: {result.get('score', 0):.4f}")
            print(f"   ID: {result.get('id', 'N/A')}")
            print(f"   텍스트: {result.get('text', '')[:200]}...")
            print()
        
        print("\n리랭킹 수행 중...")
        try:
            reranked_results = searcher.search(query, top_k=5, rerank=True)
            print(f"\n리랭킹 적용된 검색 결과 (최대 5개):")
            for i, result in enumerate(reranked_results):
                title = result.get('title', '제목 없음')
                page_num_str = f"(페이지 {result.get('page_num', 'N/A')})" if 'page_num' in result else ''
                print(f"{i+1}. {title} {page_num_str} - 리랭크 점수: {result.get('score', 0):.4f}")
                print(f"   ID: {result.get('id', 'N/A')}")
                print(f"   텍스트: {result.get('text', '')[:200]}...")
                print()
        except Exception as e:
            print(f"\n리랭킹 중 오류 발생: {e}")
