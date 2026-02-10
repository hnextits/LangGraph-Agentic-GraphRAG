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
from transformers import AutoTokenizer, AutoModelForCausalLM

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
        """리랭커 초기화 - 모델을 즉시 로드합니다."""
        config = RAGConfig()
        self.model_name = model_name if model_name else config.RERANKER_MODEL_NAME
        self.ollama_host = ollama_host if ollama_host else config.OLLAMA_API_URL
        
        # 디바이스 설정 - 메모리에 따라 RERANKER_DEVICE 사용
        self.device = torch.device(config.RERANKER_DEVICE if hasattr(config, 'RERANKER_DEVICE') else ('cuda' if torch.cuda.is_available() else 'cpu'))
        logger.info(f"디바이스 설정: {self.device}")
        
        # 배치 처리 관련 설정 (텍스트 리랭커와 일관성 유지)
        self.batch_size = getattr(config, 'RERANKER_BATCH_SIZE', 4)
        self.max_length = getattr(config, 'RERANKER_MAX_LENGTH', 8192)  # Qwen3-Reranker-4B 권장 값
        
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
            
        # SequenceClassification 모델은 logits를 직접 사용하므로 토큰 ID 불필요
            
        logger.info(f"이미지 리랭커 모델 dtype 설정: {self.torch_dtype}")
        
        # 모델 즉시 로드
        self.tokenizer = None
        self.model = None
        self._load_model()
    
    def _load_model(self):
        """모델과 토크나이저를 로드합니다."""
        if self.tokenizer is not None and self.model is not None:
            logger.info("모델이 이미 로드되어 있습니다.")
            return True
        
        config = RAGConfig()
        try:
            logger.info(f"리랭커 모델 로드 중: {self.model_name}")
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.model_name, 
                padding_side='left',  # Qwen3-Reranker 공식 방식
                trust_remote_code=True,
                cache_dir=config.CACHE_DIR, 
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
            
            # CausalLM 모델 로드 (공식 방식)
            logger.info(f"모델 로딩 시작: {self.model_name}")
            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_name,
                cache_dir=config.CACHE_DIR,
                local_files_only=True,
                trust_remote_code=True,
                torch_dtype=torch.bfloat16,
                device_map=self.device  # 직접 디바이스에 로드
            ).eval()  # 평가 모드로 설정
            logger.info(f"모델 로딩 완료: {self.model_name}")
            
            # 모델 파라미터 dtype 및 값 확인
            try:
                first_param = next(self.model.parameters())
                model_dtype = first_param.dtype
                param_mean = first_param.mean().item()
                param_std = first_param.std().item()
                logger.info(f"모델 파라미터 dtype: {model_dtype}")
                logger.info(f"첫 번째 파라미터 통계 - mean: {param_mean:.6f}, std: {param_std:.6f}")
                logger.info(f"모델 총 파라미터 수: {sum(p.numel() for p in self.model.parameters()):,}")
            except Exception as e:
                logger.error(f"모델 파라미터 확인 실패: {e}")
            
            # yes/no 토큰 ID 설정
            self.token_false_id = self.tokenizer.convert_tokens_to_ids("no")
            self.token_true_id = self.tokenizer.convert_tokens_to_ids("yes")
            logger.info(f"토큰 ID - yes: {self.token_true_id}, no: {self.token_false_id}")
            
            # 프롬프트 템플릿 (공식 방식)
            self.prefix = "<|im_start|>system\nJudge whether the Document meets the requirements based on the Query and the Instruct provided. Note that the answer can only be \"yes\" or \"no\".<|im_end|>\n<|im_start|>user\n"
            self.suffix = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
            self.prefix_tokens = self.tokenizer.encode(self.prefix, add_special_tokens=False)
            self.suffix_tokens = self.tokenizer.encode(self.suffix, add_special_tokens=False)
            logger.info(f"Prefix tokens 길이: {len(self.prefix_tokens)}, Suffix tokens 길이: {len(self.suffix_tokens)}")
            
            logger.info(f"CausalLM 모델 로드 완료 - 디바이스: {self.device}")
            
            # 모델 파라미터의 dtype 확인 및 로깅
            param_dtypes = set(p.dtype for p in self.model.parameters())
            logger.info(f"모델 파라미터 dtype: {param_dtypes}")
            
            self.model.eval()
            logger.info(f"리랭커 모델 로드 완료: {self.model_name}")
            return True
        except Exception as e:
            logger.error(f"리랭커 모델 로드 실패: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            self.tokenizer = None
            self.model = None
            return False
    
    def format_instruction(self, instruction: str, query: str, doc: str) -> str:
        """공식 프롬프트 형식"""
        if instruction is None:
            instruction = 'Given a web search query, retrieve relevant passages that answer the query'
        output = "<Instruct>: {instruction}\n<Query>: {query}\n<Document>: {doc}".format(
            instruction=instruction, query=query, doc=doc
        )
        return output
            
    def format_passage(self, doc: Union[Dict[str, Any], str]) -> str:
        """
        문서를 텍스트로 변환합니다 (SequenceClassification 모델용).
        """
        # 문서 텍스트 추출
        if isinstance(doc, str):
            return doc
        
        # 실제 임베딩에 사용되는 필드들만 추출
        text = doc.get('text', '')
        title = doc.get('title', '')
        caption = doc.get('caption', '')
        description = doc.get('description', '')
        
        # 텍스트 우선순위: text > caption > description > title
        if text:
            doc_text = text
        elif caption:
            doc_text = caption
        elif description:
            doc_text = description
        elif title:
            doc_text = title
        else:
            doc_text = ""
        
        # 문맥 정보 추가
        context_parts = []
        if title and title != doc_text:
            context_parts.append(f"Title: {title}")
        if doc.get('file_path'):
            file_name = os.path.basename(doc.get('file_path', ''))
            context_parts.append(f"File: {file_name}")
        
        # 문맥 정보 추가
        if context_parts and doc_text:
            doc_text = doc_text + "\n\n" + "\n".join(context_parts)
        
        return doc_text
    
    def compute_similarity(self, query: str, item: Union[Dict[str, Any], str]) -> float:
        """
        쿼리와 아이템 간의 유사도를 계산합니다 (SequenceClassification 모델 사용).
        """
        try:
            # 모델이 로드되지 않았으면 기본값 반환
            if self.tokenizer is None or self.model is None:
                logger.warning("리랭커 모델이 로드되지 않음")
                return 0.5
            
            # 문서 텍스트 추출
            passage = self.format_passage(item)
            
            # 텍스트가 비어있는 경우 기본값 반환
            if not passage.strip():
                logger.warning("문서 텍스트가 비어있어 기본 점수를 사용합니다.")
                return 0.5
                
            # 토큰화 (query와 passage를 pair로)
            inputs = self.tokenizer(
                query,
                passage,
                padding=True,
                truncation=True,
                max_length=self.max_length,
                return_tensors="pt"
            )
            
            # 입력을 디바이스로 이동
            inputs = {k: v.to(device=self.device) for k, v in inputs.items()}
            
            # 모델 추론 - 점수 계산
            with torch.no_grad():
                with torch.amp.autocast(device_type='cuda' if self.device.type == 'cuda' else 'cpu'):
                    outputs = self.model(**inputs, return_dict=True)
                    
                    # logits는 [batch_size, 2] 형태 - [관련없음, 관련있음]
                    logits = outputs.logits.to(dtype=torch.float32)
                    
                    # 텍스트 리랭커와 동일한 방식으로 점수 계산
                    score = torch.sigmoid((logits[:, 1] * 1.2 - logits[:, 0]) * 1.0).item()
                    
                    # 점수 로깅
                    logger.info(f"이미지 리랭커 점수: {score:.4f} (쿼리: '{query[:30]}...', 문서: '{passage[:50]}...')")
                    
                    return score
                
        except Exception as e:
            logger.error(f"유사도 계산 오류: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return 0.5

    @torch.no_grad()
    def compute_similarity_batch(self, query: str, passages: List[str], cancellation_event: Optional[threading.Event] = None) -> List[float]:
        """배치로 여러 문서의 유사도를 계산합니다 (SequenceClassification 방식)."""
        # 모델이 로드되지 않았으면 기본값 반환
        if self.tokenizer is None or self.model is None:
            logger.error("모델이 로드되지 않았습니다.")
            return [0.5] * len(passages)
        
        # 취소 이벤트 처리
        if cancellation_event and cancellation_event.is_set():
            raise InterruptedError("Image reranking operation cancelled")
        
        all_scores = []
        
        # 배치 단위로 처리
        for i in range(0, len(passages), self.batch_size):
            # 취소 이벤트 확인
            if cancellation_event and cancellation_event.is_set():
                raise InterruptedError("Image reranking operation cancelled")
            
            batch_passages = passages[i:i + self.batch_size]
            batch_size = len(batch_passages)
            
            try:
                # 프롬프트 형식으로 변환 (공식 방식)
                pairs = [self.format_instruction(None, query, passage) for passage in batch_passages]
                
                # 토큰화 (공식 방식)
                inputs = self.tokenizer(
                    pairs,
                    padding=False,
                    truncation='longest_first',
                    return_attention_mask=False,
                    max_length=self.max_length - len(self.prefix_tokens) - len(self.suffix_tokens)
                )
                
                # prefix와 suffix 토큰 추가
                for idx, ele in enumerate(inputs['input_ids']):
                    inputs['input_ids'][idx] = self.prefix_tokens + ele + self.suffix_tokens
                
                # 패딩 적용
                inputs = self.tokenizer.pad(inputs, padding=True, return_tensors="pt", max_length=self.max_length)
                
                # 입력을 디바이스로 이동
                for key in inputs:
                    inputs[key] = inputs[key].to(self.device)
                
                # 모델 추론 (공식 방식)
                with torch.no_grad():
                    outputs = self.model(**inputs)
                    
                    # 마지막 토큰의 logits 사용
                    batch_logits = outputs.logits[:, -1, :]
                    
                    # yes/no 토큰의 logits 추출
                    true_vector = batch_logits[:, self.token_true_id]
                    false_vector = batch_logits[:, self.token_false_id]
                    
                    # 점수 계산
                    batch_logits = torch.stack([false_vector, true_vector], dim=1)
                    batch_logits = torch.nn.functional.log_softmax(batch_logits, dim=1)
                    batch_scores = batch_logits[:, 1].exp().cpu().tolist()
                    all_scores.extend(batch_scores)
                
                # 배치별 점수 분포 로깅
                logger.info(f"배치 {i//self.batch_size + 1} 점수 분포 - 최소: {min(batch_scores):.4f}, 최대: {max(batch_scores):.4f}, 평균: {sum(batch_scores)/len(batch_scores):.4f}")
                
            except Exception as e:
                logger.error(f"배치 처리 중 오류 발생: {str(e)}")
                import traceback
                logger.error(traceback.format_exc())
                # 오류 발생 시 기본 점수 사용
                logger.warning(f"오류로 인해 배치 {i//self.batch_size + 1}의 {batch_size}개 문서에 기본 점수 0.5 할당")
                all_scores.extend([0.5] * batch_size)
        
        # 전체 점수 분포 로깅
        if all_scores:
            logger.info(f"배치 처리 완료: {len(passages)}개 문서, {len(all_scores)}개 점수")
            logger.info(f"전체 점수 분포 - 최소: {min(all_scores):.4f}, 최대: {max(all_scores):.4f}, 평균: {sum(all_scores)/len(all_scores):.4f}")
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
        
        # 모델이 로드되지 않았으면 원본 결과 반환
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
            if score is None:
                score_value = 0.0
            elif isinstance(score, (list, tuple)):
                score_value = float(score[0]) if len(score) > 0 else 0.0
            else:
                try:
                    score_value = float(score)
                except (TypeError, ValueError):
                    score_value = 0.0
                
            result_with_score['rerank_score'] = score_value
            result_with_score['score'] = score_value
            result_with_score['reranked'] = True
            # image_base64 필드가 누락되지 않도록 보장
            if 'image_base64' not in result_with_score and 'image_base64' in result:
                result_with_score['image_base64'] = result['image_base64']
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
