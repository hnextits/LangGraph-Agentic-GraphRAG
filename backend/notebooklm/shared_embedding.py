#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import threading
import numpy as np
import logging
import requests
import json

# 현재 스크립트의 경로를 sys.path에 추가
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config import RAGConfig

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

from sentence_transformers import SentenceTransformer
import torch
from typing import Optional

class SharedEmbeddingModel:
    _instance = None
    _model = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(SharedEmbeddingModel, cls).__new__(cls)
        return cls._instance

    def __init__(self, model_name="Qwen/Qwen3-Embedding-4B"):
        if hasattr(self, "_initialized") and self._initialized:
            return
        self.model_name = model_name
        config = RAGConfig()
        self.device = config.EMBEDDING_DEVICE if torch.cuda.is_available() else "cpu"
        self._initialized = True

    def _ensure_model_loaded(self):
        if self.__class__._model is not None:
            return
        with self.__class__._lock:
            if self.__class__._model is not None:
                return
            logger.info(
                "Loading shared SentenceTransformer model: %s on device: %s",
                self.model_name,
                self.device,
            )
            try:
                self.__class__._model = SentenceTransformer(self.model_name, device=self.device)
                logger.info("Shared embedding model loaded successfully.")
            except Exception as e:
                logger.error(f"Failed to load shared embedding model: {e}")
                raise

    def generate_embedding(self, text: str, normalize: bool = True) -> Optional[np.ndarray]:
        if not text:
            return None
        self._ensure_model_loaded()
        try:
            embedding = self.__class__._model.encode(text, normalize_embeddings=normalize)
            return np.array(embedding, dtype=np.float32)
        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
            return None

    @property
    def vector_dimension(self):
        if self.__class__._model:
            return self.__class__._model.get_sentence_embedding_dimension()
        return None

    @property
    def is_loaded(self):
        """모델이 성공적으로 로드되었는지 확인합니다."""
        return self.__class__._model is not None

    def cleanup(self):
        """로딩된 SentenceTransformer를 언로드합니다."""
        with self.__class__._lock:
            if self.__class__._model is not None:
                try:
                    del self.__class__._model
                except Exception:
                    pass
                self.__class__._model = None
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                logger.info("Shared embedding model resources have been released.")

# 전역 인스턴스
shared_embedding = SharedEmbeddingModel()
