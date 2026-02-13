#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""RAG 시스템 라우터 - 항상 RAG 검색을 사용하여 텍스트와 이미지 인덱스를 모두 검색합니다. (TAG 구분 없이 항상 RAG 사용)"""

import importlib
import json
import logging
import os
import concurrent.futures
import threading
from typing import Dict, List, Any, Optional, Tuple, Set

from config import RAGConfig

# Optional heavy dependency (sentence-transformers)
try:
    from sentence_transformers import CrossEncoder  # type: ignore
except ImportError:  # pragma: no cover
    CrossEncoder = None  # type: ignore


from parallel_search import ParallelSearcher
from query_rewriter import QueryRewriter

# 로깅 설정
logger = logging.getLogger(__name__)

class RAGRouter:
    """
    RAG 라우터
    질문을 분석하여 적절한 데이터 타입별 RAG 파이프라인으로 라우팅합니다.
    """
    
    def __init__(self, config: RAGConfig = None):
        """
        라우터 초기화
        
        Args:
            config: RAGConfig 인스턴스
        """
        if config is None:
            config = RAGConfig()
        
        self.rag_config = config
        self.searchers = {}
        self.config = self._load_config()
        self._load_searchers()

        # CrossEncoder 초기화 (선택 사항)
        self.ce_model = None
        if self.config.get("enable_cross_encoder_rerank", False):
            if CrossEncoder is None:
                logger.warning("sentence-transformers 가 설치되지 않아 CrossEncoder 기능을 비활성화합니다.")
        
        # 쿼리 재작성기 초기화 (config에서 비활성화 가능)
        if getattr(config, "use_query_rewriter", False):
            self.query_rewriter = QueryRewriter()
        else:
            self.query_rewriter = None
        
        # 병렬 검색 조정기 초기화 (쿼리 재작성기 전달)
        self.parallel_searcher = ParallelSearcher(self.rag_config, self.searchers, self.query_rewriter)
        

    def cleanup(self):
        """라우터가 로드한 모든 서브 컴포넌트를 정리합니다."""
        for name, searcher in list(self.searchers.items()):
            cleanup_fn = getattr(searcher, "cleanup", None)
            if callable(cleanup_fn):
                try:
                    cleanup_fn()
                except Exception:
                    logger.exception("검색기 정리 중 오류 발생: %s", name)
        self.searchers.clear()

        if self.query_rewriter and hasattr(self.query_rewriter, "cleanup"):
            try:
                self.query_rewriter.cleanup()
            except Exception:
                logger.exception("QueryRewriter 정리 중 오류 발생")
    
    def _load_config(self) -> Dict[str, Any]:
        """
        기본 설정 로드
        
        Returns:
            설정 딕셔너리
        """
        default_config = {
            "searchers": [
                {"name": "text", "module": "rag_text.text_search", "class": "TextSearcher"},
                {"name": "image", "module": "rag_image.image_search", "class": "ImageSearcher"}
            ],
            "default_pipeline": "text",
            "routing_thresholds": {
                "text": 0.3,
                "image": 0.3
            },
            # --- optional performance features ---
            "enable_parallel_search": False, # 병렬 처리 옵션으로 이름 변경
            "enable_early_exit": True,
            "early_exit_threshold": 0.5,
            "enable_cross_encoder_rerank": False,
            "cross_encoder_model": "cross-encoder/ms-marco-MiniLM-L-6-v2"
        }
        
        return default_config
    
    def _load_searchers(self):
        """
        설정에 따라 검색기 모듈 로드
        """
        for searcher_config in self.config["searchers"]:
            name = searcher_config["name"]
            module_name = searcher_config["module"]
            class_name = searcher_config["class"]
            
            try:
                # 모듈 동적 로드
                module = importlib.import_module(module_name)
                searcher_class = getattr(module, class_name)
                
                # 검색기 인스턴스 생성
                self.searchers[name] = searcher_class()
            except (ImportError, AttributeError) as e:
                logger.warning(f"검색기 로드 실패: {name}, 오류: {str(e)}")

    def route_query(self, query: str) -> List[str]:
        """
        항상 RAG 검색을 사용하도록 수정된 라우팅 메서드
        이제 TAG 검색은 사용하지 않고, 항상 텍스트와 이미지 인덱스를 모두 검색합니다.
        
        Args:
            query: 사용자 질문 (로깅 및 예외 처리용)
            
        Returns:
            처리할 검색기 이름 리스트 (항상 text와 image 포함)
        """
        # 항상 text와 image 검색기를 모두 사용
        selected_searchers = []
        
        # text 검색기가 있으면 추가
        if 'text' in self.searchers:
            selected_searchers.append('text')
        if 'image' in self.searchers:
            selected_searchers.append('image')
        
        # 선택된 검색기가 없으면 기본 검색기 사용 (예외 처리)
        if not selected_searchers:
            default = self.config.get("default_pipeline", "text")
            if default in self.searchers:
                selected_searchers = [default]
                logger.warning("검색기를 찾을 수 없어 기본 검색기를 사용합니다: %s", default)
        
        return selected_searchers
    
    def search(
        self,
        query: str,
        top_k: int = 15,
        cancellation_event: Optional[threading.Event] = None,
        allowed_document_uuids: Optional[Set[str]] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        쿼리를 ParallelSearcher에 위임하여 최종 결과를 반환합니다.
        항상 RAG 검색을 사용하도록 수정되었습니다.

        Args:
            query (str): 사용자 원본 쿼리
            top_k (int): 반환할 최종 결과의 수
            cancellation_event (Optional[threading.Event]): 취소 이벤트
            allowed_document_uuids (Optional[Set[str]]): 허용된 문서 UUID 집합
            session_id (Optional[str]): 세션 ID (필터링용)

        Returns:
            Dict[str, Any]: 통합되고 재정렬된 검색 결과
        """
        # 1. 항상 text와 image 검색기를 사용하도록 route_query 호출
        selected_searchers = self.route_query(query)

        # 취소 확인
        if cancellation_event and cancellation_event.is_set():
            raise InterruptedError("Operation cancelled before parallel search")

        # 2. ParallelSearcher에 검색 위임
        search_results = self.parallel_searcher.search(
            query,
            selected_searchers,
            top_k,
            cancellation_event=cancellation_event,
            allowed_document_uuids=allowed_document_uuids,
            session_id=session_id,
        )
        
        # 3. 메타데이터 보강 및 결과 반환
        search_results["metadata"]["search_mode"] = "RAG"  # 항상 RAG 모드 사용
        
        return search_results
    def _similarity_score(self, q: str, res) -> float:
        """CrossEncoder 기반 간단 유사도 점수 계산"""
        if self.ce_model is None:
            return 0.0
        texts: List[str] = []
        if isinstance(res, str):
            texts.append(res)
        elif isinstance(res, dict) and 'text' in res:
            texts.append(res['text'])
        elif isinstance(res, list):
            for item in res:
                if isinstance(item, str):
                    texts.append(item)
                elif isinstance(item, dict) and 'text' in item:
                    texts.append(item['text'])
        if not texts:
            return 0.0
        try:
            pairs = [(q, t[:512]) for t in texts]
            scores = self.ce_model.predict(pairs)
            return float(max(scores))
        except Exception:
            return 0.0
