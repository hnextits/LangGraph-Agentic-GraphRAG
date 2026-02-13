#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import sys
import logging
import threading
import requests
from typing import List, Dict, Any, Optional
import time

# config.py 파일이 있는 디렉토리를 sys.path에 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import RAGConfig

# 로깅 설정
logger = logging.getLogger(__name__)

# Qwen3-Reranker 프롬프트 포맷 상수
_QUERY_PREFIX = '<|im_start|>system\nJudge whether the Document meets the requirements based on the Query and the Instruct provided. Note that the answer can only be "yes" or "no".<|im_end|>\n<|im_start|>user\n'
_DOC_SUFFIX = '<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n'
_INSTRUCTION = 'Given a web search query, retrieve relevant passages that answer the query.\n'


class ImprovedTextReranker:
    """SGLang /v1/rerank API + Qwen3-Reranker 프롬프트 포맷 기반 텍스트 리랭커."""
    _ready = False
    _lock = threading.Lock()

    def __init__(
        self,
        model_name: str = None,
        device: str = None,
        max_length: int = 512,
        batch_size: int = 8
    ):
        self.config = RAGConfig()
        
        self.model_name = model_name or self.config.SGLANG_RERANKER_MODEL
        self.endpoint = self.config.SGLANG_RERANKER_ENDPOINT  # e.g. "http://localhost:30002"
        self._api_url = f"{self.endpoint}/v1/rerank"
        self._timeout = 60
        self._session = requests.Session()
        
        self.max_length = max_length
        self.batch_size = batch_size
        
        self.stats = {
            'total_queries': 0,
            'total_documents': 0,
            'avg_processing_time': 0.0
        }
        
        logger.info(f"텍스트 리랭커 초기화 완료 (SGLang): {self.model_name} -> {self.endpoint}")

    def _ensure_server_ready(self) -> bool:
        """SGLang 리랭커 서버가 응답 가능한지 확인합니다. 미기동 시 자동 기동."""
        from notebooklm.sglang_server_manager import sglang_manager

        if self.__class__._ready:
            try:
                resp = self._session.get(f"{self.endpoint}/health", timeout=3)
                if resp.status_code == 200:
                    sglang_manager.touch("reranker")
                    return True
            except Exception:
                pass
            self.__class__._ready = False

        with self.__class__._lock:
            if self.__class__._ready:
                sglang_manager.touch("reranker")
                return True
            try:
                resp = self._session.get(f"{self.endpoint}/health", timeout=5)
                if resp.status_code == 200:
                    self.__class__._ready = True
                    sglang_manager.touch("reranker")
                    logger.info("SGLang reranker server ready: %s", self.endpoint)
                    return True
            except (requests.ConnectionError, requests.Timeout, Exception):
                pass

            # 서버가 응답하지 않으면 sglang_manager로 자동 기동
            # cuda:1 GPU 메모리 경합 방지: 임베딩 서버가 살아있으면 먼저 종료
            if sglang_manager.is_running("embedding"):
                logger.info("리랭커 기동 전 임베딩 서버 종료 (cuda:1 메모리 확보)")
                sglang_manager.shutdown_server("embedding")
                from notebooklm.shared_embedding import SharedEmbeddingModel
                SharedEmbeddingModel._ready = False

            logger.info("SGLang reranker server 미기동 → acquire로 자동 기동 시도")
            try:
                if sglang_manager.acquire("reranker"):
                    sglang_manager.release("reranker")
                    self.__class__._ready = True
                    return True
            except Exception as e:
                logger.error("SGLang reranker 자동 기동 실패: %s", e)
            return False

    def _load_model(self) -> bool:
        """서버 연결 확인 (하위 호환성 유지)."""
        return self._ensure_server_ready()

    def compute_similarity_batch(self, query: str, passages: List[str], cancellation_event: Optional[threading.Event] = None) -> List[float]:
        """SGLang /v1/rerank API를 호출하여 배치 유사도를 계산합니다."""
        if not self._ensure_server_ready():
            logger.error("SGLang reranker server not available")
            return [0.0] * len(passages)
        
        if cancellation_event and cancellation_event.is_set():
            raise InterruptedError("Reranking operation cancelled")

        try:
            # Qwen3-Reranker 프롬프트 포맷 적용
            formatted_query = f"{_QUERY_PREFIX}<Instruct>: {_INSTRUCTION}<Query>: {query}\n"
            formatted_docs = [f"<Document>: {doc} {_DOC_SUFFIX}" for doc in passages]

            payload = {
                "query": formatted_query,
                "documents": formatted_docs,
            }
            resp = self._session.post(
                self._api_url,
                json=payload,
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            
            # SGLang 0.5.2 응답: 리스트 [{"score": 0.95, "index": 0, ...}, ...]
            # 또는 dict {"results": [{"index": 0, "relevance_score": 0.95}, ...]}
            if isinstance(data, list):
                results_data = data
                score_map = {item["index"]: item.get("score", item.get("relevance_score", 0.0)) for item in results_data}
            else:
                results_data = data.get("results", [])
                score_map = {item["index"]: item.get("relevance_score", item.get("score", 0.0)) for item in results_data}
            scores = [score_map.get(i, 0.0) for i in range(len(passages))]
            
            return scores
            
        except requests.ConnectionError:
            logger.error("SGLang reranker server connection failed: %s", self._api_url)
            return [0.0] * len(passages)
        except Exception as e:
            logger.error(f"SGLang rerank API 호출 오류: {e}")
            return [0.0] * len(passages)
    
    def rerank(
        self,
        query: str,
        results: List[Dict[str, Any]],
        top_k: int = None,
        min_score: float = 0.0,
        cancellation_event: Optional[threading.Event] = None
    ) -> List[Dict[str, Any]]:
        if not results:
            logger.info("리랭킹할 결과가 없습니다.")
            return []
        
        start_time = time.time()
        logger.info(f"리랭킹 시작 (SGLang): {len(results)}개 문서")
        
        self.stats['total_queries'] += 1
        self.stats['total_documents'] += len(results)
        
        passages = []
        for result in results:
            text = result.get('text', result.get('content', ''))
            passages.append(text)
        
        # 취소 확인
        if cancellation_event and cancellation_event.is_set():
            raise InterruptedError("Operation cancelled during text reranking")

        try:
            scores = self.compute_similarity_batch(query, passages, cancellation_event=cancellation_event)
            logger.info(f"리랭킹 점수 계산 완료: {len(scores)}개 점수")
        except Exception as e:
            logger.error(f"리랭킹 점수 계산 중 오류 발생: {e}")
            scores = [result.get('score', 0.0) for result in results]
            logger.warning("오류로 인해 원래 점수를 유지합니다.")
        
        # 점수 업데이트
        for result, score in zip(results, scores):
            result['original_score'] = result.get('score', 0.0)
            if isinstance(score, (list, tuple)):
                score_value = float(score[0]) if len(score) > 0 else 0.0
            else:
                score_value = float(score)
            result['rerank_score'] = score_value
            result['score'] = score_value
        
        results.sort(key=lambda x: x.get('rerank_score', -float('inf')), reverse=True)
        
        filtered_results = [r for r in results if r.get('rerank_score', -float('inf')) >= min_score]
        
        if not filtered_results and results:
            filtered_results = [results[0]]
            logger.warning(f"모든 결과가 임계값 {min_score} 미만. 최고 점수 결과 반환")
        
        if top_k is not None:
            filtered_results = filtered_results[:top_k]
        
        processing_time = time.time() - start_time
        if self.stats['total_queries'] > 0:
            self.stats['avg_processing_time'] = (
                (self.stats['avg_processing_time'] * (self.stats['total_queries'] - 1) + processing_time)
                / self.stats['total_queries']
            )

        scores_info = [f"{r.get('rerank_score', 0.0):.2f}" for r in filtered_results[:5]]
        logger.info(
            f"재정렬 완료 - 쿼리: '{query[:50]}...', "
            f"결과: {len(filtered_results)}/{len(results)}, "
            f"처리시간: {processing_time:.3f}s, "
            f"상위 점수: {scores_info}"
        )
        
        return filtered_results

    def cleanup(self):
        """리소스를 정리합니다."""
        self.__class__._ready = False
        try:
            self._session.close()
        except Exception:
            pass
        logger.info("SGLang 리랭커 클라이언트 정리 완료")