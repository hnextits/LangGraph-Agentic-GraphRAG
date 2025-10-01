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
from typing import List, Dict, Any, Optional
import weaviate
import torch

# config.py 파일이 있는 디렉토리를 sys.path에 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import RAGConfig
from weaviate_utils import create_schema

# 로깅 설정
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # 로그 레벨을 DEBUG로 변경

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
        
        # 공유 임베딩 모델 초기화
        from shared_embedding import SharedEmbeddingModel
        self.shared_embedding = SharedEmbeddingModel()
        
        # 개선된 텍스트 리랭커 초기화 (클래스 레벨에서 관리)
        self.reranker = None
        self._initialize_reranker()
        
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
    
    def _initialize_reranker(self):
        """개선된 텍스트 리랭커를 초기화합니다."""
        try:
            from rag_text.text_reranker_improved_2 import ImprovedTextReranker
            
            # config에서 설정값 가져오기
            config = RAGConfig()
            
            # 성능 최적화된 설정으로 리랭커 초기화
            self.reranker = ImprovedTextReranker(
                model_name=config.RERANKER_MODEL_NAME,  # config에서 모델 이름 가져오기
                max_length=8192,  # 적절한 길이 제한
                batch_size=config.RERANKER_BATCH_SIZE  # config에서 배치 크기 가져오기
            )
            logger.info(f"개선된 텍스트 리랭커 초기화 완료 - 모델: {config.RERANKER_MODEL_NAME}")
        except Exception as e:
            logger.error(f"개선된 텍스트 리랭커 초기화 실패: {e}")
            logger.warning("기존 TextReranker로 폴백합니다.")
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
            if not self.shared_embedding.is_loaded():
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

    def search(self, query: str, top_k: int = None, rerank: bool = True, rerank_top_k: int = None, cancellation_event: Optional[threading.Event] = None) -> List[Dict[str, Any]]:
        """텍스트 쿼리로 검색을 수행합니다."""
        # config에서 기본값 가져오기
        config = RAGConfig()
        top_k = top_k if top_k is not None else config.TEXT_TOP_K
        
        if not self.client:
            logger.error("Weaviate 클라이언트가 초기화되지 않았습니다.")
            return []
        
        search_top_k = top_k * 3 if rerank else top_k
        
        # 취소 확인
        if cancellation_event and cancellation_event.is_set():
            raise InterruptedError("Operation cancelled before text embedding generation")
        
        try:
            # 공유 임베딩 모델 사용 (메모리 절약)
            query_embedding = self.shared_embedding.generate_embedding(query)
            
            # 취소 확인
            if cancellation_event and cancellation_event.is_set():
                raise InterruptedError("Operation cancelled before Weaviate search")
            
            # Weaviate 벡터 검색 수행
            logger.debug(f"Weaviate 검색 시작: 클래스={self.class_name}, top_k={search_top_k}")
            
            try:
                # metadata 필드에 대한 서브 셀렉션 문제 해결
                vector_search_results = (
                    self.client.query
                    .get(self.class_name, ["text", "title", "source", "page_num"])
                    .with_near_vector({
                        "vector": query_embedding.tolist()
                    })
                    .with_limit(search_top_k)
                    .do()
                )
                
                # 검색 결과 로깅
                logger.debug(f"Weaviate 검색 결과: {vector_search_results}")
            except Exception as e:
                logger.error(f"Weaviate 검색 오류: {str(e)}")
                vector_search_results = {"data": {"Get": {}}}
                raise
            
            # 결과 파싱
            results = []
            if "data" in vector_search_results and "Get" in vector_search_results["data"]:
                items = vector_search_results["data"]["Get"].get(self.class_name, [])
                
                for i, item in enumerate(items):
                    # Weaviate의 _additional 필드에서 거리 점수 가져오기
                    score = item.get("_additional", {}).get("distance", 0)
                    # 거리를 유사도 점수로 변환 (1 - 거리)
                    similarity_score = 1 - score if score <= 1 else 0
                    
                    result = {
                        'score': similarity_score,
                        'index': i,
                        'id': item.get("id", f"doc_{i}"),
                        'title': item.get("title", f"문서 {i}"),
                        'text': item.get("text", f"인덱스 {i}에 해당하는 문서"),
                        'source': item.get("source", ""),
                        'page_num': item.get("page_num", 0),
                        'metadata': {}  # 빈 디터리로 대체
                    }
                    results.append(result)
            
            logger.info(f"쿼리 '{query}'에 대한 검색 완료, 결과 수: {len(results)}")
            
            # 리랭킹 적용
            if rerank and results and self.reranker:
                try:
                    if rerank_top_k is None:
                        rerank_top_k = top_k
                    
                    # 개선된 리랭커 사용
                    logger.info(f"개선된 리랭커로 재정렬 시작 (top_k={rerank_top_k})")
                    
                    # config에서 설정값 가져오기
                    config = RAGConfig()
                    
                    # 취소 확인
                    if cancellation_event and cancellation_event.is_set():
                        raise InterruptedError("Operation cancelled before reranking")
                    
                    # ImprovedTextReranker의 rerank 메서드 호출
                    reranked_results = self.reranker.rerank(
                        query, 
                        results, 
                        top_k=rerank_top_k, 
                        min_score=config.RELEVANCE_THRESHOLD, 
                        cancellation_event=cancellation_event
                    )
                    
                    # 리랭킹 통계 로깅
                    if hasattr(self.reranker, 'get_statistics'):
                        stats = self.reranker.get_statistics()
                        cache_hit_rate = stats.get('cache_hit_rate', 0)
                        logger.info(f"리랭킹 완료 - 캐시 적중률: {cache_hit_rate:.1f}%")
                    
                    results = reranked_results
                    logger.info(f"쿼리 '{query}'에 대한 개선된 리랭킹 완료, 결과 수: {len(results)}")
                    
                    # 리랭킹 결과 상세 로그 출력
                    logger.info(f"리랭킹 적용된 검색 결과 (최대 5개):")
                    for i, result in enumerate(results[:5]):
                        title = result.get('title', '제목 없음')
                        page_num_str = f"(페이지 {result.get('page_num', 'N/A')})" if 'page_num' in result else ''
                        logger.info(f"{i+1}. {title} {page_num_str} - 리랭크 점수: {result.get('score', 0):.4f}")
                        logger.info(f"   ID: {result.get('id', 'N/A')}, 인덱스: {result.get('index', 'N/A')}")
                        text_preview = result.get('text', '')[:100] + '...' if len(result.get('text', '')) > 100 else result.get('text', '')
                        logger.info(f"   텍스트: {text_preview}")
                
                except Exception as e:
                    logger.error(f"개선된 리랭킹 중 오류 발생: {e}")
                    logger.warning("리랭킹 없이 원본 결과를 반환합니다.")
            
            elif rerank and results and not self.reranker:
                logger.warning("리랭커가 초기화되지 않아 리랭킹을 건너뜁니다.")
            
            return results[:top_k]
            
        except Exception as e:
            logger.error(f"Weaviate 검색 중 오류 발생: {e}")
            return []

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
