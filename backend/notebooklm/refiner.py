#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
RAG 시스템 정제기 - 최종 답변을 사용자에게 적합하게 다듬습니다.
SGLang을 사용하여 로컬에서 모델을 로드하고 추론합니다.
"""

import os
import json
import logging
import time
import threading
import re
import sys
from typing import List, Dict, Any, Optional
import sglang as sgl

# config.py 임포트
from config import RAGConfig

# rag_service의 process_markdown_tables 함수 임포트
def import_process_markdown_tables():
    """
    rag_service.py에서 process_markdown_tables 함수를 동적으로 임포트
    """
    try:
        # 현재 디렉토리에서 상대 경로로 임포트 시도
        sys.path.append(os.path.join(os.path.dirname(__file__), '../services'))
        from rag_service import process_markdown_tables
        return process_markdown_tables
    except ImportError:
        # 임포트 실패 시 로깅
        logging.error("rag_service.py에서 process_markdown_tables 함수를 임포트하는데 실패했습니다.")
        # 임포트 실패 시 None 반환
        return None

# process_markdown_tables 함수 동적 임포트
process_markdown_tables = import_process_markdown_tables()

# 로깅 설정
logger = logging.getLogger(__name__)

class Refiner:
    """
    RAG 시스템 정제기
    SGLang을 사용하여 답변을 정제합니다.
    """
    
    def __init__(self, config: RAGConfig = None):
        """
        정제기 초기화
        
        Args:
            config: RAGConfig 인스턴스
        """
        if config is None:
            config = RAGConfig()
        
        self.config = config
        self.model_name = self.config.REFINER_MODEL
        self.engine = None
        self.model_loaded = False
        
        logger.info(f"Refiner 초기화 완료 (모델은 최초 요청 시 로드): {self.model_name}")

    def _load_model(self):
        """SGLang Engine 초기화"""
        try:
            logger.info(f"Refiner SGLang Engine 초기화 중: {self.model_name}")
            
            # PyTorch를 사용하여 GPU 메모리 정리
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                logger.info("GPU 캐시 메모리 정리 완료")
            
            # Config에서 디바이스 설정 가져오기
            device = self.config.REFINER_DEVICE
            logger.info(f"Refiner SGLang Engine 디바이스 설정: {device}")
            
            # device가 "cuda:N" 형식이면 환경 변수로 설정
            original_cuda_visible = os.environ.get('CUDA_VISIBLE_DEVICES')
            if device != "auto" and device.startswith("cuda:"):
                gpu_id = device.split(":")[1]
                os.environ['CUDA_VISIBLE_DEVICES'] = gpu_id
                logger.info(f"CUDA_VISIBLE_DEVICES 설정: {gpu_id}")
            
            # Engine 클래스를 사용하여 모델 초기화
            mem_fraction = getattr(self.config, 'REFINER_MEM_FRACTION', 0.2)
            try:
                self.engine = sgl.Engine(
                    model_path=self.model_name,
                    mem_fraction_static=mem_fraction,
                    disable_cuda_graph=True,
                    trust_remote_code=True,
                    dtype="auto"
                )
            finally:
                # 환경 변수 복원
                if original_cuda_visible is not None:
                    os.environ['CUDA_VISIBLE_DEVICES'] = original_cuda_visible
                elif 'CUDA_VISIBLE_DEVICES' in os.environ:
                    del os.environ['CUDA_VISIBLE_DEVICES']
            
            self.model_loaded = True
            logger.info("Refiner SGLang Engine 초기화 완료")
        except Exception as e:
            logger.error(f"Refiner SGLang Engine 초기화 실패: {e}")
            self.model_loaded = False
            raise
    
    def _ensure_model_loaded(self):
        """모델이 로드되지 않았다면 로드합니다."""
        if not self.model_loaded or self.engine is None:
            self._load_model()
    
    def cleanup_model(self):
        """SGLang 엔진과 GPU 리소스를 정리"""
        try:
            if self.engine is not None:
                shutdown = getattr(self.engine, "shutdown", None)
                if callable(shutdown):
                    shutdown()
                self.engine = None
            self.model_loaded = False

            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                logger.exception("GPU 캐시 정리 중 오류")

            logger.info("Refiner 리소스 정리 완료")
        except Exception as exc:
            logger.error("Refiner cleanup 실패: %s", exc, exc_info=True)

    def refine_answer(self, query: str, answer: str, cancellation_event: Optional[threading.Event] = None) -> str:
        """
        답변 정제
        
        Args:
            query: 사용자 질문
            answer: 원본 답변
            
        Returns:
            정제된 답변
        """
        logger.info(f"Refiner.refine_answer 호출됨 - 원본 답변 길이: {len(answer)}")
        
        # 원본 답변에서 <think> 태그와 내용 제거
        cleaned_answer = self._clean_think_tags(answer)
        
        # 프롬프트 구성
        system_prompt = self.config.REFINER_SYSTEM_PROMPT
        user_prompt = self.config.REFINER_USER_PROMPT_TEMPLATE.format(query=query, answer=cleaned_answer)
        
        # LLM을 통한 정제 수행
        try:
            if cancellation_event and cancellation_event.is_set():
                raise InterruptedError("Operation cancelled before refinement generation")
            
            refined_answer = self._generate_with_refiner_model(system_prompt, user_prompt, cancellation_event=cancellation_event)
            
            # <think> 태그가 있다면 제거하고 실제 답변만 추출
            refined_answer = self._extract_final_answer(refined_answer)
            
            # 중복 문장 제거
            refined_answer = self._remove_duplicated_sentences(refined_answer)
            
            # 마크다운 테이블 처리 - 줄바꿈 문제 해결
            if process_markdown_tables:
                logger.info("마크다운 테이블 처리 적용 중...")
                refined_answer = process_markdown_tables(refined_answer)
            
            logger.info(f"Refiner 답변 정제 완료 - 정제된 답변 길이: {len(refined_answer)}")
            logger.info(f"정제 전 답변 일부: {answer[:50]}...")
            logger.info(f"정제 후 답변 일부: {refined_answer[:50]}...")
            
            # 정제된 답변이 비어있으면 원본 답변 반환
            if not refined_answer.strip():
                logger.warning("정제된 답변이 비어있어서 원본 답변을 반환합니다.")
                return answer
                
            return refined_answer
        except Exception as e:
            logger.error(f"Refiner 답변 정제 실패: {str(e)}")
            return answer  # 실패 시 원본 답변 반환

    def _clean_think_tags(self, text: str) -> str:
        """<think> 태그와 내용 제거"""
        if "<think>" in text and "</think>" in text:
            try:
                text_parts = text.split("<think>", 1)
                think_and_rest = text_parts[1].split("</think>", 1)
                text = text_parts[0].strip() + " " + think_and_rest[1].strip()
                logger.debug(f"<think> 태그 제거 후 텍스트 길이: {len(text)}")
            except IndexError:
                logger.warning("텍스트의 <think> 태그 처리 중 오류 발생")
        elif "<think>" in text:
            try:
                parts = text.split("<think>", 1)
                if "\n\n" in parts[1]:
                    text = parts[0].strip() + " " + parts[1].split("\n\n", 1)[1].strip()
                    logger.debug(f"<think> 태그 제거 후 텍스트 길이: {len(text)}")
            except IndexError:
                logger.warning("텍스트의 <think> 태그 처리 중 오류 발생")
        return text

    def _extract_final_answer(self, text: str) -> str:
        """Qwen3 출력에서 최종 답변만 추출 (thinking 태그 제거)"""
        if "<think>" in text and "</think>" in text:
            try:
                # thinking 내용과 실제 답변 분리
                parts = text.split("</think>")
                if len(parts) > 1:
                    final_answer = parts[1].strip()
                    logger.debug(f"Thinking 태그 제거 후 최종 답변 길이: {len(final_answer)}")
                    return final_answer
            except Exception as e:
                logger.warning(f"Thinking 태그 처리 중 오류: {e}")
        
        # thinking 태그가 없거나 처리 실패 시 원본 반환
        return text
    
    def _preserve_markdown_tables(self, text: str) -> tuple:
        """마크다운 테이블을 보존하기 위해 임시로 대체"""
        import re
        
        # 마크다운 테이블 패턴 (헤더, 구분선, 데이터 행을 포함)
        table_pattern = re.compile(r'(\|[^\n]*\|\s*\n\s*\|[-:\s|]*\|[\s\S]*?(?:\n(?!\|)|$))', re.MULTILINE)
        
        # 테이블을 찾아서 임시 토큰으로 대체
        tables = []
        table_tokens = []
        
        def replace_table(match):
            table_text = match.group(0)
            token = f"__TABLE_TOKEN_{len(tables)}__"
            tables.append(table_text)
            table_tokens.append(token)
            return token
        
        # 테이블을 임시 토큰으로 대체
        processed_text = table_pattern.sub(replace_table, text)
        
        return processed_text, tables, table_tokens
    
    def _restore_markdown_tables(self, text: str, tables: list, table_tokens: list) -> str:
        """임시 토큰을 원래 테이블로 복원"""
        result = text
        for i, token in enumerate(table_tokens):
            result = result.replace(token, tables[i])
        return result
    
    def _remove_duplicated_sentences(self, text: str) -> str:
        """중복된 문장/라인 제거 (마크다운 테이블 보존 + 줄바꿈 유지)"""
        if not text:
            return text

        # 1) 테이블 보존
        processed_text, tables, tokens = self._preserve_markdown_tables(text)

        # 2) 줄 단위 처리
        seen = set()
        unique_lines = []
        for line in processed_text.splitlines():
            if not line.strip():
                unique_lines.append("")  # 빈 줄 그대로 유지
                continue
            if any(token in line for token in tokens):
                unique_lines.append(line)  # 테이블 토큰은 무조건 유지
                continue
            norm = line.strip().lower()
            if norm not in seen:
                seen.add(norm)
                unique_lines.append(line)

        # 3) 다시 합치기
        result = "\n".join(unique_lines)

        # 4) 테이블 복원
        return self._restore_markdown_tables(result, tables, tokens)
    
    def _generate_with_refiner_model(self, system_prompt: str, user_prompt: str, cancellation_event: Optional[threading.Event] = None) -> str:
        """
        SGLang Engine을 사용하여 텍스트를 생성합니다.
        
        Args:
            system_prompt: 시스템 프롬프트
            user_prompt: 사용자 프롬프트
            cancellation_event: 취소 이벤트
            
        Returns:
            생성된 텍스트
        """
        self._ensure_model_loaded()
        
        try:
            logger.info("Refiner SGLang Engine으로 텍스트 생성 시작")
            
            # 취소 확인
            if cancellation_event and cancellation_event.is_set():
                raise InterruptedError("Operation cancelled before refinement generation")
            
            # 채팅 형식 프롬프트 구성
            prompt = f"""<|im_start|>system
{system_prompt}<|im_end|>
<|im_start|>user
{user_prompt}<|im_end|>
<|im_start|>assistant
"""
            
            # 샘플링 파라미터 설정
            sampling_params = {
                "temperature": 0.3,
                "top_p": 0.9,
                "max_new_tokens": self.config.REFINER_MAX_TOKENS,
                "stop": ["<|im_end|>", "</think>"]
            }
            
            # SGLang Engine으로 텍스트 생성
            result = self.engine.generate(prompt=prompt, sampling_params=sampling_params)
            response = result["text"]
            
            # <think> 태그 제거
            response = re.sub(r'<[tT]hink>.*?</[tT]hink>', '', response, flags=re.DOTALL)
            
            # 불필요한 공백/줄바꿈 정리
            response = response.strip()
            
            if not response:
                logger.warning("Refiner가 빈 응답을 생성했습니다.")
                return ""
            
            logger.info(f"Refiner 텍스트 생성 완료 - 응답 길이: {len(response)}")
            return response
            
        except Exception as e:
            logger.error(f"Refiner 텍스트 생성 실패: {str(e)}", exc_info=True)
            raise
