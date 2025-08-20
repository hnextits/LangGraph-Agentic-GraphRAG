"""
RAG 시스템을 위한 리랭커 모듈
Qwen3-Reranker-8B 모델을 사용하여 검색 결과를 재정렬합니다.
"""

import os
import torch
import logging
import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from transformers import AutoModelForSequenceClassification, AutoTokenizer
from tqdm import tqdm
from rag_config import RAGConfig  # RAGConfig 임포트 추가

# 로깅 설정 - 기본 레벨은 WARNING으로 설정
# 이미 다른 모듈에서 basicConfig가 호출되었을 수 있으므로 여기서는 설정하지 않음
logger = logging.getLogger(__name__)
logger.setLevel(logging.WARNING)  # 현재 모듈은 WARNING 레벨로 설정

class RAGReranker:
    """
    RAG 시스템을 위한 리랭커 클래스
    Qwen3-Reranker-8B 모델을 사용하여 검색 결과를 재정렬합니다.
    """
    
    def __init__(self, 
                 model_name=None, 
                 device=None,
                 batch_size=None,
                 cache_dir=None,
                 use_fp16=None,
                 use_device_map=False):
        """
        리랭커 초기화
        
        Args:
            model_name: 사용할 리랭커 모델 이름 (None이면 RAGConfig에서 가져옴)
            device: 사용할 디바이스 (None이면 자동 감지)
            batch_size: 배치 처리 크기 (None이면 RAGConfig에서 가져옴)
            cache_dir: 모델 캐시 디렉토리 (None이면 기본값 사용)
            use_fp16: float16 정밀도 사용 여부 (None이면 RAGConfig에서 가져옴)
            use_device_map: 자동 디바이스 맵핑 사용 여부 (여러 GPU에 모델 분산)
        """
        # RAGConfig 인스턴스 생성
        self.config = RAGConfig()
        
        # 설정값 초기화
        self.model_name = model_name if model_name is not None else self.config.RERANKER_MODEL_NAME
        self.device = device if device is not None else self.config.DEVICE
        self.batch_size = batch_size if batch_size is not None else self.config.RERANKER_BATCH_SIZE
        self.cache_dir = cache_dir
        self.use_fp16 = use_fp16 if use_fp16 is not None else (self.config.RERANKER_USE_FP16 and self.device == "cuda")
        self.use_device_map = use_device_map
        
        # 모델 및 토크나이저 로드
        self._load_model()
        
        logger.debug(f"RAGReranker 초기화 완료: 모델={self.model_name}, 디바이스={self.device}")
    
    def _load_model(self):
        """리랭커 모델 로드"""
        try:
            # 모델 및 토크나이저 로드
            logger.info(f"리랭커 모델 로드 시작: {self.model_name}")
            
            # 모델 로드 방식 선택
            if self.use_device_map:
                # 자동 디바이스 맵핑 사용 (여러 GPU에 분산 가능)
                self.model = AutoModelForSequenceClassification.from_pretrained(
                    self.model_name,
                    device_map="auto",
                    torch_dtype=torch.float16 if self.use_fp16 else None
                )
                logger.info("자동 디바이스 맵핑으로 모델 로드 완료")
            else:
                # 일반 로드 후 나중에 디바이스로 이동
                self.model = AutoModelForSequenceClassification.from_pretrained(
                    self.model_name
                )
                logger.info(f"모델 로드 완료, 디바이스: {self.device}")
            
            # 토크나이저 로드
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            
            # 패딩 토큰 설정 (중요: 모델 로드 직후에 설정)
            if self.tokenizer.pad_token is None:
                if self.tokenizer.eos_token is not None:
                    self.tokenizer.pad_token = self.tokenizer.eos_token
                    logger.info("PAD 토큰이 없어 EOS 토큰을 PAD 토큰으로 설정했습니다.")
                elif self.tokenizer.sep_token is not None:
                    self.tokenizer.pad_token = self.tokenizer.sep_token
                    logger.info("PAD 토큰이 없어 SEP 토큰을 PAD 토큰으로 설정했습니다.")
                elif self.tokenizer.cls_token is not None:
                    self.tokenizer.pad_token = self.tokenizer.cls_token
                    logger.info("PAD 토큰이 없어 CLS 토큰을 PAD 토큰으로 설정했습니다.")
                else:
                    # 마지막 수단으로 특별한 토큰 추가
                    self.tokenizer.add_special_tokens({'pad_token': '[PAD]'})
                    logger.info("PAD 토큰이 없어 새로운 [PAD] 토큰을 추가했습니다.")
                    # 모델의 임베딩 레이어 크기 조정 필요
                    self.model.resize_token_embeddings(len(self.tokenizer))
            
            # 모델 평가 모드로 설정
            self.model.eval()
            
            logger.info("리랭커 모델 및 토크나이저 로드 완료")
            return True
        except Exception as e:
            logger.error(f"모델 로드 중 오류 발생: {str(e)}")
            return False
    
    def compute_scores(self, query: str, passages: List[str]) -> List[float]:
        """
        쿼리와 문서 목록 간의 관련성 점수 계산
        
        Args:
            query: 쿼리 문자열
            passages: 문서 텍스트 목록
            
        Returns:
            각 문서의 관련성 점수 목록
        """
        # 모델을 GPU로 로드
        self.load_model_to_device()
        
        # 빈 문서 목록 처리
        if not passages:
            return []
        
        all_scores = []
        
        try:
            # 현재 모델의 디바이스 확인
            device = next(self.model.parameters()).device
            
            # 각 문서를 개별적으로 처리 (배치 처리 없음)
            for passage in passages:
                # 토큰화 및 인코딩
                features = self.tokenizer(
                    query,
                    passage,
                    padding=False,
                    truncation=True,
                    return_tensors="pt",
                    max_length=512
                )
                
                # 모든 텐서를 모델과 동일한 디바이스로 이동
                features = {k: v.to(device) for k, v in features.items()}
                
                # 추론 모드로 전환
                with torch.no_grad():
                    outputs = self.model(**features)
                    
                    # 모델 출력 형식에 따라 점수 추출
                    if hasattr(outputs, 'logits'):
                        logits = outputs.logits
                        
                        # 텐서 차원 확인 및 처리
                        if logits.numel() == 1:  # 단일 요소인 경우
                            score = logits.item()
                        else:  # 여러 요소가 있는 경우 (예: [batch_size, num_classes])
                            # 첫 번째 클래스의 점수 또는 평균 점수 사용
                            score = logits.mean().item()
                            logger.debug(f"다중 요소 로짓 발견: 형태 {logits.shape}, 평균값 사용")
                    else:
                        # 다른 형태의 출력인 경우 (예: 일부 모델은 'scores'를 반환)
                        if hasattr(outputs, 'scores'):
                            score = outputs.scores.mean().item()
                        else:
                            # 마지막 수단으로 첫 번째 출력 값 사용
                            first_output = list(outputs.values())[0]
                            score = first_output.mean().item()
                            logger.warning(f"알 수 없는 출력 형식: {type(outputs)}, 첫 번째 값 사용")
                    
                all_scores.append(float(score))
                
            return all_scores
            
        except Exception as e:
            logger.error(f"점수 계산 중 오류 발생: {str(e)}")
            # 오류 발생 시 기본값 반환
            return [0.0] * len(passages)
    
    def rerank(self, query: str, search_results: List[Dict[str, Any]], top_k: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        검색 결과를 재정렬
        
        Args:
            query: 검색 쿼리
            search_results: 검색 결과 목록 (딕셔너리 형태)
            top_k: 반환할 최대 결과 수 (None이면 모든 결과 반환)
            
        Returns:
            재정렬된 검색 결과 목록
        """
        # 결과가 1개 이하면 재정렬 불필요
        if len(search_results) <= 1:
            return search_results
        
        # 텍스트 추출
        passages = []
        for result in search_results:
            if "text" in result and result["text"]:
                passages.append(result["text"])
            elif "title" in result and result["title"]:
                passages.append(result["title"])
            else:
                passages.append("")
        
        # 관련성 점수 계산
        scores = self.compute_scores(query, passages)
        
        # 원본 검색 결과에 리랭킹 점수 추가
        for i, (result, score) in enumerate(zip(search_results, scores)):
            # 원본 유사도 점수 백업
            if "similarity" in result:
                result["original_similarity"] = result["similarity"]
            
            # 리랭킹 점수로 유사도 업데이트
            result["similarity"] = float(score)
            result["rerank_score"] = float(score)
        
        # 점수에 따라 결과 정렬
        reranked_results = sorted(search_results, key=lambda x: x.get("rerank_score", 0), reverse=True)
        
        # top_k 결과만 반환
        if top_k is not None and top_k > 0:
            reranked_results = reranked_results[:top_k]
        
        return reranked_results
    
    def rerank_with_hybrid_score(self, query: str, search_results: List[Dict[str, Any]], 
                                alpha: float = 0.5, top_k: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        검색 결과를 재정렬 (원본 유사도와 리랭킹 점수를 결합)
        
        Args:
            query: 검색 쿼리
            search_results: 검색 결과 목록 (딕셔너리 형태)
            alpha: 리랭킹 점수의 가중치 (0~1 사이 값, 1이면 리랭킹 점수만 사용)
            top_k: 반환할 최대 결과 수 (None이면 모든 결과 반환)
            
        Returns:
            재정렬된 검색 결과 목록
        """
        # 결과가 1개 이하면 재정렬 불필요
        if len(search_results) <= 1:
            return search_results
        
        # 텍스트 추출
        passages = []
        for result in search_results:
            if "text" in result and result["text"]:
                passages.append(result["text"])
            elif "title" in result and result["title"]:
                passages.append(result["title"])
            else:
                passages.append("")
        
        # 관련성 점수 계산
        try:
            scores = self.compute_scores(query, passages)
            
            # 점수가 리스트가 아닌 경우 처리
            if not isinstance(scores, list):
                logger.warning(f"점수가 리스트가 아닙니다: {type(scores)}")
                scores = [float(scores)] if len(passages) == 1 else [0.0] * len(passages)
            
            # 점수 정규화를 위한 최대/최소값
            if scores:
                max_rerank_score = max(scores)
                min_rerank_score = min(scores)
            else:
                max_rerank_score = 1.0
                min_rerank_score = 0.0
            
            # 원본 유사도 점수 정규화를 위한 최대/최소값
            original_scores = [float(result.get("similarity", 0)) for result in search_results]
            if original_scores:
                max_original_score = max(original_scores)
                min_original_score = min(original_scores)
            else:
                max_original_score = 1.0
                min_original_score = 0.0
        except Exception as e:
            logger.error(f"점수 계산 및 정규화 중 오류 발생: {str(e)}")
            # 오류 발생 시 기본값 사용
            scores = [0.5] * len(passages)
            max_rerank_score, min_rerank_score = 1.0, 0.0
            max_original_score, min_original_score = 1.0, 0.0
        
        # 원본 검색 결과에 리랭킹 점수 추가 및 하이브리드 점수 계산
        for i, (result, score) in enumerate(zip(search_results, scores)):
            # 원본 유사도 점수 백업
            if "similarity" in result:
                result["original_similarity"] = result["similarity"]
                
                # 원본 점수 정규화 (0~1 범위로)
                if max_original_score > min_original_score:
                    normalized_original = (result["original_similarity"] - min_original_score) / (max_original_score - min_original_score)
                else:
                    normalized_original = 0.5
            else:
                result["original_similarity"] = 0.0
                normalized_original = 0.0
            
            # 리랭킹 점수 추가
            result["rerank_score"] = float(score)
            
            # 리랭킹 점수 정규화 (0~1 범위로)
            if max_rerank_score > min_rerank_score:
                normalized_rerank = (score - min_rerank_score) / (max_rerank_score - min_rerank_score)
            else:
                normalized_rerank = 0.5
            
            # 하이브리드 점수 계산 (가중 평균)
            hybrid_score = alpha * normalized_rerank + (1 - alpha) * normalized_original
            
            # 최종 점수 업데이트
            result["similarity"] = float(hybrid_score)
            result["hybrid_score"] = float(hybrid_score)
        
        # 하이브리드 점수에 따라 결과 정렬
        reranked_results = sorted(search_results, key=lambda x: x.get("hybrid_score", 0), reverse=True)
        
        # top_k 결과만 반환
        if top_k is not None and top_k > 0:
            reranked_results = reranked_results[:top_k]
        
        return reranked_results

    def unload_model(self):
        """
        모델을 GPU 메모리에서 해제 - RAGConfig의 정적 메서드 사용
        사용하지 않을 때 GPU 메모리를 절약하기 위해 호출
        """
        if not hasattr(self, 'model') or self.model is None:
            logger.warning("해제할 모델이 없습니다.")
            return False
            
        # RAGConfig의 정적 메서드를 사용하여 모델 해제 - 인자 없이 호출
        success = RAGConfig.unload_reranker_model()
            
        if success:
            logger.debug("리랭커 모델이 성공적으로 해제되었습니다.")
        else:
            logger.warning("리랭커 모델 해제 실패")
                
        return success

    def load_model_to_device(self):
        """
        모델을 지정된 디바이스로 이동
        모델 사용 전에 호출하여 GPU에 모델을 로드
        """
        if not hasattr(self, 'model') or self.model is None:
            # 모델이 없으면 다시 로드
            logger.info("모델이 없어 새로 로드합니다.")
            self._load_model()
            return True
            
        # device_map="auto"로 로드된 모델은 이미 GPU에 있으므로 이동할 필요 없음
        if self.use_device_map:
            logger.info(f"자동 디바이스 맵핑된 모델은 이미 GPU에 로드되어 있습니다.")
            return True
            
        try:
            # float16 변환 (GPU에서만 적용)
            if self.device == "cuda" and self.use_fp16 and torch.cuda.is_available():
                self.model = self.model.half()
                logger.info(f"모델을 float16으로 변환했습니다.")
                
            # 모델을 지정된 디바이스로 이동
            self.model = self.model.to(self.device)
            logger.info(f"리랭커 모델이 {self.device}로 성공적으로 로드되었습니다.")
            return True
        except Exception as e:
            logger.error(f"모델 로드 중 오류 발생: {str(e)}")
            return False


# 사용 예시
if __name__ == "__main__":
    # 리랭커 초기화
    reranker = RAGReranker(model_name="Qwen/Qwen3-Reranker-8B", batch_size=4, use_fp16=True)
    
    # 테스트 데이터
    query = "인공지능의 윤리적 문제점은 무엇인가?"
    search_results = [
        {
            "id": "doc1",
            "title": "인공지능 윤리",
            "text": "인공지능의 윤리적 문제점으로는 프라이버시 침해, 의사결정의 편향성, 책임 소재의 불명확성 등이 있다.",
            "similarity": 0.85
        },
        {
            "id": "doc2",
            "title": "AI 기술 발전",
            "text": "인공지능 기술은 빠르게 발전하고 있으며, 딥러닝과 강화학습이 주요 기술로 자리잡고 있다.",
            "similarity": 0.75
        },
        {
            "id": "doc3",
            "title": "윤리적 AI 개발",
            "text": "윤리적인 AI 개발을 위해서는 투명성, 공정성, 책임성, 프라이버시 보호 등의 원칙을 준수해야 한다.",
            "similarity": 0.65
        }
    ]
    
    # 기본 리랭킹 수행
    print("\n=== 기본 리랭킹 수행 중... ===")
    reranked_results = reranker.rerank(query, search_results)
    
    # 결과 출력
    print("\n=== 리랭킹 결과 ===")
    for i, result in enumerate(reranked_results):
        print(f"[{i+1}] 제목: {result['title']}")
        print(f"    원본 유사도: {result.get('original_similarity', 0):.4f}")
        print(f"    리랭킹 점수: {result.get('rerank_score', 0):.4f}")
        print(f"    텍스트: {result['text'][:100]}...")
        print()
    
    # 하이브리드 리랭킹 수행 (원본 유사도와 리랭킹 점수 결합)
    print("\n=== 하이브리드 리랭킹 수행 중... ===")
    hybrid_results = reranker.rerank_with_hybrid_score(query, search_results, alpha=0.7)
    
    # 하이브리드 결과 출력
    print("\n=== 하이브리드 리랭킹 결과 ===")
    for i, result in enumerate(hybrid_results):
        print(f"[{i+1}] 제목: {result['title']}")
        print(f"    원본 유사도: {result.get('original_similarity', 0):.4f}")
        print(f"    리랭킹 점수: {result.get('rerank_score', 0):.4f}")
        print(f"    하이브리드 점수: {result.get('hybrid_score', 0):.4f}")
        print(f"    텍스트: {result['text'][:100]}...")
        print()
    
    # GPU 메모리 해제 예시
    print("\n=== GPU 메모리 해제 중... ===")
    reranker.unload_model()
    print("모델이 GPU에서 해제되었습니다. 다른 작업 수행 가능...")
    
    # 나중에 다시 사용할 때 모델 로드
    print("\n=== 모델 다시 로드 중... ===")
    reranker.load_model_to_device()
    print("모델이 다시 GPU에 로드되었습니다. 리랭킹 작업 수행 가능...")
    
    # 다시 리랭킹 수행
    print("\n=== 모델 재로드 후 리랭킹 수행 중... ===")
    reranked_results_2 = reranker.rerank(query, search_results)
    print("리랭킹 완료!")
    
    # 작업 완료 후 다시 GPU 메모리 해제
    reranker.unload_model()
    print("모든 작업 완료 후 GPU 메모리 해제 완료")
