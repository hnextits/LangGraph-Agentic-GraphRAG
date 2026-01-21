"""
RAG 시스템을 위한 이미지 리랭커 모듈 (SGLang 기반)
"""
import os
import logging
import sys
import threading
import subprocess
import time
from typing import List, Dict, Any, Optional
import requests

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from config import RAGConfig

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class RAGReranker:
    """SGLang 기반 이미지 리랭커 (/v1/rerank API 사용)"""
    
    _lock = threading.Lock()
    _server_process = None
    
    def __init__(self, model_name: str = None, ollama_host: str = None):
        """리랭커 초기화"""
        config = RAGConfig()
        self.model_name = model_name if model_name else config.RERANKER_MODEL_NAME
        self.reranker_server_url = "http://127.0.0.1:30002"
        self.batch_size = getattr(config, 'RERANKER_BATCH_SIZE', 4)
        self.max_length = getattr(config, 'RERANKER_MAX_LENGTH', 8192)
        
        logger.info(f"이미지 리랭커 초기화: {self.model_name}, server: {self.reranker_server_url}")
    
    def _check_server_running(self):
        """서버가 실행 중인지 확인"""
        try:
            response = requests.get(f"{self.reranker_server_url}/health", timeout=2)
            return response.status_code == 200
        except:
            return False
    
    def _start_server(self):
        """SGLang 리랭커 서버 시작 (텍스트 리랭커와 공유)"""
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
    
    def _load_model(self):
        """서버 연결 확인 및 시작"""
        with self.__class__._lock:
            if not self._check_server_running():
                logger.info("리랭커 서버가 실행 중이지 않습니다. 서버를 시작합니다...")
                return self._start_server()
            return True
    
    def format_instruction(self, instruction: str, query: str, doc: str) -> str:
        """프롬프트 형식"""
        if instruction is None:
            instruction = 'Given a web search query, retrieve relevant passages that answer the query'
        return f'Instruct: {instruction}\nQuery: {query}\nDocument: {doc}\nAnswer:'
    
    def compute_score_single(self, query: str, passage: str, instruction: str = None) -> float:
        """단일 문서의 점수 계산"""
        try:
            formatted_text = self.format_instruction(instruction, query, passage)
            url = f"{self.reranker_server_url}/v1/rerank"
            data = {
                "model": self.model_name.split("/")[-1],
                "query": query,
                "documents": [passage],
                "top_k": 1
            }
            
            response = requests.post(url, json=data, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            if "results" in result and len(result["results"]) > 0:
                return result["results"][0].get("relevance_score", 0.0)
            return 0.0
            
        except Exception as e:
            logger.error(f"Score computation error: {e}")
            return 0.0
    
    def compute_score_batch(
        self,
        query: str,
        passages: List[str],
        instruction: str = None,
        cancellation_event: Optional[threading.Event] = None
    ) -> List[float]:
        """배치로 여러 문서의 점수 계산"""
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
            if "results" in result:
                scores = [item.get("relevance_score", 0.0) for item in result["results"]]
                return scores
            return [0.0] * len(passages)
            
        except Exception as e:
            logger.error(f"Batch score computation error: {e}")
            return [0.0] * len(passages)
    
    def rerank(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        top_k: int = 5,
        instruction: str = None,
        cancellation_event: Optional[threading.Event] = None
    ) -> List[Dict[str, Any]]:
        """문서를 리랭킹"""
        if not documents:
            return []
        
        if cancellation_event and cancellation_event.is_set():
            raise InterruptedError("Reranking cancelled")
        
        passages = [doc.get('text', '') or doc.get('content', '') for doc in documents]
        scores = self.compute_score_batch(query, passages, instruction, cancellation_event)
        
        for doc, score in zip(documents, scores):
            doc['rerank_score'] = float(score)
        
        reranked = sorted(documents, key=lambda x: x.get('rerank_score', 0), reverse=True)
        return reranked[:top_k]
    
    def cleanup(self):
        """리소스 정리"""
        logger.info("Image reranker cleanup (no resources to release)")
