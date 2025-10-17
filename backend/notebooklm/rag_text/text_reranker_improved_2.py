#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import sys
import logging
import torch
import threading
from typing import List, Dict, Any, Optional
import time
# *** 변경된 부분 시작 ***
# 올바른 AutoModel 클래스를 임포트합니다.
from transformers import AutoTokenizer, AutoModelForSequenceClassification
# *** 변경된 부분 끝 ***

# config.py 파일이 있는 디렉토리를 sys.path에 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import RAGConfig

# 로깅 설정
logger = logging.getLogger(__name__)

class ImprovedTextReranker:
    def __init__(
        self,
        model_name: str = None,
        device: str = None,
        max_length: int = 512,
        batch_size: int = 8
    ):
        self.config = RAGConfig()
        
        default_model = "Qwen/Qwen3-Reranker-4B"
        self.model_name = model_name if model_name else getattr(config, 'RERANKER_MODEL_NAME', default_model)
        # 명시적으로 cuda:1에 할당 (생성 모델은 cuda:0에 있음)
        if device:
            self.device = device
        else:
            # 기본값으로 cuda:1 사용 (사용 가능한 경우)
            if torch.cuda.is_available() and torch.cuda.device_count() > 1:
                self.device = "cuda:1"  # 리랭커는 두 번째 GPU에 할당
            else:
                self.device = config.RERANKER_DEVICE if torch.cuda.is_available() else "cpu"
        
        self.max_length = max_length
        self.batch_size = 8  # 배치 크기 증가 (1 -> 8, 속도 향상)
        
        self.tokenizer = None
        self.model = None
        self.torch_dtype = torch.float16  # 일관된 dtype 사용
        
        self.stats = {
            'total_queries': 0,
            'total_documents': 0,
            'avg_processing_time': 0.0
        }
        
        logger.info(f"텍스트 리랭커 초기화 완료: {self.model_name} (device: {self.device})")
        logger.info(f"성능 설정 - 배치크기: {self.batch_size}, 최대길이: {self.max_length}")

    def _load_model(self) -> bool:
        """모델과 토크나이저를 안정적으로 로드합니다."""
        if self.tokenizer is not None and self.model is not None:
            return True
        
        try:
            logger.info(f"리랭커 모델 로드 중: {self.model_name} on device: {self.device}")
            
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.model_name, 
                trust_remote_code=True, 
                cache_dir=self.config.CACHE_DIR, 
                local_files_only=True
            )
            
            # 패딩 토큰 설정 (배치 처리를 위해 필수)
            if self.tokenizer.pad_token is None:
                self.tokenizer.pad_token = self.tokenizer.eos_token
                logger.info(f"패딩 토큰을 EOS 토큰으로 설정: {self.tokenizer.eos_token}")
            
            # pad_token_id도 명시적으로 설정
            if self.tokenizer.pad_token_id is None:
                self.tokenizer.pad_token_id = self.tokenizer.eos_token_id
                logger.info(f"패딩 토큰 ID 설정: {self.tokenizer.pad_token_id}")
            
            # 비결정적 추론을 위한 시드 설정
            torch.manual_seed(42)
            torch.cuda.manual_seed_all(42)
            
            # 일관된 dtype 설정 (float16 사용)
            self.torch_dtype = torch.float16
            logger.info(f"리랭커 모델 dtype 설정: {self.torch_dtype}")
            
            # device_map 대신 직접 로드 후 이동
            self.model = AutoModelForSequenceClassification.from_pretrained(
                self.model_name,
                trust_remote_code=True,
                torch_dtype=self.torch_dtype,
                cache_dir=self.config.CACHE_DIR,
                local_files_only=True
            ).to(self.device)
            logger.info(f"리랭커 모델을 {self.device}에 로드했습니다.")
            
            # 모델 설정에도 패딩 토큰 ID 설정
            if hasattr(self.model, 'config') and self.model.config.pad_token_id is None:
                self.model.config.pad_token_id = self.tokenizer.pad_token_id
                logger.info(f"모델 config에 pad_token_id 설정: {self.model.config.pad_token_id}")
            
            # 모델 파라미터의 dtype 확인 및 로깅
            param_dtypes = set(p.dtype for p in self.model.parameters())
            logger.info(f"모델 파라미터 dtype: {param_dtypes}")
            
            self.model.eval()
            
            logger.info(f"리랭커 모델이 {self.device}에 성공적으로 로드되었습니다.")
            return True
            
        except Exception as e:
            logger.error(f"리랭커 모델 로드 실패: {str(e)}")
            self.tokenizer = None
            self.model = None
            return False

    @torch.no_grad()
    def compute_similarity_batch(self, query: str, passages: List[str], cancellation_event: Optional[threading.Event] = None) -> List[float]:
        """배치로 여러 문서의 유사도를 계산합니다."""
        if not self._load_model():
            logger.error("모델 로드 실패")
            return [0.0] * len(passages)
        
        all_scores = []
        
        for i in range(0, len(passages), self.batch_size):
            # 배치 처리 전 취소 확인
            if cancellation_event and cancellation_event.is_set():
                raise InterruptedError("Reranking operation cancelled during batch processing")

            batch_passages = passages[i:i + self.batch_size]
            
            # 토큰화는 한 번만 수행
            inputs = self.tokenizer(
                [query] * len(batch_passages),
                batch_passages,
                padding=True,
                truncation=True,
                max_length=self.max_length,
                return_tensors="pt"
            )
            
            
            # 입력 텐서를 디바이스로 이동 및 필요한 경우 dtype 변환
            for k, v in inputs.items():
                if k in ['input_ids', 'token_type_ids']:
                    # 정수형 텐서는 그대로 디바이스로 이동
                    inputs[k] = v.to(self.device)
                elif k == 'attention_mask':
                    # attention_mask는 정수형(int64 또는 bool)으로 유지해야 함
                    # float16으로 변환하면 모델이 오작동할 수 있음
                    inputs[k] = v.to(device=self.device)  # dtype 변환 제거
                else:
                    # 기타 텐서는 디바이스로 이동
                    inputs[k] = v.to(self.device)
            # *** 수정된 부분 끝 ***
            
            try:
                with torch.amp.autocast(device_type='cuda' if self.device.startswith("cuda") else 'cpu'):
                    # *** 수정된 부분 시작 ***
                    # torch.cuda.amp.autocast 대신 torch.amp.autocast 사용
                    # device_type 파라미터 추가
                    outputs = self.model(**inputs, return_dict=True)
                    
                    # Qwen3-Reranker 점수 올바른 처리 방법
                    # logits는 [batch_size, 2] 형태 - [관련없음, 관련있음]
                    logits = outputs.logits.to(dtype=torch.float32)
                    
                    # 'relevant' 로짓에 가중치(1.2)를 부여하여 점수를 상향 조정하고, 배치 전체에 대해 계산합니다.
                    scores = torch.sigmoid((logits[:, 1] * 1.2 - logits[:, 0]) * 1.0)
                    all_scores.extend(scores.tolist())
                    # *** 수정된 부분 끝 ***
                
            except RuntimeError as e:
                if "expected mat1 and mat2 to have the same dtype" in str(e):
                    logger.warning(f"dtype 불일치 오류 발생: {e}")
                    
                    # *** 수정된 부분 시작 ***
                    # 모든 텐서를 float32로 강제 변환하여 재시도
                    logger.info(f"dtype 불일치 오류 발생, 모든 텐서를 float32로 강제 변환")
                    float_inputs = {}
                    for k, v in inputs.items():
                        if k in ['input_ids', 'token_type_ids']:
                            # 정수형 텐서는 그대로 유지
                            float_inputs[k] = v
                        else:
                            # 나머지 텐서는 float32로 강제 변환
                            float_inputs[k] = v.to(dtype=torch.float32)
                        logger.info(f"변환 후 {k} dtype: {float_inputs[k].dtype}")
                    
                    # float32로 변환된 입력으로 모델 실행 (autocast 비활성화)
                    with torch.amp.autocast(device_type='cuda' if self.device.startswith("cuda") else 'cpu', enabled=False):
                        outputs = self.model(**float_inputs, return_dict=True)
                    
                    # 오류 복구 시에도 올바른 점수 처리
                    logits = outputs.logits.to(dtype=torch.float32)
                    
                    # 오류 복구 시에도 동일한 가중치 로직을 적용합니다.
                    scores = torch.sigmoid((logits[:, 1] * 1.2 - logits[:, 0]) * 1.0)
                    all_scores.extend(scores.tolist())
                    logger.info("float32 강제 변환으로 성공적으로 처리됨")
                else:
                    raise
                # *** 수정된 부분 끝 ***
                
            except Exception as e:
                logger.error(f"배치 처리 오류 (batch {i//self.batch_size}): {e}")
                all_scores.extend([0.0] * len(batch_passages))
        
        return all_scores
    
    def rerank(
        self,
        query: str,
        results: List[Dict[str, Any]],
        top_k: int = None,
        min_score: float = 0.0, # Qwen 리랭커는 점수 범위가 다르므로 임계값 조정이 필요할 수 있습니다.
        cancellation_event: Optional[threading.Event] = None
    ) -> List[Dict[str, Any]]:
        if not results:
            logger.info("리랭킹할 결과가 없습니다.")
            return []
        
        start_time = time.time()
        logger.info(f"리랭킹 시작: {len(results)}개 문서, 모델 dtype: {self.torch_dtype}")
        
        self.stats['total_queries'] += 1
        self.stats['total_documents'] += len(results)
        
        passages = []
        for result in results:
            text = result.get('text', result.get('content', ''))
            passages.append(text)
        
        # 취소 확인
        if cancellation_event and cancellation_event.is_set():
            raise InterruptedError("Operation cancelled during text reranking")

        # compute_similarity_batch 메서드 호출 - 이미 dtype 일관성 처리가 적용됨
        try:
            scores = self.compute_similarity_batch(query, passages, cancellation_event=cancellation_event)
            logger.info(f"리랭킹 점수 계산 완료: {len(scores)}개 점수")
        except Exception as e:
            logger.error(f"리랭킹 점수 계산 중 오류 발생: {e}")
            # 오류 발생 시 원래 점수 유지
            scores = [result.get('score', 0.0) for result in results]
            logger.warning("오류로 인해 원래 점수를 유지합니다.")
        
        # 점수 업데이트 및 float32로 명시적 변환하여 일관성 유지
        for result, score in zip(results, scores):
            result['original_score'] = result.get('score', 0.0)
            # 점수를 명시적으로 Python float로 변환하여 dtype 문제 방지
            # score가 리스트인 경우 첫 번째 요소 사용
            if isinstance(score, (list, tuple)):
                score_value = float(score[0]) if len(score) > 0 else 0.0
            else:
                score_value = float(score)
            result['rerank_score'] = score_value
            result['score'] = score_value
        
        results.sort(key=lambda x: x.get('rerank_score', -float('inf')), reverse=True)
        
        # 필터링 로직은 그대로 유지하되, min_score의 의미가 달라질 수 있음을 인지해야 합니다.
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
            f"상위 점수: {scores_info}, "
            f"모델 dtype: {self.torch_dtype}"
        )
        
        return filtered_results

    def cleanup(self):
        """메모리를 정리합니다."""
        if self.model:
            del self.model
            del self.tokenizer
            self.model = None
            self.tokenizer = None
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        logger.info("리랭커 메모리 정리 완료")