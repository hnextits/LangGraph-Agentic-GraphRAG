#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
텍스트 리랭커 - Hugging Face의 Qwen/Qwen3-Reranker-8B 모델을 사용하여 검색 결과를 재정렬합니다.
"""

import os
import sys
import logging
import torch
from typing import List, Dict, Any
import math

# transformers는 필요한 시점에 함수 내에서 import합니다.
from transformers import AutoTokenizer, AutoModelForSequenceClassification

# config.py 파일이 있는 디렉토리를 sys.path에 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import RAGConfig

# 로깅 설정
logger = logging.getLogger(__name__)

class TextReranker:
    def __init__(self, model_name: str = None, device: str = None):
        """텍스트 리랭커를 초기화합니다."""
        config = RAGConfig()
        self.model_name = model_name if model_name else config.RERANKER_MODEL_NAME
        # GPU 분산 배치 설정 사용 - 리랭커 전용 GPU
        if device:
            self.device = device
        else:
            self.device = config.RERANKER_DEVICE if torch.cuda.is_available() else "cpu"
        
        logger.info(f"리랭커 모델이 {self.device}에 로드됩니다.")
        
        self.tokenizer = None
        self.model = None
        self.torch_dtype = None  # 모델 로드 시 설정됨
        
        logger.info(f"텍스트 리랭커 초기화 완료: {self.model_name} (device: {self.device})")
        logger.info(f"성능 설정 - 최대길이: 8192")
        
    def _load_model(self):
        """모델과 토크나이저를 로드합니다."""
        if self.tokenizer is not None and self.model is not None:
            return True
            
        try:
            logger.info(f"리랭커 모델 로드 중: {self.model_name}")
            
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.model_name, 
                trust_remote_code=True
            )
            
            # *** dtype 일관성을 위한 수정 시작 ***
            # 명시적으로 dtype 저장 (나중에 일관성 확인에 사용)
            self.torch_dtype = torch.float16 if self.device.startswith("cuda") else torch.float32
            logger.info(f"리랭커 모델 dtype 설정: {self.torch_dtype}")
            
            # to_empty() 메서드를 사용하여 메타 텐서 오류 방지 및 명시적 디바이스 할당
            self.model = AutoModelForSequenceClassification.from_pretrained(
                self.model_name,
                trust_remote_code=True,
                torch_dtype=self.torch_dtype,
                device_map=None,  # 자동 매핑 비활성화
                # attn_implementation="eager"  # Flash Attention 사용을 위해 주석 처리
            )
            
            # 메타 텐서 오류 방지를 위한 안전한 디바이스 이동
            try:
                # 메타 텐서 오류 해결을 위해 to_empty() 메서드 사용 강제
                self.model = self.model.to_empty(device=self.device)
                logger.info(f"to_empty() 메서드로 모델을 {self.device}에 안전하게 이동했습니다.")
            except Exception as e:
                # 오류 발생 시 상세 로깅 후 기존 방식 시도
                logger.warning(f"to_empty() 메서드 사용 실패: {str(e)}")
                try:
                    self.model = self.model.to(self.device)
                    logger.info(f"기존 방식으로 모델을 {self.device}에 이동했습니다.")
                except Exception as e2:
                    logger.error(f"모델 디바이스 이동 실패: {str(e2)}")
                    raise e2
            
            # 모델 파라미터의 dtype 확인 및 로깅
            param_dtypes = set(p.dtype for p in self.model.parameters())
            logger.info(f"모델 파라미터 dtype: {param_dtypes}")
            # *** dtype 일관성을 위한 수정 끝 ***
            
            self.model.eval()
            logger.info("리랭커 모델 로드 완료")
            return True
        except Exception as e:
            logger.error(f"리랭커 모델 로드 실패: {e}")
            self.tokenizer = None
            self.model = None
            return False
        
    def compute_similarity(self, query: str, passage: str) -> float:
        """쿼리와 문서 간의 유사도 점수를 계산합니다."""
        if not self._load_model():
            logger.error("모델 로드에 실패하여 기본 점수 0.0을 반환합니다.")
            return 0.0

        try:
            inputs = self.tokenizer(
                query,
                passage,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=8192 # Qwen3-Reranker-8B는 더 긴 컨텍스트를 지원합니다.
            )
            
            # *** dtype 불일치 문제 해결을 위한 수정 시작 ***
            # 모델의 dtype 확인
            model_dtype = next(self.model.parameters()).dtype
            logger.debug(f"모델 dtype: {model_dtype}")
            
            # 각 텐서를 적절한 dtype으로 변환하여 디바이스로 이동
            for k, v in inputs.items():
                logger.debug(f"원본 {k} dtype: {v.dtype}")
                if k in ['input_ids', 'token_type_ids']:
                    # 정수형 텐서는 그대로 디바이스로 이동
                    inputs[k] = v.to(self.device)
                elif k == 'attention_mask':
                    # attention_mask는 모델의 dtype과 일치하도록 변환
                    inputs[k] = v.to(device=self.device, dtype=model_dtype)
                else:
                    # 기타 텐서는 디바이스로 이동
                    inputs[k] = v.to(self.device)
                logger.debug(f"변환 후 {k} dtype: {inputs[k].dtype}")
            # *** dtype 불일치 문제 해결을 위한 수정 끝 ***
            
            try:
                with torch.no_grad():
                    # torch.amp.autocast 사용으로 mixed precision 지원
                    with torch.amp.autocast(device_type='cuda' if self.device.startswith("cuda") else 'cpu'):
                        outputs = self.model(**inputs)
                    
                    # 모델 출력(logits)은 [batch_size, 2] 형태입니다.
                    # 두 클래스(관련 없음[0], 관련 있음[1]) 간의 점수 차이를 계산
                    # 명시적으로 float32로 변환하여 dtype 불일치 방지
                    logits = outputs.logits.to(dtype=torch.float32)
                    neg_score = logits[0, 0].item()  # 관련 없음 점수
                    pos_score = logits[0, 1].item()  # 관련 있음 점수
                    score_diff = pos_score - neg_score  # 점수 차이
                    
                    # 디버깅을 위해 원시 점수 로깅
                    logger.debug(f"Raw scores - Positive: {pos_score:.4f}, Negative: {neg_score:.4f}, Diff: {score_diff:.4f}")
                    
                    # 점수 차이를 그대로 사용 (정규화 없이)
                    score = score_diff
                
                # 원본 점수 그대로 반환 (시그모이드 정규화 제거)
                return score
                
            except RuntimeError as e:
                if "expected mat1 and mat2 to have the same dtype" in str(e):
                    logger.warning(f"dtype 불일치 오류 발생, 강제 float32 변환 시도: {e}")
                    
                    # 모든 텐서를 float32로 강제 변환하여 재시도
                    float_inputs = {}
                    for k, v in inputs.items():
                        if k in ['input_ids', 'token_type_ids']:
                            # 정수형 텐서는 그대로 유지
                            float_inputs[k] = v
                        else:
                            # 나머지 텐서는 float32로 강제 변환
                            float_inputs[k] = v.to(dtype=torch.float32)
                        logger.debug(f"강제 변환 후 {k} dtype: {float_inputs[k].dtype}")
                    
                    # float32로 변환된 입력으로 모델 실행 (autocast 비활성화)
                    with torch.no_grad():
                        with torch.amp.autocast(device_type='cuda' if self.device.startswith("cuda") else 'cpu', enabled=False):
                            outputs = self.model(**float_inputs)
                        
                        logits = outputs.logits.to(dtype=torch.float32)
                        neg_score = logits[0, 0].item()
                        pos_score = logits[0, 1].item()
                        score_diff = pos_score - neg_score
                        
                        # 정규화 없이 점수 차이를 그대로 사용
                        score = score_diff
                        
                        logger.info("float32 강제 변환으로 성공적으로 처리됨")
                        return score
                else:
                    raise
            
        except Exception as e:
            # 에러 로그에 어떤 쿼리와 문서에서 문제가 발생했는지 추가하면 디버깅에 용이합니다.
            logger.error(f"유사도 계산 중 오류 발생: {e}\nQuery: {query[:50]}...\nPassage: {passage[:50]}...")
            return 0.0  # 오류 발생 시 0점 반환

    def rerank(self, query: str, results: List[Dict[str, Any]], top_k: int = None, min_score: float = 0.0, use_batch: bool = True) -> List[Dict[str, Any]]:
        """검색 결과를 재정렬합니다.
        
        Args:
            query: 검색 쿼리
            results: 검색 결과 목록
            top_k: 반환할 최대 결과 수
            min_score: 최소 유사도 점수 임계값 (0~1 사이)
            use_batch: 배치 처리 사용 여부 (이 구현에서는 사용되지 않지만 호환성을 위해 포함)
        
        Returns:
            재정렬된 검색 결과 목록
        """
        if not results:
            return []
        
        if not self._load_model():
            logger.warning(f"리랭커 모델을 로드할 수 없어 원본 결과를 반환합니다.")
            return results[:top_k] if top_k else results
        
        # 결과마다 유사도 점수 계산
        for result in results:
            text = result.get('text', '')
            if not text:
                result['score'] = 0.0  # 텍스트가 없으면 0점 처리
                continue

            # 원본 점수 보존 후 리랭커 점수로 업데이트
            result['original_score'] = result.get('score', 0.0)
            result['score'] = self.compute_similarity(query, text)

        # 새로운 점수에 따라 내림차순 정렬
        results.sort(key=lambda x: x.get('score', 0.0), reverse=True)
        
        # 최소 점수 임계값을 적용하여 관련성이 낮은 문서 필터링
        filtered_results = [r for r in results if r.get('score', 0.0) >= min_score]
        
        # 점수 분포 로깅 (디버깅용)
        scores = [r.get('score', 0.0) for r in results]
        if scores:
            logger.debug(f"Score distribution - Min: {min(scores):.4f}, Max: {max(scores):.4f}, Avg: {sum(scores)/len(scores):.4f}")
            logger.debug(f"Filtered out {len(results) - len(filtered_results)} results below threshold {min_score}")
        
        # 모든 결과가 필터링되었지만 결과가 있으면 최소한 최고 점수 결과는 반환
        if not filtered_results and results:
            filtered_results = [results[0]]
            logger.warning(f"All results were below threshold {min_score}. Returning top result with score {results[0].get('score', 0.0):.4f}")
        
        # top_k 적용
        if top_k and len(filtered_results) > top_k:
            filtered_results = filtered_results[:top_k]
        
        logger.info(f"쿼리 '{query}'에 대한 재정렬 완료, 결과 수: {len(filtered_results)}")
        return filtered_results