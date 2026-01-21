#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
SGLang 기반 공유 임베딩 모델 (OpenAI 호환 API 사용)
SGLang 서버를 별도로 실행하고 OpenAI 클라이언트로 호출
"""

import os
import sys
import threading
import numpy as np
import logging
import subprocess
import time
import requests

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config import RAGConfig

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

try:
    import openai
except ImportError:
    openai = None
    logger.warning("OpenAI not installed. Please install it with: pip install openai")

from typing import Optional, List, Union

class SharedEmbeddingModel:
    """
    싱글톤 패턴으로 구현된 공유 임베딩 모델 (SGLang 서버 + OpenAI 클라이언트)
    서버가 없으면 자동으로 시작
    """
    _instance = None
    _client = None
    _server_process = None
    _lock = threading.Lock()
    _load_count = 0

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super(SharedEmbeddingModel, cls).__new__(cls)
        return cls._instance

    def __init__(self, model_name=None, device=None):
        if hasattr(self, '_initialized') and self._initialized:
            return
        
        config = RAGConfig()
        self.model_name = model_name or config.EMBEDDING_MODEL
        self.device = device or config.EMBEDDING_DEVICE
        self.embedding_server_url = "http://127.0.0.1:30001/v1"
        self._initialized = True
        logger.info(f"SharedEmbeddingModel initialized with model: {self.model_name}, server: {self.embedding_server_url}")

    def _check_server_running(self):
        """서버가 실행 중인지 확인"""
        try:
            response = requests.get(f"{self.embedding_server_url.replace('/v1', '')}/health", timeout=2)
            return response.status_code == 200
        except:
            return False
    
    def _start_server(self):
        """SGLang 임베딩 서버 시작"""
        if self.__class__._server_process is not None:
            if self.__class__._server_process.poll() is None:
                logger.info("임베딩 서버가 이미 실행 중입니다.")
                return True
        
        logger.info("SGLang 임베딩 서버를 시작합니다...")
        try:
            log_file = open("sglang_embedding_server.log", "w")
            self.__class__._server_process = subprocess.Popen(
                [
                    "python", "-m", "sglang.launch_server",
                    "--model-path", self.model_name,
                    "--port", "30001",
                    "--host", "127.0.0.1",
                    "--mem-fraction-static", "0.15",
                    "--disable-cuda-graph",
                    "--trust-remote-code",
                    "--is-embedding"
                ],
                env={**os.environ, "CUDA_VISIBLE_DEVICES": "1"},
                stdout=log_file,
                stderr=subprocess.STDOUT
            )
            logger.info(f"임베딩 서버 시작 중... (PID: {self.__class__._server_process.pid})")
            
            for i in range(30):
                time.sleep(1)
                if self._check_server_running():
                    logger.info(f"✓ 임베딩 서버 시작 완료 ({i+1}초 소요)")
                    return True
            
            logger.error("임베딩 서버 시작 시간 초과")
            return False
        except Exception as e:
            logger.error(f"임베딩 서버 시작 실패: {e}")
            return False

    def _ensure_client_ready(self):
        """OpenAI 클라이언트가 준비되었는지 확인하고, 서버가 없으면 시작"""
        with self.__class__._lock:
            # 서버 확인 및 시작
            if not self._check_server_running():
                logger.info("임베딩 서버가 실행 중이지 않습니다. 서버를 시작합니다...")
                if not self._start_server():
                    raise RuntimeError("임베딩 서버 시작 실패")
            
            # 클라이언트 초기화
            if self.__class__._client is None:
                self.__class__._load_count += 1
                logger.info(f"Initializing OpenAI client (attempt #{self.__class__._load_count})")
                
                if openai is None:
                    raise ImportError("OpenAI is not installed. Please install it with: pip install openai")
                
                self.__class__._client = openai.Client(
                    base_url=self.embedding_server_url,
                    api_key="EMPTY"
                )
                logger.info(f"✓ OpenAI client initialized successfully")

    def load_model(self):
        """클라이언트를 명시적으로 초기화"""
        self._ensure_client_ready()

    def generate_embedding(self, text: Union[str, List[str]], normalize: bool = True) -> Optional[np.ndarray]:
        """
        텍스트의 임베딩을 생성합니다.
        
        Args:
            text: 임베딩을 생성할 텍스트 (문자열 또는 문자열 리스트)
            normalize: 임베딩 정규화 여부
            
        Returns:
            임베딩 벡터 (numpy array)
        """
        if not text:
            return None
        
        self._ensure_client_ready()
        
        try:
            is_single = isinstance(text, str)
            texts = [text] if is_single else text
            
            response = self.__class__._client.embeddings.create(
                model=self.model_name.split("/")[-1],
                input=texts
            )
            
            embeddings = []
            for item in response.data:
                embedding = np.array(item.embedding, dtype=np.float32)
                
                if normalize:
                    norm = np.linalg.norm(embedding)
                    if norm > 0:
                        embedding = embedding / norm
                
                embeddings.append(embedding)
            
            if is_single:
                return embeddings[0]
            else:
                return np.array(embeddings, dtype=np.float32)
                
        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
            return None

    @property
    def vector_dimension(self):
        """임베딩 벡터의 차원을 반환"""
        return 2560

    @property
    def is_loaded(self):
        """클라이언트가 초기화되었는지 확인"""
        return self.__class__._client is not None

    def cleanup(self):
        """클라이언트 정리"""
        with self.__class__._lock:
            if self.__class__._client is not None:
                self.__class__._client = None
                logger.info("OpenAI client has been released.")

shared_embedding = SharedEmbeddingModel()
