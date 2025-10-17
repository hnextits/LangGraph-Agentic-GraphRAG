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
from typing import List, Dict, Any, Optional, Tuple
from PIL import Image
import weaviate

from config import RAGConfig
from shared_embedding import shared_embedding
from rag_image.image_reranker import RAGReranker
from weaviate_utils import create_schema

# 로깅 설정
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # 로그 레벨을 DEBUG로 변경

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
        
        # 공유 임베딩 모델 사용
        from shared_embedding import shared_embedding
        self.shared_embedding = shared_embedding
        
        # 메모리 정리
        torch.cuda.empty_cache()
        
        # 공유 임베딩 모델을 사용하므로 별도의 모델 로드는 필요 없음
        # 메모리 최적화를 위해 주석 처리
        self.tokenizer = None
        self.model = None
        
        # 공유 임베딩 모델이 제대로 로드되었는지 확인
        if self.shared_embedding.is_loaded:
            logger.info(f"공유 임베딩 모델 사용 중: {self.shared_embedding.model_name} (디바이스: {self.shared_embedding.device})")
        else:
            logger.error("공유 임베딩 모델이 로드되지 않았습니다.")
        
        # 리랭커 초기화
        self.reranker = None
        if self.use_reranker:
            try:
                self.reranker = RAGReranker()
                logger.info("리랭커 초기화 완료")
            except Exception as e:
                logger.error(f"리랭커 초기화 중 오류 발생: {str(e)}")
                import traceback
                logger.error(traceback.format_exc())
                self.reranker = None
        
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
            # 공유 임베딩 모델 사용
            if not self.shared_embedding.is_loaded:
                logger.error("공유 임베딩 모델이 로드되지 않았습니다.")
                return np.random.rand(self.dimension).astype('float32')
            
            # 공유 임베딩 모델을 통한 임베딩 생성
            embedding = self.shared_embedding.generate_embedding(text)
            
            if len(embedding) != self.dimension:
                logger.warning(f"임베딩 차원이 예상과 다릅니다: {len(embedding)} vs {self.dimension}")
            
            return embedding.astype('float32')
        except Exception as e:
            logger.error(f"공유 임베딩 모델 임베딩 생성 중 오류 발생: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return np.random.rand(self.dimension).astype('float32')  # 오류 발생 시 랜덤 벡터로 대체

    def search(self, query: str, top_k: int = 10, rerank: bool = True, cancellation_event: Optional[threading.Event] = None) -> List[Dict[str, Any]]:
        """이미지 쿼리로 검색을 수행합니다."""
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
            logger.info(f"정규화된 쿼리: '{normalized_query}'")
            
            # 취소 확인
            if cancellation_event and cancellation_event.is_set():
                raise InterruptedError("Operation cancelled before image query embedding generation")
            
            # 쿼리 임베딩 생성
            query_embedding = self.shared_embedding.generate_embedding(normalized_query)
            
            # 임베딩 정보 로깅
            embedding_norm = np.linalg.norm(query_embedding)
            embedding_mean = np.mean(query_embedding)
            embedding_std = np.std(query_embedding)
            logger.info(f"이미지 검색 쿼리 임베딩 생성 성공: '{normalized_query[:50]}...'")
            logger.info(f"임베딩 통계 - 노름: {embedding_norm:.4f}, 평균: {embedding_mean:.4f}, 표준편차: {embedding_std:.4f}")
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
            
            logger.debug(f"Weaviate 이미지 검색 시작: 클래스={self.class_name}, top_k={search_top_k}")
            
            try:
                # metadata 필드에 대한 서브 셀렉션 문제 해결
                vector_search_results = (
                    self.client.query
                    .get(self.class_name, ["caption", "title", "image_path", "con_type", "tags", "text"])
                    .with_near_vector({
                        "vector": query_embedding.tolist()
                    })
                    .with_limit(search_top_k)
                    .do()
                )
                
                # 검색 결과 로깅
                logger.debug(f"Weaviate 이미지 검색 결과: {vector_search_results}")
            except Exception as e:
                logger.error(f"Weaviate 이미지 검색 오류: {str(e)}")
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
                    
                    # 텍스트 필드 준비 - text > caption > title 우선순위
                    text = item.get("text", "")
                    caption = item.get("caption", "")
                    title = item.get("title", "")
                    
                    # text 필드 우선, 없으면 caption, 그것도 없으면 title
                    doc_text = text if text else (caption if caption else title)
                    
                    result = {
                        'score': similarity_score,
                        'index': i,
                        'id': item.get("id", f"img_{i}"),
                        'title': title if title else f"이미지 {i}",
                        'caption': caption,
                        'file_path': item.get("image_path", ""),  # image_path를 file_path로 변환
                        'content_type': item.get("con_type", "image"),  # con_type을 content_type으로 변환
                        'tags': item.get("tags", []),
                        'page_num': 1,  # 기본값 사용
                        'text': doc_text,  # OCR 텍스트 우선 사용
                    }
                    results.append(result)
            
            logger.info(f"쿼리 '{query}'에 대한 검색 완료, 결과 수: {len(results)}")
            
            # 검색 결과의 content_type 확인
            content_types = {}
            for r in results[:10]:
                ct = r.get('content_type', 'None')  # 이미 변환된 content_type 사용
                if ct in content_types:
                    content_types[ct] += 1
                else:
                    content_types[ct] = 1
            logger.info(f"검색 결과의 content_type 분포: {content_types}")
            
            # 상위 3개 결과 상세 로깅
            for i, r in enumerate(results[:3]):
                logger.info(f"검색 결과 {i+1}: ID={r.get('id', 'N/A')}, 점수={r.get('score', 0):.4f}, content_type={r.get('content_type', 'N/A')}")
            
            # 임계값 필터링
            config = RAGConfig()
            
            # 지원하는 모든 타입(image, chart 등)에 대해 검색 결과 포함
            filtered_results = [r for r in results if r['score'] >= config.IMAGE_THRESHOLD and 
                               r.get('content_type', 'image') in self.supported_types]  # 이미 변환된 content_type 사용
            
            if len(filtered_results) < len(results):
                logger.info(f"임계값({config.IMAGE_THRESHOLD}) 및 타입 필터링 후 결과 수: {len(filtered_results)}")
                
            # 검색 결과의 content_type 분포 확인
            content_types_filtered = {}
            for r in filtered_results[:10]:
                ct = r.get('content_type', 'None')  # 이미 변환된 content_type 사용
                if ct in content_types_filtered:
                    content_types_filtered[ct] += 1
                else:
                    content_types_filtered[ct] = 1
            logger.info(f"필터링 후 content_type 분포: {content_types_filtered}")
            
            # 리랭커 적용 전 결과를 저장
            original_results = filtered_results.copy()
            
            # reranker를 사용하여 결과 재정렬
            logger.info(f"Rerank 파라미터: {rerank}, 리랭커 사용 설정: {self.use_reranker}, 리랭커 객체 존재: {self.reranker is not None}, 결과 수: {len(filtered_results)}")
            
            if self.use_reranker and self.reranker and filtered_results:
                try:
                    logger.info(f"Reranker를 사용하여 결과 재정렬 시작")
                    # 취소 확인
                    if cancellation_event and cancellation_event.is_set():
                        raise InterruptedError("Operation cancelled before image reranking")
                    
                    reranked_results = self.reranker.rerank(query, filtered_results, top_k=top_k, cancellation_event=cancellation_event)
                    
                    # 점수 분포 확인을 위한 로깅
                    scores = [r['score'] for r in reranked_results]
                    if scores:
                        logger.info(f"점수 분포 - 최소: {min(scores):.4f}, 최대: {max(scores):.4f}, 평균: {sum(scores)/len(scores):.4f}")
                    
                    # 원본 점수 그대로 사용 (정규화 없이)
                    for result in reranked_results:
                        # 원본 점수를 그대로 유지
                        result['original_score'] = result.get('score', 0.0)  # 참조용으로 원본 점수 저장
                    
                    logger.info(f"Reranker를 사용하여 결과 재정렬 완료, 결과 수: {len(reranked_results)}")
                    
                    # 리랭킹된 이미지 결과 출력
                    print(f"\n=== 이미지 리랭킹 결과 (top {min(len(reranked_results), 3)}) ===")
                    for i, result in enumerate(reranked_results[:3]):
                        print(f"{i+1}. ID: {result.get('id', 'N/A')}")
                        print(f"   정규화 점수: {result.get('score', 0):.4f}")
                        print(f"   원본 점수: {result.get('original_score', 0):.4f}")
                        print(f"   제목: {result.get('title', '제목 없음')}")
                        caption = result.get('caption') or '캡션 없음'
                        print(f"   캡션: {caption[:100]}...")
                        print()
                    
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
