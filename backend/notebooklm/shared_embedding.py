#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import threading
import numpy as np
import logging
import requests
import json

from notebooklm.config import RAGConfig

logger = logging.getLogger(__name__)

from typing import Optional, List


class SharedEmbeddingModel:
    """SGLang /v1/embeddings API를 사용하는 임베딩 모델 클라이언트.
    
    싱글톤 패턴을 유지하며, 모델을 직접 로드하지 않고
    SGLang 서버의 OpenAI 호환 임베딩 API를 호출합니다.
    """
    _instance = None
    _ready = False
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(SharedEmbeddingModel, cls).__new__(cls)
        return cls._instance

    def __init__(self, model_name="Qwen/Qwen3-Embedding-4B"):
        if hasattr(self, "_initialized") and self._initialized:
            return
        config = RAGConfig()
        self.model_name = config.SGLANG_EMBEDDING_MODEL or model_name
        self.endpoint = config.SGLANG_EMBEDDING_ENDPOINT  # e.g. "http://localhost:30001"
        self._api_url = f"{self.endpoint}/v1/embeddings"
        self._timeout = 60  # HTTP 요청 타임아웃 (초)
        self._session = requests.Session()
        self._initialized = True

    def _ensure_server_ready(self):
        """SGLang 임베딩 서버가 응답 가능한지 확인합니다. 미기동 시 자동 기동."""
        from notebooklm.sglang_server_manager import sglang_manager

        # _ready=True여도 실제 health check로 서버 생존 확인
        if self.__class__._ready:
            try:
                resp = self._session.get(f"{self.endpoint}/health", timeout=3)
                if resp.status_code == 200:
                    sglang_manager.touch("embedding")
                    return
            except Exception:
                pass
            # 서버가 죽었으면 _ready 리셋
            self.__class__._ready = False

        with self.__class__._lock:
            if self.__class__._ready:
                sglang_manager.touch("embedding")
                return
            try:
                resp = self._session.get(f"{self.endpoint}/health", timeout=5)
                if resp.status_code == 200:
                    self.__class__._ready = True
                    sglang_manager.touch("embedding")
                    logger.info("SGLang embedding server ready: %s", self.endpoint)
                    return
            except (requests.ConnectionError, requests.Timeout, Exception):
                pass

            # 서버가 응답하지 않으면 sglang_manager로 자동 기동
            # cuda:1 GPU 메모리 경합 방지: 리랭커 서버가 살아있으면 먼저 종료
            if sglang_manager.is_running("reranker"):
                logger.info("임베딩 기동 전 리랭커 서버 종료 (cuda:1 메모리 확보)")
                sglang_manager.shutdown_server("reranker")
                try:
                    from notebooklm.rag_text.text_reranker_improved_2 import ImprovedTextReranker
                    ImprovedTextReranker._ready = False
                except ImportError:
                    pass

            logger.info("SGLang embedding server 미기동 → acquire로 자동 기동 시도")
            try:
                if sglang_manager.acquire("embedding"):
                    sglang_manager.release("embedding")
                    self.__class__._ready = True
            except Exception as e:
                logger.error("SGLang embedding 자동 기동 실패: %s", e)

    def load_model(self):
        """서버 연결 확인 (하위 호환성 유지)."""
        self._ensure_server_ready()

    def generate_embedding(self, text: str, normalize: bool = True) -> Optional[np.ndarray]:
        """SGLang /v1/embeddings API를 호출하여 임베딩을 생성합니다."""
        if not text:
            return None
        self._ensure_server_ready()
        try:
            payload = {
                "model": self.model_name,
                "input": text,
            }
            resp = self._session.post(
                self._api_url,
                json=payload,
                timeout=self._timeout,
            )
            if resp.status_code != 200:
                logger.error(
                    "SGLang embedding API error %d: %s",
                    resp.status_code, resp.text[:500],
                )
                resp.raise_for_status()
            data = resp.json()
            embedding = data["data"][0]["embedding"]
            arr = np.array(embedding, dtype=np.float32)
            if normalize:
                norm = np.linalg.norm(arr)
                if norm > 1e-10:
                    arr = arr / norm
            return arr
        except requests.ConnectionError:
            logger.error("SGLang embedding server connection failed: %s", self._api_url)
            return None
        except Exception as e:
            logger.error("Error generating embedding via SGLang: %s", e)
            return None

    def generate_embeddings_batch(self, texts: List[str], normalize: bool = True) -> Optional[List[np.ndarray]]:
        """배치 임베딩 생성. SGLang은 input에 리스트를 지원합니다."""
        if not texts:
            return None
        self._ensure_server_ready()
        try:
            payload = {
                "model": self.model_name,
                "input": texts,
            }
            resp = self._session.post(
                self._api_url,
                json=payload,
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            results = []
            for item in data["data"]:
                arr = np.array(item["embedding"], dtype=np.float32)
                if normalize:
                    norm = np.linalg.norm(arr)
                    if norm > 1e-10:
                        arr = arr / norm
                results.append(arr)
            return results
        except Exception as e:
            logger.error("Error generating batch embeddings via SGLang: %s", e)
            return None

    @property
    def vector_dimension(self):
        config = RAGConfig()
        return config.VECTOR_DIMENSION

    @property
    def is_loaded(self):
        """SGLang 서버가 응답 가능한지 확인합니다."""
        return self.__class__._ready

    def cleanup(self):
        """HTTP 세션을 정리합니다."""
        with self.__class__._lock:
            self.__class__._ready = False
            try:
                self._session.close()
            except Exception:
                pass
            logger.info("SGLang embedding client resources have been released.")

# 전역 인스턴스
shared_embedding = SharedEmbeddingModel()
