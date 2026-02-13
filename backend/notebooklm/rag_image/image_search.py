#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
이미지 검색기 - Weaviate를 사용한 버전
"""

import os
import sys
import json
import torch
import torch.nn.functional as F
import numpy as np
import threading
import logging
import time
import base64
from typing import List, Dict, Any, Optional, Tuple, Set
from PIL import Image
import weaviate

from config import RAGConfig
from shared_embedding import SharedEmbeddingModel
from rag_image.image_reranker import RAGReranker
from weaviate_utils import create_schema

# 로깅 설정
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class ImageSearcher:
    """이미지 검색을 위한 클래스입니다. 이미지와 차트 모두 검색 가능합니다."""
    
    def __init__(self, model_name: str = None, ollama_host: str = None, use_reranker: bool = True, supported_types: List[str] = ['image', 'chart']):
        """이미지 검색기를 초기화합니다."""
        config = RAGConfig()
        self.dimension = config.VECTOR_DIMENSION  # 임베딩 차원
        self.model_name = model_name if model_name else config.EMBEDDING_MODEL
        self.ollama_host = ollama_host if ollama_host else config.OLLAMA_API_URL
        self.use_reranker = use_reranker
        self.supported_types = supported_types  # 지원하는 콘텐츠 타입 (기본값: image, chart)
        
        # GPU 분산 배치 설정 사용 - 이미지 임베딩 전용 GPU
        if torch.cuda.is_available():
            self.device = torch.device(config.IMAGE_EMBEDDING_DEVICE)
        else:
            self.device = torch.device('cpu')
        
        logger.info(f"디바이스 설정: {self.device}")
        
        # 공유 임베딩 모델은 Lazy 로딩
        self.shared_embedding = SharedEmbeddingModel()
        
        # 리랭커 Lazy 로딩
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
        
        self.class_name = config.WEAVIATE_IMAGE_CLASS
        logger.info(f"Weaviate 이미지 검색기 초기화 완료 (클래스: {self.class_name})")

    def generate_embedding(self, text: str) -> np.ndarray:
        """이미지에 대한 임베딩을 생성합니다. 공유 임베딩 모델을 사용합니다."""
        try:
            if not self.shared_embedding.is_loaded:
                logger.info("공유 임베딩 모델이 아직 로드되지 않아 지금 로드합니다.")
            embedding = self.shared_embedding.generate_embedding(text)
            if embedding is None:
                raise RuntimeError("임베딩 생성 실패")
            if len(embedding) != self.dimension:
                logger.warning(f"임베딩 차원이 예상과 다릅니다: {len(embedding)} vs {self.dimension}")
            return embedding.astype('float32')
        except Exception as e:
            logger.error(f"공유 임베딩 모델 임베딩 생성 중 오류 발생: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return np.random.rand(self.dimension).astype('float32')  # 오류 발생 시 랜덤 벡터로 대체

    def _ensure_reranker(self):
        if not self.use_reranker:
            return
        if self.reranker is not None:
            return
        with self._reranker_lock:
            if self.reranker is not None:
                return
            try:
                self.reranker = RAGReranker()
                logger.info("이미지 리랭커 Lazy 로딩 완료")
            except Exception as e:
                logger.error(f"리랭커 초기화 중 오류 발생: {str(e)}")
                import traceback
                logger.error(traceback.format_exc())
                self.reranker = None

    def _build_uuid_where_filter(self, allowed_document_uuids: Set[str]) -> Optional[Dict[str, Any]]:
        """Weaviate where 필터를 구성하여 document_uuid로 제한합니다."""
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
        top_k: int = 10,
        rerank: bool = True,
        cancellation_event: Optional[threading.Event] = None,
        allowed_document_uuids: Optional[Set[str]] = None,
        use_uuid_filter: bool = False,
        session_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """이미지 쿼리로 검색을 수행합니다.
        
        Args:
            query: 검색 쿼리
            top_k: 반환할 결과 수
            rerank: 리랭킹 사용 여부
            cancellation_event: 취소 이벤트
            allowed_document_uuids: 허용된 문서 UUID 집합
            use_uuid_filter: UUID 필터 사용 여부 (기본값: False, 전체 이미지 검색)
            session_id: 세션 ID (필터링용)
        """
        # 설정에서 기본값 가져오기
        config = RAGConfig()
        if top_k is None:
            top_k = config.IMAGE_TOP_K
        
        if not self.client:
            logger.error("Weaviate 클라이언트가 초기화되지 않았습니다.")
            return []
        
        # 쿼리 임베딩 생성 - 공유 임베딩 모델 사용 (메모리 절약)
        try:
            # 쿼리 전처리 - 공백 제거 및 정규화
            normalized_query = query.strip()
            
            # 취소 확인
            if cancellation_event and cancellation_event.is_set():
                raise InterruptedError("Operation cancelled before image query embedding generation")
            
            # 쿼리 임베딩 생성
            query_embedding = self.shared_embedding.generate_embedding(normalized_query)
            
        except Exception as e:
            logger.error(f"이미지 검색 쿼리 임베딩 생성 실패: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            # 임베딩 생성 실패 시 빈 결과 반환
            return []
        
        # 취소 확인
        if cancellation_event and cancellation_event.is_set():
            raise InterruptedError("Operation cancelled before Weaviate search")
        
        try:
            # Weaviate 벡터 검색 수행
            # 필요한 개수만 검색 (리랭킹은 검색된 결과에 대해서만 수행)
            search_top_k = top_k
            
            logger.debug(f"Weaviate 이미지 검색 시작 (session: {session_id}): 클래스={self.class_name}, top_k={search_top_k}")
            
            try:
                from weaviate.classes.query import Filter
                
                collection = self.client.collections.get(self.class_name)
                
                # 필터 구성
                filters = None
                
                # 1. 세션 필터 (session_id가 제공된 경우) - 기본 파일들도 포함
                if session_id:
                    filters = None
                else:
                    pass
                
                # 2. UUID 필터 구성 (use_uuid_filter가 True일 때만 적용)
                if use_uuid_filter and allowed_document_uuids:
                    uuids = [uuid for uuid in allowed_document_uuids if uuid]
                    uuid_filter = None
                    if len(uuids) == 1:
                        uuid_filter = Filter.by_property("document_uuid").equal(uuids[0])
                    elif len(uuids) > 1:
                        uuid_filter = Filter.by_property("document_uuid").contains_any(uuids)
                    
                    if uuid_filter:
                        filters = filters & uuid_filter if filters else uuid_filter
                
                # 벡터 검색 실행 (v4 API)
                response = collection.query.near_vector(
                    near_vector=query_embedding.tolist(),
                    limit=search_top_k,
                    filters=filters,
                    return_metadata=['distance'],
                    return_properties=["caption", "title", "image_path", "con_type", "tags", "text", "document_uuid"]
                )
                
                # 검색 결과 로깅
                logger.debug(f"Weaviate 이미지 검색 결과: {len(response.objects)}개")
            except Exception as e:
                logger.error(f"Weaviate 이미지 검색 오류: {str(e)}")
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
                    'caption': obj.properties.get("caption", ""),
                    'title': obj.properties.get("title", f"이미지 {i}"),
                    'file_path': obj.properties.get("file_path", ""),
                    'content_type': obj.properties.get("content_type", "image"),
                    'tags': obj.properties.get("tags", []),
                    'metadata': {},
                    'document_uuid': obj.properties.get("document_uuid"),
                }
                results.append(result)
            
            # 후처리: 세션 검색 시 기본 파일들도 포함
            if session_id and results:
                try:
                    logger.info("후처리: 기본 이미지들도 검색 중...")
                    # 필터 없이 전체 검색 후 결과에서 필터링
                    default_response = collection.query.near_vector(
                        near_vector=query_embedding.tolist(),
                        limit=20,  # 더 많이 검색 후 필터링
                        return_metadata=['distance'],
                        return_properties=["caption", "title", "file_path", "content_type", "tags", "document_uuid", "session_id"]
                    )
                    
                    # 기본 이미지 결과를 결과에 추가 (session_id가 None인 것만)
                    default_count = 0
                    for i, obj in enumerate(default_response.objects):
                        # session_id가 None이거나 없는 것만 기본 파일로 간주
                        if obj.properties.get("session_id") is None:
                            score = obj.metadata.distance if obj.metadata.distance is not None else 0
                            similarity_score = 1 - score if score <= 1 else 0
                            
                            default_result = {
                                'score': similarity_score,
                                'index': len(results) + default_count,
                                'id': str(obj.uuid),
                                'caption': obj.properties.get("caption", ""),
                                'title': obj.properties.get("title", f"기본 이미지 {default_count}"),
                                'file_path': obj.properties.get("file_path", ""),
                                'content_type': obj.properties.get("content_type", "image"),
                                'tags': obj.properties.get("tags", []),
                                'metadata': {},
                                'document_uuid': obj.properties.get("document_uuid"),
                            }
                            results.append(default_result)
                            default_count += 1
                            
                            # 5개만 추가
                            if default_count >= 5:
                                break
                    
                    logger.info(f"후처리 완료: 기본 이미지 {default_count}개 추가")
                    
                except Exception as e:
                    logger.error(f"후처리 중 기본 이미지 검색 오류: {e}")
            
            logger.info(f"이미지 검색 완료: '{query[:30]}', 결과 수: {len(results)}")
            
            # 임계값 필터링
            config = RAGConfig()
            
            # 지원하는 모든 타입(image, chart 등)에 대해 검색 결과 포함
            filtered_results = [r for r in results if r['score'] >= config.IMAGE_THRESHOLD and 
                               r.get('content_type', 'image') in self.supported_types]  # 이미 변환된 content_type 사용
            
            if len(filtered_results) < len(results):
                logger.debug(f"임계값 필터링: {len(results)} → {len(filtered_results)}")
            
            # use_uuid_filter가 True일 때만 후처리 필터링도 적용
            if use_uuid_filter and allowed_document_uuids:
                before_filter_count = len(filtered_results)
                filtered_results = [res for res in filtered_results if res.get('document_uuid') in allowed_document_uuids]
                if before_filter_count != len(filtered_results):
                    logger.info(
                        "이미지 검색 결과 UUID 후처리 필터링 적용: %d -> %d",
                        before_filter_count,
                        len(filtered_results),
                    )

            # 리랭커 적용 전 결과를 저장
            original_results = filtered_results.copy()
            
            # reranker를 사용하여 결과 재정렬
            
            if self.use_reranker and self.reranker and filtered_results:
                try:
                    if cancellation_event and cancellation_event.is_set():
                        raise InterruptedError("Operation cancelled before image reranking")
                    
                    reranked_results = self.reranker.rerank(query, filtered_results, top_k=top_k, cancellation_event=cancellation_event)
                    
                    for result in reranked_results:
                        result['original_score'] = result.get('score', 0.0)
                    
                    logger.info(f"이미지 리랭킹 완료: {len(reranked_results)}개")
                    
                    return reranked_results[:top_k]
                except Exception as e:
                    logger.error(f"Reranker 사용 중 오류 발생: {str(e)}")
                    # Reranker 오류 시 원래 결과 반환
                    return original_results[:top_k]
            
            # top_k 제한
            return filtered_results[:top_k]
            
        except Exception as e:
            logger.error(f"Weaviate 검색 중 오류 발생: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return []

    def cleanup(self):
        """GPU 리소스를 정리합니다."""
        if self.reranker and hasattr(self.reranker, "cleanup"):
            try:
                self._ensure_reranker()
                if self.reranker:
                    self.reranker.cleanup()
            except Exception as exc:
                logger.error(f"이미지 리랭커 정리 중 오류: {exc}")
        self.reranker = None

        if hasattr(self.shared_embedding, "cleanup"):
            try:
                self.shared_embedding.cleanup()
            except Exception as exc:
                logger.error(f"공유 임베딩 정리 중 오류: {exc}")

if __name__ == "__main__":
    print("이미지 검색기 스크립트 시작")
    config = RAGConfig()
    print("RAGConfig 로드 완료")
    try:
        searcher = ImageSearcher()
        print("ImageSearcher 초기화 완료")
        if searcher.reranker:
            print("Reranker 초기화 완료")
        else:
            print("Reranker 사용하지 않음")
    except Exception as e:
        print(f"ImageSearcher 초기화 중 오류 발생: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
        
    while True:
        query = input("검색 쿼리를 입력하세요 (종료하려면 'exit' 입력): ")
        if query.lower() == 'exit':
            break
        
        # 사용자 정의 top_k 입력 받기 (선택 사항)
        top_k_input = input(f"검색 결과 수를 입력하세요 (기본값: {config.TOP_K}): ")
        top_k = int(top_k_input) if top_k_input.isdigit() else None
        
        results = searcher.search(query, top_k=top_k)
        
        # 검색 결과 출력
        print(f"\n[검색 결과] (최대 5개):")
        for i, result in enumerate(results[:5]):
            # 원래 점수가 있는 경우 함께 표시 (리랭크된 결과인 경우)
            score_display = f"{result['score']:.4f}"
            if 'original_score' in result:
                score_display += f" (원래 점수: {result['original_score']:.4f})"
                print(f"{i+1}. {result['title']} - 유사도: {score_display} [리랭크됨]")
            else:
                print(f"{i+1}. {result['title']} - 유사도: {score_display}")
            print(f"   캡션: {result.get('caption', '캡션 없음')[:200]}...")
            print(f"   파일 경로: {result.get('file_path', 'N/A')}")
            print(f"   콘텐츠 타입: {result.get('content_type', 'image')}")
            print()
