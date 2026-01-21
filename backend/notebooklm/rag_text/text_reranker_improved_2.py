#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import sys
import logging
import threading
import subprocess
import time
from typing import List, Dict, Any, Optional
import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import RAGConfig

logger = logging.getLogger(__name__)

class ImprovedTextReranker:
    """SGLang 기반 텍스트 리랭커 (/v1/rerank API 사용)"""
    
    _lock = threading.Lock()
    _server_process = None
    
    def __init__(
        self,
        model_name: str = None,
        device: str = None,
        max_length: int = 512,
        batch_size: int = 8
    ):
        self.config = RAGConfig()
        self.model_name = model_name or "Qwen/Qwen3-Reranker-4B"
        self.reranker_server_url = "http://127.0.0.1:30002"
        self.max_length = max_length
        self.batch_size = batch_size
        
        self.stats = {
            'total_queries': 0,
            'total_documents': 0,
            'avg_processing_time': 0.0
        }
        
        logger.info(f"텍스트 리랭커 초기화: {self.model_name}, server: {self.reranker_server_url}")

    def _check_server_running(self):
        """서버가 실행 중인지 확인"""
        try:
            response = requests.get(f"{self.reranker_server_url}/health", timeout=2)
            return response.status_code == 200
        except:
            return False
    
    def _start_server(self):
        """SGLang 리랭커 서버 시작"""
        if self.__class__._server_process is not None:
            if self.__class__._server_process.poll() is None:
                logger.info("리랭커 서버가 이미 실행 중입니다.")
                return True
        
        logger.info("SGLang 리랭커 서버를 시작합니다...")
        try:
            log_file = open("sglang_reranker_server.log", "w")
            self.__class__._server_process = subprocess.Popen(
                [
                    "python", "-m", "sglang.launch_server",
                    "--model-path", self.model_name,
                    "--port", "30002",
                    "--host", "127.0.0.1",
                    "--mem-fraction-static", "0.15",
                    "--disable-cuda-graph",
                    "--trust-remote-code"
                ],
                env={**os.environ, "CUDA_VISIBLE_DEVICES": "1"},
                stdout=log_file,
                stderr=subprocess.STDOUT
            )
            logger.info(f"리랭커 서버 시작 중... (PID: {self.__class__._server_process.pid})")
            
            for i in range(30):
                time.sleep(1)
                if self._check_server_running():
                    logger.info(f"✓ 리랭커 서버 시작 완료 ({i+1}초 소요)")
                    return True
            
            logger.error("리랭커 서버 시작 시간 초과")
            return False
        except Exception as e:
            logger.error(f"리랭커 서버 시작 실패: {e}")
            return False
    
    def _load_model(self) -> bool:
        """서버 연결 확인 및 시작"""
        with self.__class__._lock:
            if not self._check_server_running():
                logger.info("리랭커 서버가 실행 중이지 않습니다. 서버를 시작합니다...")
                return self._start_server()
            return True

    def compute_similarity_batch(self, query: str, passages: List[str], cancellation_event: Optional[threading.Event] = None) -> List[float]:
        """배치로 여러 문서의 유사도를 계산"""
        if not self._load_model():
            logger.error("리랭커 서버 시작 실패")
            return [0.0] * len(passages)
        
        try:
            url = f"{self.reranker_server_url}/v1/rerank"
            data = {
                "model": self.model_name.split("/")[-1],
                "query": query,
                "documents": passages,
                "top_k": len(passages)
            }
            
            response = requests.post(url, json=data, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            
            # SGLang rerank API 응답 파싱
            if "results" in result:
                scores = [item.get("relevance_score", 0.0) for item in result["results"]]
                return scores
            else:
                logger.warning(f"Unexpected rerank response format: {result}")
                return [0.0] * len(passages)
            
        except Exception as e:
            logger.error(f"Reranking error: {e}")
            return [0.0] * len(passages)

    def rerank(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        top_k: int = 5,
        cancellation_event: Optional[threading.Event] = None
    ) -> List[Dict[str, Any]]:
        """문서를 리랭킹"""
        if not documents:
            return []
        
        if cancellation_event and cancellation_event.is_set():
            raise InterruptedError("Reranking cancelled")
        
        passages = [doc.get('text', '') or doc.get('content', '') for doc in documents]
        scores = self.compute_similarity_batch(query, passages, cancellation_event)
        
        for doc, score in zip(documents, scores):
            doc['rerank_score'] = float(score)
        
        reranked = sorted(documents, key=lambda x: x.get('rerank_score', 0), reverse=True)
        return reranked[:top_k]

    def cleanup(self):
        """리소스 정리"""
        logger.info("Reranker cleanup (no resources to release)")
