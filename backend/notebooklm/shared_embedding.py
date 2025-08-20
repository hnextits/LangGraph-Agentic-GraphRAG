#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
공유 임베딩 모델 - 텍스트와 이미지 검색에서 같은 임베딩 모델을 공유하여 메모리 절약
더 간단하고 안전한 버전
"""

import os
import sys
import logging
import torch
import torch.nn.functional as F
import numpy as np
from typing import Optional
from transformers import AutoTokenizer, AutoModel

# config.py 파일이 있는 디렉토리를 sys.path에 추가
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config import RAGConfig

# 로깅 설정
logger = logging.getLogger(__name__)

class SharedEmbeddingModel:
    """텍스트와 이미지 검색에서 공유하는 임베딩 모델 싱글톤"""
    
    _instance = None
    _model = None
    _tokenizer = None
    _device = None
    _model_name = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SharedEmbeddingModel, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._model is None:
            self._initialize()
    
    def _initialize(self):
        """모델 초기화"""
        config = RAGConfig()
        self._model_name = config.EMBEDDING_MODEL
        self._device = config.EMBEDDING_DEVICE
        self.dimension = config.VECTOR_DIMENSION
        self.max_length = 32768
        
        logger.info(f"공유 임베딩 모델 초기화: {self._model_name} on {self._device}")
        
        try:
            # 기존 캐시 경로 설정
            cache_dir = "/home/nextits2/.cache/huggingface/hub"
            
            # 토크나이저 로드 (기존 캐시 사용)
            self._tokenizer = AutoTokenizer.from_pretrained(
                self._model_name, 
                trust_remote_code=True, 
                padding_side='left',
                cache_dir=cache_dir
            )
            
            # 모델 로드 - 임베딩 모델은 to_empty() 사용하지 않음
            # 기존 캐시된 모델 사용
            logger.info(f"기존 캐시된 모델 사용: {cache_dir}")
            self._model = AutoModel.from_pretrained(
                self._model_name,
                trust_remote_code=True,
                torch_dtype=torch.float32,  # float16 -> float32로 변경
                cache_dir=cache_dir,
                local_files_only=True  # 로컬 캐시만 사용, 다운로드 방지
                # attn_implementation 기본값 사용 (가능한 경우 flash attention 사용)
            )
            
            # 임베딩 모델은 직접 디바이스 이동 (to_empty() 사용 안함)
            self._model = self._model.to(self._device)
            logger.info(f"임베딩 모델을 {self._device}에 직접 이동했습니다.")
            
            self._model.eval()
            
            logger.info(f"공유 임베딩 모델 로드 완료: {self._model_name}")
            
        except Exception as e:
            logger.error(f"공유 임베딩 모델 로드 실패: {e}")
            raise
    
    def generate_embedding(self, text: str) -> np.ndarray:
        """텍스트에 대한 임베딩 생성"""
        try:
            if self._tokenizer is None or self._model is None:
                logger.error("공유 임베딩 모델이 로드되지 않았습니다.")
                return self._get_random_embedding()
            
            # 토크나이징
            inputs = self._tokenizer(
                text,
                return_tensors="pt",
                padding=False,
                truncation=True,
                max_length=self.max_length - 2
            )
            
            # 디바이스로 이동
            for key in inputs:
                if isinstance(inputs[key], torch.Tensor):
                    inputs[key] = inputs[key].to(self._device)
            
            # 임베딩 생성
            with torch.no_grad():
                outputs = self._model(**inputs)
            
            # 평균 풀링
            token_embeddings = outputs.last_hidden_state[0]
            embedding_tensor = torch.mean(token_embeddings, dim=0)
            
            # 정규화
            normalized_embedding = F.normalize(embedding_tensor, p=2, dim=0)
            
            # float32로 반환하여 임베딩 품질 향상
            return normalized_embedding.cpu().numpy().astype('float32')
            
        except Exception as e:
            logger.error(f"공유 임베딩 생성 중 오류 발생: {e}")
            return self._get_random_embedding()
    
    def _get_random_embedding(self) -> np.ndarray:
        """랜덤 임베딩 생성 (오류 시 폴백)"""
        random_embedding = np.random.randn(self.dimension).astype('float32')
        random_embedding /= np.linalg.norm(random_embedding)
        return random_embedding
    
    def get_device(self) -> str:
        """현재 디바이스 반환"""
        return self._device
    
    def is_loaded(self) -> bool:
        """모델이 로드되었는지 확인"""
        return self._model is not None and self._tokenizer is not None
    
    def get_memory_usage(self) -> dict:
        """GPU 메모리 사용량 반환"""
        if torch.cuda.is_available() and self._device.startswith('cuda'):
            device_id = int(self._device.split(':')[1]) if ':' in self._device else 0
            allocated = torch.cuda.memory_allocated(device_id) / (1024**3)  # GB
            reserved = torch.cuda.memory_reserved(device_id) / (1024**3)   # GB
            return {
                'device': self._device,
                'allocated_gb': allocated,
                'reserved_gb': reserved
            }
        return {'device': self._device, 'allocated_gb': 0, 'reserved_gb': 0}

# 전역 인스턴스
shared_embedding = SharedEmbeddingModel()
