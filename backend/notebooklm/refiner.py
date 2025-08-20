#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
RAG 시스템 정제기 - 최종 답변을 사용자에게 적합하게 다듬습니다.
Qwen3-1.7B 전용 모델 사용 (최적화됨)
"""

import os
import json
import logging
import time
import threading
import torch
import importlib
import sys
from typing import List, Dict, Any, Optional
from transformers import AutoModelForCausalLM, AutoTokenizer

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
    Qwen3-1.7B 전용 모델을 사용하여 답변을 정제합니다.
    (즉시 로딩)
    """
    
    def __init__(self, generator, config: RAGConfig = None):
        """
        정제기 초기화 (모델 즉시 로딩)
        
        Args:
            generator: Generator 인스턴스 (디바이스 정보만 참조)
            config: RAGConfig 인스턴스
        """
        if config is None:
            config = RAGConfig()
        
        self.config = config
        self.generator = generator  # 디바이스 정보 참조용
        
        # Refiner 전용 모델 설정
        self.refiner_model_name = "Qwen/Qwen3-1.7B"
        self.device = generator.device  # Generator와 같은 디바이스 사용
        self.torch_dtype = generator.torch_dtype
        
        # 모델 즉시 로딩
        self.refiner_model = None
        self.refiner_tokenizer = None
        self.model_loaded_on_gpu = False
        
        self._load_tokenizer()
        self._load_model()
        
        logger.info(f"Refiner 초기화 및 모델 로딩 완료: {self.refiner_model_name}")

    def _load_tokenizer(self):
        """Refiner 전용 토크나이저 로드"""
        try:
            self.refiner_tokenizer = AutoTokenizer.from_pretrained(
                self.refiner_model_name,
                cache_dir=self.config.CACHE_DIR,
                local_files_only=True
            )
            if self.refiner_tokenizer.pad_token_id is None:
                self.refiner_tokenizer.pad_token_id = self.refiner_tokenizer.eos_token_id
            logger.info(f"Refiner 토크나이저 로딩 완료: {self.refiner_model_name}")
        except Exception as e:
            logger.error(f"Refiner 토크나이저 로딩 실패: {e}")
            raise

    def _load_model(self):
        """Refiner 모델을 GPU에 로드"""
        logger.info(f"Refiner 모델을 GPU에 로딩 중: {self.refiner_model_name}")
        start_time = time.time()
        try:
            model_kwargs = {"torch_dtype": self.torch_dtype}
            
            self.refiner_model = AutoModelForCausalLM.from_pretrained(
                self.refiner_model_name,
                cache_dir=self.config.CACHE_DIR,
                local_files_only=True,
                **model_kwargs
            ).to(self.device)
            
            load_time = time.time() - start_time
            logger.info(f"Refiner 모델 GPU 로딩 완료: {self.refiner_model_name} ({load_time:.1f}초)")
        except Exception as e:
            logger.error(f"Refiner 모델 GPU 로딩 실패: {e}")
            self.refiner_model = None
            raise

    def refine_answer(self, query: str, answer: str) -> str:
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
            refined_answer = self._generate_with_refiner_model(system_prompt, user_prompt)
            
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
        """중복된 문장 제거 (마크다운 테이블 보존)"""
        if not text:
            return text
        
        # 마크다운 테이블 보존
        processed_text, tables, table_tokens = self._preserve_markdown_tables(text)
        
        # 문장들을 분리
        sentences = []
        current_sentence = ""
        
        # 문장 분리 (테이블 토큰은 그대로 유지)
        for line in processed_text.split('\n'):
            # 테이블 토큰이면 그대로 추가
            if any(token in line for token in table_tokens):
                if current_sentence:
                    sentences.append(current_sentence.strip())
                    current_sentence = ""
                sentences.append(line)
                continue
                
            if not line.strip():
                if current_sentence:
                    sentences.append(current_sentence.strip())
                    current_sentence = ""
                sentences.append("")
            else:
                if line.strip().endswith(('.', '!', '?', ':', ';')):
                    current_sentence += line
                    sentences.append(current_sentence.strip())
                    current_sentence = ""
                else:
                    current_sentence += line + " "
        
        if current_sentence:
            sentences.append(current_sentence.strip())
        
        # 중복 문장 제거 (테이블 토큰은 항상 유지)
        seen_sentences = set()
        unique_sentences = []
        
        for sentence in sentences:
            # 테이블 토큰이거나 빈 줄은 그대로 유지
            if not sentence or any(token in sentence for token in table_tokens):
                unique_sentences.append(sentence)
                continue
                
            # 중복 문장 제거
            if sentence.lower() not in seen_sentences:
                seen_sentences.add(sentence.lower())
                unique_sentences.append(sentence)
        
        # 테이블 토큰을 원래 테이블로 복원
        result = '\n'.join(unique_sentences)
        return self._restore_markdown_tables(result, tables, table_tokens)
    
    def _generate_with_refiner_model(self, system_prompt: str, user_prompt: str) -> str:
        """
        Refiner 전용 Qwen3-1.7B 모델을 사용하여 텍스트를 생성합니다.
        
        Args:
            system_prompt: 시스템 프롬프트
            user_prompt: 사용자 프롬프트
            
        Returns:
            생성된 텍스트
        """
        try:
            model = self.refiner_model
            
            # Qwen3 공식 권장 방식: messages 형식으로 구성
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
            
            # apply_chat_template 사용 (enable_thinking=False로 설정)
            text = self.refiner_tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False  # 중요: thinking 모드 비활성화
            )
            
            logger.info(f"Refiner 전용 모델({self.refiner_model_name})로 텍스트 생성 중")
            
            # 토크나이징 및 디바이스 이동
            model_inputs = self.refiner_tokenizer([text], return_tensors="pt").to(self.device)
            
            # Qwen3 공식 권장 파라미터 (non-thinking 모드)
            generation_params = {
                "max_new_tokens": self.config.REFINER_MAX_TOKENS,
                "do_sample": True,  # Qwen3에서는 항상 샘플링 권장
                "temperature": 0.3,  # 공식 권장값
                "pad_token_id": self.refiner_tokenizer.eos_token_id,
                "num_beams": 1,     # 샘플링과 빔서치 동시 사용 불가
            }

            with torch.no_grad():
                generated_ids = model.generate(**model_inputs, **generation_params)
            
            # Qwen3 공식 방식: 입력 길이를 제외한 새로운 토큰만 추출
            output_ids = generated_ids[0][len(model_inputs.input_ids[0]):].tolist()
            
            # 디코딩
            response = self.refiner_tokenizer.decode(output_ids, skip_special_tokens=True)
            
            if not response:
                logger.warning("Refiner가 빈 응답을 생성했습니다.")
                return ""
            

            
            logger.info(f"Refiner 텍스트 생성 완료 - 응답 길이: {len(response)}")
            return response.strip()
            
        except Exception as e:
            logger.error(f"Refiner 모델 텍스트 생성 실패: {str(e)}", exc_info=True)
            raise
    

