"""
RAG 시스템을 위한 리랭커 모듈
Qwen3-Reranker-8B 모델을 사용하여 검색 결과를 재정렬합니다.
"""
import os
import json
import logging
import torch
import numpy as np
import sys
import time
import threading
from typing import List, Dict, Any, Optional, Union
from tqdm import tqdm
from transformers import AutoTokenizer, AutoModelForSequenceClassification

# 상위 디렉토리를 모듈 경로에 추가
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from config import RAGConfig

# 로깅 설정 - 기본 레벨은 INFO로 설정 (디버깅을 위해 WARNING에서 변경)
# 이미 다른 모듈에서 basicConfig가 호출되었을 수 있으므로 여기서는 설정하지 않음
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)  # 디버깅을 위해 INFO 레벨로 변경

class RAGReranker:
    def __init__(self, model_name: str = None, ollama_host: str = None):
        """리랭커 초기화"""
        config = RAGConfig()
        self.model_name = model_name if model_name else config.RERANKER_MODEL_NAME
        self.ollama_host = ollama_host if ollama_host else config.OLLAMA_API_URL
        
        # 디바이스 설정 - 메모리에 따라 RERANKER_DEVICE 사용
        self.device = torch.device(config.RERANKER_DEVICE if hasattr(config, 'RERANKER_DEVICE') else ('cuda' if torch.cuda.is_available() else 'cpu'))
        logger.info(f"디바이스 설정: {self.device}")
        
        # 배치 처리 관련 설정 (텍스트 리랭커와 일관성 유지)
        self.batch_size = getattr(config, 'RERANKER_BATCH_SIZE', 8)
        self.max_length = getattr(config, 'RERANKER_MAX_LENGTH', 512)
        
        # 모델 dtype 설정 (텍스트 리랭커와 일관성 유지)
        if hasattr(config, 'RERANKER_DTYPE') and config.RERANKER_DTYPE in ["float16", "bfloat16", "float32"]:
            if config.RERANKER_DTYPE == "float16":
                self.torch_dtype = torch.float16
            elif config.RERANKER_DTYPE == "bfloat16":
                self.torch_dtype = torch.bfloat16
            else:
                self.torch_dtype = torch.float32
        else:
            # 기본값은 float32
            self.torch_dtype = torch.float32
            
        logger.info(f"이미지 리랭커 모델 dtype 설정: {self.torch_dtype}")
        
        try:
            logger.info(f"리랭커 모델 로드 중: {self.model_name}")
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_name, cache_dir=config.CACHE_DIR, local_files_only=True)
            
            # 명시적으로 dtype 지정하여 모델 로드
            self.model = AutoModelForSequenceClassification.from_pretrained(
                self.model_name,
                torch_dtype=self.torch_dtype,
                cache_dir=config.CACHE_DIR,
                local_files_only=True
            )
            
            # 메타 텐서 오류 방지를 위한 안전한 디바이스 이동
            try:
                # to_empty() 메서드 사용 시도 (최신 PyTorch 버전에서 지원)
                if hasattr(self.model, 'to_empty'):
                    self.model = self.model.to_empty(device=self.device)
                    logger.info(f"to_empty() 메서드로 모델을 {self.device}에 안전하게 이동했습니다.")
                else:
                    self.model = self.model.to(self.device)
                    logger.info(f"기존 방식으로 모델을 {self.device}에 이동했습니다.")
            except Exception as e:
                logger.warning(f"모델 디바이스 이동 중 오류 발생: {str(e)}")
                self.model = self.model.to(self.device)
            
            # 모델 파라미터의 dtype 확인 및 로깅
            param_dtypes = set(p.dtype for p in self.model.parameters())
            logger.info(f"모델 파라미터 dtype: {param_dtypes}")
            
            self.model.eval()
            logger.info(f"리랭커 모델 로드 완료: {self.model_name}")
        except Exception as e:
            logger.error(f"리랭커 모델 로드 실패: {str(e)}")
            self.tokenizer = None
            self.model = None
            
    def compute_similarity(self, query: str, item: Union[Dict[str, Any], str]) -> float:
        """
        쿼리와 아이템 간의 유사도를 계산합니다.
        실제 임베딩에 사용되는 필드들(text, title, page_num, file_path)만 활용합니다.
        """
        try:
            if isinstance(item, str):
                # 문자열인 경우 그대로 사용
                full_text = item
                title = ''
                page_num = ''
                file_path = ''
            else:
                # 실제 임베딩에 사용되는 필드들만 추출
                text = item.get('text', '')
                title = item.get('title', '')
                page_num = item.get('page_num', '')
                file_path = item.get('file_path', '') or item.get('image_path', '')
                
                # description 필드도 활용 (있는 경우)
                description = item.get('description', '')
                
                # 텍스트 우선순위: text > description > title
                if text:
                    full_text = text
                elif description:
                    full_text = description
                elif title:
                    full_text = title
                else:
                    # 모든 텍스트 필드가 비어있으면 기본 점수 반환
                    logger.debug(f"ID={item.get('id', 'unknown')}: 모든 텍스트 필드가 비어있음")
                    return 0.0
            
            # 모델이 로드되었는지 확인
            if self.tokenizer is None or self.model is None:
                logger.warning("리랭커 모델이 로드되지 않음")
                return 0.5
                
            # 문맥 정보 추가 (임베딩에 사용되는 필드들만)
            context_parts = []
            if title:
                context_parts.append(f"제목: {title}")
            if page_num:
                context_parts.append(f"페이지: {page_num}")
            if file_path:
                # 파일명만 추출
                import os
                file_name = os.path.basename(file_path)
                context_parts.append(f"파일: {file_name}")
            
            # 최종 텍스트 구성
            if context_parts:
                full_text = full_text + "\n\n" + "\n".join(context_parts)
            
            logger.debug(f"최종 full_text: '{full_text[:100]}...'")
            
            # full_text가 비어있는 경우 기본값 설정
            if not full_text.strip():
                full_text = "내용 없음"
                logger.warning("캡션과 태그가 모두 비어있어 기본 텍스트를 사용합니다.")
                
            logger.debug(f"최종 full_text: '{full_text[:50]}...'")
            
            # 키워드 매칭 점수 계산 (실제 사용되는 필드들만 활용)
            keyword_score = 0.0
            query_terms = set(query.lower().split())
            
            # 텍스트 필드에서 키워드 추출
            text_terms = set(full_text.lower().split()) if full_text else set()
            
            # 제목에서 키워드 추출 (추가 가중치 부여)
            title_terms = set(title.lower().split()) if title else set()
            
            # 키워드 매칭 계산
            text_matches = sum(1 for term in query_terms if term in text_terms)
            title_matches = sum(1 for term in query_terms if term in title_terms)
            
            if len(query_terms) > 0:
                # 제목 매칭에 더 높은 가중치 부여
                keyword_score = (text_matches + title_matches * 1.5) / len(query_terms)
                keyword_score = min(keyword_score, 1.0)  # 최대값 1.0으로 제한
                
            # 입력 데이터 준비
            inputs = self.tokenizer(
                query,
                full_text,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=512
            )
            
            # 입력을 디바이스로 이동 (정수형 텐서는 dtype 변환 안함)
            inputs = {k: v.to(device=self.device) for k, v in inputs.items()}
            
            # 디버깅을 위한 입력 텐서 dtype 로깅
            for k, v in inputs.items():
                if v.dtype != torch.int64:  # 정수형 텐서는 무시
                    logger.debug(f"입력 텐서 {k} dtype: {v.dtype}")
            
            # 모델 추론 - dtype 불일치 오류 처리 추가
            try:
                with torch.no_grad():
                    # 자동 혼합 정밀도 사용 (GPU에서만)
                    with torch.amp.autocast(device_type='cuda' if self.device.type == 'cuda' else 'cpu'):
                        outputs = self.model(**inputs)
                    logits = outputs.logits
            except RuntimeError as e:
                if "expected mat1 and mat2 to have the same dtype" in str(e):
                    logger.warning(f"dtype 불일치 오류 발생, 명시적 변환 시도: {e}")
                    # 모든 텐서를 float32로 강제 변환하여 재시도
                    float_inputs = {k: v.to(dtype=torch.float32) if v.dtype in [torch.float16, torch.bfloat16] else v 
                                   for k, v in inputs.items()}
                    with torch.no_grad():
                        outputs = self.model(**float_inputs)
                    logits = outputs.logits
                    logger.info("float32 강제 변환으로 성공적으로 처리됨")
                else:
                    raise
                
            # 순수 리랭커 모델 점수만 사용 (키워드 매칭 제거)
            if logits.shape[1] > 1:  # 두 개 이상의 클래스가 있는 경우
                # 두 번째 클래스(유사함)의 logit 값 사용
                raw_score = logits[0][1].item()
                logger.info(f"Raw reranker model score: {raw_score:.4f} (from multi-class model)")
            else:  # 하나의 클래스만 있는 경우
                # 원본 logit 값 사용
                raw_score = logits[0][0].item()
                logger.info(f"Raw reranker model score: {raw_score:.4f} (from single-class model)")
            
            # text_reranker_improved_2.py 방식 적용
            # logits를 float32로 변환
            logits_float = logits.to(dtype=torch.float32)
            
            # 'relevant' 로짓에 가중치(1.2)를 부여하여 점수를 상향 조정
            if logits.shape[1] > 1:
                # [batch_size, 2] 형태 - [관련없음, 관련있음]
                score = torch.sigmoid((logits_float[0, 1] * 1.2 - logits_float[0, 0]) * 1.0).item()
            else:
                # 단일 클래스인 경우 단순 시그모이드 적용
                score = torch.sigmoid(logits_float[0, 0] * 1.2).item()
            
            logger.info(f"Raw score: {raw_score:.4f}, Improved score: {score:.4f}")
                
            # 정규화된 점수 반환
            return score
                
        except Exception as e:
            logging.error(f"유사도 계산 오류: {str(e)}")
            return 0.05

    @torch.no_grad()
    def compute_similarity_batch(self, query: str, passages: List[str], cancellation_event: Optional[threading.Event] = None) -> List[float]:
        """배치로 여러 문서의 유사도를 계산합니다."""
        if self.tokenizer is None or self.model is None:
            logger.error("모델이 로드되지 않았습니다.")
            return [0.0] * len(passages)
        
        all_scores = []
        
        for i in range(0, len(passages), self.batch_size):
            # 배치 처리 전 취소 확인
            if cancellation_event and cancellation_event.is_set():
                raise InterruptedError("Image reranking operation cancelled during batch processing")

            batch_passages = passages[i:i + self.batch_size]
            
            # 토큰화는 한 번만 수행
            try:
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
                        # attention_mask는 정수형으로 유지
                        inputs[k] = v.to(device=self.device)
                    else:
                        # 기타 텐서는 디바이스로 이동
                        inputs[k] = v.to(self.device)
                
                with torch.amp.autocast(device_type='cuda' if self.device.type == 'cuda' else 'cpu'):
                    outputs = self.model(**inputs, return_dict=True)
                    
                    # logits를 float32로 변환
                    logits = outputs.logits.to(dtype=torch.float32)
                    
                    # 'relevant' 로짓에 가중치(1.2)를 부여하여 점수를 상향 조정
                    if logits.shape[1] > 1:
                        scores = torch.sigmoid((logits[:, 1] * 1.2 - logits[:, 0]) * 1.0)
                    else:
                        # 단일 클래스인 경우 단순 시그모이드 적용
                        scores = torch.sigmoid(logits[:, 0] * 1.2)
                    
                    all_scores.extend(scores.tolist())
                
            except RuntimeError as e:
                if "expected mat1 and mat2 to have the same dtype" in str(e):
                    logger.warning(f"dtype 불일치 오류 발생: {e}")
                    
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
                    
                    # float32로 변환된 입력으로 모델 실행 (autocast 비활성화)
                    with torch.amp.autocast(device_type='cuda' if self.device.type == 'cuda' else 'cpu', enabled=False):
                        outputs = self.model(**float_inputs, return_dict=True)
                    
                    # 오류 복구 시에도 올바른 점수 처리
                    logits = outputs.logits.to(dtype=torch.float32)
                    
                    # 오류 복구 시에도 동일한 가중치 로직을 적용
                    if logits.shape[1] > 1:
                        scores = torch.sigmoid((logits[:, 1] * 1.2 - logits[:, 0]) * 1.0)
                    else:
                        scores = torch.sigmoid(logits[:, 0] * 1.2)
                    
                    all_scores.extend(scores.tolist())
                    logger.info("float32 강제 변환으로 성공적으로 처리됨")
                else:
                    logger.error(f"배치 처리 오류 (batch {i//self.batch_size}): {e}")
                    all_scores.extend([0.0] * len(batch_passages))
        
        return all_scores
        
    def rerank(
        self,
        query: str,
        results: List[Dict[str, Any]],
        top_k: Optional[int] = None,
        min_score: float = None,
        cancellation_event: Optional[threading.Event] = None
    ) -> List[Dict[str, Any]]:

        """
        검색 결과를 재정렬합니다.
        
        Args:
            query: 사용자 쿼리 문자열
            results: 초기 검색 결과 목록 (각 항목은 'text' 필드를 포함해야 함)
            top_k: 반환할 상위 결과 수 (None인 경우 모든 결과 반환)
            min_score: 최소 점수 임계값 (None인 경우 config에서 가져옴)
            
        Returns:
            List[Dict[str, Any]]: 재정렬된 결과 목록
        """
        # 시작 시간 기록 및 디버깅 정보 출력
        start_time = time.time()
        logger.info(f"이미지 리랭커 호출: 쿼리='{query}', 결과 수={len(results)}, top_k={top_k}, 모델 dtype={self.torch_dtype}")
        
        if not results:
            logger.info("리랭킹할 결과가 없습니다.")
            return []
        
        # 모델이 로드되었는지 확인
        if self.tokenizer is None or self.model is None:
            logger.warning(f"리랭커 모델이 로드되지 않았습니다. 원본 결과를 그대로 반환합니다.")
            return results[:top_k] if top_k else results
        
        # config에서 설정값 가져오기
        config = RAGConfig()
        if min_score is None:
            min_score = getattr(config, 'IMAGE_RERANK_SCORE_THRESHOLD', 0.7)
            
        # 텍스트 리랭커와 일관성을 위해 통계 추적 추가
        if not hasattr(self, 'stats'):
            self.stats = {
                'total_queries': 0,
                'total_documents': 0,
                'total_time': 0.0
            }
        
        self.stats['total_queries'] += 1
        self.stats['total_documents'] += len(results)
        
        # 텍스트 리랭커와 동일한 방식으로 배치 처리 적용
        passages = []
        for result in results:
            text = result.get('text', '')
            title = result.get('title', '')
            description = result.get('description', '')
            page_num = result.get('page_num', '')
            file_path = result.get('file_path', '') or result.get('image_path', '')
            
            # 텍스트 우선순위로 주요 컨텐츠 결정
            main_content = ''
            if text:
                main_content = text
            elif description:
                main_content = description
            elif title:
                main_content = title
            else:
                main_content = "" # 비어있는 경우 빈 문자열 사용
            
            # 문맥 정보 추가 (임베딩에 사용되는 필드들만)
            context_parts = []
            if title and title != main_content:
                context_parts.append(f"제목: {title}")
            if page_num:
                context_parts.append(f"페이지: {page_num}")
            if file_path:
                # 파일명만 추출
                file_name = os.path.basename(file_path)
                context_parts.append(f"파일: {file_name}")
            
            # 최종 텍스트 구성
            if context_parts and main_content:
                full_text = main_content + "\n\n" + "\n".join(context_parts)
            else:
                full_text = main_content
            
            # full_text가 비어있는 경우 기본값 설정
            if not full_text.strip():
                full_text = "내용 없음"
                logger.debug(f"ID={result.get('id', 'unknown')}: 주요 컨텐츠가 비어있어 기본 텍스트 사용")
            
            passages.append(full_text)
        
        # 배치 처리로 점수 계산
        try:
            logger.info(f"리랭킹 점수 계산 시작: {len(passages)}개 문서")
            scores = self.compute_similarity_batch(query, passages, cancellation_event=cancellation_event)
            logger.info(f"리랭킹 점수 계산 완료: {len(scores)}개 점수")
        except Exception as e:
            logger.error(f"리랭킹 점수 계산 중 오류 발생: {e}")
            # 오류 발생 시 원래 점수 유지
            scores = [result.get('score', 0.0) for result in results]
            logger.warning("오류로 인해 원래 점수를 유지합니다.")
        
        # 점수 업데이트 및 float32로 명시적 변환하여 일관성 유지
        reranked_results = []
        for result, score in zip(results, scores):
            result_with_score = result.copy()
            result_with_score['original_score'] = result.get('score', 0.0)
            
            # 점수를 명시적으로 Python float로 변환하여 dtype 문제 방지
            if isinstance(score, (list, tuple)):
                score_value = float(score[0]) if len(score) > 0 else 0.0
            else:
                score_value = float(score)
                
            result_with_score['rerank_score'] = score_value
            result_with_score['score'] = score_value
            result_with_score['reranked'] = True
            reranked_results.append(result_with_score)
        
        # 점수에 따라 결과 정렬
        reranked_results.sort(key=lambda x: x.get('score', 0.0), reverse=True)
        
        # 최소 점수 필터링 적용
        if min_score > 0:
            filtered_results = [r for r in reranked_results if r.get('score', 0.0) >= min_score]
            logger.info(f"최소 점수 {min_score} 필터링 적용: {len(reranked_results)} -> {len(filtered_results)}개 결과")
            reranked_results = filtered_results
        
        # top_k가 지정된 경우 상위 결과만 반환
        if top_k is not None and top_k > 0:
            reranked_results = reranked_results[:top_k]
        
        # 통계 업데이트
        elapsed = time.time() - start_time
        self.stats['total_time'] += elapsed
        
        logger.info(f"쿼리 '{query}'에 대한 재정렬 완료, 결과 수: {len(reranked_results)}, 소요 시간: {elapsed:.2f}초")
        return reranked_results

# 파이프라인 수준에서 메모리 관리를 하기 때문에 이 함수는 삭제함

if __name__ == "__main__":
    # 리랭커 테스트 코드
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    reranker = RAGReranker()
    query = "해변 휴양지"
    items = [
        {"caption": "아름다운 해변과 파도, 석양이 비치는 모래사장", "tags": ["해변", "바다", "석양"]},
        {"caption": "도시의 고층 빌딩들과 교통체증", "tags": ["도시", "빌딩", "교통"]},
        {"caption": "열대 리조트의 수영장과 야자수", "tags": ["리조트", "수영장", "휴양지"]}
    ]
    
    for item in items:
        score = reranker.compute_similarity(query, item)
        print(f"쿼리: '{query}', 아이템: '{item['caption']}', 점수: {score:.4f}")
