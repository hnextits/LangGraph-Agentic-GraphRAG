#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
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

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(SharedEmbeddingModel, cls).__new__(cls)
        return cls._instance

    def __init__(self, model_name="Qwen/Qwen3-Embedding-4B"):
        if self._model is None:
            self.model_name = model_name
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
            logger.info(f"Loading shared SentenceTransformer model: {self.model_name} on device: {self.device}")
            try:
                self.__class__._model = SentenceTransformer(self.model_name, device=self.device)
                logger.info("Shared embedding model loaded successfully.")
            except Exception as e:
                logger.error(f"Failed to load shared embedding model: {e}")
                raise

    def generate_embedding(self, text: str, normalize: bool = True) -> Optional[np.ndarray]:
        if not text or self._model is None:
            return None
        try:
            embedding = self._model.encode(text, normalize_embeddings=normalize)
            return np.array(embedding, dtype=np.float32)
        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
            return None

    @property
    def vector_dimension(self):
        if self._model:
            return self._model.get_sentence_embedding_dimension()
        return None

    @property
    def is_loaded(self):
        """모델이 성공적으로 로드되었는지 확인합니다."""
        return self._model is not None

# 전역 인스턴스
shared_embedding = SharedEmbeddingModel()
